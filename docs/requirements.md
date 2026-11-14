# Requirements

Each requirement is testable; the test column names the test that checks it. Status: ✅ done and tested · 🟡 partly · ⬜ not started · 📝 planned only (stated as a limitation).

## Functional

| ID | Requirement | Tests | Status |
|---|---|---|---|
| FR-01 | Read a PDF into page-numbered text and record its SHA-256, so every citation points at a page of a specific file. | `test_classify.py::test_sha256_is_recorded` | ✅ |
| FR-02 | Classify each PDF (staff report, Clerk's notice, draft by-law, Council bill, enacted by-law, item page, declaration, public letter) from its first page, recording the evidence. Unrecognised files are `unknown`, never guessed. | `test_classify.py::test_every_file_classified` (10 real files) | ✅ |
| FR-03 | Read the staff report's author, date, ward and application number from the document. | `test_staff_report_fields_come_from_the_document` | ✅ |
| FR-04 | Quote the Clerk's participation rules verbatim; never compute a deadline. | `test_notice_quotes_participation_rules_verbatim`, `test_participation_is_quoted_not_computed` | ✅ |
| FR-05 | A claim is verified only if its quote appears in the source (on one page or across one page break, running headers stripped) and every number in the claim appears in the quote. | `test_verify.py` (19 tests incl. invented quote, changed number, too-short quote, ellipsis, page break) | ✅ |
| FR-06 | An AI drafts plain-language sentences each paired with an exact quote; every pair is run through FR-05; failures are flagged, not dropped. | `test_draft.py` (6 tests); live run: 19/19 verified | ✅ |
| FR-07 | Build one record per item with distinct staff, committee and Council stages, plus enacted by-laws when present, each with date, outcome and source file. | `test_three_stages_in_order_with_dates_from_the_record`, `test_each_stage_names_its_source_file` | ✅ |
| FR-08 | Record Council votes (counts and members), motions with their text, and declared interests from the item page. | `test_council_votes_and_declared_interest`, `test_council_motions_carry_their_text` | ✅ |
| FR-09 | Public correspondence is counted, never summarised, and no correspondent's name appears in any output. | `test_public_letters_carry_no_author`, `test_letters_are_counted_not_named` | ✅ |
| FR-10 | Staff see each draft beside its quote and page; can approve, reject, or edit then approve; the signed-in reviewer's name and time are recorded, and every decision is kept in an audit log. | `test_app.py`, `test_every_decision_is_kept_in_the_audit_log` | ✅ |
| FR-11 | Residents see only approved sentences; nothing is shown before approval. | `test_resident_view_is_empty_until_staff_approve`, `test_rejected_claim_never_shows` | ✅ |
| FR-12 | A staff edit is re-checked against the same quote; an edit that introduces an unsupported number is refused. | `test_edit_is_rechecked_against_the_quote` | ✅ |
| FR-13 | A resident enters an address or ward and sees items in their ward (and distance where known). The address is looked up via the City's API and not stored. | `test_geo.py`, `test_near_by_ward_lists_item_in_that_ward_and_stores_nothing`, `test_near_by_address_uses_city_lookup` | ✅ |
| FR-14 | Show what changed at Council: the motions and their text from the record. | `test_council_motions_carry_their_text` | ✅ |
| FR-15 | Pipeline runs on at least three real items of different types. | `test_record.py`, `test_pending_items.py` | 🟡 (three planning/heritage items; no transit/budget example) |
| FR-16 | Printable one-page notice with QR code. | `test_print_shares_review_gate_and_preserves_full_quotes`, `test_qr_targets_official_item_not_localhost` | 🟡 (print/QR implemented; long explanations span pages; visual QA pending) |
| FR-17 | SMS alerts for items with an open participation window. | — | 📝 |
| FR-18 | Translation of approved sentences. | — | 📝 |
| FR-19 | Saved agendas list items by ward without guessing their full IDs from meeting dates. | `test_agenda.py`, `test_agenda_does_not_guess_item_year_and_requires_matching_meeting` | ✅ |
| FR-20 | Pending items remain staff recommendations; revised reports use the latest dated source. | `test_pending_records_choose_latest_report`, `test_latest_report_uses_date_not_filename_order` | ✅ |
| FR-21 | Public notices preserve Clerk text and participation wording. | `test_notices.py`, `test_near_lists_public_notices_and_notice_page_quotes_the_clerk` | ✅ |

| FR-19 | Each sentence is routed to a lane: **blocked** (code check failed; cannot be approved as written), **review** (about taking part or a deadline; or states a decision, condition or uncertainty that the quoted passage does not; or the meaning check is not a clean "supported"), or **ready**. If the meaning check is missing or fails, sentences go to review. | `test_triage.py`, `test_risk_words_echoed_by_the_passage_do_not_need_a_person`, `test_staff_page_groups_sentences_by_lane_with_reasons` | ✅ |
| FR-20 | Staff approve every ready sentence with one click (used when the context check has not run); each is re-verified before it is saved. | `test_approve_ready_publishes_only_ready_sentences` | ✅ |
| FR-21 | Staff pages and actions require sign-in with an individual account; resident pages stay public. | `test_staff_pages_and_actions_require_sign_in`, `test_auth.py` | ✅ |
| FR-22 | Staff see each item's pipeline (documents → draft → source check → meaning check → review → published) and a linked list of exactly what needs a person. | `test_workflow.py`, `test_pipeline_view_lists_what_needs_a_person` | ✅ |

| FR-23 | Workers upload one or more PDFs in the browser (drag-and-drop or file picker), see each file's size, pages, record type, OCR need and duplicate/version warnings, can remove or add files, confirm the item number, and start processing only once validation passes. | `test_intake.py` | ✅ |
| FR-24 | A separate Processing page shows each pipeline step (queued, running, done, failed, blocked, skipped) with times, details and preliminary outputs, refreshes while running, and offers Retry from the failed or blocked step. Missing AI key or staff report shows as blocked, not failed. | `test_full_processing_run_then_review`, `test_missing_staff_report_blocks_and_retry_resumes`, `test_no_ai_key_is_shown_as_blocked_not_failed` | ✅ |
| FR-25 | Residents see only a published, numbered version: a frozen snapshot of approved sentences. Every approval, edit or rejection publishes the next version straight away (an empty version when the last sentence is rejected); escalating publishes nothing. Reviewer names and notes never reach residents. | `test_approving_puts_a_sentence_live_straight_away`, `test_every_decision_makes_a_new_frozen_version` | ✅ |
| FR-26 | Workers can escalate a sentence with a required internal note; escalations are listed first on the dashboard and resolved by the next approve or reject. | `test_escalate_needs_a_note_stays_internal_and_resolves_on_decision` | ✅ |
| FR-27 | The dashboard can be searched and filtered (needs review, blocked or failed, awaiting publishing, published, processing) and sorted; each item shows last update, who, and the next required action. | `test_dashboard_search_and_filters` | ✅ |
| FR-28 | Every sentence under review shows where its quote sits in the source: the page's own text with the quote highlighted, and a link that opens the PDF at that page. Source PDFs are served to signed-in staff only. | `test_source.py`, `test_review_cards_link_to_the_pdf_page_and_show_the_quote_in_context` | ✅ |
| FR-29 | A second AI check reads each sentence against the whole page around its quote, told to hold when in doubt. A sentence is approved automatically (as `auto-check`, logged like any decision) only when the code checks pass, both AI checks agree, and it is not about taking part or a deadline. Automatically approved sentences go live straight away. A person can reject or edit any of them; a held sentence offers suggested wording that is re-verified before saving. | `test_auto_needs_both_ai_checks_and_never_covers_participation`, `test_auto_approved_sentences_go_live_and_a_person_can_take_them_down`, `test_held_sentence_offers_suggested_wording` | ✅ |
| FR-30 | Residents see a short AI summary, labelled as AI-generated with a disclosure, written only from the item's live sentences. Every summary sentence must cite live sentences and contain no number they lack (code), and a second AI call must approve it; one repair attempt uses the checks' reasons. A held summary is not shown. A summary is withdrawn when any sentence it cites stops being live, and rebuilt in the background after staff decisions. | `test_summary.py`, `test_resident_page_shows_labelled_ai_summary_over_verified_sentences` | ✅ |

## Non-functional

| ID | Requirement | How checked | Status |
|---|---|---|---|
| NFR-01 | Accuracy: no unverified or unapproved AI sentence is ever shown to residents as fact. | FR-05, FR-11, FR-12, FR-19 tests; approvals bound to content (`test_approval_stops_counting_when_the_sentence_changes`); meaning drift routed to a person by risk rules and the meaning check | ✅ |
| NFR-02 | Provenance: every stage, rule and sentence names its source file and (for sentences) page; files carry checksums; retrieval date recorded. | `record.json` structure; `test_each_stage_names_its_source_file` | ✅ |
| NFR-03 | Privacy: no resident address stored; no correspondent names in outputs; source PDFs with letters kept out of the public repo. | `test_near_…_stores_nothing`, FR-09; `.gitignore` | ✅ |
| NFR-04 | Plain language, neutral tone, conditions preserved. | Prompt rules + staff review; readability score not yet measured | 🟡 |
| NFR-05 | Accessibility: semantic HTML, labelled form controls, keyboard-operable, dark-mode support, mobile width. | Manual check; automated WCAG check not yet run | 🟡 |
| NFR-06 | Reproducibility: saved model replies can be reverified without an API key when the original staff PDFs are available. | `--replay` flag; PDF-dependent tests skip when PDFs are absent; app pages still read JSON records | ✅ |
| NFR-07 | Portability: city-specific code (parsers, geocoding) isolated so another municipality can supply its own. | `classify.py`, `record.py`, `geo.py` are the only Toronto-shaped files; `record.json` is the contract | 🟡 |
| NFR-08 | Simplicity: a team member can explain every file; modules separate extraction, classification, verification, records and web views; one web framework. | Code review | 🟡 |
