FROM node:22-slim AS frontend-build

WORKDIR /workspace/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --include=optional
COPY frontend ./
RUN npm run build

# Use Python 3.11 slim image
FROM python:3.11-slim

ARG INTELISCOPE_VERSION=1.8.1
ARG INTELISCOPE_BUILD_REVISION=unknown
ARG INTELISCOPE_BUILT_AT=unknown

# Set working directory
WORKDIR /app

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY --from=frontend-build /workspace/src/ui/service_static ./src/ui/service_static
COPY scripts ./scripts
COPY .env.example .env.example

# Cache downloads across retries and tolerate slow package mirrors.
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=120 uv sync --no-dev

# Create volume mount points
RUN mkdir -p /app/data /app/logs
VOLUME ["/app/data", "/app/logs"]

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai
ENV INTELISCOPE_VERSION=${INTELISCOPE_VERSION}
ENV INTELISCOPE_BUILD_REVISION=${INTELISCOPE_BUILD_REVISION}
ENV INTELISCOPE_BUILT_AT=${INTELISCOPE_BUILT_AT}

LABEL org.opencontainers.image.version=${INTELISCOPE_VERSION} \
      org.opencontainers.image.revision=${INTELISCOPE_BUILD_REVISION} \
      org.opencontainers.image.created=${INTELISCOPE_BUILT_AT}

# Run the already-installed application without resolving dependencies at runtime.
ENTRYPOINT ["/app/.venv/bin/horizon"]
CMD []
