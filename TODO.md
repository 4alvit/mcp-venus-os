# TODO — mcp-venus-os

Target deployment: **off-device** (Synology Docker + macOS). Direct D-Bus is local-to-Cerbo only,
so the primary transport becomes the **Venus OS MQTT gateway** (`N/<portalId>/…` for reads,
`W/<portalId>/…` for writes). D-Bus stays as an optional on-device backend, not the default.

## 1. Venus OS prerequisites (Cerbo side)

- [x] Enable MQTT Gateway on Cerbo: Settings → Services → MQTT Gateway, mode = "Local network" (listens on LAN :1883)
- [x] Record Venus `portalId` (shown on the MQTT Gateway page / `com.victronenergy.system/Serial`) — `b827ebea1ece`
- [x] Verify from Mac: `mosquitto_sub -h <cerbo-ip> -t 'N/<portalId>/system/#' -v` returns telemetry
- [x] Decide broker auth: anonymous on LAN (gateway confirmed open on :1883; no TLS/auth for local use)

## 2. Config changes (`config.py`, `.env.sample`)

- [x] Add `MQTT_PORTAL_ID` (required when transport = mqtt)
- [x] Add `TRANSPORT_BACKEND` = `mqtt` | `dbus` (default `mqtt`; `dbus` kept for on-device installs)
- [x] Update `.env.sample` with real-world values (host = cerbo IP, portal id placeholder)

## 3. Read path: switch tools from D-Bus to MQTT subscription cache

- [x] Extend `MQTTClient`: on connect, subscribe `N/<portalId>/#` (gateway publishes item values directly under item paths, no `/Value` suffix) and store last value per topic in a dict
- [x] Add `read_path(device_type, instance, path)` helper resolving e.g. `battery/256/Soc`
- [x] Rewrite `get_battery_soc`, `get_pv_power`, `get_grid_status`, `get_inverter_status` to serve from the MQTT cache (map current D-Bus property names → MQTT paths)
- [x] Rewrite `list_devices` from discovered `N/<portalId>/<type>/<instance>` topics
- [x] Stale-data guard: mark readings older than N seconds (default 60s) as stale in tool output (`stale`, `age_seconds`)
- [x] Keep `DBusClient` behind the `TRANSPORT_BACKEND=dbus` switch (no behavior change for on-device mode)
- [x] Delete wrong-direction `publish_battery/publish_pv/publish_grid/publish_inverter` helpers (N/ topics are outbound from Venus only)
- [x] Unit tests: fake broker payloads → tool output mapping; stale-flag logic

## 4. Write tools: implement over `W/<portalId>/…`

- [x] Implement Victron write protocol: publish value to `W/<portalId>/<type>/<instance>/<Path>`, then publish empty payload to `W/<portalId>/<type>/<instance>/<Path>/Keepalive` every ≤60s while value active (50s interval)
- [x] Background asyncio task managing active keepalives; cancel on disconnect/shutdown
- [x] Wire `set_inverter_mode` (path `/Mode`, per-device enum tables in `MODE_CODES` — verify codes on target firmware)
- [x] Wire `set_charge_current_limit` (path `/Dc/0/MaxChargeCurrent`) through validation → publish
- [x] Wire `set_soc_limit` (path `/SocLimit` or BMS equivalent — confirm exact path on target battery) through validation → publish
- [x] Read-back verification: after publish, confirm `N/…` reflects new value within timeout, else report error (5s window)
- [x] Integration test against local mosquitto broker (docker) simulating Venus topic layout (`tests/test_integration_mosquitto.py`, skips when docker unavailable)
- [x] Safety re-check: confirmation flow still gates all three writes; limits enforced pre-publish

## 5. Server transports (how Claude Code reaches it)

- [x] Add CLI flag/env `SERVER_TRANSPORT` = `stdio` | `http` in `__main__.py`
- [x] HTTP mode: FastMCP streamable-http, bind via `SERVER_HOST` (`127.0.0.1:8000` default on Mac; compose sets `0.0.0.0`)
- [x] Optional bearer-token auth for HTTP mode (`SERVER_AUTH_TOKEN`, static verifier; 401 without/wrong token)
- [x] Test: MCP Inspector connect over both transports — verified programmatically instead of the inspector GUI (its `--cli` mode returned empty output): stdio via Python MCP client (`tools/list` = 11, read tools live), HTTP via curl full handshake against Synology (`initialize` → session → `tools/list`; 401 without token). Curl smoke earlier: 406 reachability, 401/406 with token

## 6. Container packaging

- [x] Multi-stage `Dockerfile` (uv install → slim runtime, non-root user, no build deps in final image; `--no-editable` so venv is self-contained)
- [x] `docker-compose.yml`: env-file based config, `restart: unless-stopped`, healthcheck hitting MCP HTTP endpoint
- [x] Pin base image digest (python:3.13-slim multi-arch index); image build in `docker-build.yml` (buildx, all actions SHA-pinned) on PRs → push to ghcr.io/4alvit/mcp-venus-os on main (toolkit reusable docker-build currently broken: `setup-docker` action reads `secrets.` in a composite step — upstream fix needed)

## 7. Synology deployment (`/volume1/docker/mcp-venus-os/`)

- [x] `ssh synology 'sudo mkdir -p /volume1/docker/mcp-venus-os'` (config + docker files live here)
- [x] Copy `docker-compose.yml` + `.env` (real values: cerbo IP, portal id, auth token) to that folder — `.env` generated on the NAS itself (token via openssl there), mode 600
- [x] `ssh synology 'cd /volume1/docker/mcp-venus-os && sudo docker compose up -d'` — host port remapped to **8080** (8000 = Portainer)
- [x] Verify: `docker compose ps` healthy, logs show MQTT connected to cerbo, no reconnect loop
- [x] Verify from Mac: MCP handshake against `http://<synology-ip>:8080/mcp`, bearer auth enforced (401 without token), all read tools live end-to-end
- [x] Document DSM-side notes (Container Manager vs plain compose, port remap, no-scp workaround) in README

## 8. macOS deployment (same machine as Claude Code)

- [x] `uv sync` in repo; smoke-run `uv run mcp-venus-os` (already verified working)
- [x] Register user-scope: `claude mcp add --scope user venus-os -e TRANSPORT_BACKEND=mqtt -e MQTT_HOST=192.168.160.150 -e MQTT_PORTAL_ID=b827ebea1ece -- uv --directory /Users/vmedvedev/victron/mcp-venus-os run mcp-venus-os`
- [x] Alternative (shared with other machines): point Claude Code at Synology HTTP endpoint instead of local process — done 2026-08-23: HTTP endpoint is now the **primary** registration (`http://192.168.167.25:8080/mcp` + bearer token, ✔ Connected); local stdio kept as documented NAS-down fallback; project `.mcp.json` carries a venus-os entry using `VENUS_MCP_TOKEN`
- [x] `claude mcp list` shows `✔ Connected`; read tools verified end-to-end against live Cerbo (battery/grid/PV/inverter via stdio client)

## 9. Claude Code registration cleanup

- [x] Consolidate registration: remove `venus-os` block from `/Users/vmedvedev/victron/.mcp.json` once user-scope entry exists
- [x] Clear stale `disabledMcpServers` entries (`venus-os` removed for `/victron`, `/victron/inverter-desktop`, `/victron/inverter-dashboard-go`; other servers' disables untouched; backup at `~/.claude.json.bak-*`)
- [x] Repo-local `.mcp.json`: keep only graphify (convention picked — repo-local stays minimal, venus-os registered user-scope in §8)

## 10. Docs & release

- [x] README: deployment matrix (macOS stdio / Synology HTTP / on-Cerbo D-Bus), MQTT topic map, safety model
- [x] CHANGELOG entry for transport pivot
- [x] Tag release after end-to-end write test passes against real hardware — done 2026-08-23: live write verified through the Synology HTTP deployment (`set_charge_current_limit` 52→45 A on vebus/290, read-back confirmed in 0.4 s, restored to 52; found+fixed the `{"value": …}` wrapper requirement, #22); tagged **v0.2.0** → GH Release + multi-arch Docker Hub publish (`docker-hub-release.yml`)

## 11. Capability expansion (post-v0.2.0 feedback)

- [x] A. Multi-instance reads: `instance=0` → all devices of a type as `readings` list (+`total_power`), `instance=N` → single dict (MPPT 290/291/292 live case)
- [x] B. Conditional tool registration via broker detection: `inverter/state` → `get_control_state`, `tank/<n>` → `get_tank_level`; bms/tasmota data flows through existing tools (documented, no extra tools)
- [x] C. SSH toolkit (asyncssh): version/IP/update-check/firmware-update/enable-ssh/SetupHelper status+install+remove+update-all/arbitrary exec — confirmation-gated, key-or-password auth from env
- [x] D. `docs/CAPABILITIES.md` served as MCP resource `venus-os://capabilities` + FastMCP instructions so Claude knows the surface at connect
- [x] E. `.env.sample` SSH block, README sections, CHANGELOG Unreleased; live verification through Synology HTTP endpoint after each PR

Live verification (2026-08-24, Synology :8080 + local HTTP w/ key auth):
cold `tools/list` = 12 tools (`get_control_state` registered at boot); PV fan-out
returns solarcharger 290/291/292 **and** both pvinverters (369, 9895) with plain
numeric fields; control state live (Bulk, 3 batteries, 3 MPPT, water 37%);
`pump` correctly absent (no tank topics). Local key-auth run: all 10 SSH tools
registered and verified (`cerbo_version` v3.75, reachability 34 ms,
`setuphelper_status` → dbus-mqtt-battery, gated exec, update dry-run).
