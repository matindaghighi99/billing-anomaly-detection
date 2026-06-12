# Billing Anomaly Audit Dashboard — production-style container image.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATASET=large \
    HIDE_DEMO_CREDS=1

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
RUN python run_pipeline.py \
    && python fraud_evidence.py \
    && python moh_audit.py

# Drop root for runtime.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
