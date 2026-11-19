# Research Provenance

> **边界说明**：本文件记录的是*出处引用*，不是本仓内容。研究仓（EngiWorld 实地调研、
> VM 镜像与跑批结果）是**独立的外部工作区**，不在本仓内；下文路径若指向该工作区，
> 属于外部引用，运行时依赖请见 README《仓库边界与外部依赖》。

本仓所有规格决策均可追溯到 2026-11-17/18/19 的 EngiWorld 实地调研，证据链：

| 决策 | 证据 |
|---|---|
| 三资产结构（Tasks/Images/Runtime） | EngiWorld HF 双数据集 + GitHub runtime，实测 ModelScope 47s 拉 5.5GB |
| task.json 字段集 | `engiworld-repo/task/` 实读（单软件 + 设计优化两种 evaluator 形态） |
| 五层 verifier 范式 | verifier 解剖：CalculiX(80行)/FEniCS优化(332行)/OpenFOAM(305行)/跨软件(1205行,47函数) |
| 反作弊规格（AST 校验/stealth 拒绝/通道隔离） | `engine/mm_agents/agent.py::_validate_pyautogui_cdata` + CLI system prompt 实读 |
| 审计协议 | 论文 §verifier audit：96 参考解全收 + 替代解全收 + 21+21 负面全拒 |
| 分数语义与 error 分离 | `local_eval.py`/`runner.py` 实读 + 3 题实测 summary.json |
| 环境规格（KVM ACL/netfilter 坑/177s boot） | 实测 smoke-test（environment_ready） |
| 失败模式设计输入 | t02 假提交（0 字节 dat）/ t03 调试死循环（100 轮 357K reasoning）实测 |
| split 版本化纪律 | EngiWorld main-300/main-306 并存教训 |
| GT 自校验 / 参考 deck 不一致 | 2026-11-18/19 CalculiX 审计：task-05/17/19 的 GT summary 位移比 GT deck 输出小 **8.444x**；task-04 tie 面写错；task-06 压力面写错（研究仓 §11） |
| re-score ≠ rerun | 审计重评分 9/20 vs patched deepseek rerun **8/20**；qwen4 **10/20**；pass-set 差 06/09/07（研究仓 §12、`results/PHASE-B.md`） |
| CLI 工件写入策略 | qwen3.8-flash 21 calls / glm-5.3 18 calls 在 task-01 卡 CGX/CLI policy；qwen4 7 steps 通过（研究仓 Phase B pilot） |
| benchmark repair vs model effect | deepseek 2/20→8/20（+6）；qwen4 10/20（+2：06/09）；同一 patched tree |
| 命名决议 | 联网查重：caX-bench 商标/EngiBench/FleetBench/CADTestBench 等，见 spec/06 |

外部研究仓（本机路径，仅作引用）：调研报告 `engiworld-调研报告.md`（§4 verifier 解剖、§7 三题实测、§8 EngiOps 提案、§9 社区盘点、§10 20 题基线、§11 GT/verifier 审计、§12 Phase B）；实测轨迹 `results/cae-batch/`、`results/PHASE-B.md`、`results/gt-selfcheck/`；研究仓 `develop` commit `e4d512a`。引用这些材料时请注明它们属于研究仓而非本仓。
