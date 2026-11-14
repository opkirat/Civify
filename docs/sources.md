# Sources, references and AI use

Kept current as the work happens. Covers the rubric's references criterion: libraries with versions and licences, data sources with retrieval dates, and how AI was used and checked.

## Libraries (direct dependency constraints in `pyproject.toml`)

| Library | Version | Licence | Used for |
|---|---|---|---|
| Python | 3.13.7 | PSF-2.0 | runtime |
| pypdf | 7.0.1 | BSD-3-Clause | PDF text extraction (`civify/extract.py`) |
| google-genai | 3.3.0 | Apache-2.0 | calling Gemini to draft sentences (`civify/draft.py`) |
| pydantic | 2.14.3 | MIT | schema for the model's JSON reply (`civify/draft.py`) |
| FastAPI | 0.121.2 | MIT | web app (`civify/app.py`) |
| Starlette | 0.49.3 | BSD-3-Clause | FastAPI's underlying framework |
| uvicorn | 0.38.0 | BSD-3-Clause | web server |
| Jinja2 | 3.1.6 | BSD-3-Clause | HTML templates |
| python-multipart | 0.0.20 | Apache-2.0 | HTML form parsing |
| Segno | 1.6.6 | BSD-3-Clause | QR SVG generated locally from the official item URL |
| pytest | 9.2.0 | MIT | tests (dev only) |
| httpx | 0.28.1 | BSD-3-Clause | test client (dev only) |

Standard library only: `sqlite3` (review decisions), `re`, `json`, `hashlib`, `unicodedata`, `difflib`, `urllib`.

## Algorithms written for this project

| What | Where | Note |
|---|---|---|
| Quote matching: NFKC + casefold, drop whitespace and dashes, straighten quotes, exact substring on one page or two adjacent pages | `civify/verify.py` | Fuzzy matching deliberately rejected; see decisions D-02 |
| Running header/footer detection: lines repeating on ≥ half the pages with digits masked | `civify/verify.py` | |
| Number cross-check: every number in the sentence must appear in the quote | `civify/verify.py` | |
| Document classification by first-page template | `civify/classify.py` | Rules listed in the file |
| Haversine distance | `civify/geo.py` | Standard formula |

## Data sources

| Source | URL | Retrieved | Used for | Limitations |
|---|---|---|---|---|
| Agenda item 2026.TE34.21 (item page, staff report, notice, by-laws, letters) | https://secure.toronto.ca/council/agenda-item.do?item=2026.TE34.21 and linked `toronto.ca/legdocs/mmis/2026/te/...` PDFs | 2026-11-13 | the demo item | Site blocks automated access; saved by hand |
| Agenda items 2027.PB1.5 and 2027.PB1.6 | https://secure.toronto.ca/council/agenda-item.do?item=2027.PB1.5 and https://secure.toronto.ca/council/agenda-item.do?item=2027.PB1.6 | 2026-11-13 | pending decisions; PB1.5 revised reports | Saved pages, not a live status check; item year differs from meeting year |
| Preservation Board meeting agenda | https://secure.toronto.ca/council/#/committees/3032/28421 | 2026-11-13 | six items for November 16, saved in `data/agendas/2026-11-16-PB1.pdf` | Printed agenda lost full item links; only PB1.5 and PB1.6 resolved against saved item records |
| Public Notices | https://open.toronto.ca/dataset/public-notices/ | 2026-11-13 | 14 saved notices, Clerk text and participation wording | Snapshot; coordinates can be incorrect |
| Participate in Council and Committee Meetings | https://www.toronto.ca/city-government/council/council-committee-meetings/participate/ | 2026-11-13 | general rules quoted in `data/official/participate.json` | General rules are not verified item-specific deadlines |
| City Wards | https://open.toronto.ca/dataset/city-wards/ (CKAN resource `7672dac5-…`) | 2026-11-13 | ward names (`data/wards.json`) | 25-ward model (2018) |
| Address Points (Municipal Toronto One Address Repository) | https://open.toronto.ca/dataset/address-points-municipal-toronto-one-address-repository/ (CKAN resource `0b3756af-…`) | queried live | address → ward and coordinate | Toronto only; one address per query; City API must be reachable |
| Members of Toronto City Council Voting Record | https://open.toronto.ca/dataset/members-of-toronto-city-council-voting-record/ | 2026-11-12 | choosing demo items; cross-checking the TE34.21 votes | Recorded votes only; not every decision has one |
| Development Applications | https://open.toronto.ca/dataset/development-applications/ | 2026-11-12 | choosing demo items | X/Y are projected, not lat/lon; postal codes are 3 characters |
| Challenge brief and rubric | provided by the organisers | 2026-11-12 | requirements | — |

## AI assistance

| Use | Tool | How it was checked |
|---|---|---|
| Drafting resident-facing sentences from the staff report | Gemini (`gemini-4-argon` by default; configurable) at temperature 0 with a JSON schema | Every sentence's quote is checked in code against the PDF text (`civify/verify.py`); numbers are cross-checked; every sentence must then be approved by a named staff reviewer, and staff edits are re-checked. The raw model reply is saved (`draft_response.json`) so results can be replayed. On the demo item: 19 of 19 sentences verified on the first run. |
| Meaning check: does each cited passage fully support its sentence, and is it neutral? | Gemini (same model as drafting), temperature 0, JSON schema; raw reply saved as `meaning_response.json` | It only routes sentences to lanes and never approves anything. On the 43 real sentences: 18 ready, 24 to review, 1 blocked. On the demo set it marked the meaning flip ("Staff recommend refusing" under an approval quote) "not supported". Missing or failed checks send every sentence to review. |
| Planning, data-source survey, and writing the code and tests in this repository | Claude (claude.ai and Claude Code) and Gemini (survey only) | The repository includes tests against saved Toronto records and controlled inputs. Links from the AI survey were opened before use; unverified ones were not cited. Two bugs introduced by the AI during development were caught by tests and committed outputs (page attribution; print headers in decision text). The team reviewed and can explain every file. |

Continuation assistance: Codex integrated the pending records, corrected agenda ID handling, added printable approved explanations and local QR generation, and updated tests/docs. Tests exercise report revisions, unknown participation, agenda linking and publication boundaries. No new model drafting or human approvals were performed during this continuation.
