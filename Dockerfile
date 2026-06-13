# Billing Anomaly Audit Dashboard — production-style container image.
FROM python:3.11-slim

# Code is organised into section folders (common/, detection/, …) but modules
# import each other by bare name, so every section folder is on PYTHONPATH.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATASET=large \
    HIDE_DEMO_CREDS=1 \
    PYTHONPATH=/app:/app/common:/app/detection:/app/data_pipeline:/app/dashboard:/app/auth:/app/audit:/app/ops:/app/testing

WORKDIR /app

# curl is used by the container HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Generate the expanded dataset, run the full detection pipeline, and build the
# MOH casebook at build time so the image ships with data ready to serve.
RUN python data_pipeline/run_pipeline.py \
    && python audit/fraud_evidence.py \
    && python audit/moh_audit.py

# Drop root for runtime.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8501

# Bind to ${PORT:-8501} so the same image runs locally and on platforms that
# inject a dynamic port (Render, Cloud Run, App Runner …).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8501}/_stcore/health" || exit 1

CMD ["sh", "entrypoint.sh"]
