# 10 · 任务族矩阵与规模目标

状态：**已评审通过 v0.1**（2026-11-18 人类评审通过）· D5 已定（2026-11-18）：v0/v0.5 沿用 EngiWorld 镜像；题量为 Phase 2 目标，不是承诺

## 0. 目标

1. **Phase 2 结束时 ≥2 个求解器 × 20–30 题**，每个 capability ≥3 题。
2. **题量服务于结论**：没有审计的题不加；不能支撑 capability 结论的题不加。
3. **Phase 1 不加新题**：先把 agent 契约/运行时闭环打通；现有 3 题只做回归。
4. **split 版本化**：任何对外结果必须能追溯到 split 版本 + n + 栈 + 模型 + 成本。
5. **与 spec/05 的关系**：spec/05 的 v0.5 100 题（5 求解器 × 20）是长期目标；本 spec 的 25 题是 Phase 2 的可验收子集。Phase 2 先证明 2 求解器 × 25 题，v0.5 再扩到 5 × 20。

## 1. Capability 定义

本 spec 统一 capability 枚举为 6 类（spec/01 §4 的 `cross-software` 保留为 v1 的跨软件扩展，不并入 cross-stage-consistency）：

| capability | 检验重点 | 必需 verifier 层 | 现有 | Phase 2 目标 |
|---|---|---|---|---|
| `single-execution` | 一次求解/一次建模，工件正确 | L1–L3 | 0001 | 6 |
| `design-optimization` | 可行性门 + 质量分两段式 | L1–L5 | 0002 | 5 |
| `cross-stage-consistency` | 多步骤/多工件在一套模型内自洽 | L1–L4 | 0003 | 4 |
| `software-selection` | 选对工具并交付；verifier 能判工件来自哪个工具 | L1–L3 + provenance | — | 4 |
| `observation-reconstruct` | 从图纸/报告/截图重建模型 | L1–L3 | — | 3 |
| `open-environment` | agent 自行安装/配置工具并交付 | L1–L3 | — | 3 |
| 合计 | | | 3 | **25** |

> 规模下限：20 题（每 capability ≥3，且 ≥2 求解器）。25 是目标值；达不到 25 时优先保 capability 覆盖，不靠单类堆题。

## 2. 现有资产

| 任务 | capability | 求解器 | 实现层 | 审计 | split |
|---|---|---|---|---|---|
| `cae--cli--calculix--task-0001` | single-execution | CalculiX 2.21 | L1–L3 | 7/7 | `[]`（待填） |
| `cae--cli--calculix--task-0002` | design-optimization | CalculiX 2.21 | L1–L5 | 9/9 | `[]`（待填） |
| `cae--cli--calculix--task-0003` | cross-stage-consistency | CalculiX 2.21 | L1–L4 | 8/8 | `[]`（待填） |

Phase 1 的动作：

- 把 0001–0003 归入 `splits/v0.1-cae-cli-pilot.txt`；task JSON 的 `splits` 从 `[]` 改为 `["v0.1-cae-cli-pilot"]`。
- 因为 task JSON 变了，重跑 `pack_task.py` 更新 `resources.sha256`。
- 这是**未发布任务**的元数据整理，不改变题面/verifier；不触发新 id。

## 3. 求解器矩阵

| 求解器 | 版本/镜像 | 状态 | Phase 2 题量 | 备注 |
|---|---|---|---|---|
| **CalculiX** | 2.21 / `CalculiX-2.21.qcow2` | 已验证（3 题） | 14 | 现有 3 题 + 11 新题 |
| **FEniCS** | 0.10.0.post2 / `FEniCS.qcow2` | **已验证（1 题）** | 7 | 第二求解器；`cae--cli--fenics--task-0001` 审计 12/12、L0 通过、假 agent tier-1 = 1.0 |
| **cross-solver** | 两个镜像 | 新能力 | 4 | `software-selection` 专用；verifier 需 provenance 判据 |

D5 已定（2026-11-18），执行顺序：

- **v0/v0.5：复用 EngiWorld 镜像**（CalculiX-2.21 已在本机验证；FEniCS 候选镜像需确认版本、工件格式、pins 与审计可复现）。
- **Phase 1：写自建镜像构建 recipe**，并产出一张自建镜像验证可复现（不切换）。
- **Phase 2：切换自建 VeriCAx 镜像**并重跑审计；所有 pins 必须在同镜像内重新烘焙（换镜像 = 重跑审计，spec/04 §6）。

无论哪条路径，**换镜像 = 重跑审计**；pinned 参考值与镜像绑定（spec/04 §6）。

### 3.1 现状（2026-11-19 更新）

- FEniCS 镜像已通过 ModelScope 通道获取（`engiworld.prepare_images --source modelscope --image FEniCS`，65 s；`FEniCS.qcow2` 17.0 GB，sha256 与 manifest 一致），dolfinx 0.10.0.post2。
- 第二求解器 smoke **已完成**：`cae--cli--fenics--task-0001`（带孔板，L1–L3）审计 12/12 全过、L0 参考自检 pass、假 agent tier-1 = 1.0——L1–L3 的验证逻辑与求解器无关得到实证。
- 剩余 Phase 2 工作：题量（本 solver 再 +6）、cross-solver provenance 判据、自建镜像 recipe（D5 未完成项）。

## 4. 题量分解

| capability | CalculiX | FEniCS | cross-solver | 合计 |
|---|---|---|---|---|
| single-execution | 4 | 2 | 0 | 6 |
| design-optimization | 3 | 2 | 0 | 5 |
| cross-stage-consistency | 3 | 1 | 0 | 4 |
| software-selection | 0 | 0 | 4 | 4 |
| observation-reconstruct | 2 | 1 | 0 | 3 |
| open-environment | 2 | 1 | 0 | 3 |
| **合计** | **14**（含现有 3） | **7** | **4** | **25** |

新增题数：25 − 3 = **22**。按 0.5–1 人日/题（含审计）估算，约 **11–22 人日**；单作者 2–3 周偏紧，建议两人并行或先做到 20 题下限。

## 5. Split 纪律

| split | 内容 | 时点 |
|---|---|---|
| `v0.1-cae-cli-pilot` | 0001–0003 | Phase 1 回归 |
| `v0.2-cae-cli-25` | Phase 2 的 25 题；若按下限 20 题，则为 `v0.2-cae-cli-20` | Phase 2 末冻结 |

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
| **P1** | 铺量：先 CalculiX +6、FEniCS +5（到 15 题），再补 design-optimization 到 20 题下限 | 每题过 P0 同款门；split `v0.2-cae-cli-25` 随题增长 | 5–8 人日 |
| **P2** | cross-solver provenance 判据 spike（写入 spec/02）+ 沙箱形态决策（合并镜像 vs 多 VM） | 判据可复现地判"工件来自指定工具"；1 道原型题 | 2–3 人日 |
| **P3** | 自建镜像 recipe（D5 未完成项），可与 P1 并行；顺带产出 cross-solver 合并镜像 | 构建可复现 + 一张验证镜像；pins 在同镜像重烘 | 3–5 人日 |
| **P4** | 2-VM 并行调度（soak 已过；全矩阵前做） | 两 episode 并行跑通、互不串扰 | 1–2 人日 |
| **P5** | 栈扩展 opencode/hermes/openclaw（每栈 adapter + conformance） | n=1 conformance 过 | 每栈 0.5–1 人日 |

**待决**：cross-solver 是否纳入 Phase 2（依赖 P2/P3 结论）；D5 自建镜像时点（建议与 P1 并行）。

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
- 报告字段：split 版本、n、agent/harness/model、`image_sha256`、$/题、活跃时长中位、错误分类占比。
- 通道分数不合并：CLI 与 GUI 分开；跨软件与单软件分开报。

## 9. 依赖与未决

| 项 | 依赖 | 影响 |
|---|---|---|
| 第二求解器镜像 | D5 | Phase 2 能否按 25 题排期 |
| 发布时点 | D4 | 商标检索、org 占位、split 冻结时间 |
| 任务作者产能 | 人力 | 22 新题 = 11–22 人日；决定 20 还是 25 |
| provenance 判据 | 新 verifier 能力 | `software-selection` 4 题的前置；可能需要在 spec/02 增补一层 |
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