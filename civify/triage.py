"""Decide which draft sentences need a person and which can go out in one click.

Two checks, then a lane:

1. RISK RULES (plain code). Anything about taking part or a deadline always goes
   to a person. A sentence that states a recommendation or decision, a condition,
   or uncertainty goes to a person only when the quoted passage does not say the
   same kind of thing: "must" in the sentence with no requirement in the passage,
   "may" with no hedge in the passage, "recommend" with no recommendation. When
   the passage echoes the word, the meaning check below is what confirms the
   sentence kept it intact.
2. MEANING CHECK (one model call per item). A second pass reads each sentence
   beside the quote it cites and answers: does the quote fully support it, with no
   condition dropped and nothing overstated? Is it neutral? This catches the gap
   the code verifier cannot: a real quote under a sentence that misreads it.

Lanes
  blocked  code verification failed (quote not found, wrong number). Cannot be
           approved as written; staff must edit it so it passes, or reject it.
  review   any risk rule fired, or the meaning check said anything but a clean
           "supported". Shown to staff one by one, with the reasons.
  ready    passed every check. Staff publish these together with one click.

Nothing is published without a named person's approval, even in the ready lane.
If the meaning check is not run or fails, sentences fall back to "review".

Run:  python -m civify.triage data/2027.PB1.6            # live meaning check (needs GEMINI_API_KEY)
      python -m civify.triage data/2027.PB1.6 --replay   # reuse the saved model reply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from civify.draft import DEFAULT_MODEL, load_env

# (label, pattern, always). "always" rules send the sentence to a person whenever they
# match. The others only do so when the quoted passage has no match of its own.
RISK_RULES = [
    ("mentions taking part or a deadline", r"\b(deadline|comments?|register\w*|appeal\w*|submissions?)\b", True),
    ("states a recommendation or decision", r"\b(recommend\w*|approv\w*|refus\w*|designat\w*|decid\w*|adopt\w*|reject\w*)\b", False),
    ("states a condition or requirement", r"\b(subject to|conditions?|must|requir\w*|unless|if|shall)\b", False),
    ("states uncertainty", r"\b(may|might|could|possibl\w*|anticipat\w*|expect\w*)\b", False),
]

PROMPT = """You are checking plain-language sentences written for residents against the exact passage
from a City of Toronto staff report that each sentence cites.

For each numbered pair, judge ONLY against the passage. Do not use outside knowledge.
- verdict: "supported" if the passage fully supports the sentence: nothing added, nothing stated
  more strongly than the passage, and no condition, exception or uncertainty in the passage left
  out where leaving it out changes the meaning. "not_supported" if the sentence contradicts,
  overstates or adds to the passage. "unsure" if you cannot tell.
- neutral: true if the sentence is neutral and non-partisan (no praise, criticism or prediction).
- issue: one short sentence naming the problem, or "" if there is none.

PAIRS:
{pairs}
"""


class MeaningResult(BaseModel):
    index: int
    verdict: Literal["supported", "not_supported", "unsure"]
    neutral: bool
    issue: str


class MeaningCheck(BaseModel):
    results: list[MeaningResult]


def risk_reasons(sentence: str, quote: str = "") -> list[str]:
    """Why this sentence needs a person, before the meaning check is considered.

    With no quote, every matching rule fires (the strict reading)."""
    out = []
    for label, pattern, always in RISK_RULES:
        if not re.search(pattern, sentence, re.I):
            continue
        if always or not quote or not re.search(pattern, quote, re.I):
            out.append(label if always or not quote else f"{label} that the source passage does not")
    return out


def build_prompt(claims: list[dict]) -> str:
    pairs = "\n".join(f'{i}. SENTENCE: {c["sentence"]}\n   PASSAGE: {c["quote"]}' for i, c in enumerate(claims, 1))
    return PROMPT.format(pairs=pairs)


def call_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=MeaningCheck, temperature=0),
    ).text


def check_meaning(claims: list[dict], call: Callable[[str], str] = call_gemini) -> tuple[str, dict[int, dict]]:
    """Return (raw reply, {claim index: result}). Pairs are numbered from 1 in the prompt."""
    raw = call(build_prompt(claims))
    by_index = {}
    for r in MeaningCheck.model_validate_json(raw).results:
        if 1 <= r.index <= len(claims):
            by_index[r.index - 1] = r.model_dump(exclude={"index"})
    return raw, by_index


def assign_lane(claim: dict, meaning: dict | None) -> tuple[str, list[str]]:
    """Lane and the human-readable reasons for it."""
    if not claim.get("verified"):
        return "blocked", [f"code check failed: {claim.get('reason')}"]
    reasons = risk_reasons(claim["sentence"], claim.get("quote", ""))
    if meaning is None:
        reasons.append("meaning check not run")
    else:
        if meaning["verdict"] != "supported":
            reasons.append(f"meaning check: {meaning['verdict'].replace('_', ' ')}" + (f" ({meaning['issue']})" if meaning.get("issue") else ""))
        if not meaning["neutral"]:
            reasons.append("meaning check: wording may not be neutral")
    return ("review" if reasons else "ready"), reasons


def triage(claims: list[dict], meaning: dict[int, dict]) -> list[dict]:
    out = []
    for i, c in enumerate(claims):
        lane, reasons = assign_lane(c, meaning.get(i))
        out.append({"index": i, "sentence": c["sentence"], "lane": lane, "reasons": reasons, "meaning": meaning.get(i)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--replay", action="store_true", help="reuse the saved meaning-check reply")
    args = ap.parse_args()

    claims = json.loads((args.folder / "drafts.json").read_text())
    saved = args.folder / "meaning_response.json"
    meaning: dict[int, dict] = {}
    if args.replay:
        _, meaning = check_meaning(claims, lambda _p: saved.read_text())
    else:
        load_env()
        if "GEMINI_API_KEY" not in os.environ:
            print("GEMINI_API_KEY not set: every sentence will be sent to staff review. Use --replay with a saved reply.")
        else:
            try:
                raw, meaning = check_meaning(claims)
                saved.write_text(raw)
            except Exception as e:  # fail safe: no meaning check means everything goes to review
                print(f"meaning check failed ({type(e).__name__}); every sentence will go to staff review")
    result = triage(claims, meaning)
    (args.folder / "triage.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    for t in result:
        print(f"{t['lane']:8} {t['sentence'][:80]}" + (f"\n         ↳ {'; '.join(t['reasons'])}" if t["reasons"] else ""))
    counts = {lane: sum(t["lane"] == lane for t in result) for lane in ("ready", "review", "blocked")}
    print(f"\n{counts['ready']} ready · {counts['review']} need a look · {counts['blocked']} blocked. "
          f"Run `python -m civify.record {args.folder}` to update the record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
