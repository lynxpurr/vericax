#!/usr/bin/env bash
set -euxo pipefail

# This script runs INSIDE the guest over SSH. It installs the dolfinx 0.10
# stack and the OSWorld guest server, enables both services, validates /health
# and /screenshot, and writes the package inventory used by image-build.json.
#
# The build driver powers the guest off after fetching the inventory; this
# script must NOT power off itself.

sudo cloud-init status --wait || true
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip python3-tk python3-dev \
    python3-pyatspi gnome-screenshot xvfb x11-utils x11-xserver-utils \
    scrot curl wget socat wmctrl xclip dbus-x11 at-spi2-core \
    libxkbcommon0 libxcursor1 libxtst6

# --- dolfinx 0.10 stack (P3b) ---
# The EngiWorld reference image pins dolfinx 0.10.0.post2 installed from
# `ppa:fenics-packages/fenics`. That PPA no longer serves the 0.10
# python-binding debs (superseded by 0.11 and deleted from the pool; only the
# soname-versioned C++ libs survive). The reproducible route is therefore:
#   * apt at the exact library versions the reference image carries
#     (petsc 3.19.6 / slepc 3.19.2 / gmsh 4.12.1 / meshio 5.3.5 / openmpi
#     4.1.6, all noble archive; adios2 2.10.2 from the still-published PPA
#     build, key pinned in fenics-ppa-key.asc);
#   * ufl/ffcx/basix/dolfinx built from pinned upstream git tags
#     (dolfinx v0.10.0.post2: its pyproject bakes the module version
#     "0.10.0.post2" the reference image reports; the PPA deb's changelog
#     string was 0.10.0.post3-2~ppa2~noble7).
# Every version is asserted against the reference inventory at the end.

wget -q http://10.0.2.2:8765/fenics-ppa-key.asc -O /tmp/fenics-ppa-key.asc
sudo install -o root -g root -m 0644 /tmp/fenics-ppa-key.asc \
    /etc/apt/trusted.gpg.d/fenics-ppa.asc
sudo tee /etc/apt/sources.list.d/fenics-ppa.sources >/dev/null <<'SRC'
Types: deb
URIs: https://ppa.launchpadcontent.net/fenics-packages/fenics/ubuntu/
Suites: noble
Components: main
Signed-By: /etc/apt/trusted.gpg.d/fenics-ppa.asc
SRC

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    libblas-dev liblapack-dev cmake ninja-build g++ pkg-config \
    libboost-dev libboost-mpi-dev libhdf5-openmpi-dev libpugixml-dev \
    libspdlog-dev libscotch-dev=7.0.4-1ubuntu2 libptscotch-dev=7.0.4-1ubuntu2 \
    mpi-default-dev \
    libpetsc-real3.19-dev=3.19.6+dfsg1-2.2ubuntu2 \
    libslepc-real3.19-dev=3.19.2+dfsg1-2.1build2 \
    python3-numpy python3-mpi4py=3.1.5-5ubuntu2 \
    python3-petsc4py=3.19.6-7ubuntu3 \
    python3-slepc4py=3.19.2-3ubuntu4 \
    gmsh=4.12.1+ds1-1.1build2 python3-gmsh=4.12.1+ds1-1.1build2 \
    python3-meshio=7.0.0-really-5.3.5-1 meshio-tools=7.0.0-really-5.3.5-1 \
    python3-h5py=3.10.0-1ubuntu3 \
    libadios2-common-c++11-dev=2.10.2+dfsg1-2~ppa1~noble1 \
    libadios2-mpi-c++11-dev=2.10.2+dfsg1-2~ppa1~noble1

# Pinned upstream sources (fetch over the build HTTP share; the host verified
# the sha256 of each tarball against the values recorded in the recipe README).
mkdir -p /tmp/src && cd /tmp/src
for t in ufl ffcx basix dolfinx; do
    wget -q "http://10.0.2.2:8765/tarballs/${t}.tar.gz" -O "${t}.tar.gz"
    sha256sum "${t}.tar.gz"
    mkdir "${t}" && tar -xzf "${t}.tar.gz" -C "${t}" --strip-components=1
done

# scikit-build-core/nanobind are build-only deps; exact versions are recorded
# in the inventory (they generate bindings but no numerics). setuptools is
# upgraded because noble's 68.x rejects the PEP 639 string `license` the
# upstream pyprojects use. nanobind is pinned to 2.9.x: the reference image
# was built against nanobind 2.9.2 (PPA buildinfo) and 2.15 type-casters
# reject the Form constructor call shape the python layer uses.
sudo python3 -m pip install --break-system-packages --no-cache-dir \
    --ignore-installed --upgrade "setuptools>=77,<81" "packaging>=24.2"
sudo python3 -m pip install --break-system-packages --no-cache-dir \
    "scikit-build-core[pyproject]>=0.10,<1" "nanobind>=2.9,<2.10"
# ufl/ffcx/basix/dolfinx build with --no-build-isolation against the apt
# numpy/mpi4py/petsc4py, mirroring the Debian packaging of the reference.
sudo env CMAKE_BUILD_PARALLEL_LEVEL=2 python3 -m pip install \
    --break-system-packages --no-build-isolation --no-cache-dir /tmp/src/ufl
sudo env CMAKE_BUILD_PARALLEL_LEVEL=2 python3 -m pip install \
    --break-system-packages --no-build-isolation --no-cache-dir /tmp/src/ffcx
# basix C++ first: its cmake install provides BasixConfig.cmake, which the
# basix python wheel and the dolfinx builds link against (the pip wheel
# alone does not ship a CMake config).
sudo env CMAKE_BUILD_PARALLEL_LEVEL=2 \
    cmake -S /tmp/src/basix/cpp -B /tmp/src/basix/build-cpp \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
sudo env CMAKE_BUILD_PARALLEL_LEVEL=2 cmake --build /tmp/src/basix/build-cpp
sudo cmake --install /tmp/src/basix/build-cpp
sudo env CMAKE_BUILD_PARALLEL_LEVEL=2 python3 -m pip install \
    --break-system-packages --no-build-isolation --no-cache-dir /tmp/src/basix/python
# dolfinx: the C++ library first (the python bindings link against the
# installed DOLFINX CMake config and cannot be built standalone), then the
# python bindings via pip.
#
# Ubuntu's scotch packages ship no SCOTCHConfig.cmake (find_package(SCOTCH
# CONFIG) needs one); provide the minimal imported-target config dolfinx
# expects, pointing at the apt libraries. The reference image links the same
# libptscotch-7.0 runtime.
sudo install -d /usr/local/lib/cmake/SCOTCH
sudo tee /usr/local/lib/cmake/SCOTCH/SCOTCHConfig.cmake >/dev/null <<'SCOTCHCFG'
set(SCOTCH_FOUND TRUE)
set(SCOTCH_VERSION "7.0")
set(SCOTCH_INCLUDE_DIR "/usr/include/scotch")
set(SCOTCH_LIBRARY_DIR "/usr/lib/x86_64-linux-gnu")
if(NOT TARGET SCOTCH::scotch)
  add_library(SCOTCH::scotch UNKNOWN IMPORTED)
  set_target_properties(SCOTCH::scotch PROPERTIES
    IMPORTED_LOCATION "${SCOTCH_LIBRARY_DIR}/libscotch.so"
    INTERFACE_INCLUDE_DIRECTORIES "${SCOTCH_INCLUDE_DIR}")
endif()
if(NOT TARGET SCOTCH::ptscotch)
  add_library(SCOTCH::ptscotch UNKNOWN IMPORTED)
  set_target_properties(SCOTCH::ptscotch PROPERTIES
    IMPORTED_LOCATION "${SCOTCH_LIBRARY_DIR}/libptscotch.so"
    INTERFACE_INCLUDE_DIRECTORIES "${SCOTCH_INCLUDE_DIR}"
    INTERFACE_LINK_LIBRARIES SCOTCH::scotch)
endif()
SCOTCHCFG
sudo env SLEPC_DIR=/usr/lib/slepc CMAKE_BUILD_PARALLEL_LEVEL=2 \
    cmake -S /tmp/src/dolfinx/cpp -B /tmp/src/dolfinx/build \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DCMAKE_PREFIX_PATH=/usr/local/lib/python3.12/dist-packages/basix \
    -DDOLFINX_SKIP_BUILD_TESTS=ON -DDOLFINX_ENABLE_KAHIP=OFF \
    -DDOLFINX_ENABLE_PARMETIS=OFF
sudo env SLEPC_DIR=/usr/lib/slepc CMAKE_BUILD_PARALLEL_LEVEL=2 \
    cmake --build /tmp/src/dolfinx/build
sudo env SLEPC_DIR=/usr/lib/slepc cmake --install /tmp/src/dolfinx/build
# The cmake installs drop libbasix.so/libdolfinx into /usr/local/lib but the
# loader cache only picks them up if ldconfig runs afterwards (it did NOT in
# the guest build; the L0 reference case then failed with
# "libbasix.so: cannot open shared object file"). Refresh explicitly.
sudo ldconfig
# Debian/Ubuntu patch (mirrors the reference image's python3-dolfinx deb):
# PETSc installs its real/complex variant as libpetsc_<type>.so, so
# get_petsc_lib must try that name first or `import dolfinx` fails at
# dolfinx.fem.petsc. Pure path resolution — no numerics involved.
sudo python3 - <<'PY'
import pathlib

p = pathlib.Path("/tmp/src/dolfinx/python/dolfinx/fem/petsc.py")
t = p.read_text()
old = '''    candidate_paths = [
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.so"),'''
new = '''    scalar_type = "complex" if "complex" in petsc_arch else "real"
    candidate_paths = [
        os.path.join(petsc_dir, petsc_arch, "lib", f"libpetsc_{scalar_type}.so"),
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.so"),'''
assert old in t, "petsc.py patch anchor not found"
p.write_text(t.replace(old, new))
print("petsc.py patched for libpetsc_real")
PY
sudo env CMAKE_BUILD_PARALLEL_LEVEL=2 python3 -m pip install \
    --break-system-packages --no-build-isolation --no-cache-dir /tmp/src/dolfinx/python

# --- end dolfinx stack ---

# The venv sees apt-installed pyatspi AND the dolfinx stack above; the OSWorld
# action runner is patched below to use this same interpreter.
sudo python3 -m venv --system-site-packages /home/user/venv
sudo /home/user/venv/bin/pip install --upgrade pip
sudo /home/user/venv/bin/pip install \
    Flask lxml numpy Pillow pynput PyAutoGUI pygame python-xlib requests

# The OSWorld controller runs action scripts as `python3` through
# /run_bash_script; route that name to the venv (pyautogui + dolfinx live there).
sudo tee /usr/local/bin/python3 >/dev/null <<'PY3'
#!/bin/sh
exec /home/user/venv/bin/python "$@"
PY3
sudo chmod 0755 /usr/local/bin/python3
sudo ln -sf /usr/local/bin/python3 /usr/local/bin/python

sudo mkdir -p /home/user/server
wget -q http://10.0.2.2:8765/server.tar.gz -O /tmp/server.tar.gz
sudo tar -xzf /tmp/server.tar.gz -C /home/user/server
sudo chown -R user:user /home/user/server /home/user/venv
sudo install -d -o user -g user /run/user/1000
# The task artifact contract and the episode agent working_dir are
# /home/user/Desktop; the desktop-profile reference image ships it, the
# CLI-only cloud image does not — create it explicitly.
sudo install -d -o user -g user /home/user/Desktop

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

# Assert the dolfinx inventory against the EngiWorld reference image
# (probed 2026-11-21; see containers/images/fenics/README.md).
sudo python3 - <<'PY'
import importlib.metadata as md

expect = {
    "fenics-dolfinx": "0.10.0.post2",
    "fenics-basix": "0.10.0.post0",
    "fenics-ufl": "2025.2.1",
    "fenics-ffcx": "0.10.1.post0",
    "petsc4py": "3.19.6",
    "slepc4py": "3.19.2",
    "mpi4py": "3.1.5",
    "meshio": "5.3.5",
    "numpy": "1.26.4",
}
for name, want in expect.items():
    got = md.version(name)
    assert got == want, f"{name}: installed {got}, reference {want}"
import dolfinx
assert dolfinx.__version__ == "0.10.0.post2", dolfinx.__version__
print("inventory matches reference:", dolfinx.__version__)
PY

# Solve a tiny Poisson problem through the exact interpreter chain the
# controller and the verifiers use (`python3` -> venv -> system dist-packages):
# PETSc assembly is the numerics-carrying path, an import alone is not proof.
python3 - <<'PY'
from dolfinx import fem, mesh
from dolfinx.fem.petsc import LinearProblem
import ufl
import numpy as np
from mpi4py import MPI

msh = mesh.create_unit_square(MPI.COMM_WORLD, 8, 8)
V = fem.functionspace(msh, ("Lagrange", 1))
udim = msh.geometry.dim - 1
facets = mesh.locate_entities_boundary(
    msh, udim, lambda x: np.isclose(x[0], 0.0) | np.isclose(x[0], 1.0))
dofs = fem.locate_dofs_topological(V, udim, facets)
bc = fem.dirichletbc(fem.Constant(msh, 0.0), dofs, V)
u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
problem = LinearProblem(
    ufl.dot(ufl.grad(u), ufl.grad(v)) * ufl.dx, v * ufl.dx, bcs=[bc],
    petsc_options_prefix="vcax_smoke_",
    petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
uh = problem.solve()
print("poisson smoke ok, min/max u:", uh.x.array.min(), uh.x.array.max())
PY

{
    echo "image: FEniCS self-built (P3b)"
    echo "base: Ubuntu 24.04 noble cloud image"
    echo "route: pinned apt versions + pinned upstream git tags (see recipe README)"
    sudo dpkg-query -W -f='${Package} ${Version}\n' \
        libpetsc-real3.19-dev libslepc-real3.19-dev python3-petsc4py \
        python3-slepc4py python3-mpi4py python3-numpy python3-h5py \
        python3-gmsh gmsh python3-meshio meshio-tools \
        'libadios2-common-c++11-dev' 'libadios2-mpi-c++11-dev' 2>/dev/null || true
    python3 - <<'PY'
import importlib.metadata as md
for name in ["fenics-dolfinx", "fenics-basix", "fenics-ufl", "fenics-ffcx",
             "petsc4py", "slepc4py", "mpi4py", "meshio", "numpy",
             "nanobind", "scikit-build-core"]:
    print("pip", name, md.version(name))
PY
    gmsh --version 2>/dev/null || true
    python3 -c 'import dolfinx; print("dolfinx __version__", dolfinx.__version__)'
    /usr/bin/python3 -VV
} | sudo tee /home/user/image-build.txt >/dev/null
