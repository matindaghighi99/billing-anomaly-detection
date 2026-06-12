#!/usr/bin/env sh
# Launch Streamlit on the platform-provided $PORT (Render, Cloud Run, etc.),
# falling back to 8501 for local `docker run`.
set -e
exec streamlit run app.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0 \
    --server.headless true
