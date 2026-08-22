# Multi-stage build (spec §9): distroless base, non-root UID, read-only root
# filesystem, no-new-privileges, all capabilities dropped, tmpfs scratch.
#
# Ingress and workers run the SAME image but different entrypoints and network
# policy (see docker-compose.yaml): ingress is internet-facing and holds no
# credentials; workers hold credentials and are not internet-reachable.

FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM gcr.io/distroless/python3-debian12:nonroot AS runtime
# Non-root by default in the distroless :nonroot tag (UID 65532).
ENV PYTHONPATH=/install/lib/python3.12/site-packages
COPY --from=build /install /install
COPY workflows /app/workflows
WORKDIR /app
# Entrypoint is overridden per role in docker-compose (ingress vs worker).
ENTRYPOINT ["python", "-m", "wfa"]
