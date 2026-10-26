"""Parquet -> gzip+base64 andmefailid + ühe-faililine HTML (claude.ai artefakti jaoks).

  python -m pipeline.export_static --data site/data --out dist_static [--manifest urls.json]

Ilma --manifest-ita kirjutatakse andmefailid ja nimekiri; --manifest (failinimi -> URL) korral
pannakse URL-id HTML-i sisse.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
from pathlib import Path

import duckdb

SITE = Path(__file__).resolve().parent.parent / "site"
TARGET_SHARD_BYTES = 3_000_000   # ~3 MB base64 kohta


def shard_of(kood: str, n: int) -> int:
    h = 0
    for ch in kood:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % n


def r(v):
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v) if abs(v) >= 1000 else round(v, 5)
    return v


def pack(obj, path: Path) -> int:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    path.write_text(base64.b64encode(gzip.compress(raw, 9)).decode())
    return path.stat().st_size


def dicts(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [{c: r(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def export(data: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    p = lambda t: repr(str(data / f"{t}.parquet"))
    files = {}

    # Otsinguindeks (sõnastikkodeeritud vorm/staatus)
    rows = con.execute(f"SELECT kood, nimi, vorm, staatus, viimane_aruanne FROM read_parquet({p('companies')}) "
                       "ORDER BY kood").fetchall()
    vormid = sorted({x[2] or "" for x in rows})
    staatused = sorted({x[3] or "" for x in rows})
    vi, si = {v: i for i, v in enumerate(vormid)}, {v: i for i, v in enumerate(staatused)}
    idx = {"vormid": vormid, "staatused": staatused,
           "rows": [[k, n, vi[v or ""], si[s or ""], y] for k, n, v, s, y in rows]}
    files["index"] = pack(idx, out / "index.txt")

    # Ettevõtete kaupa killud
    cos = dicts(con, f"""SELECT kood, nimi, vorm, staatus, kmkr, strftime(esmakanne, '%d.%m.%Y') AS esmakanne,
        aadress, emtak, maakond, emtak_kood, emtak_nimetus FROM read_parquet({p('companies')})""")
    fin = dicts(con, f"""SELECT * EXCLUDE (periood_algus, periood_lopp, esitatud, report_id, kategooria, audit),
        strftime(periood_lopp, '%d.%m.%Y') AS periood_lopp FROM read_parquet({p('fin')}) ORDER BY kood, aasta""")
    tax = dicts(con, f"""SELECT kood, aasta, kvartal, riiklikud_maksud, toojoumaksud, kaive, tootajad
        FROM read_parquet({p('tax_q')}) ORDER BY kood, aasta, kvartal""")
    data_by = {c["kood"]: {"co": {k: v for k, v in c.items() if v is not None}} for c in cos}
    for key, lst in (("fin", fin), ("tax", tax)):
        for row in lst:
            k = row.pop("kood")
            if k in data_by:
                data_by[k].setdefault(key, []).append({a: b for a, b in row.items() if b is not None})

    sample = list(data_by.items())[:2000]
    per = len(gzip.compress(json.dumps(sample, default=str).encode())) * 1.37 / max(1, len(sample))
    n = max(1, math.ceil(per * len(data_by) / TARGET_SHARD_BYTES))
    shards = [dict() for _ in range(n)]
    for k, v in data_by.items():
        shards[shard_of(k, n)][k] = v
    for i, s in enumerate(shards):
        files[f"shard{i}"] = pack(s, out / f"shard{i}.txt")

    # Tegevusala kvartiilid: {aasta: {emtak: [[tase, näitaja, p25, p50, p75, n]]}}
    peers: dict = {}
    for tase, emtak, aasta, naitaja, p25, p50, p75, cnt in con.execute(
            f"SELECT tase, emtak, aasta, naitaja, p25, p50, p75, n FROM read_parquet({p('peers')})").fetchall():
        peers.setdefault(str(aasta), {}).setdefault(emtak, []).append([tase, naitaja, r(p25), r(p50), r(p75), cnt])
    files["peers"] = pack(peers, out / "peers.txt")

    meta = json.loads((data / "meta.json").read_text())
    meta = {k: meta.get(k) for k in ("ehitatud", "aruanded_seisuga", "emta_viimane_kvartal")}
    (out / "build.json").write_text(json.dumps({"shards": n, "meta": meta, "sizes": files}, ensure_ascii=False))
    return {"shards": n, "sizes": files}


def html(out: Path, urls: dict):
    b = json.loads((out / "build.json").read_text())
    manifest = {"shards": b["shards"], "meta": b["meta"], "files": urls}
    page = (SITE / "index.html").read_text()
    css = (SITE / "styles.css").read_text() + """
:root { box-sizing: border-box; padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
html { scroll-padding-top: env(safe-area-inset-top, 0px); }
.top { top: env(safe-area-inset-top, 0px); }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--surface); }
"""
    js = ("const MANIFEST = " + json.dumps(manifest, ensure_ascii=False) + ";\n"
          + (SITE / "source-static.js").read_text() + "\n" + (SITE / "core.js").read_text())
    page = page.replace('<meta name="viewport" content="width=device-width, initial-scale=1">',
                        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
    page = page.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}</style>")
    start = page.index('<script type="module">')
    end = page.index("</script>", start) + len("</script>")
    page = page[:start] + f'<script type="module">\n{js}\n</script>' + page[end:]
    (out / "index.html").write_text(page)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="site/data")
    ap.add_argument("--out", default="dist_static")
    ap.add_argument("--manifest", help="JSON {failinimi: url}")
    a = ap.parse_args()
    out = Path(a.out)
    if a.manifest:
        html(out, json.loads(Path(a.manifest).read_text()))
    else:
        print(json.dumps(export(Path(a.data), out), indent=1))
