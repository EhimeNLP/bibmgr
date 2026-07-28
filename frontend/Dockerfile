# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS builder

ARG BIBMGR_BASE_PATH=/
ENV BIBMGR_BASE_PATH=$BIBMGR_BASE_PATH

WORKDIR /source/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM caddy:2.10-alpine

COPY deploy/caddy /etc/caddy/bibmgr
COPY --from=builder /source/frontend/dist /srv
