# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY tests ./tests
COPY data ./data
COPY .env.example .env.example

# Install dependencies
RUN uv sync --no-dev

# Create volume mount points
RUN mkdir -p /app/data /app/logs
VOLUME ["/app/data", "/app/logs"]

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# Run the application
ENTRYPOINT ["uv", "run", "horizon"]
CMD []
