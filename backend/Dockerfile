# syntax=docker/dockerfile:1.7
# Multi-stage build, one image per language runtime:
#   docker build --build-arg LANGUAGE=python     -t judge-python .
#   docker build --build-arg LANGUAGE=javascript -t judge-javascript .
# The worker itself is Python in both; the "language" is the runtime user code is executed with.
ARG LANGUAGE=python

FROM python:3.12-slim AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime-python

FROM node:22-slim AS runtime-javascript
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* && ln -sf /usr/bin/python3 /usr/local/bin/python3

FROM runtime-${LANGUAGE} AS final
ARG LANGUAGE
ARG IMAGE_TAG=dev
ENV LANGUAGE=${LANGUAGE} IMAGE_TAG=${IMAGE_TAG} PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/deps:/app SANDBOX_ROOT=/sandbox SANDBOX_UID=65534
# boto3 is pure Python, so the deps layer is portable between the two bases.
COPY --from=deps /install/lib/python3.12/site-packages /opt/deps
WORKDIR /app
COPY shared ./shared
COPY judge ./judge
RUN mkdir -p /sandbox && chmod 755 /sandbox
# Runs as root ON PURPOSE: sandbox.py forks each test case and drops to uid 65534 before exec.
# Fargate supplies the rest (microVM, read-only rootfs, dropped caps, no-egress subnet).
CMD ["python3", "-m", "judge.worker"]
