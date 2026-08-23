# syntax=docker/dockerfile:1
# Multi-stage build: uv installs deps into a venv, slim runtime copies it.
ARG BASE_IMAGE=python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Install the project itself (non-editable) so the venv is self-contained in the runtime stage
RUN uv sync --frozen --no-dev --no-install-project && \
    uv sync --frozen --no-dev --no-editable

FROM ${BASE_IMAGE} AS runtime

# Non-root runtime user; no build tooling in the final image
RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

# SERVER_TRANSPORT=http in compose; stdio deployments launch the binary directly
ENTRYPOINT ["mcp-venus-os"]
