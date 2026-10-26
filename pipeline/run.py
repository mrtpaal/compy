"""Käivitus: leia failid -> kontrolli muutusi -> lae alla -> ehita -> meta.json.

Näited:
  python -m pipeline.run                         # tavaline uuendus
  python -m pipeline.run --previous old_meta.json  # jäta vahele, kui allikad pole muutunud
  python -m pipeline.run --force                 # ehita alati
  python -m pipeline.run --from-dir ./allalaetud   # käsitsi allalaetud failidest (ilma internetita)
  python -m pipeline.run --profile               # näita failide päiseid ja elementide nimesid
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import fetch
from .build import build, prepare_csv, sniff
from .config import SOURCES

log = logging.getLogger("pipeline")


def from_dir(d: Path) -> dict[str, list[dict]]:
    found = {}
    names = sorted(p.name for p in d.iterdir() if p.is_file())
    for key, (_, pattern, multi) in SOURCES.items():
        rx = re.compile(pattern)
        hits = []
        for n in names:
            m = rx.search(n)
            if m:
                item = {"url": f"file://{d / n}", "filename": n}
                if m.groups():
                    item["year"] = int(m.group(1))
                hits.append(item)
        if not hits:
            raise RuntimeError(f"Kaustas {d} pole allika '{key}' faili (muster {pattern})")
        found[key] = hits if multi else hits[-1:]
    return found


def set_output(name: str, value: str):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--raw", default=".cache/raw")
    ap.add_argument("--previous", help="eelmise ehituse meta.json (muutuste tuvastuseks)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--from-dir", help="kasuta selle kausta faile allalaadimise asemel")
    ap.add_argument("--profile", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.profile:
        a.force = True

    raw = Path(a.raw)
    prev, prev_meta = {}, {}
    if a.previous and Path(a.previous).exists():
        try:
            prev_meta = json.loads(Path(a.previous).read_text())
            prev = {s["filename"]: s for s in prev_meta["allikad"]}
        except (ValueError, KeyError):
            log.warning("Eelmist meta.json-i ei saanud lugeda – ehitan kõik")

    if a.from_dir:
        files = from_dir(Path(a.from_dir))
        raw = Path(a.from_dir)
        for items in files.values():
            for it in items:
                it["sha256"] = fetch.hashlib.sha256((raw / it["filename"]).read_bytes()).hexdigest()
    else:
        files = fetch.discover()
        items = [it for v in files.values() for it in v]
        # Samm 1: odav kontroll HEAD-päringuga
        for it in items:
            it["fingerprint"] = fetch.head_fingerprint(it["url"])
        unchanged = (prev and not a.force and set(prev) == {it["filename"] for it in items}
                     and all(it["fingerprint"] and prev[it["filename"]].get("fingerprint") == it["fingerprint"]
                             for it in items))
        if unchanged:
            log.info("Allikad pole muutunud (HEAD) – ehitust pole vaja.")
            set_output("changed", "false")
            return
        # Samm 2: lae alla ja võrdle sisu räsi
        for it in items:
            it["sha256"] = fetch.download(it["url"], raw / it["filename"])
        unchanged = (prev and not a.force and set(prev) == {it["filename"] for it in items}
                     and all(prev[it["filename"]].get("sha256") == it["sha256"] for it in items))
        if unchanged:
            log.info("Failide sisu pole muutunud – ehitust pole vaja.")
            set_output("changed", "false")
            return

    if a.profile:
        for key, items in files.items():
            for it in items:
                p = prepare_csv(raw / it["filename"], raw / "_extracted")
                delim, header = sniff(p)
                print(f"\n== {key}: {it['filename']}  (eraldaja {delim!r})\n   {header}")
        return

    stats = build(files, raw, Path(a.out))
    # Kvaliteedikontroll: kui ridade arv kukub järsult (nt katkine/poolik fail), ära avalda
    for k in ("aruandeid", "ettevotteid", "emta_ridu"):
        old, new = prev_meta.get(k), stats.get(k)
        if old and new is not None and new < 0.8 * old and not a.force:
            raise RuntimeError(f"Kvaliteedikontroll: '{k}' langes {old} -> {new} (>20%). "
                               "Kontrolli allikaid; avaldamiseks käivita --force.")
    yld = files["rik_yldandmed"][0]["filename"]
    m = re.search(r"kuni_(\d{2})(\d{2})(\d{4})", yld)
    meta = {
        "ehitatud": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aruanded_seisuga": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None,
        "allikad": [{k: it.get(k) for k in ("filename", "url", "year", "fingerprint", "sha256")} | {"allikas": key}
                    for key, items in files.items() for it in items],
        **stats,
    }
    out = Path(a.out) / "meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str))
    log.info("Valmis: %s", {k: v for k, v in stats.items() if not isinstance(v, (dict, list))})
    if stats.get("puuduvad_valjad"):
        log.warning("NB! Kaardistamata väljad: %s – vaata meta.json 'kaardistamata_elemendid'",
                    stats["puuduvad_valjad"])
    set_output("changed", "true")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        logging.getLogger("pipeline").error(str(e))
        sys.exit(1)
