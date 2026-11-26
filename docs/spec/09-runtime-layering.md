# 09 · 运行时分层与评分面隔离

状态：**已评审通过 v0.1**（2026-11-18 人类评审通过；D2/D3 已冻结）

## 0. 目标

1. **执行面与评分面物理分离**：agent 能改的东西，评分面看不到；评分面能读的东西，agent 碰不到。
2. **每个 episode 从干净状态开始**：base image 不变，每 run 独立 overlay；n 次 run 不共享 VM、容器、state。
3. **评分可复现**：同一 image、同一 solver 版本、同一 verifier、同一冻结点。
4. **故障不伪装成能力**：infra 错误不计分；只有 verifier 正常返回才产生能力分数。

本 spec 规定拓扑与边界，不规定 `vericax` CLI 的内部实现。Phase 1 先做 tier-1 + 串行；并行与 GUI 留到后续。

## 1. 分层与拓扑

```
宿主 (host)
├─ eval harness (`vericax` CLI)
│    prepare → run → freeze → score → record
│
├─ 执行面
│   ├─ agent 容器（栈 + 模型；无仓库挂载；bridge 网络）
│   │      └── run/put/get ──► proxy（`vericax-sh`，宿主进程）
│   │                                └── controller HTTP ──► sandbox VM（CalculiX）
│   │                                                          └── init + 工件
│   └─ sandbox VM 的转发端口只绑 127.0.0.1；agent 容器不可达
│
├─ 冻结
│   └─ sandbox VM ──► artifact store（`runs/<episode>/artifacts/`，freeze 后只读）
│
└─ 评分面
    └─ scoring 实例（同镜像；无外网）◄── 只读冻结工件 + task package + GT
```

读图要点：

- agent 容器**没有**仓库挂载；它只能通过 `vericax-sh` 触达 sandbox。
- proxy 是宿主进程，持有 runtime 的 controller；它不暴露宿主 shell。
- 冻结工件从 sandbox 流向 artifact store，再只读挂载到 scoring 实例。
- scoring 实例与 agent 容器之间没有网络路径。

## 2. 三层边界

| 层 | 包含 | 可以访问 | 不可以访问 |
|---|---|---|---|
| **执行面** | agent 容器、sandbox VM | instruction、init_file、sandbox 内的工程软件、LLM endpoint | 仓库、`eval.py`、`ground_truth`、scoring 实例、宿主文件系统 |
| **控制面** | proxy（`vericax-sh`） | sandbox controller、工件上传/下载 | 宿主 shell、评分面、agent 的模型凭据 |
| **评分面** | scoring 实例、task package、GT、冻结工件 | 只读工件、task package、solver | agent 容器、sandbox 网络、互联网 |

边界由**部署**保证，不由 prompt 保证。任何"禁止读取"的提示都只是第一道防线。

## 3. Tier 0 / Tier 1

| 维度 | Tier 0 | Tier 1 |
|---|---|---|
| verifier 在哪跑 | sandbox VM 内 | 独立 scoring 实例 |
| agent 是否已停止 | 是（但 VM 共享） | 是，且不可达 |
| verifier/GT 是否在 agent 可达面 | 在（当前 `audit_task.py` 上传到 `/home/user/vericax/eval.py`） | 不在 |
| 后台进程能否干扰评分 | 能 | 不能 |
| 允许用途 | 任务作者调试、黄金脚本审计 | 所有发布的 run、排行榜、对外结果 |
| Phase 1 | 保留（回归用） | **必须实现** |

当前 `audit_task.py` 是 tier-0：它把 `eval.py` 上传到 agent VM 内执行。这对**审计**是可接受的（gold 脚本可信、agent 不在场），但**不能**用于发布结果。Phase 1 的回归要求：tier-0 审计仍全绿，同时同一批任务在 tier-1 下重跑一致。

## 4. Episode 隔离

| 资源 | 生命周期 | 隔离要求 |
|---|---|---|
| base image | 永久只读 | 不修改；记录 `image_sha256` |
| sandbox overlay | 每 episode 一个 | 从 base 派生；episode 结束丢弃 |
| agent 容器 | 每 episode 一个 | 不挂仓库；独立 HOME/state；bridge 网络 |
| proxy 实例 | 每 episode 一个 | 每 episode token；freeze 后关闭 |
| scoring 实例 | 每 episode 一个（Phase 1） | 无网络；只读挂载；结束销毁 |
| artifact store | 每 episode 一个目录 | freeze 后只读；保留用于复现 |
| 日志 | 每 episode | `commands.jsonl`、`agent.stdout/stderr`、`evaluator.stdout/stderr` |

规则：

- **E1** 不跨 episode 复用 sandbox overlay 或 agent 容器。
- **E2** 不跨 episode 复用 agent 的 session/state；`HOME`、`XDG_*`、栈自己的 state dir 都指向本次 episode 的临时目录。
- **E3** artifact store 在 freeze 后不可写；verifier 只能读。
- **E4** scoring 实例不能读 sandbox 的活文件系统；只能读 artifact store 的冻结副本。
- **E5** 清理顺序：杀 agent 进程组 → 关 proxy → 冻结 → 关 sandbox → 销毁 scoring。任何一步失败都记 infra。

## 5. 网络矩阵

| 源 → 目的 | Phase 1 | 说明 |
|---|---|---|
| agent 容器 → LLM endpoint | 允许 | 模型 API；若模型本地则不需要 |
| agent 容器 → proxy | 允许 | Unix socket 或专用 host 端口 |
| agent 容器 → sandbox 转发端口 | **拒绝** | VM 端口绑 127.0.0.1；容器用 bridge；禁 `--network=host` |
| agent 容器 → scoring 实例 | **拒绝** | 无路由；评分在 freeze 后启动 |
| agent 容器 → 宿主其他服务 | **拒绝** | 除 proxy 外不暴露宿主端口 |
| sandbox VM → 互联网 | **拒绝**（默认） | CLI 任务不需要；open-environment 题按任务策略单独开 |
| sandbox VM → 宿主 | **拒绝** | 只允许 controller 的入站请求 |
| proxy → sandbox controller | 允许 | runtime 的 HTTP 通道 |
| scoring 实例 → 互联网 | **拒绝** | verifier 只用标准库 + 官方 API |
| 宿主 → 全部 | 允许 | eval harness 编排 |

实现要点：

- VM 的 22/3389/osworld 端口只绑 `127.0.0.1`；容器不能用 `host.docker.internal` 绕过（该地址指向宿主网关，不是 loopback 绑定）。
- **Phase 1 的实际形态（2026-11-19）**：外部 runtime 仍把端口发布在 `0.0.0.0`，未改 provider；宿主侧用 `scripts/harden_host_input.sh` 的 INPUT 规则拦截 `docker0` → 宿主端口段（5000–5100 / 8006–8100 / 9222–9300 / 8080–8200），容器→宿主控制端被 DROP（实测 curl 超时），宿主→VM 控制通道不受影响。规则不跨重启，需在开机后重放一次。"只绑 127.0.0.1" 仍是理想形态，留待 Provider 侧改动（Phase 2）。
- proxy 优先用 **Unix socket** 挂载进容器；退而求其次用专用 bridge 网络 + 宿主端口，且该端口只对 agent 容器网段开放。
- 所有允许/拒绝都在部署层配置；不依赖 agent 遵守 instruction。

## 6. Proxy（`vericax-sh`）

### 6.1 命令面

| 命令 | 语义 | 备注 |
|---|---|---|
| `vericax-sh run [--cwd DIR] -- CMD...` | 在 sandbox 内执行命令 | 返回 stdout/stderr/exit code；per-command timeout |
| `vericax-sh put LOCAL REMOTE` | agent 容器 → sandbox | 目标必须在允许根内 |
| `vericax-sh get REMOTE LOCAL` | sandbox → agent 容器 | 只读；不允许拉取评分面路径（sandbox 内也没有） |
| `vericax-sh done` | 可选完成信号 | 提前告知 harness；不替代进程退出/截止 |
| `vericax-sh whoami` | 返回 episode/sandbox 元数据 | 调试用 |

### 6.2 语义

- **无持久 shell**：runtime 的 `/run_bash_script` 每次新建临时脚本、新起 bash 进程；`cd`/env 不保留。`--cwd` 每次带上；需要持久状态时用 session wrapper（Phase 1 spike 决定是否值得做）。
- **超时**：单命令默认 120s（task `limits` 可覆盖）；总截止由 `VERICAX_DEADLINE_EPOCH` 强制。
- **输出**：stdout/stderr 分离返回；超过 1 MiB 截断并写完整日志；exit code 原样透传。
- **路径**：`put/get` 只允许 `/home/user`、`/tmp` 下的路径；拒绝 `..` 越界、宿主路径、评分面路径。
- **认证**：每 episode 一个 token；token 只注入 agent 容器；proxy 校验后转发。
- **日志**：`commands.jsonl`，字段 `{ts, episode, verb, cwd, argv, exit, duration_ms, stdout_bytes, stderr_bytes}`；argv 中的 token 脱敏。
- **失败**：proxy 不可达/认证失败 → `infra_incomplete`；命令超时 → 返回超时错误给 agent，不直接判 episode 失败。

### 6.3 不做的事

- 不暴露宿主 shell、宿主文件系统、评分面。
- 不代理 GUI（v1.5 单独设计）。
- 不让 agent 直接调用 runtime 的 controller API。

## 7. Scoring 实例

### 7.1 形态

Phase 1 用**同镜像**启动一个独立 VM（从同一 qcow2 派生；专用评分容器/镜像留到 D5）：

- 只读注入 task package（`eval.py`、`ground_truth/`、`resources.sha256`）；VM 用上传，容器用 bind mount。
- 只读注入冻结工件到 `VERICAX_AGENT_ROOT`。
- 可写：一个临时 scratch 目录（verifier 可重解开）。
- 无外网；只保留 runtime 的 controller 控制通道。
- 环境：`VERICAX_AGENT_ROOT`、`VERICAX_CCX=/usr/bin/ccx`、`VERICAX_TASK_ID`；L6 题另加 `VERICAX_EPISODE_ID`、`VERICAX_CHALLENGE`、`VERICAX_TOOL`（required tool）。merged image 用 task JSON 的 `solver_probes` 记录每个工具的版本，不能只靠一个 `solver_version`。

### 7.2 执行

1. 校验 `resources.sha256`（task package 未被篡改）。
2. 运行 `eval.py`，超时 600s（task 可覆盖）。
3. 读 stdout 第一行作为结论；stderr 的 `debug:` 行写入评分侧日志，不回传 agent。
4. 记录 `evaluator.stdout/stderr`、耗时、verifier sha256。
5. 销毁实例。

### 7.3 确定性

- 同一 episode 的评分只跑一次；要复现就重跑整个 episode，不重跑 verifier 挑结果。
- 记录 `image_sha256`、solver 版本、`resources.sha256` 顶层 hash、`adapter` 版本。
- pinned 参考值必须来自**同一镜像**；切镜像必须重跑审计（见 spec/04 §6）。

## 8. Snapshot 与复位

- base qcow2 只读；每 run 用 `qemu-img create -f qcow2 -b <base> <overlay>`（或 runtime 等价的 snapshot 机制）。
- 启动前检查 overlay 是新建的、base 未被修改。
- readiness 探测沿用 spec/04：轮询截图/健康端点，300s 窗口；boot-to-ready 实测约 177s。
- boot 失败重试一次；连续两次失败 → `environment_error`，中止该批。
- episode 结束后丢弃 overlay；不把 overlay 回滚后复用。
- 如果 runtime 的 `DesktopEnv.close()` 默认会重置到快照，Phase 1 必须**显式**验证 overlay 语义，不能假设。

## 9. 失败模式

| 阶段 | 失败 | `error_category` | 动作 | 是否计分 |
|---|---|---|---|---|
| prepare | image 缺失/损坏 | `infra_incomplete` | 中止 | 否 |
| prepare | VM boot 超时 | `environment_error` | 重试 1 次；仍失败中止 | 否 |
| prepare | proxy 启动失败 | `infra_incomplete` | 中止 | 否 |
| run | agent 崩溃（非零退出） | `agent_error`（提案） | freeze → score | 是（verifier 结论） |
| run | 到截止 | `active_time_budget_exhausted` | 杀进程组 → freeze → 0 | 是（0） |
| run | 模型 API 中断 | `api_interruption` | 停止；按策略重试 | 否 |
| run | sandbox 控制通道失联 | `infra_incomplete` | 确认失联后立即停 agent（首错后 1 分钟内），写 `logs/sandbox-loss.json`，不 freeze | 否 |
| run | CLI policy 拒绝工件写入 | `artifact_write_rejected`（提案） | 记录；不按能力 0 计；可提示换合法生成路径 | 否（verifier 仍可判 False） |
| run | 长循环探测 CGX/格式 | `agent_stalled` | 早停/换策略提示 | verifier 通过则有效；失败则排除 |
| freeze | 工件拉取失败 | `infra_incomplete` | 中止 | 否 |
| freeze | 工件缺失/空 | `null`（L1 失败） | score | 是（0/False） |
| score | scoring 实例启动失败 | `infra_incomplete` | 中止 | 否 |
| score | verifier 超时/崩溃 | `infra_incomplete` | 中止 | 否 |
| record | 落盘失败 | `infra_incomplete` | 中止 | 否 |

原则：**能归因到 agent 的，才计分；能归因到基础设施的，一律不计分。**

**控制通道失联的判定（2026-11-26）**：B2 的 16 次 infra 失败全部是 sandbox 控制通道失联，
首次错误多出现在 agent 开始后几分钟内，而 agent 会继续跑到 deadline（单个 episode 空转
10–27 分钟）。现在 proxy 在一次控制器调用放弃之后启动一次失联确认：先等过 runtime 的
30 秒 fast-fail 窗口（窗口内的探测必然失败，说明不了 VM 状态），再探测一次，探测超时
25 秒；确认后 proxy 对后续请求立即返回 `sandbox_unavailable`，`run_agent` 停掉 agent 容器。
一次失败后恢复的 VM 不算失联。freeze 阶段的 `SandboxUnavailable` 同样记 `infra_incomplete`
并写取证记录；工件缺失或为空仍是 L1 能力失败。

**取证（2026-11-27）**：每个 episode 在 agent 启动前写 `logs/guest-profile.txt`（系统、内核、
init、内存、定时器列表），在 sandbox 关闭前保存 guest 控制台日志 `logs/vm-console.log`
（qemu 的串口输出，含 guest 内核消息）；失联记录另含 VM 进程树的内存峰值、容器 cgroup 的
内存计数和主机的 pressure stall 信息。原因：guest 会自己崩溃——B2 时期遗留的两台 VM 都在
开机约 35 分钟后因 PID 1（systemd）段错误而 kernel panic——而容器一旦删除这些证据就没了。

**批量侧（2026-11-26，spec/11 §3 第 4 条的可执行形式）**：

- `vericax batch` 在首轮跑完后用新 episode 重试 infra 的 job，每个 (task, run_index) 上限
  2 次（`--infra-retries`）；原生分数（含 0.0）永不重试。
- 连续 3 次 infra 结果触发熔断（`--infra-breaker`），未开始的 job 记为 skipped。
- 开跑前做离线预检（manifest、镜像、adapter）：配置错误直接终止，不记 infra、不重试。
- 开跑前后列出已在运行的 VeriCAx VM 容器（只报告，不删除）；`close()` 会重试并确认 VM
  容器已删除，确认不了时写 `logs/leak.json`。被硬杀的 episode 进程不会执行清理，只能靠
  这份清单发现残留。
- 每次发车前等待可用内存（每个在飞 episode 6 GB，`--min-free-mb`；最长等 600 秒，
  `--memory-wait`），等不到就停止 batch。

## 10. Phase 1 实现清单

- [x] `vericax` CLI：`prepare / check / smoke / run / score / report`（2026-11-19）。
- [x] `vericax-sh` 原型：run/put/get/done；token；命令日志；超时（2026-11-19）。
- [x] agent 容器 recipe：无仓库挂载、bridge 网络、独立 state、凭据注入（2026-11-19）。
- [x] sandbox overlay 管理：每 run 新建、结束丢弃（`vericax verify-overlay` 显式验证：标记不跨 boot 持久、base 镜像未变）。
- [x] tier-1 scoring 实例：同镜像、只读挂载、无网络。guest 层 iptables 已实现；2026-11-20/21 的 21 题 L0 与 fake smoke 均记录 sandbox/scoring `network_isolation=true`。宿主层 DOCKER-USER 加固仍留 Phase 2（D3/R1 残余）。
- [x] artifact freeze：扁平化、sha256、`artifacts.json`。
- [x] `summary.json`：三件套归因 + `error_category` + `scoring_basis` + cost + `image_sha256`。
- [x] 回归：现有 3 题 tier-0 审计全绿（7/7、9/9、8/8）；tier-1 gold 一致（True、0.35、True，0003 pins 从 GT 烘焙）。
- [x] 作弊拒绝测试：假 summary、篡改工件、空交付、后台进程（全部 0.0 拒绝；后台写者不改变 tier-1 结论）。
- [x] 静态检查：lifecycle/freeze/score 无 `if stack ==`（`tests/run_acceptance.py` 纯度检查）。

## 11. 待定

- ~~2 VM 并行（Phase 2 先 soak）~~ **soak 已通过（2026-11-19）**：`tests/soak_two_vms.py` 同时启动两台 sandbox VM（各 179s ready，wall 209s），两台均健康、init 注入成功、guest 隔离生效、独立关闭。
- **P4 并发调度已完成（2026-11-22）**：`vericax batch --parallel 2` 用线程池跑 `run_episode`，每个 episode 独立 overlay、agent 容器、proxy socket、cache 与 scoring 实例；`--image SNAPSHOT=PATH` 支持跨镜像批。E5 清理顺序已落实为 **freeze → 关 sandbox → scoring**（此前 scoring 与 sandbox 并行，单 episode 就占 2 台 VM）。验收：两道 fake episode 并行各 1.0，wall 423s（两集串行合计 841s），无 infra/串扰。`MAX_VALIDATED_PARALLEL=2`，更高并发打警告。
- **L6 每 episode challenge 绑定（P4，2026-11-22）**：`episode_challenge` 为 L6 题生成 `VCAX_EP_<16 hex>`；题面的 `{challenge}` 占位符在 `instruction_text` 渲染；agent 容器注入 `VERICAX_CHALLENGE`（**不注入** `VERICAX_TOOL`，选工具是题面能力），scoring 实例注入 `VERICAX_CHALLENGE` + `VERICAX_TOOL`（spec/09 §7.1）；L0/audit 无 env，退回 `provenance.challenge` 固定 token。验收：task-0002 动态 token=1.0；伪造 episode 仍用 audit token=0.0（L6.3 拒绝重放）。5 道 L6 任务 L0 全部重跑通过。
- GUI 通道（v1.5；截图/鼠标键盘与 CLI 分榜）。
- 自建评分镜像（依赖 D5）。
- 远程/云 sandbox（不在 v0/v0.5 范围）。
- Windows/macOS 宿主。
- 是否需要 session wrapper（Phase 1 spike 决定）。
- 版本化工件写入 / `artifact_write_rejected` 分类（EngiWorld CLI integrity policy 实测；spec/08 §11）。