# syntax=docker/dockerfile:1.7

FROM rust:1.86-bookworm AS builder

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3.11 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /source
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY config ./config
COPY slack ./slack

RUN python3.11 -m pip install --break-system-packages --no-cache-dir \
      "maturin>=1.9,<2" \
    && mkdir /wheels \
    && maturin build \
      --release \
      --manifest-path crates/bibmgr-python/Cargo.toml \
      --out /wheels \
    && python3.11 -m pip wheel \
      --wheel-dir /wheels \
      --no-cache-dir \
      "slack-bolt>=1.29,<2" \
    && python3.11 -m pip wheel \
      --wheel-dir /wheels \
      --no-cache-dir \
      --no-deps \
      ./slack

FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install \
      --no-cache-dir \
      --no-index \
      --find-links=/wheels \
      bibmgr-native \
      bibmgr-slack \
    && rm -rf /wheels \
    && useradd --system --create-home --home-dir /var/lib/bibmgr-slack bibmgr-slack \
    && mkdir -p /opt/bibmgr-slack/export-profiles

COPY slack/config/export-profiles /opt/bibmgr-slack/export-profiles

ENV PYTHONUNBUFFERED=1 \
    BIBMGR_SLACK_PROFILE_DIR=/opt/bibmgr-slack/export-profiles

USER bibmgr-slack
WORKDIR /var/lib/bibmgr-slack

CMD ["bibmgr-slack"]
