# Build context is the repo root (see docker-compose.yml / the build command
# in docs/DEPLOYMENT.md) -- backend/committee imports as `backend.committee...`
# from the repo root, so the root has to be on PYTHONPATH, not just backend/.

# --- builder: compile native deps (arch, lightgbm) into a throwaway venv ----
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --- runtime: no compiler, just the venv + app code + cached reference data -
FROM python:3.11-slim
RUN useradd --create-home --uid 1000 committee
WORKDIR /app
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY backend ./backend
COPY pyproject.toml README.md ./
# Locally-generated reference data (see docs/DEPLOYMENT.md's pre-build step):
# data/models/ is the trained Forecasting-agent LightGBM model (agent
# degrades gracefully if absent, so this is recommended, not required);
# data/historical/ is Replay Mode's OHLCV cache and self-heals from a live
# Breeze pull on first use if a symbol's cache file is missing. Neither is
# committed to git (see .gitignore) -- both must exist in the build context
# for this COPY to bundle them.
COPY data/models ./data/models
COPY data/historical ./data/historical
COPY data/news_corpus ./data/news_corpus

# data/committee.db (SQLite) is deliberately NOT copied in -- it's runtime
# state, mounted from a volume in docker-compose.yml so trade history
# survives a container recreate instead of resetting on every deploy.
RUN mkdir -p /app/data && chown -R committee:committee /app
USER committee

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)" || exit 1

CMD ["uvicorn", "backend.committee.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
