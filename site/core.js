// Kasutajaliides. Andmeallikas (globaalne `source`) tuleb kas source-duckdb.js-ist või source-static.js-ist.
const $ = (s, el = document) => el.querySelector(s);
const statusEl = $("#status"), q = $("#q"), list = $("#results"), view = $("#view");
let ready, charts = [];

// ------------------------------------------------------------------ vorming
const nf0 = new Intl.NumberFormat("et-EE", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("et-EE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("et-EE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = v => nf0.format(v);
const FMT = {
  teur: v => nf0.format(v / 1000),
  eur: v => nf0.format(v),
  pct: v => nf1.format(v * 100) + " %",
  x: v => nf2.format(v),
  int: v => nf0.format(v),
};
const normText = s => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

// Näitajate kirjeldus: [veerg, silt, vorming, selgitus]
const METRICS = [
  ["Mahud, tuh €", [
    ["tulu", "Müügitulu", "teur", "Müügitulu; mittetulundusühingutel tulu ettevõtlusest"],
    ["ebitda", "EBITDA", "teur", "Ärikasum + põhivara kulum ja väärtuse langus"],
    ["arikasum", "Ärikasum", "teur"],
    ["puhaskasum", "Aruandeaasta kasum", "teur"],
    ["varad", "Varad kokku", "teur"],
    ["omakapital", "Omakapital", "teur"],
    ["kaibekapital", "Käibekapital", "teur", "Käibevara − lühiajalised kohustised"],
    ["tootajate_arv", "Töötajad (täistööajale taandatud)", "int"],
  ]],
  ["Kasumlikkus", [
    ["tulu_kasv", "Müügitulu kasv", "pct", "Võrreldes eelmise majandusaastaga"],
    ["ebitda_marginaal", "EBITDA marginaal", "pct", "EBITDA / müügitulu"],
    ["arikasumi_marginaal", "Ärikasumi marginaal", "pct", "Ärikasum / müügitulu"],
    ["puhaskasumi_marginaal", "Puhaskasumi marginaal", "pct", "Aruandeaasta kasum / müügitulu"],
    ["roe", "ROE", "pct", "Aruandeaasta kasum / keskmine omakapital"],
    ["roa", "ROA", "pct", "Aruandeaasta kasum / keskmised varad"],
  ]],
  ["Likviidsus", [
    ["lyhiajaline_maksevoime", "Lühiajaline maksevõime", "x", "Käibevara / lühiajalised kohustised"],
    ["raha_kordaja", "Raha kordaja", "x", "Raha / lühiajalised kohustised"],
  ]],
  ["Kapitali struktuur", [
    ["omakapitali_maar", "Omakapitali määr", "pct", "Omakapital / varad"],
    ["volakordaja", "Võlakordaja", "pct", "Kohustised kokku / varad"],
    ["kohustised_omakapitalile", "Kohustised / omakapital", "x", "Arvutatakse ainult positiivse omakapitali korral"],
  ]],
  ["Efektiivsus", [
    ["varade_kaibevus", "Varade käibesagedus", "x", "Müügitulu / keskmised varad"],
    ["toojoukulu_osakaal", "Tööjõukulu osakaal", "pct", "Tööjõukulud / müügitulu"],
    ["tulu_tootaja_kohta", "Müügitulu töötaja kohta, €", "eur"],
    ["toojoukulu_tootaja_kohta_kuus", "Tööjõukulu töötaja kohta kuus, €", "eur", "Sisaldab tööandja makse"],
    ["lisandvaartus_tootaja_kohta", "Lisandväärtus töötaja kohta, €", "eur", "(Ärikasum + tööjõukulud + kulum) / töötajad"],
  ]],
  ["Maksu- ja Tolliamet, kalendriaasta", [
    ["emta_riiklikud_maksud", "Tasutud riiklikud maksud, tuh €", "teur"],
    ["emta_toojoumaksud", "Tasutud tööjõumaksud, tuh €", "teur"],
    ["emta_kaive", "Deklareeritud käive, tuh €", "teur"],
    ["emta_kaive_tulule", "EMTA käive / müügitulu", "x", "Ainult kalendriaastaga võrduva majandusaasta ja 4 kvartali andmete korral"],
    ["toojoumaksud_toojoukuludele", "Tööjõumaksud / tööjõukulud", "pct", "Ainult kalendriaasta ja 4 kvartali andmete korral"],
    ["maksukoormus_tulust", "Riiklikud maksud / müügitulu", "pct", "Sisaldab käibemaksu ja aktsiise"],
  ]],
];

// ------------------------------------------------------------------ otsing
let sel = -1, current = [], timer;
q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 120); });
q.addEventListener("keydown", e => {
  if (list.hidden) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    sel = Math.max(0, Math.min(current.length - 1, sel + (e.key === "ArrowDown" ? 1 : -1)));
    [...list.children].forEach((li, i) => li.setAttribute("aria-selected", i === sel));
    list.children[sel]?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter" && current.length) {
    open(current[Math.max(sel, 0)].kood);
  } else if (e.key === "Escape") list.hidden = true;
});
document.addEventListener("click", e => { if (!e.target.closest(".search")) list.hidden = true; });

async function search() {
  const term = q.value.trim();
  if (term.length < 2) { list.hidden = true; return; }
  await ready;
  const res = await source.search(term, normText);
  current = res; sel = -1;
  list.innerHTML = res.length ? "" : `<li><span class="s">Vasteid ei leitud. Proovi lühemat nimeosa või registrikoodi.</span></li>`;
  for (const r of res) {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    if (r.staatus && !/registrisse kantud/i.test(r.staatus)) li.className = "inactive";
    li.innerHTML = `<span class="n"></span><span class="k"></span><span class="s"></span>`;
    li.children[0].textContent = r.nimi;
    li.children[1].textContent = r.kood;
    li.children[2].textContent = [r.vorm, r.staatus, r.viimane_aruanne ? `aruanne ${r.viimane_aruanne}` : "aruandeid pole"]
      .filter(Boolean).join(", ");
    li.addEventListener("click", () => open(r.kood));
    list.appendChild(li);
  }
  list.hidden = false;
}

function open(kood) { list.hidden = true; q.blur(); location.hash = kood; }
addEventListener("hashchange", route);

// ------------------------------------------------------------------ ettevõtte vaade
async function route() {
  const kood = decodeURIComponent(location.hash.slice(1));
  if (!kood) return;
  await ready;
  const { co, fin, tax } = await source.company(kood);
  if (!co) { view.innerHTML = `<section class="empty"><p>Registrikoodiga ${escapeHtml(kood)} ettevõtet ei leitud.</p></section>`; return; }
  document.title = `${co.nimi} – Compy`;
  render(co, fin, tax);
}

function render(co, fin, tax) {
  charts.forEach(c => c.destroy()); charts = [];
  const node = $("#company-tpl").content.cloneNode(true);
  $(".cname", node).textContent = co.nimi;
  const facts = [["Registrikood", co.kood], ["Õiguslik vorm", co.vorm], ["Staatus", co.staatus],
                 ["KMKR", co.kmkr], ["Esmakanne", co.esmakanne],
                 ["Põhitegevusala", co.emtak_kood ? `${co.emtak_kood} ${co.emtak_nimetus ?? ""}` : co.emtak],
                 ["Maakond", co.maakond], ["Aadress", co.aadress]];
  $(".facts", node).innerHTML = facts.filter(f => f[1]).map(([k, v]) =>
    `<div><dt>${k}</dt><dd>${escapeHtml(String(v))}</dd></div>`).join("");

  const years = fin.slice(-7);              // kronoloogiline (graafikud, trend)
  const cols = [...years].reverse();         // tabelis viimane aasta esimesena
  const tbl = $(".ratios", node);
  if (!years.length) {
    tbl.innerHTML = `<tbody><tr><td>Äriregistri avaandmetes pole selle ettevõtte majandusaasta aruannete põhinäitajaid.</td></tr></tbody>`;
  } else {
    let h = `<thead><tr><th>Majandusaasta</th>${cols.map(y =>
      `<th title="Periood lõppes ${y.periood_lopp ?? "?"}">${y.aasta}${y.kalendriaasta ? "" : "*"}</th>`).join("")}<th>Trend</th></tr></thead><tbody>`;
    for (const [grp, items] of METRICS) {
      const present = items.filter(([k]) => years.some(y => y[k] != null));
      if (!present.length) continue;
      h += `<tr class="grp"><td colspan="${years.length + 2}">${grp}</td></tr>`;
      for (const [k, label, f, hint] of present) {
        const vals = cols.map(y => y[k]);
        h += `<tr><td class="lbl">${hint ? `<abbr title="${escapeHtml(hint)}">${label}</abbr>` : label}</td>` +
          vals.map(v => v == null || !isFinite(v) ? `<td class="na">–</td>`
            : `<td class="${v < 0 ? "neg" : ""}">${FMT[f](v)}</td>`).join("") +
          `<td class="spark">${spark([...vals].reverse())}</td></tr>`;
      }
    }
    tbl.innerHTML = h + "</tbody>";
  }

  const tt = $(".taxes", node);
  if (!tax.length) {
    tt.innerHTML = `<tbody><tr><td>Maksu- ja Tolliameti avaldatud andmetes see ettevõte puudub.</td></tr></tbody>`;
  } else {
    const last = tax.slice(-12).reverse();
    tt.innerHTML = `<thead><tr><th>Kvartal</th><th>Riiklikud maksud, €</th><th>Tööjõumaksud, €</th>
      <th>Käive, €</th><th>Töötajaid</th></tr></thead><tbody>` +
      last.map(r => `<tr><td>${r.aasta} Q${r.kvartal}</td>${["riiklikud_maksud", "toojoumaksud", "kaive", "tootajad"]
        .map(k => r[k] == null ? `<td class="na">–</td>` : `<td>${fmtInt(r[k])}</td>`).join("")}</tr>`).join("") + "</tbody>";
  }

  view.replaceChildren(node);
  setupPeers(years);
  drawCharts(years, tax);
  window.scrollTo({ top: 0 });
}

// ------------------------------------------------------------------ tegevusala võrdlus
const PEER_METRICS = METRICS.flatMap(([, items]) => items).filter(([k]) =>
  ["tulu_kasv", "ebitda_marginaal", "arikasumi_marginaal", "puhaskasumi_marginaal", "roe", "roa",
   "lyhiajaline_maksevoime", "omakapitali_maar", "volakordaja", "varade_kaibevus", "toojoukulu_osakaal",
   "tulu_tootaja_kohta", "toojoukulu_tootaja_kohta_kuus", "lisandvaartus_tootaja_kohta"].includes(k));
const LEVEL_NAME = { 2: "osa", 3: "grupp", 4: "klass", 5: "alaklass" };

async function setupPeers(years) {
  const sec = $(".peers");
  let withEmtak = years.filter(y => y.emtak_kood);
  if (withEmtak.length) {
    // ainult aastad, mille kohta võrdlusgrupp on olemas (viimane aasta on sageli veel poolik)
    const codes = [...new Set(withEmtak.map(y => String(y.emtak_kood).slice(0, 2)))];
    const avail = new Set(await source.peerYears(codes));
    withEmtak = withEmtak.filter(y => avail.has(y.aasta));
  }
  if (!withEmtak.length) { sec.hidden = true; return; }
  const ySel = $(".p-year", sec), lSel = $(".p-level", sec);
  ySel.innerHTML = [...withEmtak].reverse().map(y => `<option>${y.aasta}</option>`).join("");
  const load = async () => {
    const row = withEmtak.find(y => String(y.aasta) === ySel.value);
    const code = String(row.emtak_kood), prefixes = [2, 3, 4, 5].filter(l => code.length >= l).map(l => code.slice(0, l));
    const peers = await source.peers(row.aasta, prefixes);
    const levels = [...new Set(peers.map(p => p.tase))].sort((a, b) => b - a);
    const keep = lSel.value;
    const nMax = l => Math.max(...peers.filter(p => p.tase === l).map(p => p.n));
    lSel.innerHTML = `<option value="best">Täpseim võimalik</option>` + levels.map(l =>
      `<option value="${l}">EMTAK ${LEVEL_NAME[l]} ${code.slice(0, l)}${l === code.length && row.emtak_nimetus
        ? " " + escapeHtml(row.emtak_nimetus) : ""} (kuni ${nMax(l)} ettevõtet)</option>`).join("");
    if ([...lSel.options].some(o => o.value === keep)) lSel.value = keep;
    drawPeerTable(row, peers, lSel.value);
  };
  ySel.onchange = load;
  lSel.onchange = load;
  load();
}

function drawPeerTable(row, peers, level) {
  const t = $(".ptable");
  let h = `<thead><tr><th>Näitaja</th><th>Ettevõte</th><th>Alumine kvartiil</th><th>Mediaan</th>
    <th>Ülemine kvartiil</th><th>Asend grupis</th><th></th></tr></thead><tbody>`;
  let any = false;
  for (const [k, label, f] of PEER_METRICS) {
    const cand = peers.filter(p => p.naitaja === k && (level === "best" || p.tase === Number(level)))
                      .sort((a, b) => b.tase - a.tase);
    const p = cand[0], v = row[k];
    if (!p) continue;
    any = true;
    const fmt = x => x == null || !isFinite(x) ? "–" : FMT[f](x);
    const q = v == null || !isFinite(v) ? "" : v < p.p25 ? "alumine veerand" : v < p.p50 ? "teine veerand"
            : v < p.p75 ? "kolmas veerand" : "ülemine veerand";
    h += `<tr><td class="lbl" title="EMTAK ${p.emtak}, n = ${p.n}">${label}</td>
      <td class="${v < 0 ? "neg" : ""}">${fmt(v)}</td><td>${fmt(p.p25)}</td><td>${fmt(p.p50)}</td><td>${fmt(p.p75)}</td>
      <td class="pos">${box(v, p)}</td><td class="qt">${q}</td></tr>`;
  }
  t.innerHTML = any ? h + "</tbody>"
    : `<tbody><tr><td>Selle tegevusala ja aasta kohta pole piisavalt võrreldavaid ettevõtteid.</td></tr></tbody>`;
}

function box(v, p) {
  const W = 200, H = 18, iqr = (p.p75 - p.p25) || Math.abs(p.p50) || 1;
  let lo = p.p25 - 1.5 * iqr, hi = p.p75 + 1.5 * iqr;
  const has = v != null && isFinite(v);
  const X = x => 4 + (Math.min(Math.max(x, lo), hi) - lo) / (hi - lo) * (W - 8);
  const out = has && (v < lo || v > hi);
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <line x1="4" x2="${W - 4}" y1="9" y2="9" stroke="var(--rule)" stroke-width="1"/>
    <rect x="${X(p.p25)}" y="4" width="${Math.max(1, X(p.p75) - X(p.p25))}" height="10" rx="2"
          fill="color-mix(in srgb, var(--petrol) 22%, transparent)" stroke="var(--petrol)" stroke-width="1"/>
    <line x1="${X(p.p50)}" x2="${X(p.p50)}" y1="2" y2="16" stroke="var(--petrol)" stroke-width="2"/>
    ${has ? `<circle cx="${X(v)}" cy="9" r="${out ? 3.5 : 4.5}" fill="var(--amber)" stroke="var(--surface)" stroke-width="1.5"/>` : ""}
    ${out ? `<text x="${v < lo ? 0 : W}" y="17" font-size="9" fill="var(--muted)" text-anchor="${v < lo ? "start" : "end"}">${v < lo ? "◂" : "▸"}</text>` : ""}
  </svg>`;
}

function spark(vals) {
  const pts = vals.map((v, i) => [i, v]).filter(([, v]) => v != null && isFinite(v));
  if (pts.length < 2) return "";
  const W = 88, H = 22, ys = pts.map(p => p[1]), lo = Math.min(...ys), hi = Math.max(...ys), n = vals.length - 1;
  const xy = pts.map(([i, v]) => [(i / n) * (W - 4) + 2, H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6)]);
  const last = xy[xy.length - 1];
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <polyline fill="none" stroke="var(--muted)" stroke-width="1.3" points="${xy.map(p => p.join(",")).join(" ")}"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2.6" fill="var(--petrol)"/></svg>`;
}

function drawCharts(years, tax) {
  if (!window.Chart) return;
  const css = getComputedStyle(document.documentElement), c = n => css.getPropertyValue(n).trim();
  Chart.defaults.color = c("--muted");
  Chart.defaults.font.family = "IBM Plex Sans, system-ui, sans-serif";
  Chart.defaults.borderColor = c("--rule");
  const k = v => v == null ? null : v / 1000;
  const fmtTick = { callback: v => nf0.format(v) };
  if (years.length) charts.push(new Chart($(".c-fin"), {
    type: "bar",
    data: { labels: years.map(y => y.aasta), datasets: [
      { label: "Müügitulu", data: years.map(y => k(y.tulu)), backgroundColor: c("--petrol") },
      { label: "EBITDA", data: years.map(y => k(y.ebitda)), backgroundColor: c("--amber") }] },
    options: { maintainAspectRatio: false, scales: { y: { ticks: fmtTick } }, plugins: { legend: { position: "bottom" } } },
  }));
  if (tax.length) {
    const t = tax.slice(-16);
    charts.push(new Chart($(".c-tax"), {
      type: "bar",
      data: { labels: t.map(r => `${r.aasta} Q${r.kvartal}`), datasets: [
        { label: "Riiklikud maksud", data: t.map(r => k(r.riiklikud_maksud)), backgroundColor: c("--petrol") },
        { label: "Tööjõumaksud", data: t.map(r => k(r.toojoumaksud)), backgroundColor: c("--amber") }] },
      options: { maintainAspectRatio: false, scales: { y: { ticks: fmtTick } }, plugins: { legend: { position: "bottom" } } },
    }));
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// ------------------------------------------------------------------ jalus
async function footer() {
  try {
    const m = await source.meta();
    const d = s => s ? new Date(s).toLocaleDateString("et-EE") : "?";
    $("#foot").innerHTML = `<p>Majandusaasta aruannete andmed seisuga ${d(m.aruanded_seisuga)}; Maksu- ja Tolliameti
      viimane kvartal ${m.emta_viimane_kvartal ?? "?"}. Andmed uuendatud ${d(m.ehitatud)}.</p>
      <p>Allikad: <a href="https://avaandmed.ariregister.rik.ee/et/avaandmete-allalaadimine">e-äriregistri avaandmed</a>,
      <a href="https://www.emta.ee/eraklient/amet-uudised-ja-kontakt/uudised-pressiinfo-statistika/statistika-ja-avaandmed">Maksu- ja Tolliameti avaandmed</a>.
      * tähistab majandusaastat, mis ei lõpe 31. detsembril.</p>`;
  } catch { /* meta puudub – pole kriitiline */ }
}

ready = source.init().then(n => { statusEl.textContent = `${fmtInt(n)} ettevõtet`; }).catch(e => { statusEl.textContent = "Andmete laadimine ebaõnnestus: " + e.message; throw e; });
footer();
route();
