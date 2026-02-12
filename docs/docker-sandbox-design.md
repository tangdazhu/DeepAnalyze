# DeepAnalyze 代码执行环境隔离 — 架构设计与实现文档

> **版本**: v1.0  
> **日期**: 2026-02-11  
> **状态**: 设计阶段  
> **依赖**: Docker Engine ≥ 24.0, Python 3.12

---

## 1. 背景与动机

### 1.1 现状

当前 `demo/backend.py` 中模型生成的代码通过 `execute_code_safe()` 函数执行：

```python
# demo/backend.py:459-501
def execute_code_safe(code_str, workspace_dir=None, timeout_sec=120):
    completed = subprocess.run(
        [sys.executable, tmp_path],   # 使用宿主 Python 解释器
        cwd=exec_cwd,                 # 工作目录 = session workspace
        capture_output=True, text=True, timeout=timeout_sec,
        env=child_env,
    )
```

**调用链路**：
- `bot_stream()` → `execute_code_safe(exec_code, str(workspace_path))` — 主循环中每轮代码执行
- `run_schema_bootstrap()` → `execute_code_safe(script, str(workspace_path))` — 首轮 schema 查询
- `/execute` API → `execute_code_safe(code, workspace_dir)` — 前端手动执行

### 1.2 问题

| 问题 | 说明 |
|------|------|
| **依赖冲突** | 不同数据集可能需要不同版本的库（如 geopandas、networkx、statsmodels），全装在宿主环境会冲突 |
| **安全风险** | 模型生成的代码可访问宿主文件系统、网络、环境变量（含 API Key） |
| **资源竞争** | 多 session 并发时，一个 OOM 或死循环可能影响整个服务 |
| **环境污染** | `pip install` 写入宿主环境，残留文件难以清理 |

### 1.3 目标

- 通过配置开关控制是否启用 Docker 沙箱执行
- **关闭**（默认）：保持现有 `subprocess.run()` 模式，零额外依赖
- **开启**：代码在 Docker 容器中执行，实现进程/文件系统/网络隔离
- 对 `bot_stream()` 等上层调用者**完全透明**，无需修改调用方式

---

## 2. 架构设计

### 2.1 总体架构

```
┌──────────────────────────────────────────────────────────────┐
│                     backend.py (FastAPI)                      │
│                                                              │
│  bot_stream() ──▶ execute_code_safe(code, workspace_dir)     │
│                          │                                   │
│                          ▼                                   │
│              ┌─── DOCKER_SANDBOX_ENABLED? ───┐               │
│              │                               │               │
│         False│                          True │               │
│              ▼                               ▼               │
│   ┌──────────────────┐        ┌──────────────────────────┐   │
│   │  _exec_local()   │        │  _exec_in_docker()       │   │
│   │  subprocess.run() │        │  docker run --rm ...     │   │
│   │  (现有逻辑)       │        │  挂载 workspace → /data  │   │
│   └──────────────────┘        │  资源限制 + 超时          │   │
│                               └──────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 配置项

在 `API/config.py` 中新增：

```python
# ===== Docker 沙箱执行配置 =====
# True = 在 Docker 容器中执行模型生成的代码（需要 Docker Engine）
# False = 使用宿主 subprocess 执行（默认，无额外依赖）
DOCKER_SANDBOX_ENABLED = False

# Docker 基础镜像名称（需预先构建，见 docs/docker-sandbox-design.md）
DOCKER_SANDBOX_IMAGE = "deepanalyze-sandbox:latest"

# 容器资源限制
DOCKER_SANDBOX_MEMORY_LIMIT = "2g"       # 内存上限
DOCKER_SANDBOX_CPU_LIMIT = "2.0"         # CPU 核数上限
DOCKER_SANDBOX_TIMEOUT = 120             # 执行超时（秒），与 CODE_EXECUTION_TIMEOUT 对齐
DOCKER_SANDBOX_NETWORK = "none"          # 网络模式：none=禁用网络, bridge=允许网络
DOCKER_SANDBOX_TMPFS_SIZE = "256m"       # /tmp 临时文件系统大小
```

### 2.3 核心模块划分

```
demo/
├── backend.py                  # 修改 execute_code_safe()，增加分支
├── docker_executor.py          # 【新增】Docker 执行器模块
├── docker/
│   ├── Dockerfile              # 【新增】沙箱基础镜像定义
│   ├── requirements.txt        # 【新增】沙箱内预装的 Python 包
│   └── build.sh                # 【新增】镜像构建脚本
└── API/
    └── config.py               # 新增 DOCKER_SANDBOX_* 配置项
```

---

## 3. 详细设计

### 3.1 `docker/Dockerfile` — 沙箱基础镜像

```dockerfile
FROM python:3.12-slim

LABEL maintainer="DeepAnalyze"
LABEL description="DeepAnalyze code execution sandbox"

# 系统依赖（字体、图形渲染）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 预装数据分析常用库
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# 设置无界面环境
ENV MPLBACKEND=Agg
ENV QT_QPA_PLATFORM=offscreen
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# 工作目录
WORKDIR /data

# 非 root 用户执行（安全加固）
RUN useradd -m -s /bin/bash sandbox
USER sandbox
```

### 3.2 `docker/requirements.txt` — 沙箱预装包

```text
pandas>=2.2
numpy>=1.26
matplotlib>=3.8
seaborn>=0.13
scikit-learn>=1.4
scipy>=1.12
openpyxl>=3.1
xlrd>=2.0
chardet>=5.2
tabulate>=0.9
Pillow>=10.2
wordcloud>=1.9
```

### 3.3 `demo/docker_executor.py` — Docker 执行器

```python
"""Docker 沙箱代码执行器。

通过 docker run 在隔离容器中执行模型生成的 Python 代码。
容器生命周期：每次执行创建 → 运行 → 销毁（--rm），无状态。

配置项从 API/config.py 读取，以 DOCKER_SANDBOX_ 为前缀。
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("deepanalyze.docker_executor")


def check_docker_available() -> bool:
    """检查 Docker Engine 是否可用。"""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_image_exists(image: str) -> bool:
    """检查指定 Docker 镜像是否存在。"""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def execute_in_docker(
    code_str: str,
    workspace_dir: str,
    image: str,
    timeout_sec: int = 120,
    memory_limit: str = "2g",
    cpu_limit: str = "2.0",
    network: str = "none",
    tmpfs_size: str = "256m",
) -> str:
    """在 Docker 容器中执行 Python 代码。

    Args:
        code_str: 要执行的 Python 代码字符串
        workspace_dir: 宿主机 workspace 绝对路径（挂载到容器 /data）
        image: Docker 镜像名称
        timeout_sec: 执行超时（秒）
        memory_limit: 内存上限（如 "2g"）
        cpu_limit: CPU 核数上限（如 "2.0"）
        network: 网络模式（"none" 禁用网络, "bridge" 允许网络）
        tmpfs_size: /tmp 大小

    Returns:
        stdout + stderr 合并输出
    """
    workspace_path = Path(workspace_dir).resolve()
    generated_dir = workspace_path / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    # 将代码写入 generated/ 下的临时文件（容器内可通过 /data/generated/ 访问）
    fd, tmp_path = tempfile.mkstemp(suffix=".py", dir=str(generated_dir))
    os.close(fd)
    tmp_name = Path(tmp_path).name

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(code_str)

        # 构建 docker run 命令
        # workspace/ 整体挂载为 /data（读写），代码在 /data 下执行
        container_script = f"/data/generated/{tmp_name}"

        cmd = [
            "docker", "run", "--rm",
            # 资源限制
            f"--memory={memory_limit}",
            f"--cpus={cpu_limit}",
            # 网络隔离
            f"--network={network}",
            # 临时文件系统
            f"--tmpfs=/tmp:size={tmpfs_size}",
            # 安全：禁止提权
            "--security-opt=no-new-privileges",
            # 只读根文件系统（/data 除外）
            "--read-only",
            # 挂载 workspace → /data（读写，因为需要写入 generated/）
            "-v", f"{workspace_path}:/data",
            # 工作目录
            "-w", "/data",
            # 镜像
            image,
            # 执行命令
            "python", container_script,
        ]

        logger.info(
            "[docker_exec] Running: image=%s, script=%s, timeout=%ss, mem=%s, cpu=%s",
            image, tmp_name, timeout_sec, memory_limit, cpu_limit,
        )

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 10,  # 额外 10s 给容器启动/销毁
        )

        output = (completed.stdout or "") + (completed.stderr or "")

        if completed.returncode != 0 and not output.strip():
            output = f"[Error]: Container exited with code {completed.returncode}"

        return output

    except subprocess.TimeoutExpired:
        logger.warning("[docker_exec] Timeout after %ss for script %s", timeout_sec, tmp_name)
        # 尝试清理可能残留的容器（--rm 通常会自动清理）
        return f"[Timeout]: execution exceeded {timeout_sec} seconds"
    except FileNotFoundError:
        logger.error("[docker_exec] Docker command not found. Is Docker installed?")
        return "[Error]: Docker is not installed or not in PATH"
    except Exception as e:
        logger.error("[docker_exec] Unexpected error: %s", e)
        return f"[Error]: {str(e)}"
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
```

### 3.4 `backend.py` 改造 — `execute_code_safe()` 增加分支

改造范围极小，仅修改 `execute_code_safe()` 函数：

```python
# ---- 新增：在文件顶部配置区读取 Docker 开关 ----
DOCKER_SANDBOX_ENABLED = getattr(api_config, "DOCKER_SANDBOX_ENABLED", False)
DOCKER_SANDBOX_IMAGE = getattr(api_config, "DOCKER_SANDBOX_IMAGE", "deepanalyze-sandbox:latest")
DOCKER_SANDBOX_MEMORY_LIMIT = getattr(api_config, "DOCKER_SANDBOX_MEMORY_LIMIT", "2g")
DOCKER_SANDBOX_CPU_LIMIT = getattr(api_config, "DOCKER_SANDBOX_CPU_LIMIT", "2.0")
DOCKER_SANDBOX_NETWORK = getattr(api_config, "DOCKER_SANDBOX_NETWORK", "none")
DOCKER_SANDBOX_TMPFS_SIZE = getattr(api_config, "DOCKER_SANDBOX_TMPFS_SIZE", "256m")

# 启动时校验 Docker 可用性
if DOCKER_SANDBOX_ENABLED:
    from docker_executor import check_docker_available, check_image_exists, execute_in_docker
    if not check_docker_available():
        logger.error("[启动] DOCKER_SANDBOX_ENABLED=True 但 Docker 不可用，回退到本地执行")
        DOCKER_SANDBOX_ENABLED = False
    elif not check_image_exists(DOCKER_SANDBOX_IMAGE):
        logger.error("[启动] Docker 镜像 %s 不存在，请先构建。回退到本地执行", DOCKER_SANDBOX_IMAGE)
        DOCKER_SANDBOX_ENABLED = False
    else:
        logger.info("[启动] ✅ Docker 沙箱执行已启用，镜像: %s", DOCKER_SANDBOX_IMAGE)


# ---- 改造 execute_code_safe() ----
def execute_code_safe(code_str: str, workspace_dir: str = None, timeout_sec: int = 120) -> str:
    """在隔离环境中执行代码。

    根据 DOCKER_SANDBOX_ENABLED 配置：
    - False: 使用宿主 subprocess 执行（现有逻辑）
    - True:  使用 Docker 容器执行
    """
    if workspace_dir is None:
        workspace_dir = WORKSPACE_BASE_DIR
    exec_cwd = os.path.abspath(workspace_dir)
    os.makedirs(exec_cwd, exist_ok=True)

    # ===== Docker 模式 =====
    if DOCKER_SANDBOX_ENABLED:
        return execute_in_docker(
            code_str=code_str,
            workspace_dir=exec_cwd,
            image=DOCKER_SANDBOX_IMAGE,
            timeout_sec=timeout_sec,
            memory_limit=DOCKER_SANDBOX_MEMORY_LIMIT,
            cpu_limit=DOCKER_SANDBOX_CPU_LIMIT,
            network=DOCKER_SANDBOX_NETWORK,
            tmpfs_size=DOCKER_SANDBOX_TMPFS_SIZE,
        )

    # ===== 本地模式（现有逻辑，原样保留） =====
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".py", dir=exec_cwd)
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(code_str)
        # ... 现有 subprocess.run 逻辑不变 ...
    except subprocess.TimeoutExpired:
        return f"[Timeout]: execution exceeded {timeout_sec} seconds"
    except Exception as e:
        return f"[Error]: {str(e)}"
    finally:
        # ... 清理临时文件 ...
```

**关键点**：上层调用者（`bot_stream()`、`run_schema_bootstrap()`、`/execute` API）**无需任何修改**，它们只调用 `execute_code_safe()`，内部自动路由。

---

## 4. 文件挂载与路径映射

### 4.1 挂载策略

```
宿主机                              容器内
─────────────────────────────────────────────────
workspace/{session_id}/          →  /data/           (读写)
  ├── data/                      →  /data/data/      (数据文件)
  ├── generated/                 →  /data/generated/  (产出文件)
  └── *.sqlite                   →  /data/*.sqlite   (数据库)
```

### 4.2 路径兼容性

模型生成的代码中使用的路径（如 `Path('generated') / 'xxx.png'`）在容器内同样有效，因为：
- 容器工作目录 `-w /data` 对应宿主 `workspace/{session_id}/`
- 相对路径 `generated/xxx.png` → 容器内 `/data/generated/xxx.png` → 宿主 `workspace/{session_id}/generated/xxx.png`

**无需修改模型 prompt 或代码模板。**

### 4.3 文件权限

容器内以 `sandbox` 用户（UID 1000）运行。宿主机 workspace 目录需确保该 UID 有读写权限：

```bash
# Linux 部署时需执行（Windows/macOS Docker Desktop 自动处理）
chmod -R 777 workspace/
```

---

## 5. 安全加固

| 措施 | 说明 |
|------|------|
| `--network=none` | 默认禁用网络，防止代码外传数据或下载恶意包 |
| `--read-only` | 容器根文件系统只读，仅 `/data` 和 `/tmp` 可写 |
| `--security-opt=no-new-privileges` | 禁止容器内进程提权 |
| `--rm` | 容器执行完毕自动销毁，不留残留 |
| `--memory=2g` | 内存上限，防止 OOM 影响宿主 |
| `--cpus=2.0` | CPU 限制，防止死循环占满所有核心 |
| `USER sandbox` | 非 root 用户运行，降低逃逸风险 |
| `--tmpfs=/tmp:size=256m` | 临时文件系统有大小限制 |

### 5.1 可选：允许网络（按需安装库）

某些数据集可能需要额外的 Python 库。可通过配置开启网络：

```python
# API/config.py
DOCKER_SANDBOX_NETWORK = "bridge"  # 允许网络访问（pip install 等）
```

**风险**：模型生成的代码可能发起外部请求。建议仅在受信任环境中开启。

---

## 6. 构建与部署

### 6.1 构建镜像

```bash
cd demo/docker
docker build -t deepanalyze-sandbox:latest .
```

### 6.2 验证镜像

```bash
# 测试基础功能
docker run --rm deepanalyze-sandbox:latest python -c "
import pandas as pd
import matplotlib
import seaborn as sns
print('pandas:', pd.__version__)
print('matplotlib:', matplotlib.__version__)
print('seaborn:', sns.__version__)
print('All OK')
"
```

### 6.3 启用 Docker 模式

```python
# API/config.py 中修改
DOCKER_SANDBOX_ENABLED = True
```

重启 backend 服务即可生效。启动日志会显示：

```
[启动] ✅ Docker 沙箱执行已启用，镜像: deepanalyze-sandbox:latest
```

### 6.4 回退到本地模式

```python
# API/config.py 中修改
DOCKER_SANDBOX_ENABLED = False
```

或者当 Docker 不可用时，系统自动回退并输出警告日志。

---

## 7. 实现步骤

实现分为两大阶段。**Phase A** 独立完成 Docker 沙箱的构建和验证，不触碰主程序代码；**Phase B** 再将沙箱接入主程序并做端到端测试。两阶段之间有明确的验收门槛，Phase A 通过后才进入 Phase B。

---

### Phase A: Docker 沙箱独立构建与验证

> **目标**：构建镜像 + 编写执行器模块 + 独立测试脚本全部通过，**不修改 `backend.py` 和 `config.py`**。

#### A-1: 创建 Docker 镜像文件

| 文件 | 说明 |
|------|------|
| `demo/docker/Dockerfile` | 沙箱镜像定义（见 §3.1） |
| `demo/docker/requirements.txt` | 沙箱预装包列表（见 §3.2） |
| `demo/docker/build.sh` | 一键构建脚本（Linux/macOS） |
| `demo/docker/build.ps1` | 一键构建脚本（Windows PowerShell） |

#### A-2: 构建镜像

```bash
cd demo/docker
docker build -t deepanalyze-sandbox:latest .
```

#### A-3: 镜像冒烟测试

逐项验证镜像基础能力，全部通过才进入下一步：

```bash
# 测试 1: 基础库可用
docker run --rm deepanalyze-sandbox:latest python -c "
import pandas as pd; import matplotlib; import seaborn as sns; import sklearn
print('pandas:', pd.__version__)
print('matplotlib:', matplotlib.__version__)
print('seaborn:', sns.__version__)
print('sklearn:', sklearn.__version__)
print('[PASS] 基础库加载正常')
"

# 测试 2: 文件读写（模拟 workspace 挂载）
mkdir -p /tmp/test_sandbox/data /tmp/test_sandbox/generated
echo "col1,col2" > /tmp/test_sandbox/data/test.csv
echo "1,2" >> /tmp/test_sandbox/data/test.csv
docker run --rm -v /tmp/test_sandbox:/data -w /data deepanalyze-sandbox:latest python -c "
import pandas as pd
from pathlib import Path
df = pd.read_csv('data/test.csv')
print('Read CSV:', df.shape)
Path('generated/output.txt').write_text('hello from sandbox')
print('[PASS] 文件读写正常')
"
cat /tmp/test_sandbox/generated/output.txt  # 应输出 "hello from sandbox"

# 测试 3: matplotlib 图片生成
docker run --rm -v /tmp/test_sandbox:/data -w /data deepanalyze-sandbox:latest python -c "
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
df = pd.read_csv('data/test.csv')
df.plot(kind='bar')
plt.savefig('generated/test_chart.png', dpi=100)
print('PNG size:', Path('generated/test_chart.png').stat().st_size, 'bytes')
print('[PASS] 图片生成正常')
"

# 测试 4: SQLite 访问
docker run --rm -v /tmp/test_sandbox:/data -w /data deepanalyze-sandbox:latest python -c "
import sqlite3
conn = sqlite3.connect(':memory:')
conn.execute('CREATE TABLE t(id INTEGER, name TEXT)')
conn.execute(\"INSERT INTO t VALUES(1, 'test')\")
row = conn.execute('SELECT * FROM t').fetchone()
print('SQLite row:', row)
print('[PASS] SQLite 正常')
"

# 测试 5: 资源限制生效
docker run --rm --memory=64m deepanalyze-sandbox:latest python -c "
try:
    data = bytearray(128 * 1024 * 1024)  # 尝试分配 128MB
    print('[FAIL] 内存限制未生效')
except MemoryError:
    print('[PASS] 内存限制生效')
"

# 测试 6: 网络隔离（默认 none）
docker run --rm --network=none deepanalyze-sandbox:latest python -c "
import urllib.request
try:
    urllib.request.urlopen('https://example.com', timeout=3)
    print('[FAIL] 网络未隔离')
except Exception as e:
    print('[PASS] 网络已隔离:', type(e).__name__)
"
```

#### A-4: 新增 `demo/docker_executor.py`

独立模块，不依赖 `backend.py`：

- `check_docker_available()` — 检查 Docker Engine 是否可用
- `check_image_exists(image)` — 检查指定镜像是否存在
- `execute_in_docker(code_str, workspace_dir, ...)` — 核心执行函数

详见 §3.3。

#### A-5: 执行器独立测试

编写 `demo/docker/test_executor.py`，**脱离 backend 独立运行**：

```python
"""Docker 执行器独立测试脚本。

用法：
    cd demo
    python docker/test_executor.py

前置条件：
    1. Docker Engine 已启动
    2. 已构建镜像: docker build -t deepanalyze-sandbox:latest docker/
"""
import sys
import tempfile
from pathlib import Path

# 将 demo/ 加入 sys.path 以导入 docker_executor
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from docker_executor import check_docker_available, check_image_exists, execute_in_docker

IMAGE = "deepanalyze-sandbox:latest"
PASSED = 0
FAILED = 0

def run_test(name, code, workspace_dir, expect_in_output=None, expect_not_in_output=None):
    global PASSED, FAILED
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"{'='*60}")
    output = execute_in_docker(code, workspace_dir, IMAGE, timeout_sec=30)
    print(f"输出:\n{output}")

    ok = True
    if expect_in_output:
        for s in expect_in_output:
            if s not in output:
                print(f"  ❌ 期望输出包含 '{s}'，但未找到")
                ok = False
    if expect_not_in_output:
        for s in expect_not_in_output:
            if s in output:
                print(f"  ❌ 期望输出不包含 '{s}'，但找到了")
                ok = False
    if ok:
        print(f"  ✅ 通过")
        PASSED += 1
    else:
        FAILED += 1

def main():
    # 前置检查
    print("检查 Docker 可用性...")
    assert check_docker_available(), "Docker 不可用，请先启动 Docker Engine"
    print("检查镜像存在...")
    assert check_image_exists(IMAGE), f"镜像 {IMAGE} 不存在，请先构建"

    # 创建临时 workspace
    with tempfile.TemporaryDirectory(prefix="deepanalyze_test_") as tmpdir:
        ws = Path(tmpdir)
        (ws / "data").mkdir()
        (ws / "generated").mkdir()
        # 写入测试数据
        (ws / "data" / "test.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

        # 测试 1: 基础输出
        run_test("基础 print",
            'print("hello sandbox")',
            str(ws),
            expect_in_output=["hello sandbox"])

        # 测试 2: 读取 CSV
        run_test("读取 CSV",
            'import pandas as pd; df = pd.read_csv("data/test.csv"); print("rows:", len(df))',
            str(ws),
            expect_in_output=["rows: 2"])

        # 测试 3: 写入 generated/
        run_test("写入文件到 generated/",
            'from pathlib import Path; Path("generated/result.txt").write_text("ok"); print("written")',
            str(ws),
            expect_in_output=["written"])
        # 验证宿主机文件
        result_file = ws / "generated" / "result.txt"
        assert result_file.exists(), f"宿主机未找到 {result_file}"
        assert result_file.read_text() == "ok", f"文件内容不匹配"
        print("  ✅ 宿主机文件验证通过")

        # 测试 4: matplotlib 生成 PNG
        run_test("matplotlib 生成 PNG",
            """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1,2,3],[1,4,9])
plt.savefig('generated/test.png', dpi=72)
print('png saved')
""",
            str(ws),
            expect_in_output=["png saved"])
        png_file = ws / "generated" / "test.png"
        assert png_file.exists(), f"PNG 文件未生成"
        assert png_file.stat().st_size > 1000, f"PNG 文件过小: {png_file.stat().st_size}"
        print(f"  ✅ PNG 文件验证通过 ({png_file.stat().st_size} bytes)")

        # 测试 5: 错误处理
        run_test("语法错误捕获",
            'print(1/0)',
            str(ws),
            expect_in_output=["ZeroDivisionError"])

        # 测试 6: 超时处理
        run_test("超时处理",
            'import time; time.sleep(60)',
            str(ws),
            expect_in_output=["Timeout"])

    # 汇总
    print(f"\n{'='*60}")
    print(f"测试结果: {PASSED} 通过, {FAILED} 失败")
    print(f"{'='*60}")
    sys.exit(1 if FAILED > 0 else 0)

if __name__ == "__main__":
    main()
```

#### A-6: Phase A 验收标准

| # | 验收项 | 通过条件 |
|---|--------|---------|
| 1 | 镜像构建 | `docker build` 成功，无报错 |
| 2 | 镜像冒烟测试 | A-3 中 6 项测试全部输出 `[PASS]` |
| 3 | 执行器独立测试 | `python docker/test_executor.py` 全部通过 |
| 4 | 不影响主程序 | `backend.py` 和 `config.py` 未被修改 |

**Phase A 全部通过后，才进入 Phase B。**

---

### Phase B: 与主程序集成

> **目标**：将 Docker 执行器接入 `backend.py`，通过配置开关控制，端到端测试通过。

#### B-1: 修改 `API/config.py`

新增 `DOCKER_SANDBOX_*` 配置项（见 §2.2），默认 `DOCKER_SANDBOX_ENABLED = False`。

#### B-2: 修改 `demo/backend.py`

仅修改 `execute_code_safe()` 函数：
1. 文件顶部读取 Docker 配置 + 启动时校验 Docker 可用性
2. 函数内部增加 `if DOCKER_SANDBOX_ENABLED` 分支，调用 `execute_in_docker()`
3. 现有本地执行逻辑放入 `else` 分支，**原样保留**

详见 §3.4。

#### B-3: 本地模式回归测试

**先确认关闭 Docker 开关时，现有功能不受影响**：

```bash
# 确保 DOCKER_SANDBOX_ENABLED = False（默认值）
# 1. 启动 backend
python demo/backend.py
# 2. 启动前端
cd demo/chat && npm run dev
# 3. 上传数据集 → 执行分析 → 确认 Round 1-10 正常完成
# 4. 确认日志中无 [docker_exec] 前缀（走的是本地 subprocess）
```

#### B-4: Docker 模式集成测试

```bash
# 1. 修改 API/config.py: DOCKER_SANDBOX_ENABLED = True
# 2. 重启 backend
python demo/backend.py
# 3. 确认启动日志出现:
#    [启动] ✅ Docker 沙箱执行已启用，镜像: deepanalyze-sandbox:latest

# 4. 上传数据集 → 执行分析 → 确认 Round 1-10 正常完成
# 5. 检查 backend 日志中出现 [docker_exec] 前缀
# 6. 确认 generated/ 下文件正常生成（CSV、PNG、README.md、报告）
# 7. 点击「重新生成报告」按钮 → 确认 Round 8-10 正常重跑
```

#### B-5: 自动回退测试

```bash
# 场景 1: Docker 未启动
# 1. 停止 Docker Engine
# 2. 设置 DOCKER_SANDBOX_ENABLED = True
# 3. 启动 backend → 确认日志输出:
#    [启动] DOCKER_SANDBOX_ENABLED=True 但 Docker 不可用，回退到本地执行
# 4. 执行分析 → 确认正常完成（走本地 subprocess）

# 场景 2: 镜像不存在
# 1. docker rmi deepanalyze-sandbox:latest
# 2. 设置 DOCKER_SANDBOX_ENABLED = True
# 3. 启动 backend → 确认日志输出:
#    [启动] Docker 镜像 deepanalyze-sandbox:latest 不存在，请先构建。回退到本地执行
# 4. 执行分析 → 确认正常完成（走本地 subprocess）
```

#### B-6: Phase B 验收标准

| # | 验收项 | 通过条件 |
|---|--------|---------|
| 1 | 本地模式回归 | `DOCKER_SANDBOX_ENABLED=False` 时 Round 1-10 正常完成 |
| 2 | Docker 模式 | `DOCKER_SANDBOX_ENABLED=True` 时 Round 1-10 正常完成 |
| 3 | Resume 功能 | Docker 模式下「重新生成报告」Round 8-10 正常重跑 |
| 4 | 自动回退 | Docker 不可用时自动回退到本地模式，不影响功能 |
| 5 | 日志可追踪 | Docker 模式日志含 `[docker_exec]` 前缀，可区分执行模式 |

---

## 8. 性能考量

### 8.1 容器启动开销

| 模式 | 首次执行 | 后续执行 |
|------|---------|---------|
| 本地 subprocess | ~50ms | ~50ms |
| Docker `--rm`（冷启动） | ~800ms | ~500ms |

**影响评估**：每轮分析约 30-120 秒（模型生成 + 代码执行），容器启动的 500ms 开销占比 < 2%，可忽略。

### 8.2 未来优化方向（Phase 3）

如果并发量增大，可考虑：

- **容器复用**：每个 session 创建一个长驻容器，通过 `docker exec` 执行代码，避免重复创建/销毁
- **镜像预热**：`docker pull` + `docker create` 预创建容器池
- **按需安装缓存**：将 pip cache 挂载为 volume，加速 `pip install`

这些优化不在当前 Phase 2 范围内，但架构设计已预留扩展空间。

---

## 9. 配置速查表

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DOCKER_SANDBOX_ENABLED` | `False` | 总开关。False=本地执行，True=Docker 执行 |
| `DOCKER_SANDBOX_IMAGE` | `deepanalyze-sandbox:latest` | 沙箱镜像名称 |
| `DOCKER_SANDBOX_MEMORY_LIMIT` | `2g` | 容器内存上限 |
| `DOCKER_SANDBOX_CPU_LIMIT` | `2.0` | 容器 CPU 核数上限 |
| `DOCKER_SANDBOX_TIMEOUT` | `120` | 执行超时（秒） |
| `DOCKER_SANDBOX_NETWORK` | `none` | 网络模式。none=禁用，bridge=允许 |
| `DOCKER_SANDBOX_TMPFS_SIZE` | `256m` | /tmp 大小限制 |

---

## 10. 回滚方案

如果 Docker 模式出现问题：

1. **自动回退**：Docker 不可用或镜像不存在时，启动日志会警告并自动回退到本地模式
2. **手动回退**：修改 `API/config.py` 中 `DOCKER_SANDBOX_ENABLED = False`，重启服务即可
3. **代码回滚**：`execute_code_safe()` 的本地执行分支完全保留原有逻辑，删除 Docker 相关代码不影响任何功能

---

## 附录 A: 完整文件清单

```
新增文件:
  demo/docker/Dockerfile              # 沙箱镜像定义
  demo/docker/requirements.txt        # 沙箱预装包
  demo/docker/build.sh                # 构建脚本
  demo/docker_executor.py             # Docker 执行器模块

修改文件:
  API/config.py                       # +7 行配置项
  demo/backend.py                     # execute_code_safe() 增加 ~20 行分支逻辑
```

## 附录 B: 与现有功能的兼容性

| 功能 | Docker 模式兼容性 | 说明 |
|------|-------------------|------|
| Round 1-7 数据分析 | ✅ | 代码在容器内执行，产出文件通过挂载写入 generated/ |
| Round 8-10 报告生成 | ✅ | 同上 |
| Resume from Round | ✅ | `cleanup_rounds_from()` 操作宿主文件系统，不受影响 |
| Schema Bootstrap | ✅ | `run_schema_bootstrap()` 调用 `execute_code_safe()`，自动路由 |
| `/execute` API | ✅ | 同上 |
| 文件下载/预览 | ✅ | HTTP 文件服务器读取宿主 workspace，不经过容器 |
| SQLite 数据库访问 | ✅ | .sqlite 文件在 workspace/ 下，容器内通过 /data/ 访问 |
