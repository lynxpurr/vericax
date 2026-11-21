# Lessons — Phase 2 P1 铺量、P2 L6、P3a 镜像（2026-11-21）

本文件记录 2026-11-20/21 两轮铺量与 spike 中的**耐久经验**；证据在各任务包
`ground_truth/audit.md`、`runs/` 和 `spec/10` 的计数。规格已同步到
`spec/01/02/05/08/09/10`。

## 1. 题量下限要按 capability 算，不是按总数算

spec/10 的 20 题下限是“每 capability ≥3”。从 14 题补到 20 时，按总数补 6 题
会得到 open-environment 2 题，仍不达标。最终补了 7 题（21 题）才满足：
single 6 / design 5 / cross-stage 4 / observation 3 / open-environment 3。

**要求**：宣布 P1/suite 完成前，先列 capability × 题数矩阵；总数不是门。
剩余 4 题必须全是 `software-selection`，而不是“随便凑 4 题”。

## 2. 审计矩阵的标签和门要早跑

`pack_task.py` 会校验 `NEGATIVE_KINDS` 的 label 必须出现在 `CASES` 中。曾把
`N6/N7/N8/N9` 写成与 `CASES` 不一致，audit 通过但 pack 拒收。铺量时先把
`pack_task --check` 跑起来，再跑贵的 VM 审计。

**要求**：新题的 `NEGATIVE_KINDS` 与 `CASES` 同一次编辑；六类键齐全；
`pack_task --check` 作为第一道本地门。

## 3. script 检查只是威慑，不是执行证明

open-environment 题的 verifier 用 `"skfem" / "pygmsh" / "trimesh" in solve.py`
检查工具使用。0016 的“无工具”负例脚本在注释里写了 `trimesh`，导致检查误收
（MISS）。把注释去掉后通过；但这说明 substring 检查可被注释/字符串绕过。

**要求**：
- 负例脚本不要在自己的注释里出现被检查的工具名；
- 更好的检查是解析 `^\s*(import|from)\s+<tool>`，但仍只是威慑；
- 真正的判据是**数值工件**（verifier 独立重算/精确解），不是脚本文本；
- spec/02 的 L6 也同理：工件-工具等价性 ≠ 调用证明。

## 4. 自建镜像必须从 clean build 验收，且记录 sha

P3a 的调试 work.qcow2 曾能启动，但 clean build 的验收才算数。最终 clean build
产出 Ubuntu 24.04 + `calculix-ccx=2.21-1` 镜像，`task-0001` L0 pass + fake smoke
1.0，sha256 `91b1d6c8…47cd`。

CLI-only OSWorld guest 的五个必要修复（都进了 `containers/images/calculix/provision.sh`）：

1. 通用 DHCP netplan（runner NIC 名与 build NIC 不同）；
2. `x11-xserver-utils`（`prepare_desktop` 调 `xrandr`）；
3. `gnome-screenshot` → `scrot` shim（pyautogui 在 Xvfb 下截图）；
4. `server/main.py` `/run_python` 走 venv；
5. `/usr/local/bin/python3` → venv（controller 的 `/run_bash_script` 以
   `python3` 跑 action；system pip 安装会与 Debian 包冲突）。

**要求**：镜像验收 = clean build + 记录 sha + `/health`/`/screenshot` 200 +
L0 + fake smoke；不要把调试 overlay 当 recipe 验证。换镜像 = 重烘 pins/重审计。

## 5. 环境相关作者坑（逐条可复现）

- CalculiX 2D 单元（CAX4/CPS/CPE）必须位于 `z=0` 平面，轴向为 `y`；CAX4 的
  压力面 `P4` 只加在最内层单元。
- CalculiX 数据行最多 16 项；长 `*Nset/*Elset` 必须换行。
- `*CLOAD` 在 step 2 默认叠加；`OP=NEW` 会重置。verifier 必须按 step 维护
  load state（0010/0008 的教训）。
- 已存在 `*Node Print` 时不要重复注入；否则 `.dat` 的 step block 顺序会错。
- T3D2 桁架用 `*Solid Section` 的面积行；两杆桁架两端都 pin 才稳定，单 roller
  是机构（0012 的 probe 得到 1e9 级位移）。
- FEniCS pygmsh：`mesh.write("mesh.msh")` 会落到 meshio 的 Ansys writer，必须
  `file_format="gmsh22"`。
- pygmsh boolean 会丢弃对象上的 `mesh_size`；用
  `geom.set_mesh_size_callback(...)` 设尺寸场。
- 用坐标找中心/指定节点，不要按固定 node id（不同编号方案会变）。
- 多工件题的 `summary.txt` 要有清晰的量纲/位置定义（beam vs solid、step1/2）。

## 6. open-environment 的 v0.2 形态是本地 wheelhouse

v0.2 不放开外网：`init_file/wheels/` 提供工具轮子（scikit-fem / pygmsh /
trimesh），agent 自行创建/配置环境并从本地安装；sandbox 仍无外网。互联网/包源
按任务放开留 v0.5。任务 JSON 的 `integrity_policy.forbid_third_party_imports`
按题允许相应包。

**要求**：wheelhouse 是任务资源（进 `resources.sha256`）；verifier 在评分 VM
不需要该工具；数值结果/几何量由 verifier 独立校验。

## 7. 分支/PR 栈要显式记录

P1 收尾是在 `feature/phase2-batch2-p2-p3`（PR #14）上叠了
`feature/p1-batch3`。handoff 必须写清 base/head、PR 号、合并顺序；不能只说
“分支存在”。合并流程：squash base → `git rebase --onto develop` → force-with-lease
→ retarget top PR → squash-merge。不要直接 retarget 未 rebase 的 stacked PR。

## 8. L0 / pins 随镜像走

`reference_selfcheck.json` 是派生文件；L0 必须用任务声明的 `solver_probe`
（FEniCS 曾误记 `ccx: command not found`，已在 `lifecycle` 修复）。换镜像后
pins 必须在同镜像重烘并重跑 audit/L0；自建镜像的 L0 记录要单独保存证据，
不要把默认镜像的记录覆盖后当成交付物。
## 9. P3b/P3c 自建镜像：来源必须从"可观测事实"倒推（2026-11-21）

EngiWorld FEniCS 镜像的 dolfinx 0.10 **python 绑定 deb 已被 PPA 永久删除**（被 0.11
superseded，池里只剩 soname 库和 doc；Debian 也没发过 0.10.0.post3）。可复现路线只能是从
**固定上游 tag 重建**（ufl/ffcx/basix/dolfinx），而不是找旧 deb。

- **版本锚点用模块版本，不用 deb 版本**：`dolfinx.__version__` 来自 pyproject，参考镜像报
  `0.10.0.post2` → 用 tag `v0.10.0.post2`（其 changelog 名义是 `0.10.0.post3-2~ppa2~noble7`）。
  验证方式：L0 的 observed summary 与 pins 逐位一致。
- **构建顺序**：ufl → ffcx → **basix C++（cmake install）→ basix python** → **dolfinx C++
  （cmake install）→ dolfinx python**。basix/dolfinx 的 python wheel 不带 CMake config，
  pip-only 构建必失败（`find_package(DOLFINX/Basix)`）。
- **nanobind 必须钉 2.9.x**：PPA 构建用 2.9.2（buildinfo 可查）；nanobind 2.15 的 caster
  拒收 `Form_float64(<uintptr list>, …)` 调用形状（metadata 期签名看起来一样，只有构建版本能暴露）。
- **setuptools≥77 + packaging≥24.2**（noble 自带 68 不认 PEP 639 字符串 license），且要用
  `--ignore-installed`（pip/setuptools/packaging 是 Debian 包，不能卸载）。
- **`cmake --install` 到 /usr/local/lib 后必须 `sudo ldconfig`**：否则 `import basix.ufl`
  在求解时失败（`libbasix.so: cannot open shared object file`），而 provision 的
  `import dolfinx` 冒烟会漏过（basix.ufl 是惰性导入）。
- **CLI-only 镜像必须显式建 `/home/user/Desktop`**：它是工件契约与 agent working_dir；
  缺失时 episode 在 2 秒内 rc=2，而 L0 通过（runtime 的 DesktopEnv 自己会建）。
- Ubuntu 的 scotch 包不带 CMake config；写一个最小 `SCOTCHConfig.cmake`（定义
  `SCOTCH::scotch`/`SCOTCH::ptscotch`）。dolfinx 的 `get_petsc_lib` 需按参考镜像的 Debian
  补丁先找 `libpetsc_real.so`（读参考镜像文件逐字确认）。
- **provision 冒烟要覆盖真实求解路径**：泊松+PETSc 组装一次 + CalculiX 小 job 一次；
  只 import 不够。冒烟里 `ccx -v`/`ccx <job>` 的退出码怪癖见 §11。

## 10. 探测 EngiWorld 镜像的正确姿势（2026-11-21）

- 镜像是 **UEFI/q35**：`-machine type=q35,smm=off -pflash OVMF_CODE_4M.fd -pflash <VARS 副本>`
  + `-device ide-hd`。用 SeaBIOS 会**零写盘零串口地挂死**（看似 CPU 忙、实为固件找不到 ESP）。
- 无 SSH：通道是 guest 内 OSWorld server 的 `POST /execute`（5000 端口，user-mode
  hostfwd）。命令用 base64 包裹（`echo <b64> | base64 -d | bash`）规避 JSON 引号地狱；
  长任务用 `/run_bash_script` 带 `timeout`。读文件用 `POST /file`。
- 一律用 **overlay qcow2**（`qemu-img create -b ref -F qcow2`）只读探查，参考镜像永不被写。

## 11. CalculiX 退出码与 .dat 的实测怪癖（2026-11-21）

- apt `calculix-ccx=2.21-1`：`ccx -v` **打印版本后 exit 201**；且 stdout 走管道时**丢失**
  （异常退出路径不 flush），必须 `ccx -v > file 2>&1` 再 `grep -m1 Version`。成功 job
  exit 0，任何错误（含缺分析卡）exit 201。
- `*STEP` 里没有 `*STATIC`/`*BUCKLE`/`*FREQUENCY` 等分析卡 → `*ERROR … no analysis was
  selected`；`*Frequency` 还需要材料 `*Density`（N-mm-MPa 制钢 `7.85e-9`）。
- OCC `getBoundingBox` 有 ~1e-7 容差垫：用 `== 100.0` 选边会**静默选空**（空物理组 →
  不写 1D 单元）。用 1e-3 绝对容差。
- 频率 `.dat` 表列：mode, eigenvalue(rad²/s²), rad/time, cycles/time；屈曲表头是
  `B U C K L I N G   F A C T O R   O U T P U T`，隔字母写法要用 compact 匹配。

## 12. software-selection 任务（L6 落地）的作者经验（2026-11-21）

- **让 L6 全场比对确定性成立**：在 instruction 里钉死离散化（元素阶次、形式、求解器、
  `petsc_options_prefix`）。否则 agent 的离散解与 verifier 重解天然不同阶，1e-4 全场比对必误杀。
- **坐标键绑定**：`create_mesh` 可能重排几何索引、meshio 与 gmshio 的点序也可能不同——
  提交场↔重解场、token 组↔边界 facet 一律按**舍入坐标键**匹配，绝不按点索引。
- dolfinx 0.10：`dolfinx.io.gmsh`（无 gmshio）、`read_from_msh` 返回 Meshdata 对象、
  `locate_entities_boundary` 在 `dolfinx.mesh`、XDMFFile **没有 read_function**（checkpoint
  只写不读）→ verifier 用 h5py+XML 独立解析（`/Mesh/mesh/geometry`、`/Function/…`；标量
  `(n,1)`、向量 `(n,3)`）。这同时满足 L2 的"独立解析路径"。
- 零右端：`0.0 * v * dx` 报 "missing an integration domain"，用
  `fem.Constant(domain, 0.0) * v * ufl.dx`。
- **meshio `cell_data["gmsh:physical"]` 是按块的 list**：用 `zip(m.cells, …)`，别用扁平
  offset 切片（list 切片与整数比较得 `False`，静默选空）。
- **网格可变任务的 pin 容差**：合法替代网格会让离散 summary 差 ~1%——pinned-reference 检查
  用 ~5e-2（仍能抓镜像漂移），fresh-run 对比保持 1e-4。
- **spec/01 的 `provenance` 块** pack 门不检查，但 spec 要求 L6 题必填；作者自查（本轮补了
  四题的 provenance 与 splits 字段）。

## 13. 发布门与 bootstrap 顺序（harness，2026-11-21）

PR #15 把 L0 记录做成 pack 的硬发布门，但 L0 自身要校验 manifest，而 manifest 只能由 pack
写出、pack 又拒绝无 L0 的首次打包——**新任务无法初始化**。修复：`vericax audit` 仅在
manifest 与 L0 记录**都缺失**时放行（bootstrap 记录 `tree_version=null`），pack 写 manifest
时的 L0 硬门不变。新任务正确顺序：

```
scripts/audit_task.py → vericax audit (bootstrap L0) → pack_task.py
→ vericax audit (刷新 tree_version) → pack_task.py --check → fake episode
```

fake 冒烟必须带 `--payload-dir`（按 `tests/run_acceptance.py:build_payload` 构造）；裸
`vericax run --adapter fake` 会在 2 秒内 rc=2（payload 未挂载）。
