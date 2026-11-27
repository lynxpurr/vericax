# 05 · 路线图

状态：草案 v0.1（2026-11-18）· 与调研报告 §8.6 档 0/1/2 对齐，换 VeriCAx 口径

> **2026-11-22 状态校准（取代 2026-11-21 块）**：Phase 0 冻结；Phase 1 验收（dsh × task-0001 × n=3 = 1.0/1.0/1.0；pi × n=1 = 1.0）；Phase 1.5 benchmark-validity gate 完成；**Phase 2 完成**——25 道目标题 + 1 道 L6 原型（共 26 包），L6 provenance 判据在 merged 镜像上实证，三张自建镜像 clean-build 验收并已切换为默认镜像（2026-11-22，26 包全部重审计 + L0）。P4 已完成（`batch --parallel 2`、E5 清理顺序、每 episode challenge token）；P5 已完成（opencode/hermes/openclaw adapter + phase2 agent 镜像，三栈 n=1 conformance = 1.0）。E 已随 public 仓库解除；三栈 n≥3 B2 结果于 2026-11-24 发布（`docs/results/2026-11-24-b2.md`）。Phase 2 出口仍按 spec/10 §8。

## 档 0 · 闭环 pilot（~1 天）

> 实际执行偏差（2026-11-19）：未做 5 题；改为 3 题 pilot + Phase 1 runner，任务矩阵见 spec/10 §2。

- [x] 项目骨架 + spec v0.1（本文档体系）
- [ ] 复用已验证环境（CalculiX-2.21 镜像 + EngiWorld runtime），按 spec/01 模板产出 **5 道原生 CAE 题**（不得照抄 EngiWorld 题面，验证"自建题→审计→评分"全流程）
- [ ] 每题跑通：prepare → check → smoke → 2 个被测 agent（Hermes / ZCode bot）×1 run
- [ ] 退出条件：verifier 三组审计全过（spec/02 §4）+ 好坏 run 可区分 + summary.json 全字段落盘

## 档 1 · 可信评测闭环（1-2 天）

> 大部分已由 Phase 1 实现（spec/09 §10 清单全勾）；dsh × task-0001 × n=3 已于 2026-11-19 完成（1.0/1.0/1.0）。

- [x] 评分面/执行面分离落地（verifier 带外执行容器）
- [x] 反作弊层按 spec/02 §2 逐项实现 + 单元测试（AST 校验器用真实 bypass 样本测）
- [x] result schema v0.1 固化 + 复现存档目录结构
- [x] verifier 审计套件做成可执行脚本（`vericax.audit --task <id>`）

## 档 1.5 · benchmark-validity gate（2026-11-19 新增）

- [x] GT self-check：每个任务包用参考 deck 重放并复现 GT summary；fail 不得发布（spec/02 L0）。
      实现：`vericax audit --task <id> --group reference`；VM 验证已完成（21 题 L0）。
- [x] `run_mode` / `tree_version` 进 summary（spec/03）。实现：`validity.tree_version` + summary 字段。
- [ ] CLI artifact-write policy：记录 `artifact_write_rejected` / `agent_stalled`；决定是否支持版本化重试（spec/09 §11）。
- [x] 模型对比必须同一 `tree_version`；n≥3 才下结论。实现：`report` 按 tree/mode 分组，测试集默认排除。
- [x] 验收：审计套件含参考自洽组；榜单模板含 tree 版本；Phase 2 第一批题全部过 gate。

## 档 2 · v0.5 CAE 全量（~1 周）

- [ ] 5 求解器 × 20 题 = 100 题（复用 EngiWorld 15 镜像中 CAE 五个，31.6GB）
- [ ] CAM 先发 20 题（freecad-path 镜像，社区空白域）
- [x] 排行榜 v1：至少 3 个 agent 栈 × n≥3（2026-11-24 完成：dsh / opencode / openclaw × 22 题 × n=3；见 `docs/results/2026-11-24-b2.md`；协议 spec/11）
- [ ] Fleet CP 加 VeriCAx tab（ECharts 骨架现成）：通过率/留存率/$每题/错误分类

## 里程碑语义

- **v0.1**：spec 冻结（档 0 退出后修订一轮）
- **v0.5**：CAE 100 题 + CAM 20 题发布（HF org 上线）
- **v1**：CAD 域 + GUI 通道 + 跨域留存率面板
- **v1.5**：VeriCAx-Ops 子集独立发布（运维域，先发空间见调研报告 §9）

## 2026-11-26 下一阶段计划

B2 已完成并发布。2026-11-26 owner 决定按 v0.2.1-alpha → 可靠性/成本 → 难度校准的顺序执行；
每个 batch 的真实跑量仍需逐批授权。

| 步骤 | 内容 | 验收 | 估算 |
|---|---|---|---|
| **1. v0.2.1-alpha 补丁发布（已完成 2026-11-26）** | `develop → main`：socket 修复、Bailian 变体、能力报告工具、B2 结果、状态/隐私清扫（#29–#35，共 7 个 commit），另含 release 元数据；tag `v0.2.1-alpha`，pre-release | main 含这 7 个 commit + release commit；CI 绿；release notes 不含账户信息；任务包与 split 不变 | ~1h |
| **2. 可靠性与成本** | 顺序：(1) sandbox 失联即中止并取证；(2) 在 dsh × FEniCS 最坏组合上定位根因，每次只改一个变量；(3) 按根因修；(4) batch 自动 infra 重试：首轮跑完后统一重试，每格上限 2 次，新 episode，次数入 `batch.json`，连续 3 次 infra 熔断；(5) 防泄漏与 batch 前置检查；(6) openclaw usage 解析 | 机制层面：失联后 1 分钟内中止、重试有记录、原生 0.0 不重试、无容器残留；真实 infra 率放到步骤 3 的校准批实测 | 1 周 |
| **3. 难度校准** | 新增 4 道 FEniCS：cross-stage-consistency（补 capability × solver 空格，先做试点）、open-environment、observation-reconstruct、design-optimization；cross-solver 暂缓；只对新题跑 3 栈 × n=3 | 每题 audit 15/15、robust 10/10、L0；每题至少一个 cell 两栈极差不重叠；三栈全零先查评分侧原因再判定 | 1–2 周 |
| **4. 再决策** | 根据步骤 3 决定 v0.5（CAE 100 + CAM 20）或 B3（五栈） | owner 评审 | — |

**2026-11-26 调整依据（B2 batch 记录复核）**：已记录的 16 次 infra 失败全部是 sandbox
控制通道失联，首次错误多出现在 agent 开始后几分钟内，且 dsh 在 parallel 2 与 parallel 1 下
的失败数相同（各 4/27）；因此内存感知并行降为前置检查，先做失联即中止与根因定位。
验收不再写"infra 率低于某个值"：小批量下该比率没有统计意义。cross-solver 4 题中 0004
三栈全 1.0、0002/0003 各栈不超过 0.333，加难只会产生地板效应，暂缓。

**2026-11-27 进展**：

- **v0.2.2-alpha 工具补丁**（#38–#43，任务套件不变）：失联即中止与取证、batch 自动
  infra 重试/熔断/预检、openclaw usage 解析、缓存读取口径，以及 B2 结果的三处更正
  （infra 19/217 = 8.8%、openclaw token 列、cache-read 列）。
- **步骤 2 的失联机制已确认**：sandbox 失联是 guest kernel panic。自建镜像里 PID 1
  （systemd 255.4-1ubuntu8.18，内核 6.8.0-147-generic）的主线程从系统调用
  （`epoll_wait`、`clone3`）返回时出错，PID 1 一死内核即 panic。不接 agent 的 VM 也
  会崩（开机后 41 分钟）；捕获到的几次都没有主机压力或 guest 内存不足。触发条件未知，
  下一步是内核层面的定位；`logs/vm-console.log` 与 `logs/sandbox-loss.json` 是证据。
  原定的 8G 内存对照组因此取消，agent 命令回放也不再需要。
- **步骤 3 试点**：`cae--cli--fenics--task-0017`（热弹两阶段分析，L1–L4）已过审计
  19/19、robust 10/10，尚未进 split。

- **B3 暂缓**：pi/hermes 需先有 Bailian provider 配置与 usage 口径；B2 已有三栈结果，边际收益低。
- **不做**（除非 owner 另行决定）：org 迁移、公告、n>3 的统计扩展。
- 发布规则见 spec/11 与 `docs/results/2026-11-24-b2.md`：只发布聚合表，不发布 raw runs、账户信息或 verifier 规则文本。

## 明确的不做

- 全域 15 镜像一次拉齐（BIM/DCC/EDA 对当前工作线无产出）
- 单跑定选型结论（论文与实测双重告诫：方差大，n≥3 起步）
- 把 re-score 当 rerun，或在未过 benchmark-validity gate 的题上做模型对比
- 裸 LLM 榜（那是 EngiWorld 的活；VeriCAx 的被测对象永远是完整 agent 栈）
