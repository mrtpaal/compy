// Andmeallikas GitHub Pagesi jaoks: DuckDB-WASM loeb Parquet faile HTTP range-päringutega.
import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm";
const BASE = new URL("data/", location.href).href;
let conn;

async function rows(sql, ...params) {
  let res;
  if (params.length) { const st = await conn.prepare(sql); res = await st.query(...params); await st.close(); }
  else res = await conn.query(sql);
  return res.toArray().map(r => {
    const o = r.toJSON();
    for (const k in o) if (typeof o[k] === "bigint") o[k] = Number(o[k]);
    return o;
  });
}

window.source = {
  async init() {
    const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
    const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
    const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), new Worker(workerUrl));
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(workerUrl);
    conn = await db.connect();
    await conn.query(`CREATE TABLE c AS SELECT kood, nimi, nimi_norm, vorm, staatus, viimane_aruanne
                      FROM read_parquet('${BASE}companies.parquet')`);
    return (await rows(`SELECT count(*) AS n FROM c`))[0].n;
  },
  async search(term, normText) {
    if (/^\d+$/.test(term)) return rows(`SELECT * FROM c WHERE kood LIKE (? || '%') ORDER BY kood LIMIT 30`, term);
    const t = normText(term).replace(/[%_]/g, " ");
    const toks = t.split(/\s+/).filter(Boolean).slice(0, 5);
    const where = toks.map(() => `nimi_norm LIKE ('%' || ? || '%')`).join(" AND ");
    return rows(`SELECT * FROM c WHERE ${where}
      ORDER BY (nimi_norm = ?) DESC, (nimi_norm LIKE (? || '%')) DESC,
               (lower(coalesce(staatus,'')) LIKE '%registrisse kantud%') DESC,
               viimane_aruanne DESC NULLS LAST, length(nimi) LIMIT 30`, ...toks, t, t);
  },
  async company(kood) {
    const [co] = await rows(`SELECT kood, nimi, vorm, staatus, kmkr, strftime(esmakanne, '%d.%m.%Y') AS esmakanne,
                                    aadress, emtak, maakond, emtak_kood, emtak_nimetus
                             FROM read_parquet('${BASE}companies.parquet') WHERE kood = ?`, kood);
    if (!co) return {};
    const fin = await rows(`SELECT * EXCLUDE (periood_algus, periood_lopp, esitatud),
                              strftime(periood_lopp, '%d.%m.%Y') AS periood_lopp
                            FROM read_parquet('${BASE}fin.parquet') WHERE kood = ? ORDER BY aasta`, kood);
    const tax = await rows(`SELECT * FROM read_parquet('${BASE}tax_q.parquet') WHERE kood = ? ORDER BY aasta, kvartal`, kood);
    return { co, fin, tax };
  },
  async peerYears(codes2) {
    return (await rows(`SELECT DISTINCT aasta FROM read_parquet('${BASE}peers.parquet')
      WHERE tase = 2 AND emtak IN (${codes2.map(() => "?").join(",")})`, ...codes2)).map(r => r.aasta);
  },
  async peers(year, prefixes) {
    return rows(`SELECT tase, emtak, naitaja, p25, p50, p75, n FROM read_parquet('${BASE}peers.parquet')
                 WHERE aasta = ? AND emtak IN (${prefixes.map(() => "?").join(",")})`, year, ...prefixes);
  },
  async meta() { return (await fetch(BASE + "meta.json", { cache: "no-cache" })).json(); },
};
