#!/usr/bin/env bash
set -euo pipefail
cd /work

if [ ! -f base.img ]; then
    echo "base.img missing" >&2
    exit 2
fi
if [ ! -f seed/user-data ] || [ ! -f seed/meta-data ]; then
    echo "seed files missing" >&2
    exit 2
fi
if [ ! -f http/server.tar.gz ]; then
    echo "server.tar.gz missing" >&2
    exit 2
fi

cp -f base.img work.qcow2
qemu-img resize work.qcow2 50G
cloud-localds seed.iso seed/user-data seed/meta-data

python3 -m http.server 8765 --directory /work/http >/tmp/http.log 2>&1 &
HTTP_PID=$!
trap 'kill $HTTP_PID 2>/dev/null || true' EXIT

qemu-system-x86_64 \
    -m 4096 -smp 4 -enable-kvm -cpu host \
    -drive file=/work/work.qcow2,if=virtio,format=qcow2 \
    -drive file=/work/seed.iso,media=cdrom,format=raw \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 \
    -device virtio-net-pci,netdev=net0 \
    -display none -serial file:/work/serial.log -monitor none \
    -no-reboot &
QEMU_PID=$!

ready=0
for _ in $(seq 1 120); do
    if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -o ConnectTimeout=3 -i /work/id_ed25519 -p 2222 user@127.0.0.1 true 2>/dev/null; then
        ready=1
        break
    fi
    sleep 5
done
if [ "$ready" -ne 1 ]; then
    echo "guest SSH did not become ready; serial log follows" >&2
    tail -80 /work/serial.log >&2 || true
    kill "$QEMU_PID" 2>/dev/null || true
    exit 3
fi

scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /work/id_ed25519 -P 2222 /work/provision.sh user@127.0.0.1:/tmp/provision.sh
set +e
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /work/id_ed25519 -p 2222 user@127.0.0.1 'bash /tmp/provision.sh' \
    > /work/provision.log 2>&1
rc=$?
set -e
cat /work/provision.log

if [ "$rc" -ne 0 ]; then
    echo "provision failed rc=$rc; guest journal tail follows" >&2
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -i /work/id_ed25519 -p 2222 user@127.0.0.1 \
        'sudo journalctl -u osworld --no-pager | tail -80' >&2 || true
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -i /work/id_ed25519 -p 2222 user@127.0.0.1 'sudo poweroff' || true
    wait "$QEMU_PID" || true
    exit "$rc"
fi

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /work/id_ed25519 -p 2222 user@127.0.0.1 'cat /home/user/image-build.txt' \
    > /work/out/provision-info.txt || true
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /work/id_ed25519 -p 2222 user@127.0.0.1 'sudo poweroff' || true

wait "$QEMU_PID" || true

qemu-img check work.qcow2
mkdir -p /work/out
qemu-img convert -O qcow2 -c work.qcow2 /work/out/CalculiX-2.21.qcow2
sha256sum /work/out/CalculiX-2.21.qcow2 | awk '{print $1}' > /work/out/CalculiX-2.21.qcow2.sha256

chown -R 1000:1000 /work/out /work/*.qcow2 /work/*.log /work/*.iso 2>/dev/null || true
echo "image build complete: /work/out/CalculiX-2.21.qcow2"
cat /work/out/CalculiX-2.21.qcow2.sha256