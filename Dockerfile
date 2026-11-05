# Resmara — container image for a hosted deployment.
# Build:  docker build -t resmara .
# Run:    docker run --env-file .env -p 8000:8000 -v resmara_uploads:/app/uploads resmara
# See DEPLOY.md for the full walk-through (compose, Postgres, domain, Meta settings).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The application. uploads/ is created empty on purpose: in production it must be a
# mounted volume, otherwise uploaded listing media disappears on every redeploy and
# Instagram's media fetch (which works by public URL) breaks.
COPY app ./app
COPY static ./static
COPY engine_spec ./engine_spec
COPY admin ./admin
COPY workers ./workers
COPY tests ./tests
COPY scripts ./scripts
COPY proxy.py README.md ./

RUN mkdir -p uploads /data/uploads \
 && useradd --create-home --uid 10001 resmara \
 && apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/* \
 && chown -R resmara:resmara /app /data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Deliberately NO `USER resmara` here: the container starts as root so the entrypoint can fix
# ownership of whatever volume is mounted, then it drops to uid 10001 before running the server.

EXPOSE 8000

# The app has no /health route of its own, so probe the static frontend at the root; the
# operator console exposes the real health signals at /admin.html (API: GET /api/admin/health).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"

# Schema migrations run at startup (app/main.py), not at build time. The entrypoint takes care
# of volume ownership and drops from root to resmara before this command runs.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
