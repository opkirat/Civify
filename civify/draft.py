"""Draft plain-language claims from a staff report, then check every one.

The model only PROPOSES. Each sentence it writes comes with the exact quote it
relies on, and `verify.py` then checks that quote against the real PDF text.
Nothing the model says is trusted until it passes that check, and nothing is
published until staff approve it.

Run:   python -m civify.draft data/2026.TE34.21
Replay a saved response without calling the model (no key needed):
       python -m civify.draft data/2026.TE34.21 --replay
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from civify.classify import DocType, classify
from civify.extract import Document, extract
from civify.verify import Verifier

# Model is configurable because Google renames models often. Set GEMINI_MODEL in .env.
DEFAULT_MODEL = "gemini-4-argon"

PROMPT = """You are helping a city clerk explain a municipal staff report to residents.

Write short, plain-language sentences (about grade 8 reading level) that cover:
what is proposed, why, where, what staff recommend, and any conditions.

Rules:
- Use ONLY the report below. Do not add outside knowledge.
- One fact per sentence. Neutral and non-partisan: no praise, criticism or predictions.
- Keep conditions and uncertainty ("subject to...", "if...", "may..."); never state something
  more firmly than the report does.
- Do NOT mention deadlines, how to comment, or who supports or opposes. Those come from other records.
- Every sentence needs a "quote": copied EXACTLY, word for word, from the report. It must be one
  continuous passage of at least 8 words, from a single page, with no "..." and no page markers.
- Every number in your sentence must appear in your quote.

REPORT (pages are marked with === PAGE n ===):
{report}
"""


class DraftClaim(BaseModel):
    sentence: str
    quote: str


class Draft(BaseModel):
    claims: list[DraftClaim]


def load_env(path: str = ".env") -> None:
    """Tiny .env reader so we need no extra dependency. Existing variables win."""
    if os.path.exists(path):
        for line in Path(path).read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def call_gemini(prompt: str) -> str:
    """The only provider-specific code. Returns the model's JSON text."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Draft,
            temperature=0,  # we want the same quotes each run, not creativity
        ),
    )
    return response.text


def build_prompt(doc: Document) -> str:
    report = "\n".join(f"=== PAGE {p.number} ===\n{p.text}" for p in doc.pages)
    return PROMPT.format(report=report)


def draft(doc: Document, call: Callable[[str], str] = call_gemini) -> tuple[str, list[dict]]:
    """Return (raw model response, checked claims). `call` is swappable for tests and replay."""
    raw = call(build_prompt(doc))
    verifier = Verifier(doc)
    checked = []
    for claim in Draft.model_validate_json(raw).claims:
        result = verifier.check(claim.sentence, claim.quote)
        checked.append({
            "sentence": claim.sentence,
            "quote": claim.quote,
            "verified": result.verified,
            "reason": result.reason,
            "page": result.page,
            "source_file": doc.filename,
            "source_sha256": doc.sha256,
        })
    return raw, checked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--replay", action="store_true", help="reuse the saved model response instead of calling the API")
    args = ap.parse_args()

    # Use the classifier to find the staff report, instead of trusting a filename.
    report = next((d for d in map(extract, sorted(args.folder.glob("*.pdf")))
                   if classify(d).doc_type is DocType.STAFF_REPORT), None)
    if report is None:
        print("no staff report found in that folder")
        return 1

    saved = args.folder / "draft_response.json"
    if args.replay:
        call = lambda _prompt: saved.read_text()
    else:
        load_env()
        if "GEMINI_API_KEY" not in os.environ:
            print("GEMINI_API_KEY is not set. Add it to .env, or use --replay with a saved response.")
            return 1
        call = call_gemini

    raw, checked = draft(report, call)
    if not args.replay:
        saved.write_text(raw)
    (args.folder / "drafts.json").write_text(json.dumps(checked, indent=2, ensure_ascii=False))

    for c in checked:
        label = f"VERIFIED   [p.{c['page']}]" if c["verified"] else f"UNVERIFIED [{c['reason']}]"
        print(f"{label}  {c['sentence']}")
    ok = sum(c["verified"] for c in checked)
    print(f"\n{ok}/{len(checked)} claims verified; the rest are flagged for staff. Wrote {args.folder / 'drafts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
