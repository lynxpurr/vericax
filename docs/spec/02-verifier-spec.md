# 02 · Verifier 规格（核心文档）

状态：草案 v0.1（2026-11-18）· 五层范式源自 EngiWorld verifier 解剖（CalculiX 80 行 → 跨软件 1205 行/47 函数），反作弊规格源自 `engine/mm_agents/agent.py` AST 校验器实读

## 0. 设计立场

verifier 是本基准的第一公民。社区（CAD Bench v2、BIM-Edit、FEABench）已普遍走到"执行/重开验真"，但没人把**反作弊栈 + verifier 反向审计**做成一等公民——这是 VeriCAx 的差异化锚点，本规格因此比任务集更优先冻结。

## 1. 五层范式 + L0 参考自洽 + L6 provenance（L0 是发布门槛；每道 verifier 必须声明实现的 L1–L5 层；L1/L2 强制，L3/L4 按题型，L5 优化题强制，L6 `software-selection` 强制）

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

### L0 参考自洽（发布门槛；2026-11-19 增补）
- 用任务包 `ground_truth/` 里的参考 deck 原样走一遍 verifier，必须复现 shipped GT summary。
- GT deck 与 GT summary 任一不一致 → **任务包无效，不得发布**；这不是 agent 失败。
- L0 是发布门槛，不是 agent 评分层；`IMPLEMENTS` 不要求写 L0。
- 审计证据：EngiWorld CalculiX 20 题中 task-05/17/19 的 GT summary 位移比自己的 GT deck 输出小 **8.444x**；task-04 的 tie 面写错、task-06 的压力面写错。详见研究仓 `engiworld-调研报告.md` §11 与 `results/gt-selfcheck/`。

### L6 工具来源（provenance；`software-selection` 强制，2026-11-20 P2 spike）

本仓的 provenance 指**工件-工具等价性**：提交的工件必须是 required tool 对该输入的**可复现原生输出**。它**不**证明"agent 确实调用了该工具"——后者需要 host 侧进程/宿主机证明（未实现，见 §6 边界）。spec/10 §3 的 cross-solver 任务必须实现 L6；其他 capability 可选。

- **L6.1 原生工件对**：任务必须要求 required tool 的**原生 model + 原生 result**（CalculiX：`.inp` + `.dat`/`.frd`；FEniCS：`mesh.msh` + `XDMF/HDF5` 或 dolfinx checkpoint），并按 job/stem 配对。中性格式（`mesh.msh`、`summary.txt`）不是 provenance 证据；出现其他工具的原生结果族（`.odb`/`.rst`/`.xdmf` 等）或混合分支时拒绝。
- **L6.2 重跑等价**：verifier 在评分 VM 用 required tool 重跑 submitted model，并比较**提交的原生结果**（逐节点/逐单元场）与新鲜结果，容差在任务包中声明；只比 `summary.txt` 不够。空文件、伪造的非空结果、混合分支结果一律拒绝。FEniCS 不得执行 agent 提交的 `solve.py`（评分 VM 内有 `ground_truth/`）；用 verifier 自己的重解脚本。
- **L6.3 挑战绑定**：episode 生成 challenge token，写入模型的要求字段/集合名，并必须出现在 solver 生成的输出中；L0/审计可用固定 audit token。P2 采用 **label token**（不改变物理，pins 与 L0 稳定）；**physics token**（扰动载荷/几何，强制真算）留到后续。
- **L6.4 环境记录**：`image_sha256`、`snapshot`、required tool 的 probe 必须记录；合并镜像需要 `solver_probes` 映射（不能只有一个 `solver_probe`）。verifier 只接受 required tool 的分支，即使镜像里同时存在另一个工具。
- **L6.5 审计**：正面 + 至少 2 条 required tool 的合法替代路径；负面组必须覆盖：其他工具工件、重放/错误 token、混合原生分支、伪造的非空原生结果。其他工具 fixture 必须带自己的 provenance 记录（生成镜像的 `image_sha256`、工具版本、命令、sha256），不得当作 pin。

**P2 沙箱形态决定（2026-11-20）**：cross-solver 采用**单镜像双求解器**（merged image）。理由：当前契约是单 `snapshot`、单 sandbox、单 proxy endpoint；多 VM 选择需要 proxy 路由、第二产物通道与契约变更，属于 P4 而不是 P2。P3 产出 merged image（2026-11-21 验收，`VeriCAx-merged.qcow2`）；4 道 `software-selection` 题（cross-solver task-0002…0005）在 merged image 上完成 L1–L3+L6 全管线（audit 15/15、robust 10/10、L0、fake smoke 1.0），`software-selection` capability 就绪。L6 原型题保留 CalculiX 镜像 + 固定 audit token 作拒绝判据回归。

## 2. 反作弊规格

| 威胁 | 对策 | 源头先例 |
|---|---|---|
| 交假脚本（没真跑求解器） | AST 校验解题脚本：必须 import 官方 API、必须出现完整求解工作流调用组、字符串字面量必须引用工件文件名 | FEniCS 优化 verifier `check_solver_script` |
| 编码 payload 绕过 | Base64/hex/压缩/动态 import 解码后复审 | `_PYAUTOGUI_REJECT` 正则先例 |
| 试探 verifier 规则 | 拒绝消息统一隐匿（stealth message），防枚举 | `_PYAUTOGUI_REJECT_MSG` 先例 |
| 通道借道（GUI 题跑 shell） | pyautogui 代码 AST 白名单 + 禁 `os.system/subprocess.*` + 禁终端 hotkey 组合 + 循环打字检测 + 聚合字面量检查；CLI 题禁截屏/鼠标键盘 API | `_validate_pyautogui_cdata`（v1 GUI 引入） |
| 用文本工具手搓工件 | integrity_policy.native_interface_only：原生 deck 可编辑，评分工件必须经官方接口产出 | CLI integrity rules 先例 |
| 偷改输入/读参考答案 | L2 防篡改 + runtime 封禁清单 + 带外评分（§3） | 综合先例 |
| 用别的工具的结果冒充 required tool | L6.1 原生工件对 + L6.2 全字段重跑比较 | EngiWorld `discover_branch` 先例 |
| 重放旧 episode/旧 token 的工件 | L6.3 challenge 绑定（label token；physics token 留后） | P2 spike |
| 混合两个工具的原生分支 | L6.1 分支排他：出现第二个原生结果族即拒绝 | P2 spike |
| 伪造非空的 `.dat`/场文件 | L6.2 逐节点比较提交结果与重跑结果 | P2 spike |
| 调试死循环刷轮次 | 不属于 verifier 职责，由 runtime 侧早停策略处理（连续 N 步同类错误 → 换策略提示或止损；记录为 `agent_stalled` 类目，不污染分数） | t03 教训（100 轮 357K reasoning） |

**`allow_native_deck_edit` × summary 防伪造（2026-11-22 正式确认）**：允许文本编辑原生
deck 与"summary 防伪造"是设计组合，不矛盾——agent 可以编辑 `.inp`/`.FOAM` 等 driver
文件，但评分工件仍由 verifier 用**提交的 deck 独立重跑**并逐项比对 summary/场结果
（L2/L6.2），N5（fabricated summary）负例覆盖伪造路径；字段为 `false` 只表示该题没有
可编辑的原生 deck（交付 XDMF/HDF5 等格式）。该字段是任务作者与审计者的**通道声明**，
harness 不据此改变运行时行为（spec/01 §2）。

## 3. 评分面与执行面分离（测 agent 栈的关键改造）

EngiWorld 测裸 LLM 时模型看不到 task-root；VeriCAx 的被测 agent 拥有文件系统，因此：

1. agent 环境只注入：instruction + `init_file/` 内容
2. `eval.py`、`ground_truth/`、`resources.sha256` 只存在于评分面（host 评分容器/带外目录），agent 不可达
3. 评分在 episode 结束后带外执行；评分输出只有 `True/False/<score>` 一行，失败原因以 `debug:` 行写评分侧日志（可发布、不含规则枚举信息）
4. 任务包发布物中 verifier 以 **checksum 引用**存在，reveal 政策：审计通过后随任务包公开（公开是为了社区复现审计，非供 agent 检索——runtime 的封禁清单保证 agent 评测时读不到）

## 4. Verifier 审计协议（第一公民；审计不过 = 任务包不得发布）

| 组 | 构成 | 通过判据 |
|---|---|---|
| 参考自洽组 | 参考案例重放（`audit_cases.py` 的 GOLD；包内若有 GT deck 则原样重放）+ 与 GT summary 对表 | 100% 一致；否则任务包无效（L0） |
| 正面组 | 参考解（ground_truth）走完整评分流程 | 100% 收 |
| 替代路径组 | ≥2 条与参考解**不同**的合法解法（不同软件路径/不同参数/不同中间格式） | 100% 收 |
| 负面组 | ①空交付 ②只交指标不交工件 ③篡改输入 ④跳步骤（中间产物缺失）⑤编码 payload ⑥假场/抄数值 | 100% 拒 |
| 稳健组 | 同一 verifier 连续 10 次对同一提交 | 判定全一致 |

参考自洽组的执行入口是 `vericax audit --task <id> --group reference`：重放参考案例，
要求产出与 `ground_truth/summary.txt` 数值一致，并用同一 verifier 复判；结果写
`ground_truth/reference_selfcheck.json`，summary 的 `reference_selfcheck` 字段引用
`pass | fail | not_run`。该记录是派生审计产物，不进入 `resources.sha256`。

审计记录模板写入任务包 `ground_truth/audit.md`：每组用例、期望、实际、审计人、日期。北极星：误杀 0%、漏放 0%（调研报告 §4/§7 的 t02 案例 = 负面组 ② 的原型）。

### 4.1 可执行化与强制（2026-11-20 拍板，铺题前置门）

审计协议不再只靠文档纪律，由工具链强制执行：

1. **稳健组入口**：`scripts/audit_task.py --repeat N`。跑完全部用例后，在同一 VM 内对
   GOLD 提交连续判定 N 次，要求判定全一致；`audit.md` 写入一行
   `- robust: N/N consistent`。发布前 N≥10。
2. **负面组分类声明**：`audit_cases.py` 必须提供 `NEGATIVE_KINDS` 字典，把六类反作弊
   负例的标签映射到：
   `empty | metrics_only | tampered_input | skipped_steps | encoded_payload | fabricated_field`。
   允许额外的物理/格式负例不进入该字典——它们只计入负面组数量，不参与六类覆盖检查。
3. **打包门**：`scripts/pack_task.py` 导入 `audit_cases.py` 并校验——
   正面组 ≥1、替代路径组 ≥2、负面组 ≥6 且六类键齐全、`audit.md` 含 `robust: N/N consistent`
   且 N≥10；任一不满足，打包失败（`--check` 同样失败）。
4. **替代路径的判据**：必须与参考解在工作流上不同（不同编码/网格策略/中间格式），
   不能只是同一文件换空白或改名；审计记录里写清"不同在哪里"。
5. **负例拒绝边距（2026-11-22）**：`scripts/audit_task.py` 用数值型用例的分数计算
   `min(ge 期望的实际收分) - max(le 期望的实际拒分)`，写入 `audit.md` 的
   `- rejection margin: X (min positive … - max negative …)` 行；数值题要求该边距
   `> 0`，正负分数带重叠即审计失败。exact_match 题没有数值带，记录为
   `n/a (no numeric expectations)`。该行不改变打包门校验的表格结构（行数/列数不变），
   因此旧记录的打包校验不受影响；下次重审计自动带边距。

## 5. Verifier 工程约束

- 无第三方依赖（标准库 + 被测软件官方 API + Pillow），保证评分容器最小化
- 单 verifier ≤ 450 行为宜（2026-11-20 由 300 放宽：当时 3 个 CalculiX verifier 为 383–411 行，拆分收益低于改动风险）；超限说明任务该拆分。**例外（2026-11-22）**：`cross-solver/task-0005` 为 454 行，按软约束接受——裁 4 行的收益低于触发该题重新审计/L0 的成本。
- **例外（2026-11-28）**：读 CalculiX deck 的 15 个 verifier 各带一份逐字相同的 `canonical_deck`（约 160 行，把合法写法规范化后再检查，见 lessons §17），行数因此到 470–614。这段拷贝由 `tests/test_deck_spellings.py` 与 `scripts/deck_canonical.py` 核对，不计入「超限说明任务该拆分」的判断；把 deck 解析做成随包分发的共用模块是后续工作。`calculix/task-0013`（570 行）和 `task-0014`（570 行，2026-11-28 入库）是两道多步 deck 题，自己解析 deck、长度在三个步骤的载荷与集合检查上，按同一软约束接受。
- 每个 verifier 顶部声明实现层：`IMPLEMENTS = ("L1", "L2", "L3", "L5")`
- 版本随任务包走，`resources.sha256` 覆盖 eval.py 自身
- **不做语义等价的字面量拒绝**：`valid_input` 只做数学校验（载荷和、边界 DOF、关键字存在），不要求唯一字符串拼写；summary 解析容忍表头/空行；等价写法必须都收。EngiWorld 审计中 task-09（`,,5.0,1.0e-5` vs `1,8,5.0,1.0e-5`）、task-12/18（summary 表头）因此误杀。
- **拒绝原因必须可分类**：`numeric_mismatch` / `format_error` / `equivalent_but_rejected`；`equivalent_but_rejected` 是 verifier 缺陷，必须修，不能计入 agent 能力。

## 6. provenance 边界（P2 spike 结论，2026-11-20）

- **L6 是工件-工具等价性，不是调用证明**。verifier 能证明"该工件是 required tool 对该输入的原生可复现输出"，不能证明"agent 进程确实执行了该工具"。后者需要 host 侧进程追踪/不可变审计，当前 harness 没有；spec、报告和任务说明都必须按前者表述。
- **真正的 `software-selection` 需要 merged image**。单镜像双求解器是当前单 `snapshot`/单 sandbox/单 proxy 契约下唯一可行的形态；多 VM-per-task 属于 P4，不是 P2。
- **原型题在 merged image 可用前只能是 conformance**：用 CalculiX 镜像 + 固定 audit token + 伪造/其他工具 fixture 验证拒绝判据；`capability` 如实写 `single-execution`，不写成 `software-selection`。
- **fixture 也要有 provenance**：其他工具 fixture 必须记录生成镜像的 `image_sha256`、工具版本、命令与文件 sha256；它是审计证据，不是 pin。
- **P2 验收标准**：判据写入 spec/02；原型题过 P0 审计门（P≥1、A≥2、N≥6、六类、robust 10/10）；L0 + fake smoke；明确记录"未验证真正的工具选择"。
