# 任务包模板

复制 `_template/` 为 `tasks/<domain>/<interface>/<software>/task-<NNNN>/` 后填写。

## 填写步骤

1. `task-0000.json` → 重命名并按 spec/01 字段表填写；`id` 规范 `<domain>--<interface>--<software>--task-<NNNN>`
2. `init_file/` → 任务初始资源（会注入 agent 环境）——**不得含任何判据信息**
3. `ground_truth/` → 参考工件 + `audit.md`（审计记录模板见 spec/02 §4）——**永不注入 agent 环境**
4. `eval.py` → 按 spec/02 实现所需层；顶部 `IMPLEMENTS` 声明；L1/L2 必做
5. 打包：`vericax.prepare --task <id>` 生成 `resources.sha256`（覆盖 eval.py 自身）

## 红线（违反 = 任务包发布被拒）

- instruction 不得泄露 verifier 判据细节（可以说"保存为 X 格式"，不能说"我们会校验 Y 值在 Z 区间"）
- ground_truth/eval.py 不得出现在 init_file/
- eval.py 不得硬编码 metric（优化题的 metric 写 task.json `evaluator.metric`）
- 未过审计协议（正/替/负/稳健四组）不得进 split
