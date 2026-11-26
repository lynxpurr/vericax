# 11 · Capability 跑批协议（n≥3）

状态：草案（2026-11-22）。每次跑批前需要 owner 逐批放行；本文只定义协议与批次，
不代表任何批次已获授权。

## 1. 目的

把 capability episode 组织成**可发布**的结果：在同一 `tree_version` 上，每个
（任务 × agent 栈）至少 n=3 次成功评分，按 **capability × solver × 栈**报告
n、均值、极差、成本、活跃时长和错误分类。本文补全 spec/10 §8 的可执行部分。

**状态（2026-11-24）**：B0（27 episodes）、B1（54）、B2（198）均已完成并通过
G1–G3；B2 结果已发布（`docs/results/2026-11-24-b2.md`）。B3（五栈）未启动；
`pi`/`hermes` 需要各自的 Bailian provider 配置。

**后续（2026-11-26）**：B3 暂缓，前置条件是 pi/hermes 的 Bailian provider 与
usage 解析；可靠性/成本改进与难度校准见 spec/05 的下一阶段计划。新题校准仍按
本文的 n=3 协议与报告契约执行。

## 2. 术语

- **episode**：一次完整 run（prepare → run → freeze → score → record），落在
  `runs/ep-*/`，以 `summary.json` 为准。
- **cell**：`capability × solver × agent 栈 × model × tree_version` 的聚合单元。
- **n**：同一 task 在同一 cell 内**成功评分**的次数；`scoring_basis=infra` 不计入。
- **batch**：一次受控的 episode 集合，固定 tasks / stacks / n / 预算。
- **solver**：任务 JSON 的 `snapshot`（CalculiX-2.21 / FEniCS / VeriCAx-merged）。
- **tree_version**：任务包内容指纹（spec/03）；不同 tree 的结果不可合并。

## 3. 规范

1. **标签**：能力跑使用 `--kind capability` 与 `--run-mode rerun`；`test`/`debug`
   不进能力均值（`vericax report` 默认排除）。
2. **固定**：batch 内 split、每个 snapshot 的镜像不得变化。`tree_version` 是**每题
   manifest 的指纹**：同一 task 的所有 episode 必须共享该 task 的 tree_version；
   不同 task 之间 tree_version 天然不同，不构成混树。同一 task 内混树视为无效。
3. **n≥3**：每（task × stack）至少 3 次成功评分；报告必须写 n。任何 n<3 的 cell
   不得进入发布表。
4. **infra 失败**：不计分；同一（task, run_index）最多重试 2 次，使用新 episode；
   报告记录重试次数与 infra 率。batch 内 infra 率 >10% 时暂停并诊断。
   `vericax batch` 自 2026-11-26 起自动执行该重试：首轮跑完后统一重试，连续 3 次 infra
   熔断；每个 attempt 都进 `batch.json`（`attempt`、`infra_attempts`、`infra_rate`、
   `retried_jobs`），报告 infra 率时失败的重试也要计入。
5. **成本**：只有 `cost.usd_estimate` 全部可用时才聚合 $/题；订阅制网关（如 Bailian
   Token Plan）没有 USD 单价时，报告 **token/题** 并写 `$/题 n/a`，不得静默按价目表
   估算。token 计数始终记录。
6. **时长**：报告 `active_time_seconds` 中位数，并注明覆盖率。
7. **错误分类**：按栈汇总 `error_category` 占比。
8. **发布**：原始 `runs/` 不入库；聚合表写入 `docs/results/<date>-<batch>.md`。
   结果必须声明 split、n、栈版本、model、tree_version、image sha256、成本口径。
9. **不得**把 re-score 当 rerun 发布；不得合并 CLI/GUI 或单软件/跨软件分数。
10. **放行**：每个 batch 执行前由 owner 明确授权；batch 之间按 §6 的 go/no-go 门。

## 4. 分批计划

栈的选择：B0–B2 使用 `dsh`、`opencode-bailian`、`openclaw-bailian`（同一个
Bailian Token Plan 网关；dsh/opencode 的 cost 可读，openclaw 为 `null`，结果表标
`n/a`）。`pi` 与 `hermes` 需要各自的 Bailian provider 配置，暂不进入 B0–B2；
B3 可在补齐配置与 usage 解析后加入。openclaw 的 usage 信封解析已于 2026-11-26 修复
（`_extract_cost` 能定位 stderr 日志行之后的缩进 JSON 信封），此后的批次可读；
B2 结果表里的 `n/a` 是修复前的记录，可用本地 episode 离线重算后补上。

| batch | 范围 | 栈 | n | episode 数 | 目的 | 估算 |
|---|---|---|---|---|---|---|
| **B0 harness smoke** | calculix-0001 / 0002 / 0003 | 3 | 3 | **27** | 验证 batch 管线、成本提取、方差与聚合工具 | 0.5–2 h |
| **B1 capability breadth** | 六题各覆盖一个 capability（见 §5） | 3 | 3 | **54** | 跨三张镜像、六类能力、merged + L6 | 1–3 h |
| **B2 leaderboard v1** | `v0.2-cae-cli-25`（18）+ `v0.2-cae-cli-merged`（4） | 3 | 3 | **198** | 可发布的能力矩阵 | 5–15 h |
| **B3 full matrix**（可选） | 22 题 | 5 | 3 | **330** | 五栈完整对比 | 15–30 h |

估算只用于排期；**B0 实测的 $/题与 wall/episode 是 B1/B2 预算的唯一依据**。

## 5. 题集

**B0（同一镜像，先排管线）**

| task | capability | solver |
|---|---|---|
| `cae--cli--calculix--task-0001` | single-execution | CalculiX-2.21 |
| `cae--cli--calculix--task-0002` | design-optimization | CalculiX-2.21 |
| `cae--cli--calculix--task-0003` | cross-stage-consistency | CalculiX-2.21 |

覆盖 `exact_match` 与 `quantified_score` 两种评测器，且不跨镜像。

**B1（六类能力各一题，跨三张镜像）**

| task | capability | solver |
|---|---|---|
| `cae--cli--calculix--task-0001` | single-execution | CalculiX-2.21 |
| `cae--cli--calculix--task-0002` | design-optimization | CalculiX-2.21 |
| `cae--cli--calculix--task-0003` | cross-stage-consistency | CalculiX-2.21 |
| `cae--cli--fenics--task-0013` | observation-reconstruct | FEniCS |
| `cae--cli--fenics--task-0014` | open-environment | FEniCS（wheelhouse） |
| `cae--cli--cross-solver--task-0002` | software-selection | VeriCAx-merged（L6） |

**B2** 使用冻结 split，不选题：
`v0.2-cae-cli-25`（18 题）+ `v0.2-cae-cli-merged`（4 题）。
**B3** 为 B2 的 22 题 × 五栈。

## 6. 门（go/no-go）

| 门 | 时点 | 通过条件 |
|---|---|---|
| **G0** | B0 前 | agent 镜像存在；`DEEPSEEK_API_KEY` 已注入（不落盘）；三张镜像可解析；磁盘 ≥20 GB；`capability_report.py` 离线测试通过 |
| **G1** | B0 后 | 27 episodes 中每个 task 内部 tree 一致；native 评分 ≥90%；infra ≤10%；聚合表可生成；实测 $/题与 wall/episode 已记录 |
| **G2** | B1 后 | 六类 capability 均达到 n=3；三张镜像均跑通（含 merged + L6）；方差与成本已知；决定 B2 范围/预算 |
| **G3** | B2 后 | 每个 cell n=3；报告字段齐全（spec/10 §8）；owner 复核后才可发布 |
| **G4** | B3 前 | 明确需要五栈对比；hermes/openclaw 的 cost 处理方式已定（补解析或标 n/a） |

**停止条件**：batch 内 infra 率 >10%、adapter 系统性失败、tree 漂移、实测成本/时长
超过估算 2×、或任务/verifier 在 batch 中变更 → 暂停并重新评估。

## 7. 执行

前置：`vericax.toml [images] dir` 指向三张镜像的 suite 目录；否则 batch 跨 snapshot
时必须用 `--image SNAPSHOT=PATH`，且不得设置 `VERICAX_IMAGE`。

B0（每个栈一次）：

```bash
DEEPSEEK_API_KEY=... bin/vericax batch \
  --task cae--cli--calculix--task-0001 \
  --task cae--cli--calculix--task-0002 \
  --task cae--cli--calculix--task-0003 \
  --adapter dsh --runs 3 --parallel 2 --kind capability
```

B1（每个栈一次；跨三张镜像）：

```bash
DEEPSEEK_API_KEY=... bin/vericax batch \
  --task cae--cli--calculix--task-0001 \
  --task cae--cli--calculix--task-0002 \
  --task cae--cli--calculix--task-0003 \
  --task cae--cli--fenics--task-0013 \
  --task cae--cli--fenics--task-0014 \
  --task cae--cli--cross-solver--task-0002 \
  --adapter pi --runs 3 --parallel 2 --kind capability
```

B2（两个 batch：18 题与 merged 4 题；同一 tree 上聚合）：

```bash
DEEPSEEK_API_KEY=... bin/vericax batch \
  --split v0.2-cae-cli-25 --adapter opencode \
  --runs 3 --parallel 2 --kind capability

DEEPSEEK_API_KEY=... bin/vericax batch \
  --split v0.2-cae-cli-merged --adapter opencode \
  --runs 3 --parallel 2 --kind capability
```

`--parallel 2` 是 P4 验证过的上限；`--runs 3` 即 n=3。真实 episode 使用动态
challenge token；不得用 `--run-mode rescore` 代替 rerun。凭据只经环境变量注入，
不写入任何文件。

## 8. 报告

```bash
python3 scripts/capability_report.py \
  --batch-dir runs/batch-... [--batch-dir runs/batch-...] \
  --require-n 3 --out docs/results/<date>-<batch>.md
```

输出 **capability × solver × 栈** 矩阵，每行包含：n、均值、min、max、infra 数、
token/题、$/题、活跃时长中位（覆盖率）、错误分类、model；per-task 表另有 split 与
tree_version。同一 task 内混树或 n<3 时脚本以非零状态退出。原始 `runs/` 保留本地，
不入库。

## 9. 风险

| 风险 | 处理 |
|---|---|
| B0 实测成本远高于估算 | 暂停，缩小 B1/B2 题集或降低 n |
| hermes/openclaw cost 为 null | 标 `n/a`，或先补 usage 解析再进 B3 |
| n=3 方差大 | 记录极差；必要时对高方差 cell 加到 n=5，单独说明 |
| 控制通道 reset 被误判为能力失败 | 按 infra 处理：重试并记录，不计分 |
| 任务/verifier 中途变更 | 新 tree_version；受影响 cell 重跑，不合并旧结果 |
| 长跑中断（机器/网络） | 以 batch 为单位分批执行；已完成 episode 不复跑 |

## 10. 非目标

- GUI 通道与 `cross-software`（v1 范围）。
- 超过 n=3 的统计显著性结论。
- 榜单托管、自动发布或持续评测。