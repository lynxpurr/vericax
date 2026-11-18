# VeriCAx

**Artifact-centric verification benchmark for agents in professional CAx (CAD/CAE/CAM) environments.**

VeriCAx 评测通用 agent（完整 agent 栈，而非裸 LLM）在专业 CAx 软件里交付**工程工件**的能力。第一性原则：

> **分数只来自重开工件的可执行校验。** agent 的自述、日志、轨迹永远不作为得分依据。
> verifier 本身被反向审计（正面/替代/负面三组）——审计不过，verifier 不可信。

## 三资产结构（继承 EngiWorld 验证过的形态）

| 资产 | 内容 | 位置 |
|---|---|---|
| VeriCAx-Tasks | 任务包（task.json + verifier + 资源，SHA256 清单） | `tasks/`（本仓） |
| VeriCAx-Images | VM 环境镜像（qcow2+zstd+manifest） | HF org `vericax`（待建） |
| VeriCAx-Runtime | 评测 runtime（容器化 VM、通道隔离、带外评分） | `runtime/`（v0 档 2 落地） |

## 规格文档（spec 是本仓当前的主体交付）

- [`docs/spec/00-vision-and-scope.md`](docs/spec/00-vision-and-scope.md) — 定位、差异化矩阵、范围与非目标
- [`docs/spec/01-task-package-schema.md`](docs/spec/01-task-package-schema.md) — 任务包格式与 split 纪律
- [`docs/spec/02-verifier-spec.md`](docs/spec/02-verifier-spec.md) — **五层 verifier 范式 + 反作弊 + 审计协议**（核心）
- [`docs/spec/03-scoring-and-results.md`](docs/spec/03-scoring-and-results.md) — 分数语义、结果 schema、运维纪律
- [`docs/spec/04-environment-spec.md`](docs/spec/04-environment-spec.md) — 镜像/运行时规格（含实测踩坑记录）
- [`docs/spec/05-roadmap.md`](docs/spec/05-roadmap.md) — 档 0/1/2 路线图
- [`docs/spec/06-naming-and-legal.md`](docs/spec/06-naming-and-legal.md) — 命名决议、四连查结果、法律边界

任务模板见 [`tasks/_template/`](tasks/_template/)。

## 状态

2026-11-18 立项。spec 冻结前待办：商标库人工查询（06 号文档 checklist）；档 0 pilot 任务设计。

## 考古出处

本仓全部设计来自 EngiWorld（arXiv:2609.37686）实地调研：环境复现、verifier 解剖、3 题/20 题实测与失败模式分析。完整调研报告与实测数据见 `~/projects/engiworld-playground/engiworld-调研报告.md`（含 results/cae-batch/ 轨迹留档）。

## License

MIT（见 LICENSE）。注意：第三方工程软件各自许可不受此影响；专有软件（Abaqus/ANSYS 等）任务定义可公开、镜像不公开。
