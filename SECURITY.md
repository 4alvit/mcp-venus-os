# Security

## Threat Model

**Trust boundary**: the Cerbo GX LAN interface (MQTT :1883) and the SSH port
(:22). Anything reachable from those interfaces is inside the threat model.

**Attack surface**: every tool exposed by this MCP server is a potential target.

| Tool group | What it changes | Who can call it |
|---|---|---|
| Read tools (battery, PV, grid, inverter) | Nothing — MQTT subscribe only | Anyone on LAN |
| MQTT write tools (`set_*`) | W/… MQTT topics → Venus device state | Anyone on LAN |
| SSH tools (`cerbo_*`, `setuphelper_*`) | Shell commands on Cerbo | Anyone with SSH credentials |
| `cerbo_ssh_exec` | Arbitrary shell on Cerbo | Anyone with SSH credentials |

**Control plane posture: deny-by-default.** No write or control tool can mutate
device state unless all three gates pass:

1. **Killswitch** — `SAFETY_ENABLE_WRITES=true` must be set. Default is `false`.
   `confirmed=True` does not bypass this gate.
2. **Path allowlist** — MQTT writes must target a known safe path
   (`Mode`, `Dc/0/MaxChargeCurrent`, `SocLimit` on the correct device type).
3. **Confirmation** — `confirmed=true` must be passed on the tool call,
   unless `SAFETY_REQUIRE_CONFIRMATION=false` (not recommended).

SSH tools additionally run each command through a deny-pattern check
(`ssh_command_deny_patterns`) that blocks filesystem nukes, raw-disk writes,
and pipe-to-shell downloads even when all other gates pass.

**What this does NOT cover** (out of scope for the control plane):

- MQTT broker authentication — broker config is the operator's responsibility.
- SSH credential storage — the `.env` / env-var approach is as secure as the
  host filesystem permissions.
- CVE research, malicious firmware, or physical access to the Cerbo.
- Rate-limiting or DoS protection on the Cerbo MQTT gateway.

## Reporting a Vulnerability

Private vulnerability reporting is enabled for this repository. Use
[Report a vulnerability](https://github.com/4alvit/mcp-venus-os/security/advisories/new)
to send a confidential report to the maintainers. Follow
[GitHub's private reporting instructions](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
if you need help submitting the report.

Include the affected version or commit, steps to reproduce, expected and actual
behavior, and potential impact. Remove access tokens, credentials and personal
data from examples. Do not disclose exploit details in public issues before
coordinating with the maintainers.
