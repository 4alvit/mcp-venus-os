# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Transport pivot**: MQTT gateway (`N/<portalId>/…` / `W/<portalId>/…`) is now
  the primary backend so the server can run off-device (Synology Docker, macOS);
  D-Bus remains available behind `TRANSPORT_BACKEND=dbus` for on-device installs.
  - New required config: `MQTT_PORTAL_ID`; new `TRANSPORT_BACKEND` selector
    (default `mqtt`); `MQTT_BASE_TOPIC` removed (prefix derived from portal id).
  - Read tools serve from a subscription cache with a stale-data guard
    (`stale`, `age_seconds`, `MQTT_STALE_AFTER_SECONDS`, default 60s).
  - Write tools execute over `W/…` topics with 50s keepalives and 5s read-back
    verification; per-device Mode enum tables; unknown modes rejected pre-publish.
  - Removed wrong-direction `publish_battery/publish_pv/publish_grid/publish_inverter`
    helpers; `MQTTClient.publish()` now takes absolute topics.
  - `_topic_matches` honors trailing `#` as a multi-level wildcard.

### Added

- `SERVER_TRANSPORT` (`stdio` | `http`) with `--transport` CLI flag,
  `SERVER_HOST`/`SERVER_PORT`, and optional bearer-token auth via
  `SERVER_AUTH_TOKEN` (FastMCP static token verifier).
- Container packaging: multi-stage `Dockerfile` (uv, digest-pinned
  python:3.13-slim runtime, non-root), `docker-compose.yml` with healthcheck,
  CI image build/push to ghcr.io on main.
