# ── Stage 1: build wheel ─────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel build --quiet

COPY dockup ./dockup
RUN python -m build --wheel --outdir /dist

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="dockup"
LABEL org.opencontainers.image.description="Automated database backup manager with Docker auto-discovery"
LABEL org.opencontainers.image.source="https://github.com/yourorg/dockup"
LABEL org.opencontainers.image.licenses="MIT"

# Install native backup CLI tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    mysql-client \
    mongodb-clients \
    redis-tools \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install elasticdump via Node (lightweight)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs --no-install-recommends && \
    npm install -g elasticdump --quiet && \
    rm -rf /var/lib/apt/lists/* /root/.npm

# Install Python wheel
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Create non-root user
RUN groupadd -r dockup && useradd -r -g dockup -s /sbin/nologin dockup
RUN mkdir -p /backups /etc/dockup && chown -R dockup:dockup /backups /etc/dockup

USER dockup
WORKDIR /home/dockup

VOLUME ["/backups", "/var/run/docker.sock"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

ENTRYPOINT ["dockup"]
CMD ["serve"]
