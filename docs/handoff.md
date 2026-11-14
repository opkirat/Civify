# Civify continuation — November 14, 2026

Working notes passed between development sessions. Where they disagree with the README or the other docs, those are current; for example, budget and SMS (demo mode) are now built and sentences can go live automatically (D-19, D-20).

## Current handoff

This section supersedes the historical notes below.

- Eight saved items now exist: property tax item 2026.CC38.1, College Street 2026.TE34.21, and Preservation Board items 2027.PB1.1 through PB1.6.
- Upload jobs 2–5 completed successfully for PB1.1–PB1.4. Their local published explanations contain 11, 8, 7 and 8 approved sentences respectively. Pending sentences still require staff review. Publications and accounts live in the ignored local SQLite database and are not shipped through GitHub.
- The user authorized pushing the pending commits and Codex edits to GitHub. They deferred the manual sentence-review walkthrough. Do not approve those sentences on their behalf.
- SMS signup, code confirmation, ward matching and staff dispatch are implemented in demo mode. Local Twilio credentials authenticated on November 13; that account was Trial and had no owned sender numbers. Live sending and a public webhook remain unconfigured. See `sms.md`; never commit `.env` files.
- The app now binds reviews to content and records publication versions. The older warning below about index-only approvals is obsolete.
- No permission was given to relax numeric verification to accept a year elsewhere on the page. Keep the existing verification rule. The proposed expired-deadline labels also remain pending.
- Remaining external inputs: human review; a real phone/QR walkthrough; team names and roles for the readiness report; and the Kennedy Road item page when available. The handoff suggested checking for that page November 18–20, not treating its absence today as an error.

## Historical notes — November 13

This records the state after continuing the supplied Claude conversation. The original brief and rubric are in `.claude/skills/civify-context/`. `README.md` describes implemented features; `docs/limitations.md` records gaps.

## Decisions to preserve

- The user narrowed the initial demo to zoning/planning. Do not describe transit, budget, SMS or translation as implemented.
- Gemini is the existing drafting provider. The saved responses support replay with the original staff PDFs. This continuation did not call a model, read credentials or approve resident-facing claims.
- Every draft needs a real quote, numeric verification and a named human review. Verifying a quote does not verify meaning. Do not infer participation deadlines from meeting dates.
- Public correspondence is counted rather than summarized. Source PDFs and the local review database remain excluded from Git.
- The prior conversation left local commits unpushed. This continuation neither committed nor pushed changes.

## Data on disk

| Item | Snapshot state | Saved draft checks |
|---|---|---|
| 2026.TE34.21, College Street rezoning | Council adopted with amendments; enacted by-laws downloaded | 19/19 passed |
| 2027.PB1.5, 19 Don Ridge Drive | Staff recommendation; Preservation Board meeting listed November 16, 2026 | 12/13 passed; ward quote too short |
| 2027.PB1.6, 1337 Queen Street West | Staff recommendation; same board meeting listed | 11/11 passed |

PB1.5 has three staff report versions; the latest is `backgroundfile-290992.pdf`, dated November 13, 2026. Neither PB record contains an item-specific participation rule. Their 2027 item IDs come from the saved item pages, even though the meeting is in 2026.

There are also 14 saved Clerk notices, a six-item board agenda and general participation rules retrieved November 13. These are snapshots, not live monitoring. The Kennedy Road notice contains a November 24 registration rule; current participation still needs official confirmation.

## Work completed in this continuation

- Finished integration of the pending items and report versions; scoped committee status to its own section and stopped storing a future meeting as a Council outcome.
- Removed invented agenda item years. Direct links now require a full ID from a saved source; local records join only on matching short ID, body, meeting date and ward.
- Added clear missing-rule messaging, upcoming meeting context and staff report version visibility.
- Added `/items/{id}/print` using the same approval gate as resident pages, and `/items/{id}/qr.svg` using Segno 1.6.6. QR codes point to the official item page so they work beyond localhost. Long explanations retain all approved text and source quotes and may span pages.
- Updated README, requirements, architecture, source log and limitations. Added regression tests. Full suite: **89 passed**. A separate copy without PDFs: **31 passed, 51 skipped**. Both runs have one dependency deprecation warning.

## Next actions

1. Human review of PB1.5 and PB1.6 in `/staff/{id}`. Keep the short-quote ward claim unapproved unless it has adequate evidence. Preserve conditions when assessing the other claims.
2. Browser QA: desktop/mobile, keyboard flow, print preview and scan the QR on a phone. This session had no browser runtime; HTTP/template behavior was tested instead.
3. Address index-based review persistence before regenerating reviewed drafts: bind approvals to claim/source content and retain an audit history. Current limitation is documented; old approvals must not survive changed evidence.
4. Confirm participation on the official item page before presenting any opportunity as open. Obtain the Kennedy Road item page when available if it remains in scope.
5. Prepare the municipal readiness report and demo video, using actual test results and clearly separating implemented and planned features.

Run locally: `.venv/bin/uvicorn civify.app:app --reload`. Select an item from `/`, use its staff-review link, then inspect the resident and printable views. Reviews are local to `civify.db`; no approvals were added by this continuation.

## UI refresh

The next turn added a green-and-cream resident interface, persistent navigation, address/ward search on the homepage, readable issue cards, a separate `/staff` queue, a two-column explanation/participation page and side-by-side staff review. Other-ward results are collapsed under disclosures. See `docs/testing.md` for the test walkthrough and browser evidence. Existing approval behavior is unchanged.
