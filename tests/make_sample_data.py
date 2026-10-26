"""Sünteetilised näidisfailid, mis jäljendavad RIK/EMTA failivorminguid.
Kasutus: python tests/make_sample_data.py tests/sample && python -m pipeline.run --from-dir tests/sample --out site/data
"""
import csv, io, random, sys, zipfile
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/sample"); out.mkdir(parents=True, exist_ok=True)
random.seed(7)
names = ["Terminal Oil AS", "Põhjala Kütus OÜ", "Läänemere Logistika AS", "Õunapuu Kaubandus OÜ",
         "Tartu Energia OÜ", "Saaremaa Laevad AS", "Viru Tankla OÜ", "Mustamäe Ehitus OÜ"]
names += [f"Näidis {i} OÜ" for i in range(40)]
codes = [str(10000000 + i * 1234567 % 9000000) for i in range(len(names))]
EMTAK = [("47301", "Mootorikütuse jaemüük"), ("46711", "Mootorikütuse hulgimüük"), ("49411", "Kaubavedu maanteel")]
emtak_rows = []

def zipcsv(fname, rows, header, enc="utf-8-sig"):
    buf = io.StringIO(); w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(header); w.writerows(rows)
    with zipfile.ZipFile(out / fname, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(fname.replace(".zip", "").replace(".csv", "") + ".csv", buf.getvalue().encode(enc))

zipcsv("ettevotja_rekvisiidid__lihtandmed.csv.zip",
       [[n, c, "Osaühing" if n.endswith("OÜ") else "Aktsiaselts", "", f"EE10{c}", "R", "Registrisse kantud",
         "01.02.2001", "Tallinn", f"Harju maakond, Tallinn, Tänav {i}"] for i, (n, c) in enumerate(zip(names, codes))],
       ["nimi", "ariregistri_kood", "ettevotja_oiguslik_vorm", "ettevotja_oigusliku_vormi_alaliik", "kmkr_nr",
        "ettevotja_staatus", "ettevotja_staatus_tekstina", "ettevotja_esmakande_kpv", "asukoht_ettevotja_aadressis",
        "ads_normaliseeritud_taisaadress"])

labels = ["Raha", "Käibevarad kokku", "Põhivarad kokku", "Varad", "Lühiajalised kohustised kokku",
          "Pikaajalised kohustised kokku", "Omakapital", "Müügitulu", "Tööjõukulud",
          "Põhivarade kulum ja väärtuse langus", "Ärikasum (kahjum)", "Aruandeaasta kasum (kahjum)",
          "Töötajate keskmine arv taandatud täistööajale", "Eelmiste perioodide jaotamata kasum (kahjum)",
          "Kasum (kahjum) enne tulumaksustamist", "Mingi uus element"]
rep_rows, rid = [], 1000
els = {y: [] for y in (2022, 2023, 2024, 2025)}
for c, n in zip(codes, names):
    rev = random.uniform(1e6, 2e8)
    for y in (2022, 2023, 2024, 2025):
        if y == 2025 and random.random() < .5: continue
        rev *= random.uniform(.9, 1.2)
        for corr in ([0, 1] if (y == 2023 and c == codes[0]) else [0]):   # parandatud aruanne
            rid += 1
            e = EMTAK[codes.index(c) % 3]
            emtak_rows.append([rid, e[0], e[1], f"{rev*.9:.2f}".replace(".", ","), "jah"])
            emtak_rows.append([rid, "68201", "Kinnisvara üürileandmine", f"{rev*.1:.2f}".replace(".", ","), "ei"])
            rep_rows.append([rid, c, n, y, f"01.01.{y}", f"31.12.{y}", f"{20+corr}.05.{y+1}", "Keskmine", "Auditeeritud"])
            assets = rev * random.uniform(.4, .9); ca = assets * .6; eq = assets * random.uniform(.2, .6)
            cl = (assets - eq) * .7; ncl = assets - eq - cl
            op = rev * random.uniform(-.02, .08); dep = -rev * .02; lab = -rev * random.uniform(.05, .15)
            ebt = op * .95; net = ebt * .9
            vals = [ca*.2, ca, assets-ca, assets, cl, ncl, eq, rev*(1.5 if corr else 1), lab, dep, op, net,
                    round(abs(lab)/30000), eq*.5, ebt, 1]
            for l, v in zip(labels, vals):
                els[y].append([rid, l, f"{v:.2f}".replace(".", ",")])
zipcsv("1.aruannete_yldandmed_kuni_30092026.zip", rep_rows,
       ["report_id", "registrikood", "nimi", "aruandeaasta", "perioodi_algus", "perioodi_lopp", "esitamise_kpv",
        "aruande_kategooria", "audiitori_otsuse_tyyp"])
zipcsv("2.EMTAK_myygitulu_kuni_30092026.zip", emtak_rows,
       ["report_id", "emtak_kood", "emtak_nimetus", "myygitulu", "pohitegevusala"])
for y, rows in els.items():
    zipcsv(f"4.{y}_aruannete_elemendid_kuni_30092026.zip", rows, ["report_id", "elemendi_nimetus", "vaartus"])

hdr = ["Registrikood", "Nimi", "Liik", "Registreeritud käibemaksukohustuslaste registrisse",
       "EMTAK tegevusvaldkond, mis on EMTAKi struktuuris tähistatud tähtkoodiga", "Maakond", "Riiklikud maksud",
       "Tööjõumaksud ja maksed", "Käive", "Töötajaid", "Aasta", "Kvartal"]
for fname, years, enc in [("tasutud_maksud_varasemad_aastad.csv", (2022, 2023, 2024), "cp1257"),
                          ("tasutud_maksud_kaesolev_aasta.csv", (2025, 2026), "utf-8-sig")]:
    rows = []
    for c, n in zip(codes, names):
        for y in years:
            for q in ["I", "II", "III", "IV"]:
                if y == 2026 and q == "IV": continue
                rows.append([c, n, "Äriühing", "jah", "HULGI- JA JAEKAUBANDUS", "Harju ( Tallinn )",
                             f"{random.uniform(1e4,5e6):.2f}".replace(".", ","), f"{random.uniform(1e4,1e6):.2f}".replace(".", ","),
                             f"{random.uniform(1e5,5e7):.2f}".replace(".", ","), random.randint(5, 400), y, q])
    with open(out / fname, "w", encoding=enc, newline="") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(hdr); w.writerows(rows)
print("Näidisandmed:", out)
