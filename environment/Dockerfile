FROM node:22.22.0-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends coreutils curl python3 \
    && npm install --global opencode-ai@1.19.5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY f1pitwall /opt/f1pitwall/f1pitwall
COPY bin/f1ctl /usr/local/bin/f1ctl

RUN chmod 0755 /usr/local/bin/f1ctl \
    && mkdir -p /app/submission \
    && chown -R node:node /app

ENV PYTHONPATH=/opt/f1pitwall
WORKDIR /app
USER node
