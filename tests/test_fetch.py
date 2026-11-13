"""Fetcher tests: link discovery on the real saved page; downloads use a fake HTTP call."""

from pathlib import Path

import pytest

from civify.fetch import download, fetch_folder, links_in

DATA = Path("data/2026.TE34.21")
pytestmark = pytest.mark.skipif(not (DATA / "Agenda_Item_History.pdf").exists(), reason="source PDFs not in this checkout")


def test_saved_item_page_yields_all_pdf_links_and_the_item_id():
    pdfs, items = links_in(DATA / "Agenda_Item_History.pdf")
    assert items == ["2026.TE34.21"]
    names = {u.rsplit("/", 1)[-1] for u in pdfs}
    assert {"backgroundfile-288412.pdf", "backgroundfile-288413.pdf", "law1064.pdf", "law1234.pdf"} <= names
    assert len(pdfs) == 10


def test_download_skips_existing_and_writes_new(tmp_path):
    calls = []
    fake = lambda url: calls.append(url) or b"%PDF-fake"
    existing = tmp_path / "a.pdf"; existing.write_bytes(b"old")
    assert download("https://www.toronto.ca/legdocs/x/a.pdf", existing, fake) is False
    assert download("https://www.toronto.ca/legdocs/x/b.pdf", tmp_path / "b.pdf", fake) is True
    assert calls == ["https://www.toronto.ca/legdocs/x/b.pdf"] and existing.read_bytes() == b"old"


def test_fetch_folder_only_downloads_what_is_missing(tmp_path):
    (tmp_path / "page.html").write_text(
        '<a href="https://www.toronto.ca/legdocs/mmis/2026/te/bgrd/backgroundfile-1.pdf">r</a>'
        '<a href="https://www.toronto.ca/legdocs/bylaws/2026/law0001.pdf">b</a>')
    (tmp_path / "law0001.pdf").write_bytes(b"have")
    got = fetch_folder(tmp_path, lambda url: b"%PDF-fake")
    assert got == ["backgroundfile-1.pdf"]
