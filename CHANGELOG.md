# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.20] - 2026-10-25

### Changed

- Update the locked FastMCP and FastMCP Slim runtime dependencies together from 3.4.5 to 3.4.10.
- Refresh pinned CI Actions while preserving the shared fuzz workflow's configured runner fallback. Update its workflow, runtime input and release policy together to prevent future pin drift.

### Upgrade

Install the new package or container through the existing release procedure and restart the server. Preserve connection settings, credentials and hardware-write permissions, and retain the previous immutable artifacts for rollback. Publishing the beta does not deploy it or establish live-device acceptance.

### Security

Include the [FastMCP 3.4.10 authorization fixes](https://github.com/PrefectHQ/fastmcp/releases/tag/v3.4.10), which recheck transformed components and prevent a denied resource from being served through a matching template, together with the preceding 3.4.x security patches. Existing MCP session limits and device-write safeguards remain enabled.

## [0.2.19]

### Changed

- Require OpenTelemetry API 1.45.1 or newer and refresh its runtime lock.
- Add inbound metadata regression checks for normal, boundary-size and oversized tracestate values.

### Upgrade

Install the new package or container through the existing release procedure. Preserve local configuration and credentials, and retain the previous immutable artifacts for rollback. Publishing this release does not deploy it.

### Security

Fix [GHSA-xcq7-p3pf-p88h](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h), an availability issue caused by unbounded tracestate parsing in OpenTelemetry API through 1.45.0. MCP request metadata is parsed by FastMCP even when no telemetry exporter is configured. The patched parser bounds oversized metadata while retaining valid parent trace context.

## [0.2.18] - 2026-10-22

### Fixed

- Ignore malformed MQTT tank topics during discovery so an unrelated publisher cannot break tank reads. Explicit positive instances read their own cached level directly; discovery keeps numerically sorted, unique canonical tank instances.

### Upgrade

Restart the server after installing the new package. No configuration change is required for canonical `tank/<instance>/Level` publishers. Tank instance identifiers must use nonnegative ASCII decimal integers without signs or leading zeroes (except `0`); malformed aliases are ignored. Freshness reporting and single/multiple-tank response shapes are unchanged. Retain the previous immutable package for rollback.

### Security

- Update the locked development tools to filelock 4.2.1 and virtualenv 21.14.13, addressing CVE-2026-112940 and CVE-2026-115586. Application dependencies and required security checks are unchanged.

Malformed companion-topic identifiers no longer cause an uncaught conversion error that prevents valid tank reads. Update certifi to 2026.10.19 in the application and build-tool locks to remove a compromised CA trust chain, and retain the earlier activation/launcher fixes through virtualenv 21.14.13 with packaging 26.3. Hardware-write permissions and transport authentication are unchanged. Offline checks do not establish live-device acceptance.

## [0.2.17] - 2026-10-18

### Changed

- Update the grouped GitHub Actions dependencies while preserving container, security and release validation.

### Upgrade

Preserve installation-specific configuration and retain the previous immutable release for rollback. Required CI and source-bound RC qualification remain enabled. Publishing this release does not deploy it to an installation or establish hardware acceptance.

### Security

Session bounds, device-write protections and mandatory security checks remain enabled. No new runtime security fix is claimed.

## [0.2.16] - 2026-10-17

### Changed

- Link the shared illustrated RC fuzzing process and result guides; these documentation links were added after the published v0.2.15 source.

### Upgrade

This documentation release preserves runtime behavior and configuration from 0.2.15, including its MCP session-retention fix. Preserve device permissions and connection settings and retain the previous package for rollback.

### Security

No new runtime security fix is claimed. Existing session limits, hardware write protections and source-bound RC fuzzing remain required; physical device acceptance is separate.

## [0.2.15] - 2026-10-16

### Security

Require MCP Python SDK 1.30.0 or newer within the compatible 1.x series to fix
unbounded stateful HTTP session retention (CVE-2026-59951 /
[GHSA-84m7-p3x7-pcfv](https://github.com/advisories/GHSA-84m7-p3x7-pcfv)).
The locked FastMCP version remains 3.4.5. HTTP regression tests exercise session
capacity, deletion, expiry and rejected opening requests without device access.

### Upgrade

Replace the container or upgrade the Python package, preserving configuration.
HTTP clients must reconnect after a server restart or an expired session. The
SDK now expires idle sessions after 30 minutes and limits simultaneous sessions
to 10,000; a full pool returns HTTP 503. Stdio operation and hardware write
safety settings are unchanged. Continue requiring authentication and restricting
endpoint access.

## [0.2.14] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

RC publication rejects absent or invalid source-bound fuzz reports. The fuzz runner bounds corpus paths, file types and size. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

## [0.2.13] - Development line

### Maintenance

- Require bounded fuzzing on public release candidates, with source-bound reports and retained diagnostics; beta and ordinary CI do not run mutation campaigns.
- Reject numeric hardware-contract and write values that exceed the finite hardware range.

### Upgrade

Use the documented update procedure and retain local configuration. Automated tests do not establish target-device acceptance.

### Security

Release qualification now requires isolated fuzzing against the candidate source. Report findings through SECURITY.md.

## [0.2.12]

### Changed

- Make the full multi-platform runnable OCI archive repeatable for the same
  reviewed source and frozen plan. Preserve the original build attestations in
  a separate required provenance file, including their truthful per-run dates.

### Security

- Verify captured signature-control bytes consistently and reject nonregular
  files and aliases. Release verification binds the required OCI/provenance pair
  to the signed inventory, reviewed source, frozen plan and both platforms.

- Reject boolean, non-finite and nonnumeric readbacks when confirming numeric
  hardware writes; a fresh `true` echo no longer confirms a requested mode `1`.
  Finite numeric strings remain compatible with device telemetry.

- Close TLS sockets when native certificate verification or handshake fails,
  while preserving nonblocking read/write retries. Strict warning tests now
  catch leaked sockets before publication.

Reject non-finite numbers and booleans before current-limit comparisons. Reject
invalid or reversed configured safety bounds at startup and require an integer
SoC limit. Validation logs record the operation name without its argument values,
so SSH command arguments are no longer copied into the validation log.

MQTT TLS now rejects undersized keys in the entire verified broker chain before
sending CONNECT or credentials, including RSA 2047-bit trust anchors. Normal CA
and hostname verification and the existing MQTT lifecycle remain active.

Enforce the key-strength policy on both SSH server host keys and the explicitly
selected client private key. RSA keys below 2048 bits and unsupported keys fail
closed. Trusted host matching, revocations and key verification during rekeying
remain active. Only explicit raw-key/password authentication is used; implicit
agents, default identities, hardware tokens, GSS/host-based authentication and
SSH/X.509 certificates cannot bypass the policy.

SSH management verifies the remote host key instead of accepting any key.
Unknown or changed hosts fail closed. An optional `SSH_KNOWN_HOSTS` file allows
an explicit trust store; otherwise standard AsyncSSH known-host files apply.
SSH negotiation also excludes SHA-1 signatures/MACs and non-ephemeral key
exchange. Algorithm selection keeps the trusted `known_hosts` preference order,
so a server offering several keys can still use its trusted RSA/SHA-2 key.
Update obsolete SSH server software instead of disabling verification.

### Upgrade

For new container candidates, retain both `mcp-venus-os-container.oci.tar` and
`mcp-venus-os-container.provenance.json` with the full release asset set. Follow
`docs/release-signatures.md` using the reviewed verifier; the sidecar is required
for provenance verification. The packaging change requires a new RC after RC1
and the normal release acceptance before stable promotion.

Keep current limits finite and non-negative, and keep SoC bounds within 0–100
with the minimum no greater than the maximum. Existing normal numeric environment
values remain supported. Remove secrets from old log archives according to the
operator's retention policy and rotate a credential if it appeared in a command
argument that was logged. This change does not modify device configuration.

For `MQTT_TLS=true`, replace broker or CA keys below the documented minimum before
upgrading. Use supported CPython 3.11+ with the existing `cryptography` dependency;
unsupported verified-chain APIs fail closed. No device or trust-store settings
are changed automatically.

Replace weak SSH keys before upgrading, verifying new host fingerprints through
an independently trusted channel. Configure `SSH_KEY_PATH` and
`SSH_KNOWN_HOSTS` explicitly if an installation previously relied on ambient
AsyncSSH identity/trust configuration. Ordinary RSA-2048+, NIST P-256+, Ed25519
and Ed448 keys remain supported. Alternatively leave both SSH credential
variables unset to keep SSH management tools disabled. No device, credential or
trust-store change is performed automatically. The security documentation also
describes the verified Python and release-helper TLS profiles.

Before using SSH tools, independently verify the Cerbo host-key fingerprint
and install its trusted record. Compose installations must provide
`keys/known_hosts`, mounted read-only with the existing key directory. Existing
installations without a trusted record will refuse SSH access until configured.
After a firmware reflash verify the new key independently before updating it;
there is no verification-disable switch. No hardware access, deployment or
trust-store modification is performed automatically by this release.

The release also adds contributor instructions and a source-linked OpenSSF
assessment, without claiming a badge before the assessment is completed.

### Changed

Release candidates use a frozen version plan for wheel, source package, runtime
version and container labels. Stable publication validates a new final build
against an accepted RC from the same source. Signed inventories bind all release
payloads to the reviewed source and publisher identity. Historical unsigned
releases remain unsigned; signing configuration alone does not award a badge.

Expanded tests measure all Python production modules, including operational
scripts. Governance, contributor conduct, a one-year roadmap and security
assurance are documented. Access continuity remains explicitly unresolved.

## [0.2.4] - 2026-09-12

### Fixed

- Validate SetupHelper package names, check downloads before installation, and
  overlay package sources without deleting local configuration, environments or
  live supervisor directories.
- Delegate removal to the package-owned uninstaller and refuse to delete a
  package directory when no supported uninstaller is available.
- Document offline dependencies, persistent paths and companion-host deployment.
- Align package and runtime version metadata with this release.

The existing MQTT keepalive, discovery and SSH features below were already
included in preceding tags; they remain documented here from the earlier
unreleased changelog. Docker images target Linux amd64 and arm64, not ARMv7 GX
devices. Updating an existing companion host requires its own saved configuration.

## Historical notes for releases after 0.2.0 and before 0.2.4

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

[Unreleased]: https://github.com/4alvit/mcp-venus-os/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/4alvit/mcp-venus-os/compare/v0.2.3...v0.2.4
