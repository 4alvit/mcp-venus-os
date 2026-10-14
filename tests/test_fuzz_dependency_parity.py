"""The contract fuzz target must exercise the shipped Pydantic dependency versions."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _assert_dependency_parity(runtime: dict, fuzz_lock: str) -> None:
    versions = {
        _normalize_name(package["name"]): package["version"] for package in runtime["package"]
    }
    fuzz = {
        _normalize_name(name): version
        for name, version in re.findall(
            r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", fuzz_lock, flags=re.MULTILINE
        )
    }
    assert {"pydantic", "pydantic-core"} <= fuzz.keys()
    # Atheris is a testing tool. Every other locked package belongs to the
    # production Pydantic closure and must match the container's frozen lock.
    for name, version in fuzz.items():
        if name != "atheris":
            assert versions.get(name) == version, f"Regenerate fuzz lock for {name}"


def test_fuzz_dependency_versions_match_production_lock() -> None:
    _assert_dependency_parity(
        tomllib.loads((ROOT / "uv.lock").read_text()),
        (ROOT / ".github/requirements-fuzz.txt").read_text(),
    )


@pytest.mark.parametrize("name", ["TYPING_Extensions", "Typing.Extensions"])
def test_alternate_package_spelling_cannot_hide_dependency_drift(name: str) -> None:
    runtime = {
        "package": [
            {"name": "pydantic", "version": "2.13.5"},
            {"name": "pydantic-core", "version": "2.46.5"},
            {"name": "typing-extensions", "version": "4.16.0"},
        ]
    }
    fuzz_lock = f"pydantic==2.13.5\npydantic_core==2.46.5\n{name}==4.15.0\n"
    with pytest.raises(AssertionError, match="Regenerate fuzz lock for typing-extensions"):
        _assert_dependency_parity(runtime, fuzz_lock)
