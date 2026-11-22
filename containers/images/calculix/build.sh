#!/usr/bin/env bash
# Build a self-contained CalculiX-2.21 qcow2 from a pinned Ubuntu 24.04 cloud
# image (D5 / P3a). Run from the repository root or anywhere; paths are
# derived from this script.
#
#   ./containers/images/calculix/build.sh
#
# The heavy lifting happens in a Docker builder (QEMU/KVM); the host only
# downloads the base image and prepares the seed. The output is written to
#   ${VERICAX_IMAGE_BUILD_DIR:-$HOME/vericax-image-build/calculix}/out/
# and is NOT committed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="${VERICAX_IMAGE_BUILD_DIR:-$HOME/vericax-image-build/calculix}"
BASE_URL="${VERICAX_BASE_URL:-https://cloud-images.ubuntu.com/noble/20261017}"
BASE_IMG="noble-server-cloudimg-amd64.img"
SERVER_DIR="${VERICAX_OSWORLD_SERVER:-}"
BUILDER_TAG="vericax-image-builder:24.04"

if [ -z "$SERVER_DIR" ] || [ ! -d "$SERVER_DIR" ]; then
    echo "OSWorld server bundle not found: ${SERVER_DIR:-<unset>}" >&2
    echo "set VERICAX_OSWORLD_SERVER to the desktop_env/server directory of an" >&2
    echo "EngiWorld runtime clone (docs/setup.md section 2)." >&2
    exit 2
fi

mkdir -p "$WORK/http" "$WORK/seed" "$WORK/out"
cd "$WORK"

if [ ! -f "$BASE_IMG" ]; then
    echo "downloading pinned base image $BASE_URL/$BASE_IMG"
    curl -fL --retry 3 -o "$BASE_IMG.part" "$BASE_URL/$BASE_IMG"
    mv "$BASE_IMG.part" "$BASE_IMG"
fi
if [ ! -f SHA256SUMS ]; then
    curl -fL --retry 3 -o SHA256SUMS "$BASE_URL/SHA256SUMS"
fi
expected="$(grep -E "[ *]${BASE_IMG}$" SHA256SUMS | awk '{print $1}' | head -1)"
actual="$(sha256sum "$BASE_IMG" | awk '{print $1}')"
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    echo "base image sha256 mismatch: expected=$expected actual=$actual" >&2
    exit 3
fi
echo "base sha256: $actual"
ln -f "$WORK/$BASE_IMG" "$WORK/base.img" 2>/dev/null || cp -f "$WORK/$BASE_IMG" "$WORK/base.img"

tar -czf "$WORK/http/server.tar.gz" -C "$SERVER_DIR" .

if [ ! -f "$WORK/id_ed25519" ]; then
    ssh-keygen -t ed25519 -N '' -f "$WORK/id_ed25519" >/dev/null
fi
PUBKEY="$(cat "$WORK/id_ed25519.pub")"
sed "s|__SSH_PUBKEY__|$PUBKEY|" \
    "$REPO_ROOT/containers/images/calculix/user-data.tpl" > "$WORK/seed/user-data"
cp "$REPO_ROOT/containers/images/calculix/meta-data" "$WORK/seed/meta-data"
cp "$REPO_ROOT/containers/images/calculix/provision.sh" "$WORK/provision.sh"
cp "$REPO_ROOT/containers/images/calculix/build_inside.sh" "$WORK/build_inside.sh"
chmod +x "$WORK/provision.sh" "$WORK/build_inside.sh"

docker build -t "$BUILDER_TAG" -f "$REPO_ROOT/containers/images/builder/Dockerfile" "$REPO_ROOT/containers/images/builder"
docker run --rm --device /dev/kvm -v "$WORK":/work "$BUILDER_TAG" bash /work/build_inside.sh

PYTHONHASHSEED=0 python3 - "$WORK" "$BASE_URL" "$BASE_IMG" "$actual" <<'PY'
import datetime
import json
import pathlib
import sys

work = pathlib.Path(sys.argv[1])
base_url, base_img, base_sha = sys.argv[2], sys.argv[3], sys.argv[4]
image = work / "out" / "CalculiX-2.21.qcow2"
sha = (work / "out" / "CalculiX-2.21.qcow2.sha256").read_text().strip()
info = (work / "out" / "provision-info.txt").read_text(errors="ignore")
record = {
    "image": image.name,
    "image_sha256": sha,
    "image_bytes": image.stat().st_size,
    "base_url": f"{base_url}/{base_img}",
    "base_sha256": base_sha,
    "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "builder": "containers/images/builder/Dockerfile",
    "provision": "containers/images/calculix/provision.sh",
    "guest_inventory": info.strip().splitlines(),
    "notes": (
        "P3a CalculiX-only image. The qcow2 is not expected to be bit-identical "
        "across builds (UUIDs/timestamps); reproducibility means the pinned base "
        "sha256, the recorded package versions, and identical audit outputs. "
        "FEniCS and the merged cross-solver image are P3b/P3c."
    ),
}
(work / "out" / "image-build.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
PY

echo
echo "built: $WORK/out/CalculiX-2.21.qcow2"
echo "validate with:"
echo "  VERICAX_IMAGE_DIR=$WORK/out ./bin/vericax audit --task cae--cli--calculix--task-0001 --group reference"