# ============================================================================
# Multi-Stage Production Dockerfile: Zero-Trust Enterprise RAG
# Hardened, minimal footprint, running as unprivileged non-root user (UID 10001)
# ============================================================================

# ----------------------------------------------------------------------------
# Stage 1: Build & Dependency Wheel Compilation
# ----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

# ----------------------------------------------------------------------------
# Stage 2: Hardened Runtime Container
# ----------------------------------------------------------------------------
FROM python:3.11-slim AS runner

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Install minimal runtime dependencies and curl for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged application user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /bin/bash appuser

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder --chown=appuser:appgroup /root/.local /home/appuser/.local

# Copy application source code
COPY --chown=appuser:appgroup . /app

# Switch to non-root user
USER appuser

# Expose FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501

# Liveness / Readiness Health Check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Default entry point: FastAPI service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
