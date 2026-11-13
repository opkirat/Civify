# Sources, references and AI use

Kept current as the work happens. Covers the rubric's references criterion: libraries with versions and licences, data sources with retrieval dates, and how AI was used and checked.

## Libraries (all pinned in `pyproject.toml`)

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
| City Wards | https://open.toronto.ca/dataset/city-wards/ (CKAN resource `7672dac5-…`) | 2026-11-13 | ward names (`data/wards.json`) | 25-ward model (2018) |
| Address Points (Municipal Toronto One Address Repository) | https://open.toronto.ca/dataset/address-points-municipal-toronto-one-address-repository/ (CKAN resource `0b3756af-…`) | queried live | address → ward and coordinate | Toronto only; one address per query; City API must be reachable |
| Members of Toronto City Council Voting Record | https://open.toronto.ca/dataset/members-of-toronto-city-council-voting-record/ | 2026-11-12 | choosing demo items; cross-checking the TE34.21 votes | Recorded votes only; not every decision has one |
| Development Applications | https://open.toronto.ca/dataset/development-applications/ | 2026-11-12 | choosing demo items | X/Y are projected, not lat/lon; postal codes are 3 characters |
| Challenge brief and rubric | provided by the organisers | 2026-11-12 | requirements | — |

## AI assistance

| Use | Tool | How it was checked |
|---|---|---|
| Drafting resident-facing sentences from the staff report | Gemini (`gemini-4-argon` by default; configurable) at temperature 0 with a JSON schema | Every sentence's quote is checked in code against the PDF text (`civify/verify.py`); numbers are cross-checked; every sentence must then be approved by a named staff reviewer, and staff edits are re-checked. The raw model reply is saved (`draft_response.json`) so results can be replayed. On the demo item: 19 of 19 sentences verified on the first run. |
| Planning, data-source survey, and writing the code and tests in this repository | Claude (claude.ai and Claude Code) and Gemini (survey only) | Every piece of code has tests run on the real Toronto records (62 tests). Links from the AI survey were opened before use; unverified ones were not cited. Two bugs introduced by the AI during development were caught by tests and committed outputs (page attribution; print headers in decision text). The team reviewed and can explain every file. |
