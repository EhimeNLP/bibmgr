# syntax=docker/dockerfile:1.7

FROM rust:1.86-bookworm AS builder

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3.11 python3.11-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /source
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY config ./config
COPY backend ./backend

RUN python3.11 -m pip install --break-system-packages --no-cache-dir \
      "maturin>=1.9,<2" "build>=1.2,<2" \
    && mkdir /wheels \
    && maturin build \
      --release \
      --manifest-path crates/bibmgr-python/Cargo.toml \
      --out /wheels \
    && python3.11 -m pip wheel \
      --wheel-dir /wheels \
      --no-cache-dir \
      ./backend

FROM postgres:18-bookworm

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
      ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/bibmgr

COPY --from=builder /wheels /wheels
RUN /opt/bibmgr/bin/pip install \
      --no-cache-dir \
      --no-index \
      --find-links=/wheels \
      bibmgr-backend \
      bibmgr-native \
    && rm -rf /wheels \
    && useradd --system --create-home --home-dir /var/lib/bibmgr bibmgr \
    && mkdir -p /var/lib/bibmgr/backups \
    && chown bibmgr:nogroup /var/lib/bibmgr/backups

ENV PATH="/opt/bibmgr/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER bibmgr
WORKDIR /var/lib/bibmgr
EXPOSE 8000

CMD ["uvicorn", "bibmgr_backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
