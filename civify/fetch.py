"""Download every official PDF that a saved TMMIS page links to.

The City's council site blocks automated clients, so a person saves the page
(an agenda item or a meeting agenda) by hand. The PDFs it links to live on
www.toronto.ca/legdocs, which is open, so from that one saved page this
fetches the lot: staff reports, notices, by-laws, public letters.

Run:   python -m civify.fetch data/2026.TE34.21            # folder containing a saved item page
       python -m civify.fetch data/agendas/te35.html --out data   # a saved meeting agenda
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

from civify.extract import extract

PDF_URL = re.compile(r"https?://www\.toronto\.ca/legdocs/[\w/.-]+?\.pdf", re.I)
ITEM_ID = re.compile(r"agenda-item\.do\?item=(\d{4}\.[A-Z]{2,4}\d+\.\d+)")


def links_in(path: Path) -> tuple[list[str], list[str]]:
    """(pdf urls, item ids) referenced by a saved page, HTML or printed-to-PDF."""
    text = extract(path).text if path.suffix.lower() == ".pdf" else path.read_text(errors="ignore")
    text = text.replace("\n", "")  # printed pages wrap long URLs across lines
    pdfs = sorted(set(PDF_URL.findall(text)))
    items = sorted(set(ITEM_ID.findall(text)))
    return pdfs, items


def download(url: str, dest: Path, fetch=None) -> bool:
    """Save url to dest unless it already exists. Returns True if downloaded."""
    if dest.exists():
        return False
    data = (fetch or _http_get)(url)
    dest.write_bytes(data)
    return True


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Civify/0.1 (civic-tech hackathon; downloads public council PDFs)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_folder(folder: Path, fetch=None) -> list[str]:
    """For an item folder: read every saved page in it and download the PDFs they link to."""
    got = []
    for page in sorted(folder.iterdir()):
        if page.suffix.lower() not in (".html", ".htm", ".pdf"):
            continue
        pdfs, _ = links_in(page)
        for url in pdfs:
            name = url.rsplit("/", 1)[-1]
            if download(url, folder / name, fetch):
                got.append(name)
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, help="an item folder, or a saved meeting-agenda page")
    ap.add_argument("--out", type=Path, default=Path("data"), help="where item folders go (agenda mode)")
    args = ap.parse_args()

    if args.path.is_dir():
        got = fetch_folder(args.path)
        print(f"{args.path}: downloaded {len(got)} new file(s): {', '.join(got) or '-'}")
        return 0

    pdfs, items = links_in(args.path)
    print(f"{args.path.name}: {len(items)} agenda item(s), {len(pdfs)} PDF link(s)")
    for item in items:
        (args.out / item).mkdir(parents=True, exist_ok=True)
    # Agenda pages link PDFs without saying which item they belong to, so they go
    # under the agenda's own folder; the item page (saved separately) ties them together.
    dest = args.out / "agendas" / args.path.stem
    dest.mkdir(parents=True, exist_ok=True)
    n = sum(download(u, dest / u.rsplit("/", 1)[-1]) for u in pdfs)
    print(f"downloaded {n} new PDF(s) to {dest}; item folders: {', '.join(items) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
