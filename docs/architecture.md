# Architecture

Diagrams are Mermaid (render on GitHub). Each one is drawn from the code as it is, not as planned; if the code changes, change the diagram.

## 1. Pipeline (component view)

```mermaid
flowchart LR
  PDFs[(PDFs saved by hand<br/>data/&lt;item&gt;/)] --> extract[extract.py<br/>pages + sha256]
  extract --> classify[classify.py<br/>doc type, author, fields]
  classify --> item[item.json]
  extract --> draft[draft.py<br/>Gemini: sentence + quote]
  draft --> verify[verify.py<br/>quote exists? numbers match?]
  verify --> drafts[drafts.json]
  item --> record[record.py<br/>stages, votes, motions,<br/>participation, location]
  drafts --> record
  City[(City Address Points API)] -.ward, lat/lon.-> record
  record --> recjson[record.json]
  recjson --> app[app.py · FastAPI]
  db[(civify.db<br/>reviews)] <--> app
  app --> staff[/staff: review screen/]
  app --> resident[/items, /near: resident views/]
  City -.ward lookup, not stored.-> app
```

## 2. Classes (the data the code passes around)

```mermaid
classDiagram
  class Document { filename; sha256; pages: Page[]; text; first_lines(); first_page_flat }
  class Page { number: int; text: str }
  class Classification { doc_type: DocType; author; evidence; fields: dict }
  class DocType { <<enum>> STAFF_REPORT; PUBLIC_NOTICE; DRAFT_BYLAW; COUNCIL_BILL; ITEM_PAGE; DECLARATION; PUBLIC_LETTER; UNKNOWN }
  class Verifier { pages: (number, normalized)[]; check(sentence, quote) Result; _find(needle) }
  class Result { verified: bool; reason: str; page: int? }
  class DraftClaim { sentence; quote }
  class Draft { claims: DraftClaim[] }
  Document "1" *-- "many" Page
  Verifier --> Document : built from
  Verifier --> Result : returns
  Draft "1" *-- "many" DraftClaim
  Classification --> DocType
```

`record.json` shape (one per item): `item_id, title, ward, location, retrieved, official_url, current_stage, stages[3]{stage, body, date, outcome|status, …, source{file, sha256}}, participation{written_comments_rule, speaker_registration_rule, public_meeting, council_has_decided, basis, source, note}, public_letters, claims[]{sentence, quote, verified, reason, page, source_file, source_sha256}`.

## 3. A claim's life (state)

```mermaid
stateDiagram-v2
  [*] --> Drafted : model proposes sentence + quote
  Drafted --> Verified : quote found, numbers match
  Drafted --> Unverified : not found / number mismatch / too short
  Verified --> Approved : staff approve (or edit; edit re-checked)
  Unverified --> Approved : staff edit so it passes, then approve
  Verified --> Rejected : staff reject
  Unverified --> Rejected
  Approved --> Published : shown on /items
  Rejected --> [*]
```

## 4. An item's stages (state, from the record)

```mermaid
stateDiagram-v2
  [*] --> StaffRecommendation : staff report dated
  StaffRecommendation --> CommitteeDecision : committee considers (may amend)
  CommitteeDecision --> CouncilDecision : Council considers (may amend)
  CouncilDecision --> Closed : adopted / by-laws enacted
  CouncilDecision --> Appeal : (not modelled yet)
```

Stages are read from the item page's Tracking Status and section headings; the app never infers one.

## 5. Staff approval (sequence)

```mermaid
sequenceDiagram
  actor Clerk
  participant App as app.py
  participant V as Verifier
  participant DB as civify.db
  Clerk->>App: POST /staff/{item}/{i} action=edit, sentence, reviewer
  App->>V: check(edited sentence, original quote)
  alt numbers not in quote
    V-->>App: unverified: "…not in the quote: 54"
    App-->>Clerk: 303 back to screen with error, nothing saved
  else ok
    V-->>App: verified
    App->>DB: INSERT OR REPLACE reviews(item, i, approved, sentence, reviewer, time)
    App-->>Clerk: 303 back to screen, claim marked approved
  end
  Note over App,DB: /items/{item} reads only rows with status = approved
```

## 6. Scalability notes

- **Per item:** extraction ~1 s for 35 pages; one model call (~20 s, ~40k input tokens); verification is milliseconds. A city's weekly agenda (tens of items) is minutes of batch work.
- **Bottlenecks if it grew:** (1) the model call — batchable and cacheable; the report text is the stable prefix. (2) `list_items()` reads every `record.json` per request — fine for hundreds, move to the database for thousands. (3) The live address lookup — ~0.4 s per request against the City API; a pilot would load the Address Points dataset locally.
- **What is Toronto-specific:** `classify.py` rules, `record.py` headings, `geo.py` API. Everything downstream consumes `record.json`, so another municipality supplies those three and keeps the rest.
