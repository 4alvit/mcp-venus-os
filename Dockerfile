# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Multi-stage build: uv installs deps into a venv, slim runtime copies it.
ARG BASE_IMAGE=python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

ARG SOURCE_DATE_EPOCH
ENV UV_LINK_MODE=copy \
    UV_NO_INSTALLER_METADATA=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Install the project itself (non-editable) so the venv is self-contained in the runtime stage
RUN uv sync --frozen --no-dev --no-install-project && \
    uv sync --frozen --no-dev --no-editable && \
    PYTHONHASHSEED=0 .venv/bin/python -m compileall -q -f --invalidation-mode checked-hash .venv && \
    .venv/bin/python -c "import importlib.metadata as m; d=m.distribution('mcp-venus-os'); assert d.version; assert d.read_text('RECORD'); assert any(e.name == 'mcp-venus-os' for e in d.entry_points)"

FROM ${BASE_IMAGE} AS runtime
ARG SOURCE_DATE_EPOCH

# Non-root runtime user; no build tooling in the final image
RUN groupadd -r app && useradd -r -g app -d /app app && \
    chage --lastday "$((SOURCE_DATE_EPOCH / 86400))" app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

# SERVER_TRANSPORT=http in compose; stdio deployments launch the binary directly
ENTRYPOINT ["mcp-venus-os"]
