"""Toorfailidest -> puhastatud Parquet failid veebilehe jaoks.

Kogu ehitus on olekuta (stateless): iga käivitus ehitab kõik nullist.
See on teadlik valik: RIK uuendab igakuiselt ka varasemate aastate faile
(hilinenud ja parandatud aruanded), nii et inkrementaalne laadimine tooks
kaasa topeltridu ja käsitööd. Andmemahud on piisavalt väikesed (mõni minut).
"""
from __future__ import annotations

import codecs
import csv
import json
import logging
import re
import unicodedata
import zipfile
from pathlib import Path

import duckdb

from .config import (COLS, COMPILED_ELEMENT_MAP, CANONICAL_FIELDS, COST_FIELDS, PARQUET_ROW_GROUP,
                     PREFER_CONSOLIDATED, PEER_LEVELS, PEER_MIN_N, PEER_MIN_REVENUE, PEER_METRICS)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- abifunktsioonid
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def map_element(name: str) -> str | None:
    key = norm(name)
    for canon, patterns in COMPILED_ELEMENT_MAP:
        if any(p.search(key) for p in patterns):
            return canon
    return None


def prepare_csv(path: Path, workdir: Path) -> Path:
    """Pakib zip-i lahti ja tagab, et CSV on UTF-8. Tagastab CSV tee."""
    workdir.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            members = [m for m in z.infolist() if m.filename.lower().endswith(".csv")]
            if not members:
                raise RuntimeError(f"{path.name}: zip-is pole CSV faili")
            m = max(members, key=lambda x: x.file_size)
            out = workdir / (path.stem + ".csv")
            with z.open(m) as src, open(out, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            path = out
    # kodeeringu kontroll: kui pole UTF-8, eeldame Windows-1257 (Balti)
    dec = codecs.getincrementaldecoder("utf-8")()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 22):
                dec.decode(chunk)
            dec.decode(b"", final=True)
        return path
    except UnicodeDecodeError:
        out = workdir / (path.stem + ".utf8.csv")
        log.info("%s pole UTF-8, teisendan cp1257 -> UTF-8", path.name)
        with open(path, "r", encoding="cp1257", newline="") as src, \
             open(out, "w", encoding="utf-8", newline="") as dst:
            while chunk := src.read(1 << 22):
                dst.write(chunk)
        return out


def sniff(path: Path) -> tuple[str, list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        first = f.readline()
    delim = max([";", ",", "\t", "|"], key=first.count)
    header = next(csv.reader([first], delimiter=delim))
    return delim, [h.strip() for h in header]


def resolve(header: list[str], spec: dict, kind: str, fname: str) -> dict[str, str | None]:
    normed = {norm(h): h for h in header}
    out = {}
    for canon, rule in spec.items():
        hit = next((normed[c] for c in rule.get("exact", []) if c in normed), None)
        if hit is None:
            for frag in rule.get("contains", []):
                hit = next((orig for n, orig in normed.items() if frag in n), None)
                if hit:
                    break
        if hit is None and rule.get("required"):
            raise RuntimeError(
                f"{fname} ({kind}): kohustuslikku veergu '{canon}' ei leitud.\n"
                f"  Faili päised: {header}\n  Lisa sobiv nimi pipeline/config.py COLS['{kind}']['{canon}'].")
        out[canon] = hit
    log.info("%s veerud: %s", fname, {k: v for k, v in out.items() if v})
    if any(v is None for v in out.values()):
        log.info("%s kõik päised: %s", fname, header)
    return out


def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_TAX_METRICS = [("riiklikud", "riiklik"), ("toojou", "toojou"), ("kaive", "kaive"), ("tootajad", "tootaja")]


def load_emta(con, path: Path, rank: int, append: bool):
    """EMTA fail kas pikas (rida = kvartal) või laias (rida = aasta, veerud '… I kv' … '… IV kv') vormis."""
    delim, header = sniff(path)
    spec = {k: v for k, v in COLS["emta"].items() if k not in dict(_TAX_METRICS)}
    m = resolve(header, spec, "emta", path.name)
    wide: dict[int, dict[str, str]] = {}
    for h in header:
        n = norm(h)
        qm = re.search(r"(?:^|_)(iv|iii|ii|i|[1-4])_?kv(?:artal)?$", n)
        if not qm:
            continue
        qn = _ROMAN.get(qm.group(1)) or int(qm.group(1))
        for canon, frag in _TAX_METRICS:
            if frag in n:
                wide.setdefault(qn, {})[canon] = h
    src = (f"read_csv({repr(str(path))}, delim={repr(delim)}, header=true, all_varchar=true, "
           f"quote='\"', escape='\"', null_padding=true, ignore_errors=true, sample_size=-1)")
    base = ", ".join(f"{q(c)} AS {k}" if c else f"NULL::VARCHAR AS {k}" for k, c in m.items() if k not in ("kvartal",))
    if wide:
        log.info("%s: lai vorming, kvartalid %s", path.name, sorted(wide))
        parts = []
        for qn, cols in sorted(wide.items()):
            mets = ", ".join(f"{q(cols[c])} AS {c}" if c in cols else f"NULL::VARCHAR AS {c}" for c, _ in _TAX_METRICS)
            parts.append(f"SELECT {base}, '{qn}' AS kvartal, {mets}, {rank}::INTEGER AS allika_jrk FROM {src}")
        sql = " UNION ALL ".join(parts)
    else:
        full = resolve(header, {**spec, **{c: COLS["emta"][c] for c, _ in _TAX_METRICS}}, "emta", path.name)
        mets = ", ".join(f"{q(full[c])} AS {c}" if full[c] else f"NULL::VARCHAR AS {c}" for c, _ in _TAX_METRICS)
        kv_ = f"{q(m['kvartal'])}" if m.get("kvartal") else "NULL::VARCHAR"
        sql = f"SELECT {base}, {kv_} AS kvartal, {mets}, {rank}::INTEGER AS allika_jrk FROM {src}"
    verb = "INSERT INTO src_tax BY NAME" if append else "CREATE OR REPLACE TABLE src_tax AS"
    con.execute(f"{verb} {sql}")


def load_csv(con, path: Path, kind: str, table: str, extra_cols: dict | None = None, append=False):
    delim, header = sniff(path)
    m = resolve(header, COLS[kind], kind, path.name)
    sel = ", ".join(f"{q(src)} AS {canon}" if src else f"NULL::VARCHAR AS {canon}" for canon, src in m.items())
    for k, v in (extra_cols or {}).items():
        sel += f", {v} AS {k}"
    src = (f"read_csv({repr(str(path))}, delim={repr(delim)}, header=true, all_varchar=true, "
           f"quote='\"', escape='\"', null_padding=true, ignore_errors=true, sample_size=-1)")
    verb = f"INSERT INTO {table}" if append else f"CREATE OR REPLACE TABLE {table} AS"
    con.execute(f"{verb} SELECT {sel} FROM {src}")
    return m


MACROS = r"""
CREATE OR REPLACE MACRO clean(x) AS NULLIF(trim(x), '');
CREATE OR REPLACE MACRO numclean(x) AS regexp_replace(coalesce(x, ''), '[\s\x{00A0}€]', '', 'g');
CREATE OR REPLACE MACRO numparse(v) AS TRY_CAST(CASE
     WHEN v = '' THEN NULL
     WHEN regexp_matches(v, '^-?\d{1,3}(\.\d{3})+(,\d+)?$') THEN replace(replace(v, '.', ''), ',', '.')
     WHEN regexp_matches(v, '^-?\d{1,3}(,\d{3})+(\.\d+)?$') THEN replace(v, ',', '')
     ELSE replace(v, ',', '.') END AS DOUBLE);
CREATE OR REPLACE MACRO num(x) AS numparse(numclean(x));
CREATE OR REPLACE MACRO dt(x) AS COALESCE(
  TRY_STRPTIME(left(trim(x), 10), '%d.%m.%Y'),
  TRY_STRPTIME(left(trim(x), 10), '%Y-%m-%d'),
  TRY_STRPTIME(left(trim(x), 10), '%d/%m/%Y'))::DATE;
CREATE OR REPLACE MACRO div(a, b) AS CASE WHEN b IS NULL OR b = 0 THEN NULL ELSE a / b END;
CREATE OR REPLACE MACRO kv(x) AS CASE upper(regexp_extract(coalesce(x, ''), '(IV|III|II|I|[1-4])', 1))
  WHEN 'I' THEN 1 WHEN 'II' THEN 2 WHEN 'III' THEN 3 WHEN 'IV' THEN 4
  ELSE TRY_CAST(regexp_extract(coalesce(x, ''), '([1-4])', 1) AS INTEGER) END;
CREATE OR REPLACE MACRO kood(x) AS regexp_replace(trim(x), '\.0$', '');
"""


# ---------------------------------------------------------------- põhiloogika
def build(files: dict[str, list[dict]], raw_dir: Path, out_dir: Path) -> dict:
    """files: {allika_võti: [{filename, year?, ...}]} – failid asuvad raw_dir-is."""
    work = raw_dir / "_extracted"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute(MACROS)
    stats: dict = {}

    def csvpath(item):
        return prepare_csv(raw_dir / item["filename"], work)

    # 1) Registri lihtandmed --------------------------------------------------
    load_csv(con, csvpath(files["rik_lihtandmed"][0]), "lihtandmed", "src_reg")
    con.execute("""
      CREATE TABLE reg AS SELECT kood(kood) AS kood, any_value(clean(nimi)) AS nimi,
        any_value(clean(vorm)) AS vorm, any_value(clean(staatus)) AS staatus, any_value(clean(kmkr)) AS kmkr,
        any_value(dt(esmakanne)) AS esmakanne, any_value(clean(aadress)) AS aadress
      FROM src_reg WHERE clean(kood) IS NOT NULL GROUP BY 1""")

    # 2) Aruannete üldandmed ---------------------------------------------------
    load_csv(con, csvpath(files["rik_yldandmed"][0]), "yldandmed", "src_rep")
    con.execute("""
      CREATE TABLE rep AS SELECT clean(report_id) AS report_id, kood(kood) AS kood, clean(nimi) AS nimi,
        TRY_CAST(left(clean(aasta), 4) AS INTEGER) AS aasta, dt(periood_algus) AS periood_algus,
        dt(periood_lopp) AS periood_lopp, dt(esitatud) AS esitatud, clean(kategooria) AS kategooria,
        clean(audit) AS audit
      FROM src_rep WHERE clean(report_id) IS NOT NULL""")

    # 3) Aruannete elemendid (üks fail aasta kohta) -----------------------------
    first = True
    for item in sorted(files["rik_elemendid"], key=lambda x: x.get("year", 0)):
        load_csv(con, csvpath(item), "elemendid", "src_el",
                 extra_cols={"faili_aasta": f"{int(item.get('year') or 0)}::INTEGER"}, append=not first)
        first = False
    elements = con.execute(
        "SELECT clean(element) e, count(*) n FROM src_el GROUP BY 1 ORDER BY 2 DESC").fetchall()
    mapping = [(e, map_element(e)) for e, _ in elements if e]
    con.execute("CREATE TABLE elmap (element VARCHAR, canon VARCHAR)")
    con.executemany("INSERT INTO elmap VALUES (?, ?)", [m for m in mapping if m[1]])
    freq = dict(elements)
    stats["kaardistatud_elemendid"] = {e: c for e, c in mapping if c}
    stats["kaardistamata_elemendid"] = [{"element": e, "ridu": freq[e]} for e, c in mapping if not c][:60]
    missing = sorted(set(CANONICAL_FIELDS) - {c for _, c in mapping if c})
    if missing:
        log.warning("Ükski element ei kaardistunud väljadele: %s", missing)
        log.warning("Kaardistamata elemendid (sagedasemad): %s",
                    [e for e, c in mapping if not c][:40])
    stats["puuduvad_valjad"] = missing

    pref = "TRUE" if PREFER_CONSOLIDATED else "FALSE"
    con.execute(f"""
      CREATE TABLE facts AS
      SELECT report_id, canon, v, faili_aasta FROM (
        SELECT clean(s.report_id) AS report_id, m.canon, num(s.vaartus) AS v, s.faili_aasta,
          ROW_NUMBER() OVER (PARTITION BY clean(s.report_id), m.canon ORDER BY
            (lower(coalesce(s.konsolideeritud, '')) IN ('true','1','jah','yes','t','j')) = {pref} DESC,
            num(s.vaartus) IS NULL) AS rn
        FROM src_el s JOIN elmap m ON clean(s.element) = m.element)
      WHERE rn = 1""")
    pivot = ",\n        ".join(f"max(v) FILTER (WHERE canon = '{f}') AS {f}" for f in CANONICAL_FIELDS)
    con.execute(f"""
      CREATE TABLE wide AS SELECT report_id, max(faili_aasta) AS faili_aasta,
        {pivot}
      FROM facts GROUP BY report_id""")

    # 4) Üks aruanne ettevõtte ja aasta kohta (viimati esitatud võidab) ---------
    con.execute("""
      CREATE TABLE fin_base AS SELECT * EXCLUDE (rn) FROM (
        SELECT r.kood, COALESCE(r.aasta, year(r.periood_lopp), NULLIF(w.faili_aasta, 0)) AS aasta,
          r.report_id, r.periood_algus, r.periood_lopp, r.esitatud, r.kategooria, r.audit, w.* EXCLUDE (report_id, faili_aasta),
          ROW_NUMBER() OVER (PARTITION BY r.kood, COALESCE(r.aasta, year(r.periood_lopp), NULLIF(w.faili_aasta, 0))
                             ORDER BY r.esitatud DESC NULLS LAST, TRY_CAST(r.report_id AS BIGINT) DESC NULLS LAST, r.report_id DESC) AS rn
        FROM wide w JOIN rep r USING (report_id)
        WHERE r.kood IS NOT NULL)
      WHERE rn = 1 AND aasta IS NOT NULL""")
    stats["aruandeid"] = con.execute("SELECT count(*) FROM fin_base").fetchone()[0]

    # 4b) Põhitegevusala aruandest (EMTAK müügitulu jaotus): märgitud põhitegevus, muidu suurim müügitulu
    load_csv(con, csvpath(files["rik_emtak"][0]), "emtak", "src_emtak")
    con.execute("""
      CREATE TABLE rep_emtak AS SELECT report_id, emtak_kood, emtak_nimetus FROM (
        SELECT clean(report_id) AS report_id, regexp_replace(clean(emtak), '[^0-9]', '', 'g') AS emtak_kood,
          clean(nimetus) AS emtak_nimetus,
          ROW_NUMBER() OVER (PARTITION BY clean(report_id) ORDER BY
            lower(coalesce(pohi, '')) IN ('true','1','jah','yes','t','j') DESC, num(summa) DESC NULLS LAST) AS rn
        FROM src_emtak WHERE clean(emtak) IS NOT NULL)
      WHERE rn = 1 AND emtak_kood <> ''""")
    con.execute("""CREATE OR REPLACE TABLE fin_base AS
      SELECT f.*, e.emtak_kood, e.emtak_nimetus FROM fin_base f LEFT JOIN rep_emtak e USING (report_id)""")
    stats["emtak_kaetus"] = con.execute(
        "SELECT round(avg((emtak_kood IS NOT NULL)::INT), 3) FROM fin_base").fetchone()[0]

    # 5) EMTA tasutud maksud ----------------------------------------------------
    first = True
    for rank, key in enumerate(["emta_varasem", "emta_jooksev"]):
        for item in files.get(key, []):
            load_emta(con, csvpath(item), rank, append=not first)
            first = False
    # tühjad kvartalid (nt jooksva aasta veel avaldamata kvartalid laias vormingus) välja
    con.execute("""DELETE FROM src_tax WHERE clean(riiklikud) IS NULL AND clean(toojou) IS NULL
                   AND clean(kaive) IS NULL AND clean(tootajad) IS NULL""")
    con.execute("""
      CREATE TABLE tax_q AS SELECT * EXCLUDE (rn) FROM (
        SELECT kood(kood) AS kood,
          COALESCE(TRY_CAST(left(clean(aasta), 4) AS INTEGER),
                   TRY_CAST(regexp_extract(periood, '(\\d{4})', 1) AS INTEGER)) AS aasta,
          COALESCE(kv(kvartal), kv(regexp_replace(coalesce(periood, ''), '\\d{4}', ''))) AS kvartal,
          clean(nimi) AS nimi, clean(liik) AS liik, clean(emtak) AS emtak, clean(maakond) AS maakond,
          clean(kmkr) AS kmkr, num(riiklikud) AS riiklikud_maksud, num(toojou) AS toojoumaksud,
          num(kaive) AS kaive, num(tootajad) AS tootajad,
          ROW_NUMBER() OVER (PARTITION BY kood(kood),
             COALESCE(TRY_CAST(left(clean(aasta), 4) AS INTEGER), TRY_CAST(regexp_extract(periood, '(\\d{4})', 1) AS INTEGER)),
             COALESCE(kv(kvartal), kv(regexp_replace(coalesce(periood, ''), '\\d{4}', '')))
             ORDER BY allika_jrk DESC) AS rn
        FROM src_tax WHERE clean(kood) IS NOT NULL)
      WHERE rn = 1 AND aasta IS NOT NULL AND kvartal IS NOT NULL""")
    if con.execute("SELECT count(*) FROM tax_q").fetchone()[0] == 0:
        raise RuntimeError("EMTA failidest ei õnnestunud tuvastada aastat/kvartalit – kontrolli COLS['emta'].")
    stats["emta_ridu"] = con.execute("SELECT count(*) FROM tax_q").fetchone()[0]
    stats["emta_viimane_kvartal"] = con.execute(
        "SELECT max(aasta)::VARCHAR || ' Q' || arg_max(kvartal, aasta*10+kvartal)::VARCHAR FROM tax_q").fetchone()[0]
    con.execute("""
      CREATE TABLE tax_y AS SELECT kood, aasta, count(*) AS kvartaleid,
        sum(riiklikud_maksud) AS riiklikud_maksud, sum(toojoumaksud) AS toojoumaksud,
        sum(kaive) AS kaive, avg(tootajad) AS tootajad_kesk
      FROM tax_q GROUP BY 1, 2""")

    # 6) Suhtarvud ---------------------------------------------------------------
    abs_ = {f: (f"abs({f})" if f in COST_FIELDS else f) for f in CANONICAL_FIELDS}
    con.execute(f"""
      CREATE TABLE fin AS
      WITH b AS (
        SELECT *, COALESCE(myygitulu, tulu_ettevotlusest) AS tulu,
          CASE WHEN lyhiajalised_kohustised IS NULL AND pikaajalised_kohustised IS NULL THEN NULL
               ELSE coalesce(lyhiajalised_kohustised, 0) + coalesce(pikaajalised_kohustised, 0) END AS kohustised,
          arikasum + coalesce({abs_['kulum']}, 0) AS ebitda
        FROM fin_base),
      l AS (
        SELECT *,
          lag(aasta) OVER w = aasta - 1 AS eelmine_ok,
          lag(tulu) OVER w AS tulu_eelm, lag(varad) OVER w AS varad_eelm, lag(omakapital) OVER w AS ok_eelm
        FROM b WINDOW w AS (PARTITION BY kood ORDER BY aasta))
      SELECT l.* EXCLUDE (eelmine_ok, tulu_eelm, varad_eelm, ok_eelm),
        CASE WHEN eelmine_ok AND tulu_eelm > 0 THEN tulu / tulu_eelm - 1 END AS tulu_kasv,
        div(ebitda, tulu) AS ebitda_marginaal,
        div(arikasum, tulu) AS arikasumi_marginaal,
        div(puhaskasum, tulu) AS puhaskasumi_marginaal,
        div(puhaskasum, CASE WHEN eelmine_ok AND ok_eelm IS NOT NULL THEN (omakapital + ok_eelm) / 2 ELSE omakapital END) AS roe,
        div(puhaskasum, CASE WHEN eelmine_ok AND varad_eelm IS NOT NULL THEN (varad + varad_eelm) / 2 ELSE varad END) AS roa,
        div(tulu, CASE WHEN eelmine_ok AND varad_eelm IS NOT NULL THEN (varad + varad_eelm) / 2 ELSE varad END) AS varade_kaibevus,
        div(kaibevara, lyhiajalised_kohustised) AS lyhiajaline_maksevoime,
        div(raha, lyhiajalised_kohustised) AS raha_kordaja,
        kaibevara - lyhiajalised_kohustised AS kaibekapital,
        div(omakapital, varad) AS omakapitali_maar,
        div(kohustised, varad) AS volakordaja,
        CASE WHEN omakapital > 0 THEN kohustised / omakapital END AS kohustised_omakapitalile,
        div({abs_['toojoukulud']}, tulu) AS toojoukulu_osakaal,
        div(tulu, tootajate_arv) AS tulu_tootaja_kohta,
        div({abs_['toojoukulud']}, tootajate_arv * 12) AS toojoukulu_tootaja_kohta_kuus,
        div(arikasum + coalesce({abs_['toojoukulud']}, 0) + coalesce({abs_['kulum']}, 0), tootajate_arv)
            AS lisandvaartus_tootaja_kohta,
        CASE WHEN kasum_enne_tm > 0 THEN 1 - puhaskasum / kasum_enne_tm END AS tulumaksu_osakaal,
        (periood_lopp IS NULL OR (month(periood_lopp) = 12 AND day(periood_lopp) = 31)) AS kalendriaasta,
        t.kvartaleid AS emta_kvartaleid, t.riiklikud_maksud AS emta_riiklikud_maksud,
        t.toojoumaksud AS emta_toojoumaksud, t.kaive AS emta_kaive, t.tootajad_kesk AS emta_tootajad_kesk,
        CASE WHEN t.kvartaleid = 4 AND (periood_lopp IS NULL OR strftime(periood_lopp, '%m-%d') = '12-31') THEN div(t.kaive, tulu) END AS emta_kaive_tulule,
        CASE WHEN t.kvartaleid = 4 AND (periood_lopp IS NULL OR strftime(periood_lopp, '%m-%d') = '12-31') THEN div(t.toojoumaksud, {abs_['toojoukulud']}) END AS toojoumaksud_toojoukuludele,
        CASE WHEN t.kvartaleid = 4 AND (periood_lopp IS NULL OR strftime(periood_lopp, '%m-%d') = '12-31') THEN div(t.riiklikud_maksud, tulu) END AS maksukoormus_tulust
      FROM l LEFT JOIN tax_y t ON t.kood = l.kood AND t.aasta = l.aasta""")

    # 7) Ettevõtete otsinguindeks --------------------------------------------------
    con.execute("""
      CREATE TABLE companies AS
      WITH ids AS (SELECT kood FROM reg UNION SELECT kood FROM fin UNION SELECT kood FROM tax_q),
      rn AS (SELECT kood, arg_max(nimi, coalesce(esitatud, DATE '1900-01-01')) AS nimi FROM rep GROUP BY 1),
      tl AS (SELECT kood, arg_max(nimi, aasta*10+kvartal) AS nimi, arg_max(emtak, aasta*10+kvartal) AS emtak,
                    arg_max(maakond, aasta*10+kvartal) AS maakond, arg_max(liik, aasta*10+kvartal) AS liik
             FROM tax_q GROUP BY 1),
      fy AS (SELECT kood, max(aasta) AS viimane_aruanne, arg_max(emtak_kood, aasta) AS emtak_kood,
                    arg_max(emtak_nimetus, aasta) AS emtak_nimetus FROM fin GROUP BY 1)
      SELECT i.kood, COALESCE(g.nimi, rn.nimi, tl.nimi) AS nimi,
        lower(strip_accents(COALESCE(g.nimi, rn.nimi, tl.nimi))) AS nimi_norm,
        COALESCE(g.vorm, tl.liik) AS vorm, g.staatus, g.kmkr, g.esmakanne, g.aadress,
        tl.emtak, tl.maakond, fy.viimane_aruanne, fy.emtak_kood, fy.emtak_nimetus,
        tl.kood IS NOT NULL AS on_maksuandmed
      FROM ids i LEFT JOIN reg g USING (kood) LEFT JOIN rn USING (kood)
        LEFT JOIN tl USING (kood) LEFT JOIN fy USING (kood)
      WHERE COALESCE(g.nimi, rn.nimi, tl.nimi) IS NOT NULL""")
    stats["ettevotteid"] = con.execute("SELECT count(*) FROM companies").fetchone()[0]

    # 7b) Tegevusala võrdlusjaotused (kvartiilid) --------------------------------------
    unions = []
    for lvl in PEER_LEVELS:
        for m in PEER_METRICS:
            unions.append(f"""SELECT {lvl} AS tase, left(emtak_kood, {lvl}) AS emtak, aasta, '{m}' AS naitaja,
                quantile_cont({m}, 0.25) AS p25, median({m}) AS p50, quantile_cont({m}, 0.75) AS p75, count({m}) AS n
              FROM fin WHERE length(emtak_kood) >= {lvl} AND tulu >= {PEER_MIN_REVENUE} AND isfinite({m})
              GROUP BY ALL HAVING count({m}) >= {PEER_MIN_N}""")
    con.execute("CREATE TABLE peers AS " + " UNION ALL ".join(unions))
    con.execute("""CREATE TABLE emtak_names AS SELECT emtak_kood AS emtak, mode(emtak_nimetus) AS nimetus
                   FROM fin WHERE emtak_nimetus IS NOT NULL GROUP BY 1""")
    stats["vordlusgruppe"] = con.execute("SELECT count(DISTINCT (tase, emtak, aasta)) FROM peers").fetchone()[0]

    # 8) Väljund ---------------------------------------------------------------------
    for table, order in [("companies", "kood"), ("fin", "kood, aasta"), ("tax_q", "kood, aasta, kvartal"),
                         ("peers", "emtak, aasta, naitaja"), ("emtak_names", "emtak")]:
        target = out_dir / f"{table}.parquet"
        con.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO {repr(str(target))} "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD, PARQUET_VERSION V1, ROW_GROUP_SIZE {PARQUET_ROW_GROUP})")
        log.info("Kirjutatud %s (%.1f MB)", target.name, target.stat().st_size / 1e6)
    con.close()
    return stats
