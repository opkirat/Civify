# Known limitations and gaps

Running log. Each entry says what the gap is, whether it fails safe, and what a pilot would need. Feeds the "limitations" and "pilot next steps" sections of the readiness report.

## Verification

- **Meaning drift is not caught by code alone.** A real quote under a sentence that contradicts it passes the code verifier. *Now mitigated twice:* risk rules send any sentence stating a decision, condition, uncertainty or deadline to a person, and a second model call (the meaning check, `civify/triage.py`) judges whether each quote fully supports its sentence. On the demo "Staff recommend refusing" under a real approval quote, both fired. *Remaining limit:* the meaning check is AI checking AI and can be wrong in both directions (on the 43 real sentences it flagged some that a person may judge fine, e.g. "staff recommend" when the cited passage is the recommendation list itself). Since D-19/D-20, a sentence that passes the code checks and both AI checks goes live without a person; anything about taking part or deadlines never does. The error rate of that path has not been measured; `CIVIFY_AUTO_APPROVE=0` turns it off so a person approves every sentence.
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

- **Processing runs inside the web server process.** A run started from the browser executes as a background task. If the server stops mid-run, the job stays "running"; Retry resumes it from the unfinished step. A pilot would use a proper job queue.
- **No assignment of items to workers.** The dashboard shows who last touched each item; assigning work, notifications and role-based permissions are pilot next steps.
- **The AI summary is a compression.** It is built only from verified sentences and checked by code and a second AI, but a shorter text can still lose emphasis or context that no single check catches. It is labelled AI-generated, and the verified sentences and the official page are one tap away. It reflects the staff report's sentences, so for a decided item it can read as "staff recommend" while the stage shown above says Council decided.
- **Automatic approval relies on the AI checks being right when they agree.** Both checks use the same model family, so they can share a blind spot. Safeguards: the quote and every number are checked by code; taking part and deadlines never auto-approve; any AI error sends sentences to a person; automatic approvals are labelled on the staff screen, and a person can take any sentence down with one click (the resident page updates straight away). Because nobody reads an auto-approved sentence before residents do, a wrong one is live until someone notices. A pilot should measure the false-approval rate on a hand-labelled sample before relying on it, and could use a different model for the second check.
- **The in-context excerpt is extracted text, not the page image.** Tables and multi-column layouts can read out of order, and a quote that straddles two pages shows as one run of text. The link to the PDF at that page is the authority when layout matters; `#page=N` is honoured by the built-in PDF viewers in Chrome, Edge, Firefox and Safari.
- **Uploads are validated, not virus-scanned.** Files must start with the PDF signature, are size-limited and are parsed in-process. A pilot should scan uploads and run parsing in an isolated worker.

- **Staff sign-in is local accounts** (`civify/auth.py`: scrypt-hashed passwords, server-side sessions, 12-hour expiry). Real reviewer identity is now recorded on every decision and in an append-only audit log. A pilot would replace it with the City's single sign-on and add roles (e.g. who may publish vs. draft). No CSRF token is used; the session cookie is SameSite=Lax, which blocks cross-site form posts in current browsers.
- **Approvals are bound to content.** A decision counts only for the exact sentence, quote and source file it was made on. Re-running the pipeline sends changed sentences back to review. Approvals made before this change have no content hash and no longer count.
- **Amendment view is verbatim, not a semantic diff.** Staff and resident screens show Council motions and their text. There is no automatic plain-language comparison of versions.
- **SMS is a demo until a provider is configured.** Ward signup, confirmation, STOP handling, and staff-reviewed dispatch are implemented. Real carrier delivery and webhook operation have not been exercised. See [sms.md](sms.md). Translation is not implemented. Printable notices with local QR generation are implemented; full approved sentences and quotes are retained, so lengthy notices can exceed one page. Physical QR scanning and a full accessibility audit remain pending.
- **Review decisions are keyed by claim index.** Replacing or reordering drafts after review can associate an old approval with a new claim. Do not regenerate reviewed items without clearing their reviews; a pilot needs content-bound approvals and review history.
- **Official coordinates can be wrong.** The earlier source inspection found a Kennedy Road notice geocoded to Kennedy Avenue. Ward matching is useful context but does not establish parcel-level impact.
