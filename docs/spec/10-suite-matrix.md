# 10 · 任务族矩阵与规模目标

状态：**已评审通过 v0.1**（2026-11-18 人类评审通过）· D5 已定（2026-11-18）：v0/v0.5 沿用 EngiWorld 镜像；**2026-11-22 起套件默认改用三张自建镜像**（§3）；题量为 Phase 2 目标，不是承诺

## 0. 目标

1. **Phase 2 结束时 ≥2 个求解器 × 20–30 题**，每个 capability ≥3 题。
2. **题量服务于结论**：没有审计的题不加；不能支撑 capability 结论的题不加。
3. **Phase 1 不加新题**：先把 agent 契约/运行时闭环打通；现有 3 题只做回归。
4. **split 版本化**：任何对外结果必须能追溯到 split 版本 + n + 栈 + 模型 + 成本。
5. **与 spec/05 的关系**：spec/05 的 v0.5 100 题（5 求解器 × 20）是长期目标；本 spec 的 25 道目标题（+1 道 L6 原型）是 Phase 2 的可验收子集。Phase 2 先证明 2 求解器 × 25 题，v0.5 再扩到 5 × 20。

## 1. Capability 定义

本 spec 统一 capability 枚举为 6 类（spec/01 §4 的 `cross-software` 保留为 v1 的跨软件扩展，不并入 cross-stage-consistency）：

| capability | 检验重点 | 必需 verifier 层 | 现有 | Phase 2 目标 |
|---|---|---|---|---|
| `single-execution` | 一次求解/一次建模，工件正确 | L1–L3 | 0001/0004/0005/0006/0007 + FEniCS 0001 + cross-solver 0001（L6 原型） | 6 |
| `design-optimization` | 可行性门 + 质量分两段式 | L1–L5 | 0002 + FEniCS 0002/0003/0004/0005 | 5 |
| `cross-stage-consistency` | 多步骤/多工件在一套模型内自洽 | L1–L4 | 0003/0008/0009/0010 | 4 |
| `software-selection` | 选对工具并交付；verifier 能判工件来自哪个工具 | L1–L3 + L6 | — | 4 |
| `observation-reconstruct` | 从图纸/报告/截图重建模型 | L1–L3 | 0011/0012/0013 | 3 |
| `open-environment` | agent 自行安装/配置工具并交付 | L1–L3 | 0014/0015/0016 | 3 |
| 合计 | | | 22（21 道目标 + 1 道 L6 原型） | **25** |

> 规模下限：20 题（每 capability ≥3，且 ≥2 求解器）。25 是目标值；达不到 25 时优先保 capability 覆盖，不靠单类堆题。

## 2. 现有资产

| 任务 | capability | 求解器 | 实现层 | 审计 | split |
|---|---|---|---|---|---|
| `cae--cli--calculix--task-0001` | single-execution | CalculiX 2.21 | L1–L3 | 10/10 | `v0.1-cae-cli-pilot` |
| `cae--cli--calculix--task-0002` | design-optimization | CalculiX 2.21 | L1–L5 | 13/13 | `v0.1-cae-cli-pilot` |
| `cae--cli--calculix--task-0003` | cross-stage-consistency | CalculiX 2.21 | L1–L4 | 11/11 | `v0.1-cae-cli-pilot` |
| `cae--cli--fenics--task-0001` | single-execution | FEniCS 0.10.0.post2 | L1–L3 | 15/15 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0004` | single-execution | CalculiX 2.21 | L1–L3 | 14/14 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0005` | single-execution | CalculiX 2.21 | L1–L3 | 13/13 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0006` | single-execution | CalculiX 2.21 | L1–L3 | 13/13 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0002` | design-optimization | FEniCS 0.10.0.post2 | L1–L5 | 16/16 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0003` | design-optimization | FEniCS 0.10.0.post2 | L1–L5 | 16/16 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0007` | single-execution | CalculiX 2.21 | L1–L3 | 14/14 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0008` | cross-stage-consistency | CalculiX 2.21 | L1–L4 | 15/15 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0009` | cross-stage-consistency | CalculiX 2.21 | L1–L4 | 13/13 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0004` | design-optimization | FEniCS 0.10.0.post2 | L1–L5 | 15/15 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0005` | design-optimization | FEniCS 0.10.0.post2 | L1–L5 | 15/15 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0010` | cross-stage-consistency | CalculiX 2.21 | L1–L4 | 14/14 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0011` | observation-reconstruct | CalculiX 2.21 | L1–L3 | 14/14 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0012` | observation-reconstruct | CalculiX 2.21 | L1–L3 | 13/13 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0013` | observation-reconstruct | FEniCS 0.10.0.post2 | L1–L3 | 15/15 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0014` | open-environment | FEniCS 0.10.0.post2 | L1–L3 | 12/12 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0015` | open-environment | FEniCS 0.10.0.post2 | L1–L3 | 13/13 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0016` | open-environment | FEniCS 0.10.0.post2 | L1–L3 | 11/11 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0013` | cross-stage-consistency | CalculiX 2.21 | L1–L5 | 35/35 | `v0.2-cae-cli-25` |
| `cae--cli--calculix--task-0014` | cross-stage-consistency | CalculiX 2.21 | L1–L5 | 27/27 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0017` | cross-stage-consistency | FEniCS 0.10.0.post2 | L1–L4 | 20/20 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0019` | observation-reconstruct | FEniCS 0.10.0.post2 | L1–L3 | 27/27 | `v0.2-cae-cli-25` |
| `cae--cli--fenics--task-0020` | design-optimization | FEniCS 0.10.0.post2 | L1–L5 | 22/22 | `v0.2-cae-cli-25` |
| `cae--cli--cross-solver--task-0001` | single-execution (L6 prototype) | CalculiX 2.21 | L1–L3 + L6 | 15/15 | `v0.2-cae-cli-l6-pilot` |
| `cae--cli--cross-solver--task-0002` | software-selection | CalculiX（*Buckle）| L1–L3 + L6 | 15/15 | `v0.2-cae-cli-merged` |
| `cae--cli--cross-solver--task-0003` | software-selection | FEniCS（异质模量）| L1–L3 + L6 | 15/15 | `v0.2-cae-cli-merged` |
| `cae--cli--cross-solver--task-0004` | software-selection | FEniCS（平流-扩散）| L1–L3 + L6 | 15/15 | `v0.2-cae-cli-merged` |
| `cae--cli--cross-solver--task-0005` | software-selection | CalculiX（*Frequency）| L1–L3 + L6 | 15/15 | `v0.2-cae-cli-merged` |

2026-11-21（P0 重审计 + P1 试点 + P1 第二批 + P1 完成 + P3c）后计数如上；`v0.1-cae-cli-pilot` 保留 3 题，
`v0.2-cae-cli-25` 随 P1 增长，`v0.2-cae-cli-merged` 为 P3c merged image 专用 split（4 题）。审计记录以各任务包的
`ground_truth/audit.md` 为准（robust 10/10）。

**任务包计数（2026-11-22 校准）**：表内共 **26 个任务包** = 25 道 Phase 2 目标（6/5/4/4/3/3）+ 1 道
`cross-solver task-0001` L6 原型（capability 如实记为 `single-execution`）。split 文件合计 26 个唯一 id；
`v0.2-cae-cli-25` 的名字是冻结的 split 版本号，不因多出的原型题改名。

**2026-11-28/29（T1/T2 校准题入库）**：新增 5 题——多步 CalculiX deck 两道（0013 三个静力步、
0014 频率–静力–屈曲）、更难的 FEniCS 三道（0017 热弹两阶段、0019 双孔板读图重建、0020 椭圆孔双工况优化）。
各 capability 现有题数：`cross-stage-consistency` 4 → 7，`observation-reconstruct` 3 → 4，
`design-optimization` 5 → 6。`v0.2-cae-cli-25` 18 → 23 题，任务包 26 → 31（30 道 Phase 2 目标 + 1 道
L6 原型）；split 版本号不变（按 `splits/README.md` 的流程追加 id）。三栈 × n=3 的校准
（`--kind test`，不作为能力结果发布）：dsh 与 opencode-bailian 在五道题交付的工件上没有可靠差别；
见各题提交说明。同日 15 个读 deck 的 verifier 加了规范化拷贝（lessons §17），它们的 `tree_version` 都变了。

## 3. 求解器矩阵

| 求解器 | 版本/镜像 | 状态 | Phase 2 题量 | 备注 |
|---|---|---|---|---|
| **CalculiX** | 2.21 / `CalculiX-2.21.qcow2` | 已验证（12 题） | 12 | P1 完成 12 题 |
| **FEniCS** | 0.10.0.post2 / `FEniCS.qcow2` | **已验证（9 题）** | 9 | 第二求解器；P1 完成 9 题（DO/observation/open-environment） |
| **cross-solver** | 2.21 + 0.10.0.post2 / `VeriCAx-merged.qcow2`（P3c 自建，2026-11-27 重建，sha `98bf5ce7…ec33`） | **已验证（4 题 + 原型）** | 4 | `software-selection` 专用；L6 判据见 spec/02 §1；merged image 2026-11-21 验收（calculix/fenics/cross-solver 三家族 L0 + 4 题全管线） |

D5 已定（2026-11-18），执行顺序：

- **v0/v0.5：复用 EngiWorld 镜像**（CalculiX-2.21 已验证；FEniCS 候选镜像需确认版本、工件格式、pins 与审计可复现）。
- **Phase 1：写自建镜像构建 recipe**，并产出一张自建镜像验证可复现（不切换）。
- **Phase 2：切换自建 VeriCAx 镜像**并重跑审计；所有 pins 必须在同镜像内重新烘焙（换镜像 = 重跑审计，spec/04 §6）。三张自建镜像已全部验收（P3a CalculiX 2026-11-20、P3b FEniCS 2026-11-21、P3c merged 2026-11-21）；merged 镜像承载 4 道 `software-selection`（`v0.2-cae-cli-merged`）。
- **默认镜像切换已完成（2026-11-22）**：26 个任务包全部在自建镜像上重跑 `audit_task.py --repeat 10` + L0 + `pack_task`；L0 的 `image_sha256` 与 snapshot 一一对应——CalculiX `91b1d6c8…`（13 包）、FEniCS `b0e2f239…`（9 包）、merged `e6514410…`（4 包）。task-0014/0016 的本地 wheelhouse 补了 `scipy 1.13.1`（scikit-fem/trimesh 的运行时依赖，自建镜像不含 scipy）。`vericax.toml` 的 `[images] dir` 现在指向三张镜像的 suite 链接目录；EngiWorld 镜像保留作对照。

- **镜像重建（2026-11-27，v0.2.3-alpha）**：三张自建镜像的 grub 配置追加 `clearcpuid=519`，对 guest 内核隐藏 CPU 的影子栈特性——否则 guest 的 PID 1 会因影子栈缺页死亡、内核 panic（`docs/lessons-2026-11-27-sandbox-loss.md`）。干净重建后记录的包版本与此前逐项相同；26 个包再次全部重跑 `audit_task.py --repeat 10` + L0 + `pack_task`，L0 的 `image_sha256` 更新为CalculiX `822915ce…`（13 包）、FEniCS `ff6d3b5e…`（9 包）、merged `98bf5ce7…`（4 包）。

无论哪条路径，**换镜像 = 重跑审计**；pinned 参考值与镜像绑定（spec/04 §6）。

### 3.1 现状（2026-11-22 更新）

- FEniCS 镜像已通过 ModelScope 通道获取（`engiworld.prepare_images --source modelscope --image FEniCS`，65 s；`FEniCS.qcow2` 17.0 GB，sha256 与 manifest 一致），dolfinx 0.10.0.post2。
- 第二求解器 smoke **已完成**：`cae--cli--fenics--task-0001`（带孔板，L1–L3）P0 重审计 15/15、L0 参考自检 pass、假 agent tier-1 = 1.0——L1–L3 的验证逻辑与求解器无关得到实证。
- **P1 已完成（2026-11-20/21）**：21 题；P2 L6 spike 完成（+1 道 prototype）；P3a/P3b/P3c 三张自建镜像验收；**Phase 2 套件目标 25 题已达成**（2026-11-21，4 道 `software-selection` 落地；任务包共 26 个）。P4/P5 已于 2026-11-22 完成；E 已随公开仓库解除（见 `docs/ci.md`）。三栈 n≥3 能力跑 B2 于 2026-11-24 完成并发布（`docs/results/2026-11-24-b2.md`）。

## 4. 题量分解

| capability | CalculiX | FEniCS | cross-solver | 合计 |
|---|---|---|---|---|
| single-execution | 5 | 1 | 1 | 7 |
| design-optimization | 1 | 4 | 0 | 5 |
| cross-stage-consistency | 4 | 0 | 0 | 4 |
| software-selection | 0 | 0 | 4 | 4 |
| observation-reconstruct | 2 | 1 | 0 | 3 |
| open-environment | 0 | 3 | 0 | 3 |
| **合计** | **12** | **9** | **5** | **26** |

当前 **26 个任务包已落地**（25 道 Phase 2 目标 + 1 道 L6 原型；每 capability ≥3），全部跑自建镜像：
13 个 CalculiX、9 个 FEniCS、4 个 merged；从 Phase 1 的 3 题算起新增 23 个，已全部过 P0 门并在
2026-11-22 于自建镜像上重审计。

## 5. Split 纪律

| split | 内容 | 时点 |
|---|---|---|
| `v0.1-cae-cli-pilot` | 0001–0003 | Phase 1 回归 |
| `v0.2-cae-cli-25` | 18 题（自建 CalculiX/FEniCS 镜像） | Phase 2 末冻结 |
| `v0.2-cae-cli-merged` | 4 题 `software-selection`（merged 镜像） | Phase 2 末冻结 |

规则：

- 每个 split 是 `splits/<version>.txt`，一行一个 task id。
- **永不原地修改**已发布的 split；修订生成新版本号。
- 任何对外结果必须同时声明：split 版本、n、栈（agent/harness/model）、成本口径。
- 同一 task 的题面/verifier 变更 → 新 id + `id-migration-<date>.json`；新旧结果不可直接合并（spec/01 §3）。

## 6. 任务设计规则

- **一题一 capability**：不要在单题里混测"会不会选工具"和"会不会优化"。
- **原创**：结构可借鉴 EngiWorld，题面不得照抄。
- **层声明**：`eval.py` 顶部 `IMPLEMENTS` 必须与实际实现一致；L1/L2 强制。
- **审计**：正例 ≥1、替代合法路径 ≥2、负例 ≥6、稳健 10 次；`audit.md` 无 `MISS` 才可入 split（spec/02 §4）。
- **工件可重开**：verifier 必须用原生 API/格式解析器重开，不读 agent 自述。
- **求解器版本固定**：task JSON 的 `snapshot` 指向明确镜像；结果记录 `image_sha256`。
- **无 split 不发布**：task JSON 的 `splits` 不得为空。
- **GT 自校验**：GT deck 必须复现 GT summary；base 模板与 GT deck 的单元类型/面编号/输出请求一致；任务书必须写明 verifier 会检查的设置，不得有隐藏变更（spec/02 L0）。
- **禁止字面量 verifier**：`valid_input` 只做数学校验；summary 解析容忍表头/空行；等价写法必须都收（spec/02 §5）。

## 7. Phase 2 执行顺序

1. **第二求解器 smoke**：FEniCS 上做 1 道 `single-execution`，证明 L1–L3 与求解器无关。
2. **铺量**：两求解器的 `single-execution` + `design-optimization` 补齐。
3. **software-selection**：4 道 cross-solver 题；先解决 provenance 判据（如何证明工件来自指定工具），再写题。
4. **observation-reconstruct**：3 道；引入图纸/报告类 init_file，验证"输入不是完整 deck"时的重建能力。
5. **open-environment**：3 道；需要按任务放开包源/网络策略，默认仍是 sandbox 无外网。
6. **冻结 split + suite 报告**：25 题（或 20 题下限）全部审计通过后冻结，split 名随最终题量。

顺序理由：每一步引入一种新的验证挑战（求解器无关 → provenance → 输入重建 → 环境开放），不要混在一起，否则失败无法归因。

### 7.1 执行排期（2026-11-20 拍板）

铺题之前先补审计债（现在 4 题，补债最便宜；放大到 25 题会按倍数复制）：

| 优先级 | 动作 | 验收 | 估算 |
|---|---|---|---|
| **P0** | 审计协议可执行化（spec/02 §4.1）：`--repeat 10`、`NEGATIVE_KINDS` 六类、pack 打包门；给现有 4 题补第二条替代路径与缺失负例并重审计 | 4 题 audit.md 显示 A≥2、六类负例、robust 10/10；pack 通过 | 1–1.5 人日 |
| **P1** | 铺量：先 CalculiX +6、FEniCS +5（到 15 题），再补 design-optimization 到 20 题下限 | 每题过 P0 同款门；split `v0.2-cae-cli-25` 随题增长 | **已完成 2026-11-20：21 题**（含每 capability ≥3） |
| **P2** | cross-solver provenance 判据 spike（写入 spec/02）+ 沙箱形态决策（合并镜像 vs 多 VM） | 判据可复现地判"工件来自指定工具"；1 道原型题 | 2–3 人日 |
| **P3** | 自建镜像 recipe（D5 未完成项），可与 P1 并行；顺带产出 cross-solver 合并镜像 | 构建可复现 + 一张验证镜像；pins 在同镜像重烘 | 3–5 人日 |
| **P4** | 2-VM 并行调度（soak 已过；全矩阵前做） | 两 episode 并行跑通、互不串扰 | **已完成 2026-11-22**（`batch --parallel 2`；另含每 episode challenge token 管道） |
| **P5** | 栈扩展 opencode/hermes/openclaw（每栈 adapter + conformance） | n=1 conformance 过 | **已完成 2026-11-22**（三栈各 n=1 = 1.0） |

**本轮拍板（2026-11-20）**：

- **P1 试点制**：先写 5 题（FEniCS `design-optimization` ×2、CalculiX `single-execution` ×3），过同一打包门后再续下一批。
- **cross-solver 纳入 Phase 2**，但先做 P2 provenance spike；判据不能可复现地判"工件来自指定工具"时，`software-selection` 回落到 v0.5。
- **D5 自建镜像（P3）与 P1 并行**：越晚换镜像，越多题要重烘 pins、重跑审计。
- **verifier 软约束放宽到 ≤450 行**（spec/02 §5）；`cross-solver/task-0005` 454 行是已记录的例外。 2026-11-28 起读 deck 的 15 个 verifier 各带一份约 160 行的规范化拷贝，行数 470–614，拷贝不计入（spec/02 §5 的例外）。

**P2 状态（2026-11-20，P3c 后更新）**：L6 判据已写入 spec/02 §1/§2/§6，task schema 增加 `provenance` 块（spec/01，P3c 四题已填写）。原型 `cae--cli--cross-solver--task-0001` 审计 15/15、robust 10/10、L0 pass、fake smoke 1.0；`capability` 如实写 `single-execution`。**真正的 `software-selection` 已于 P3c 验证**：cross-solver task-0002…0005 在 merged image 上完成 L1–L3+L6 全管线（各 audit 15/15、robust 10/10、L0、fake smoke 1.0）。

**P3 状态（2026-11-21）**：三张自建镜像全部 clean-build 验收——P3a CalculiX 2.21（`91b1d6c8…47cd`）、P3b FEniCS 0.10.0.post2（`b0e2f239…ebc4`，PPA 0.10 绑定包已删、按固定上游 tag 重建）、P3c merged（`e6514410…a262`，双求解器，三家族 L0 全过）。**默认镜像切换已于 2026-11-22 完成**：26 个任务包在自建镜像上重跑完整审计并刷新 L0/pins（见 §3）。

**open-environment 的 v0.2 形态（2026-11-20）**：最小实现是**本地 wheelhouse**——`init_file/wheels/` 提供工具轮子（scikit-fem、pygmsh），agent 在无外网的 sandbox 里自行创建/配置环境并安装；互联网/包源按任务放开留 v0.5。该形态用于 0014/0015，任务 JSON 的 `integrity_policy` 允许相应第三方包。

**P1 完成（2026-11-20）**：21 题（single 6 / design 5 / cross-stage 4 / observation 3 / open-environment 3），满足 20 题下限与每 capability ≥3。

**Phase 2 套件完成（2026-11-21）**：25 道目标题（在 P1 基础上 +4 `software-selection`），capability 矩阵 6/5/4/4/3/3；
连同 L6 原型共 26 个任务包。

**P4 完成（2026-11-22）**：`vericax batch --parallel 2` 两 episode 并行（各 1.0，wall 423s）；E5 顺序改为 freeze → 关 sandbox → scoring；L6 每 episode challenge token 管道落地（动态 token 1.0 / audit-token 重放 0.0），5 道 L6 任务 L0 重跑通过。详见 spec/09 §11。

**P5 完成（2026-11-22）**：`opencode 1.19.5` / `hermes 0.21.6` / `openclaw 2026.9.9` 三栈 adapter + `vericax-agent:phase2` 镜像；task-0001 × n=1 全部 1.0（native evaluator，sandbox/scoring 网络隔离均 true，三件套归因完整）。Hermes/OpenClaw 的 cost 为 `null`（usage 在容器内文件/混合 stderr，harness 不读；spec/08 §5 允许）。详见 `tests/conformance_adapters.py` 与 spec/08 §10。

**E（CI）**：GitHub Actions 曾在账户级阻塞；已加 `scripts/ci_local.sh`（CI 三步 + offline tests）与 pre-push 门。仓库 2026-11-22 公开后标准 runner 正常，`main`/`develop` 均为绿；详见 `docs/ci.md`。

**待决**：无（E 已解除；B3 五栈矩阵为可选，见 spec/11）。

**P0 已完成（2026-11-20）**：4 题全部 A≥2、六类反作弊负例齐全、`robust: 10/10 consistent`；`audit_task.py --repeat N` 与 `pack_task.py` 打包门已生效（spec/02 §4.1）。

## 8. 验收与报告

**单题验收：**

- `audit.md` 无 `MISS`。
- `resources.sha256` 匹配。
- gold case 的 tier-1 评分与 tier-0 审计结论一致（Phase 1 回归）。

**Suite 验收（Phase 2 出口）：**

- ≥2 求解器、20–30 题、每 capability ≥3。
- **benchmark-validity gate**：每个任务包通过 GT 自校验；模型比较必须在同一 `tree_version` 上；n≥3；re-score 不得当 rerun 发布（spec/02 L0、spec/03 §1）。
- 成绩矩阵：capability × solver，每格给出 n、均值、极差。
- 报告字段：split 版本、n、agent/harness/model、`image_sha256`、`$/题`（订阅制网关用 token/题）、活跃时长中位、错误分类占比。
- 通道分数不合并：CLI 与 GUI 分开；跨软件与单软件分开报。

可执行协议、分批计划（B0–B3）、go/no-go 门与报告字段见
[`spec/11-capability-runs.md`](11-capability-runs.md)。

## 9. 依赖与未决

| 项 | 依赖 | 影响 |
|---|---|---|
| 第二求解器镜像 | D5 | P3a/P3b/P3c 自建镜像已验证；默认镜像切换 2026-11-22 完成（26 包重审计 + L0） |
| 发布时点 | D4 | 已公开（2026-11-22）；商标轻量查重完成、不注册；org 迁移延后 |
| 任务作者产能 | 人力 | Phase 2 完成 25 道目标题 + 1 道 L6 原型（每 capability ≥3）；v0.5 扩到 5 求解器 × 20 待 P5 |
| provenance 判据 | 新 verifier 能力 | L6 已写入 spec/02；原型 + P3c 四题在 merged image 上验证（native 对、token 绑定、全场重解比对） |
| 图纸/报告输入格式 | task schema | `observation-reconstruct` 的 init_file 类型 |
| open-environment 网络策略 | spec/09 | 默认 sandbox 无外网；按任务开包源 |
| benchmark 修复 / tree 版本 | 审计 | 未修复题会把 benchmark 缺陷误读为能力差异；EngiWorld 2/20→8/20 主要是 repair |
| GUI 通道 | v1.5 | 不在 Phase 2 矩阵内 |
| cross-software | v1 | 独立于本表的 6 类；届时新增 capability |

## 10. 明确不做

- 在 Phase 1 加第 4 道题（agent 契约未闭环前，加题不产生结论）。
- 用单次 run 给 capability 下结论（n≥3 起步）。
- 把不同求解器/通道的分数合成一个总分。
- 把未审计的题放进 split。
- 为了凑 25 题而重复同质题；宁可 20 题保覆盖。