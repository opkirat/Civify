# Known limitations and gaps

Running log. Each entry says what the gap is, whether it fails safe, and what a pilot would need. Feeds the "limitations" and "pilot next steps" sections of the readiness report.

## Verification

- **Meaning drift is not caught by code.** A real quote under a sentence that contradicts it (e.g. "refuse" vs "approve", a dropped "not" or condition) passes the verifier. Numbers are checked; wording is not. *Mitigation:* staff see sentence and quote side by side and must approve before publication. *Pilot:* a second, independent model check ("does this quote support this sentence?") would reduce staff load but is still AI checking AI.
- **Quotes may span at most one page break.** Running headers/footers are stripped first. A quote across three pages fails (safe: flagged, not shown).
- **Matching ignores hyphens, dashes and whitespace.** So "490-unit" and "490 unit" are equal. Judged safe because numbers are checked separately.

## Classification and parsing

- **Rules were fitted to one item (2026.TE34.21).** Staff report and Clerk's notice rules rest on City templates and should carry over; the by-law, declaration-of-interest and item-page parsers are the likely ones to break on other items. Unrecognised files come back `unknown` (safe) rather than mislabelled.
- **The record parser is Toronto-shaped.** It keys on TMMIS headings ("City Council Decision", "Community Council Recommendations", "Vote (...)"). Another municipality needs its own parser producing the same `record.json` shape.
- **Image-only (scanned) PDFs are not read.** They come back `unknown` with a note that OCR is needed.
- **The "council bill" is not the enacted by-law.** It still has placeholders (`[###]`). The enacted by-laws are fetched separately (`civify/fetch.py`) and form the fourth stage, which is also where Strong Mayor written approval ("Mayoral Decision N-YYYY") is recorded.

## Participation

- **Participation is quoted, never computed.** The app never derives a deadline. The only derived field is `council_has_decided`, read from the Tracking Status line. For a live item the app says "check the official item page", which is honest but thin.
- **No open-window item yet.** TE34.21 is decided. 673-679 Coldstream Ave (community meeting 2026-12-14) is a candidate.

## Data and access

- **Toronto's council site blocks automated access** (HTTP 403), and we do not try to get around that (a headless-browser workaround was considered and rejected). A person saves the item or agenda page; `civify/fetch.py` then downloads every PDF it links to from the open `legdocs` host. *Pilot:* the Clerk's office uploads pages, or provides a feed.
- **Source PDFs are not in the public repo** because public letters carry residents' names. `item.json`, `drafts.json` and `record.json` are tracked; they contain no resident names (letters are counted, not named).
- **The Gemini model name is configurable (`GEMINI_MODEL`)** because Google renames models; the default worked on first run but may lapse.
- **Free-tier Gemini keys may permit Google to use inputs.** Staff reports are public records, so acceptable for the demo; a pilot should use a paid tier or an on-premise model.

## App

- **Reviewer identity is a typed name, not a login.** Enough for a demo; a pilot needs municipal SSO.
- **No "what changed" (amendment) view yet.** The record holds committee recommendations and the Council decision text, so the diff is one step away.
- **No translation, no SMS, no print notice yet.** Planned; see README for the honest working-vs-planned split.
