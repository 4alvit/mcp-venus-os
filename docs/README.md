# Documentation index

These documents describe the MCP server for Venus OS: its capabilities, the
HTTP session and hardware-write boundaries, packaging and assurance evidence.

## Get started

| Document | Description |
| --- | --- |
| [Capability map](CAPABILITIES.md) | Reference for MCP clients on what this server can do. |
| [HTTP session lifecycle](http-session-security.md) | Supported transports, session lifecycle and client configuration. |

## Safety and security

| Document | Description |
| --- | --- |
| [Hardware write qualification](hardware-write-contracts.md) | What must be verified before enabling writes for a new device. |
| [Security assurance case](security-assurance.md) | Claims linked to implementation and tests, with their limits. |

## Package and release

| Document | Description |
| --- | --- |
| [Release operations](release-packaging.md) | Validation workflows run by beta and RC candidates before building. |
| [Verify a signed release](release-signatures.md) | Signature verification for published release assets. |
| [Container repeatability](container-repeatability.md) | Separating the runnable OCI archive from its build evidence. |
| [Repeatable OCI payloads with detached build evidence](detached-provenance.md) | The detached-provenance contract for container bytes. |
| [Release helper TLS profile](RELEASE_TLS_PROFILE.md) | Verified TLS profile used by release helpers. |
| [CI orchestration](CI-ORCHESTRATION.md) | How the quality gate and release pipeline divide validation. |

## Assurance and evidence

| Document | Description |
| --- | --- |
| [Quality policy and reproducible evidence](quality-evidence.md) | Testing requirements and the reproducible evidence behind them. |
| [OpenSSF Best Practices evidence](openssf-evidence.md) | Evidence index for the Passing and Silver self-assessment. |
| [Release-candidate fuzz testing](fuzzing.md) | The bounded RC fuzz target and its release-inventory binding. |
| [Reproduce the supplemental source inventory](evidence/supplemental-coverage-recipe.md) | The review recipe for the supplemental coverage upper bound. |

Shared repository policy: [release-workflow.md](release-workflow.md), [runner-preflight.md](runner-preflight.md), [VERSIONING.md](VERSIONING.md), [rc-fuzzing.md](rc-fuzzing.md) are generated or shared boilerplate maintained in [victron-venus/venus-os-ci-toolkit](https://github.com/victron-venus/venus-os-ci-toolkit).
