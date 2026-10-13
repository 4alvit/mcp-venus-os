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
executed lines in the denominator. The simple shell launchers are reviewed and
exercise Python entry points; their shell lines are not Python statements.

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

The successful 12 October 2026 local run passed **968 tests**, with three optional
environment skips, and executed **5,655 of 6,376 statements (88.69%)** across all
36 production Python modules. [The measured report](evidence/coverage-2026-10-12.json)
records module hashes, the complete denominator and environment limitations.
Hosted CI remains required for Linux/container-specific validation.

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

[The six-month ledger](evidence/regression-history-2026-10-12.json) links candidate
defect-fix commits to newly added test cases and states where classification or
causal verification remains incomplete. Test names alone do not prove that a
test detects the defect. The ledger deliberately does not claim the Silver
50% requirement while its complete defect denominator is unresolved.

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
their package metadata. [The comparison](evidence/repeat-build-2026-10-12.json)
records the toolchain and hashes. Multi-platform OCI reproducibility remains
unverified, so this does not yet establish the complete Silver build criterion.

## Analysis and limitations

Ruff, mypy, Bandit, CodeQL, dependency review and the release security scanner
complement the tests. Do not weaken their failure thresholds to make a run pass.
Python dependency packages may contain native code, but this repository owns no
native implementation requiring its own AddressSanitizer/Valgrind harness.
The tests use synthetic values and isolated services, never a physical inverter.
Passing them cannot establish firmware compatibility or hardware safety.
