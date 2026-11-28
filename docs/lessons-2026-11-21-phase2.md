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

**2026-11-28 修订**：首次 L0 没通过时也会留下记录（`passed: false`），旧规则看到记录就拒绝再跑
（"package has no manifest"），而 pack 又拒绝未通过的记录——作者只能手删。现在没有 manifest 时，
只有**通过的**记录才构成矛盾；未通过或读不出的记录不挡路。`scripts/audit_suite.py` 也按包的
状态选顺序：有 manifest 且记录通过 → audit → pack → L0 → check；新包 → audit → L0 → pack →
L0 → check；有 manifest 但记录未通过 → L0 → audit → pack → L0 → check。另外两个只在新题上
出现、审计发现不了的问题：评分是带外的，verifier 只能依赖声明的交付物（L0 是唯一按评分方式
布置文件的门）；gold 和 verifier 共用求解模板时，审计矩阵只证明两者一致——0019 的模板把厚度
只乘在载荷项上，参考值大了两倍，26 个用例照样全过，直到校准批里所有 agent 的正确解被拒。
出 gold 后先和手算估计对照，再跑模型。

## 14. P4 并行调度与 L6 challenge 绑定（2026-11-22）

- **先修清理顺序再谈并行**：旧 `run_episode` 在 sandbox 还开着时就启动 scoring VM，单 episode
  同时占 2 台 VM。按 spec/09 E5 改成 freeze → 关 sandbox → scoring 后，2 个并行 episode 的
  峰值才是 2 台。验收：两道 fake 各 1.0，并行 wall 423s，两集 wall 合计 841s。
- **并行只共享两处，都要显式处理**：episode 目录用毫秒 + 3 字节随机（同秒不撞）；镜像 sha
  缓存改成进程内锁 + `os.replace` 原子写（否则并发读到半截文件）。其余（overlay、容器名、
  proxy socket、scoring cache）本来就按 episode 分目录。
- **batch 需要 per-task payload/image 映射**：`--payload-dir-map TASK=DIR` 与
  `--image SNAPSHOT=PATH`；跨 snapshot 时禁止用单一 `VERICAX_IMAGE`，否则所有题都会被
  指向同一张镜像。
- **challenge token 分三处落地**：题面用 `{challenge}` 占位符；agent 容器注入
  `VERICAX_CHALLENGE`（不注入 `VERICAX_TOOL`，选工具是能力）；scoring 实例注入两者。
  verifier 用 `os.environ.get("VERICAX_CHALLENGE", <audit token>)`，所以 L0/audit 无 env 时
  行为不变。5 道 L6 题改完必须 `pack → vericax audit（刷新 tree_version）→ pack --check`。
- **fake agent 要重写 token**：gold recipe 里是固定 audit token；测试 payload 把
  `audit_token` 传给 fake_agent，由它把 recipe 中的 audit token 替换成 episode token。
  `wrong_challenge` 模式故意不替换，用来证明 L6.3 拒绝重放（实测 0.0）。
- **文档计数核对**：套件实际是 26 个任务包（25 道 Phase 2 目标 + 1 道 L6 原型），
  `25 题` 的说法漏掉了原型；spec/10 §2 的表有 26 行，§4 矩阵必须把 prototype 计入
  single-execution，否则总数对不上。

## 15. P5 三栈 adapter 与 phase2 镜像（2026-11-22）

- **直接用官方 Hermes 镜像做基座**：`nousresearch/hermes-agent:v0.21.6` 已带 Python 3.14、
  Node 26、`/opt/hermes` 与 `HERMES_HOME=/opt/data`；清除其 `ENTRYPOINT`（harness 以
  adapter argv 为主进程），再 npm 装其余四栈。自己 pip 装 hermes 走不通：
  `hermes-agent` 的构建后端明确拒绝 wheel/sdist，只支持 installer/Docker/Nix。
- **npm 12 默认不跑 lifecycle scripts**：不加 `--allow-scripts=opencode-ai,...` 时
  `opencode.exe` 只是 479 字节的报错 stub，`opencode --version` 直接退出。另外全局 bin
  在 `/opt/hermes/tools/node-<ver>/bin`，必须加进 PATH（`ENV PATH=...:$PATH`），
  否则 `command -v opencode` 全部 MISSING。
- **三个 headless 入口的实测形态**：
  `opencode run --format json --auto --model deepseek/deepseek-flash <instruction>`；
  `hermes -z <instruction> --yolo --ignore-user-config --provider deepseek -m deepseek-flash -t terminal`
  （`-t` 是逗号分隔名，不是 JSON 数组）；`openclaw agent exec --message-file - --json`
  （instruction 走 stdin，`--code-mode direct`）。
- **凭据一律 env 注入**：opencode profile 用 `{env:DEEPSEEK_API_KEY}`，openclaw 用
  `source:"env"` SecretRef，hermes 读同名变量；`[container] env_from` 从宿主转发，
  不写进镜像/不落盘。profile 里同时 deny 原生文件工具
  （opencode `permission.read/write/edit=deny`，openclaw `tools.deny=["group:fs"]`），
  把交付逼回 `vericax-sh`。
- **cost 允许 null**：hermes 的 usage 写在容器内文件、openclaw 的 `--json` 信封落在
  stderr 且混有日志，harness 不读容器文件；spec/08 §5 允许 `null`，conformance 只要求
  三件套归因与分数。opencode 的 `step_finish.part.tokens` 可以正常提取。
- **conformance 记录用 `kind=test`**：三栈 n=1 全 1.0，但不进能力聚合；`runs/` 里的
  episode 不进 git。

## 16. 默认镜像切换(2026-11-22)

- **切换不是改 `snapshot` 名**,而是让同名 snapshot 解析到自建 qcow2。做法:把三张镜像
  `ln -s` 到一个 suite 目录,`vericax.toml [images] dir` 指过去;任务 JSON 的 `snapshot`
  不变。`VERICAX_IMAGE` 只是单文件逃生口,跨 snapshot 的 batch 必须用
  `--image SNAPSHOT=PATH`。
- **镜像变小后审计快很多**:自建镜像 1.5–2.3 GB,单题 `audit_task --repeat 10` +
  L0 + pack 约 170–300 s;26 题 parallel=2 约 75 分钟完成。旧的 11.7 GB EngiWorld
  镜像单题要 5–10 分钟。
- **wheelhouse 要覆盖依赖闭包,不是只放目标包**:scikit-fem 的 METADATA 依赖 scipy,
  trimesh 的 scipy 是**可选**依赖(pip 不会装),而两者的运行时路径都可能走到 scipy。
  自建 FEniCS 镜像不含 scipy,所以给 task-0014/0016 的 wheelhouse 补
  `scipy-1.13.1-cp312` 并在 INSTALL 里显式安装(0016 必须显式,因为 pip 不知道可选依赖)。
  排查方式:在 VM 里直接跑 gold 脚本并打印 stderr,不要只看 `FAILED to fetch`。
- **Ubuntu 24.04 的 PEP 668 不是这里的坑**:`pip install --user` 在自建镜像里可用;
  先别急着加 `--break-system-packages`,先确认缺的是哪个模块。
- **并发审计要按题分 cache**:`audit_task.py` 原来所有题共用一个
  `cache/audit`,parallel=2 时可能互踩;改成 `cache/audit/<task-id>`。
- **VM 偶发控制通道 reset 不是题的问题**:fenics-0002 在一次并行审计里
  `get_screenshot` 连续 90 s 失败,重跑单题即过(16/16)。批量审计要把这种失败
  与真正的包/依赖失败分开,单独重跑后再判定。
- **审计产物有非确定性字节**:FEniCS 的 `ground_truth/solution.h5` 每次重生成
  sha 会变(大小相同),所以 `resources.sha256`/`tree_version` 会变;pins 与
  summary 不变。发布结果必须带 `tree_version`,不能用旧树的结果比新树。

## 17. 验证器读不懂 agent 实际写出的合法 deck（2026-11-28）

- **症状**：两道新 CalculiX 题审计全过（31/31、25/25）、robust、L0 都过，第一轮校准里 18 份正确
  deck 有 14 份被判 0；回看已发布的 B2，CalculiX 和 software-selection 两族的 43 个 0 分里 34 个
  是同一类——agent 自己的求解输出等于参考值，被拒的原因是 deck 检查读不懂它用的写法。
- **写法**（CalculiX 2.21 都接受，题面都没有限定）：`*ELSET`/`*NSET` 的 `GENERATE` 形式
  （首、末、增量）；`*BOUNDARY` 行写节点集、省略默认值 0、省略等于首自由度的末自由度；集合定义在
  `*NODE, NSET=` 上；`*DLOAD` 直接写单元号；载荷除出来之后四舍五入到 8 位有效数字（验证器用
  1e-9 的**绝对**容差）；节点行只写两个坐标；用 `*DSLOAD` 施加面压力；数据行以逗号结尾再接关键字。
- **规则早就有，没有落地**：spec/02 §5 写了「等价写法必须都收」和 `equivalent_but_rejected`，
  但 15 个读 deck 的验证器没有一个实现它，也没有任何测试碰这些写法。审计里的「替代合法」用例是
  作者想出来的写法（逆序编号、拆 elset 卡），覆盖不到 agent 的写法。
- **修法：先规范化，再检查**。`scripts/deck_canonical.py` 的 `canonical_deck()` 把这些写法改写成
  验证器已经认识的形式（展开 `GENERATE`、补第三个坐标、节点集的边界行和载荷行展开成逐成员的行、
  续行逗号接上、关键字前的逗号去掉），每个读 deck 的验证器在 `inp_blocks()` 开头调用它，原有检查
  一行不动。这段代码在每个 `eval.py` 里有一份逐字拷贝（评分是带外的，verifier 是单文件），
  `tests/test_deck_spellings.py` 核对 15 份拷贝与源一致。
- **测试是机械改写，不靠想象力**：`scripts/deck_variants.py` 对每道题的 gold deck 做 7 种改写，
  `tests/test_deck_spellings.py` 要求每个验证器的 deck 检查都接受（加固前 63 处拒绝，之后 0），
  并要求规范化后的改写 deck 与规范化后的 gold 意义相同。每道题的审计多了一个「全部写法一起上」
  的替代合法用例（A3），所以镜像上的 ccx 也要接受这些写法并给出参考值。
- **验证**：把 B2 里被 deck 规则拒掉的 38 份冻结 deck 用加固后的验证器重放，38/38 通过 deck
  检查；B2 里得满分的 68 份 deck，68/68 仍然通过。
- **同一个教训的另外两面**：(1) `evaluator.stderr` 里的边界/载荷/集合类拒绝原因只是线索，
  读冻结的 deck、确认它确实违反题面之前，不能记成能力失败——B2 文档曾据此写下「不是验证器
  缺陷」。(2) 零分有四个来源：做错、太慢（用完活动时间预算，按 spec 记 0）、没收尾、被截断；
  T2 的四个 0 分 deck 全是对的。
- **顺带修掉的两处**：`scripts/calibration_report.py` 把用完时间预算的集算成 infra 并从均值里去掉，
  `scripts/capability_report.py` 两边都不计（spec/03 §2 规定记 0）；adapter profile 里同一个模型
  的输出上限各栈不同（dsh 声明 32768，openclaw 没声明、落到默认 8192；opencode 也没声明），
  现在三个 profile 声明相同，`tests/test_adapter_profiles.py` 逐模型核对。
- **新题怎么用**：deck 类验证器保留 `inp_blocks(text)`；`python3 scripts/inject_deck_canonical.py
  <task-id>` 把 `scripts/deck_canonical.py` 的内容放进两行标记之间，并让 `inp_blocks` 的第一句是
  `text = canonical_deck(text)`；在 `tests/test_deck_spellings.py` 的 `REGISTRY` 里登记这道题的
  deck 检查入口；审计里加一个「全部写法一起上」的替代合法用例。没有 `inp_blocks` 的验证器
  （自己解析 deck 的）直接进 `REGISTRY`，由同一个测试把关。
