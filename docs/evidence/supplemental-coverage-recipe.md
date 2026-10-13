# Reproduce the supplemental source inventory

This is a source-review upper bound, not measured shell coverage. The inventory
records the source revision and SHA-256 of each input file. Its correction adds
14 previously omitted shell/SSH payload entries to the original 40 entries:
204 + 34 = 238 reviewed statements, plus an 18-statement margin = the same 256
uncovered supplemental statements used by the coverage report.

Use the recorded revision, or a later checkout whose recorded input hashes all
match. Prepare the locked development environment as described in
[the quality policy](../quality-evidence.md). Run the following from the
repository root. It reads source and invokes only `bash -n` for syntax checking;
it never executes the recorded commands or connects to a device.

```sh
.venv/bin/python - <<'PY'
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

inventory = json.loads(
    Path('docs/evidence/supplemental-coverage-2026-10-12.json').read_text()
)
entries = inventory['fragments']
for entry in entries:
    data = Path(entry['path']).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry['source_sha256'], entry['path']

# Rebuild the original physical-line-plus-delimiter counts. This intentionally
# counts blanks, comments, continuation lines and some non-executable syntax.
actual = {}
def add(path, fragment, text):
    boundaries = {
        ';': text.count(';'), '&&': text.count('&&'), '||': text.count('||'),
        '$(': text.count('$('), 'backtick_pairs': (text.count('`') + 1) // 2,
    }
    actual[(str(path), fragment)] = len(text.splitlines()) + sum(boundaries.values())

tracked = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
for name in filter(None, tracked):
    path = Path(name)
    if path.is_file():
        data = path.read_bytes()
        if data.startswith(b'#!') and b'python' not in data.splitlines()[0]:
            add(path, 'whole non-Python shebang file (including embedded Python)', data.decode())
for path in sorted(Path('.github/workflows').glob('*.yml')):
    tree = yaml.safe_load(path.read_text())
    for name, job in tree.get('jobs', {}).items():
        for index, step in enumerate(job.get('steps', [])):
            if 'run' in step:
                add(path, f'jobs.{name}.steps[{index}].run', str(step['run']))
add(Path('Dockerfile'), 'whole Dockerfile; counts declarative lines too', Path('Dockerfile').read_text())
path = Path('docker-compose.yml')
for name, service in yaml.safe_load(path.read_text())['services'].items():
    command = service.get('healthcheck', {}).get('test', [])
    if command:
        add(path, f'services.{name}.healthcheck.test', '\n'.join(command))
expected = {
    (entry['path'], entry['fragment']): entry['statement_upper_bound']
    for entry in entries if 'physical_lines_including_blanks_comments_and_continuations' in entry
}
assert actual == expected
assert len(actual) == 40 and sum(actual.values()) == 204

manual = [entry for entry in entries if 'reviewed_commands' in entry]
assert len(manual) == 14
for entry in manual:
    for command in entry['reviewed_commands']:
        subprocess.run(['bash', '-n'], input=command, text=True, check=True)
    if 'count_breakdown' in entry:
        assert sum(entry['count_breakdown'].values()) == entry['statement_upper_bound']
assert sum(entry['statement_upper_bound'] for entry in manual) == 34
assert len(entries) == 54
assert sum(entry['statement_upper_bound'] for entry in entries) == 238
assert inventory['reviewed_statement_upper_bound'] + inventory['rounding_safety_margin'] == 256
assert inventory['supplemental_denominator_used'] == 256
assert inventory['supplemental_covered_statements_credited'] == 0
print('54 fragments; reviewed bound 238; margin 18; supplemental denominator 256')
PY
```

The script verifies recorded inputs and arithmetic; it cannot prove that a new
source revision has no additional fragments. Repeat the source review when code
or configuration changes:

```sh
rg -n 'subprocess|shell=|create_subprocess|\.run\(|bash|local_checks' src scripts .release-policy.json
```

Inspect every subprocess wrapper and its callers, every `run` block and
non-Python shebang, Docker/Compose commands, and AsyncSSH payload construction.
At the recorded revision, local subprocess calls use argument vectors without
`shell=True`. `scripts/release.py::local_checks` invokes `bash -c`; its two policy
commands and fallback are counted separately, even though the fallback repeats
a command. The invoked `scripts/ci.sh` body is already in the original inventory.

For remote commands, compare `reviewed_commands` with the source, including
both literal firmware paths. The package examples instantiate the validated
`package` and `repo` arguments with `example-package` and
`example-owner/example-package`. These values are syntax-review fixtures,
not packages to install. The installer counts twelve statements: `set`, the
`stage` assignment, nested `mktemp`, trap registration, deferred `rm`, `wget`,
`tar`, `test`, `mkdir`, `cp`, `cd`, and the environment-prefixed `bash` invocation.
The IP query counts `ip`, the `awk` invocation and its embedded `print` statement.
The password is stdin data, not shell source. Operator-supplied arbitrary SSH
commands are external input; firmware and package-owned invoked scripts are
third-party implementations. Their invocation wrappers are counted here.

Do not credit any supplemental statement as covered. The traced Python caller
is measured separately from its untraced shell payload. Any changed input hash,
new embedded language, command form or entry point requires renewed review;
do not assume the existing margin covers an unknown addition.
