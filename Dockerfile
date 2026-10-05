# Stage 1: Build virtual environment with production dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy package definition and application source
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install only production dependencies (excludes optional/dev dependencies)
RUN pip install --no-cache-dir .

# Stage 2: Minimal runtime container
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8080

WORKDIR /app

# Create unprivileged non-root user and group with UID/GID 10001
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid 10001 --create-home --shell /bin/false appuser && \
    chown -R 10001:10001 /app

# Copy virtual environment from builder stage
COPY --from=builder --chown=10001:10001 /opt/venv /opt/venv

# Copy entrypoint script and set permissions
COPY --chown=10001:10001 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

# Run as non-root user
USER 10001:10001

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "srtrsh_communication_backend.main:app", "--host", "0.0.0.0", "--proxy-headers", "--forwarded-allow-ips=*"]
