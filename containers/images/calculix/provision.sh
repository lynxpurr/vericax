#!/usr/bin/env bash
set -euxo pipefail

# This script runs INSIDE the guest over SSH. It installs CalculiX 2.21 and
# the OSWorld guest server, enables both services, validates /health and
# /screenshot, and writes the package inventory used by image-build.json.
#
# The build driver powers the guest off after fetching the inventory; this
# script must NOT power off itself.

sudo cloud-init status --wait || true
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    calculix-ccx=2.21-1 python3 python3-venv python3-pip python3-tk python3-dev \
    python3-pyatspi gnome-screenshot xvfb x11-utils x11-xserver-utils \
    scrot curl wget socat wmctrl xclip dbus-x11 at-spi2-core \
    libxkbcommon0 libxcursor1 libxtst6

# The venv sees apt-installed pyatspi; the OSWorld action runner is patched
# below to use this same interpreter.
sudo python3 -m venv --system-site-packages /home/user/venv
sudo /home/user/venv/bin/pip install --upgrade pip
sudo /home/user/venv/bin/pip install \
    Flask lxml numpy Pillow pynput PyAutoGUI pygame python-xlib requests

sudo mkdir -p /home/user/server
wget -q http://10.0.2.2:8765/server.tar.gz -O /tmp/server.tar.gz
sudo tar -xzf /tmp/server.tar.gz -C /home/user/server
sudo chown -R user:user /home/user/server /home/user/venv
sudo install -d -o user -g user /run/user/1000

# /run_python used the system python; the action scripts need the venv deps.
sudo sed -i 's#/usr/bin/python3#/home/user/venv/bin/python#g' \
    /home/user/server/main.py

# pyautogui's Linux screenshot path calls gnome-screenshot; in this CLI-only
# image we provide a scrot shim (the full GUI profile will use a real desktop).
sudo tee /usr/local/bin/gnome-screenshot >/dev/null <<'WRAP'
#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -f) out="$2"; shift 2 ;;
    --file=*) out="${1#--file=}"; shift ;;
    *) shift ;;
  esac
done
[ -n "$out" ] || exit 2
exec /usr/bin/scrot -o "$out"
WRAP
sudo chmod 0755 /usr/local/bin/gnome-screenshot

# The runner's NIC name differs from the build NIC; DHCP any en* interface.
sudo tee /etc/netplan/99-vericax.yaml >/dev/null <<'YAML'
network:
  version: 2
  ethernets:
    all-en:
      match:
        name: "en*"
      dhcp4: true
      dhcp6: false
      optional: true
YAML
sudo chmod 600 /etc/netplan/99-vericax.yaml
sudo netplan apply || true

sudo tee /etc/systemd/system/xvfb.service >/dev/null <<'EOF'
[Unit]
Description=VeriCAx Xvfb
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :0 -screen 0 1920x1080x24 -ac
Restart=always
RestartSec=2s

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/osworld.service >/dev/null <<'EOF'
[Unit]
Description=VeriCAx OSWorld server
After=network.target xvfb.service
Wants=xvfb.service

[Service]
Type=simple
ExecStart=/home/user/venv/bin/python /home/user/server/main.py
User=user
WorkingDirectory=/home/user
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1000
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now xvfb.service
sudo systemctl enable --now osworld.service

for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:5000/health >/tmp/health.json 2>/dev/null; then
        break
    fi
    sleep 2
done
curl -fsS http://127.0.0.1:5000/health
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null http://127.0.0.1:5000/screenshot 2>/dev/null; then
        break
    fi
    sleep 2
done
curl -fsS -o /dev/null http://127.0.0.1:5000/screenshot

{
    echo "image: CalculiX-2.21 self-built (P3a)"
    echo "base: Ubuntu 24.04 noble cloud image"
    /usr/bin/ccx -v 2>&1 | head -2 || true
    dpkg-query -W -f='${Package} ${Version}\n' \
        calculix-ccx python3 xvfb x11-xserver-utils gnome-screenshot
    /home/user/venv/bin/python --version
} | sudo tee /home/user/image-build.txt >/dev/null