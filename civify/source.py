"""Lead a reviewer to the exact spot in the PDF that a quote came from.

The verifier proves a quote exists; this module shows *where*, so the person
checking a sentence reads the passage in its surroundings instead of hunting
through the file. It never changes what is shown as evidence: the quote stays
the quote, and the excerpt is the page's own text around it.

Matching tolerates what PDF extraction changes: line breaks, hyphenation,
curly quotes, dashes and spacing. Nothing fuzzy; every letter and digit of the
quote must appear, in order.
"""

from __future__ import annotations

import re

from civify.extract import Document
from civify.verify import running_lines, strip_running_lines

CONTEXT_CHARS = 420  # roughly a paragraph either side
_GAP = r"[\s\-‐‑‒–—−­]*"  # whitespace, every kind of dash, soft hyphen
_QUOTES = {"'": "['‘’]", '"': '["“”]', "‘": "['‘’]", "’": "['‘’]", "“": '["“”]', "”": '["“”]'}


def pattern(quote: str) -> re.Pattern:
    parts = []
    for ch in quote:
        if ch.isspace() or ch in "-‐‑‒–—−­":
            continue
        parts.append(_QUOTES.get(ch, re.escape(ch)))
    return re.compile(_GAP.join(parts), re.I | re.S)


def locate(doc: Document, quote: str, page: int | None = None) -> dict | None:
    """Where the quote sits: {"page", "pages", "before", "match", "after"}, or None.

    Tries the page the verifier named first, then that page joined with the next
    (a quote can straddle a page break), then every page. "pages" is the label to
    show, e.g. "4" or "4–5"."""
    if not quote.strip():
        return None
    pat = pattern(quote)
    running = running_lines(doc)
    texts = {p.number: strip_running_lines(p.text, running) for p in doc.pages}
    order = [page] if page in texts else []
    order += [n for n in texts if n not in order]
    for n in order:                       # whole pages first, like the verifier
        hit = _excerpt(pat, texts[n], str(n))
        if hit:
            return {"page": n, **hit}
    for n in order:                       # then a page joined with the next
        if n + 1 in texts:
            hit = _excerpt(pat, texts[n] + "\n" + texts[n + 1], f"{n}–{n + 1}")
            if hit:
                return {"page": n, **hit}
    return None


def _excerpt(pat: re.Pattern, text: str, label: str) -> dict | None:
    m = pat.search(text)
    if not m:
        return None
    start, end = m.span()
    before = text[max(0, start - CONTEXT_CHARS):start]
    after = text[end:end + CONTEXT_CHARS]
    if start - CONTEXT_CHARS > 0:
        before = "…" + before.split(" ", 1)[-1]
    if end + CONTEXT_CHARS < len(text):
        after = after.rsplit(" ", 1)[0] + "…"
    return {"pages": label, "before": _tidy(before), "match": _tidy(m.group(0)), "after": _tidy(after)}


def _tidy(s: str) -> str:
    """Join the lines PDF extraction broke, keep paragraph breaks."""
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)          # re-join hyphenated words
    s = re.sub(r"\n{2,}", "\n\n", s)
    s = re.sub(r"(?<!\n)\n(?!\n)", " ", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()
