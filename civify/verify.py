"""Claim verifier: checks a plain-language sentence against the official record.

A summary sentence (the "claim") arrives with the exact quote it relies on.
This module answers two questions in code, with no AI involved:

1. QUOTE EXISTS: does the quote appear on a page of the source document?
   We ignore only PDF noise (line breaks, hyphens, curly quotes, capitals).
   There is deliberately no fuzzy matching: a "close enough" quote can be a
   different quote, for example one with a "not" missing.
2. NUMBERS AGREE: does every number in the sentence also appear in the quote?
   This catches "684 units" quietly becoming "864 units" even when the quote is real.

What it cannot catch: a paraphrase that changes meaning without changing a
number (a dropped condition, a flipped "not"). That is why staff must review
and approve every summary before it is published.

Page breaks: running headers and footers ("... Page 15 of 35") are stripped
first, because they land in the middle of sentences that cross a page. A quote
may then span one page break; it is reported under the page where it starts.

Run the demo:  python -m civify.verify
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from collections import Counter

from civify.extract import Document, extract

# Minimum quote length after normalisation (about 7-8 words). Shorter phrases such
# as "the proposed development" appear on several pages and prove nothing.
MIN_QUOTE_CHARS = 40

# Curly quotes become straight; hyphens and dashes are dropped, because PDFs
# break words across lines ("resi-\ndential") and people swap "-" for "–".
_CLEAN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        **{ord(c): None for c in "-‐‑‒–—−­"}})


def normalize(text: str) -> str:
    """Make two texts comparable: same case, no whitespace, no dashes, straight quotes."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(_CLEAN)
    return re.sub(r"\s+", "", text)


def numbers(text: str) -> set[str]:
    """'$1,250,000' and '1250000' both become '1250000'; '158.5' stays '158.5'."""
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def running_lines(doc: Document) -> set[str]:
    """Lines that repeat on at least half the pages, with digits masked so
    'Page 15 of 35' and 'Page 16 of 35' count as the same footer."""
    seen = Counter()
    for page in doc.pages:
        for line in {re.sub(r"\d", "#", l.strip()) for l in page.text.splitlines() if l.strip()}:
            seen[line] += 1
    threshold = max(3, len(doc.pages) // 2)
    return {line for line, n in seen.items() if n >= threshold}


def strip_running_lines(text: str, running: set[str]) -> str:
    return "\n".join(l for l in text.splitlines() if re.sub(r"\d", "#", l.strip()) not in running)


@dataclass
class Result:
    verified: bool
    reason: str            # "ok", or why it failed (shown to staff)
    page: int | None = None  # page the quote was found on, for click-through


class Verifier:
    def __init__(self, doc: Document):
        running = running_lines(doc)
        self.pages = [(page.number, normalize(strip_running_lines(page.text, running))) for page in doc.pages]

    def check(self, sentence: str, quote: str) -> Result:
        if "..." in quote or "…" in quote:
            return Result(False, "quote contains an ellipsis; a quote must be one continuous passage")

        needle = normalize(quote)
        if len(needle) < MIN_QUOTE_CHARS:
            return Result(False, "quote is too short to count as evidence")

        page = self._find(needle)
        if page is None:
            return Result(False, "quote not found in the source document")

        unsupported = numbers(sentence) - numbers(quote)
        if unsupported:
            return Result(False, f"number(s) in the sentence are not in the quote: {', '.join(sorted(unsupported))}")

        return Result(True, "ok", page)

    def _find(self, needle: str) -> int | None:
        """Page the quote starts on. Single pages first, so a quote that sits wholly on
        one page is never attributed to the page before it; joined pairs only as a fallback."""
        for number, text in self.pages:
            if needle in text:
                return number
        for (number, text), (_, next_text) in zip(self.pages, self.pages[1:]):
            if needle in text + next_text:
                return number
        return None


# --- demo: `python -m civify.verify` ------------------------------------------

def demo(folder: Path) -> int:
    """Run the claims in demo_claims.json and print a pass/fail table."""
    claims = json.loads((folder / "demo_claims.json").read_text())
    verifiers: dict[str, Verifier] = {}
    unexpected = 0
    for c in claims:
        if c["file"] not in verifiers:
            verifiers[c["file"]] = Verifier(extract(folder / c["file"]))
        r = verifiers[c["file"]].check(c["sentence"], c["quote"])
        as_expected = r.verified == c["expect_verified"]
        unexpected += not as_expected
        label = f"VERIFIED   [p.{r.page}]" if r.verified else f"UNVERIFIED [{r.reason}]"
        print(f"{'✓' if as_expected else '✗ UNEXPECTED'} {label}  {c['sentence']}")
        if c.get("note"):
            print(f"      note: {c['note']}")
    print(f"\n{len(claims) - unexpected}/{len(claims)} behaved as expected")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(demo(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/2026.TE34.21")))
