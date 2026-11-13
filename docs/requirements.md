# Requirements

Each requirement is testable; the test column names the test that checks it. Status: ✅ done and tested · 🟡 partly · ⬜ not started · 📝 planned only (stated as a limitation).

## Functional

| ID | Requirement | Tests | Status |
|---|---|---|---|
| FR-01 | Read a PDF into page-numbered text and record its SHA-256, so every citation points at a page of a specific file. | `test_classify.py::test_sha256_is_recorded` | ✅ |
| FR-02 | Classify each PDF (staff report, Clerk's notice, draft by-law, Council bill, item page, declaration, public letter) from its first page, recording the evidence. Unrecognised files are `unknown`, never guessed. | `test_classify.py::test_every_file_classified` (10 real files) | ✅ |
| FR-03 | Read the staff report's author, date, ward and application number from the document. | `test_staff_report_fields_come_from_the_document` | ✅ |
| FR-04 | Quote the Clerk's participation rules verbatim; never compute a deadline. | `test_notice_quotes_participation_rules_verbatim`, `test_participation_is_quoted_not_computed` | ✅ |
| FR-05 | A claim is verified only if its quote appears in the source (on one page or across one page break, running headers stripped) and every number in the claim appears in the quote. | `test_verify.py` (19 tests incl. invented quote, changed number, too-short quote, ellipsis, page break) | ✅ |
| FR-06 | An AI drafts plain-language sentences each paired with an exact quote; every pair is run through FR-05; failures are flagged, not dropped. | `test_draft.py` (6 tests); live run: 19/19 verified | ✅ |
| FR-07 | Build one record per item with three distinct stages (staff recommendation, committee decision, council decision), each with date, outcome and source file. | `test_three_stages_in_order_with_dates_from_the_record`, `test_each_stage_names_its_source_file` | ✅ |
| FR-08 | Record Council votes (counts and members), motions with their text, and declared interests from the item page. | `test_council_votes_and_declared_interest`, `test_council_motions_carry_their_text` | ✅ |
| FR-09 | Public correspondence is counted, never summarised, and no correspondent's name appears in any output. | `test_public_letters_carry_no_author`, `test_letters_are_counted_not_named` | ✅ |
| FR-10 | Staff see each draft beside its quote and page; can approve, reject, or edit then approve; the reviewer's name and time are recorded. | `test_app.py` | ✅ |
| FR-11 | Residents see only approved sentences; nothing is shown before approval. | `test_resident_view_is_empty_until_staff_approve`, `test_rejected_claim_never_shows` | ✅ |
| FR-12 | A staff edit is re-checked against the same quote; an edit that introduces an unsupported number is refused. | `test_edit_is_rechecked_against_the_quote` | ✅ |
| FR-13 | A resident enters an address or ward and sees items in their ward (and distance where known). The address is looked up via the City's API and not stored. | `test_geo.py`, `test_near_by_ward_lists_item_in_that_ward_and_stores_nothing`, `test_near_by_address_uses_city_lookup` | ✅ |
| FR-14 | Show what changed at Council: the motions and their text from the record. | `test_council_motions_carry_their_text` | ✅ |
| FR-15 | Pipeline runs on at least three real items of different types. | — | 🟡 (1 of 3) |
| FR-16 | Printable one-page notice with QR code. | — | 📝 |
| FR-17 | SMS alerts for items with an open participation window. | — | 📝 |
| FR-18 | Translation of approved sentences. | — | 📝 |

## Non-functional

| ID | Requirement | How checked | Status |
|---|---|---|---|
| NFR-01 | Accuracy: no unverified or unapproved AI sentence is ever shown to residents as fact. | FR-05, FR-11, FR-12 tests; the one known gap (meaning drift with a real quote) is documented and covered by human review | ✅ |
| NFR-02 | Provenance: every stage, rule and sentence names its source file and (for sentences) page; files carry checksums; retrieval date recorded. | `record.json` structure; `test_each_stage_names_its_source_file` | ✅ |
| NFR-03 | Privacy: no resident address stored; no correspondent names in outputs; source PDFs with letters kept out of the public repo. | `test_near_…_stores_nothing`, FR-09; `.gitignore` | ✅ |
| NFR-04 | Plain language, neutral tone, conditions preserved. | Prompt rules + staff review; readability score not yet measured | 🟡 |
| NFR-05 | Accessibility: semantic HTML, labelled form controls, keyboard-operable, dark-mode support, mobile width. | Manual check; automated WCAG check not yet run | 🟡 |
| NFR-06 | Reproducibility: the pipeline can be replayed without network or API key from committed outputs. | `--replay` flag; tests run with PDFs absent (19 skip, rest pass) | ✅ |
| NFR-07 | Portability: city-specific code (parsers, geocoding) isolated so another municipality can supply its own. | `classify.py`, `record.py`, `geo.py` are the only Toronto-shaped files; `record.json` is the contract | 🟡 |
| NFR-08 | Simplicity: a team member can explain every file; no file over ~150 lines; one framework. | Code review | ✅ |
