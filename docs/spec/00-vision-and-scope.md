# 00 · 愿景与范围

状态：草案 v0.1（2026-11-18）· 冻结条件：档 0 pilot 完成后修订一次

## 1. 一句话定位

VeriCAx 是**工件级验真（artifact-centric verification）优先**的 CAx agent 评测框架：测通用 agent 栈（harness + 模型，而非裸 LLM）在专业 CAD/CAE/CAM 软件里交付工程工件的能力。

## 2. 第一性原则（不可妥协）

1. **分数只来自重开工件的可执行校验**——verifier 用原生 API/格式解析器重开交付物，agent 自述/日志/轨迹不得作为得分依据
2. **verifier 被反向审计**——正面组全收、替代合法路径组全收、负面组全拒；审计记录随任务包发布（详见 spec/02）
3. **评分面与执行面分离**——verifier 与 ground_truth 永不出现在 agent 可达盘面（agent 能读文件，这是与 EngiWorld 测裸 LLM 的本质差异）
4. **通道隔离**——每道题固定 CLI 或 GUI 通道；CLI 题禁 GUI 操作，GUI 题禁 shell 借道（解析器级拦截，v1 引入 GUI）

## 3. 差异化定位矩阵

| 项目 | 范围 | 通道 | verifier 态度 | VeriCAx 差异点 |
|---|---|---|---|---|
| EngiWorld (2609.37686) | 6 域 26 软件 | CLI+GUI 隔离 | 工件级 + 审计 | 它测裸 LLM；我们测 agent 栈（verifier 带外执行） |
| CADWorld (2609.16251) | FreeCAD 工作流 | 纯 GUI | 过程+结果 | 我们 CLI 先行 + CAM 覆盖 |
| FEABench (2504.06260) | COMSOL 多物理场 | API 代码生成 | 执行验真 | 单一商业软件 vs 我们开源全家桶 |
| CAE-bench | FEA/CFD/多体/耐久 | 待查 | 待查 | 待细读后补 |
| CAD Bench v2 / CAD-bench | Build123d/FreeCAD | 代码 | verifier 排行榜 | 无反作弊栈、无审计协议 |
| CADTestBench (NeurIPS'26) | Text-to-CAD 单点生成 | — | 测试用例 | 非工作流、非 agent |
| caX-bench (Ai Build, 商标) | CAD/CAE/CAM cost-accuracy | — | 未公开细节 | 我们公开、可复现、审计型 |

**定位句（对外统一口径）**：*VeriCAx: Artifact-Centric Evaluation of General Agents in Professional CAx Environments*。

## 4. 范围

| 版本 | 域 | 软件（全开源） | 题量目标 |
|---|---|---|---|
| v0 (pilot) | CAE | CalculiX 2.21（复用调研环境） | 5 题打通闭环 |
| v0.5 | CAE 全量 | CalculiX / FEniCS / OpenFOAM / OpenFAST / FLORIS | 5×20 = 100 题 CLI |
| v1 | CAM（空白域先发） | freecad-path (CAM 工作台) | 20 题 |
| v1 | CAD | FreeCAD / OpenSCAD / Blender / BRL-CAD | 4×20 |
| v1.5 | GUI 通道 | 同上软件 GUI 形态 | 另行分层 |
| 并行 | VeriCAx-Ops | 运维域子集（RAGFlow/cron/跨服务链，见调研报告 §8） | 5→20 题 |

镜像策略：v0/v0.5 直接复用 EngiWorld 15 个开源镜像（MIT，含 CalculiX-2.21 已在 um890 实测可用）；v1 起自建镜像按 spec/04 规范。

## 5. 非目标（明确排除）

- 训练数据集（不保证分布覆盖，只保证验收有效性）
- 通用对话/推理能力评测
- 硬件性能测试（Cadalyst 类）
- 专有软件镜像分发（Abaqus/ANSYS 任务定义可公开，镜像永不公开，同 EngiWorld 许可边界）
- GUI 题在 v1.5 前进入主榜（GUI 分与 CLI 分永不合并为一个总分，通道分数永远分开报告）

## 6. 成功判据

档 0 退出条件见 spec/05。北极星指标：**verifier 对"故意错提交"的拒收率 = 100%**，且对替代合法路径的误杀率 = 0%。
