# 07 · Abaqus 移植指南（从三道已验证的 CalculiX 题到 Abaqus 线）

状态：v0.1（2026-11-18）· 依据：task-0001/0002/0003 的实测 verifier + audit

## 0. 结论先行

五层范式与审计协议**不依赖求解器**，可直接搬；真正要换的只有三样：
1. **工件格式**：CalculiX `.dat` 文本 → Abaqus `.odb` 二进制（+ `.dat`/`.msg` 文本）
2. **重解接口**：`ccx <job>` → `abaqus job=<name> input=<inp> interactive`（或 CAE noGUI 脚本）
3. **数值读取**：文本块解析 → **ODB API**（`odbAccess.openOdb` → steps/frames/fieldOutputs/values）

其余（L1 完整性、L2 设计合规、L3 独立重解、L4 链路一致性、L5 两段式、审计四组）逐条对应。

## 1. 映射表

| VeriCAx 概念 | CalculiX 实现（已验证） | Abaqus 对应 |
|---|---|---|
| 求解命令 | `/usr/bin/ccx solution` | `abaqus job=solution input=solution.inp interactive mp_mode=threads cpus=2` |
| 模型文件 | `solution.inp`（keyword deck） | `solution.inp`（同一语法族，关键字差异见 §3） |
| 结果文本 | `solution.dat`（`*Node Print` 输出） | `solution.dat`（`*Node Print`/`*El Print` 仍有效）+ `.msg` |
| 主要结果工件 | `.dat` / `.frd` | **`.odb`**（field output）；也可保留 `.dat` 作为人工可读旁证 |
| 读结果 | 正则解析文本块 | `odbAccess`：`step.frames[-1].fieldOutputs['U'].values` → `{nodeLabel: (ux,uy,uz)}` |
| 运行环境 | Ubuntu VM，`/usr/bin/ccx` | **Windows VM**（Learning Edition/授权版）+ `abaqus` 在 PATH |
| 单元/截面 | B31 + `*Beam Section, section=RECT` | B31（一致）；实体为 C3D8I/C3D10 |
| 集合 | `*Nset`/`*Elset` + `NSET=`/`ELSET=` | 同名语法；`*Node Print, NSET=` 仍需要显式集合 |
| 许可失败 | 不存在 | `license checkout` 失败 → `error_category=infra_incomplete`，**不得记 0 分**（spec/03 §1） |

## 2. Verifier 骨架（Abaqus ODB，对应 task-0001 的 L1/L2/L3）

```python
# verify.py —— 由 "abaqus python verify.py" 执行（abaqus python 自带 odbAccess）
from odbAccess import openOdb
from pathlib import Path

AGENT = Path(r"C:\Users\user\Desktop")
REQUIRED = ["solution.inp", "solution.odb", "summary.txt"]

def l1():
    for name in REQUIRED:
        p = AGENT / name
        if not p.is_file() or p.stat().st_size == 0:
            raise SystemExit("debug: missing or empty artifact: %s" % name)

def l3_node_displacement(odb_path, step_name, node_label, component=1):
    odb = openOdb(str(odb_path), readOnly=True)
    try:
        step = odb.steps[step_name]
        u = step.frames[-1].fieldOutputs["U"]
        for v in u.values:
            if v.nodeLabel == node_label:
                return v.data[component]      # 0=U1,1=U2,2=U3
        raise ValueError("node %s has no U value" % node_label)
    finally:
        odb.close()

# L3: 独立重解提交的 deck（起 job 并等 .lck 消失后再读 odb）
#   subprocess.run([r"C:\SIMULIA\Commands\abaqus.bat", "job=verify", "input=solution.inp",
#                   "interactive", "ask_delete=OFF"])
# L2: 解析 solution.inp 文本做设计合规（与 CalculiX 版同构，关键字层差异见 §3）
```

要点：`interactive` 保证同步返回；重复运行前删 `verify.lck/verify.odb`；读 ODB 前确认 `steps` 名与任务书一致（建议任务书显式规定 `*Step, name=Step-1`）。

## 3. 关键字层差异（会咬人的）

| 主题 | CalculiX（已验证） | Abaqus | 处理 |
|---|---|---|---|
| 打印请求 | `*Node Print, NSET=` 必带集合；无 `NALL` | `*Node Print, NSET=` 同；`NALL`/`EALL` 可用 | verifier 自行声明集合，别依赖 agent 的命名 |
| beam 应力 | 截面高斯点（≈0.58×外纤维） | `S` 为积分点；`.dat` 可 `*El Print, POSITION=CENTROID` | 同 task-0001 决策：**评分用节点位移/支反力**，不用 beam 应力 |
| 多步 | `*Step` + `*Cload, OP=NEW` | 同语法；`*Boundary, OP=NEW` 亦可 | task-0003 的 L4 比值检查可原样搬 |
| 单位制 | mm/N/MPa | 同（无单位系统，须任务书声明） | 任务书显式写 `mm, N, MPa` |
| 截面 | `*Beam Section, section=RECT` | 相同 | — |
| 求解器选项 | `*Static` 默认 | `*Static` 默认；线程 `cpus=` | 固定 `cpus=2` 减少方差 |
| 结果读取 | 文本 `.dat` | **优先 `.odb`**；`.dat` 仅辅助 | verifier 主路径走 ODB |

## 4. L5 优化题移植（task-0002 → Abaqus）

同构：变量 `a1/a2` 写在 section 数据行；门 = 挠度（ODB 节点 U）+ 外纤维应力（**梁理论自算**，不读 FEA 应力）+ 变量界；分 = `1 - mass/mass_baseline`。
差异只有一处：ODB 读取替代文本解析，其余判据与 task-0002 完全一致（可直接复用其 `outer_fibre_stress` / `mass_of` 公式）。

## 5. 反作弊与沙箱（Abaqus 特有）

- **agent 可以合法读 ODB**（它就是自己产出的工件）——verifier 不因此假阳性；关键是**判据不外泄**：`verify.py` 与 ground truth 只在 episode 结束后注入（spec/02 §3）
- **`.lck` 残留**会让下一次 job 启动失败 → runtime 的 reset 快照必须干净；verifier 起 job 前主动删 `*.lck`
- **许可**：并发 checkpoint 数有限，批量评测必须串行或限并发；采不到许可记 `infra_incomplete`，不污染能力分数
- **破坏性操作**：Abaqus 的 `abaqus job=...` 会写工作目录；快照复位使"故意做坏一次再恢复"的测试安全可行（这是 VeriCAx 相对真实产线的最大解锁）

## 6. 迁移清单（按此顺序落地）

1. 取一台 Abaqus Windows VM，跑通 `abaqus python -c "from odbAccess import *; print('ok')"`
2. 把 task-0001 的 10 单元阶梯梁用 Abaqus deck 重写（关键字几乎逐行可比），生成黄金解，确认 ODB 读数与解析解 -0.3504 mm 对表
3. 写 `verify_abq.py`（§2 骨架），跑 VeriCAx 审计四组（正/替/负/稳健）——**审计不过不发布**
4. 复制 task-0002 的 L5 结构与公式，做 Abaqus 优化题
5. 与 CalculiX 版对比同一设计的得分：若两者的黄金解互相印证（数值差 <1%），说明任务定义无歧义
