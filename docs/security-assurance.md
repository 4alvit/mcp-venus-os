# Security assurance case

This case links security claims to implementation and tests. It is an engineering
argument with stated limitations, not third-party certification or proof of
hardware safety. Reassess it when a trust boundary, dependency or release path
changes. [SECURITY.md](../SECURITY.md) defines reporting and deployment policy.

## Scope and assumptions

The project includes the Python MCP service and its checked-in operational
scripts. Inputs include MCP tool requests, MQTT messages, D-Bus values, SSH
responses and operator configuration. Dependencies and device firmware are
trusted only within the documented deployment assumptions; a compromised host,
operator account or device can defeat those assumptions. Bind network-facing
MCP transport appropriately and enable its authentication before exposing it.
The local Venus MQTT gateway may be plaintext and needs an isolated trusted
network; TLS settings do not encrypt unrelated plaintext listeners.

## C1: control requests pass independent admission checks

The default write killswitch prevents mutation. The safety validator checks
operation-specific bounds and confirmation; the MQTT client additionally
requires one exact operator-reviewed hardware contract, fresh identities and
qualified value semantics before publishing a write. A read-back echo is not
hardware qualification. Invalid numeric values must be rejected before ordinary
range comparisons. Confirmation of a numeric write rejects boolean, non-finite
and nonnumeric echoes while accepting finite numeric strings from telemetry.

Evidence: [safety.py](../src/mcp_venus_os/safety.py),
[hardware_contracts.py](../src/mcp_venus_os/hardware_contracts.py),
[MQTT client](../src/mcp_venus_os/mqtt_client.py),
[safety denial tests](../tests/test_safety_deny.py),
[numeric boundary tests](../tests/test_safety.py),
[real MCP dispatch and readback tests](../tests/test_write_tools.py), and
[hardware contract tests](../tests/test_hardware_contracts.py).

Limitation: an authorized operator can configure unsafe physical bounds or
approve an unsuitable contract. This software cannot replace independent BMS,
inverter and installation safety controls. SSH command deny patterns are an
additional safeguard, not a sandbox for an authorized shell.

## C2: remote identities are verified before protected traffic

SSH connections use known-host validation and a restricted key/algorithm
policy. MQTT TLS preserves certificate/hostname validation and checks peer-key
strength before sending credentials. Secrets are supplied through deployment
configuration rather than committed source. Rotation is described in
[SECURITY.md](../SECURITY.md#credential-rotation).

Evidence: [SSH client](../src/mcp_venus_os/ssh_client.py),
[TLS policy](../src/mcp_venus_os/tls_policy.py),
[MQTT TLS tests](../tests/test_mqtt_tls.py), and
[SSH key-policy tests](../tests/test_ssh_key_policy.py).

Limitation: plaintext MQTT on an isolated LAN remains plaintext. A valid
certificate or SSH host key does not make the remote firmware trustworthy.
Operators must maintain their trust stores and replace compromised credentials.

## C3: telemetry failures remain bounded and visible

The MQTT client separates network callbacks from processing, retains exact
receive timestamps, bounds cached state and diagnostic data, and constrains
reconnect/shutdown behavior. Callers receive missing/stale data rather than an
implicit approval to write.

Evidence: [MQTT client tests](../tests/test_mqtt_client.py),
[diagnostic tests](../tests/test_mqtt_diagnostics.py),
[socket-event tests](../tests/test_mqtt_socket_events.py), and
[socket diagnostics tests](../tests/test_socket_diagnostics.py).

Limitation: these bounds do not guarantee network availability or protect a
broker against denial of service. Deployments need their own network controls.

## C4: source changes and releases retain reviewable evidence

Contribution policy requires tests for major changes and regression tests for
bug fixes. Required CI runs lint/type/tests and security checks. Release tooling
checks exact source, policy and artifact identities; its offline regression
suite rejects ambiguous or incomplete evidence before publication.

Evidence: [CONTRIBUTING.md](../CONTRIBUTING.md),
[quality gate](../.github/workflows/quality-gate.yml),
[release controller](../scripts/release_control.py),
[release tests](../.github/release-tests), and
[quality evidence](quality-evidence.md).

Limitation: checksums alone do not authenticate a release. Signed-release
compliance requires separately verified signing and recipient-verification
evidence. Repository access continuity is currently unmet as documented in
[GOVERNANCE.md](../GOVERNANCE.md#continuity-status). Passing tests do not establish
acceptance on physical equipment.

## Review procedure

For each security-relevant change, identify the affected claim, update its
implementation/tests and limitations, and record exact validation in the pull
request. Do not remove a limitation until its replacement evidence is publicly
reviewable. Report a counterexample through the confidential vulnerability
process; credit a reporter with their consent and preserve a reproducible test
where safe.
