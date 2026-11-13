# Civify

Civify turns municipal council decisions into plain-language explanations that residents can trust. Every sentence is paired with the exact passage of the official record it came from, the code checks that passage exists before anything is shown, and City staff approve every sentence before residents see it. Residents enter an address or ward to see what is proposed near them, what stage it is at, and what the Clerk's notice says about having a say.

Built for the "Making municipal decisions easier to understand" challenge, on real City of Toronto records.

## What works today

- **Pipeline** on a folder of downloaded PDFs: extract text with page numbers → classify each file (staff report, Clerk's notice, draft by-law, Council bill, item page, declaration, public letter) → draft plain-language sentences with Gemini, each with an exact quote → verify every quote and number in code → build one `record.json` per item with three distinct stages, votes, motions and quoted participation rules.
- **Staff review screen**: each sentence beside its quote and page; approve, reject, or edit (edits are re-checked). Nothing reaches residents until a named reviewer approves it.
- **Resident view**: where the item stands, whether Council has decided, what the Clerk's notice says about taking part, what changed at Council, and the approved explanation with a source for every sentence.
- **Near me**: address or ward → items in your ward, with distance. The address is looked up on the City's own API and never stored.
- Demonstrated on item **2026.TE34.21** (191-199 College St rezoning): 10 documents classified, 19 of 19 drafted sentences verified, 23-0 Council vote and the Mayor's declared interest read from the record.

## Planned, not built

Printable one-page notice with QR code · SMS alerts · translation · two further items (transit, budget) through the pipeline · appeal stage. See [docs/limitations.md](docs/limitations.md) for the full, honest list.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 62 tests; 19 skip if the source PDFs are absent

# Pipeline (the saved Gemini reply lets you replay without a key)
python -m civify.ingest data/2026.TE34.21 --retrieved 2026-11-13
python -m civify.draft  data/2026.TE34.21 --replay     # or set GEMINI_API_KEY in .env for a live run
python -m civify.record data/2026.TE34.21
python -m civify.verify                                 # demo: watch wrong summaries get rejected

# Web app
uvicorn civify.app:app --reload          # http://127.0.0.1:8000
```

Source PDFs are not in this repository (public letters carry residents' names). The pipeline's outputs for the demo item are committed, so the app runs from a fresh clone.

## Docs

- [docs/requirements.md](docs/requirements.md) — numbered, testable requirements with status
- [docs/architecture.md](docs/architecture.md) — pipeline, class, state and sequence diagrams drawn from the code
- [docs/decisions.md](docs/decisions.md) — each design choice with alternatives and trade-offs
- [docs/sources.md](docs/sources.md) — libraries (versions, licences), data sources (dates), AI use and how it was checked
- [docs/limitations.md](docs/limitations.md) — known gaps and what a pilot would need

## How AI is used, in one paragraph

A language model writes the first draft of each resident-facing sentence and must attach the exact quote it relied on. It is never trusted: code confirms the quote exists in the PDF and that every number in the sentence appears in the quote; anything that fails is flagged for staff. Code cannot judge meaning, so a named staff reviewer reads each sentence against its quote and approves, edits (re-checked) or rejects it. Only approved sentences are published. The model never produces stages, votes or deadlines; those are read from the record or quoted verbatim.
