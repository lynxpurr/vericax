# 02 · Verifier 规格（核心文档）

状态：草案 v0.1（2026-11-18）· 五层范式源自 EngiWorld verifier 解剖（CalculiX 80 行 → 跨软件 1205 行/47 函数），反作弊规格源自 `engine/mm_agents/agent.py` AST 校验器实读

## 0. 设计立场

verifier 是本基准的第一公民。社区（CAD Bench v2、BIM-Edit、FEABench）已普遍走到"执行/重开验真"，但没人把**反作弊栈 + verifier 反向审计**做成一等公民——这是 VeriCAx 的差异化锚点，本规格因此比任务集更优先冻结。

## 1. 五层范式（每道 verifier 必须声明实现了哪些层；L1/L2 强制，L3/L4 按题型，L5 优化题强制）

### L1 交付完整性（强制）
- required artifacts 逐一存在且非空（对应实测教训：t02 交付 0 字节 `laminate.dat` 仍"流程完整"，必须由本层拦住）
- 工件用**原生 API 或格式解析器**重开：CalculiX 用 `.dat/.frd` 解析、FEniCS 用 dolfin checkpoint 读取、BIM 用 IfcOpenShell、通用结构用 schema 校验
- 中性格式（STEP/DXF/IFC）**重新导入**再校验——导出环节的错误也算错

### L2 防篡改 + 双路径互验（强制）
- 输入/baseline 文件逐字节（或 1e-9 数值）比对，任何修改 → 0 分（对应 `assert_baseline_is_unchanged` 范式）
- 关键结论用**两条独立解析路径**交叉验证（EngiWorld 先例：`abaqus_step_bbox` 与 `external_cadquery_step_bbox` 互验）。VeriCAx 常用对：官方 API vs 独立解析器（如 meshio/vtk vs 求解器自带 reader）
- agent 可达面封禁清单（ground_truth/evaluator）由 runtime 强制，不依赖 prompt

### L3 独立重算交叉验证（仿真/优化题强制）
- verifier 从任务输入**独立重解算**，将提交的场结果读回逐节点/逐单元比对（容差 1e-8·scale，对应 FEniCS 优化 verifier 实测范式）
- 意义：提交的物理结果必须与提交的输入物理自洽，假场文件/抄来的数值当场识破

### L4 链路证据（跨软件/多阶段题强制）
- 中间产物必须存在且跨阶段一致（EngiWorld `cae_chain_blob` 先例）
- VeriCAx 运维子集对应物：配置版本 hash 必须能在运行时状态里找到

### L5 两段式评分（design-optimization 题强制）
- 第一段可行性门：约束全过才进第二段；任一违反 → 0 分（不部分给分）
- 第二段质量分：`score = clamp(1 − C_submitted / C_baseline)`，C 由 verifier 现场重算；metric 写在 task.json（`{name, baseline_score, direction, output_field}`），verifier 内不硬编码
- baseline_score 必须来自 verifier 自测参考解，不接受任务书里的声明值

## 2. 反作弊规格

| 威胁 | 对策 | 源头先例 |
|---|---|---|
| 交假脚本（没真跑求解器） | AST 校验解题脚本：必须 import 官方 API、必须出现完整求解工作流调用组、字符串字面量必须引用工件文件名 | FEniCS 优化 verifier `check_solver_script` |
| 编码 payload 绕过 | Base64/hex/压缩/动态 import 解码后复审 | `_PYAUTOGUI_REJECT` 正则先例 |
| 试探 verifier 规则 | 拒绝消息统一隐匿（stealth message），防枚举 | `_PYAUTOGUI_REJECT_MSG` 先例 |
| 通道借道（GUI 题跑 shell） | pyautogui 代码 AST 白名单 + 禁 `os.system/subprocess.*` + 禁终端 hotkey 组合 + 循环打字检测 + 聚合字面量检查；CLI 题禁截屏/鼠标键盘 API | `_validate_pyautogui_cdata`（v1 GUI 引入） |
| 用文本工具手搓工件 | integrity_policy.native_interface_only：原生 deck 可编辑，评分工件必须经官方接口产出 | CLI integrity rules 先例 |
| 偷改输入/读参考答案 | L2 防篡改 + runtime 封禁清单 + 带外评分（§3） | 综合先例 |
| 调试死循环刷轮次 | 不属于 verifier 职责，由 runtime 侧早停策略处理（连续 N 步同类错误 → 换策略提示或止损；记录为 `agent_stalled` 类目，不污染分数） | t03 教训（100 轮 357K reasoning） |

## 3. 评分面与执行面分离（测 agent 栈的关键改造）

EngiWorld 测裸 LLM 时模型看不到 task-root；VeriCAx 的被测 agent 拥有文件系统，因此：

1. agent 环境只注入：instruction + `init_file/` 内容
2. `eval.py`、`ground_truth/`、`resources.sha256` 只存在于评分面（host 评分容器/带外目录），agent 不可达
3. 评分在 episode 结束后带外执行；评分输出只有 `True/False/<score>` 一行，失败原因以 `debug:` 行写评分侧日志（可发布、不含规则枚举信息）
4. 任务包发布物中 verifier 以 **checksum 引用**存在，reveal 政策：审计通过后随任务包公开（公开是为了社区复现审计，非供 agent 检索——runtime 的封禁清单保证 agent 评测时读不到）

## 4. Verifier 审计协议（第一公民；审计不过 = 任务包不得发布）

| 组 | 构成 | 通过判据 |
|---|---|---|
| 正面组 | 参考解（ground_truth）走完整评分流程 | 100% 收 |
| 替代路径组 | ≥2 条与参考解**不同**的合法解法（不同软件路径/不同参数/不同中间格式） | 100% 收 |
| 负面组 | ①空交付 ②只交指标不交工件 ③篡改输入 ④跳步骤（中间产物缺失）⑤编码 payload ⑥假场/抄数值 | 100% 拒 |
| 稳健组 | 同一 verifier 连续 10 次对同一提交 | 判定全一致 |

审计记录模板写入任务包 `ground_truth/audit.md`：每组用例、期望、实际、审计人、日期。北极星：误杀 0%、漏放 0%（调研报告 §4/§7 的 t02 案例 = 负面组 ② 的原型）。

## 5. Verifier 工程约束

- 无第三方依赖（标准库 + 被测软件官方 API + Pillow），保证评分容器最小化
- 单 verifier ≤ 300 行为宜；超限说明任务该拆分
- 每个 verifier 顶部声明实现层：`IMPLEMENTS = ("L1", "L2", "L3", "L5")`
- 版本随任务包走，`resources.sha256` 覆盖 eval.py 自身
