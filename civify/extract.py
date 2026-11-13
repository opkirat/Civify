"""Read a PDF into page-numbered text.

Every claim Civify shows must point back to a page of the original document,
so we keep the page boundary and never merge pages at this stage.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader


@dataclass
class Page:
    number: int  # 1-based, matches what a PDF viewer shows
    text: str


@dataclass
class Document:
    filename: str
    sha256: str  # proves the file we analysed is the file we cite
    pages: list[Page] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def first_lines(self, n: int = 15) -> list[str]:
        """Non-empty lines from page 1, whitespace collapsed.

        Some PDFs extract one word per line, so we also provide a joined form
        via `first_page_flat` for pattern matching.
        """
        lines = [collapse(l) for l in self.pages[0].text.splitlines()] if self.pages else []
        return [l for l in lines if l][:n]

    @property
    def first_page_flat(self) -> str:
        return collapse(self.pages[0].text) if self.pages else ""


def collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract(path: str | Path) -> Document:
    path = Path(path)
    reader = PdfReader(str(path))
    pages = [Page(i, p.extract_text() or "") for i, p in enumerate(reader.pages, start=1)]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return Document(filename=path.name, sha256=digest, pages=pages)
