#!/usr/bin/env bash
# Build a self-contained FEniCS (dolfinx 0.10.0.post2) qcow2 from a pinned
# Ubuntu 24.04 cloud image (D5 / P3b). Run from the repository root or
# anywhere; paths are derived from this script.
#
#   ./containers/images/fenics/build.sh
#
# The heavy lifting happens in a Docker builder (QEMU/KVM); the host only
# downloads/verifies the pinned inputs and prepares the seed. The output is
# written to ${VERICAX_IMAGE_BUILD_DIR:-$HOME/vericax-image-build/fenics}/out/
# and is NOT committed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="${VERICAX_IMAGE_BUILD_DIR:-$HOME/vericax-image-build/fenics}"
BASE_URL="${VERICAX_BASE_URL:-https://cloud-images.ubuntu.com/noble/20261017}"
BASE_IMG="noble-server-cloudimg-amd64.img"
SERVER_DIR="${VERICAX_OSWORLD_SERVER:-}"
BUILDER_TAG="vericax-image-builder:24.04"
RECIPE="$REPO_ROOT/containers/images/fenics"

# Pinned upstream sources: git tag == tarball name, sha256 recorded here.
# dolfinx uses tag v0.10.0.post2 (pyproject bakes module "0.10.0.post2", the
# version the EngiWorld reference image reports).
TARBALLS="
ufl|https://codeload.github.com/FEniCS/ufl/tar.gz/902582a2c9932cf2b46a3a0219c784e8325a2a1c|259812d30cf324ad78f4cf8dbea5cb7125957f031cf11e9eabd72495fb914893
ffcx|https://codeload.github.com/FEniCS/ffcx/tar.gz/009c0e75776314689be039b19eeffad6a1a2817f|ea9b22b6de577e7996b16d2171485fdc8dbd472a2f7bc7aacef1aa81bf8413b7
basix|https://codeload.github.com/FEniCS/basix/tar.gz/433fb7f60f8511e16bcbb403870867d20a69fb4a|94cbc8bbb068f18121bcc19eb22b48e3cd7801f98fd12bbaa35b62eb925d7026
dolfinx|https://codeload.github.com/FEniCS/dolfinx/tar.gz/fbc8e77958ac49b55d9f9940ce481c03a914b298|5993bc857d269cf070a7562256fa7cc20de449fe4e3e020eaad9e49b52522352
"
PPA_KEY_SHA256="62f256fa21f9dbb4290e203a4da3a45f8d11b26c2ca2fee2ba70f2c841782c0f"

if [ -z "$SERVER_DIR" ] || [ ! -d "$SERVER_DIR" ]; then
    echo "OSWorld server bundle not found: ${SERVER_DIR:-<unset>}" >&2
    echo "set VERICAX_OSWORLD_SERVER to the desktop_env/server directory of an" >&2
    echo "EngiWorld runtime clone (docs/setup.md section 2)." >&2
    exit 2
fi

mkdir -p "$WORK/http/tarballs" "$WORK/seed" "$WORK/out"
cd "$WORK"

if [ ! -f "$BASE_IMG" ]; then
    # Same pinned base as the calculix recipe; reuse an already-downloaded copy.
    for c in "$HOME/vericax-image-build/calculix" "$WORK"; do
        if [ -f "$c/$BASE_IMG" ]; then cp -f "$c/$BASE_IMG" "$BASE_IMG.part"; mv "$BASE_IMG.part" "$BASE_IMG"; break; fi
    done
fi
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

# Pinned tarballs and PPA key into the guest-visible http share.
while IFS='|' read -r name url want; do
    [ -n "$name" ] || continue
    f="$WORK/http/tarballs/$name.tar.gz"
    if [ ! -f "$f" ]; then
        echo "fetching $name ($url)"
        curl -fL --retry 3 -o "$f.part" "$url"
        mv "$f.part" "$f"
    fi
    got="$(sha256sum "$f" | awk '{print $1}')"
    if [ "$got" != "$want" ]; then
        echo "$name sha256 mismatch: expected=$want actual=$got" >&2
        exit 3
    fi
    echo "$name sha256 ok"
done <<< "$TARBALLS"
if [ ! -f "$WORK/http/fenics-ppa-key.asc" ]; then
    FP="6C1DA1C0EC4B649179C1C7437C3297BD11D01687"
    curl -fL --retry 3 -o "$WORK/http/fenics-ppa-key.asc" \
        "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x$FP"
fi
got="$(sha256sum "$WORK/http/fenics-ppa-key.asc" | awk '{print $1}')"
if [ "$got" != "$PPA_KEY_SHA256" ]; then
    echo "fenics ppa key sha256 mismatch: expected=$PPA_KEY_SHA256 actual=$got" >&2
    exit 3
fi
echo "fenics ppa key sha256 ok"

tar -czf "$WORK/http/server.tar.gz" -C "$SERVER_DIR" .

if [ ! -f "$WORK/id_ed25519" ]; then
    ssh-keygen -t ed25519 -N '' -f "$WORK/id_ed25519" >/dev/null
fi
PUBKEY="$(cat "$WORK/id_ed25519.pub")"
sed "s|__SSH_PUBKEY__|$PUBKEY|" \
    "$RECIPE/user-data.tpl" > "$WORK/seed/user-data"
cp "$RECIPE/meta-data" "$WORK/seed/meta-data"
cp "$RECIPE/provision.sh" "$WORK/provision.sh"
cp "$RECIPE/build_inside.sh" "$WORK/build_inside.sh"
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
image = work / "out" / "FEniCS.qcow2"
sha = (work / "out" / "FEniCS.qcow2.sha256").read_text().strip()
info = (work / "out" / "provision-info.txt").read_text(errors="ignore")
record = {
    "image": image.name,
    "image_sha256": sha,
    "image_bytes": image.stat().st_size,
    "base_url": f"{base_url}/{base_img}",
    "base_sha256": base_sha,
    "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "builder": "containers/images/builder/Dockerfile",
    "provision": "containers/images/fenics/provision.sh",
    "guest_inventory": info.strip().splitlines(),
    "notes": (
        "P3b FEniCS image. dolfinx 0.10.0.post2 stack rebuilt from pinned "
        "upstream tags (dolfinx v0.10.0.post2) against apt-pinned noble "
        "library versions (petsc 3.19.6, slepc 3.19.2, adios2 2.10.2 from "
        "the fenics PPA) to match the EngiWorld reference inventory; the "
        "PPA's 0.10 python-binding debs are superseded and deleted from the "
        "pool. The qcow2 is not expected to be bit-identical across builds."
    ),
}
(work / "out" / "image-build.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
PY

echo
echo "built: $WORK/out/FEniCS.qcow2"
echo "validate with:"
echo "  VERICAX_IMAGE=$WORK/out/FEniCS.qcow2 ./bin/vericax audit --task cae--cli--fenics--task-0001 --group reference"
