"""Kõik allikatega seotud seadistus ühes kohas.

Kui RIK või EMTA muudab failinimesid või veergude nimesid, on vaja muuta
ainult seda faili. Ülejäänud koodis pole ühtegi kõvakodeeritud URL-i ega veerunime.
"""
import re

# --------------------------------------------------------------------------
# 1. Allikalehed. Failide URL-id leitakse nendelt lehtedelt iga käivitusega
#    (RIK lisab failinimesse kuupäeva "kuni_30092026", mis muutub igakuiselt).
# --------------------------------------------------------------------------
RIK_PAGE = "https://avaandmed.ariregister.rik.ee/et/avaandmete-allalaadimine"
EMTA_PAGE = ("https://www.emta.ee/eraklient/amet-uudised-ja-kontakt/"
             "uudised-pressiinfo-statistika/statistika-ja-avaandmed")

# allika võti -> (leht, href-i regex, kas võib olla mitu faili)
SOURCES = {
    "rik_lihtandmed": (RIK_PAGE,  r"ettevotja_rekvisiidid__lihtandmed\.csv\.zip$", False),
    "rik_yldandmed":  (RIK_PAGE,  r"1\.aruannete_yldandmed_kuni_\d{8}\.zip$", False),
    "rik_emtak":      (RIK_PAGE,  r"2\.EMTAK_myygitulu_kuni_\d{8}\.zip$", False),
    "rik_elemendid":  (RIK_PAGE,  r"4\.(\d{4})_aruannete_elemendid_kuni_\d{8}\.zip$", True),
    "emta_jooksev":   (EMTA_PAGE, r"tasutud_maksud_kaesolev_aasta\.csv(?:\.zip)?$", False),
    "emta_varasem":   (EMTA_PAGE, r"tasutud_maksud_varasemad_aastad\.csv(?:\.zip)?$", False),
}

# Kasutame ainult neid aruandeaastaid (None = kõik, mis lehel on)
MIN_REPORT_YEAR = None

# --------------------------------------------------------------------------
# 2. Veergude tuvastamine. Päised normaliseeritakse (väiketähed, täpitähed
#    lahti, mitte-tähed -> "_"). Esmalt otsitakse täpset vastet, siis
#    "contains" reeglit. Kohustuslik veerg, mida ei leita -> build katkeb
#    veateatega, mis näitab faili tegelikke päiseid.
# --------------------------------------------------------------------------
COLS = {
    "lihtandmed": {
        "kood":      dict(exact=["ariregistri_kood", "registrikood", "kood"], required=True),
        "nimi":      dict(exact=["nimi", "ettevotja_nimi"], required=True),
        "vorm":      dict(exact=["ettevotja_oiguslik_vorm", "oiguslik_vorm"], contains=["oiguslik_vorm"]),
        "staatus":   dict(exact=["ettevotja_staatus_tekstina", "staatus_tekstina", "ettevotja_staatus", "staatus"]),
        "kmkr":      dict(exact=["kmkr_nr", "kmkr", "kmkr_number"]),
        "esmakanne": dict(exact=["ettevotja_esmakande_kpv", "esmakande_kpv", "esmakanne"], contains=["esmakande"]),
        "aadress":   dict(exact=["ads_normaliseeritud_taisaadress", "ettevotja_aadress", "aadress"]),
    },
    "yldandmed": {
        "report_id":     dict(exact=["report_id", "aruande_id", "aruanne_id"], contains=["report_id"], required=True),
        "kood":          dict(exact=["registrikood", "ariregistri_kood", "kood"], required=True),
        "nimi":          dict(exact=["nimi", "arinimi", "ettevotja_nimi"]),
        "aasta":         dict(exact=["aruandeaasta", "aruande_aasta", "majandusaasta", "aasta"]),
        "periood_algus": dict(exact=["perioodi_algus", "periood_algus", "aruandeperioodi_algus",
                                     "majandusaasta_algus"], contains=["algus"]),
        "periood_lopp":  dict(exact=["perioodi_lopp", "periood_lopp", "aruandeperioodi_lopp",
                                     "majandusaasta_lopp"], contains=["lopp"]),
        "esitatud":      dict(exact=["esitamise_aeg", "esitamise_kp", "esitamise_kuupaev", "esitatud"],
                              contains=["esitami"]),
        "kategooria":    dict(exact=["aruande_kategooria", "kategooria"], contains=["kategooria"]),
        "audit":         dict(exact=["audiitori_otsuse_tyyp", "audiitori_otsus", "auditeeritud"], contains=["audi"]),
    },
    "elemendid": {
        "report_id": dict(exact=["report_id", "aruande_id", "aruanne_id"], contains=["report_id"], required=True),
        "element":   dict(exact=["elemendi_nimetus", "elemendi_nimi", "element", "elemendi_kood", "nimetus",
                                 "tunnus", "naitaja"], contains=["element"], required=True),
        "vaartus":   dict(exact=["vaartus", "elemendi_vaartus", "summa", "value"], contains=["vaartus"],
                          required=True),
        "konsolideeritud": dict(exact=["konsolideeritud", "on_konsolideeritud"], contains=["konsolid"]),
    },
    "emtak": {
        "report_id": dict(exact=["report_id", "aruande_id", "aruanne_id"], contains=["report_id"], required=True),
        "emtak":     dict(exact=["emtak_kood", "emtak", "tegevusala_kood", "emtak_kood_5"], contains=["emtak"],
                          required=True),
        "nimetus":   dict(exact=["emtak_nimetus", "emtak_tekstina", "tegevusala", "nimetus"], contains=["nimetus"]),
        "summa":     dict(exact=["myygitulu", "muugitulu", "summa", "vaartus", "muugitulu_summa"],
                          contains=["tulu", "summa"], required=True),
        "pohi":      dict(exact=["pohitegevusala", "on_pohitegevusala", "pohitegevus"], contains=["pohitegev"]),
    },
    "emta": {
        "kood":      dict(exact=["registrikood", "kood"], required=True),
        "nimi":      dict(exact=["nimi"], required=True),
        "liik":      dict(exact=["liik"]),
        "kmkr":      dict(contains=["kaibemaksukohustuslas"]),
        "emtak":     dict(contains=["emtak"]),
        "maakond":   dict(exact=["maakond"]),
        "riiklikud": dict(exact=["riiklikud_maksud"], contains=["riiklik"], required=True),
        "toojou":    dict(exact=["toojoumaksud_ja_maksed"], contains=["toojou"], required=True),
        "kaive":     dict(exact=["kaive"], contains=["kaive"], required=True),
        "tootajad":  dict(exact=["tootajaid", "tootajate_arv"], contains=["tootaja"]),
        "aasta":     dict(exact=["aasta"]),
        "kvartal":   dict(exact=["kvartal"], contains=["kvartal"]),
        "periood":   dict(exact=["periood"], contains=["periood"]),
    },
}

# --------------------------------------------------------------------------
# 3. Aruande elementide kaardistus kanoonilisteks näitajateks.
#    Regex rakendatakse normaliseeritud elemendinimele; esimene vaste võidab,
#    seega spetsiifilisemad mustrid enne üldisemaid.
#    Toetab nii eestikeelseid silte kui ka taksonoomia koode (nt "CurrentAssets").
#    Kaardistamata elemendid kirjutatakse meta.json-i -> näed kohe, kui RIK
#    on midagi ümber nimetanud.
# --------------------------------------------------------------------------
ELEMENT_MAP = [
    ("raha",                    [r"^raha$", r"^raha_ja_raha_ekvivalendid$", r"^cash(andcashequivalents)?$"]),
    ("kaibevara",               [r"^kaibevara(d)?(_kokku)?$", r"^currentassets$"]),
    ("pohivara",                [r"^pohivara(d)?(_kokku)?$", r"^noncurrentassets$"]),
    ("varad",                   [r"^varad(_kokku)?$", r"^assets$"]),
    ("lyhiajalised_kohustised", [r"^luhiajalised_kohustised(_kokku)?$", r"^currentliabilities$"]),
    ("pikaajalised_kohustised", [r"^pikaajalised_kohustised(_kokku)?$", r"^noncurrentliabilities$"]),
    ("omakapital",              [r"^omakapital(_kokku)?$", r"^equity$"]),
    ("myygitulu",               [r"^muugitulu$", r"^myygitulu$", r"^revenue$"]),
    ("tulu_ettevotlusest",      [r"^tulu_ettevotlus(est|elt)$", r"^revenuefrombusiness"]),
    ("toojoukulud",             [r"^toojoukulud$", r"^laborexpense$"]),
    ("kulum",                   [r"^pohivara(de)?_kulum", r"kulum_ja_vaartuse_langus", r"^depreciationandimpairment"]),
    ("arikasum",                [r"^arikasum(_kahjum)?$", r"^totaloperatingprofitloss$", r"^operatingprofitloss$"]),
    ("kasum_enne_tm",           [r"^kasum_kahjum_enne_tulumaksustamist$", r"^kasum_enne_tulumaksustamist$",
                                 r"^totalprofitlossbeforetax$", r"^profitlossbeforetax$"]),
    ("puhaskasum",              [r"^aruande_?aasta_kasum(_kahjum)?$", r"^totalannualperiodprofitloss$",
                                 r"^annualperiodprofitloss$"]),
    ("jaotamata_kasum",         [r"^eelmiste_perioodide_jaotamata_kasum(_kahjum)?$", r"^retainedearningsloss$"]),
    ("tootajate_arv",           [r"tootajate_arv", r"taistooajale", r"numberofemployees"]),
]

CANONICAL_FIELDS = [name for name, _ in ELEMENT_MAP]
# Kulud on aruannetes sageli negatiivse märgiga – suhtarvudes kasutame absoluutväärtust
COST_FIELDS = {"toojoukulud", "kulum"}
COMPILED_ELEMENT_MAP = [(n, [re.compile(p) for p in pats]) for n, pats in ELEMENT_MAP]

# Kui aruandeid on samale aastale mitu (parandatud aruanne), võetakse viimasena esitatud.
# Konsolideeritud vs konsolideerimata: eelistame konsolideerimata (ettevõtte enda) näitajaid.
PREFER_CONSOLIDATED = False

# Tegevusala võrdlus: EMTAK-i tasemed (koodi pikkus), mida arvutatakse; veebileht valib
# kõige täpsema taseme, kus on vähemalt PEER_MIN_N ettevõtet.
PEER_LEVELS = [2, 3, 4, 5]
PEER_MIN_N = 10
PEER_MIN_REVENUE = 50_000      # välistab tühjad/miniettevõtted, mis moonutavad jaotust
PEER_METRICS = ["tulu_kasv", "ebitda_marginaal", "arikasumi_marginaal", "puhaskasumi_marginaal", "roe", "roa",
                "lyhiajaline_maksevoime", "omakapitali_maar", "volakordaja", "varade_kaibevus",
                "toojoukulu_osakaal", "tulu_tootaja_kohta", "toojoukulu_tootaja_kohta_kuus",
                "lisandvaartus_tootaja_kohta"]

PARQUET_ROW_GROUP = 25_000   # väikesed row-groupid -> brauser loeb ainult vajaliku osa
