# ============================================================================
# nautilus_AItrader - production image (Dokploy / docker compose / plain docker)
# ============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    AUTO_CONFIRM=true

# tzdata/ca-certificates for TLS + correct UTC clock reporting; curl for debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (layer cache). nautilus_trader ships manylinux wheels - no compiler needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY main_live.py ./
COPY strategy/ ./strategy/
COPY utils/ ./utils/
COPY indicators/ ./indicators/
COPY configs/ ./configs/
COPY tools/ ./tools/
COPY deploy/docker-entrypoint.sh ./deploy/docker-entrypoint.sh

# Non-root runtime user; /app/logs is the only writable, persisted path
RUN useradd -m -u 1000 trader \
    && mkdir -p /app/logs \
    && chmod +x /app/deploy/docker-entrypoint.sh \
    && chown -R trader:trader /app
USER trader
VOLUME ["/app/logs"]

# Liveness: heartbeat touched on every bar / cycle; stale > 40 min = unhealthy
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "tools/healthcheck.py"]

# Graceful shutdown: SIGINT -> NautilusTrader stops the node; exchange-side exits stay in place
STOPSIGNAL SIGINT

ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["trade"]
