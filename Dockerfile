# Docker Hub is intermittently unavailable from local operator networks.  Use
# a reachable Node 22 build image for the frontend stage instead.
FROM quay.io/fedora/nodejs-22@sha256:98036a2ddd3d1bfc10550c92b6a3501757cd46a222bd2c257e677f2f50b9d6e5 AS frontend-build

USER root

WORKDIR /workspace/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    NPM_CONFIG_CACHE=/root/.npm npm ci --include=optional --prefer-offline --no-audit --no-fund
COPY frontend ./
RUN npm run build

# Keep the original Python version and slim Debian contract via MCR's mirror.
FROM mcr.microsoft.com/mirror/docker/library/python:3.11-slim@sha256:193fdd0bbcb3d2ae612bd6cc3548d2f7c78d65b549fcaa8af75624c47474444d

# Set working directory
WORKDIR /app

# Remote managed Agent access uses a pinned, forced-command SSH identity.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /usr/local/bin/uv

# Install locked third-party dependencies before any application files.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=120 UV_LINK_MODE=copy uv sync --frozen --no-dev --no-install-project

# Copy project files and generated frontend assets only after dependency setup.
COPY README.md ./
COPY src ./src
COPY --from=frontend-build /workspace/src/ui/service_static ./src/ui/service_static
COPY scripts ./scripts
COPY .env.example .env.example

# Install the project itself, reusing the already populated environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=120 UV_LINK_MODE=copy uv sync --frozen --no-dev

# Create volume mount points
RUN mkdir -p /app/data /app/logs
VOLUME ["/app/data", "/app/logs"]

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# Run the already-installed application without resolving dependencies at runtime.
ENTRYPOINT ["/app/.venv/bin/horizon-api"]
CMD ["--host", "0.0.0.0", "--port", "8080"]

# Release identity changes must not invalidate any RUN or COPY layer above.
ARG INTELISCOPE_VERSION=1.8.1
ARG INTELISCOPE_BUILD_REVISION=unknown
ARG INTELISCOPE_SOURCE_DIGEST=unknown
ARG INTELISCOPE_BUILT_AT=unknown

ENV INTELISCOPE_VERSION=${INTELISCOPE_VERSION}
ENV INTELISCOPE_BUILD_REVISION=${INTELISCOPE_BUILD_REVISION}
ENV INTELISCOPE_SOURCE_DIGEST=${INTELISCOPE_SOURCE_DIGEST}
ENV INTELISCOPE_BUILT_AT=${INTELISCOPE_BUILT_AT}

LABEL org.opencontainers.image.version=${INTELISCOPE_VERSION} \
      org.opencontainers.image.revision=${INTELISCOPE_BUILD_REVISION} \
      io.inteliscope.source.digest=${INTELISCOPE_SOURCE_DIGEST} \
      org.opencontainers.image.created=${INTELISCOPE_BUILT_AT}
