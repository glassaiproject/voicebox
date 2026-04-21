# ============================================================
# Voicebox — Local TTS Server with Web UI (CPU)
# 3-stage build: Frontend → Python deps → Runtime
# ============================================================

# === Stage 1: Build frontend ===
FROM oven/bun:1 AS frontend

WORKDIR /build

# Copy workspace config and frontend source
COPY package.json bun.lock CHANGELOG.md ./
COPY app/ ./app/
COPY web/ ./web/

# Strip workspaces not needed for web build, and fix trailing comma
RUN sed -i '/"tauri"/d; /"landing"/d' package.json && \
    sed -i -z 's/,\n  ]/\n  ]/' package.json
RUN bun install --no-save
# Build frontend (skip tsc — upstream has pre-existing type errors)
RUN cd web && bunx --bun vite build


# === Stage 2: Build Python dependencies ===
FROM python:3.11-slim AS backend-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# CPU image: PyPI "torch" is CUDA (+ nvidia-*). Resolve torch/torchaudio from PyTorch CPU index
# first; everything else from PyPI via --extra-index-url (single install avoids CUDA re-resolve).
COPY backend/requirements.txt /tmp/requirements.txt
RUN sed -e '/^torch[>=<]/d' -e '/^torch[[:space:]]/d' -e '/^torchaudio/d' /tmp/requirements.txt \
      > /tmp/requirements-notorch.txt && \
    pip install --no-cache-dir --prefix=/install -r /tmp/requirements-notorch.txt \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple && \
    rm -f /tmp/requirements.txt /tmp/requirements-notorch.txt
RUN pip install --no-cache-dir --prefix=/install --no-deps chatterbox-tts
RUN pip install --no-cache-dir --prefix=/install --no-deps hume-tada
# GitHub tree overwrites PyPI qwen-tts; --no-deps avoids duplicating torch/gradio/etc. already in /install
# (full deps would re-download ~GB and often hit Docker disk limits during this layer).
RUN pip install --no-cache-dir --prefix=/install --no-deps \
    git+https://github.com/QwenLM/Qwen3-TTS.git


# === Stage 3: Runtime ===
FROM python:3.11-slim

# Create non-root user for security
RUN groupadd -r voicebox && \
    useradd -r -g voicebox -m -s /bin/bash voicebox

WORKDIR /app

# Install only runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=backend-builder /install /usr/local

# Copy backend application code
COPY --chown=voicebox:voicebox backend/ /app/backend/

# Copy built frontend from frontend stage
COPY --from=frontend --chown=voicebox:voicebox /build/web/dist /app/frontend/

# Create data directories owned by non-root user
RUN mkdir -p /app/data/generations /app/data/profiles /app/data/cache \
    && chown -R voicebox:voicebox /app/data

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Expose the API port
EXPOSE 17493

# Health check — auto-restart if the server hangs
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD curl -f http://localhost:17493/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]

# Start the FastAPI server (entrypoint drops to voicebox after fixing volume ownership)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "17493"]
