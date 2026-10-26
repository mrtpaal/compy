# Compy – ettevõtete finantsnäitajad (RIK + EMTA avaandmed)

Staatiline veebileht, mis võimaldab otsida ettevõtteid nime või registrikoodi järgi ning kuvab
majandusaasta aruannete põhinäitajad, suhtarvud ja Maksu- ja Tolliameti kvartaliandmed.
Andmed uuenevad automaatselt, käsitööd ei ole.

## Arhitektuur

```
RIK avaandmete leht ─┐                                   GitHub Pages (või Azure Static Web Apps)
EMTA avaandmete leht ┴─► pipeline (Python + DuckDB) ─► site/data/*.parquet ─► brauser (DuckDB-WASM)
                          GitHub Actions, ajastatult
```

| Kiht | Lahendus | Miks |
|---|---|---|
| Failide leidmine | `fetch.discover()` loeb allikalehtedelt lingid regexiga | RIK failinimes on kuupäev (`kuni_30092026`), mis muutub igakuiselt; uus aasta (nt `4.2026_…`) lisandub ise |
| Muutuste tuvastus | HEAD (ETag/Last-Modified) → vajadusel sha256 | Kui midagi pole muutunud, ei laeta ega avaldata |
| Töötlus | DuckDB, olekuta täisehitus | RIK uuendab igakuiselt ka vanemaid aastaid (hilinenud/parandatud aruanded); täisehitus välistab topeltread |
| Kvaliteet | Katkestab, kui ridade arv langeb >20% või kohustuslikku veergu ei leita | Pooliku/muutunud faili korral jääb eelmine versioon üles ja tuleb e-kiri |
| Veeb | Staatiline HTML + DuckDB-WASM loeb Parquet faile HTTP range-päringutega | Serverit ega andmebaasi pole; uuendus = failide asendamine |

## Allikad

| Võti | Fail | Uuendus |
|---|---|---|
| `rik_lihtandmed` | `ettevotja_rekvisiidid__lihtandmed.csv.zip` | iga päev |
| `rik_yldandmed` | `1.aruannete_yldandmed_kuni_DDMMYYYY.zip` | kord kuus |
| `rik_emtak` | `2.EMTAK_myygitulu_kuni_DDMMYYYY.zip` (põhitegevusala) | kord kuus |
| `rik_elemendid` | `4.YYYY_aruannete_elemendid_kuni_DDMMYYYY.zip` (iga aasta) | kord kuus |
| `emta_jooksev` | `tasutud_maksud_kaesolev_aasta.csv` (jooksev + eelmine aasta) | kvartali järgneva kuu 10. kp |
| `emta_varasem` | `tasutud_maksud_varasemad_aastad.csv` | — |

## Väljund (`site/data/`)

| Fail | Võti | Sisu |
|---|---|---|
| `companies.parquet` | `kood` | nimi, vorm, staatus, KMKR, aadress, EMTAK, maakond, viimane aruandeaasta |
| `fin.parquet` | `kood, aasta` | 16 põhinäitajat + suhtarvud + EMTA aastasummad |
| `tax_q.parquet` | `kood, aasta, kvartal` | riiklikud maksud, tööjõumaksud, käive, töötajad |
| `peers.parquet` | `emtak, aasta, naitaja` | kvartiilid (p25/p50/p75) ja n EMTAK-i tasemetel 2–5 |
| `emtak_names` | `emtak` | EMTAK koodide nimetused |
| `meta.json` | — | allikad, seisuga kuupäevad, kaardistamata elemendid |

Samu Parquet faile saab lugeda ka Power BI / Fabric (Lakehouse) poolt.

## Kasutuselevõtt (GitHub Pages, avalik)

1. Loo GitHubis avalik repo (nt `compy`) ja lae failid üles.
2. *Settings → Pages → Source: GitHub Actions*.
3. *Actions → Andmete uuendamine → Run workflow* (esimene ehitus).
4. Leht on aadressil `https://<kasutaja>.github.io/compy/`; ettevõtte otselink `…/#10000000`.
5. Edasi käib kõik ajakava järgi. Ebaõnnestumisel saadab GitHub e-kirja.
6. Soovi korral oma domeen: *Settings → Pages → Custom domain* + DNS CNAME.

## Kohalik käivitus

```bash
pip install -r requirements.txt
python -m pipeline.run --profile         # esmakordsel kasutusel: näita failide tegelikke päiseid
python -m pipeline.run --force           # ehita site/data
cd site && python -m http.server 8000    # ava http://localhost:8000
```

Testimine ilma internetita: `python tests/make_sample_data.py tests/sample && python -m pipeline.run --from-dir tests/sample`.

## Kui allikas muutub

Kõik URL-mustrid, veerunimed ja elementide kaardistus on failis `pipeline/config.py`.
Kaardistamata aruande elemendid on näha `meta.json` väljal `kaardistamata_elemendid`.
