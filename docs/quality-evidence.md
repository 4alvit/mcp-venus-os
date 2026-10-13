# Quality policy and reproducible evidence

The project requires automated tests for major new functionality and a focused
regression case for a defect fix. Test both acceptance and rejection where a
boundary affects device writes, credentials, remote identity or publication.
Review the expected result independently of the implementation. New tests must
run through the normal pytest entry point; their introduction and purpose belong
in the pull request. [CONTRIBUTING.md](../CONTRIBUTING.md) describes the workflow.

## Coverage scope

The measured production scope is every Python module under `src/` and `scripts/`,
including vendored release, registry-publication and security tools. Tests are
discovered in `tests/`, `.github/release-tests/` and `.github/workflow-tests/`.
The report excludes test bodies so adding assertions cannot inflate production
coverage. Namespace-package discovery includes scripts which no test imports.
The minimum required statement coverage is 80%; the configured minimum
is a gate, not a claim that a particular run achieved it. Keep modules with no
executed lines in the denominator. A separate source inventory includes shell
launchers, executable workflow fragments, the Dockerfile, the Compose
healthcheck, release-policy shell checks and fixed/generated SSH payloads. Their coverage is not instrumented, so the all-language lower
bound credits none of those statements as executed.

[The current supplemental inventory](evidence/supplemental-coverage-repeatable-2026-10-12.json)
records 58 reviewed fragments with source hashes and an upper bound of 295
statements. It includes the new container packaging recipe and repeatability
workflow, as well as all fixed/generated shell and SSH payloads. Counting
comments, blank/continuation lines, extra command separators and both fixed
firmware-path alternatives deliberately overstates the executable count.
A further 25-statement margin gives 320 supplemental statements with no
execution credit. The earlier 256-statement bound remains historical evidence
for PR101/PR102; it is not reused after adding new executable fragments.
[Reproduce the inventory review](evidence/supplemental-coverage-recipe.md) whenever
executable fragments change; this is not a general shell parser or measured
shell coverage.

Prepare the locked application/test environment, then run:

```sh
uv sync --locked --extra dev --python 3.12
uv pip install --python .venv/bin/python --require-hashes --only-binary=:all: \
  -r .github/requirements-bandit-1.9.2.txt
.venv/bin/python -m pytest --cov=. \
  --cov-report=term-missing --cov-report=xml --cov-report=json
```

The security boundary tests also require the repository's pinned Bandit tool,
installed by the commands above and by the separate CI security job. Record
interpreter, tool versions, source hashes, executed/skipped
tests and the report's actual numerator/denominator alongside the result. A
failed run is diagnostic evidence, not a successful coverage qualification.
Broker integration tests require the isolated Mosquitto fixture described in
`tests/test_integration_mosquitto.py`; a skipped fixture is not a live-device test.

The earlier PR101 local run on 12 October 2026 passed **984 tests**, with three optional
environment skips, and executed **5,662 of 6,383 statements (88.70%)** across all
36 production Python modules. Counting the 256 supplemental statements and all
5 excluded Python lines as uncovered gives an all-language coverage lower bound
of **5,662 / 6,644 = 85.22%**. This is not a claim of measured shell coverage.
[The report](evidence/coverage-2026-10-12.json) records source hashes, both
denominators and environment limitations. Hosted CI remains required for
Linux/container-specific validation.

The subsequent container/provenance change passed **1,012 tests**, with three
optional environment skips, and executed **6,032 of 6,810 statements (88.58%)**
across all **39 production Python modules**. Including all five excluded lines
and the renewed 320-statement supplemental bound gives
**6,032 / 7,135 = 84.54%**. The
[current coverage record](evidence/coverage-repeatable-2026-10-12.json) binds the
measurement to exact source hashes and records the successful run. This
conservative all-language calculation still gives no credit for shell coverage.

## Warning policy

Ruff enables error, undefined-name, import, naming, modernization, bugbear,
annotation, simplification, comprehension, print/debug, pytest, path, argument,
exception and TODO checks. CI treats every enabled diagnostic as failure; mypy
uses strict mode for the application. The former repository-wide warning
ignores were removed. Exceptions are narrow and documented in `pyproject.toml`:
unused Paho callback arguments, fixture/protocol-double arguments, and return
annotations in retained upstream workflow test helpers. Two public callback/stub
arguments use inline explanations. Vendored scripts keep the upstream E/F/I/UP
policy and its line-length exception so regeneration remains byte-for-byte
verifiable; their security behavior is covered by contract tests and Bandit.

Pytest promotes all Python warnings to errors, including resource leaks and
unraisable exceptions; there are no global warning suppressions. The pinned
third-party build frontend emits a separate virtualenv command-line deprecation
notice during isolated package construction. This is recorded in the build
evidence and does not suppress runtime warnings or relax failure gates.

## Regression history

[The six-month ledger](evidence/regression-history-2026-10-12.json) reviews all
122 first-parent changes through the recorded base revision and links reviewed
behavioral assertions to 68 corrected defects. It uses an upper denominator of
115: all six reported PyJWT findings and all three virtualenv/python-discovery
findings count separately with no regression credit, even though archival
advisory identities and possible duplicates remain unknown. Stale tracked
package metadata counts separately. The resulting lower bound is **59.13%**.

To include PR101 conservatively, that historical ledger adds 15 possible
behavioral defects, deliberately splitting some overlapping boundary fixes,
and gives their tests no additional numerator credit. **68 / 130 = 52.31%**
still exceeds the 50% criterion. These are lower bounds, not exact percentages
of distinct vulnerabilities. Source/assertion review determines credit;
commit subjects and test-function counts alone do not. Test introduction dates
and retrospective additions remain explicit.


The [subsequent reviewed inventory](evidence/regression-repeatable-2026-10-12.json)
retains that history and credits eight merged PR101 regressions backed by the
already published parent/current differential results. It adds 19 further
possible behavior units with no new regression credit, including separately
counted packaging nondeterminism causes and unshipped draft integration failures.
The resulting reviewed-inventory lower bound is **76 / 149 = 51.01%**. This is
not an exact defect universe; the extra denominator intentionally overcounts
possible overlaps. Test-addition dates do not establish bug-introduction dates.

[Differential evidence](evidence/differential-2026-10-12.json) records new tests
run against historical function definitions and the corrected implementation.
This checks the behavior of those definitions in the current test environment;
it does not claim that a complete historical checkout was rebuilt. The MQTT
full-publish regression case was added retrospectively on 12 October 2026 for
the August fix, not in the original fix commit.

## Repeatable build procedure

Use a clean checkout of the reviewed source commit and retain its dependency
locks, build-tool lock, release policy and frozen release plan where applicable.
Use the same supported interpreter, operating system/architecture, build tools,
environment and source timestamp for a repeat comparison. Install the hashed
build requirements from `.github/requirements-build.txt`. Record the build
backend version as well: this project pins the isolated PEP 517 backend in
`pyproject.toml`, separately from the outer environment. Run the documented packaging command
twice into different empty output directories and compare their SHA-256 sums.

The source-archive regression test verifies stable archive ordering, timestamps,
permissions and exclusion of untracked files. It also verifies that package
backends work in an isolated copy. That test alone does not prove byte-for-byte
reproducibility of the wheel, sdist or multi-platform container. Publish measured
comparison results and the actual toolchain before marking repeatable builds
verified. `RELEASE_PYTHON` selects the build interpreter; this project does not
compile owned C/C++ code or recursively invoke Make.

On 12 October 2026, two real builds of the synchronized Python release fixture
produced identical wheel, sdist and checksum bytes, and the build receipt verified
their package metadata. [The historical comparison](evidence/repeat-build-2026-10-12.json)
records that toolchain and its hashes. The current packaging revision was then
[rebuilt twice](evidence/python-repeatable-2026-10-12.json): wheel, sdist and
checksums again matched and both package-metadata receipts passed.

[Two fresh hosted container builders](evidence/container-repeatable-2026-10-12.json)
also produced identical complete multi-platform runnable OCI archives after
independent provenance validation. The [container procedure](container-repeatability.md)
records the exact source, plan, toolchain and diagnostic correction. The diagnostic sidecars are semantically verified; the release workflow also
signs the complete inventory containing those sidecars. Attestation and signature
bytes are not claimed identical. These measurements do not replace device acceptance
or approval of a supported stable release.

## Analysis and limitations

Ruff, mypy, Bandit, CodeQL, dependency review and the release security scanner
complement the tests. Do not weaken their failure thresholds to make a run pass.
Python dependency packages may contain native code, but this repository owns no
native implementation requiring its own AddressSanitizer/Valgrind harness.
The tests use synthetic values and isolated services, never a physical inverter.
Passing them cannot establish firmware compatibility or hardware safety.
