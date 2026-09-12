"""Build candidate assets from declared, tracked inputs without installing services."""

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory


def build_package(root: Path, version: str, channel: str, output: Path) -> list[Path]:
    """Build reproducible archives and wheels, preserving committed version metadata."""
    if not re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        message = "Expected a semantic version without path or shell characters"
        raise ValueError(message)
    if channel not in {"nightly", "beta", "rc", "stable"}:
        message = "Unknown release channel"
        raise ValueError(message)
    config = json.loads((root / ".release-package.json").read_text())
    policy = json.loads((root / ".release-policy.json").read_text())
    if policy.get("version_file") == "pyproject.toml":
        committed = tomllib.loads((root / "pyproject.toml").read_text())["project"][
            "version"
        ]
    elif policy.get("version_file"):
        committed = (root / policy["version_file"]).read_text().strip()
    else:
        committed = policy.get("version")
    if committed and (
        version.removeprefix("v").split("-")[0]
        != committed.removeprefix("v").split("-")[0]
    ):
        message = "Candidate base version must match committed project metadata"
        raise ValueError(message)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        message = "Output directory must be empty to prevent stale release assets"
        raise ValueError(message)
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        .decode()
        .split("\0")
    )
    tracked = [name for name in tracked if name]
    if config.get("source", False):
        tracked = [
            name
            for name in tracked
            if (root / name).exists() or (root / name).is_symlink()
        ]
    includes = config.get("include", [])
    for required in includes:
        tracked_input = any(
            name == required or name.startswith(required + "/") for name in tracked
        )
        if not (root / required).exists() or not tracked_input:
            message = f"Missing required runtime input: {required}"
            raise ValueError(message)
    selected = sorted(
        name
        for name in tracked
        if config.get("source", False)
        or any(name == item or name.startswith(item + "/") for item in includes)
    )
    assets = []
    if selected:
        archive = output / f"{config['name']}-{version}.tar.gz"
        with archive.open("wb") as destination:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=destination, mtime=0
            ) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as package:
                    for name in selected:
                        path = root / name
                        if path.is_symlink() or not path.is_file():
                            message = f"Refusing non-regular runtime input: {name}"
                            raise ValueError(message)
                        content = path.read_bytes()
                        entry = tarfile.TarInfo(f"{config['name']}/{name}")
                        entry.size = len(content)
                        entry.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                        package.addfile(entry, io.BytesIO(content))
        assets.append(archive)
    if config.get("wheel", False):
        # Backends may update tracked egg-info files; isolate all build writes.
        with TemporaryDirectory(prefix="release-build-") as directory:
            project = Path(directory) / config["name"]
            project.mkdir()
            for name in tracked:
                source = root / name
                if source.is_symlink():
                    message = f"Refusing symlink in distribution source: {name}"
                    raise ValueError(message)
                if not source.exists() or ".egg-info" in name:
                    continue
                destination = project / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            subprocess.run(
                [sys.executable, "-m", "build", "--outdir", str(output), str(project)],
                check=True,
            )
        distributions = sorted(output.glob("*.whl")) + sorted(output.glob("*.tar.gz"))
        subprocess.run(
            [
                sys.executable,
                "-m",
                "twine",
                "check",
                "--strict",
                *[str(path) for path in distributions if path not in assets],
            ],
            check=True,
        )
        assets = sorted(set(assets + distributions))
    if not assets:
        message = "No release assets were built"
        raise ValueError(message)
    checksum = output / "SHA256SUMS"
    checksum.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in assets
        )
    )
    return assets


def main() -> None:
    """Expose the same packaging command to local operators and GitHub Actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("channel", choices=["nightly", "beta", "rc", "stable"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve() if args.output else root / "release-dist"
    for asset in build_package(root, args.version, args.channel, output):
        sys.stdout.write(f"{asset}\n")


if __name__ == "__main__":
    main()
