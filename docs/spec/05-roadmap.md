# 05 · 路线图

状态：草案 v0.1（2026-11-18）· 与调研报告 §8.6 档 0/1/2 对齐，换 VeriCAx 口径

## 档 0 · 闭环 pilot（~1 天）

- [x] 项目骨架 + spec v0.1（本文档体系）
- [ ] 复用 um890 已验证环境（CalculiX-2.21 镜像 + EngiWorld runtime），按 spec/01 模板产出 **5 道原生 CAE 题**（不得照抄 EngiWorld 题面，验证"自建题→审计→评分"全流程）
- [ ] 每题跑通：prepare → check → smoke → 2 个被测 agent（Hermes / ZCode bot）×1 run
- [ ] 退出条件：verifier 三组审计全过（spec/02 §4）+ 好坏 run 可区分 + summary.json 全字段落盘

## 档 1 · 可信评测闭环（1-2 天）

- [ ] 评分面/执行面分离落地（verifier 带外执行容器）
- [ ] 反作弊层按 spec/02 §2 逐项实现 + 单元测试（AST 校验器用真实 bypass 样本测）
- [ ] result schema v0.1 固化 + 复现存档目录结构
- [ ] verifier 审计套件做成可执行脚本（`vericax.audit --task <id>`）

## 档 2 · v0.5 CAE 全量（~1 周）

- [ ] 5 求解器 × 20 题 = 100 题（复用 EngiWorld 15 镜像中 CAE 五个，31.6GB）
- [ ] CAM 先发 20 题（freecad-path 镜像，社区空白域）
- [ ] 排行榜 v1：Hermes / ZCode bot / OpenClaw 至少 3 个 agent 栈 × n≥3
- [ ] Fleet CP 加 VeriCAx tab（ECharts 骨架现成）：通过率/留存率/$每题/错误分类

## 里程碑语义

- **v0.1**：spec 冻结（档 0 退出后修订一轮）
- **v0.5**：CAE 100 题 + CAM 20 题发布（HF org 上线）
- **v1**：CAD 域 + GUI 通道 + 跨域留存率面板
- **v1.5**：VeriCAx-Ops 子集独立发布（运维域，先发空间见调研报告 §9）

## 明确的不做

- 全域 15 镜像一次拉齐（BIM/DCC/EDA 对当前工作线无产出）
- 单跑定选型结论（论文与实测双重告诫：方差大，n≥3 起步）
- 裸 LLM 榜（那是 EngiWorld 的活；VeriCAx 的被测对象永远是完整 agent 栈）
