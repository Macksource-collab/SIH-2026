# SIH demonstration procedure

## Before judges arrive

1. Start the database/API and frontend.
2. Open `/health`; confirm API, database, upload storage, report storage, and rule engine are ONLINE.
3. Login as admin, open System Status, and select **Warm Up OCR Worker**.
4. Confirm OCR Worker is `ONLINE / READY`.
5. Login as inspector and run one known test analysis.
6. Generate and open its PDF.
7. Login as admin and confirm Overview, Rules, Audit Logs, and System Status load.

## Live demonstration

1. Login as Inspector.
2. Start New Inspection.
3. Upload sharp Front and Back images.
4. Run Analysis and mention measured processing duration.
5. Expand OCR text.
6. Explain structured declarations and confidence.
7. Open evidence for one declaration and show its highlighted region.
8. Explain PASS/FAIL/REVIEW and why weak evidence produces REVIEW.
9. Correct one field when appropriate; compare Machine Extracted and Human Corrected.
10. Show deterministic reevaluation without another OCR run.
11. Generate and open the PDF.
12. Refresh, reopen Inspection History, and show persistence.
13. Login as Admin.
14. Show real overview statistics, users, inspections, reports, audit logs, versioned rules, and system status.

## Fallback when live OCR is slow

Open a previously analyzed synthetic demonstration inspection from Inspection History. State clearly: **“This is pre-generated demo data from an earlier OCR run, not OCR being performed live now.”** Show its OCR text, evidence, correction, evaluations, report, and audit events. Do not claim fallback data came from the current photographs.

Keep the example images locally, disable sleep, use AC power, and avoid downloading models during the judged session.
