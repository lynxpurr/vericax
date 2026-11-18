# 04 · 环境与 Runtime 规格

状态：草案 v0.1（2026-11-18）· 含实测踩坑记录（smoke-test environment_ready 实证）

## 1. 镜像规范（VeriCAx-Images）

| 项 | 规格 |
|---|---|
| 格式 | qcow2 + zstd 压缩（实测 5.47GB 压缩 → 11.7GB 实际 / 50GiB 逻辑盘） |
| 校验 | `manifest.json`（逐镜像 `package_sha256`+字节数）+ 顶层 `SHA256SUMS`；下载器自校验 |
| 命名 | `<Software>-<version>.qcow2.zst`（如 `CalculiX-2.21.qcow2.zst`） |
| 基线 | Ubuntu 24.04 base + 被测软件官方版本 + 桌面环境（GUI 通道需要）+ osworld_server 服务 |
| 分发 | HF org `vericax`（占位未建）+ ModelScope 镜像（国内实测 47s 拉 5.5GB，走 `--source modelscope`，须剥代理变量） |

## 2. 运行时架构

- 容器内 QEMU（KVM 直通），宿主机无需安装 qemu——**osworld-docker 验证过的架构**
- 默认资源：4 vCPU / 16G RAM / 200G 虚拟盘（`ENGIWORLD_DOCKER_*` 式环境变量可覆盖）
- 16C/89G 宿主实测：串行 1 VM 稳；并行 2 VM 理论可行（2×16G），未验证，v0 不支持
- 分辨率 1920×1080，初始化前后校准（GUI 通道）

## 3. 已知部署坑（实测，必读）

| 坑 | 现象 | 解法 |
|---|---|---|
| **KVM 权限** | `/dev/kvm` root:kvm 660 | 测试机上已挂 ACL（`<user>:rw-`）；新机器 `sudo usermod -aG kvm $USER` 或复制 ACL |
| **netfilter legacy 模块** | 容器内 iptables 失败 → QEMU 静默退化 user-mode（只转 22/3389）→ guest 服务端口永不可达 → readiness 300s 超时。现象极迷惑：VM 明明启动到 graphical.target | 载入 `ip_tables iptable_nat iptable_filter iptable_mangle`；持久化：`sudo tee /etc/modules-load.d/vericax-netfilter.conf <<< "ip_tables"`。sudo 不可用时的替代：特权容器 `--entrypoint modprobe` + 挂载解压后的模块树（见调研报告 §6） |
| **pip 安装路径断裂** | 包安装到 site-packages 后相对路径定位 engine 失效 | 源码仓一律 `pip install -e`；或显式 `ENGINE_PATH` 环境变量且代码走 env 优先 |
| **代理计费** | ModelScope/dashscope 国内直连，默认 shell 挂 Clash | 下载/评分进程统一 `unset HTTP_PROXY HTTPS_PROXY ALL_PROXY ...` |

readiness 探测：轮询 `localhost:<port>/screenshot`（10s 超时 ×300s 窗口）；boot-to-ready 实测 177s。

## 4. 通道隔离的 runtime 强制

- CLI：观察=终端输出；动作 bash/python/readimg/wait/fail/done；单动作 120s 墙钟；history 15 轮；max_steps 100（任务包 `limits` 可覆盖）
- GUI（v1）：观察=1920×1080 截图；动作 pyautogui 唯一；AST 白名单校验（spec/02 §2）
- 隔离在 **runtime 解析器层**强制（拒在执行前），system prompt 禁令只是第一道而非唯一一道防线

## 5. Runtime 最小接口（v0 只需这些）

```python
DesktopEnv(provider_name="docker", path_to_vm=<qcow2>, os_type="Ubuntu",
           action_space=..., headless=True, client_password=..., cache_dir=...)
env.reset(task_config=...)   # 注入 init_file
env.close()                  # 快照复位
```
v0 直接复用 EngiWorld runtime（MIT）+ 上述坑位补丁；v1 抽象成 `vericax-runtime` 独立包。

## 6. CalculiX 工件与输出格式（task-0001 实测，写 verifier 必读）

| 事项 | 事实 | 对 spec/02 的影响 |
|---|---|---|
| `.dat` 来源 | 只有 `*Node Print` / `*El Print` 写 `.dat`；`*Node File` / `*El File` 只写 `.frd` | 要求 `.dat` 交付物时，任务书必须说明 print 卡；verifier 应自行注入 |
| 集合要求 | `*Node Print, NSET=...` / `*El Print, ELSET=...` 必须指向已定义集合；`NALL`/`EALL` 是 Abaqus 约定，CalculiX 无 | verifier 注入时自己声明 `*Nset` 覆盖全部 id（见 eval.py `_ensure_output_requests`） |
| 应力语义 | beam 单元应力输出在截面高斯点（方形截面 y≈±0.577·半宽），约为外纤维值的 0.58x | **不要**把 beam 应力作为评分量；用节点位移/支反力等无歧义量 |
| 网格收敛 | 1 单元/段：挠度低 24%；≥10 单元（每 10mm 一个）误差 <1% | 评分量与解析解挂钩时，任务必须规定足够密的网格 |
| 运行 | `ccx <jobname>` 就地写 `<jobname>.dat/.frd/.sta/.cvg`；无 MPI 依赖可直接在 VM 跑 | 参考解必须在同一镜像内生成（跨镜像会漂移） |

**审计教训（写进流程）**：task-0001 首版用 2 单元 + "最大应力"作为评分量，审计正例被解析解带子拒收——审计协议在冻结前抓到的是**题目设计缺陷**，不是代码 bug。这正是 spec/02 §4 存在的理由：先审计 verifier，再发布任务。

## 7. 与外部资产的关系（部署边界）

VeriCAx 不 vendor 运行时与镜像。`scripts/_config.py` 是唯一的解析入口：

| 资产 | 环境变量 | 配置文件 |
|---|---|---|
| runtime（含 `engine/desktop_env`） | `VERICAX_RUNTIME` | `vericax.toml` → `[runtime] path` |
| 镜像目录（含 `<snapshot>.qcow2`） | `VERICAX_IMAGE_DIR`（或单文件 `VERICAX_IMAGE`） | `vericax.toml` → `[images] dir` |

v0 复用 EngiWorld runtime 与其公开镜像；v0.5 起发布自有镜像集（VeriCAx-Images）时，只换配置指向，任务包与 verifier 不受影响。
