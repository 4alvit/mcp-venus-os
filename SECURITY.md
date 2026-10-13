# Security

## Threat Model

**Trust boundaries**: the MCP client connection, the Cerbo GX MQTT gateway
(typically LAN port 1883), SSH (typically port 22), and the host configuration.
MCP authentication and device authentication are separate boundaries.

**Attack surface**: every tool exposed by this MCP server is a potential target.

| Tool group | What it changes | Who can call it |
|---|---|---|
| Read tools (battery, PV, grid, inverter) | Nothing — MQTT subscribe only | A connected MCP client; HTTP bearer authentication when configured |
| MQTT write tools (`set_*`) | W/… MQTT topics → Venus device state | A connected MCP client, subject to all write gates |
| SSH tools (`cerbo_*`, `setuphelper_*`) | Shell commands on Cerbo | A connected MCP client when the server has operator-configured SSH credentials; write-shaped tools also require write gates |
| `cerbo_ssh_exec` | Arbitrary shell on Cerbo | A connected MCP client when SSH is configured and all write gates pass |

Without HTTP bearer authentication, any client that can reach the HTTP listener
can call its tools. A client does not need to possess the server's SSH credentials
to request an enabled SSH tool. Restrict listener access and configure
authentication before sharing it. Anyone reaching a separately unauthenticated
MQTT broker can bypass MCP entirely; the MCP write gates cannot secure that
broker or other device clients.

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

Ask the reporter how they wish to be credited. Credit confirmed vulnerability
reports in the advisory or release notes with consent; respect requests for
anonymity and do not publish identifying details or private reports without
permission. Record the report, response, fix and disclosure dates privately so
that the response history can be reviewed without disclosing confidential data.

## Deployment trust boundaries

Keep the default write killswitch disabled until the operator explicitly enables control. Confirmations, path allowlists and value limits are independent gates. An MCP tool call is not authorization to bypass those gates. HTTP transport authentication, MQTT TLS/authentication and SSH host/key controls must match the deployment threat model. Shell access carries the privileges of the configured remote user; deny patterns are an additional safeguard, not a shell sandbox.

Use synthetic data for testing. Never attach live tokens, private keys, database exports or household telemetry to public CI artifacts. Report a suspected credential exposure privately and revoke the credential through its issuer. See [CONTRIBUTING.md](CONTRIBUTING.md) for validation and [the evidence index](docs/openssf-evidence.md) for assessment limits.


## Cryptographic implementation and platform policy

Use current supported Python and TLS/SSH libraries. HTTPS requests retain the
library's certificate verification; do not disable verification to work around
an endpoint error. The audited Python 3.12.14/OpenSSL 3.5.8 default TLS context
requires TLS 1.2 or later, security level 2, at least 128-bit symmetric encryption
and ephemeral key exchange. Retain those requirements on the deployed runtime.
The project delegates cryptographic primitives to FLOSS libraries; it does not
implement a cipher or a random-number generator for keys/nonces. Telemetry
sampling and retry jitter, where present, are not cryptographic operations.

Use authenticated encrypted transport whenever credentials or private data leave
a trusted isolated network. A local plaintext MQTT/HTTP option is not encrypted
by these TLS defaults. Operators must separately verify remote certificates or
SSH host-key fingerprints and replace obsolete endpoint keys. The source and
release downloads are served through GitHub HTTPS.

SSH verifies the operator-approved known-hosts file (the standard user file by
default). Its explicit algorithm policy allows Curve25519, ECDH and SHA-2
finite-field ephemeral key exchange with groups of at least 2048 bits. SHA-1
key exchange and signature/MAC algorithms are excluded. See the SSH setup and
firmware key-rotation instructions in [README.md](README.md).

## Verifying key-length policy in the deployed environment

MQTT TLS delegates to Paho when enabled. SSH has a separate raw-key policy described below; the Go setting for release helpers does not affect SSH or Python TLS.

The verified Python profile is CPython 3.12.14 with OpenSSL 3.5.8 and
SSL security level 2. At this level OpenSSL rejects RSA/DH keys shorter than
2048 bits and elliptic-curve keys shorter than 224 bits. It applies the check
to certificate-chain keys as well as negotiated parameters. Use current
supported runtime builds which preserve this policy; do not lower the security
level or turn off certificate/hostname verification to accept an old endpoint.
Check the interpreter which actually runs the application:

```sh
python - <<'PYTHON'
import ssl
import sys
context = ssl.create_default_context()
print(sys.version)
print(ssl.OPENSSL_VERSION)
print(context.security_level, context.minimum_version.name)
if context.security_level < 2 or context.minimum_version < ssl.TLSVersion.TLSv1_2:
    raise SystemExit("Unsupported TLS policy: upgrade the runtime; do not weaken verification")
PYTHON
```

Release helpers also invoke `gh`, which has a separate TLS implementation.
Follow [the release helper profile](docs/RELEASE_TLS_PROFILE.md) for the tested
GitHub CLI/Go versions and the command-local option that completely disables
smaller certificate keys. That option does not change system-wide settings.

References: [OpenSSL security levels](https://docs.openssl.org/3.5/man3/SSL_CTX_set_security_level/)
and [Python SSL contexts](https://docs.python.org/3.12/library/ssl.html#ssl.SSLContext).

## Credential rotation

Keep passwords and tokens in a separate service-account-readable credentials
file, for example `/run/secrets/mcp-credentials.env`, containing only the required
`HTTP_AUTH_TOKEN`, `MQTT_PASSWORD` and/or `SSH_PASSWORD` entries. Supply that file
through the service manager's `EnvironmentFile` or a separate Compose `env_file`;
keep ordinary settings in another file. Do not commit either deployment file.
SSH private keys already use the separate `SSH_KEY_PATH` file. Restrict parent
directory and file permissions and use a read-only secret mount where available.
The application accepts the resulting environment values, so rotation does not
require changing code or rebuilding packages.

HTTP bearer tokens, MQTT credentials and SSH credentials are deployment inputs,
not permanent identities embedded in the program. To rotate them, provision a
replacement at the issuer/broker/device, update the protected environment or
secret-file input used by the deployment, restart the MCP process and verify a
read-only operation. Then revoke the old credential. Do not assume that editing
an environment file changes the cached configuration of a running process.

For an SSH host-key change, authenticate the new fingerprint through an
independent trusted device-management channel before updating `SSH_KNOWN_HOSTS`.
Never bypass verification to complete a rotation. Keep private keys and `.env`
files readable only by the service account; do not include them in command-line
arguments, logs, source archives or public CI evidence. Test new credentials
with writes disabled before restoring an explicitly approved control workflow.

The [assurance case](docs/security-assurance.md) maps these requirements to
implementation/tests and records the remaining limits, including hardware
qualification and maintainer access continuity.
