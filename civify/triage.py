"""Decide which draft sentences a person must read, and which are approved automatically.

Checks, in order:

1. CODE (civify/verify.py): the quote is in the PDF and every number matches.
   Failing this is "blocked": a person must edit or reject the sentence.
2. RISK RULES (plain code). Anything about taking part or a deadline always goes
   to a person. A decision, condition or hedge word ("recommend", "must", "may")
   that the quoted passage does not also contain is flagged for the context check.
3. MEANING CHECK (AI call 1). Reads each sentence beside its quote: fully
   supported, nothing overstated or dropped, neutral?
4. CONTEXT CHECK (AI call 2). Reads each sentence against the whole page around
   its quote, told about any flags, and told that an approval goes to residents
   with no person reading it first: "when in doubt, hold". When it holds, it
   suggests corrected wording a person can accept in one click.

Lanes
  blocked  the code check failed.
  review   about taking part or a deadline; or either AI check was not a clean
           yes; or a flagged word was not cleared by the context check.
  ready    everything above agreed. If the context check ran, these are
           approved automatically (as "auto-check", logged like any decision);
           if it did not, a person approves them with one click.

Every check fails safe: an AI call that errors or isn't run sends sentences to
"review", never to "ready". Approved sentences go live for residents straight away
(see db.sync_publication); a person can take any of them down.

Run:  python -m civify.triage data/2027.PB1.6            # live AI checks (needs GEMINI_API_KEY)
      python -m civify.triage data/2027.PB1.6 --replay   # reuse the saved model replies
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

from civify import source
from civify.draft import DEFAULT_MODEL, load_env
from civify.extract import extract

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


CONFIRM_PROMPT = """You are the last check before plain-language sentences are shown to residents of Toronto
WITHOUT any person reading them first. A wrong approval misleads the public; a hold only costs a
staff member a minute. When in doubt, hold.

Each numbered item has the SENTENCE, the QUOTE it cites from a City of Toronto staff report, and the
PAGE text around that quote (the quote is marked [[like this]]). Some items list FLAGS raised by
earlier checks: examine each one against the page.

Approve only if ALL of these are true:
- every fact in the sentence is stated in the quote or the surrounding page text; nothing comes from
  outside knowledge;
- nothing is stated more strongly or more certainly than the source, and who does what (staff
  recommend, Council decides, the owner must) matches the source;
- no condition, exception, number or qualifier that would change what a resident understands is left out;
- the wording is neutral: no praise, criticism, prediction or persuasion.
Otherwise hold.

For every item return:
- verdict: "approve" or "hold"
- neutral: true or false
- issue: one short sentence naming the problem, or "" if approved
- suggestion: if held, a corrected plain-language sentence that uses only facts from the QUOTE and keeps
  every number exactly as it is written there; "" if approved or if no faithful sentence is possible.

ITEMS:
{items}
"""


class ConfirmResult(BaseModel):
    index: int
    verdict: Literal["approve", "hold"]
    neutral: bool
    issue: str
    suggestion: str


class ConfirmCheck(BaseModel):
    results: list[ConfirmResult]


def _split_reasons(sentence: str, quote: str) -> tuple[list[str], list[str]]:
    """(always: a person must read it, soft: the passage doesn't echo the word)."""
    always, soft = [], []
    for label, pattern, is_always in RISK_RULES:
        if not re.search(pattern, sentence, re.I):
            continue
        if is_always:
            always.append(label)
        elif not quote or not re.search(pattern, quote, re.I):
            soft.append(label if not quote else f"{label} that the source passage does not")
    return always, soft


def risk_reasons(sentence: str, quote: str = "") -> list[str]:
    """Why this sentence needs a person, before the AI checks are considered.

    With no quote, every matching rule fires (the strict reading)."""
    always, soft = _split_reasons(sentence, quote)
    return always + soft


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


def contexts_for(claims: list[dict], folder: Path) -> list[dict | None]:
    """The page text around each quote (None if the file or quote can't be found)."""
    docs, out = {}, []
    for c in claims:
        f = c.get("source_file")
        if f and f not in docs and (folder / f).exists():
            docs[f] = extract(folder / f)
        out.append(source.locate(docs[f], c["quote"], c.get("page")) if f in docs else None)
    return out


def build_confirm_prompt(claims: list[dict], contexts: list[dict | None], meaning: dict[int, dict]) -> tuple[str, list[int]]:
    """Prompt for the context check, and which claim indexes it covers.

    Only sentences that could be approved automatically are sent: verified, and not
    about taking part. Items are numbered by claim index + 1 so replies map back."""
    items, sent = [], []
    for i, c in enumerate(claims):
        always, soft = _split_reasons(c["sentence"], c.get("quote", ""))
        if not c.get("verified") or always:
            continue
        ctx = contexts[i] if i < len(contexts) else None
        page = (f"(page {ctx['pages']}) …{ctx['before'][-700:]}[[{ctx['match']}]]{ctx['after'][:700]}…" if ctx
                else "(not available; judge against the quote alone)")
        m = meaning.get(i)
        flags = soft + ([f"meaning check: {m['verdict'].replace('_', ' ')} ({m['issue']})"] if m and m["verdict"] != "supported" else [])
        items.append(f"{i + 1}. SENTENCE: {c['sentence']}\n   QUOTE: {c['quote']}\n   PAGE {page}\n   FLAGS: {'; '.join(flags) or 'none'}")
        sent.append(i)
    return CONFIRM_PROMPT.format(items="\n".join(items)), sent


def call_gemini_confirm(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=ConfirmCheck, temperature=0),
    ).text


def check_confirm(claims: list[dict], contexts: list[dict | None], meaning: dict[int, dict],
                  call: Callable[[str], str] = call_gemini_confirm) -> tuple[str, dict[int, dict]]:
    """Return (raw reply, {claim index: result}). Replies for indexes not sent are ignored."""
    prompt, sent = build_confirm_prompt(claims, contexts, meaning)
    if not sent:
        return '{"results": []}', {}
    raw = call(prompt)
    by_index = {}
    for r in ConfirmCheck.model_validate_json(raw).results:
        if r.index - 1 in sent:
            by_index[r.index - 1] = r.model_dump(exclude={"index"})
    return raw, by_index


def assign_lane(claim: dict, meaning: dict | None, confirm: dict | None = None) -> tuple[str, list[str]]:
    """Lane and the human-readable reasons for it."""
    if not claim.get("verified"):
        return "blocked", [f"code check failed: {claim.get('reason')}"]
    always, soft = _split_reasons(claim["sentence"], claim.get("quote", ""))
    reasons = list(always)
    if meaning is None:
        reasons.append("meaning check not run")
    else:
        if meaning["verdict"] != "supported":
            reasons.append(f"meaning check: {meaning['verdict'].replace('_', ' ')}" + (f" ({meaning['issue']})" if meaning.get("issue") else ""))
        if not meaning["neutral"]:
            reasons.append("meaning check: wording may not be neutral")
    confirmed = confirm is not None and confirm["verdict"] == "approve" and confirm["neutral"]
    if soft and not confirmed:
        reasons += soft                       # a flagged word stays with a person unless the page clears it
    if confirm is not None and not confirmed:
        reasons.append("context check: held" + (f" ({confirm['issue']})" if confirm.get("issue") else ""))
    return ("review" if reasons else "ready"), reasons


def triage(claims: list[dict], meaning: dict[int, dict], confirm: dict[int, dict] | None = None) -> list[dict]:
    """One row per claim. "auto" is true when the context check ran and every check agreed."""
    confirm = confirm or {}
    out = []
    for i, c in enumerate(claims):
        lane, reasons = assign_lane(c, meaning.get(i), confirm.get(i))
        out.append({"index": i, "sentence": c["sentence"], "lane": lane, "reasons": reasons,
                    "meaning": meaning.get(i), "confirm": confirm.get(i), "auto": lane == "ready" and i in confirm})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--replay", action="store_true", help="reuse the saved AI replies")
    args = ap.parse_args()

    claims = json.loads((args.folder / "drafts.json").read_text())
    saved, saved_confirm = args.folder / "meaning_response.json", args.folder / "confirm_response.json"
    contexts = contexts_for(claims, args.folder)
    meaning: dict[int, dict] = {}
    confirm: dict[int, dict] = {}
    if args.replay:
        _, meaning = check_meaning(claims, lambda _p: saved.read_text())
        if saved_confirm.exists():
            _, confirm = check_confirm(claims, contexts, meaning, lambda _p: saved_confirm.read_text())
    else:
        load_env()
        if "GEMINI_API_KEY" not in os.environ:
            print("GEMINI_API_KEY not set: every sentence will be sent to staff review. Use --replay with saved replies.")
        else:
            try:
                raw, meaning = check_meaning(claims)
                saved.write_text(raw)
                raw, confirm = check_confirm(claims, contexts, meaning)
                saved_confirm.write_text(raw)
            except Exception as e:  # fail safe: a missing check means review, never ready
                print(f"AI check failed ({type(e).__name__}: {e}); affected sentences will go to staff review")
    result = triage(claims, meaning, confirm)
    (args.folder / "triage.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    for t in result:
        lane = "auto" if t["auto"] else t["lane"]
        print(f"{lane:8} {t['sentence'][:80]}" + (f"\n         ↳ {'; '.join(t['reasons'])}" if t["reasons"] else ""))
    auto = sum(t["auto"] for t in result)
    counts = {lane: sum(t["lane"] == lane for t in result) for lane in ("ready", "review", "blocked")}
    print(f"\n{auto} auto-approve · {counts['ready'] - auto} ready (one click) · {counts['review']} need a person · {counts['blocked']} blocked. "
          f"Run `python -m civify.record {args.folder}` to update the record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
