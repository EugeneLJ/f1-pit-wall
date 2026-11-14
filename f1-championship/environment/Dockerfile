FROM node:22.22.0-bookworm-slim

# Agent image: OpenCode + a thin socket client. No simulator, seed or state.
RUN apt-get update \
    && apt-get install -y --no-install-recommends coreutils curl python3 \
    && npm install --global opencode-ai@1.19.5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY client/f1ctl /usr/local/bin/f1ctl

RUN chmod 0755 /usr/local/bin/f1ctl \
    && mkdir -p /app \
    && chown -R node:node /app

WORKDIR /app
USER node
