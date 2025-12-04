# DeepAnalyze 安装与运行手册

要启动一个全新的 DeepAnalyze 数据分析项目，建议按照 README 中的顺序完成环境与服务安装配置：

## 1. 准备 Python 环境

建议使用 Conda 为推理单独创建虚拟环境，避免与训练依赖冲突：

```bash
conda create -n deepanalyze python=3.12 -y
conda activate deepanalyze
```

然后安装核心依赖：

```bash
pip install -r requirements.txt
```

这些依赖包含 torch、transformers、vllm 等运行 DeepAnalyze 所需的组件。@README.md#107-205

## 2. （可选）训练相关依赖

若需要本地训练或继续优化模型，还需在对应子目录下安装可编辑包：

```bash
(cd ./deepanalyze/ms-swift/ && pip install -e .)
(cd ./deepanalyze/SkyRL/ && pip install -e .)
```

为避免推理与训练包冲突，推荐分别建立环境。@README.md#107-205

## 10. 三终端并行启动示例

1. **模型服务**
   ```bash
   (deepanalyze) tdz@tangdazhu:~$
   conda activate deepanalyze
   vllm serve ~/models/qwen2.5-3b-instruct \
     --host 0.0.0.0 --port 8000 \
     --served-model-name qwen2.5-3b-instruct \
     --trust-remote-code
   ```
2. **后端服务**（使用 demo/backend.py，提供 `/workspace/*` 等接口）
   ```bash
   conda activate deepanalyze
   cd ~/DeepAnalyze/demo
   python backend.py
   ```
3. **前端 WebUI**
   ```bash
   conda activate deepanalyze
   cd ~/DeepAnalyze/demo/chat
   npm run dev -- --hostname 0.0.0.0 --port 4000
   ```

 然后从浏览器访问WebUI： http://172.23.6.173:4000/

此模式下无需再启动 `API/start_server.py`，避免 8200/8100 端口冲突。若后续改用官方 API，可将 `/workspace/*` 路由迁移或继续并行运行 `backend.py`。


## 3. 部署推理模型（vLLM）

先下载模型权重（可暂用 Qwen2.5-3B-Instruct 等），再启动 vLLM 服务：

```bash
vllm serve ~/models/qwen2.5-3b-instruct \
    --host 0.0.0.0 --port 8000 \
    --trust-remote-code
```

该服务会被 API 层调用，确保先启动。@README.md#47-205 @API/README.md#1-33

## 4. 启动 API 服务器

在 WSL 中打开新终端，进入 `API` 目录运行：

```bash
conda activate deepanalyze
cd ~/DeepAnalyze/API
python start_server.py
```

默认主 API 端口为 8200（文件下载 8100，健康检查 `/health`）。若日志提示 `ImportError: Using SOCKS proxy`，请安装 `pip install "httpx[socks]"`。@API/README.md#13-25

## 5. （可选）运行前端或 CLI

- **WebUI**：进入 `demo/chat` 执行 `npm install`，随后在 `demo` 目录运行 `bash start.sh` 即可通过 `http://localhost:4000` 访问。@README.md#47-60
- **CLI**：保持 API 运行后，进入 `demo/cli` 执行 `python api_cli.py`（英文）或 `python api_cli_ZH.py`（中文）。@README.md#79-95

## 6. 调用 API 进行数据分析

接口遵循 OpenAI 风格，可先上传文件，再调用 `chat/completions`：

```bash
FILE_RESPONSE=$(curl -s -X POST "http://localhost:8200/v1/files" \
    -F "file=@data.csv" \
    -F "purpose=file-extract")
FILE_ID=$(echo $FILE_RESPONSE | jq -r '.id')

curl -X POST http://localhost:8200/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
          "model": "DeepAnalyze-8B",
          "messages": [
            {"role": "user",
             "content": "Generate a data science report.",
             "file_ids": ["'$FILE_ID'"]
            }
          ]
        }'
```

@README.md#177-205

完成上述步骤后，你就拥有了一个可用的 DeepAnalyze 推理环境。可在 `example/` 目录复现示例，进一步了解自动化分析流程。

## 7. 启动 WebUI（独立终端）

进入 `demo/chat`，安装依赖并运行：

```bash
cd ~/DeepAnalyze/demo/chat
npm install
cd ..
bash start.sh
```

浏览器访问 `http://localhost:4000`，在设置里填入 `http://localhost:8200/v1` 和任意 API Key（如 `dummy-key`）即可交互。

### 避免 start.sh 误杀现有服务

`start.sh` 默认会通过 `pkill` + `lsof → kill -9` 清理 8000/8100/8200 端口，再启动 demo 自带的 `backend.py`。若希望保留自己手动起的 vLLM/API，可设置：

```bash
cd ~/DeepAnalyze/demo
export SKIP_CLEANUP=1  # 或直接 SKIP_CLEANUP=1 bash start.sh
bash start.sh
```

若只想启用前端并复用真实 API，建议在 `demo/chat` 中直接运行：

```bash
cd ~/DeepAnalyze/demo/chat
npm install  # 首次执行
npm run dev -- --host 0.0.0.0 --port 4000
```

## 8. GPU 占用排查

使用 `nvidia-smi` 查看显存。如果发现进程（如 `/python3.12`）长期占满显存，可：

1. 确认进程身份：
   ```bash
   ps -fp <PID>
   ```
2. 结束进程：
   ```bash
   kill -TERM <PID>
   sleep 2
   kill -9 <PID>
   ```
   或直接 `pkill -f "vllm"` / `pkill -f "start_server.py"`。

## 9. Node.js 与 WebUI 依赖

若运行 `npm run dev` 时提示 `next: not found`，请先安装依赖：

```bash
cd ~/DeepAnalyze/demo/chat
npm install
npm run dev -- --host 0.0.0.0 --port 4000
```

如遇 `SyntaxError: Unexpected token '?'`，说明 Node 版本 < 18.17。可通过 nvm 升级：

```bash
node -v  # 检查
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.nvm/nvm.sh
nvm install 20
nvm use 20
nvm alias default 20

cd ~/DeepAnalyze/demo/chat
rm -rf node_modules package-lock.json
npm install
npm run dev -- --hostname 0.0.0.0 --port 4000
```



## 11. 模型名称一致性

若 vLLM 日志提示 “The model `DeepAnalyze-8B` does not exist”，通常是请求里的 `model` 字段与 vLLM 的 `served_model_name` 不一致。

- `demo/backend.py` 中 `MODEL_PATH` 默认是 `DeepAnalyze-8B`，需改为你的模型名。
- WebUI 的 `three-panel-interface.tsx` 里也写死了 `deepanalyze-8b`，必要时同步修改。

**两种解决方案：**

1. 启动 vLLM 时显式指定名称：
   ```bash
   vllm serve ~/models/qwen2.5-3b-instruct \
     --host 0.0.0.0 --port 8000 \
     --served-model-name qwen2.5-3b-instruct \
     --trust-remote-code
   ```
   并在 backend/WebUI 中使用同样的字符串。
2. 若未指定 `--served-model-name`，vLLM 会使用完整路径（如 `/home/tdz/models/qwen2.5-3b-instruct`）。此时需将 backend 与 WebUI 的 `model` 字段改成该绝对路径。

只要三者一致，`/v1/chat/completions` 就不会再返回 404。

