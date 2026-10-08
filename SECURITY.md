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

## Support and response

Security fixes target the current default branch and the latest maintained release, where releases exist. Older versions are not promised backports. Maintainers aim to acknowledge private reports within 14 days, investigate and communicate status within 60 days, and coordinate disclosure with the reporter. Confirmed vulnerabilities with a practical fix receive priority over feature work; publish an advisory and release notes that identify affected versions, mitigation and the fixed version. If a fix takes longer, keep the reporter informed without exposing confidential details.

## Deployment trust boundaries

Keep the default write killswitch disabled until the operator explicitly enables control. Confirmations, path allowlists and value limits are independent gates. An MCP tool call is not authorization to bypass those gates. HTTP transport authentication, MQTT TLS/authentication and SSH host/key controls must match the deployment threat model. Shell access carries the privileges of the configured remote user; deny patterns are an additional safeguard, not a shell sandbox.

Use synthetic data for testing. Never attach live tokens, private keys, database exports or household telemetry to public CI artifacts. Report a suspected credential exposure privately and revoke the credential through its issuer. See [CONTRIBUTING.md](CONTRIBUTING.md) for validation and [the evidence index](docs/openssf-evidence.md) for assessment limits.
