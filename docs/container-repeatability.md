# Container repeatability

The container recipe separates the runnable OCI archive from its build evidence.
`mcp-venus-os-container.oci.tar` contains the original image manifests, configs and
layers for Linux amd64 and arm64. `mcp-venus-os-container.provenance.json` retains
the original BuildKit graphs and exact attestation bytes. Both files are required
release payloads, authenticated by the signed release inventory. See the
[shared verification contract](detached-provenance.md).

The source commit and frozen release plan are inputs. The OCI export has an
explicit `ghcr.io/4alvit/mcp-venus-os:<frozen-version>` name so BuildKit emits a
nonempty in-toto subject bound to the resulting manifest. This local export name
does not push a registry tag. The shipping workflow pins
Buildx 0.37.2, BuildKit 0.33.1 by image digest, the emulation image by digest and
the Dockerfile frontend by digest. Base and builder images are also digest-pinned.
These versions were observed in the successful RC1 build before adoption; changes
to any build input require another repeatability check.

The recipe derives `SOURCE_DATE_EPOCH` from the source commit. BuildKit applies it
to image metadata and rewrites new layer timestamps. Python bytecode uses checked
source hashes; `PYTHONHASHSEED=0` is scoped to compilation, and is not a runtime
environment setting. The pinned uv installer omits its machine-specific installer
metadata; distribution metadata, entry points and `RECORD` remain present. The
final image runs the CLI help path as its non-root account during construction.
Those smoke commands disable bytecode writes only for their own processes: the
beartype import hook otherwise persists timestamped transformed caches.
The normal checked-hash precompilation remains, and runtime settings are unchanged.
The account's shadow date comes from the source epoch; temporary account-tool
backup files are removed in that same layer. Active account records remain.

BuildKit provenance remains enabled in `mode=max`. Its real timestamps and
invocation identifiers are preserved, so evidence from two executions is expected
to differ. Do not add credentials as Docker build arguments: this provenance mode
records build parameters. Use the existing reviewed workflow and secret handling.

## Evidence procedure

The `Container repeatability` workflow builds the shipping recipe on two separate
hosted runners with fresh BuildKit instances and no imported layer cache. A local,
nonpublished diagnostic plan assigns the same source, package version and build
number to both jobs; it does not allocate or publish a release. The comparison
job independently reconstructs that plan, validates each complete provenance graph,
and compares SHA-256 and size of the entire runnable tar. Equal individual layer
hashes are insufficient. Each original sidecar remains downloadable with its
corresponding archive.

The workflow uploads `container-repeatability.json` only after successful semantic
verification; a byte mismatch is recorded and fails the job. Build failures can
retain original platform OCI inputs for diagnosis. The bounded metadata report
includes only graph descriptors, statement type/predicate type/subjects, platform
and source/version labels, excluding predicate build arguments and config environment.
None of these tools extract or execute a downloaded archive.

A successful diagnostic is evidence for that exact source, plan and recorded
build environment. It does not establish acceptance on a Venus OS device or
promise identical evidence sidecars across executions. Packaging changes require
a new RC and the normal [release acceptance](../RELEASING.md) checks before stable
promotion. The previous RC1 predates this packaging change.

## Measured result

[The hosted comparison](evidence/container-repeatable-2026-10-12.json) on
12 October 2026 validated both complete provenance graphs and produced identical
**143,974,400-byte** runnable archives. Both have SHA-256
`5fb3b910374a51b79c1101fdda892b7ee996e7d462043dbc4c51fb4159e15ff8`.
The record includes the tested source/plan, recipe hashes, toolchain, distinct
preserved sidecars and [required CI run](https://github.com/4alvit/mcp-venus-os/actions/runs/38337908962).

The first named-export comparison correctly failed. Its
[diagnostic record](evidence/container-cache-diagnostic-2026-10-12.json) shows
that only the final smoke layer differed: beartype cached source timestamps in
transformed bytecode. The fix prevents those build-time writes while retaining
the real CLI smoke test. The earlier unnamed exporter also correctly failed
because its raw in-toto subject was empty; the explicit frozen-version name
supplies the required manifest subject without publishing a registry tag.
