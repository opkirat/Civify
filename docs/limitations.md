# Known limitations and gaps

Running log. Each entry says what the gap is, whether it fails safe, and what a pilot would need. Feeds the "limitations" and "pilot next steps" sections of the readiness report.

## Verification

- **Meaning drift is not caught by code.** A real quote under a sentence that contradicts it (e.g. "refuse" vs "approve", a dropped "not" or condition) passes the verifier. Numbers are checked; wording is not. *Mitigation:* staff see sentence and quote side by side and must approve before publication. *Pilot:* a second, independent model check ("does this quote support this sentence?") would reduce staff load but is still AI checking AI.
- **Quotes may span at most one page break.** Running headers/footers are stripped first. A quote across three pages fails (safe: flagged, not shown).
- **Matching ignores hyphens, dashes and whitespace.** So "490-unit" and "490 unit" are equal. Judged safe because numbers are checked separately.

## Classification and parsing

- **Rules have been exercised on three items (TE34.21, PB1.5 and PB1.6).** Staff report and Clerk's notice rules rest on City templates and should carry over; the by-law, declaration-of-interest and item-page parsers are the likely ones to break on other items. Unrecognised files come back `unknown` (safe) rather than mislabelled.
- **The record parser is Toronto-shaped.** It keys on TMMIS headings ("City Council Decision", "Community Council Recommendations", "Vote (...)"). Another municipality needs its own parser producing the same `record.json` shape.
- **Image-only (scanned) PDFs are not read.** They come back `unknown` with a note that OCR is needed.
- **The "council bill" is not the enacted by-law.** It still has placeholders (`[###]`). The enacted by-laws are fetched separately (`civify/fetch.py`) and form the fourth stage, which is also where Strong Mayor written approval ("Mayoral Decision N-YYYY") is recorded.

## Participation

- **Participation is quoted, never computed.** The app never derives a deadline. The Council outcome and next meeting are read from Tracking Status. A scheduled meeting does not establish an open comment window. Pending item pages explicitly show when no item-specific participation rule was found.
- **Saved snapshots are not automatically refreshed.** The notices include a Kennedy Road speaker-registration rule dated November 24, 2026; the PB records list a November 16 meeting but no item-specific deadline. Neither a saved notice nor a general participation rule confirms current availability. Staff must check the official item page before presenting a window as open.
- **Agenda IDs are not meeting years.** The November 2026 PB agenda contains 2027 item IDs. When a full ID is missing, the app retains the short ID and offers the City agenda index; it resolves a local item only when short ID, body, meeting date and ward agree.

## Data and access

- **Toronto's council site blocks automated access** (HTTP 403), and we do not try to get around that (a headless-browser workaround was considered and rejected). A person saves the item or agenda page; `civify/fetch.py` then downloads every PDF it links to from the open `legdocs` host. *Pilot:* the Clerk's office uploads pages, or provides a feed.
- **Source PDFs are not in the public repo** because public letters carry residents' names. `item.json`, `drafts.json` and `record.json` are tracked; they contain no resident names (letters are counted, not named).
- **The Gemini model name is configurable (`GEMINI_MODEL`)** because Google renames models; the default worked on first run but may lapse.
- **Free-tier Gemini keys may permit Google to use inputs.** Staff reports are public records, so acceptable for the demo; a pilot should use a paid tier or an on-premise model.

## App

- **Reviewer identity is a typed name, not a login.** Enough for a demo; a pilot needs municipal SSO.
- **Amendment view is verbatim, not a semantic diff.** Staff and resident screens show Council motions and their text. There is no automatic plain-language comparison of versions.
- **No translation or SMS.** Printable notices with local QR generation are implemented; full approved sentences and quotes are retained, so lengthy notices can exceed one page. The UI refresh was checked in headless Chrome at desktop and 390px phone widths, and a sample print PDF was generated. Physical QR scanning and a full accessibility audit remain pending.
- **Review decisions are keyed by claim index.** Replacing or reordering drafts after review can associate an old approval with a new claim. Do not regenerate reviewed items without clearing their reviews; a pilot needs content-bound approvals and review history.
- **Official coordinates can be wrong.** The earlier source inspection found a Kennedy Road notice geocoded to Kennedy Avenue. Ward matching is useful context but does not establish parcel-level impact.
