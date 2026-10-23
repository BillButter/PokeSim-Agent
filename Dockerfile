# syntax=docker/dockerfile:1.7

# ---- build stage: compile/install Python dependencies (including PyBoy) ----
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libsdl2-dev \
        libsdl2-image-dev \
        libsdl2-mixer-dev \
        libsdl2-ttf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install ".[emulator]"

# ---- runtime stage ----
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    POKESIM_HOST=0.0.0.0 \
    POKESIM_PORT=8000 \
    POKESIM_ROMS_DIR=/roms \
    POKESIM_DATA_DIR=/data \
    SDL_VIDEODRIVER=dummy \
    SDL_AUDIODRIVER=dummy

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libsdl2-2.0-0 \
        libsdl2-image-2.0-0 \
        libsdl2-mixer-2.0-0 \
        libsdl2-ttf-2.0-0 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 pokesim \
    && useradd --uid 1000 --gid pokesim --create-home --shell /usr/sbin/nologin pokesim \
    && mkdir -p /roms /data \
    && chown -R pokesim:pokesim /roms /data

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./

USER pokesim

EXPOSE 8000
VOLUME ["/roms", "/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "-m", "app"]
