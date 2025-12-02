## Windows 11 WSL 2 安装与配置指南

> 参考资料：https://learn.microsoft.com/windows/wsl/install

### 1. 系统要求

- Windows 11（或 Windows 10 版本 ≥ 2004，内部版本 ≥ 19041）。
- BIOS/UEFI 已启用虚拟化（Intel VT-x / AMD-V）。如未启用，请进入 BIOS/UEFI 开启 Virtualization 相关选项并保存。

### 2. 以管理员身份打开终端

在开始菜单搜索 “PowerShell” 或 “Windows Terminal”，右键选择 **以管理员身份运行**。

### 3. 一键安装 WSL（含默认 Ubuntu）

```powershell
wsl --install
```

- 自动启用 `VirtualMachinePlatform` 与 `Microsoft-Windows-Subsystem-Linux` 组件、下载 Linux 内核并安装 Ubuntu。
- 安装结束后若提示重启，请立即重启。

### 4. 首次启动并创建 Linux 账户

重启后第一次打开 WSL，会进入 Ubuntu 初始化流程，按提示设置新的 UNIX 用户名和密码（可与 Windows 账号不同）。

### 5. 选择或更换发行版（可选）

查看可安装的发行版：

```powershell
wsl --list --online
```

安装特定发行版（示例 Debian）：

```powershell
wsl --install -d Debian
```

查看本机已装发行版与默认项：

```powershell
wsl --list --verbose
```

切换默认发行版：

```powershell
wsl --set-default <发行版名称>
```

### 6. 确认或升级到 WSL 2

检查发行版所用版本：

```powershell
wsl --list --verbose
```

若仍是 WSL 1，可升级：

```powershell
wsl --set-version <发行版名称> 2
```

### 7. 更新 Linux 内核（如提示）

执行：

```powershell
wsl --update
```

建议随后重启 WSL：

```powershell
wsl --shutdown
```

### 8. WSLg（可选 GUI 支持）

Windows 11 已默认集成 WSLg，只需保持系统更新即可获得 GUI 支持。

### 9. 访问 WSL 文件系统

- 在资源管理器地址栏输入 `\\wsl$` 可直接打开 Linux 文件。
- 建议在 Linux 目录（如 `~/projects`）内操作，避免跨平台权限问题。

### 10. 在 WSL 内安装 DeepAnalyze 环境

进入 Ubuntu 终端后，参考 README 执行：

```bash
conda create -n deepanalyze python=3.12 -y
conda activate deepanalyze
pip install -r requirements.txt
```

这样可获得 Linux + CUDA 兼容的运行环境。

完成以上 10 步后，即可在 Ubuntu 终端中 clone DeepAnalyze 仓库、安装依赖并部署 vLLM/DeepAnalyze 服务。

---

## 已有 docker-desktop WSL 的补充说明

执行 `wsl --list --verbose` 的结果：

```text
NAME              STATE           VERSION
* docker-desktop    Running         2
```

- 说明系统已支持 WSL 2，但 `docker-desktop` 仅供 Docker 使用，不适合部署 DeepAnalyze。
- 需额外安装常规发行版（如 Ubuntu），所有 DeepAnalyze 操作在该发行版内进行。

### 1. 安装 Linux 发行版

- 再次确认可选列表：
  ```powershell
  wsl --list --online
  ```
- 安装 Ubuntu：
  ```powershell
  wsl --install -d Ubuntu
  ```
- 建议指定 LTS 版本（如 22.04）：
  ```powershell
  wsl --install -d Ubuntu-22.04
  ```

### 2. 首次启动并设置账户

- 打开 “Ubuntu” 应用，按提示设置 Linux 用户名/密码（示例 `tdz/tdz`）。
- 示例网络信息：`IPv4 address for eth0: 172.23.6.173`。

### 3. WSL 与 GUI 相关说明

- WSL 默认提供 CLI，这是正常现象。
- Windows 11 自带 WSLg，可直接运行 `gedit`、`nautilus` 等 GUI 应用。
- 若需要完整桌面，可安装轻量桌面 + XRDP/VNC；但 DeepAnalyze 仅需终端。
- 结论：在 Ubuntu 终端按 README 完成安装即可，如确有 GUI 需求再扩展配置。

### 4. WSL ping Windows 失败（防火墙 ICMP）

- 通过 `ifconfig` 获取 WSL IP（如 172.23.6.173），默认 “Hyper-V firewall” 走 Public 配置。
- 若 Public 配置禁用 “File and Printer Sharing (Echo Request - ICMPv4-In)” 规则，Ping 会被阻断。
- 解决：在 “Windows Defender 防火墙 → 高级设置 → 入站规则” 中启用该 ICMP 规则的 Public 配置。

### 5. 确认版本与默认发行版（可选）

- 再次检查：
  ```powershell
  wsl --list --verbose
  ```
- 若存在多个发行版，可执行：
  ```powershell
  wsl --set-default Ubuntu
  ```

### 6. 更新并准备开发环境

- 在 Ubuntu 终端执行：
  ```bash
  sudo apt update && sudo apt upgrade -y
  sudo apt install git build-essential -y
  ```
- 之后参考 README 创建 Conda 环境并 `pip install -r requirements.txt`，即可部署 DeepAnalyze 与 vLLM。

### 7. 允许局域网/WSL 访问

- 在代理软件（Clash、V2RayN 等）中勾选 “Allow LAN / 允许局域网连接”。
- 在 WSL 中设置代理：
  ```bash
  export http_proxy=http://172.23.0.1:7890
  export https_proxy=http://172.23.0.1:7890
  export all_proxy=socks5://172.23.0.1:7890
  ```
- 如需持久化，将上述命令追加到 `~/.bashrc` 或 `~/.zshrc`：
  ```bash
  echo 'export http_proxy=http://172.23.0.1:7890' >> ~/.bashrc
  echo 'export https_proxy=http://172.23.0.1:7890' >> ~/.bashrc
  echo 'export all_proxy=socks5://172.23.0.1:7890' >> ~/.bashrc
  source ~/.bashrc
  ```

### 8. 下载模型

- 登录 Hugging Face：`hf auth login`（粘贴 token）。
- 下载权重：
  ```bash
  hf download RUC-DataLab/DeepAnalyze-8B --local-dir ~/models/DeepAnalyze-8B
  ```

### 9. 启动服务

- 启动 vLLM：
  ```bash
  vllm serve ~/models/DeepAnalyze-8B --host 0.0.0.0 --port 8000
  ```
- 按 README @README.md#47-205 启动 API/WebUI 或 CLI，测试链路。

### 日志里的根本错误是 “Failed to find C compiler”。也就是说当前 WSL 环境还没有可用的 gcc/g++，所以 Triton 无法编译内核。请按下面步骤处理：

`vllm` 在加载 DeepAnalyze-8B 时需要用 Triton/torch.compile 生成 CUDA kernel，日志里的根本错误是 “**Failed to find C compiler**”。也就是说当前 WSL 环境还没有可用的 `gcc`/`g++`，所以 Triton 无法编译内核。请按下面步骤处理：

1. **安装编译工具链**  
   ```bash
   sudo apt update
   sudo apt install -y build-essential
   ```
   这会安装 `gcc`, `g++`, `make` 等。安装完务必确认：
   ```bash
   gcc --version
   which gcc
   ```
   若输出正常，则编译器已就绪。@wsl安装指南.md#134-167 也提醒过此步骤，可作为参考。

2. **（如有多版本 gcc）显式指定 CC**  
   如果你安装了多个编译器，可在启动 vLLM 之前加上：
   ```bash
   export CC=/usr/bin/gcc
   export CXX=/usr/bin/g++
   ```
   确保指向刚安装的 gcc/g++。

3. **重新启动 vLLM**  
   退出之前的 vLLM 进程（若仍在运行可 `Ctrl+C`），然后再次执行：
   ```bash
   vllm serve ~/models/DeepAnalyze-8B --host 0.0.0.0 --port 8000
   ```
   首次编译仍会花一点时间，但不会再因缺少 C 编译器而失败。

4. **可忽略的告警**  
   - `pin_memory=False`：WSL 环境下默认设置，仅影响性能。  
   - `torch-c-dlpack-ext`：可选组件，若想消除提示可 `pip install torch-c-dlpack-ext`。  
   - `Not enough SMs to use max_autotune_gemm`：显卡 SM 数较少时的提示，不影响运行。  

完成以上步骤后，vLLM 应能顺利加载模型并对外提供 8000 端口的 API。若仍有报错，请提供新的日志。

### 根据最新日志，当前 16 GB 显卡连模型本体都快放不下（启动时只剩 14.57 GiB 空闲，却想保留 0.95×16 GiB≈15.12 GiB 给 vLLM），因此还没进入 KV cache 初始化就被拒绝。要在 16 GB 上勉强跑 DeepAnalyze-8B，需要进一步牺牲上下文、并发甚至把 KV cache 部分放到 CPU。可按优先级尝试：

1. **减小 GPU 预留比例**  
   - 改用 0.8 甚至 0.75：  
     ```bash
  vllm serve ~/models/DeepAnalyze-8B \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.65 \
  --max-model-len 1024 \
  --max-num-batched-tokens 128 \
  --max-num-seqs 1 --swap-space 8
     ```
   - `--max-num-seqs 1` 强制单会话，进一步压缩缓存。

2. **启用 CPU Swap（迁移部分 KV cache 到内存）**  
   - 例如再加 `--swap-space 8`（单位 GiB）：  
     ```bash
     ... --swap-space 8
     ```
   - CPU 内存够用的话可调更大，但延迟会明显升高。

3. **清理显卡占用**  
   - 启动前运行 `nvidia-smi`，确保没有其他进程占用显存；必要时 `sudo fuser -v /dev/nvidia*` 查出进程并关闭。

4. **考虑量化或更大显存设备**  
   - 16 GB 对 FP16/bfloat16 的 8B 模型实在吃紧。如果允许，改用 24 GB+ GPU、或寻找 AWQ/GPTQ 等量化权重会更可靠。

5. **可选：安装 `torch-c-dlpack-ext` 并保持 `max-model-len` 更低（如 1024）**  
   - ```bash
     pip install torch-c-dlpack-ext
     ```
   - 这有助于内存复用，但不是决定性因素。

以上参数调整后，再次运行 `vllm serve`。若仍失败，请附带 `nvidia-smi` 输出和最新日志，我再帮你进一步分析。

### 当前硬件的最终结论

- 经过多轮调参（`--gpu-memory-utilization`、`--max-model-len`、`--max-num-batched-tokens`、`--max-num-seqs`、`--swap-space` 等）后，16 GB 显卡在未量化的情况下仍无法为 DeepAnalyze-8B 的 KV Cache 提供足够显存，启动最终都会因 `Available KV cache memory < 0` 而失败。
- 可行的替代路径：
  1. 使用更小/量化版本的模型（如官方后续提供的 AWQ/GPTQ 版本，或暂时换 7B/4B 级模型）。
  2. 在具备 24 GB 以上显存的 GPU 上运行（本地或云端实例），再通过 API 与 DeepAnalyze 对接。
  3. 若需要继续探索，可将推理部署在远程 GPU 资源上，本地仅负责调用 API。
  4. 保留现有配置记录，待硬件升级或拿到量化权重后，复用当前步骤重新尝试。

### 要快速“走通流程”，你可以用任意开源 7B 左右的指令模型来替代 DeepAnalyze-8B，只要它在 README 里提到的 vLLM 模型接口兼容即可。推荐思路如下：

1. **选择兼容的 7B 指令模型**  
   - 例如 `Qwen2.5-7B-Instruct`、`Llama-3.1-8B-Instruct`（8B 但显存需求略低）、`Yi-1.5-6B-Chat`、`Mistral-7B-Instruct-v0.3` 等，Hugging Face 上都可直接 `hf download`。这些模型和 DeepAnalyze-8B 一样属于 decoder-only、支持 OpenAI Chat 接口，替换成本低。  
   - 下载方式与之前一致：  
     ```bash
     hf download Qwen/Qwen2.5-3B-Instruct --local-dir ~/models/qwen2.5-3b-instruct
     ```

2. **用相同的 vLLM 命令启动，但换模型路径**  
   - 假设你选的是 Qwen2.5-3B：  
     ```bash
     vllm serve ~/models/qwen2.5-3b-instruct \
       --host 0.0.0.0 --port 8000 \
       --trust-remote-code
     ```  
   - 7B 模型在 16 GB 显卡上通常不需要额外的 `--max-model-len`/`--swap-space` 调整，所以可以保持默认配置，验证流程更简单。

3. **保持 API 层与 README 流程一致**  
   - 启动 DeepAnalyze 的 API、前端、示例脚本时，仍按 README @README.md#47-205 的顺序操作，只是模型端换成了临时 7B 权重。这样可以确认 API 调度、任务解析、文件上传等功能都运转正常。

4. **记录替代方案**  
   - 在文档（如 `wsl安装指南.md`）中说明：测试阶段使用某个 7B 模型，通过 vLLM + DeepAnalyze API 已走通流程；待获取大显存或量化版本后，再切回官方 DeepAnalyze-8B。

这样做可以先验证“流程通”“接口通”，后续再切换回 DeepAnalyze-8B 时只需改模型路径即可。不需要额外的代码改动。

#### 可在 16 GB 显卡上运行的 Qwen 模型清单

| 模型 | 参数规模 | 说明 |
| --- | --- | --- |
| `Qwen/Qwen2.5-0.5B-Instruct` | 0.5B | 占用极低，适合最小化流程验证。 |
| `Qwen/Qwen2.5-1.5B-Instruct` | 1.5B | 性能与显存平衡，16 GB 轻松运行。 |
| `Qwen/Qwen2.5-3B-Instruct` | 3B | 约 10–12 GB 显存即可，适合中等规模测试。 |
| `Qwen/Qwen2.5-7B-Instruct` | 7B | 在 16 GB 上可运行，建议适度降低 `max_model_len`。 |
| `Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4` | 7B INT4 | 官方量化版，显存 8–10 GB 即可，需要 `--quantization gptq`。 |
| `Qwen/Qwen1.5-4B-Chat` | 4B | 旧版 Chat 模型，显存余量更大。 |
| `Qwen/Qwen1.5-1.8B-Chat` | 1.8B | 低显存占用，适合脚本化验证。 |
| `Qwen/Qwen1.5-7B-Chat` / `Qwen/Qwen2-7B-Instruct` | 7B | 经典 7B 版本，可作为 Qwen2.5 的替代。 |

> 以上显存估算基于 FP16/bfloat16，全精度运行时可按照 README 流程直接部署；若使用量化权重，需在 vLLM 命令中添加对应 `--quantization` 参数。

### 编译器缺失：Failed to find C compiler

`vllm` 在加载 DeepAnalyze-8B 时需要 Triton/torch.compile 生成 CUDA kernel，若日志提示 “Failed to find C compiler”，说明当前 WSL 环境没有可用的 `gcc/g++`。处理步骤：

1. **安装编译工具链**
   ```bash
   sudo apt update
   sudo apt install -y build-essential
   ```
   安装后确认：
   ```bash
   gcc --version
   which gcc
   ```
2. **如有多个 gcc 版本，显式指定**
   ```bash
   export CC=/usr/bin/gcc
   export CXX=/usr/bin/g++
   ```
3. **重新启动 vLLM**
   ```bash
   vllm serve ~/models/DeepAnalyze-8B --host 0.0.0.0 --port 8000
   ```
4. **可忽略的常见告警**
   - `pin_memory=False`：WSL 默认设置，仅影响性能。
   - `torch-c-dlpack-ext`：可选组件，若要消除警告可 `pip install torch-c-dlpack-ext`。
   - `Not enough SMs to use max_autotune_gemm`：显卡 SM 较少时的提示，不影响运行。

完成以上步骤后，vLLM 应能顺利加载模型并提供 8000 端口的 API。

### KV Cache 显存不足：Available KV cache memory < 0

若日志出现 `Available KV cache memory: -1.60 GiB` 并抛出 `ValueError: No available memory for the cache blocks`，说明 8B 模型几乎耗尽显存，需要压缩 KV Cache：

1. **调低 KV Cache 占用**
   ```bash
   vllm serve ~/models/DeepAnalyze-8B \
     --host 0.0.0.0 --port 8000 \
     --gpu-memory-utilization 0.7 \
     --max-model-len 4096
   ```
   可根据显卡从 0.6~0.7 试起。
2. **降低最大上下文长度**：将 `--max-model-len` 设为 4k/8k/16k。
3. **限制并发 token 数**：如 `--max-num-batched-tokens 1024`。
4. **确认显存占用**：启动前运行 `nvidia-smi` 并关闭占用显存的进程。
5. **可选优化**：`pip install torch-c-dlpack-ext`，或使用量化权重（`--quantization awq` 等）。

通常组合使用方案 1+2 即可在 16GB 显卡上运行；如仍不足，再调低并发或关闭其他进程。

### 启动阶段即报显存不足

若 16GB 显卡在模型加载阶段即失败，可进一步牺牲上下文/并发或启用 CPU Swap：

```bash
vllm serve ~/models/DeepAnalyze-8B \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.65 \
  --max-model-len 1024 \
  --max-num-batched-tokens 128 \
  --max-num-seqs 1 \
  --swap-space 8
```

- `--max-num-seqs 1` 强制单会话以减少缓存。
- `--swap-space 8` 将部分 KV cache 放到 CPU，延迟会上升但可换取内存。

如显存依旧不足，可考虑量化或使用更大显存的 GPU。

### 当前硬件的最终结论

- 在 16GB 显卡上以非量化方式运行 DeepAnalyze-8B 非常困难，即使调低各项参数仍可能因 KV Cache 空间不足失败。
- 可行替代：
  1. 使用更小或量化模型（7B/4B/GPTQ/AWQ 等）。
  2. 在 24GB+ 显卡或云端部署，再通过 API 调用。
  3. 若需继续探索，可远程部署推理，本地仅调用接口。

### 以 7B 级模型替代 DeepAnalyze-8B 的实践

1. **选择兼容模型**：如 `Qwen2.5-7B-Instruct`、`Llama-3.1-8B-Instruct`、`Yi-1.5-6B-Chat`、`Mistral-7B-Instruct-v0.3` 等。
2. **下载权重**：
   ```bash
   hf download Qwen/Qwen2.5-3B-Instruct --local-dir ~/models/qwen2.5-3b-instruct
   ```
3. **启动 vLLM**：
   ```bash
   vllm serve ~/models/qwen2.5-3b-instruct \
     --host 0.0.0.0 --port 8000 \
     --trust-remote-code
   ```
4. **保持 API/WebUI 流程不变**：仍按 README 顺序启动 API、WebUI、示例脚本，只是模型端换成 7B 权重即可验证链路。
5. **记录替代方案**：在文档中说明临时使用 7B 模型，待硬件升级或量化权重到位后，再切回 DeepAnalyze-8B。

#### 可在 16 GB 显卡上运行的 Qwen 模型清单

| 模型 | 参数规模 | 说明 |
| --- | --- | --- |
| `Qwen/Qwen2.5-0.5B-Instruct` | 0.5B | 占用极低，适合最小化流程验证。 |
| `Qwen/Qwen2.5-1.5B-Instruct` | 1.5B | 16 GB 显存轻松运行。 |
| `Qwen/Qwen2.5-3B-Instruct` | 3B | 约 10–12 GB 显存即可。 |
| `Qwen/Qwen2.5-7B-Instruct` | 7B | 16 GB 可运行，建议降低 `max_model_len`。 |
| `Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4` | 7B INT4 | 8–10 GB 显存即可，需 `--quantization gptq`。 |
| `Qwen/Qwen1.5-4B-Chat` | 4B | 显存余量更大，适合测试。 |
| `Qwen/Qwen1.5-1.8B-Chat` | 1.8B | 低显存占用，适合脚本验证。 |
| `Qwen/Qwen1.5-7B-Chat` / `Qwen/Qwen2-7B-Instruct` | 7B | 经典 7B 版本，可替代使用。 |

> 以上显存估算基于 FP16/bfloat16；若使用量化权重，请在 vLLM 命令中添加对应 `--quantization` 参数。
