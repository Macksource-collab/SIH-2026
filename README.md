# PackSure AI

PackSure AI is a learning-focused SIH 2026 prototype for authenticated packaged-commodity inspections. An inspector uploads package-side photographs, the backend prepares copies for OCR, PaddleOCR reads label text, deterministic extractors create evidence-backed declarations, structured demo rules evaluate them, and ReportLab produces a PDF.

The included compliance rules are **DEMO / PROVISIONAL**. They demonstrate the engine; they are not legal certification or verified Legal Metrology citations.

## Start on Windows

The FastAPI environment is `backend/venv`. PaddleOCR is isolated in Python 3.12 because PaddlePaddle 3.2.2 has no compatible Windows wheel for the project's Python 3.14 API environment.

From `backend/`:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m scripts.seed_demo_rules
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

On a fresh machine, create the OCR environment with 64-bit Python 3.12:

```powershell
py -3.12 -m venv .ocr-venv
.\.ocr-venv\Scripts\python.exe -m pip install -r ocr_worker\requirements-lock.txt
```

The first OCR run downloads Paddle models into `backend/.ocr-cache/`; later runs reuse them. Keep `OCR_WORKER_PYTHON=.ocr-venv/Scripts/python.exe` in `.env`. Admin > System Status can warm the worker before a demonstration without making API startup depend on OCR.

In another terminal, from `frontend/`:

```powershell
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

On a fresh clone, copy `backend/.env.example` to `backend/.env` and replace `JWT_SECRET_KEY` with a random secret of at least 32 characters. Never commit `.env`.

## Accounts and authorization

Create users from `backend/`; passwords are hidden and must be at least 12 characters:

```powershell
.\venv\Scripts\python.exe -m scripts.seed_user --name "PackSure Admin" --email admin@packsure.example.com --role admin
.\venv\Scripts\python.exe -m scripts.seed_user --name "PackSure Inspector" --email inspector@packsure.example.com --role inspector
```

Reset an existing password with:

```powershell
.\venv\Scripts\python.exe -m scripts.set_password --email admin@packsure.example.com
```

Inspectors can create, upload, analyze, view evidence, and generate/view reports for their own inspections. Admins can access all inspections and reports, user/system/audit data, analytics, and the structured rule list. FastAPI enforces ownership and roles.

The prototype stores its JWT in `localStorage`. Hardened production should use HTTPS and Secure, HttpOnly cookies with a deliberate CSRF design, throttling, recovery, and stronger session revocation.

## Intelligence flow

1. Original files remain unchanged in `backend/uploads/<inspection_uuid>/` with UUID filenames.
2. Pillow safely decodes PNG/JPEG/WEBP, applies reliable EXIF orientation, limits pixels, and resizes working copies to at most 2400×2400.
3. OpenCV measures dimensions, Laplacian blur, brightness, and contrast. The transparent heuristic returns `GOOD`, `LOW_QUALITY`, or `UNREADABLE`. Only low-contrast copies receive mild CLAHE and denoising.
4. A persistent Python 3.12 worker lazily loads PaddleOCR once per API process. OCR regions retain text, confidence, normalized box, image ID, and side.
5. Keyword/regex/context, date, quantity/unit, and numeric parsers extract declarations without inventing unsupported fields.
6. Rules use a fixed validator allowlist: `required`, `regex`, `numeric`, `date`, `comparison`, and `conditional_required`. Stored rules never execute Python.
7. Poor quality, low confidence, conflicting evidence, uncertain applicability, or a failed side yields `REVIEW`. Provisional rules always keep the overall result at `REVIEW_REQUIRED`.
8. OCR, analysis snapshots, fields, evaluations, and report metadata persist. Reruns replace that image's OCR rows transactionally; one failed side does not erase successful sides.

The evidence viewer fetches the authenticated derived image and overlays its normalized OCR polygon. Derived files are private under each inspection's `.derived/` folder.

## Database and migration

Foundation tables remain: `users`, `inspections`, `inspection_images`, `audit_logs`, and `reports`. Migration `backend/alembic/versions/0cff59a89d4b_intelligence_pipeline.py` adds:

- `image_processing`: source hash, pipeline version, quality metrics, status/error.
- `ocr_results`: detected text, confidence, and JSON bounding box.
- `analysis_runs`: immutable result snapshot and overall status.
- `extracted_fields`: value plus source image, side, text, confidence, and box.
- `compliance_rules`: versioned structured validator data, dates, source, active/provisional flags.
- `rule_evaluations`: PASS/FAIL/REVIEW, reason, rule snapshot, and optional evidence field.

Migration `backend/alembic/versions/ee57e063679e_human_declaration_corrections.py` adds `machine_value`, `corrected_value`, `corrected_by`, `corrected_at`, and `is_human_reviewed` to extracted fields. Existing normalized values are backfilled as their original machine values. Reports may now be `superseded` when a later correction changes their analysis snapshot.

SQLAlchemy uses portable UUID/JSON types for SQLite development and PostgreSQL architecture. The Docker stack targets PostgreSQL 17. Docker and PostgreSQL were unavailable on the final Windows verification host, so runtime PostgreSQL verification remains explicitly outstanding.

## Demo rules

`python -m scripts.seed_demo_rules` is idempotent. It creates:

| Code | Demonstration |
| --- | --- |
| `DEMO-MRP` | Positive MRP detected |
| `DEMO-QUANTITY` | Positive net quantity detected |
| `DEMO-MANUFACTURER` | Manufacturer or packer detected |
| `DEMO-CARE` | Consumer-care phone or email detected |
| `DEMO-ORIGIN` | Origin required when importer applicability is confidently established |

Their source is explicitly `PackSure demonstration specification - NOT official law`; source references are empty. Exact official documents, clauses, amendments, effective dates, category scope, units, tolerances, and enforcement interpretation require qualified domain verification before production use.

## New APIs

Existing auth, uploads, owner checks, admin APIs, and `/health` remain.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/inspections/summary` | Role-scoped dashboard totals/recent rows |
| POST | `/inspections/{id}/ocr?force=false` | Process all sides with cache and partial success |
| POST | `/inspections/{id}/analyze?force=false` | OCR, extraction, rule evaluation, persistence |
| GET | `/inspections/{id}/result` | Latest snapshot, stale flag, report-ready state |
| GET | `/inspections/{id}/images/{image_id}/evidence` | Authorized evidence image |
| PATCH | `/inspections/{id}/fields/{field_id}` | Save a human correction and reevaluate deterministic rules without OCR |
| POST | `/inspections/{id}/report` | Generate PDF and persist metadata |
| GET | `/inspections/{id}/report?download=false` | Authorized inline/attachment PDF |
| GET | `/admin/rules` | Admin structured rule list |
| PATCH | `/admin/rules/{rule_id}` | Admin active toggle only |
| POST | `/admin/rules/import/validate` | Validate and preview a structured JSON rule import |
| POST | `/admin/rules/import/commit` | Commit the unchanged validated import digest |
| POST | `/admin/ocr/warmup` | Deliberately initialize the persistent OCR model |

Admin stats now include latest compliant/non-compliant/review counts, OCR-processed inspections, and reports. API errors are sanitized JSON without browser stack traces.

## Frontend workflow

Log in as inspector, select **New Inspection**, upload Front/Back or other sides, then **Run Analysis**. The loading stages explain one synchronous request; they are not fake streaming. Results display quality, declarations, confidence, rule status, OCR text, and **View Evidence**. Reports can be generated, viewed, and downloaded. Saved results survive refresh.

The Admin page displays live database counts, users, audit events, and demo rules with read-only configuration plus active toggles. Dashboard sample numbers were replaced by database values.

For a detected declaration, select **Review / Correct**. The panel keeps the machine value and raw OCR text visible, accepts a validated manual value, records the reviewer and time, and marks the declaration **Human Reviewed**. Saving reevaluates only the stored deterministic rules. It does not preprocess the image or call PaddleOCR. Any previously generated PDF is marked superseded, so the reviewer must generate a fresh report containing both machine and corrected values.

## Verification commands and results

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m alembic check
.\venv\Scripts\python.exe -m pip check
.\.ocr-venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m scripts.ocr_smoke
```

```powershell
cd frontend
npm run lint
npm run build
```

Verified in this Windows workspace:

- 63 backend tests passed, plus 11 existing upload subtests; two upstream deprecation warnings remain.
- ESLint and the Vite production build passed.
- Alembic found no pending model operations; both Python environments reported no broken requirements.
- Real PaddleOCR smoke found six regions in the synthetic Front fixture, including `Net Wt. 500 g` and `MRP Rs. 120 incl. all taxes`.
- Browser E2E passed: inspector login, Front+Back upload, real OCR, 12 declarations, REVIEW REQUIRED, MRP evidence, PDF, refresh persistence, admin inspection/stats/rules/audits, Backend API Online.
- The E2E images are synthetic test labels, not a benchmark on real product photography.

Tests mock expensive inference while exercising real decoding, persistence, partial failure, extraction, rules, authorization, evidence, and PDF creation. Cases cover corrupt images, single/multiple sides, cache/force, OCR unavailable, supported extraction fields, PASS/FAIL/REVIEW, disabled/effective rules, low confidence, provisional status, reports, and admin access.

## Files changed

Created:

- `backend/app/services/{image_processing,ocr,extraction,compliance,pipeline,reporting,routes}.py`
- `backend/ocr_worker/worker.py`, `requirements-lock.txt`
- `backend/scripts/ocr_smoke.py`, `seed_demo_rules.py`
- intelligence Alembic migration, `backend/tests/test_intelligence.py`, and two synthetic fixtures
- `frontend/src/AnalysisPanel.jsx`, `RuleManagement.jsx`
- `backend/alembic/versions/ee57e063679e_human_declaration_corrections.py`

Integrated through `backend/app/{models,config,main,admin,inspections}.py`, environment/dependency files, and `frontend/src/{App,InspectionForm,InspectionList,AdminPanel,api}.jsx/js` plus CSS and tests.

Main-environment additions: OpenCV headless, NumPy, Pillow, ReportLab, pypdf, charset-normalizer. The isolated OCR lock pins PaddlePaddle 3.2.2, PaddleOCR 3.3.2, PaddleX 3.3.13, and transitive packages.

## Limitations

- PaddleOCR is English/CPU only. Startup is slow and analysis is synchronous; production needs a durable background job queue.
- Windows PaddlePaddle currently requires the separate Python 3.12 worker; the FastAPI environment is Python 3.14.
- Quality labels are heuristics. Bright synthetic fixtures were conservatively `LOW_QUALITY`, forcing review.
- OCR can misread characters: the real E2E read `care@example.com` as `care@example.cor`; evidence exposes this for human review.
- Deterministic extraction cannot cover every language, label layout, glare/curvature, unit spelling, address, or date pattern.
- Filesystem and database commits cannot be perfectly atomic across process crashes; orphan reconciliation remains future work.
- Legacy `inspection.json` files remain untouched and are not authoritative or auto-imported.
- Corrections currently replace the latest correction on that extracted-field row; the append-only audit log retains every correction event, but a separate version-history table and correction reversal workflow are future work.
- No LLM, AI legal decision, verified legal dataset, certification, background queue, refresh tokens, or real PostgreSQL deployment is included.

## Deployment and legal-data workflow

Production React builds are served by nginx; Vite is development-only. The root `docker-compose.yml` defines nginx, FastAPI, and a private PostgreSQL service with durable database, upload, report, and OCR-cache volumes. See [DEPLOYMENT.md](DEPLOYMENT.md) for local, Docker, and Linux/VM procedures and [DEMO.md](DEMO.md) for the judged demonstration checklist.

Rules use explicit `DEMO`, `PROVISIONAL`, or `VERIFIED` status. PackSure never promotes a rule automatically. See [legal-data governance](docs/legal-data.md), [rule-engine design](docs/rule-engine.md), [architecture](docs/architecture.md), and the [API inventory](docs/api.md). The import example remains disabled and marked DEMO.

Core principle:

> AI extracts. Rules validate. Evidence explains. Human verifies.

The PDF contains inspection/analysis IDs, inspector/time, overall result, quality summary, declarations, rule evaluations, review items, evidence text/confidence/boxes, and human-verification/provisional disclaimers.
