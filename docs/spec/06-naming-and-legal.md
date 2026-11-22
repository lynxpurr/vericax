# 06 · 命名决议与法律边界

状态：决议（2026-11-18 定案）

## 1. 定名：VeriCAx

- 全称定位句：*VeriCAx: Artifact-Centric Evaluation of General Agents in Professional CAx Environments*
- 资产命名：VeriCAx-Tasks / VeriCAx-Images / VeriCAx-Runtime；CLI 包名 `vericax`；运维子集 VeriCAx-Ops

## 2. 否决记录（查重实证，防止未来翻案）

| 候选 | 否决理由 |
|---|---|
| cax-testbench | 未被占但：与 CADTestBench（NeurIPS 2026）形态过近；cax…bench 框架已挤 8 项目；"testbench"词性偏工具 |
| cax-harness-bench | "test harness"=装具的术语歧义（会被读成工具而非基准）；三段连字符拗口 |
| EngiBench 系 | arXiv:2509.17677 已占；Engi* 前缀空间拥挤 |
| FleetBench | google/fleetbench 已占 |
| VeriCAx | GitHub org / PyPI / HF org 三项 2026-11-18 实测 404=可用；**无公开同名项目** |

## 3. 启用前四连查 checklist

- [x] GitHub org `vericax` —— 2026-11-18 web 查询 404=可用（待注册占位）
- [x] PyPI `vericax` —— 2026-11-18 404=可用
- [x] HuggingFace org `vericax` —— 2026-11-18 404=可用（待注册占位）
- [x] Name availability was reviewed before the first public release.
- [ ] GitHub org 与 HF org 注册占位（先占名再开发）

## 4. 许可边界

| 对象 | 许可 |
|---|---|
| VeriCAx 代码/任务定义/verifier | MIT |
| EngiWorld 派生部分（v0 复用的镜像/runtime） | 按 EngiWorld MIT 归属；派生任务须声明 source |
| 第三方工程软件（镜像内） | 各自许可；分发的是 VM 镜像而非软件副本时的边界随 v1 自建镜像时请法务复核 |
| 专有软件（Abaqus/ANSYS） | 任务定义可公开，镜像永不公开（同 EngiWorld 先例） |
| 数据 | ground_truth 与审计记录随任务包公开（公开=供社区复现审计；agent 评测时 runtime 保证不可达） |

## 5. 品牌一致性规则

- 对外一律 `VeriCAx`（CamelCase，CAx 保持行业拼法）；代码/包名一律小写 `vericax`
- 不使用 "cax + bench" 连字框架
- 引用 EngiWorld 必须带 arXiv:2609.37686；引用实测数据必须带 split 版本
