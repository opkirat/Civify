# Test Civify in five minutes

Start the app from the project folder if it is not already running:

```bash
.venv/bin/uvicorn civify.app:app --reload
```

Open http://127.0.0.1:8000 on the same computer. The preview is local, so this address will not open the app on a separate phone.

## Resident walkthrough

1. On the homepage, choose **Ward 4 · Parkdale-High Park**, then **Find issues**. This works without an external address lookup. The issue at 1337 Queen Street West should appear under “Issues in your ward.”
2. Open the issue. Its status should be **Proposed**, with a saved board meeting date of November 16, 2026. The participation panel should explicitly say that an open comment window has not been verified.
3. Check the explanation. Until a person reviews the drafts, “No approved explanation yet” is expected. The app must not publish drafts simply because they passed quote checks.
4. Use **Decision timeline**, **Official item page**, and **Printable notice with QR code**. The QR leads to the City’s official page. Printing should retain the source text and hide navigation; long approved explanations can span pages.
5. Use the navigation to open **Meetings**, then return to **Explore issues** and open the College Street item. It should show the enacted stage and Council amendment motions.

## Reviewer walkthrough

Review actions persist in the local `civify.db` and change the resident view. Use your own name and approve only after reading the sentence against its evidence.

1. Open **Staff workspace → 1337 Queen Street West → Review drafts**.
2. Use **Jump to draft sentences**. Each card pairs the proposed explanation with its supporting quote and page.
3. Read a sentence and its evidence, enter your name, and approve it if it is accurate. Use **Preview resident view** to confirm that sentence appears with its source.
4. For a validation test, edit a sentence to introduce an unsupported number such as `99999`, then submit it. The edit should be refused and the prior review should remain unchanged.
5. Reject a previously approved sentence and confirm it disappears from the resident and print views.

Do not regenerate or reorder reviewed drafts during this walkthrough. Reviews currently use claim indices; content-bound approval persistence remains an outstanding fix.

## Usability check with a teammate

Give someone the homepage without explaining the navigation. Ask them to find a Ward 4 issue and answer:

- What place does it affect?
- Is this a proposal or a final decision?
- Is there a verified deadline to participate?
- Where can they check the original source?

Record where they hesitate. Separately, test at a narrow browser width and use Tab, Shift+Tab and Enter to navigate the search, links and source disclosures.

## Checks completed for the UI refresh

- 21 existing app and pending-item regression tests passed.
- Home, staff queue, review, ward results, meetings, issue, print and stylesheet routes returned HTTP 200.
- Headless Chrome checked six screens at a true 390px viewport with no horizontal overflow; screenshots were inspected for the homepage, issue and staff review layouts.
- The browser submitted the actual ward-search form and reached Ward 4 results.
- Chrome generated a one-page PDF for the pending PB1.6 item with no approved sentences. This does not establish one-page output for longer explanations.

A complete accessibility audit, physical QR scanning and an unassisted teammate test are still pending.

## Address search update

The resident search again accepts addresses. Live City API checks passed for 100 Queen St W, 1337 Queen Street West, 19 Don Ridge Drive and 191 College Street; lowercase, a Toronto suffix and `Unit 5, 100 Queen St W` also matched. `100 Queen St` requires choosing East or West. Service failures are distinguished from missing or incomplete addresses.

Near me shows issues within 2 km plus other issues in the matched ward. Conflicting item/coordinate wards are excluded from distance calculations. The saved Queen Street West location was corrected from the erroneous Queen Street East match using the City API. Public notices use their stated wards, because their supplied coordinates have known errors. Coverage remains limited to the saved pilot records.

The home heading and search are centered. Desktop Chrome screenshot inspected; the running app returned matched/ambiguous results for live search requests. Search URLs can appear in browser history and server access logs even though the application does not save resident addresses in its database.
