# Deployment

## A. Local SIH demo on Windows

Install Python 3.14, Python 3.12, Node.js, and Git. Copy `backend/.env.example` to `backend/.env`, generate a random JWT secret, then follow the README start commands. Run Alembic and create users before the demo. Warm OCR from Admin > System Status after services start.

Persistent local data is `backend/packsure.db`, `backend/uploads`, `backend/reports`, and `backend/.ocr-cache`. Back these up while the API is stopped.

## B. Docker demo

Docker was not available in the verification environment, so these definitions were statically reviewed but not built here.

1. Install Docker Desktop with Compose.
2. Copy `.env.docker.example` to `.env` and replace both secrets with long random alphanumeric values.
3. Run `docker compose build` and `docker compose up -d`.
4. Check `docker compose ps`, `http://localhost:8080`, and `http://localhost:8080/api/health`.
5. Create users:
   `docker compose exec backend python -m scripts.seed_user --name "PackSure Admin" --email admin@example.test --role admin`
6. Demo rules are seeded idempotently at backend startup. Import reviewed rule JSON through Admin when needed.

PostgreSQL has no host port. Named volumes persist PostgreSQL, uploads, reports, and the OCR model cache. Back up all three data volumes plus PostgreSQL with `pg_dump`.

## C. Production-like Linux/VM

Use a managed PostgreSQL service or a privately networked database. Build immutable images in CI, run Alembic as a release job, and run the API as a non-root user. Put an HTTPS reverse proxy/load balancer in front of nginx, redirect HTTP, set the exact HTTPS origin in `ALLOWED_ORIGINS`, and retain HSTS.

Mount uploads, reports, and OCR cache on durable storage. Schedule database and file backups together and test restoration. Forward stdout/stderr to centralized logs without secrets. Restart failed containers with an orchestrator and monitor `/health`; treat OCR `DEGRADED/NOT_INITIALIZED` differently from a database outage.

The current in-memory login limiter and localStorage token are SIH-scale controls. A hardened deployment should use a shared rate limiter and Secure HttpOnly cookie/session design with CSRF protection. Multiple API workers require a separate durable OCR/job service rather than one subprocess per worker.
