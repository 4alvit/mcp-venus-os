# mcp-venus-os — Capability Map

Reference for MCP clients (Claude, …) on what this server can do. The same
summary is served as the MCP resource **`venus-os://capabilities`**; a short
version ships in the server `instructions` so it is visible at connect time.

## Tool groups

### Always present (Venus OS gateway)

| Tool | Notes |
|------|-------|
| `get_battery_soc(instance=0)` | SoC/voltage/current/power/temperature/status/time-to-go |
| `get_pv_power(instance=0)` | solarcharger + pvinverter layouts; V×I fallback |
| `get_grid_status(instance=0)` | grid meter service paths |
| `get_inverter_status(instance=0)` | vebus mode/state/powers/temperature |
| `list_devices()` | every discovered `N/<portal>/<type>/<instance>` |
| `mqtt_connect` / `mqtt_disconnect` / `mqtt_subscribe` (stub) | connection control |

**Multi-instance semantics**: `instance=0` (default) →
`{"readings": [{"device_type", "instance", ...fields}, ...], "total_power": <sum>}`
across *all* devices of the type(s). Explicit `instance=N` → single device dict.
Every reading carries `stale` + `age_seconds` (`MQTT_STALE_AFTER_SECONDS`, 60 s default).

### Conditional — companion services detected on the broker

Registered dynamically only when their marker topics are seen; absent services
cost zero tool-schema context.

| Capability | Marker topic(s) | Tools added |
|------------|-----------------|-------------|
| `control` | `inverter/state` (inverter-control MQTT bridge) | `get_control_state()` — one retained JSON: grid powers, per-battery detail (SoC/V/I/P/time-to-go), per-MPPT breakdown, tasmota plug powers, EV data, water level, control booleans, inverter state + setpoint |
| `pump` | `tank/<n>/…` (dbus-pump) | `get_tank_level(instance=0)` — fresh-water tank level(s) |

Data from dbus-mqtt-battery and dbus-tasmota-pv flows through `get_control_state`
and the Venus tree already — no separate tools by design.

### Conditional — Cerbo management over SSH

Registered only when `SSH_PASSWORD` or `SSH_KEY_PATH` is configured
(`SSH_HOST` defaults to `MQTT_HOST`). Confirmation-gated tools marked 🔒.

| Tool | Purpose |
|------|---------|
| `cerbo_ssh_available()` | TCP probe + latency, no auth |
| `cerbo_version()` | Venus firmware version |
| `cerbo_ip()` | MQTT host + device-reported addresses |
| `cerbo_check_updates()` | firmware update dry run |
| 🔒 `cerbo_firmware_update(confirmed)` | download + apply firmware (reboot likely) |
| 🔒 `cerbo_enable_ssh(password?, confirmed)` | set root password via stdin→chpasswd; generated password returned once |
| `setuphelper_status()` | SetupHelper installed? version? package list |
| 🔒 `setuphelper_install_package(package, repo, confirmed)` | wget+tar+setup pattern |
| 🔒 `setuphelper_remove_package(package, confirmed)` | package's own uninstall script |
| 🔒 `cerbo_ssh_exec(command, timeout_s?, confirmed)` | arbitrary shell command, output capped 4 KB |

### Write tools (Venus gateway, always confirmation-gated)

| Tool | Path | Notes |
|------|------|-------|
| 🔒 `set_inverter_mode(mode, instance, confirmed)` | `W/…/vebus/<inst>/Mode` | enum table per device type; unknown combos rejected pre-publish |
| 🔒 `set_charge_current_limit(current, instance, confirmed)` | `W/…/vebus/<inst>/Dc/0/MaxChargeCurrent` | Amps |
| 🔒 `set_soc_limit(soc_limit, instance, confirmed)` | `W/…/battery/<inst>/SocLimit` | verify exact BMS path on your battery |

Safety order: confirmation gate → hard limits → enum mapping → publish →
read-back verification (5 s) → keepalive every 50 s (write expires ~60 s after
the server stops refreshing). **Acceptance ≠ persistence**: items owned by an
active service (e.g. a BMS driver asserting `MaxChargeCurrent`) get re-applied
within seconds of any external write.

## MQTT topic map

```
N/<portalId>/<type>/<instance>/<Path>            reads (gateway publishes)
W/<portalId>/<type>/<instance>/<Path>            writes ({\"value\": X} JSON!)
W/<portalId>/<type>/<instance>/<Path>/Keepalive  empty payload ≤60s while active
R/<portalId>                                     request a full re-publish
inverter/state                                   inverter-control aggregate (retained)
tank/<n>/Level                                   dbus-pump tank level
battery*/sensor|status|binary_sensor             dbus-mqtt-battery HA-style topics
tele/tasmota_*                                   tasmota plug telemetry
```

## Environment

See [.env.sample](../.env.sample): MQTT (`MQTT_*`), SSH (`SSH_*`),
root-password provisioning (`CERBO_ROOT_PASSWORD`), safety limits
(`SAFETY_*`), HTTP transport (`SERVER_*`).
