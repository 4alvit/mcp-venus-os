# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- MQTT keepalive-timeout reconnect loop (drop every ~7 min → full retained-tree
  re-flood): inbound messages are now decoded on a worker thread instead of
  inline in paho's network thread, so `_check_keepalive` can no longer be
  starved by the message stream. Protocol keepalive set explicitly to 30s;
  bounded inbox (10k) drops instead of raising under flood.
- Healthcheck false-unhealthy: compose timeout raised 5s→10s — the host stalls
  several seconds under load even though the server answers fine.

### Added

- Multi-instance reads: `instance=0` returns every device of a type as a
  `readings` list with `total_power` (live system runs three MPPTs that a
  first-match read hid); explicit `instance=N` keeps the single-dict shape.
- Conditional tool groups registered only when detected on the broker:
  `get_control_state()` (inverter-control aggregate state) via the
  `inverter/state` topic, `get_tank_level()` (dbus-pump) via `tank/<n>/…`;
  absent services cost zero tool-schema context.
- Cerbo SSH management toolkit over asyncssh (`SSH_PASSWORD`/`SSH_KEY_PATH`
  gated): version/IP/update-check/firmware-update/enable-ssh,
  SetupHelper status/install/remove, arbitrary `cerbo_ssh_exec` — destructive
  and write-shaped operations share the write tools' confirmation gate
  (deduplicated into `_confirm_gate`).
- Capability discovery for clients: MCP resource `venus-os://capabilities`
  plus server `instructions`; full reference in `docs/CAPABILITIES.md`.

### Changed

- MQTT client also subscribes companion-service topics (`inverter/state`,
  `tank/#`) alongside the Venus gateway wildcard.

## [0.2.0] - 2026-08-23

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
- Multi-arch release publishing to **Docker Hub** (`alvit/mcp-venus-os:vX.Y.Z`
  + `latest`) on `v*` tag pushes (`docker-hub-release.yml`; requires
  `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets).
- Project `.mcp.json`: venus-os HTTP entry reading the token from
  `VENUS_MCP_TOKEN`.
- Instance auto-discovery for read tools (real Venus instances are nonzero,
  e.g. battery/289, grid/40, vebus/290) and per-layout topic maps for
  pvinverter/grid-meter services; cold-start warm-up gated on the gateway's
  `full_publish_completed` marker.

### Fixed

- W-topic writes now publish the value wrapped as `{"value": …}` — the Venus
  MQTT gateway silently ignores bare scalars (verified live); read-back
  verification unwraps the gateway's echo dicts before comparing.
- Compose healthcheck used a folded YAML scalar that produced invalid Python
  (`try:` after `;` → SyntaxError → container permanently unhealthy despite a
  working server); now a literal block.

[Unreleased]: https://github.com/4alvit/mcp-venus-os/compare/v0.2.0...HEAD
