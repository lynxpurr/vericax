# 05 · 路线图

状态：草案 v0.1（2026-11-18）· 与调研报告 §8.6 档 0/1/2 对齐，换 VeriCAx 口径

> **2026-11-22 状态校准（取代 2026-11-21 块）**：Phase 0 冻结；Phase 1 验收（dsh × task-0001 × n=3 = 1.0/1.0/1.0；pi × n=1 = 1.0）；Phase 1.5 benchmark-validity gate 完成；**Phase 2 完成**——25 道目标题 + 1 道 L6 原型（共 26 包），L6 provenance 判据在 merged 镜像上实证，三张自建镜像 clean-build 验收并已切换为默认镜像（2026-11-22，26 包全部重审计 + L0）。P4 已完成（`batch --parallel 2`、E5 清理顺序、每 episode challenge token）；P5 已完成（opencode/hermes/openclaw adapter + phase2 agent 镜像，三栈 n=1 conformance = 1.0）。唯一未完成的是 E：GitHub Actions 账户级账单阻塞，本地 `scripts/ci_local.sh` 为权威门禁。Phase 2 出口仍按 spec/10 §8。

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
- [ ] 排行榜 v1：至少 3 个 agent 栈 × n≥3（当前建议 dsh / pi / opencode；协议与批次见 spec/11）
- [ ] Fleet CP 加 VeriCAx tab（ECharts 骨架现成）：通过率/留存率/$每题/错误分类

## 里程碑语义

- **v0.1**：spec 冻结（档 0 退出后修订一轮）
- **v0.5**：CAE 100 题 + CAM 20 题发布（HF org 上线）
- **v1**：CAD 域 + GUI 通道 + 跨域留存率面板
- **v1.5**：VeriCAx-Ops 子集独立发布（运维域，先发空间见调研报告 §9）

## 明确的不做

- 全域 15 镜像一次拉齐（BIM/DCC/EDA 对当前工作线无产出）
- 单跑定选型结论（论文与实测双重告诫：方差大，n≥3 起步）
- 把 re-score 当 rerun，或在未过 benchmark-validity gate 的题上做模型对比
- 裸 LLM 榜（那是 EngiWorld 的活；VeriCAx 的被测对象永远是完整 agent 栈）
