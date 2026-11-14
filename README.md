# Civify

Civify turns municipal council decisions into plain-language explanations that residents can trust. Every sentence is paired with the exact passage of the official record it came from, the code checks that passage exists before anything is shown, and a named reviewer approves every sentence before residents see it. Residents enter an address or ward to see what is proposed near them, what stage it is at, and what the Clerk's notice says about having a say.

Built for the "Making municipal decisions easier to understand" challenge, on real City of Toronto records.

## What works today

- **Pipeline** on a folder of downloaded PDFs: extract text with page numbers → classify each file (staff report, Clerk's notice, draft by-law, Council bill, item page, declaration, public letter) → draft plain-language sentences with Gemini, each with an exact quote → verify every quote and number in code → build one `record.json` per item with distinct staff, committee and Council stages, enacted by-laws where available, votes, motions and quoted participation rules.
- **Add documents in the browser**: workers upload the staff report or the saved item page; each file is validated (PDF, pages, record type, OCR need, duplicates and report versions) before anything is processed. A **Processing** page shows each pipeline step running, preliminary outputs, and Retry.
- **Publishing versions**: residents only see a published, numbered version of approved sentences; reviewer names and internal notes never leave the staff side. Workers can **escalate** a sentence with an internal note.
- **Staff workspace** (sign-in required): a searchable, filterable dashboard of every item and a linked list of exactly what needs a person. Sentences are sorted into **ready** (passed the source check, the AI meaning check and the risk rules: publish all with one click), **needs a look** (with the reasons), and **blocked** (failed the source check). Nothing reaches residents until a signed-in reviewer approves it; approvals are bound to the exact sentence and evidence, and every decision is logged.
- **Resident view**: where the item stands, whether Council has decided, what the Clerk's notice says about taking part, what changed at Council, and the approved explanation with a source for every sentence.
- **Near me**: address or ward → items in your ward, with distance. The address is looked up on the City's own API and never stored.
- **Three saved item records**: `2026.TE34.21` (College Street rezoning, enacted); `2027.PB1.5` (19 Don Ridge Drive heritage designation); and `2027.PB1.6` (1337 Queen Street West demolition/new construction). The latter two records list a November 16, 2026 board meeting, with no board or Council decision yet. Their item IDs really use 2027; a meeting's year cannot determine its item IDs.
- **Revised reports**: PB1.5 has three versions; drafting uses the newest dated report, November 13, 2026. Stored quote/number checks passed for 19/19 TE34.21 claims, 12/13 PB1.5 claims and 11/11 PB1.6 claims. Passing these checks does not establish meaning or staff approval.
- **Public notices and agendas**: 14 saved Clerk notices and the six-item Preservation Board agenda, retrieved November 13, 2026. General participation rules are quoted separately from item-specific notices; no deadlines are calculated from meetings. Confirmed items link to their Civify record.
- **Printable notice with QR code**: open an item's “Printable notice” link, then print or save as PDF. It includes approved sentences and full source quotes; the QR opens the official City item page. Long explanations may span multiple pages.

## Planned, not built

SMS alerts · translation · transit/budget examples · appeal stage · guaranteed one-page print layout. See [docs/limitations.md](docs/limitations.md) for the full, honest list.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # PDF-dependent checks skip when sources are absent

# Pipeline (the saved Gemini reply lets you replay without a key)
python -m civify.ingest data/2026.TE34.21 --retrieved 2026-11-13
python -m civify.draft  data/2026.TE34.21 --replay     # or set GEMINI_API_KEY in .env for a live run
python -m civify.triage data/2026.TE34.21 --replay    # meaning check + lanes (live without --replay)
python -m civify.record data/2026.TE34.21
python -m civify.verify                                 # demo: watch wrong summaries get rejected

# Web app
python -m civify.auth add yourname --name "Your Name"   # create a staff account (prompts for a password)
uvicorn civify.app:app --reload          # http://127.0.0.1:8000, staff sign in at /staff
```

Source PDFs are excluded from Git (public letters carry residents' names). The JSON records let the app display items without PDFs; drafting, replaying and approving require the original staff reports locally. Review decisions are in the local `civify.db`, not shared through Git. Staff accounts are local to `civify.db`; a pilot would use the City's single sign-on.

For a new item, save its official page as `data/<actual-item-id>/Agenda_Item_History.pdf`, run `python -m civify.fetch data/<actual-item-id>`, then `ingest`, `draft` and `record` as above. For a saved agenda, run `python -m civify.agenda data/agendas/<file>.pdf --retrieved YYYY-MM-DD`. Only full IDs confirmed by sources receive direct item links.

## Docs

- [docs/testing.md](docs/testing.md) — five-minute resident/reviewer walkthrough
- [docs/handoff.md](docs/handoff.md) — current state, constraints and next actions
- [docs/requirements.md](docs/requirements.md) — numbered, testable requirements with status
- [docs/architecture.md](docs/architecture.md) — pipeline, class, state and sequence diagrams drawn from the code
- [docs/decisions.md](docs/decisions.md) — each design choice with alternatives and trade-offs
- [docs/sources.md](docs/sources.md) — libraries (versions, licences), data sources (dates), AI use and how it was checked
- [docs/limitations.md](docs/limitations.md) — known gaps and what a pilot would need

## How AI is used, in one paragraph

A language model writes the first draft of each resident-facing sentence and must attach the exact quote it relied on. It is never trusted: code confirms the quote exists in the PDF and that every number in the sentence appears in the quote; anything that fails is flagged for staff. Code cannot judge meaning, so a named staff reviewer reads each sentence against its quote and approves, edits (re-checked) or rejects it. Only approved sentences are published. The model never produces stages, votes or deadlines; those are read from the record or quoted verbatim.
