"""Exercise source packaging against isolated tracked inputs, without publishing."""

import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "package_release", Path(__file__).parents[1] / "scripts/package_release.py"
)
assert SPEC is not None
assert SPEC.loader is not None
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """Use real files but an explicit tracked-file inventory, without a git remote."""
    root = tmp_path / "source"
    root.mkdir()
    (root / ".release-package.json").write_text('{"name":"fixture","source":true}')
    (root / ".release-policy.json").write_text('{"version_file":"pyproject.toml"}')
    (root / "pyproject.toml").write_text('[project]\nversion="1.2.3"\n')
    (root / "runtime.py").write_text('print("fixture")\n')
    return root


def build(root: Path, output: Path, tracked: tuple[str, ...] = ("runtime.py",)) -> list[Path]:
    """Supply the same NUL-separated inventory git ls-files returns."""
    with patch.object(package.subprocess, "check_output", return_value="\0".join(tracked).encode()):
        return cast(list[Path], package.build_package(root, "1.2.3", "rc", output))


def test_source_archive_is_repeatable_and_excludes_untracked_files(
    source: Path, tmp_path: Path
) -> None:
    """File timestamps, an unrelated secret and the destination do not change bytes."""
    (source / "private.env").write_text("NOT A REAL SECRET")
    first = build(source, tmp_path / "first")[0]
    (source / "runtime.py").touch()
    second = build(source, tmp_path / "second")[0]
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert archive.getnames() == ["fixture/runtime.py"]
        info = archive.getmember("fixture/runtime.py")
        assert (info.uid, info.gid, info.mtime) == (0, 0, 0)
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    assert (first.parent / "SHA256SUMS").read_text() == f"{digest}  {first.name}\n"


@pytest.mark.parametrize("version", ["../1.2.3", "1.2.3;echo invalid", "1.2", "2.0.0"])
def test_invalid_version_fails_before_creating_output(
    source: Path, tmp_path: Path, version: str
) -> None:
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Expected a semantic version|Candidate base version"):
        package.build_package(source, version, "rc", output)
    assert not output.exists()


def test_invalid_channel_fails_before_output(source: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown release channel"):
        package.build_package(source, "1.2.3", "unreviewed", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_stale_output_is_never_reused(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "stale.whl").write_bytes(b"stale bytes")
    with pytest.raises(ValueError, match="must be empty"):
        build(source, output)
    assert (output / "stale.whl").read_bytes() == b"stale bytes"


def test_required_untracked_input_is_not_packaged(source: Path, tmp_path: Path) -> None:
    (source / ".release-package.json").write_text('{"name":"fixture","include":["required.py"]}')
    (source / "required.py").write_text("# untracked\n")
    with pytest.raises(ValueError, match="Missing required runtime input"):
        build(source, tmp_path / "output")


def test_symlink_input_cannot_disclose_outside_file(source: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("private fixture\n")
    (source / "runtime.py").unlink()
    (source / "runtime.py").symlink_to(outside)
    with pytest.raises(ValueError, match="Refusing non-regular runtime input"):
        build(source, tmp_path / "output")
    assert outside.read_text() == "private fixture\n"


def test_missing_tracked_source_is_not_read(source: Path, tmp_path: Path) -> None:
    result = build(source, tmp_path / "output", ("runtime.py", "deleted.py"))
    with tarfile.open(result[0]) as archive:
        assert archive.getnames() == ["fixture/runtime.py"]


def test_empty_packaging_plan_is_rejected(source: Path, tmp_path: Path) -> None:
    (source / ".release-package.json").write_text('{"name":"fixture"}')
    with pytest.raises(ValueError, match="No release assets"):
        build(source, tmp_path / "output")


def test_declared_subdirectory_is_packaged_with_executable_mode(
    source: Path, tmp_path: Path
) -> None:
    (source / ".release-package.json").write_text('{"name":"fixture","include":["bin"]}')
    (source / "bin").mkdir()
    script = source / "bin" / "run"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    result = build(source, tmp_path / "output", ("runtime.py", "bin/run"))
    with tarfile.open(result[0]) as archive:
        assert archive.getnames() == ["fixture/bin/run"]
        assert archive.getmember("fixture/bin/run").mode == 0o755


@pytest.mark.parametrize("kind", ["version-file", "policy-version"])
def test_version_sources_stay_bound_to_requested_base(
    source: Path, tmp_path: Path, kind: str
) -> None:
    policy = {"version_file": "version"} if kind == "version-file" else {"version": "v1.2.3"}
    (source / ".release-policy.json").write_text(json.dumps(policy))
    (source / "version").write_text("v1.2.3\n")
    assert len(build(source, tmp_path / "output")) == 1


def test_wheel_backend_operates_on_isolated_tracked_copy(source: Path, tmp_path: Path) -> None:
    """Backend writes cannot alter the checkout, and untracked files stay out."""
    (source / ".release-package.json").write_text('{"name":"fixture","wheel":true}')
    (source / "private.env").write_text("not for distribution")
    output = tmp_path / "output"

    def backend(
        command: list[str], *, check: bool, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        assert check
        if command[2] == "build":
            assert env is not None
            assert env["SOURCE_DATE_EPOCH"] == "0"
            isolated = Path(command[-1])
            assert isolated != source
            assert not (isolated / "private.env").exists()
            assert (isolated / "runtime.py").read_bytes() == (source / "runtime.py").read_bytes()
            (isolated / "runtime.py").write_text("# backend mutation\n")
            (output / "fixture-1.2.3-py3-none-any.whl").write_bytes(b"wheel fixture")
        else:
            assert command[2:5] == ["twine", "check", "--strict"]
        return subprocess.CompletedProcess(command, 0)

    with patch.object(package.subprocess, "run", side_effect=backend):
        result = build(source, output)
    assert (source / "runtime.py").read_text() == 'print("fixture")\n'
    assert [p.name for p in result] == ["fixture-1.2.3-py3-none-any.whl"]


def test_versioned_packaging_checks_the_real_frozen_overlay(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PEP 440 RC can package; a changed input or channel cannot reuse its plan."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    version_plan = importlib.import_module("version_plan")
    policy = {
        "repository": "example/fixture",
        "version_file": "pyproject.toml",
        "versioning": {
            "schema": 1,
            "promotion": "final-build",
            "files": [
                {
                    "path": "pyproject.toml",
                    "format": "toml",
                    "field": "project.version",
                    "value": "package",
                    "ecosystem": "pep440",
                }
            ],
        },
    }
    (source / ".release-policy.json").write_text(json.dumps(policy))
    for args in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Packaging fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Reviewed fixture inputs",
        ],
    ):
        subprocess.run(["git", *args], cwd=source, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    plan = version_plan.create_plan("1.2.3", "rc", 7, sha, policy, 7)
    (source / ".release-plan.json").write_text(json.dumps(plan))
    version_plan.sync_versions(source, policy, plan)
    assets = package.build_package(source, "1.2.3", "rc", tmp_path / "valid")
    assert assets[0].name == "fixture-1.2.3-rc.7.tar.gz"
    with tarfile.open(assets[0]) as archive:
        member = archive.extractfile("fixture/pyproject.toml")
        assert member is not None
        assert b"1.2.3rc7" in member.read()
    with pytest.raises(ValueError, match="differ from the frozen plan"):
        package.build_package(source, "1.2.3", "beta", tmp_path / "wrong-channel")
    (source / "pyproject.toml").write_text('[project]\nversion="1.2.4"\n')
    with pytest.raises(ValueError, match="Version inputs do not match release plan"):
        package.build_package(source, "1.2.3", "rc", tmp_path / "changed-input")
    assert not (tmp_path / "wrong-channel").exists()
    assert not (tmp_path / "changed-input").exists()


def test_sdist_normalization_preserves_content_and_removes_host_metadata(tmp_path: Path) -> None:
    paths = [tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"]
    for count, path in enumerate(paths, start=1):
        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            entry = tarfile.TarInfo("fixture/run.py")
            entry.uid = entry.gid = count
            entry.uname = entry.gname = f"builder-{count}"
            entry.mtime = count + 0.5
            entry.mode = 0o755
            entry.size = len(b"content\n")
            archive.addfile(entry, io.BytesIO(b"content\n"))
        package.normalize_sdist(path, 0)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    with tarfile.open(paths[0]) as archive:
        entry = archive.getmember("fixture/run.py")
        assert (entry.uid, entry.gid, entry.uname, entry.gname, entry.mtime) == (0, 0, "", "", 0)
        assert entry.mode == 0o755
        member = archive.extractfile(entry)
        assert member is not None
        assert member.read() == b"content\n"


def test_sdist_normalization_rejects_links_without_replacing_original(tmp_path: Path) -> None:
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        entry = tarfile.TarInfo("fixture/link")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "/outside"
        archive.addfile(entry)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="non-regular member"):
        package.normalize_sdist(path, 0)
    assert path.read_bytes() == original
