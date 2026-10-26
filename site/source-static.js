// Andmeallikas claude.ai artefakti jaoks: andmed on gzip+base64 failidena artefakti varahoidlas.
// MANIFEST (failinimi -> URL) lisatakse lehele ehituse käigus.
const SHARDS = MANIFEST.shards;
const cache = new Map();
let IDX, NORM, PEERS;

async function load(name) {
  if (!cache.has(name)) cache.set(name, (async () => {
    const r = await fetch(MANIFEST.files[name]);
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    const bin = Uint8Array.from(atob((await r.text()).trim()), c => c.charCodeAt(0));
    const stream = new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  })());
  return cache.get(name);
}
const shardOf = kood => { let h = 0; for (const ch of kood) h = (Math.imul(h, 31) + ch.charCodeAt(0)) >>> 0; return h % SHARDS; };

window.source = {
  async init() {
    IDX = await load("index");
    NORM = IDX.rows.map(r => r[1].normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase());
    return IDX.rows.length;
  },
  async search(term, normText) {
    const row = i => { const r = IDX.rows[i];
      return { kood: r[0], nimi: r[1], vorm: IDX.vormid[r[2]], staatus: IDX.staatused[r[3]], viimane_aruanne: r[4] }; };
    if (/^\d+$/.test(term)) {
      const out = [];
      for (let i = 0; i < IDX.rows.length && out.length < 30; i++) if (IDX.rows[i][0].startsWith(term)) out.push(row(i));
      return out;
    }
    const t = normText(term), toks = t.split(/\s+/).filter(Boolean).slice(0, 5), hits = [];
    for (let i = 0; i < NORM.length; i++) if (toks.every(k => NORM[i].includes(k))) hits.push(i);
    const active = i => /registrisse kantud/i.test(IDX.staatused[IDX.rows[i][3]] || "");
    const key = i => [NORM[i] === t ? 0 : 1, NORM[i].startsWith(t) ? 0 : 1, active(i) ? 0 : 1,
                      -(IDX.rows[i][4] || 0), IDX.rows[i][1].length];
    hits.sort((a, b) => { const ka = key(a), kb = key(b); for (let j = 0; j < ka.length; j++) if (ka[j] !== kb[j]) return ka[j] - kb[j]; return 0; });
    return hits.slice(0, 30).map(row);
  },
  async company(kood) {
    const s = await load("shard" + shardOf(kood));
    return s[kood] ? { co: s[kood].co, fin: s[kood].fin || [], tax: s[kood].tax || [] } : {};
  },
  async peerYears(codes2) {
    PEERS ??= await load("peers");
    return Object.keys(PEERS).filter(y => codes2.some(c => PEERS[y][c])).map(Number);
  },
  async peers(year, prefixes) {
    PEERS ??= await load("peers");
    const y = PEERS[year] || {};
    return prefixes.flatMap(p => (y[p] || []).map(([tase, naitaja, p25, p50, p75, n]) =>
      ({ tase, emtak: p, naitaja, p25, p50, p75, n })));
  },
  async meta() { return MANIFEST.meta; },
};
