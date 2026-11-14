FROM python:3.12.12-slim-bookworm

WORKDIR /tests
COPY . /tests/
RUN chmod 0755 /tests/test.sh
ENV PYTHONDONTWRITEBYTECODE=1
