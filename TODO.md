# TODO — mcp-venus-os

Target deployment: **off-device** (Synology Docker + macOS). Direct D-Bus is local-to-Cerbo only,
so the primary transport becomes the **Venus OS MQTT gateway** (`N/<portalId>/…` for reads,
`W/<portalId>/…` for writes). D-Bus stays as an optional on-device backend, not the default.

## 1. Venus OS prerequisites (Cerbo side)

- [ ] Enable MQTT Gateway on Cerbo: Settings → Services → MQTT Gateway, mode = "Local network" (listens on LAN :1883)
- [ ] Record Venus `portalId` (shown on the MQTT Gateway page / `com.victronenergy.system/Serial`)
- [ ] Verify from Mac: `mosquitto_sub -h <cerbo-ip> -t 'N/<portalId>/system/#' -v` returns telemetry
- [ ] Decide broker auth (Venus local gateway allows anonymous on LAN; document if reverse-proxied)

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

- [ ] Implement Victron write protocol: publish value to `W/<portalId>/<type>/<instance>/<Path>`, then publish empty payload to `W/<portalId>/<type>/<instance>/<Path>/Keepalive` every ≤60s while value active
- [ ] Background asyncio task managing active keepalives; cancel on disconnect/shutdown
- [ ] Wire `set_inverter_mode` (path `/Mode`, int codes: 1=on? map enum per docs) through validation → publish
- [ ] Wire `set_charge_current_limit` (path `/Dc/0/MaxChargeCurrent`) through validation → publish
- [ ] Wire `set_soc_limit` (path `/SocLimit` or BMS equivalent — confirm exact path on target battery) through validation → publish
- [ ] Read-back verification: after publish, confirm `N/…` reflects new value within timeout, else report error
- [ ] Integration test against local mosquitto broker (docker) simulating Venus topic layout
- [ ] Safety re-check: confirmation flow still gates all three writes; limits enforced pre-publish

## 5. Server transports (how Claude Code reaches it)

- [ ] Add CLI flag/env `SERVER_TRANSPORT` = `stdio` | `http` in `__main__.py`
- [ ] HTTP mode: FastMCP streamable-http on `0.0.0.0:8000` (container), bind `127.0.0.1:8000` default on Mac
- [ ] Optional bearer-token auth for HTTP mode (`SERVER_AUTH_TOKEN`)
- [ ] Test: `npx @modelcontextprotocol/inspector` connect over both transports

## 6. Container packaging

- [ ] Multi-stage `Dockerfile` (uv install → slim runtime, non-root user, no build deps in final image)
- [ ] `docker-compose.yml`: env-file based config, `restart: unless-stopped`, healthcheck hitting MCP HTTP endpoint
- [ ] Pin base image digest; add image build to CI (existing toolkit workflows)

## 7. Synology deployment (`/volume1/docker/mcp-venus-os/`)

- [ ] `ssh synology 'sudo mkdir -p /volume1/docker/mcp-venus-os'` (config + docker files live here)
- [ ] Copy `docker-compose.yml` + `.env` (real values: cerbo IP, portal id, auth token) to that folder
- [ ] `ssh synology 'cd /volume1/docker/mcp-venus-os && sudo docker compose up -d'`
- [ ] Verify: `docker compose ps` healthy, logs show MQTT connected to cerbo, no reconnect loop
- [ ] Verify from Mac: MCP handshake against `http://<synology-ip>:8000/mcp` returns 11 tools
- [ ] Document DSM-side notes (Container Manager vs plain compose) in README

## 8. macOS deployment (same machine as Claude Code)

- [ ] `uv sync` in repo; smoke-run `uv run mcp-venus-os` (already verified working)
- [ ] Register user-scope (skips per-project approval):
      `claude mcp add --scope user venus-os -e TRANSPORT_BACKEND=mqtt -e MQTT_HOST=<cerbo> -e MQTT_PORTAL_ID=<id> -- uv --directory /Users/vmedvedev/victron/mcp-venus-os run mcp-venus-os`
- [ ] Alternative (shared with other machines): point Claude Code at Synology HTTP endpoint instead of local process
- [ ] `claude mcp list` shows `✔ Connected`; call one read tool end-to-end

## 9. Claude Code registration cleanup

- [ ] Consolidate registration: remove `venus-os` block from `/Users/vmedvedev/victron/.mcp.json` once user-scope (or HTTP) entry exists
- [ ] Clear stale `disabledMcpServers` entries (`/victron`, `/victron/inverter-desktop`, `/victron/inverter-dashboard-go`)
- [ ] Repo-local `.mcp.json`: keep only graphify or add venus-os explicitly — pick one convention

## 10. Docs & release

- [ ] README: deployment matrix (macOS stdio / Synology HTTP / on-Cerbo D-Bus), MQTT topic map, safety model
- [ ] CHANGELOG entry for transport pivot
- [ ] Tag release after end-to-end write test passes against real hardware
