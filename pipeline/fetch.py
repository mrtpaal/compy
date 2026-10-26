"""Failide leidmine allikalehtedelt ja allalaadimine muutuste tuvastusega."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

from .config import SOURCES, MIN_REPORT_YEAR

log = logging.getLogger(__name__)
UA = {"User-Agent": "compy/1.0 (avaandmete taaskasutus)"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def _get(url: str, **kw) -> requests.Response:
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == 3:
                raise
            log.warning("Päring ebaõnnestus (%s), proovin uuesti: %s", e, url)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def discover() -> dict[str, list[dict]]:
    """Tagastab {allika_võti: [{url, filename, year?}]}. Katkeb, kui midagi ei leita."""
    pages: dict[str, list[str]] = {}
    found: dict[str, list[dict]] = {}
    for key, (page, pattern, multi) in SOURCES.items():
        if page not in pages:
            p = _Links()
            p.feed(_get(page).text)
            pages[page] = [urljoin(page, h) for h in p.hrefs]
        rx = re.compile(pattern)
        hits, seen = [], set()
        for url in pages[page]:
            path = url.split("?")[0]
            m = rx.search(path)
            if m and path not in seen:
                seen.add(path)
                item = {"url": url, "filename": path.rsplit("/", 1)[-1]}
                if m.groups():
                    item["year"] = int(m.group(1))
                hits.append(item)
        if multi and MIN_REPORT_YEAR:
            hits = [h for h in hits if h.get("year", 9999) >= MIN_REPORT_YEAR]
        if not hits:
            raise RuntimeError(
                f"Allikat '{key}' ei leitud lehelt {page} (muster {pattern}). "
                "Tõenäoliselt on failinimi muutunud – uuenda pipeline/config.py SOURCES.")
        if not multi and len(hits) > 1:
            log.warning("'%s': leiti %d vastet, kasutan esimest", key, len(hits))
            hits = hits[:1]
        found[key] = hits
        log.info("%-15s %d fail(i): %s", key, len(hits), ", ".join(h["filename"] for h in hits))
    return found


def head_fingerprint(url: str) -> str | None:
    """Odav sõrmejälg ilma allalaadimiseta (ETag / Last-Modified + Content-Length)."""
    try:
        r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
        if r.status_code >= 400:
            return None
        etag, lm, cl = r.headers.get("ETag"), r.headers.get("Last-Modified"), r.headers.get("Content-Length")
        if etag:
            return f"etag:{etag}"
        if lm and cl:
            return f"lm:{lm}|{cl}"
    except requests.RequestException:
        pass
    return None


def download(url: str, dest: Path) -> str:
    """Laeb faili alla ja tagastab sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True) as r, open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            h.update(chunk)
    tmp.replace(dest)
    log.info("Alla laetud %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return h.hexdigest()
