







要启动一个全新的 DeepAnalyze 数据分析项目，建议按照 README 中的顺序完成环境与服务安装配置：

1. **准备 Python 环境** – 建议使用 Conda 为推理单独创建虚拟环境，避免与训练依赖冲突：
   ```bash
   conda create -n deepanalyze python=3.12 -y
   conda activate deepanalyze
   ```
   然后安装核心依赖：
   ```bash
   pip install -r requirements.txt
   ```
   这些依赖包含 torch、transformers、vllm 等运行 DeepAnalyze 所需的组件。@README.md#107-205

2. **（可选）训练相关依赖** – 若后续需要在本地进行训练或继续优化模型，还需在对应子目录下安装可编辑包：
   ```bash
   (cd ./deepanalyze/ms-swift/ && pip install -e .)
   (cd ./deepanalyze/SkyRL/ && pip install -e .)
   ```
   为了隔离推理与训练时的包版本冲突，官方推荐分别建立环境。@README.md#107-205

3. **部署推理模型（vLLM）** – 先下载 DeepAnalyze-8B 权重（README 顶部“Demo”部分提供 HuggingFace 链接），再用 vLLM 提供服务：
   ```bash
   vllm serve ~/models/qwen2.5-3b-instruct \
       --host 0.0.0.0 --port 8000 \
       --trust-remote-code
   ```
   该服务会被 API 层调用，确保先启动。@README.md#47-205 @API/README.md#1-33

4. **再打开一个wsl命令行启动 API 服务器** – 进入 `API` 目录并运行：
   ```bash
    conda activate deepanalyze
    cd DeepAnalyze/API
   python start_server.py
   ```
   默认主 API 端口为 8200（文件下载 8100，健康检查 `/health`），日志会提示是否成功创建 `workspace` 等运行目录。@API/README.md#13-25
  - ImportError: Using SOCKS proxy 错误， 需要安装
   pip install "httpx[socks]"

5. **（可选）运行前端或 CLI** – README 给出了多种 UI：
   - WebUI：进入 `demo/chat` 执行 `npm install`，随后在 `demo` 目录运行 `bash start.sh` 即可通过浏览器访问 `http://localhost:4000`。@README.md#47-60
   - CLI：在一个终端保持 API 运行，在另一个终端进入 `demo/cli` 执行 `python api_cli.py`（英文）或 `python api_cli_ZH.py`（中文）。@README.md#79-95

6. **调用 API 进行数据分析** – 提供 OpenAI-style REST 接口，可先上传文件，再发起 `chat/completions` 调用：
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

完成上述步骤后，你就拥有了一个可用的 DeepAnalyze 推理环境。接下来可根据需要上传数据文件、指定任务，或者在 `example`/`.example` 目录内复现官方示例，进一步了解自动化分析流程。

### 在另一个终端执行WebUI
进入 demo/chat，安装依赖并运行：
bash
npm install
bash ../start.sh

浏览器访问 http://localhost:4000，在设置里填入 http://localhost:8200/v1 和任意 API Key（例如 dummy-key），即可通过界面与模型交互。


### [start.sh](cci:7://file:///d:/Python-Learning/deepanalyze/demo/start.sh:0:0-0:0) 默认会执行 `pkill` 及 `lsof → kill -9` 来“清理”8000/8100/8200 端口，因此无论在哪个目录运行，都会把你先前启动的 vLLM/`python start_server.py` 进程终止，脚本自身再起一个 demo 用 `backend.py`。清理逻辑在 [demo/start.sh](cci:7://file:///d:/Python-Learning/deepanalyze/demo/start.sh:0:0-0:0) 第 6-42 行，可见会逐一杀掉占用这些端口的程序 @demo/start.sh#6-42。

我在脚本里加了 `SKIP_CLEANUP` 开关：将环境变量设置为 `1` 时，会跳过 `pkill` 与端口清理，避免误杀现有服务，同时保留其余启动步骤 @demo/start.sh#6-42。用法示例：

```bash
cd ~/DeepAnalyze/demo
export SKIP_CLEANUP=1          # 或临时写成 SKIP_CLEANUP=1 bash start.sh
bash start.sh
```

若你只想复用前端、继续使用真实 API（`python start_server.py`），建议仍然在单独终端进入 `demo/chat` 直接运行：

```bash
cd ~/DeepAnalyze/demo/chat
npm install            # 首次执行
npm run dev -- --host 0.0.0.0 --port 4000
```

这样不会触发 demo 脚本的后端与端口清理，也就不会中断已有的 vLLM 和 API 服务。

### 检查GPU占用
 -  nvidia-smi
 `nvidia-smi` 显示显存几乎被 PID 5174 的 `/python3.12` 占满（15807 MiB/16303 MiB），说明上一轮 vLLM/`python start_server.py` 仍在后台，没有正确退出，显存自然不会释放。可以按下面步骤清理：

1. 在同一个 WSL 终端里确认进程身份：  
   ```bash
   ps -fp 5174
   ```  
   如果确定就是之前的 vLLM 或 API，直接结束即可。

2. 结束进程：  
   ```bash
   kill -TERM 5174          # 先尝试优雅退出
   sleep 2
   kill -9 5174             # 若仍存在，再强制杀掉
   ```  
   或者直接 `pkill -f "vllm"` / `pkill -f "start_server.py"`。

### sh: 1: next: not found
`next` 是由 `node_modules/.bin/next` 提供的可执行文件，只有在 `demo/chat` 目录里安装完依赖后才会存在。第一次或清理过 `node_modules` 后，需要先执行：

```bash
cd ~/DeepAnalyze/demo/chat
npm install   # 读取 package.json，安装 next 等依赖
```

安装完成再运行：

```bash
npm run dev -- --host 0.0.0.0 --port 4000
```

就能找到 `next` 并成功启动前端。如果之前 `npm install` 报错过，建议先 `rm -rf node_modules package-lock.json` 后重装一次，确保依赖完整。

### 

[package.json](cci:7://file:///d:/Python-Learning/deepanalyze/demo/chat/package.json:0:0-0:0) 指明前端基于 **Next 14.2.16 + React 18**（见 [demo/chat/package.json](cci:7://file:///d:/Python-Learning/deepanalyze/demo/chat/package.json:0:0-0:0) 的 `dependencies` 部分）@demo/chat/package.json#1-85。Next 14 官方要求 Node.js ≥ 18.17；你当前环境里 `npm run dev` 调用了系统自带的旧版 Node（不支持可选链/空值合并），因此在加载 `commander` 打包代码时直接抛出 `SyntaxError: Unexpected token '?'`。

处理步骤（WSL 中执行）：

1. **查看当前 Node 版本**  
   ```bash
   node -v
   ```
   若 < 18.17，继续下一步。

2. **用 nvm 安装新版本 Node**
（假设已装 nvm；若未装，可先 `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash`，重新打开终端）：  

安装完成后重新打开一个终端，或手动载入配置：
bash
source ~/.nvm/nvm.sh


   ```bash
   nvm install 20          # 安装 Node 20 LTS
   nvm use 20
   nvm alias default 20
   ```

3. **清理旧依赖并重新安装**  
   ```bash
   cd ~/DeepAnalyze/demo/chat
   rm -rf node_modules package-lock.json
   npm install
   ```

4. **重新启动前端**  
   ```bash
 npm run dev -- --hostname 0.0.0.0 --port 4000
   ```

完成后 `next` 会使用新 Node 运行，语法错误即可消失。如果你有其他项目依赖旧 Node，可通过 `nvm use <version>` 来切换。

###  3个终端的启动命令
- 启动模型
(deepanalyze) tdz@tangdazhu:~$ vllm serve ~/models/qwen2.5-3b-instruct        --host 0.0.0.0 --port 8000        --trust-remote-code

- 启动服务 ： 
cd ~/DeepAnalyze/demo
python backend.py

- 启动客户端webui 
tdz@tangdazhu:~/DeepAnalyze/demo/chat$ 
npm run dev -- --hostname 0.0.0.0 --port 4000


现在的 WebUI 之所以恢复正常，是因为你改成运行 
demo/backend.py
，它自身就提供了 /workspace/*、代码执行、导出报告等接口（端口 8200/8100）。在这种模式下：*

不需要再启动 API/start_server.py。两者都会占用 8200/8100，功能还部分重叠，反而会端口冲突。
只要保持三件事在跑：
vllm serve ... --port 8000（模型服务）
python backend.py（demo 后端，负责 workspace + API）
npm run dev -- --hostname 0.0.0.0 --port 4000（WebUI）
如果你未来想使用更标准的 OpenAI 兼容接口（/v1/models、/v1/chat/completions 等），可以改回 API/start_server.py，但那时需要把 /workspace/* 路由迁过去或继续额外跑 
backend.py
。当前阶段，为了完成流程验证，维持上述三进程即可。*

- tdz@tangdazhu:~/DeepAnalyze/API$ python start_server.py


### “The model DeepAnalyze-8B does not exist” 的原因

前端 → backend → vLLM 这条链路里，模型名称依旧写死为 `DeepAnalyze-8B`（大写），这就是 vLLM 日志里报 “The model `DeepAnalyze-8B` does not exist” 的原因。虽然你已经用 Qwen2.5-3B-Instruct 启动了 vLLM，但：

- [demo/backend.py](cci:7://file:///d:/Python-Learning/deepanalyze/demo/backend.py:0:0-0:0) 初始化 OpenAI 客户端时，`MODEL_PATH = "DeepAnalyze-8B"`，后续所有 `/v1/chat/completions` 请求都会带上这个 `model` 名称 @demo/backend.py#118-135。
- WebUI 的 [ThreePanelInterface](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:115:0-3280:1) 里同样把 `model` 字段写成 `deepanalyze-8b` @demo/chat/components/three-panel-interface.tsx#2138-2159。

要让整个链路指向你当前的 Qwen 模型，有 2 个选择：

1. **改 backend 的模型名**（推荐，只需一次）：  
   - 打开 [demo/backend.py](cci:7://file:///d:/Python-Learning/deepanalyze/demo/backend.py:0:0-0:0)，把 `MODEL_PATH = "DeepAnalyze-8B"` 改成你在 vLLM `--served-model-name`/默认模型的名字（例如 `MODEL_PATH = "qwen2.5-3b-instruct"`）。  
   - 重启 `python backend.py`。这样 WebUI 发来的任何请求都会携带 `model="qwen2.5-3b-instruct"`。

2. **改 WebUI 的请求模型名**（如果只想改前端）：  
   - 在 [demo/chat/components/three-panel-interface.tsx](cci:7://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:0:0-0:0) 中把 `model: "deepanalyze-8b"` 改为 `model: "qwen2.5-3b-instruct"`，重新 `npm run dev`。  
   - 但 backend 里仍是 `DeepAnalyze-8B`，它在其他 API（如生成报告、执行代码）里也会用到 OpenAI 接口，所以最终还是要改 backend。

只要两个地方（backend + WebUI）统一成 vLLM 里实际的模型名字，所有 `/v1/chat/completions` 请求就会命中 Qwen，聊天不会再 404 卡住。

