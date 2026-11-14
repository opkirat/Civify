# Test Civify in five minutes

Start the app from the project folder if it is not already running:

```bash
.venv/bin/uvicorn civify.app:app --reload
```

Open http://127.0.0.1:8000 on the same computer. The preview is local, so this address will not open the app on a separate phone.

## Resident walkthrough

1. On the homepage, choose **Ward 4 · Parkdale-High Park** and search. The issue at 1337 Queen Street West appears, along with the city-wide property tax item (city-wide items show for every ward).
2. Open the issue. It leads with a short summary labelled **AI-generated**. Expand it to see each verified sentence with its exact source quote and page.
3. Check **Can I still have a say?** and **Where it stands**. The item is a staff recommendation with a saved board meeting date of November 16, 2026; no deadline is calculated.
4. Open 106 Beverley Street (Ward 10). It has no AI summary because the summary's guardrail held it (it stated a staff judgement as fact). Residents see the verified sentences directly.
5. Open the College Street item. It shows Council's decision, the enacted stage and the amendment motions.
6. Use **Print with QR code**. The QR opens the City's official item page.

## Reviewer walkthrough

Sign in at `/staff` with a staff account (`python -m civify.auth add <username> --name "<Name>"`). Decisions persist in the local `civify.db` and change the resident page immediately.

1. The dashboard shows each item's pipeline (documents → draft → source check → meaning check → reviewed → live → AI summary) and a list of exactly what needs a person.
2. Open an item with sentences that need you. Each card shows the reasons it was flagged, the quote highlighted in its paragraph, **Open the PDF** at that page, and often a suggested fix.
3. Approve a sentence. The notice says it is live and names the new resident page version; check it on **Resident view**.
4. Validation test: choose **Edit, then approve**, add an unsupported number such as `99999`, and submit. It is refused and nothing is saved.
5. Reject a live sentence (including one approved by `auto-check`) and confirm it disappears from the resident and print pages, and that any AI summary citing it is withdrawn until rebuilt.

Approvals are bound to the exact sentence, quote and source checksum, so re-drafting an item sends changed sentences back to review.

## Usability check with a teammate

Give someone the homepage without explaining the navigation. Ask them to find a Ward 4 issue and answer:

- What place does it affect?
- Is this a proposal or a final decision?
- Is there a verified deadline to participate?
- Where can they check the original source?

Record where they hesitate. Separately, test at a narrow browser width and use Tab, Shift+Tab and Enter to navigate the search, links and source disclosures.

## Checks completed for the UI refresh

- At the time, 21 app and pending-item regression tests passed (163 tests in the suite now).
- Home, staff queue, review, ward results, meetings, issue, print and stylesheet routes returned HTTP 200.
- Headless Chrome checked six screens at a true 390px viewport with no horizontal overflow; screenshots were inspected for the homepage, issue and staff review layouts.
- The browser submitted the actual ward-search form and reached Ward 4 results.
- Chrome generated a one-page PDF for the pending PB1.6 item with no approved sentences. This does not establish one-page output for longer explanations.

A complete accessibility audit, physical QR scanning and an unassisted teammate test are still pending.

## Address search update

The resident search again accepts addresses. Live City API checks passed for 100 Queen St W, 1337 Queen Street West, 19 Don Ridge Drive and 191 College Street; lowercase, a Toronto suffix and `Unit 5, 100 Queen St W` also matched. `100 Queen St` requires choosing East or West. Service failures are distinguished from missing or incomplete addresses.

Near me shows issues within 2 km plus other issues in the matched ward. Conflicting item/coordinate wards are excluded from distance calculations. The saved Queen Street West location was corrected from the erroneous Queen Street East match using the City API. Public notices use their stated wards, because their supplied coordinates have known errors. Coverage remains limited to the saved pilot records.

The home heading and search are centered. Desktop Chrome screenshot inspected; the running app returned matched/ambiguous results for live search requests. Search URLs can appear in browser history and server access logs even though the application does not save resident addresses in its database.
