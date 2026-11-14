# Architecture decisions

Each entry: the choice, the alternatives considered, and the trade-off. Written as the decision was made, not after.

## D-01 · Verify quotes in code; let the AI only propose

**Choice.** The model returns sentence + exact quote; deterministic code checks the quote exists and the numbers match; a human approves.
**Alternatives.** (a) Trust the AI summary. (b) Ask a second model to grade the first. (c) No AI: staff write every summary.
**Trade-off.** (a) is what the brief warns against. (b) is AI checking AI and costs double. (c) doesn't scale to weekly council volume. The chosen design catches invented quotes and changed numbers with certainty, and routes the remaining risk (meaning drift) to a human with the evidence side by side. Tested: 0 false claims passed on the demo item.

## D-02 · Exact (normalised) matching, not fuzzy

**Choice.** Drop whitespace and dashes, straighten quotes, casefold, then exact substring.
**Alternatives.** Edit-distance or embedding similarity.
**Trade-off.** Fuzzy matching would accept a quote with "not" removed. Exact matching occasionally rejects a true quote (we saw one, across a page footer) — that fails safe. We then fixed the specific cause (strip running headers/footers; allow one page break) rather than loosening the match.

## D-03 · Cross-check numbers between sentence and quote

**Choice.** Every number in the sentence must appear in the quote.
**Why.** Numbers (storeys, units, dollars, dates) are the highest-stakes details and the easiest to distort while keeping a real quote. Caught "684 → 864" in the demo.
**Limit.** Numbers written as words and meaning changes without numbers are not caught; see D-01.

## D-04 · pypdf for extraction

**Alternatives.** PyMuPDF (faster, better layout, but AGPL — a real obstacle for a municipality), pdfplumber (MIT, heavier), hosted document AI (sends documents out, per-page cost).
**Trade-off.** pypdf is pure Python, BSD, and read all 35 pages of the demo report cleanly. It cannot OCR scans; those come back `unknown`. Extraction is one function, so swapping is a one-file change.

## D-05 · Classify by first-page template, in code

**Choice.** Pattern-match Toronto's fixed templates (`REPORT FOR ACTION`, Clerk letterhead, `BY-LAW`, `Tracking Status`); letters by the City's own filename prefix.
**Alternative.** Ask the model to classify.
**Trade-off.** Code classification is free, instant, explainable ("because page 1 starts with REPORT FOR ACTION") and testable. It is Toronto-shaped; another city adds rules. Unknown files go to staff rather than being guessed (we removed a loose content fallback after it mislabelled a fake Clerk document as a public letter).

## D-06 · Gemini with a JSON schema at temperature 0, raw reply saved

**Choice.** Structured output so parsing never guesses; temperature 0 so quotes are stable; the raw reply is committed so anyone can replay without a key.
**Alternatives.** Any other LLM (the call is one 15-line function); free-text output parsed by regex.
**Trade-off.** Model names change (configurable via `GEMINI_MODEL`). Free-tier terms may allow Google to use inputs; acceptable for public staff reports, not for a pilot.

## D-07 · JSON files as the pipeline contract; SQLite only for human decisions

**Choice.** Each step writes a file (`item.json` → `drafts.json` → `record.json`); the app reads `record.json`; only staff decisions live in SQLite.
**Alternatives.** A database for everything; or an in-memory pipeline.
**Trade-off.** Files are inspectable, diffable and re-runnable — committed outputs caught a page-attribution bug when 14 page numbers shifted. SQLite keeps the audit trail (who approved what, when) durable with zero setup. Scaling: a city with thousands of items would move the records into the database and keep the same shapes.

## D-08 · FastAPI + Jinja2 server-rendered HTML, no JavaScript framework

**Alternatives.** React/Vue single-page app; Streamlit.
**Trade-off.** Server-rendered pages are accessible by default (real forms, real links, works without JS), testable with one HTTP client, and understandable by the whole team. A SPA would be prettier and slower to build. Streamlit can't do the approval workflow cleanly.

## D-09 · Geocode via the City's own API; store nothing

**Choice.** Send the typed address to Toronto's Address Points API for one request; use the ward and coordinate; keep no record.
**Alternatives.** (a) Download the full address dataset (~500k rows) and match locally. (b) A third-party geocoder (Google, Nominatim). (c) Postal-code prefixes.
**Trade-off.** (a) is heavy for a hackathon but is the pilot answer (no outbound call). (b) sends residents' addresses to a third party. (c) is too coarse (a 3-character prefix spans wards). The City already holds every address, so asking it which ward one is in adds no new exposure.

## D-10 · Hand ingestion of items; everything after is automated

**Why.** `secure.toronto.ca` returns 403 to automated clients and there is no public API. Rather than scrape around it, the demo ingests saved pages and PDFs by hand and states this. A pilot gets items from the Clerk's office by upload or feed. The pipeline from upload onward is fully automated and generic.

## D-11 · "What changed" from the motions, not a text diff

**Choice.** Show Council's motions with their text.
**Alternative.** Diff committee recommendations against the Council decision.
**Trade-off.** The diff was noisy (flagged "191-199" vs "191 to 199") and missed the substantive change; the motions state exactly what was altered, by whom, and whether it carried — and they are the record's own explanation.

## D-12 · Confirm item identity independently of the meeting year

The November 2026 Preservation Board agenda uses 2027 item IDs. The parser retains a short ID when the full ID is absent, rather than constructing a URL from the meeting year. A local record resolves an agenda entry only when short ID, body, meeting date and ward agree. This leaves some entries without direct links but prevents navigation to an unrelated or nonexistent item.

## D-13 · Printable notices retain evidence and use official-page QR codes

The print route uses the resident approval gate and includes complete approved sentences and their source quotes. Segno generates QR SVG locally, pointing to the official City item page so a phone does not need access to the demo's localhost. Long content can span multiple pages; fitting it by truncation could remove a condition or citation. Physical print layout and QR scanning still require manual verification.

## D-12 · One meaning-check call and risk rules, not a multi-agent pipeline

**Choice.** Keep the drafter, add one second model call per item that judges each sentence against its own quote, plus plain-code risk rules. Route sentences into ready / review / blocked lanes.
**Alternatives.** (a) A four-agent pipeline (curator, validator, impact & personalisation, engagement guide). (b) Send every sentence to a person (status quo). (c) Publish ready sentences with no human action.
**Trade-off.** (a) adds cost, latency and failure points; its "impact level" and demographic matching would put AI judgement on political decisions and need personal data, against the brief's neutrality and data-minimisation constraints; stages and participation are already read from the record, so an engagement agent would only add risk. (b) was the friction staff asked us to remove: on the real items, 18 of 43 sentences were ready for one-click approval under the first rule, 31 of 43 under D-17. (c) removes the one human signature the brief's "checked against the records" rule relies on; one click per item keeps it nearly frictionless. The meaning check fails safe: if it errors or isn't run, everything goes to review.

## D-13 · Local accounts with server-side sessions

**Choice.** Individual accounts, scrypt password hashes (standard library), random session tokens stored in SQLite, HttpOnly SameSite=Lax cookie.
**Alternatives.** One shared staff password; signed-cookie sessions (needs another library and can't be revoked server-side); City single sign-on.
**Trade-off.** A shared password gives no real audit trail. Server-side sessions end the moment a user signs out or is removed. SSO is the pilot answer but needs the City's identity provider; the app only asks "who is signed in", so swapping it in touches one module.

## D-14 · Approvals bound to content, with an append-only audit log

**Why.** Reviews used to be keyed by claim position. Re-running the drafter could silently attach an old approval to a new sentence. Each decision now stores a hash of sentence + quote + source checksum; a mismatch sends the sentence back to review, and every decision is appended to an audit table that is never updated.

## D-15 · Published versions instead of live approvals

**Choice.** Approving a sentence no longer shows it to residents. A worker publishes a numbered version: a frozen copy of the approved sentences with their quotes and sources (no lanes, reasons, notes or reviewer names).
**Why.** It gives the City one deliberate "this is what we're telling residents" moment per item, an exact record of what residents saw and when, and stops a half-reviewed item from leaking out sentence by sentence.

## D-16 · Steps, not "agents"; reasons, not confidence scores; no assignment yet

A review prompt asked for per-agent progress, numeric confidence and assigned workers. The pipeline has six steps, two of which use AI, so the Processing page shows those steps honestly rather than a fictional agent chain. A model-produced "87% confident" would be false precision; each sentence instead carries its lane and the plain-language reasons for it. Assignment adds accounts, notifications and permissions the hackathon doesn't need; the dashboard shows who last acted on each item.

## D-17 · Risk words need a person only when the passage doesn't echo them

**Choice.** The code risk rules first sent any sentence containing a decision, condition or hedge word to a person. Now those words route to a person only when the quoted passage has no word of the same kind: "must" with no requirement in the passage, "may" with no hedge, "recommend" with no recommendation. Taking part and deadlines still always go to a person. The AI meaning check still has to say "supported".
**Alternatives.** (a) Keep the strict rule (24 of 43 real sentences waited for a person, most of them "Staff recommend…" beside a passage that says "recommends"). (b) Drop the risk rules and trust the meaning check alone.
**Trade-off.** (a) is the friction workers complained about and it buries the few real problems among routine ones. (b) leaves a single model judgement between a sentence and residents on the details that change what a resident does. The echo rule is deterministic and explainable on the card ("states a condition that the source passage does not"); on the real items, every sentence it leaves in review is one the meaning check also flagged or one that attributes a recommendation the passage doesn't make.

## D-18 · Lead the reviewer to the passage, don't just name the page

**Choice.** Each card shows the page's own text around the quote with the quote highlighted, and a link that opens the PDF at that page. The excerpt comes from the same extracted text the verifier searched, with headers and footers removed; matching tolerates line breaks, hyphenation, dashes and curly quotes but is otherwise exact.
**Alternatives.** (a) Name the file and page and leave the reviewer to open the PDF and search. (b) Embed a PDF viewer with coordinates highlighted.
**Trade-off.** (a) is what the first version did; reviewers told us it made every check a hunt. (b) needs text-position extraction and a viewer, and still breaks on scanned pages. The excerpt gives the surrounding paragraph in one glance, and the PDF link covers the cases where layout matters.
