# 08 · Agent 接入契约

状态：**已评审通过 v0.1**（2026-11-18 人类评审通过；D1–D5 全部已定，见 §2）

## 0. 设计立场

1. **任何能执行 shell 命令的 agent 栈都能被评测**——不要求它实现某个私有动作协议。
2. **agent 留在沙箱外**——VM 只提供工程软件与文件系统；agent 不进入被测软件所在的操作系统。
3. **instruction 走文件**——不依赖某家栈的对话格式或 system prompt 约定。
4. **终止靠进程退出 + 墙钟**——不依赖某家栈的 `done` 回调。
5. **工件冻结后再评分**——评分面看不到运行中的 agent，agent 也看不到评分面。
6. **契约按 5 家栈设计，Phase 1 只验证 2 家**——设计目标 dsh / pi / opencode / hermes / openclaw；首批实现 dsh + pi。

本 spec 规定的是**接口语义**，不是实现。`vericax-sh` 与 SSH 都只是契约的传输实现；Phase 0 选择前者（D2a）。

## 1. 术语

| 术语 | 含义 |
|---|---|
| **被测栈 (agent stack)** | 被评分的完整执行体：`model` + `agent harness` + `config` 的组合 |
| **agent harness** | 被测栈内部的框架层：工具循环、上下文管理、系统提示、审批、会话状态（dsh / pi / …） |
| **eval harness** | VeriCAx 自己的编排层：`vericax` CLI，负责 prepare/run/freeze/score/record |
| **adapter** | 唯一允许按栈定制的代码/配置：启动命令、配置映射、输出解析、审批开关、状态目录 |
| **sandbox** | 运行被测工程软件的 VM；agent 只能通过 `vericax-sh` 触达 |
| **proxy** | 宿主侧的 `vericax-sh` 服务：把 `run/put/get` 转成 runtime 的 controller 调用 |
| **scoring surface** | 评分实例 + task package + ground_truth；agent 不可达 |
| **artifact snapshot** | freeze 阶段从 sandbox 拉出的工件副本 + sha256 清单；评分只读它 |

### 1.1 归因三件套的语义

spec/03 目前使用 `agent` / `model` / `harness` 三个字段。本 spec 冻结它们的语义；`config_hash` 是可选扩展（需 spec/03 增补）：

| 字段 | 记录什么 | 例 |
|---|---|---|
| `agent` | 被测的 agent 产品/入口 | `dsh`、`pi` |
| `harness` | 该产品内部的框架/版本 | `dsh 0.2.1-rc.5`、`pi 1.4.0` |
| `model` | 底座模型 + endpoint | `deepseek-v4.1` + provider |
| `config_hash`（可选） | 系统提示 / 工具集 / 审批策略的 hash | 12 位 hex |

规则：**分数永远归属于一个栈配置**，不能只写模型名，也不能只写产品名。

## 2. 决策记录

| # | 决定 | 理由 | 影响 |
|---|---|---|---|
| **D1** | Phase 1 验证 dsh + pi；Phase 2 扩到 5 家；契约按 5 家设计 | dsh 是一次性 headless（生命周期基线），pi 有原生 read/bash/edit/write（文件通道风险）；两家覆盖最关键的差异轴 | `spec/08` adapter schema 按 5 家设计；Phase 1 只实现 `adapters/dsh.toml`、`adapters/pi.toml` |
| **D2a** | 沙箱传输用代理 CLI `vericax-sh`，不用 SSH | controller bash 通道已被 `audit_task.py` 实际使用；代理可做超时、日志、路径封禁，后端可换 | `VERICAX_SANDBOX` 是 `vericax-sh` 入口，不是 `ssh://` URL |
| **D2b** | agent 跑隔离容器：不挂仓库、不直连 VM 端口、只暴露代理 | "agent 留宿主"会让它读到 `eval.py`/`ground_truth` 并直连 QEMU 转发端口，评分面分离失效 | Phase 1 需要容器 recipe + 代理 socket/端口 + 凭据注入 |
| **D3** | Phase 1 串行 1 VM；验收 n=3；Phase 2 先 2 VM soak；每 run 独立 qcow2 overlay | spec/04 明确 2 VM 未验证；n≥3 是 spec/03 的发布纪律；overlay 是防串扰/反作弊要求 | `spec/09` 按串行实现；并发留到 Phase 2 |
| **D4** | ✅ 已定（2026-11-18；2026-11-22 更新） | 发布时点：Phase 2 收口后公开代码/spec/任务包（2026-11-22 已公开）；公开榜单按 spec/11 的 n≥3 跑批；商标采用轻量查重、不注册（spec/06 §3），org 占位延后 | 商标/组织动作见 spec/06；不阻塞评测 |
| **D5** | ✅ 已定（2026-11-18） | 镜像策略：v0/v0.5 沿用 EngiWorld 镜像；Phase 1 写构建 recipe 并产出一张自建镜像验证可复现；Phase 2 切换自建镜像并重跑审计（pins 与镜像绑定） | `spec/10` §3 执行；Phase 2 前不动现有 pins |

> **执行状态（2026-11-22）**：P3a/P3b/P3c 三张自建镜像均已验收（CalculiX 2.21、FEniCS 0.10.0.post2、merged cross-solver），并已切换为套件默认镜像——26 个任务包全部重审计、L0 与 snapshot 一一对应（spec/10 §3）。P4 已完成：`vericax batch --parallel 2`（spec/09 §11），E5 清理顺序落实，L6 每 episode challenge token 管道上线。P5 的 opencode/hermes/openclaw adapter 与 phase2 agent 镜像在 2026-11-22 落地，n=1 conformance 见 spec/10 §7。

## 3. Episode 生命周期

```
prepare  →  run  →  freeze  →  score  →  record
```

| 阶段 | 执行者 | 输入 | 输出 | 失败语义 |
|---|---|---|---|---|
| **prepare** | eval harness | task package、image、adapter | 启动 sandbox（新 overlay）、注入 init_file、写 instruction 文件、启动 proxy、启动 agent 容器 | `environment_error` / `infra_incomplete`；不计分 |
| **run** | agent 进程 | `VERICAX_*` env、instruction、sandbox 入口 | agent 的 shell 轨迹、sandbox 内工件 | 截止/崩溃/API 中断；见 §7 |
| **freeze** | eval harness | `artifact_paths` | 工件副本 + `artifacts.json`（sha256/bytes） | 拉取失败 → `infra_incomplete`；文件缺失 → L1 失败（不是 infra） |
| **score** | scoring instance | 冻结工件 + task package | verifier 的一行结论 | verifier 崩溃 → `infra_incomplete`；正常返回 → 分数 |
| **record** | eval harness | 以上全部 | `summary.json` + 日志 + 工件快照 | 落盘失败 → `infra_incomplete` |

### 3.1 不变量

- **I1** agent 进程永远看不到 `eval.py`、`ground_truth/`、`resources.sha256`。
- **I2** agent 环境只注入 instruction、init_file、sandbox 入口、代理凭据。
- **I3** 评分只读 freeze 后的工件副本；不读 sandbox 的活文件系统。
- **I4** agent 的 summary/日志/自述**不作为证据**；verifier 只重开工件。
- **I5** freeze 必须在 score 之前完成；score 期间 agent 进程必须已终止。
- **I6** 截止时间由 eval harness 强制；不依赖 agent 自觉退出。
- **I7** 每个 run 使用独立 overlay、独立 agent 容器、独立 state 目录；n 次 run 不共享状态。

## 4. 环境变量

agent 进程看到的环境变量（最小集）：

| 变量 | 作用域 | 语义 | 必需 |
|---|---|---|---|
| `VERICAX_TASK_ID` | agent 容器 | 任务 id，用于日志/归因 | 是 |
| `VERICAX_EPISODE_ID` | agent 容器 | 本次 episode 的唯一 id | 是 |
| `VERICAX_RUN_INDEX` | agent 容器 | 第几次 run（1-based） | 是 |
| `VERICAX_INSTRUCTION` | agent 容器 | instruction 文件的**本地路径**（只读） | 是 |
| `VERICAX_SANDBOX` | agent 容器 | `vericax-sh` 可执行文件路径 | 是 |
| `VERICAX_SANDBOX_TOKEN` | agent 容器 | 代理凭据；每 episode 轮换 | 是 |
| `VERICAX_DEADLINE_EPOCH` | agent 容器 | UTC Unix 秒；硬截止 | 是 |
| `VERICAX_WORKDIR` | agent 容器（值为 sandbox 路径） | 默认工作目录（如 `/home/user/Desktop`） | 是 |
| `VERICAX_ARTIFACTS` | agent 容器 | `artifact_paths` 的 JSON 数组（机器可读） | 否 |
| `VERICAX_CHALLENGE` | agent 容器（L6 题） | 每 episode 的挑战 token；题面 `{challenge}` 已渲染为同值 | L6 题是 |
| `VERICAX_TOOL` | **仅 scoring 实例** | `provenance.required_tool`；不注入 agent，选工具是题面能力 | L6 题是 |

禁止注入：任何 `VERICAX_EVAL_*`、`VERICAX_GROUND_TRUTH*`、宿主仓库路径、宿主机绝对路径。
`VERICAX_CHALLENGE` 只用于把工件绑定到本次 episode；`VERICAX_TOOL` 只告诉评分面该题要求哪个工具分支。

`VERICAX_DEADLINE_EPOCH` 的语义是**硬截止**：agent 应在此之前自行结束；到点后 eval harness 先 SIGTERM，宽限期后 SIGKILL，并杀掉整个进程组/cgroup。

## 5. Adapter

adapter 是契约中**唯一允许按栈定制**的部分。Phase 1 的目录约定：`adapters/<stack>.toml`。

```toml
name = "dsh"
version = "0.2.1-rc.5"

[launch]
command = ["dsh", "headless", "{instruction}"]   # 或包一层 vericax-launch
instruction = "argv"                             # argv | file | stdin
approval = []                                    # 非交互开关，如 ["--yolo"]
grace_seconds = 10

[sandbox]
shell = "path"                                   # path | config | wrapper
shell_target = "vericax-sh"
file_tools = "disable"                           # disable | proxy | allow_local
working_dir = "/home/user/Desktop"

[output]
format = "text"                                  # text | json
cost_path = null                                 # 如 "usage.total_tokens"
cost_event_types = []                            # 只统计这些事件类型；空 = 所有带 usage 的事件

[state]
dir = ".dsh"                                     # 每 run 用独立 HOME 隔离
```

| 字段 | 作用 |
|---|---|
| `launch.command` | 启动 argv；`{instruction}` 的替换规则见下 |
| `launch.instruction` | instruction 的投递方式：`argv`（替换为文件内容）/ `file`（替换为文件路径）/ `stdin`（从 stdin 灌入） |
| `launch.approval` | 非交互/自动批准开关；不同栈不同，只允许出现在 adapter |
| `launch.grace_seconds` | SIGTERM 到 SIGKILL 的宽限 |
| `sandbox.shell` | 把栈的 shell 工具指向 `vericax-sh` 的方式（PATH / 配置键 / wrapper） |
| `sandbox.file_tools` | 原生 read/write/edit 的处理：禁用、代理到 sandbox、或允许本地写（不推荐） |
| `output.format` / `cost_path` | 输出解析与 token/cost 提取；拿不到就记 `null`。接受的形态：每行一个 JSON 事件（NDJSON），或一个不在独立行上的 JSON 信封（缩进打印，可排在同流的日志行之后，如 openclaw `--json`） |
| `output.cost_granularity` | 一个 usage 事件描述的是一次模型调用（`call`，默认）还是整个会话（`session`，openclaw `--json`）；`session` 时 cost 里的 `max_output_tokens` / `truncated_replies` 记 `null` |
| `output.cost_event_types` | 只在这些事件类型上提取 usage（如 pi 的 `message_end`、dsh 的 `status`）。流式 `message_update` 会重复携带 usage，不过滤会把一次调用计成上百次 `llm_calls` |
| `state.dir` | 每 run 独立状态目录，避免 n 次 run 互相污染 |

`{instruction}` 的替换规则：

- `instruction = "argv"`：`{instruction}` 替换为 instruction 文件的**内容**（harness 负责正确的 shell/argv 转义）。
- `instruction = "file"`：`{instruction}` 替换为 instruction 文件的**路径**。
- `instruction = "stdin"`：命令不出现 `{instruction}`；harness 把内容写入 stdin。

规则：

- **A1** 生命周期、env 注入、freeze、score、record 代码中不得出现 `if stack == ...`。
- **A2** 只允许 adapter 文件按栈不同；新增一家栈 = 新增一个 adapter + 一个 conformance 用例。
- **A3** adapter 必须声明 `file_tools`；`allow_local` 仅用于调试，发布配置不得使用。
- **A4** adapter 的 `name`/`version` 写入 `summary.json` 的 `agent`；`harness` 记录栈内部框架层及其版本（若产品与框架同版本则同值）。
- **A5**（2026-11-28）同一个模型在所有 adapter profile 里声明的上下文窗口和输出上限必须相同（dsh：`contextWindow` / `maxTokens`；openclaw：模型条目的 `contextWindow` / `maxTokens`；opencode：`limit.context` / `limit.output`）。不声明时各栈用自己的默认值，一次回复会被截在不同的长度：B2 里 dsh 声明了 32768，openclaw 落到默认的 8192，之后的校准里 openclaw 的 11 个 0 分有 9 个是一次回复停在这个上限。`tests/test_adapter_profiles.py` 逐模型核对。

## 6. 工件交接与冻结

### 6.1 工件路径

- `artifact_paths` 是 **sandbox 内的绝对路径**（如 `/home/user/Desktop/solution.inp`）。
- 冻结目录按 **basename 扁平化**存放：`artifacts/solution.inp`。task package 的 `artifact_paths` 必须 basename 唯一；重名在 `check` 阶段拒绝。
- 评分实例的 `VERICAX_AGENT_ROOT` 指向冻结目录；`VERICAX_CCX` 指向同镜像的求解器。

### 6.2 freeze 步骤

1. 终止 agent 进程组；确认无子进程存活。
2. 关闭 proxy 入口（不再接受 `run/put/get`）。
3. 对每个 `artifact_path` 做 `stat`；缺失/空文件记录 `present=false`，**不**算 infra 错误。
4. 通过 runtime 的 `get_file` 拉取到 `runs/<episode>/artifacts/`。
5. 计算 sha256 与字节数，写 `artifacts.json`。
6. （可选）打包为 `artifact_uri`，用于复现审计；评分只读解包后的目录。

`artifacts.json` 最小 schema：

```jsonc
{
  "task_id": "cae--cli--calculix--task-0001",
  "episode_id": "...",
  "image_sha256": "...",
  "artifacts": [
    {"path": "/home/user/Desktop/solution.inp", "name": "solution.inp",
     "present": true, "bytes": 1234, "sha256": "..."}
  ]
}
```

### 6.3 符号链接

- freeze 时解析 symlink；目标必须落在允许根（`/home/user`、`/tmp`）内。
- 目标越界 → 该工件记 `present=false` + `reason=symlink_escape`；verifier 按 L1 拒绝。
- 不跟随 symlink 去读宿主或评分面路径。

### 6.4 原生文件工具

- pi 等栈有原生 `read/write/edit` 工具；如果它们写 agent 容器本地，文件**不会**出现在 sandbox，freeze 时缺失，L1 失败。
- Phase 1 默认 `file_tools = "disable"`：agent 必须用 shell + `vericax-sh` 在 sandbox 内产出工件。
- 若某栈必须保留原生工具，adapter 可设 `"proxy"`，把写操作映射为 `vericax-sh put`；这属于 adapter 实现，不进契约。
- instruction 必须明确：交付物必须落在 sandbox 的 `artifact_paths`。

## 7. 终止语义

| 条件 | 处理 | `error_category` | `scoring_basis` | 分数 |
|---|---|---|---|---|
| agent 在截止前 exit 0 | freeze → score | `null` | `native_evaluator` | verifier 结论 |
| agent 在截止前 exit ≠0 | freeze → score | `agent_error`（提案，见 §8） | `native_evaluator` | verifier 结论 |
| 到截止时间 | 杀进程组 → freeze | `active_time_budget_exhausted` | `active_time_budget` | `0` |
| 运行时判定无进展 | 早停 → freeze → score | `agent_stalled` | `native_evaluator` | verifier 结论；若失败，聚合时排除 |
| 模型 API 中断 | 停止 → 记录 | `api_interruption` | `infra` | 不计分；按策略重试 |
| sandbox/proxy/评分实例故障 | 停止 → 记录 | `environment_error` / `infra_incomplete` | `infra` | 不计分 |

补充：

- `vericax-sh done` 是**可选**的提前完成信号；harness 仍以进程退出或截止为准。
- 杀进程必须覆盖整个进程组/cgroup；只杀父进程会让后台子进程继续写工件或干扰评分。
- 截止后不再接受 `put/get`；freeze 只读已有文件。

## 8. 错误分类与计分基础（与 spec/03 对齐）

spec/03 当前枚举：`environment_error | infra_incomplete | active_time_budget_exhausted | api_interruption | agent_stalled`。

本 spec 提出一个**待 spec/03 增补**的枚举 `agent_error`，用于"agent 非零退出但未到截止"的崩溃场景；在 spec/03 更新前，用 `error_category=agent_stalled` + `error="exit_nonzero"` 兜底，且不得静默改变聚合口径。

原则：

- **infra 故障不是 0 分**：`environment_error` / `infra_incomplete` / `api_interruption` 一律不计分，不进入能力聚合。
- **能力失败是 0 分**：正常跑完但 verifier 判 False/0，属于能力结果，不是 infra。
- **agent_stalled**：verifier 通过则分数有效（工件已交付）；verifier 失败则记录 `agent_stalled` 并在聚合中排除，避免把"卡死"伪装成"能力 0"。
- **active_time_budget_exhausted**：按 spec/03 记 0，`scoring_basis=active_time_budget`；不跑 verifier 作为分数依据（可跑诊断，但不计分）。

## 9. 反作弊边界（契约层）

| 威胁 | 契约层对策 |
|---|---|
| agent 读 verifier/GT | 容器不挂仓库；评分面在独立实例；VM 内不放 `eval.py`/`ground_truth` |
| agent 绕过 proxy 直连 VM | VM 端口绑定 127.0.0.1；容器用 bridge 网络；禁止 `--network=host` |
| agent 在宿主执行命令 | proxy 只实现 VM 内 `run` 与 `put/get`，不暴露宿主 shell |
| agent 用原生文件工具伪造"交付" | `file_tools=disable/proxy`；freeze 只认 sandbox 内的 `artifact_paths` |
| agent 用 shell 覆盖最终工件 | CLI integrity policy 拒绝写入/覆盖；最终工件必须由应用生成（spec/02 §2） |
| agent 留后台进程干扰评分 | freeze 前杀进程组；评分在独立实例、独立网络 |
| agent 用符号链接越界 | freeze 解析 symlink 并拒绝越界目标 |
| agent 伪造 summary | summary 不作为证据；只读工件；L1–L5 verifier 重开/重算 |
| agent 枚举 verifier 规则 | verifier 失败原因只写评分侧日志；agent 侧只看到统一失败（spec/02 §2） |

更细的 verifier 级反作弊见 spec/02 §2；本 spec 只负责**运行边界**。

## 10. 一致性验收（Phase 1）

契约通用性 = 换 adapter 后不改契约/评测 harness 仍能跑通。Phase 1 验收：

1. ✅ **脚本化假 agent × 3 题**（2026-11-19）：0001=1.0、0002=0.35、0003=1.0，全部经 tier-1 verifier。
2. ✅ **dsh × task-0001 × n=3**（2026-11-19）：score=1.0 / 1.0 / 1.0，经 tier-1；三件套归因完整（dsh 0.2.1-rc.5 / deepseek-v4.1-flash-1017 @ Bailian Token Plan）；prompt tokens 26k/28k/23k；活跃 60–70s/集。
3. ✅ **pi × task-0001 × n=1**（2026-11-19）：score=1.0，活跃 102s，三件套归因完整，cost 从 stderr NDJSON 提取；原生 write/edit 工具被 adapter 禁用，工件全部经 sandbox 产出。
4. ✅ **作弊提交全拒**：空交付 / 假 summary / 篡改 summary 均 0.0；VM 内后台写者不改变 tier-1 结论（1.0 vs 1.0）。
5. ✅ **静态检查**：lifecycle/freeze/score 路径无 `if stack ==`。
6. ✅ **opencode 1.19.5 × task-0001 × n=1**（2026-11-22）：score=1.0，active 10s，cost 5 calls（prompt 3,243 / completion 1,084），经 tier-1；容器镜像 `vericax-agent:phase2`。
7. ✅ **hermes 0.21.6 × task-0001 × n=1**（2026-11-22）：score=1.0，active 108s，cost `null`（usage 写容器内文件），经 tier-1。
8. ✅ **openclaw 2026.9.9 × task-0001 × n=1**（2026-11-22）：score=1.0，active 22s，cost `null`（usage 信封在 stderr 混合流），经 tier-1。

三栈均记录 sandbox/scoring `network_isolation=true`，三件套归因完整；conformance 记录为 `kind=test`，不进入能力聚合。Phase 2 加这三家栈只新增 adapter/配置/镜像，未改生命周期契约（A1 纯度检查通过）。

Phase 2 加 opencode/hermes/openclaw 时，预期**只新增 adapter 和 conformance 用例**，不改契约。

## 11. 待定与开放问题

- ~~`agent_error` 是否加入 spec/03 的 `error_category` 枚举~~ **已定（2026-11-18 评审）：加入**；spec/03 §2 已增补。
- ~~`vericax-sh` 是否需要 session wrapper~~ **Phase 1 spike 结论（2026-11-19）：不起持久进程**。proxy 在每条 run 的命令后追加哨兵捕获最终 `pwd`，下一条命令在捕获的目录中启动——`cd` 语义跨调用保留，环境变量不保留（需 per-command inline）。实测 pi × task-0001 通过该通道完成交付。
- ~~代理认证：Unix socket vs 每 episode token~~ **已定（2026-11-18 评审）：两者都用**——Unix socket 限定可达面，每 episode token 防同容器/网段内伪造；与 spec/09 §5 一致。
- ~~`artifact_uri` 的形态~~ **已定（2026-11-18 评审）：逐文件 + `artifacts.json` manifest**；tarball 仅用于复现归档，评分只读解包目录。
- 多 run 状态隔离的具体目录布局（HOME/config/session）。
- **CLI artifact-write policy / one-shot recovery（2026-11-19 新增）**：runtime 拒绝直接写入/覆盖 scored artifact；首次 deck 写错后不能简单重写，agent 可能转向 CGX/格式探测长循环。EngiWorld 实测 qwen3.8-flash（21 calls）与 glm-5.3（18 calls）在 task-01 未收敛；qwen4 一次写对后 7 步通过。待定：允许版本化输入（`beam.v2.inp`）再由应用生成最终工件，还是保持 first-write-wins；前者影响反作弊/复现语义。当前不改契约。
- Windows/macOS 宿主支持不在 v0 范围。