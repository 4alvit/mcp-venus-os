"""Diagnostic evidence keeps subject bindings without publishing build arguments."""

import importlib.util
import io
import json
import tarfile
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/inspect_container_metadata.py"
SPEC = importlib.util.spec_from_file_location("container_metadata", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_diagnostic_keeps_binding_and_excludes_unnecessary_private_fields(tmp_path: Path) -> None:
    records: dict[str, Any] = {
        "statement": {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "slsa",
            "subject": [{"name": "image", "digest": {"sha256": "a" * 64}}],
            "predicate": {"build_args": {"PRIVATE": "not for diagnostic output"}},
        },
        "config": {
            "architecture": "amd64",
            "os": "linux",
            "config": {
                "Env": ["PRIVATE=value"],
                "Labels": {"org.opencontainers.image.revision": "b" * 40},
            },
        },
        "index.json": {"mediaType": "index", "manifests": [{"digest": "sha256:" + "c" * 64}]},
    }
    path = tmp_path / "image.tar"
    with tarfile.open(path, "w") as archive:
        for name, value in records.items():
            raw = json.dumps(value).encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
        raw = b"not JSON layer data"
        info = tarfile.TarInfo("layer")
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
        link = tarfile.TarInfo("symlink")
        link.type = tarfile.SYMTYPE
        link.linkname = "/outside"
        archive.addfile(link)
    result = MODULE.inspect(path)
    assert len(result) == 3
    assert result[0]["subject"] == records["statement"]["subject"]
    assert result[1]["labels"]["org.opencontainers.image.revision"] == "b" * 40
    assert "PRIVATE" not in json.dumps(result)
    assert result[2]["manifests"] == records["index.json"]["manifests"]
