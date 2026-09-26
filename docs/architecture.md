# Architecture

```text
Browser (React/Vite build served by nginx)
        | HTTPS /api
FastAPI (auth, inspections, rules, reports, health)
        | SQLAlchemy/Alembic          | private files
PostgreSQL or SQLite                  uploads/reports
        |
Python OCR subprocess (PaddleOCR model reused in one worker)
```

Original package images are immutable UUID-named files. Derived OCR images are private and replaceable. SQLAlchemy stores identities, metadata, OCR regions, declarations, human corrections, analyses, evaluations, reports, and audit events.

The OCR subprocess uses a JSON-lines protocol. FastAPI starts without OCR, readiness checks do not initialize a model, and Admin can warm the model before a demo. One API process owns one persistent OCR process; the supplied Docker configuration intentionally runs one API worker.

The analysis pipeline preserves partial successes. A current successful analysis is reused unless `force=true`, images/rules change, or a prior side failed. Human correction reevaluates stored deterministic rules without OCR.

Core principle:

> AI extracts. Rules validate. Evidence explains. Human verifies.
