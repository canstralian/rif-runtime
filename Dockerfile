# syntax=docker/dockerfile:1

# Comments are provided throughout this file to help you get started.
# If you need more help, visit the Dockerfile reference guide at
# https://docs.docker.com/go/dockerfile-reference/

# Want to help us make this template better? Share your feedback here: https://forms.gle/ybq9Krt8jtBL3iCk7

ARG PYTHON_VERSION=3.12.3
FROM python:${PYTHON_VERSION}-slim AS base

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-privileged user that the app will run under.
# See https://docs.docker.com/go/dockerfile-user-best-practices/
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Install the hash-pinned runtime lock, not the unconstrained requirements.txt.
# --require-hashes rejects any artefact whose digest is not in the lock, so the
# image is built from the same bytes CI resolves. requirements.txt is
# deliberately unpinned and exists for the merge-gate clean-clone job, which
# wants upstream breakage to surface; an image should not be resolving fresh.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements/runtime.txt,target=requirements/runtime.txt \
    python -m pip install --require-hashes -r requirements/runtime.txt

# Copy the source code into the container before installing the package.
COPY . .

# --no-deps: dependencies are already pinned by the lock above, and an editable
# install cannot itself be hash-checked. Mirrors the CI install order.
RUN python -m pip install -e . --no-deps

# Every preceding layer runs as root, so /app/data lands root-owned while the
# process runs as appuser -- the first decision append then dies with
# PermissionError, after the container has already reported healthy. The data
# directory is the only path the runtime writes: policies.json, decisions.jsonl,
# posture_history.jsonl, metasploit_evidence.jsonl all live there. config/ stays
# root-owned and read-only on purpose.
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

# Switch to the non-privileged user to run the application.
USER appuser

# Expose the port that the application listens on.
EXPOSE 8000

# The service exposes /health; without a HEALTHCHECK an orchestrator has no
# signal beyond "the process is up". Uses python rather than curl so the slim
# image needs no extra package.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

# Run the application. The installed package path (rif_runtime.api), not
# src.rif_runtime.api -- the latter only resolved via implicit namespace
# packages from /app and disagreed with the `rif` console script.
CMD ["uvicorn", "rif_runtime.api:app", "--host=0.0.0.0", "--port=8000"]
