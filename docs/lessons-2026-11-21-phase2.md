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