#!/usr/bin/env python3
"""Write bounded validation metadata from OCI archives without extracting or executing."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path
from typing import Any

LIMIT = 2_000_000
FIELDS = (
    "mediaType",
    "artifactType",
    "_type",
    "predicateType",
    "subject",
    "manifests",
    "config",
    "layers",
)


def inspect(path: Path) -> list[dict[str, Any]]:
    """Keep statement subjects and graph descriptors, excluding predicate build arguments."""
    records = []
    budget = 0
    with tarfile.open(path, "r:") as archive:
        for index, member in enumerate(archive):
            if index >= 4096:
                raise ValueError("Too many OCI entries")
            if not member.isfile() or not 0 < member.size <= LIMIT:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                continue
            with stream:
                raw = stream.read(LIMIT + 1)
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(value, dict):
                continue
            budget += len(raw)
            if budget > 32_000_000:
                raise ValueError("Too much OCI metadata")
            selected = {key: value[key] for key in FIELDS if key in value}
            if "architecture" in value:
                labels = value.get("config", {}).get("Labels", {})
                selected = {
                    "architecture": value["architecture"],
                    "os": value.get("os"),
                    "labels": {
                        key: labels.get(key)
                        for key in (
                            "org.opencontainers.image.version",
                            "org.opencontainers.image.revision",
                        )
                    },
                }
            if selected:
                records.append({"entry": member.name, **selected})
    return records


def main() -> None:
    """The caller chooses a build-local input and output; no contents are executed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.archive), indent=2) + "\n")


if __name__ == "__main__":
    main()
