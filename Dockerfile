# RadarAgent — daemon + in-process FastAPI web app.
# bge-m3/torch is intentionally NOT installed: on a CPU VPS use
# embedding.provider=openai (see docs/deploy.md).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer: copy only what the build backend needs to resolve+install
# so `pip install` is cached until pyproject or sources actually change.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Non-root; data dir is the mounted volume (sqlite + chroma).
RUN useradd --create-home --uid 10001 radar \
    && mkdir -p /app/data \
    && chown -R radar:radar /app
USER radar

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else sys.exit(1)"]

# Serves the web app in the same loop as the scheduler when web.enabled.
CMD ["radaragent", "run", "--settings", "config/settings.yaml"]
