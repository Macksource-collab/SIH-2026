# API inventory

All protected endpoints use `Authorization: Bearer <JWT>`. Inspectors are restricted to their own inspections; admins can inspect all records.

## Public and authentication

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | API message |
| GET | `/health` | Real component health; OCR degradation does not disable core use |
| POST | `/auth/register` | Register an inspector |
| POST | `/auth/login` | Login with basic rate limiting |
| GET | `/auth/me` | Current active user |

## Inspections and intelligence

| Method | Path | Purpose |
|---|---|---|
| POST/GET | `/inspections` | Create/list role-scoped inspections |
| GET | `/inspections/summary` | Dashboard totals and recent records |
| GET | `/inspections/{id}` | Inspection and uploaded sides |
| POST | `/inspections/{id}/images` | Validated package-side upload |
| POST | `/inspections/{id}/ocr` | OCR all sides; cached unless forced |
| POST | `/inspections/{id}/analyze` | Analyze or reuse current persisted result |
| GET | `/inspections/{id}/result` | Latest persisted analysis |
| GET | `/inspections/{id}/images/{image_id}/evidence` | Authorized evidence image |
| PATCH | `/inspections/{id}/fields/{field_id}` | Human correction and deterministic reevaluation |
| POST | `/inspections/{id}/report` | Create immutable PDF metadata/file |
| GET | `/inspections/{id}/report` | Latest current report |
| GET | `/inspections/{id}/reports/{report_id}` | Exact authorized report |
| GET | `/inspections/reports` | Role-scoped report list |

## Administration

`/admin/stats`, `/users`, `/inspections`, `/reports`, `/logs`, `/rules`, and `/status` provide real database/system data. User and rule PATCH routes apply safe structured updates. `POST /admin/ocr/warmup` initializes OCR deliberately. Rule imports use `/admin/rules/import/validate` and `/commit`.

Errors use sanitized JSON and never include browser stack traces, passwords, tokens, or connection parameters.
