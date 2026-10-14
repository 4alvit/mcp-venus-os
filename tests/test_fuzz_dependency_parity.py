"""The contract fuzz target must exercise the shipped Pydantic dependency versions."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fuzz_dependency_versions_match_production_lock() -> None:
    runtime = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = {package["name"]: package["version"] for package in runtime["package"]}
    fuzz = dict(
        re.findall(
            r"^([a-z0-9-]+)==([^\s;\\]+)",
            (ROOT / ".github/requirements-fuzz.txt").read_text(),
            flags=re.MULTILINE,
        )
    )
    assert {"pydantic", "pydantic-core"} <= fuzz.keys()
    # Atheris is a testing tool. Every other locked package belongs to the
    # production Pydantic closure and must match the container's frozen lock.
    for name, version in fuzz.items():
        if name != "atheris":
            assert versions.get(name) == version, f"Regenerate fuzz lock for {name}"
