#!/usr/bin/env bash
# Export immutable runtime bytes and preserve each platform's original evidence.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f release-dist/SHA256SUMS ]] || { echo 'Build package assets first.' >&2; exit 1; }
asset="mcp-venus-os-container.oci.tar"
sidecar="mcp-venus-os-container.provenance.json"
[[ ! -e "release-dist/$asset" && ! -e "release-dist/$sidecar" ]] || { echo 'Container output already exists.' >&2; exit 1; }
python_bin="${RELEASE_PYTHON:-python3}"
identity="$("$python_bin" scripts/release_container_labels.py --shell)"
read -r package_version source_revision <<< "$identity"
source_epoch="$(git show -s --format=%ct "$source_revision")"
mkdir -p build
inputs="$(mktemp -d "$PWD/build/container-inputs.XXXXXX")"
trap 'if [[ "${KEEP_CONTAINER_INPUTS:-0}" != 1 ]]; then rm -rf "$inputs"; fi' EXIT
for architecture in amd64 arm64; do
  docker buildx build --platform "linux/$architecture" \
    --build-arg "SOURCE_DATE_EPOCH=$source_epoch" \
    --provenance=mode=max \
    --tag "ghcr.io/4alvit/mcp-venus-os:$package_version" \
    --metadata-file "$inputs/$architecture.metadata.json" \
    --label "org.opencontainers.image.version=$package_version" \
    --label "org.opencontainers.image.revision=$source_revision" \
    --output "type=oci,dest=$inputs/$architecture.oci.tar,rewrite-timestamp=true" .
  if [[ "${KEEP_CONTAINER_INPUTS:-0}" == 1 ]]; then
    "$python_bin" scripts/inspect_container_metadata.py "$inputs/$architecture.oci.tar" "$inputs/$architecture.validation.json"
  fi
done
"$python_bin" scripts/release_provenance.py detach --directory release-dist \
  --input "linux/amd64=$inputs/amd64.oci.tar" --input "linux/arm64=$inputs/arm64.oci.tar" \
  --image "$asset" --sidecar "$sidecar"
"$python_bin" - "$asset" "$sidecar" <<'CHECKSUM'
import hashlib
import sys
from pathlib import Path
with Path("release-dist/SHA256SUMS").open("a") as checksums:
    for name in sys.argv[1:]:
        path = Path("release-dist") / name
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        checksums.write(f"{digest}  {name}\n")
CHECKSUM
