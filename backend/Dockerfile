
# syntax=docker/dockerfile:1.7

# Multi-stage build: one image per language runtime.
# Build with LANGUAGE=python or LANGUAGE=javascript.

ARG LANGUAGE=python

# Stage 1: Install Python dependencies
FROM python:3.12-slim AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime-python

# Stage 3: JavaScript runtime
FROM node:22-slim AS runtime-javascript

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /usr/local/lib/node_modules/npm \
              /usr/local/bin/npm \
              /usr/local/bin/npx \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3

# Stage 4: Final image
FROM runtime-${LANGUAGE} AS final

ARG LANGUAGE
ARG IMAGE_TAG=dev

ENV LANGUAGE=${LANGUAGE} \
    IMAGE_TAG=${IMAGE_TAG} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/deps:/app \
    SANDBOX_ROOT=/sandbox \
    SANDBOX_UID=65534

# Copy installed Python dependencies
COPY --from=deps /install/lib/python3.12/site-packages /opt/deps

WORKDIR /app

# Copy judge application
COPY shared ./shared
COPY judge ./judge

# Prepare sandbox directory
RUN mkdir -p /sandbox && chmod 755 /sandbox

# The worker drops privileges when executing submitted code.
CMD ["python3", "-m", "judge.worker"]
