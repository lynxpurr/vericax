# 01 · 任务包 Schema

状态：草案 v0.1（2026-11-18）· 字段集源自 EngiWorld 实读结构，扩展处标注 ▲

## 1. 任务包目录形态

```
tasks/<domain>/<interface>/<software>/task-<NNNN>/
├── task-<NNNN>.json        # 任务定义（下方字段表）
├── eval.py                 # verifier（带外执行，见 spec/02 §3）
├── init_file/              # 任务初始资源（注入 agent 环境）
├── ground_truth/           # 参考工件（仅评分侧可达，永不下发 agent）
└── resources.sha256        # 本包全部资源清单（▲ 强制，EngiWorld 为全局 manifest，我们包级自包含）
```

## 2. task.json 字段表

```jsonc
{
  "id": "cae--cli--calculix--task-0001",          // ▲ 规范化 id：<domain>--<interface>--<software>--task-<NNNN>
  "schema_version": "0.1",                        // ▲ 本 schema 版本（迁移须配 id-migration 文件，EngiWorld 2026-10-09 先例）
  "snapshot": "CalculiX-2.21",                    // 对应 VeriCAx-Images 镜像名
  "interface": "cli",                             // ▲ 通道，首公民字段（EngiWorld 隐含在目录路径）
  "instruction": "...",                            // 面向 agent 的任务书；不得泄露 verifier 判据细节
  "source": "...",                                 // 题目来源（改编出处/原创）
  "config": [ {"type": "upload_file", "parameters": {"files": [{"local_path": "...", "path": "..."}]}} ],
  "artifact_paths": ["/home/user/Desktop/beam.inp", "..."],   // 交付物清单（L1 校验对象）
  "integrity_policy": {                            // ▲ 通道完整性规则（生成 system prompt 的"禁令"段）
    "native_interface_only": true,                 // 工件必须经被测软件官方接口产出
    "allow_native_deck_edit": true,                // 原生 driver 文件（.inp/.foam/.scad）可文本编辑
    "forbid_gui_control": true,                    // CLI 题禁 GUI 操控
    "forbid_third_party_imports": ["numpy", "scipy"],  // 除官方 API/PIL 外
    "forbid_read": ["ground_truth", "evaluator"]   // agent 可达面封禁清单
  },
  "evaluator": {
    "func": "exact_match",                         // exact_match | quantified_score（两段式）
    "postconfig": [ /* 将 eval.py 注入评分环境（非 agent 环境） */ ],
    "result": {"type": "vm_command_line", "command": "python3 /scoring/eval.py", "shell": "true"},
    "expected": {"type": "rule", "rules": {"expected": "True\n"}},
    "metric": {                                    // func=quantified_score 时必填
      "name": "normalized compliance improvement",
      "baseline_score": 0.272613,
      "direction": "maximize",
      "output_field": "score"
    }
  },
  "limits": {"cli_max_steps": 100, "gui_max_steps": null, "active_time_seconds": 18000},  // ▲ 收进任务包（EngiWorld 放全局 profile）
  "solver_probe": "ccx -v 2>&1 | head -2",         // ▲ 可选：评分前记录求解器版本的命令（缺省按 CalculiX）
  "solver_probes": {                               // ▲ merged image 时按工具给 probe（L6.4）
    "calculix": "ccx -v 2>&1 | head -2",
    "fenics": "python3 -c 'import dolfinx;print(dolfinx.__version__)'"
  },
  "provenance": {                                  // ▲ L6 题必填（spec/02 §1 L6；software-selection 强制）
    "required_tool": "calculix",
    "native_model": "solution.inp",
    "native_result": "solution.dat",
    "challenge": "VCAX_<token>",                   // 审计用固定 token；生产按 episode 生成
                                                   // 题面用 {challenge} 占位符；agent 收到 VERICAX_CHALLENGE
    "rerun_tolerance": 1.0e-4,
    "reject_native_families": [".xdmf", ".h5", ".vtu", ".odb", ".rst"]
  },
  "related_apps": ["calculix"],
  "splits": ["v0.1-cae-cli-100"],                  // ▲ 所属 split（版本化，见 §3）
  "possibility_of_env_change": "low"
}
```

`integrity_policy.allow_native_deck_edit` 是**通道声明**而非信任假设（2026-11-22 正式确认）：
`true` 允许 agent 文本编辑原生 driver 文件，但评分工件仍须由 verifier 用提交的 deck
独立重跑产生/复核（spec/02 §2）；`false` 用于没有可编辑原生 deck 的交付形态
（cross-solver task-0003/0004 的 XDMF/HDF5）。harness 不据此改变运行时行为。

## 3. Split 纪律（EngiWorld main-300/main-306 并存教训）

- 每个 split 是一个版本化文件：`splits/v0.1-cae-cli-100.txt`，一行一个任务 id，**永不原地修改**——修订生成新版本号
- 发布任何基线/排行榜结果必须同时声明：split 版本 + 每题 run 次数 n + 模型/agent 版本 + 成本口径
- 同一任务版本迁移（改题/改 verifier）→ 新 id + `id-migration-<date>.json`，旧结果与新结果不可直接合并

## 4. 难度与类型标注（▲，供留存率分析）

可选字段 `capability`：`single-execution | design-optimization | cross-stage-consistency | software-selection | observation-reconstruct | open-environment`（spec/10 §1 的六类；`cross-software` 保留为 v1 跨软件扩展，不并入）。
对齐调研报告 §8.2 的六域映射，用于计算"单软件→跨软件留存率"（EngiWorld 68/64/30/11% 的 VeriCAx 版）。

## 5. 打包与校验流程

1. 产出任务包 → `vericax.prepare --task <id>` 计算包级 `resources.sha256`
2. `vericax.check --task <id>` 离线核验（无网络）
3. `vericax.smoke --task <id>` 环境就绪测试（不调用模型、不评分）
4. 发布前必须通过 spec/02 §4 审计协议，审计记录写入 `ground_truth/audit.md`（评分侧文件）
