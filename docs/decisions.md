# Architecture decisions

Each entry: the choice, the alternatives considered, and the trade-off. Written as the decision was made, not after; when a later decision replaces part of an earlier one, the earlier entry says so and is kept. D-22 and D-23 were added out of order and are listed last.

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

## D-12 · One meaning-check call and risk rules, not a multi-agent pipeline

**Choice.** Keep the drafter, add one second model call per item that judges each sentence against its own quote, plus plain-code risk rules. Route sentences into ready / review / blocked lanes.
**Alternatives.** (a) A four-agent pipeline (curator, validator, impact & personalisation, engagement guide). (b) Send every sentence to a person (status quo). (c) Publish ready sentences with no human action.
**Trade-off.** (a) adds cost, latency and failure points; its "impact level" and demographic matching would put AI judgement on political decisions and need personal data, against the brief's neutrality and data-minimisation constraints; stages and participation are already read from the record, so an engagement agent would only add risk. (b) was the friction we hit reviewing the items ourselves: on the real items, 18 of 43 sentences were ready for one-click approval under the first rule, 31 of 43 under D-17. (c) removes the one human signature the brief's "checked against the records" rule relies on; one click per item keeps it nearly frictionless. The meaning check fails safe: if it errors or isn't run, everything goes to review.
**Later.** Option (c) was revisited in D-19 with a second, differently framed AI check added; the one-click button remains for when automatic approval is turned off (`CIVIFY_AUTO_APPROVE=0`).

## D-13 · Local accounts with server-side sessions

**Choice.** Individual accounts, scrypt password hashes (standard library), random session tokens stored in SQLite, HttpOnly SameSite=Lax cookie.
**Alternatives.** One shared staff password; signed-cookie sessions (needs another library and can't be revoked server-side); City single sign-on.
**Trade-off.** A shared password gives no real audit trail. Server-side sessions end the moment a user signs out or is removed. SSO is the pilot answer but needs the City's identity provider; the app only asks "who is signed in", so swapping it in touches one module.

## D-14 · Approvals bound to content, with an append-only audit log

**Why.** Reviews used to be keyed by claim position. Re-running the drafter could silently attach an old approval to a new sentence. Each decision now stores a hash of sentence + quote + source checksum; a mismatch sends the sentence back to review, and every decision is appended to an audit table that is never updated.

## D-15 · Published versions instead of live approvals

**Choice.** Approving a sentence no longer shows it to residents. A worker publishes a numbered version: a frozen copy of the approved sentences with their quotes and sources (no lanes, reasons, notes or reviewer names).
**Later.** Replaced by D-20: approving now publishes. Frozen numbered versions remain.
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
**Trade-off.** (a) is what the first version did; in our own review it made every check a hunt through the PDF. (b) needs text-position extraction and a viewer, and still breaks on scanned pages. The excerpt gives the surrounding paragraph in one glance, and the PDF link covers the cases where layout matters.

## D-19 · Approve automatically when two AI checks and the code agree; people publish

**Choice.** Add a second AI call that reads each sentence against the whole page around its quote, is told that an approval goes to residents with no person reading it first, and is told to hold when in doubt. When the code checks pass, the first AI check says "supported and neutral", the second says "approve", and the sentence is not about taking part or a deadline, the sentence is approved automatically under the name `auto-check`. A person can reject or edit any automatic approval. (As first built, a person still clicked Publish; D-20 removed that step.) Held sentences come with suggested wording that is re-verified before it can be saved.
**Alternatives.** (a) Keep a person approving every sentence, with one click for the ready ones (D-12). (b) Approve on the first AI check alone. (c) Publish automatically as well.
**Trade-off.** (a) left 43 decisions across three items. Most of those clicks were rubber stamps. (b) puts one model judgement between a sentence and residents. Two differently framed reads (the quote alone, then the page) plus the deterministic quote and number checks catch more than either check alone. On the real items, every held sentence named a real slip: a proposal stated as fact, a dropped condition, an attribution the page doesn't make. (c) would remove the last person accountable for what residents see. With this design a person reviews about 4 sentences per item. On the first three items: 32 of 43 approved automatically, 10 needed a person, 1 blocked; across all 8 items: 88 of 119 automatic, 25 flagged, 6 blocked.

## D-20 · Approving is publishing

**Choice.** A sentence goes live for residents as soon as it is approved: automatically when every check agrees (D-19), or when a worker clicks Approve. Rejecting or editing updates the resident page the same way. Each change still creates a new frozen, numbered version (D-15), so the record of what residents saw and when is kept. The separate Publish step is gone from the worker's screen.
**Alternatives.** (a) Keep "approve, then publish" (D-15). (b) Publish automatically only for AI approvals, and keep the Publish button for staff decisions.
**Trade-off.** In our own testing, (a) was confusing: an approved sentence moved to "decided" but residents still couldn't see it. (b) keeps two ways for a sentence to go live, which is the same confusion. The cost of this design is that no person signs off on a version as a whole, and auto-approved sentences reach residents without anyone reading them. The safeguards are the code checks, two AI checks, the rule that taking part and deadlines never auto-approve, one-click takedown, and the full version history.

## D-21 · An AI summary for residents, built only from verified sentences

**Choice.** The resident page leads with a two- or three-sentence summary, labelled "AI-generated", with a note saying how it was made and that the sentences and official page are the authority. The summary is written only from sentences that are already live, and each summary sentence cites the ones it uses. Code checks that every citation is live and that every number appears in the cited sentences. A second AI call, told it is the last check before residents and to hold when in doubt, must approve each summary sentence. If either check fails, the writer gets the reasons and one more try. No person approves the summary. Expanding it shows every verified sentence with its source quote.
**Alternatives.** (a) No summary, only the sentence list. (b) Staff choose one to three sentences as "key points" (an approach tried and withdrawn). (c) A summary written from the whole report.
**Trade-off.** (a) is accurate but long: 8 to 22 sentences is a lot to read on a phone. (b) puts a manual step back in front of every item, which is the friction this design set out to remove. (c) cannot be traced back to evidence sentence by sentence. Building from live sentences means the summary cannot introduce a fact that hasn't already passed the source checks, and citations let it be withdrawn the moment a sentence it relies on is rejected. On the real items, the guardrail held drafts that said "will create" where the report says "proposed to create", and that stated a staff recommendation as settled. After one repair, 7 of 8 summaries passed; the eighth falls back to the sentence list.

## D-22 · Confirm item identity independently of the meeting year

The November 2026 Preservation Board agenda uses 2027 item IDs. The parser retains a short ID when the full ID is absent, rather than constructing a URL from the meeting year. A local record resolves an agenda entry only when short ID, body, meeting date and ward agree. This leaves some entries without direct links but prevents navigation to an unrelated or nonexistent item.

## D-23 · Printable notices retain evidence and use official-page QR codes

The print route uses the resident approval gate and includes complete approved sentences and their source quotes. Segno generates QR SVG locally, pointing to the official City item page so a phone does not need access to the demo's localhost. Long content can span multiple pages; fitting it by truncation could remove a condition or citation. Physical print layout and QR scanning still require manual verification.

## D-24 · Text alerts go out automatically

**Choice.** When an item first has a live explanation, its ward's confirmed subscribers get a text with no staff step (city-wide items go to every subscriber). A new subscriber is texted what is already live in their ward right after confirming, up to three items. Staff keep a "send now" button only for when an automatic send didn't happen.
**Alternatives.** (a) Staff read and send every alert (the first version). (b) A daily digest instead of per-item texts.
**Trade-off.** (a) added a manual step after publishing, which is the friction D-19 and D-20 removed for sentences. The alert text carries no AI-written content: it names the place, the ward and the official link, built in code from the record, so there is nothing new for a person to check; the explanation it points to has already passed its checks. (b) is gentler on phones but delays news residents may want quickly; the one-alert-per-phone-per-day limit gives most of that benefit. Catch-up texts don't count toward the daily limit, so the next new item still arrives.

