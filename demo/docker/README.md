# DeepAnalyze 沙箱执行环境 Docker 镜像

本目录包含 DeepAnalyze 代码执行沙箱的 Docker 镜像构建文件。该镜像用于在隔离环境中安全执行模型生成的 Python 数据分析代码。

## 目录结构

```
demo/docker/
├── Dockerfile           # 镜像定义
├── requirements.txt     # 沙箱内预装的 Python 包
├── build.sh             # 构建脚本（Linux/macOS）
├── build.ps1            # 构建脚本（Windows PowerShell）
├── test_executor.py     # 独立测试脚本
└── README.md            # 本文件
```

## 前置条件

- **Docker Engine** ≥ 24.0（或 Docker Desktop）
- 确保 Docker 服务已启动

## 构建镜像

### Linux / macOS

```bash
cd demo/docker
bash build.sh
```

### Windows PowerShell

```powershell
cd demo\docker
.\build.ps1
```

### 手动构建

```bash
docker build -t deepanalyze-sandbox:latest .
```

构建完成后，镜像名称为 `deepanalyze-sandbox:latest`。

## 验证镜像

```bash
# 检查基础库是否可用
docker run --rm deepanalyze-sandbox:latest python -c "
import pandas as pd
import matplotlib
import seaborn as sns
import sklearn
print('pandas:', pd.__version__)
print('matplotlib:', matplotlib.__version__)
print('seaborn:', sns.__version__)
print('sklearn:', sklearn.__version__)
print('All OK')
"
```

## 预装 Python 包

| 包名 | 最低版本 | 用途 |
|------|---------|------|
| pandas | 2.2 | 数据处理 |
| numpy | 1.26 | 数值计算 |
| matplotlib | 3.8 | 图表绘制 |
| seaborn | 0.13 | 统计可视化 |
| scikit-learn | 1.4 | 机器学习 |
| scipy | 1.12 | 科学计算 |
| openpyxl | 3.1 | Excel 读写 |
| xlrd | 2.0 | Excel 读取 |
| chardet | 5.2 | 编码检测 |
| tabulate | 0.9 | 表格格式化 |
| Pillow | 10.2 | 图像处理 |
| wordcloud | 1.9 | 词云生成 |

如需添加新的包，编辑 `requirements.txt` 后重新构建镜像。

## 使用方式

### 1. 直接运行代码

```bash
docker run --rm deepanalyze-sandbox:latest python -c "print('hello')"
```

### 2. 挂载 workspace 目录执行

```bash
# 将本地 workspace 挂载到容器 /data 目录
docker run --rm \
  -v /path/to/workspace:/data \
  -w /data \
  deepanalyze-sandbox:latest \
  python your_script.py
```

### 3. 带资源限制和安全隔离

```bash
docker run --rm \
  --memory=2g \
  --cpus=2.0 \
  --network=none \
  --read-only \
  --tmpfs=/tmp:size=256m \
  --security-opt=no-new-privileges \
  -v /path/to/workspace:/data \
  -w /data \
  deepanalyze-sandbox:latest \
  python your_script.py
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--memory=2g` | 内存上限 2GB |
| `--cpus=2.0` | 最多使用 2 个 CPU 核心 |
| `--network=none` | 禁用网络访问 |
| `--read-only` | 容器根文件系统只读 |
| `--tmpfs=/tmp:size=256m` | /tmp 临时文件系统，限制 256MB |
| `--security-opt=no-new-privileges` | 禁止容器内进程提权 |

## 运行独立测试

测试脚本会验证镜像的基础功能（print、CSV 读取、文件写入、matplotlib 绑图、异常捕获、超时处理）：

```bash
cd demo
python docker/test_executor.py
```

> **注意**：Windows 下如遇 Unicode 输出问题，请设置环境变量：
> ```powershell
> $env:PYTHONIOENCODING='utf-8'; python docker/test_executor.py
> ```

预期输出：

```
测试结果: 6 通过, 0 失败
```

## 与主程序集成

在 `API/config.py` 中设置以下配置项即可启用 Docker 沙箱执行：

```python
DOCKER_SANDBOX_ENABLED = True                          # 开启 Docker 模式
DOCKER_SANDBOX_IMAGE = "deepanalyze-sandbox:latest"    # 镜像名称
DOCKER_SANDBOX_MEMORY_LIMIT = "2g"                     # 内存上限
DOCKER_SANDBOX_CPU_LIMIT = "2.0"                       # CPU 上限
DOCKER_SANDBOX_NETWORK = "none"                        # 网络模式
DOCKER_SANDBOX_TMPFS_SIZE = "256m"                     # /tmp 大小
```

设置 `DOCKER_SANDBOX_ENABLED = False`（默认值）则使用本地 subprocess 执行，无需 Docker。

详细设计文档见 [`docs/docker-sandbox-design.md`](../../docs/docker-sandbox-design.md)。
