# Civify

Two-day hackathon build. Residents enter a location and see Toronto council items near them: what is proposed, what stage it is at, and whether they can still have a say. Every claim is tied to the source record.

- Requirements: [.claude/skills/civify-context/brief.md](.claude/skills/civify-context/brief.md) (the challenge statement, verbatim)
- Judging: [.claude/skills/civify-context/rubric.md](.claude/skills/civify-context/rubric.md) (verbatim). The weights are Project 40, Software 20 and Presentation 40. The report and video are deliverables, not an afterthought.

## What the rubric demands of the code (aim for "5 · Excellent")

| Criterion | Points | What it means for the build |
|---|---|---|
| Stakeholders | 10 | Serve residents **and** staff (review console) **and** offline people (print/SMS). Document harms and trade-offs. |
| Quality and functionality | 15 | The core workflow must really work, with outputs checked by code. Only tertiary features may be mocked. Show data limits and incomplete features **in the UI**. |
| Design and feasibility | 10 | A novice completes the task with no help: plain language, WCAG 2.2 AA, mobile-first, in-app guidance. |
| Impact | 5 | Nothing Toronto-specific in the core. Isolate city-specific parts (scrapers, ward data) behind adapters so another municipality can plug in. |
| Requirements and UML | 5 | Requirements are numbered and testable (`docs/requirements.md`). Tests reference requirement IDs. UML must match the code, so update the diagrams when the design changes. |
| Architecture rationale | 5 | Record each major choice with the alternatives considered and the trade-offs (`docs/decisions.md`): maintainability, testability, scalability. |
| Code awareness | 5 | The team must be able to explain and modify every file. Keep code small and readable. Explain non-obvious choices in comments or commit messages. Add tests proving behaviour. |
| References | 5 | `SOURCES.md` lists every library with its version and licence, every data source with a retrieval date, and every AI use with how it was verified. |
| Readiness report | 20 | Written for a municipal audience: needs → evidence → results → recommendations → pilot next steps. Sources and limitations are explicit. |
| Demo video | 20 | Tells a story, shows the core workflow and clearly separates working features from planned ones. Show the verifier catching a wrong summary. |

## Non-negotiables (never cut these)

1. **Verified claims.** Each summary sentence carries an exact quote from the source. Code checks that the quote exists in the source text. Anything that fails is dropped or shown as "unverified". Never display an unchecked AI sentence as fact.
2. **Explicit stages.** Staff recommendation → committee decision → council decision → closed or appeal. Stages are read from the record and never inferred. Keep staff, committee and council text distinct.
3. **Deadlines only from the official item page,** with a "last verified" date. Never derive a deadline from a meeting date. If none is found, say so and link out.
4. **Staff approval before publishing.** Nothing reaches residents (web or SMS) until staff approve it.
5. **Neutral, plain language.** Non-partisan. Preserve conditions and uncertainty. Show no personal info from public correspondence.

## Data minimization

Store no street addresses. Geocode, then discard. SMS subscribers: phone number, three-character postal area code (e.g. M5V) and language only.

## Stack

Python 3.13 with FastAPI, SQLite, a simple frontend, and Twilio for SMS (trial account).

## Logging rule

Every new library (version and licence), data source (URL and retrieval date) and AI use (what it did and how it was checked) goes into [SOURCES.md](SOURCES.md) when you add it, not at the end.

## Scope

Three pre-ingested real Toronto items: zoning or development, fee or budget, and bike lane or transit. At least one item should have been amended and one should have an open comment window. Live parsing of arbitrary council items is out of scope and is a stated limitation. If behind schedule, cut in this order: translation, notifications, the amendment diff.
