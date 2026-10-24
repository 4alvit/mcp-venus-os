# Release operations

`release.sh` delegates to the shared release client. PRs validate code; nightly,
beta and RC candidates run the listed validation workflows before building
assets. An RC contains the final package version while its tag and manifest retain
the RC identity. Stable promotion verifies and copies that exact accepted inventory,
including signatures and original build receipts, after protected approval. No
package is rebuilt or re-signed between RC acceptance and stable publication.
The workflow and promotion commands are documented by `python3 scripts/release.py --help`.

## Local validation

```sh
bash scripts/ci.sh --install
bash scripts/ci.sh
bash scripts/ci.sh security
```

The installation command creates `.venv-ci` with the development dependencies.
Use `CI_PYTHON=/path/to/prepared/python` to run in an existing environment.
The security command requires the Trivy CLI and fails when it is unavailable.
The source checks preserve existing coverage thresholds and known type-check
exceptions; a new release is blocked when an enabled check fails.

## Local candidate packaging

```sh
RELEASE_PYTHON="$PWD/.venv-ci/bin/python" bash scripts/package-release.sh VERSION rc
```

Replace VERSION with the committed base version, for example `0.2.12`.
For a publishable candidate, use a disposable checkout at the exact reviewed
commit, download its frozen `.release-plan.json` from the preparation job, and
run `python3 scripts/version_plan.py sync --plan .release-plan.json` first.
The plan supplies one version to `pyproject.toml`, the runtime constant and the
owned `uv.lock` entry. The packager rejects a changed overlay or wrong channel.
Without a plan, only an explicitly local base-version development build is
possible; it cannot produce the required publication receipt.
The output directory `release-dist` must be empty; use `--output /path/to/empty-directory`
for another build. The package builder uses an explicit runtime file list, rejects
missing files and symlinks, preserves executable bits, and writes SHA256SUMS.
Wheel-based projects require `build` and `twine`, installed by the bootstrap above.
Python beta versions use PEP 440 (`0.2.19b1`, for example). Under this
repository's `promote-bytes` policy, RC wheel/sdist versions and OCI labels already
use the final base (`0.2.19`); the release tag, manifest and source identity preserve
the original `v0.2.19-rc.N` qualification. An RC must not be published to the stable
registry channel before its explicit promotion. The release manifest binds the plan, source commit,
actual package metadata and digests. Stage all final files with
`python3 scripts/stage_release_assets.py --target package --pattern 'release-dist/*'`
to verify metadata and record the build receipt. Publication also verifies a
signed inventory; see [signature verification](release-signatures.md).

The build backend is pinned in `pyproject.toml`; install outer build tools from
the hashed `.github/requirements-build.txt`. The packager passes
`SOURCE_DATE_EPOCH` to the backend (default `0`) for repeatable wheel timestamps
and normalizes sdist timestamps, user/group IDs and archive order while retaining
member content and executable permissions. Keep the same epoch and toolchain
when comparing builds. The backend builds in a copy so generated metadata cannot
alter the source checkout. See [quality evidence](quality-evidence.md) for actual
repeat-build results and the separate limits of container reproducibility.

Container projects also export an OCI archive in CI. They never update a registry
from a branch or tag push. Use the shared client's explicit registry promotion
command for approved stable artifacts. Physical device/firmware tests and any
separate PyPI or deployment approvals remain required outside hardware-free CI.
The release policy lists project-specific limits.

Build the matching OCI artifact locally with `bash scripts/package-container.sh`
after Python/native packaging. Docker Buildx and ARM64 emulation must be available.
