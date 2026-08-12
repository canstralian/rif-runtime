# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.3
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    python -m pip install -r requirements.txt

COPY . .

RUN python -m pip install -e .

# Persistent JSONL ledger lives here; mount a volume at this path in production.
RUN mkdir -p /app/data && chown appuser /app/data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "rif_runtime.api:app", "--host", "0.0.0.0", "--port", "8000"]
