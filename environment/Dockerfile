FROM python:3.12.12-slim-bookworm

COPY f1pitwall /opt/f1pitwall/f1pitwall
COPY bin/f1ctl /usr/local/bin/f1ctl

RUN chmod 0755 /usr/local/bin/f1ctl \
    && useradd --create-home --uid 1000 agent \
    && mkdir -p /app/submission \
    && chown -R agent:agent /app

ENV PYTHONPATH=/opt/f1pitwall
WORKDIR /app
USER agent
