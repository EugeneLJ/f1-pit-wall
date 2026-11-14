FROM python:3.12.12-slim-bookworm

# Hidden seed, live state and journal live only in this image/container.
COPY f1pitwall /opt/f1sim/f1pitwall
COPY f1sim /opt/f1sim/f1sim
COPY secret/seed.json /opt/f1sim/secret/seed.json

RUN chmod 0700 /opt/f1sim/secret \
    && chmod 0600 /opt/f1sim/secret/seed.json \
    && mkdir -p /var/lib/f1sim /run/f1sim /evidence \
    && chmod 0700 /var/lib/f1sim \
    && chmod 0755 /run/f1sim

ENV PYTHONPATH=/opt/f1sim PYTHONDONTWRITEBYTECODE=1
HEALTHCHECK --interval=1s --timeout=3s --start-period=2s --retries=30 \
    CMD ["python3", "-m", "f1sim.healthcheck"]
CMD ["python3", "-m", "f1sim.server"]
