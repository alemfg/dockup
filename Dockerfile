FROM python:3.12-slim

# Build-time version baked in — visible in `docker inspect` and logs
ARG ARBX_VERSION=unknown
ARG BUILD_DATE=unknown
LABEL description="ARBX Brain" \
      arbx.version="${ARBX_VERSION}" \
      arbx.build_date="${BUILD_DATE}" \
      arbx.component="brain"

# Make version available at runtime as an env var
ENV ARBX_BUILD_VERSION=${ARBX_VERSION}
ENV ARBX_BUILD_DATE=${BUILD_DATE}
ENV ARBX_COMPONENT=brain

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd -m -u 1000 brain && chown -R brain:brain /app
USER brain

EXPOSE 8000
CMD ["python", "-m", "scripts.run_brain"]
