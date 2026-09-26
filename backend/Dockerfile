FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/api-venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/api-venv \
    && python -m venv /opt/ocr-venv

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY ocr_worker/requirements-lock.txt ./ocr_worker/requirements-lock.txt
RUN /opt/api-venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/ocr-venv/bin/pip install --no-cache-dir -r ocr_worker/requirements-lock.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
COPY ocr_worker/worker.py ./ocr_worker/worker.py

RUN addgroup --system packsure && adduser --system --ingroup packsure packsure \
    && mkdir -p /data/uploads /data/reports /data/ocr-cache \
    && chown -R packsure:packsure /app /data
USER packsure

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
