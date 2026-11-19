# 03 · 分数语义与结果 Schema

状态：草案 v0.1（2026-11-18）· 字段集源自 EngiWorld `local_eval.py`/`runner.py` 实读 + 3 题/20 题实测 summary.json

## 1. 分数语义

| func | 输出 | 语义 |
|---|---|---|
| `exact_match` | `"True\n"` / `"False\n"` | 执行类题；verifier 内部 L1→L5 全过才 True |
| `quantified_score` | `"0.735"`（6 位小数） | 优化类题；L5 可行性门通过后输出质量分，失败输出 `"0.000000"` |

规则：
- 分数与错误**分离**：分数无效时写 0 并打 `scoring_basis` 标记，绝不把 infra 故障伪装成能力 0 分
- 通道分数永不合并：`cli` 与 `gui` 是两个独立榜（EngiWorld 合成 EngiScore 的做法不采纳——调研结论：通道能力不可加总）
- 单跑方差纪律：排行榜比较必须 n≥3，同时报告均值与极差；单跑结果只能标 `preliminary`
- `agent_error`（agent 非零退出但未到截止，2026-11-18 增补）不是 infra：照常 freeze → score，分数归属 verifier 结论（spec/08 §7/§8）
- **`run_mode` 必填**（2026-11-19 增补）：`rerun` | `rescore`；re-score 只作估计，不得与 rerun 混表；任务树/verifier 变更后必须 rerun。
- **`tree_version` 必填**：任务树/补丁集标识；不同 tree 的结果不可合并（与 spec/01 §3 的 id 迁移纪律一致）。
- **`reference_selfcheck` 必填**：`pass` | `fail` | `not_run`；`fail` 的任务包不得进入榜单（spec/02 L0）。详细记录落 `ground_truth/reference_selfcheck.json`。
- **`kind` 必填**：`capability` | `test` | `debug`；聚合默认只收 `capability`，作弊/回归测试不得移动能力均值。

## 2. summary.json Schema（每次 run 一个）

```jsonc
{
  "task_id": "cae--cli--calculix--task-0001",
  "agent": {"name": "...", "version": "..."},        // ▲ agent 栈标识（VeriCAx 被测对象是栈）
  "model": {"name": "...", "endpoint": "..."},       // ▲ 底座模型单独记录（栈-模型归因）
  "harness": {"name": "...", "version": "..."},      // ▲ harness 标识（归因三件套）
  "score": 1.0,
  "scoring_basis": "native_evaluator",               // native_evaluator | active_time_budget | infra
  "native_evaluator_executed": true,                 // evaluator 真跑了才有资格谈分数
  "error": null,
  "error_category": null,        // environment_error | infra_incomplete | active_time_budget_exhausted
                                 // | api_interruption | agent_stalled | agent_error
                                 // | artifact_write_rejected (proposal, 2026-11-19; spec/09 §9)
                                 // ▲ 前四类继承 EngiWorld，agent_stalled 为 VeriCAx 新增，
                                 //   agent_error 于 2026-11-18 增补（spec/08 §8：agent 非零退出但未到截止）
  "result_dir": "...",
  "artifact_uri": null,          // ▲ 交付物快照存档（复现审计用）；2026-11-18 定形：逐文件副本 +
                                 //   artifacts.json manifest（basename 扁平化 + sha256），tarball 仅作归档
  "cost": {"llm_calls": 148, "prompt_tokens": 2190000, "completion_tokens": 475000,
           "reasoning_tokens": 402000, "usd_estimate": null},   // ▲ token 三分口径实测验证有效
  "wall_duration_seconds": 4658.2,
  "paused_seconds": 0.0,                             // 暂停去重计账（重叠只算一次）
  "active_duration_seconds": 4658.2,
  "active_time_limit_seconds": 18000,
  "split_version": "v0.1-cae-cli-100",               // ▲ 强制回填，杜绝无 split 声明的基线
"tree_version": "calculix-2026-11-18-patched",     // ▲ 任务树/补丁集标识；不同 tree 不可合并
                                                      //   VeriCAx 默认写任务包 manifest 摘要 sha256:<hex>；
                                                      //   跨仓对比可用 --tree-version 覆盖
  "run_mode": "rerun",                               // ▲ rerun | rescore；rescore 只作估计
  "reference_selfcheck": "pass",                     // ▲ pass | fail | not_run（spec/02 L0）
  "kind": "capability",                              // ▲ capability | test | debug；test/debug 不进能力聚合
  "run_index": 1, "run_total": 3                     // ▲ n≥3 纪律的落点
}
```

聚合规则：`report` 默认只统计 `kind=capability`；`test`（作弊/回归）与
`debug`（诊断）单独展示。旧 episode 缺 `kind` 时，`fake` adapter 按 `test`
处理，其余按 `capability` 处理。

## 3. 三级入口（任何评测系统的标准动作，EngiWorld 验证有效）

| 入口 | 做什么 | 不做什么 |
|---|---|---|
| `prepare` | 下载任务包/镜像，逐资源 SHA256 校验 | — |
| `check` | 离线核资源 + 任务定义合法性 | 不起 VM、不调模型 |
| `smoke` | 起/复位 VM、注入 init、截屏存证（`environment_ready`） | 不调模型、不评分 |

## 4. 排行榜发布模板（强制字段）

```
Agent/模型 | split 版本 | tree 版本 | n | 通过率 | 域分(CAE/CAM/...) | 留存率(单软件→跨软件) | $/题 | 活跃时长中位 | 错误分类占比
```

留存率定义：`跨软件题得分 / 同软件单软件基线得分`（EngiWorld 68/64/30/11% 口径的 VeriCAx 版）。

## 5. 复现纪律

每次 run 存档：summary.json + traj.jsonl + llm_calls.jsonl + evaluator_stdout/stderr + 交付物快照（artifact_uri）。实测体积参考：3 题全留档 1.3MB——留存成本低，不设豁免。

- 每次 run 记 `run_mode` 与 `tree_version`；patch 过的任务必须用 patched tree 重跑，不能把旧 run 重评分当 rerun。
- `reference_selfcheck=fail` 的任务包先修；修好后重新审计，不得直接重评分入榜。
- 同一模型/栈的跨 tree 结果不得合并成一条曲线；分开报，注明 `tree_version`。
