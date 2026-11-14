# Architecture

Diagrams are Mermaid (they render on GitHub). Each is drawn from the code as it is on `main`, with the function or table that implements each box. If the code changes, change the diagram. Requirement IDs (FR-xx, NFR-xx) refer to [requirements.md](requirements.md); decision IDs (D-xx) to [decisions.md](decisions.md).

## 1. Components and data flow

```mermaid
flowchart LR
  subgraph Intake["Staff intake (FR-23)"]
    upload["/staff/intake<br/>intake.py: validate PDFs"] --> job["pipeline.py: tracked job<br/>(FastAPI BackgroundTasks)"]
  end
  subgraph Pipeline["pipeline.py steps (FR-24)"]
    fetch["fetch.py<br/>linked official PDFs"] --> classify["extract.py + classify.py<br/>pages, sha256, doc type"]
    classify --> draft["draft.py · AI call 1<br/>sentence + exact quote"]
    draft --> verify["verify.py · code<br/>quote exists? numbers match?"]
    verify --> triage["triage.py · AI calls 2 and 3<br/>meaning check, context check<br/>+ risk-word rules → lane"]
    triage --> rec["record.py<br/>stages, votes, motions,<br/>participation, lanes"]
  end
  job --> fetch
  rec --> recjson[("data/&lt;item&gt;/record.json")]
  rec --> auto["db.auto_approve<br/>as 'auto-check' (FR-29)"]
  auto --> pub["db.sync_publication<br/>frozen numbered version (FR-25)"]
  pub --> summ["summary.py · AI calls 4–7<br/>write → code check → guardrail<br/>(one repair) (FR-30)"]
  summ --> sjson[("data/&lt;item&gt;/summary.json")]
  subgraph DB["civify.db (SQLite)"]
    reviews[(reviews, audit,<br/>publications, escalations)]
    jobs[(jobs, job_steps)]
    users[(users, sessions)]
    sms[(sms_subscriptions,<br/>campaigns, deliveries)]
  end
  auto --> reviews
  pub --> reviews
  job --> jobs
  recjson --> app["app.py · FastAPI + Jinja2"]
  sjson --> app
  reviews <--> app
  app --> staff["/staff: dashboard, pipeline view,<br/>review queue, PDF at page (FR-22, FR-28)"]
  app --> resident["/items, /near, /notices, /meetings<br/>AI summary + verified sentences"]
  app --> alerts["/alerts: SMS sign-up (sms.py)"]
  City[(City Address Points API)] -. "ward, lat/lon; not stored" .-> app
  notices["notices.py, agenda.py<br/>saved Clerk notices, agendas"] --> app
```

AI calls per item: 1 draft, 1 meaning check, 1 context check, then the summary (write + guardrail, plus a second write + guardrail only if the first is held). That is 5 calls normally and 7 at most. Everything between the calls is deterministic code.

## 2. Classes and data shapes

```mermaid
classDiagram
  class Document {
    filename
    sha256
    pages: Page[]
    text
  }
  class Page {
    number: int
    text: str
  }
  class Classification {
    doc_type: DocType
    author
    evidence
    fields
  }
  class DocType {
    <<enumeration>>
    STAFF_REPORT
    PUBLIC_NOTICE
    DRAFT_BYLAW
    COUNCIL_BILL
    ENACTED_BYLAW
    ITEM_PAGE
    DECLARATION
    PUBLIC_LETTER
    APPENDIX
    UNKNOWN
  }
  class Verifier {
    check(sentence, quote) Result
  }
  class Result {
    verified: bool
    reason: str
    page: int?
  }
  class Draft {
    claims: DraftClaim[]
  }
  class DraftClaim {
    sentence
    quote
  }
  class MeaningResult {
    index
    verdict: supported or not_supported or unsure
    neutral
    issue
  }
  class ConfirmResult {
    index
    verdict: approve or hold
    neutral
    issue
    suggestion
  }
  class Claim {
    sentence
    quote
    verified
    reason
    page
    source_file
    source_sha256
    lane: ready or review or blocked
    reasons[]
    auto: bool
  }
  class Record {
    item_id
    title
    ward
    citywide
    current_stage
    stages[]
    participation
    claims: Claim[]
  }
  class Publication {
    item_id
    version
    published_by
    claims: frozen sentence+quote+page
  }
  class Summary {
    status: ok or held
    based_on[]
    sentences: text+uses[]
    issues[]
  }
  Document "1" *-- "many" Page
  Verifier --> Document : built from
  Verifier --> Result : returns
  Draft "1" *-- "many" DraftClaim
  Classification --> DocType
  DraftClaim ..> Claim : verify.py adds verified, page
  MeaningResult ..> Claim : triage.assign_lane
  ConfirmResult ..> Claim : triage.assign_lane
  Record "1" *-- "many" Claim
  Publication ..> Claim : approved subset, frozen
  Summary ..> Publication : cites live sentences only
```

`MeaningResult`, `ConfirmResult` (in `triage.py`) and `Written`/`Checked` (in `summary.py`) are Pydantic models passed to Gemini as the JSON response schema, so a malformed reply fails validation instead of being half-read.

## 3. Database tables (SQLite)

```mermaid
erDiagram
  reviews {
    text item_id PK
    int claim_index PK
    text status
    text sentence
    text reviewer
    text claim_hash
  }
  audit {
    int id PK
    text item_id
    int claim_index
    text claim_hash
    text action
    text reviewer
    text at
  }
  publications {
    text item_id PK
    int version PK
    text published_by
    text claims_json
  }
  escalations {
    text item_id
    int claim_index
    text note
    text raised_by
    text resolved_at
  }
  users {
    text username PK
    text name
    text password_hash
  }
  sessions {
    text token PK
    text username FK
  }
  jobs {
    int id PK
    text item_id
    text status
    text started_by
  }
  job_steps {
    int job_id PK
    int position PK
    text step
    text status
    text detail
    text output_json
  }
  sms_subscriptions {
    text phone PK
    text ward
    text status
    text code_hash
    text last_alert_at
  }
  sms_campaigns {
    int id PK
    text item_id UK
    int publication_version
    text body
  }
  sms_deliveries {
    int campaign_id PK
    text phone PK
    text status
  }
  users ||--o{ sessions : "signs in"
  jobs ||--|{ job_steps : has
  sms_campaigns ||--o{ sms_deliveries : sends
  sms_subscriptions ||--o{ sms_deliveries : receives
```

`reviews` holds the current decision per sentence; `audit` is append-only and keeps every decision, including `auto-check` ones. `claim_hash` binds an approval to the exact sentence, quote and source file: if a re-draft changes any of them, the old approval stops counting (`db.current_review`). `publications` is what residents read; it never contains reviewer names, lanes or notes.

## 4. A sentence's life (state)

```mermaid
stateDiagram-v2
  [*] --> Drafted : AI call 1 proposes sentence + quote
  Drafted --> Blocked : code check fails (quote not found, number missing, quote too short)
  Drafted --> Review : flagged word, taking part, or an AI check holds
  Drafted --> Ready : code + both AI checks agree, no taking-part words
  Ready --> Approved : db.auto_approve as "auto-check"
  Review --> Approved : person approves, or edits / takes the suggested fix (re-verified)
  Blocked --> Approved : person edits so the code check passes
  Review --> Escalated : person asks for a second opinion (internal note)
  Escalated --> Approved
  Escalated --> Rejected
  Review --> Rejected
  Approved --> Rejected : person takes it down
  Approved --> Live : sync_publication makes a new frozen version
  Rejected --> [*] : sync_publication removes it from the next version
```

With `CIVIFY_AUTO_APPROVE=0`, the Ready → Approved transition needs a person (one click for all ready sentences, `/staff/{item}/approve-ready`).

## 5. An item's stages (state, from the record)

```mermaid
stateDiagram-v2
  [*] --> StaffRecommendation : staff report dated
  StaffRecommendation --> CommitteeDecision : committee considers (may amend)
  StaffRecommendation --> CouncilDecision : item goes straight to Council (no committee stage shown)
  CommitteeDecision --> CouncilDecision : Council considers (may amend)
  CouncilDecision --> Enacted : enacted by-law records passage
```

Stages are read from the item page's Tracking Status and headings; the app never infers one. A future meeting is shown as "next meeting", never as an outcome. Appeals are not modelled.

## 6. Processing an upload (sequence)

```mermaid
sequenceDiagram
  actor W as Worker
  participant A as app.py
  participant P as pipeline.run (background)
  participant G as Gemini
  participant DB as civify.db
  W->>A: POST /staff/intake/{uid}/start
  A->>DB: create job + 6 steps (queued)
  A-->>W: 303 → /staff/processing/{job}
  A->>P: BackgroundTasks.add_task
  P->>P: save, fetch, classify (code)
  P->>G: draft (AI 1)
  P->>P: verify every quote and number (code)
  P->>G: meaning check (AI 2), context check (AI 3)
  P->>P: assign_lane per sentence
  P->>DB: auto_approve (ready + auto) as "auto-check", audit row each
  P->>DB: sync_publication → version N
  P->>G: summary write + guardrail (AI 4–5, up to 7)
  P->>DB: each step's status, timing, detail
  Note over W,A: the Processing page refreshes while running. Retry resumes from a failed or blocked step
```

## 7. A person decides on a flagged sentence (sequence)

```mermaid
sequenceDiagram
  actor W as Worker
  participant A as app.py decide()
  participant V as Verifier
  participant DB as civify.db
  participant S as summary.refresh_item
  W->>A: POST /staff/{item}/{i} action=approve|edit|reject|escalate
  alt escalate without a note
    A-->>W: 303 with error, nothing saved
  else approve or edit
    A->>V: check(final sentence, original quote)
    alt not verified
      V-->>A: e.g. "number 54 not in the quote"
      A-->>W: 303 with error, nothing saved
    else verified
      A->>DB: save_review (reviews + audit), resolves any escalation
    end
  else reject
    A->>DB: save_review(rejected)
  end
  A->>DB: sync_publication → new frozen version if anything changed
  A-->>W: 303 "Approved. It is now live for residents."
  A-)S: background: rebuild the AI summary from what is live
```

## 8. Scalability

### Measured today (one laptop, 8 real items)

| What | Measured | Source |
|---|---|---|
| Pipeline per item, end to end | ~52 s: fetch 4.6 s, classify 2.6 s, draft 21.0 s, both checks 21.2 s, record 2.4 s | average of 5 browser-run jobs in `job_steps` |
| AI calls per item | 5 normally, 7 at most | §1 |
| Draft input | ~40k tokens for a 35-page staff report | Gemini usage on TE34.21 |
| Resident item page | 32 ms; ward search 75 ms; home 10 ms | `curl` against the local server |
| Tests | 163 pass in ~70 s | `pytest` |

### Scenario: one Council cycle, ~300 new items in a week (an assumption for sizing, not a City figure)

| Pressure | What happens with today's design | Fix, and why it is cheap here |
|---|---|---|
| AI time: 300 × ~52 s ≈ 4.3 h if run one after another | Jobs run inside the web process via `BackgroundTasks`, one per upload | Move `pipeline.run` to a job queue with N workers (RQ, Celery or a cloud task queue). Items are independent, so 10 workers ≈ 26 min. Each step already records its state in `job_steps`, so Retry and resume carry over. |
| AI cost and rate limits: ~1,500–2,100 calls | One synchronous call per step | The staff report is the stable prefix of every prompt, so context caching and the provider's batch API both apply. AI output is reused when inputs are unchanged (same report hash, same sentences), so re-runs cost nothing. |
| Staff review: today 26% of sentences need a person (31 of 119) | ~3–4 sentences per item → ~1,000 decisions a week | The pipeline view lists exactly what needs a person, with reasons and a suggested fix, so most decisions are one click. Escalation routes hard ones to a senior reviewer. |
| Resident traffic spikes (a contested rezoning) | Each page reads `record.json` and the latest publication | Published versions are frozen and numbered, so pages are cacheable at a CDN until the next version. |
| `db.list_items()` reads every `record.json` on the dashboard and ward search | Fine for hundreds of items | Move records into the database with an index on ward and stage; the JSON shape stays the contract. |
| SQLite: one writer at a time | Fine for a team of reviewers; writes are single rows | Postgres for a multi-city or multi-server deployment. `db.py` is the only module with SQL. |
| City address lookup ~0.4 s per search, external dependency | Live API call per address search | Load the Address Points dataset locally; ward search already works without it. |

### What is Toronto-specific

`classify.py` rules, `record.py` headings, `geo.py` (City API) and `notices.py`/`agenda.py` parsers. Everything downstream reads `record.json`, so another municipality supplies those modules and keeps the verifier, the checks, review, publishing and the resident pages.
