# 断点续跑功能：从指定轮次重新执行

> 文档版本：v2.0 | 创建日期：2026-02-11 | 更新：2026-02-11（代码分析完成）

---

## 1. 需求背景

DeepAnalyze 的多轮分析流程（Round 1~10）完整执行一次需要 15~30 分钟。
其中 Round 1~7 为数据分析轮次（CSV 分析、SQLite 查询、多表关联等），产出 CSV 和 PNG 文件；
Round 8~10 为汇总轮次（README 生成、综合分析报告、最终 Answer）。

**痛点**：当 Round 8/9/10 的模板或配置调整后，需要从头重跑全部 10 轮，浪费大量时间。
实际上 Round 1~7 的产出文件（CSV、PNG）不需要重新生成，只需从 Round 8 开始重跑即可。

## 2. 需求定义

### 2.1 核心需求

- 用户在一次完整分析执行结束后，可以选择**从 Round 8 开始重新执行**（重新生成 README、综合分析报告、最终 Answer）
- 重跑时**复用** Round 1~7 已有的产出文件（CSV、PNG、execute_round_1~7.txt）
- 重跑时**删除**旧的 Round 8+ 产出文件（README.md、comprehensive_analysis_report.md、execute_round_8~10.txt），不做备份
- 重跑通过**页面按钮**触发，用户点击「重新生成报告」即可

### 2.2 用户场景

```
场景 1：模板调整后重跑
  用户修改了 backend_helpers.py 中的报告模板 → 点击「重新生成报告」→ 从 Round 8 开始重跑

场景 2：配置调整后重跑
  用户修改了 round_io_rules.json 中 Round 9/10 的 guidance → 点击「重新生成报告」→ 从 Round 8 开始重跑

场景 3：报告质量不满意
  用户查看生成的报告后不满意 → 点击「重新生成报告」→ 重新生成 README + 报告 + Answer
```

### 2.3 非需求（暂不实现）

- ❌ 从 Round 1~7 任意轮次重跑（未来可扩展）
- ❌ 保存完整对话历史 checkpoint（轻量方案不需要）
- ❌ 备份旧的产出文件到 .archive/（用户明确不需要）

## 3. 代码分析结果

### 3.1 系统调用链路

代码分析已完成，完整调用链路如下：

```
前端 Web UI (Next.js)                    后端 API + 执行引擎 (FastAPI)
demo/chat/                               demo/backend.py
┌────────────────────────┐               ┌──────────────────────────────┐
│ three-panel-interface  │               │ FastAPI app (port 8200)      │
│ .tsx                   │               │                              │
│                        │  POST         │ @app.post("/chat/completions")│
│ handleSendMessage() ──────────────────►│ async def chat(body):        │
│   fetch(CHAT_COMPLETIONS)│  NDJSON     │   for delta in bot_stream(): │
│   stream reader ◄──────────────────────│     yield json chunk         │
│                        │               │                              │
│ handleStop() ─────────────────────────►│ @app.post("/chat/stop")      │
│   fetch(CHAT_STOP)     │               │   trigger_stop_flag()        │
└────────────────────────┘               └──────────────────────────────┘
```

**关键发现**：

| 问题 | 结论 |
|------|------|
| **Q1：前端技术栈** | ✅ **Next.js + React + shadcn/ui + Tailwind**，位于 `demo/chat/` 目录。核心组件 `three-panel-interface.tsx`（3364 行），三栏布局：左侧文件树、中间对话、右侧代码编辑器 |
| **Q2：API 与 Backend 关系** | ✅ **同一进程**。`demo/backend.py` 既是 FastAPI 服务（端口 8200），又包含 `bot_stream()` 执行引擎。路由 `@app.post("/chat/completions")` 直接调用 `bot_stream(messages, workspace, session_id)` |
| **Q4：重跑时是否重新加载配置** | ✅ **是**。`round_io_rules.json` 在 `bot_stream()` 中通过 `get_round_rule()` 读取全局变量 `ROUND_IO_RULES`，该变量在模块加载时初始化。重跑时需要调用 `load_round_io_rules_config()` 刷新 |

### 3.2 关键文件清单

| 文件 | 角色 | 修改内容 |
|------|------|----------|
| `demo/backend.py` | FastAPI 服务 + 执行引擎 | 1. `bot_stream()` 增加 `resume_from` 参数<br>2. `/chat/completions` 路由透传 `resume_from`<br>3. 新增 `/chat/regenerate` 路由（专用） |
| `demo/backend_helpers.py` | 辅助函数 | 新增 `cleanup_rounds_from()` |
| `demo/chat/components/three-panel-interface.tsx` | Web UI 主组件 | 1. 新增「重新生成报告」按钮<br>2. 按钮点击调用 `/chat/regenerate` |
| `demo/chat/lib/config.ts` | API 配置 | 新增 `CHAT_REGENERATE` endpoint |

### 3.3 前端关键代码位置

```
three-panel-interface.tsx 关键位置：
├── L96-130    : Message / Step 等 TypeScript 接口定义
├── L140-160   : 状态变量（isTyping, sessionId, messages 等）
├── L2150-2349 : handleSendMessage() — 发送消息 + 流式接收
├── L2351-2369 : handleStop() — 停止执行
├── L2183-2198 : fetch(CHAT_COMPLETIONS) 请求体构造
└── L2331-2333 : 流式结束后刷新文件列表
```

### 3.4 后端关键代码位置

```
backend.py 关键位置：
├── L586-590   : FastAPI app 初始化
├── L2031-2234 : bot_stream() 函数入口 + 状态变量初始化
├── L2089      : execute_rounds = 0（需要在 resume 时设为 N-1）
├── L2219-2234 : schema bootstrap 逻辑（resume 时需跳过）
├── L2236-2240 : 主循环条件
├── L4635      : execute_rounds += 1（每轮执行后递增）
├── L5220-5262 : /chat/completions 路由（需透传 resume_from）
└── L5265-5269 : /chat/stop 路由
```

## 4. 架构设计

### 4.1 系统架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                     前端层 (Next.js)                          │
│                   demo/chat/ (port 4000)                      │
│                                                              │
│  three-panel-interface.tsx                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  对话结束后 → 显示「🔄 重新生成报告」按钮            │    │
│  │  点击 → fetch POST /chat/regenerate                  │    │
│  │         { session_id, resume_from: 8 }               │    │
│  │  流式接收 → 更新对话面板                              │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP (NDJSON stream)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              后端 API + 执行引擎 (FastAPI, port 8200)         │
│                     demo/backend.py                           │
│                                                              │
│  新增路由：                                                   │
│  @app.post("/chat/regenerate")                               │
│  async def regenerate(body):                                 │
│      session_id = body["session_id"]                         │
│      resume_from = body.get("resume_from", 8)                │
│      # 重新加载 round_io_rules.json（用户可能修改了配置）     │
│      reload_round_io_rules()                                 │
│      for delta in bot_stream(messages=[], workspace=[],      │
│                               session_id, resume_from):      │
│          yield NDJSON chunk                                  │
│                                                              │
│  bot_stream() 修改：                                          │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ if resume_from > 0:                                  │    │
│  │   1. cleanup_rounds_from(generated_dir, resume_from) │    │
│  │   2. messages = rebuild_minimal_context(workspace)   │    │
│  │   3. execute_rounds = resume_from - 1                │    │
│  │   4. schema_bootstrap_used = True (跳过 bootstrap)   │    │
│  │   5. 进入主循环，从 Round resume_from 开始           │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    文件系统层                                  │
│              workspace/generated/                             │
│                                                              │
│  保留（Round 1~7 产出）：                                     │
│  ├── execute_round_0_bootstrap.txt                           │
│  ├── execute_round_1.txt ~ execute_round_7.txt               │
│  ├── *.csv（enrolled_summary.csv, disabled_count.csv 等）    │
│  ├── *.png（enrolled_school_dist.png 等）                    │
│  └── multi_table_join_result.csv                             │
│                                                              │
│  删除后重新生成（Round 8~10 产出）：                          │
│  ├── execute_round_8.txt, execute_round_9.txt                │
│  ├── README.md                                               │
│  └── comprehensive_analysis_report.md                        │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 关键设计决策

| 决策点 | 方案 | 理由 |
|--------|------|------|
| 是否保存 checkpoint | **否** | Round 8+ 是模板驱动，不依赖对话历史 |
| 对话上下文恢复 | **从文件系统重建最小上下文** | 读取 bootstrap.txt + 文件清单即可 |
| 旧文件处理 | **直接删除** | 用户明确不需要备份 |
| 触发方式 | **Web 页面按钮** | 执行结束后显示「重新生成报告」 |
| 重跑起始轮次 | **固定 Round 8**（按钮默认） | 最常见场景；API 层支持任意 N |
| API 路由 | **新增 `/chat/regenerate`** | 与 `/chat/completions` 分离，语义清晰，避免污染正常对话流程 |
| 配置重载 | **重跑时重新加载 `round_io_rules.json`** | 用户可能修改了 Round 8/9/10 的 guidance |

### 4.3 核心函数设计

#### 4.3.1 `cleanup_rounds_from(generated_dir, from_round)` — 位于 `backend_helpers.py`

```python
def cleanup_rounds_from(generated_dir: Path, from_round: int) -> list[str]:
    """删除 >= from_round 的产出文件。

    删除规则：
    - execute_round_{N}.txt（N >= from_round）
    - README.md（Round 8 产出）
    - comprehensive_analysis_report*.md（Round 9 产出）

    不删除：
    - CSV 文件（Round 1~7 产出）
    - PNG 文件（Round 1~7 产出）
    - execute_round_0_bootstrap.txt

    Returns:
        被删除的文件名列表
    """
```

#### 4.3.2 `rebuild_minimal_context(workspace_path, session_id)` — 位于 `backend.py`

```python
def rebuild_minimal_context(workspace_path: Path, session_id: str) -> list[dict]:
    """从文件系统重建最小对话上下文，供 resume 使用。

    构建的 messages 列表：
    [
      { "role": "user",
        "content": "# Instruction\n请分析以下数据...\n\n# Data\n<workspace 文件信息>" },
      { "role": "assistant",
        "content": "<bootstrap 结果（从 execute_round_0_bootstrap.txt 读取）>" },
      { "role": "user",
        "content": "前 N-1 轮已完成。generated/ 下已有文件：\n- enrolled_summary.csv\n- ..." }
    ]

    关键点：
    - 第一条 user 消息包含 workspace 文件信息（与正常流程一致）
    - assistant 消息包含 bootstrap 结果（让模型知道数据库 schema 和路径）
    - 最后一条 user 消息包含 generated/ 文件清单（让模型知道已有产出）
    """
```

#### 4.3.3 `bot_stream(..., resume_from=0)` 修改 — 位于 `backend.py`

```python
def bot_stream(messages, workspace, session_id="default", resume_from: int = 0):
    """
    resume_from > 0 时的处理流程：
    1. 调用 cleanup_rounds_from(generated_dir, resume_from) 清理旧文件
    2. 调用 rebuild_minimal_context(workspace_path, session_id) 重建 messages
    3. 设置 execute_rounds = resume_from - 1
    4. 设置 non_schema_exec_rounds = resume_from - 2（扣除 bootstrap）
    5. 设置 schema_bootstrap_used = True, schema_confirmed = True
    6. 跳过 bootstrap 逻辑
    7. 进入主循环，从 Round resume_from 开始执行

    注意：resume 时 messages 参数被忽略，使用 rebuild_minimal_context() 的结果。
    """
```

#### 4.3.4 新增 API 路由 `/chat/regenerate` — 位于 `backend.py`

```python
@app.post("/chat/regenerate")
async def regenerate(body: dict = Body(...)):
    """重新生成报告（从指定轮次重跑）。

    请求体：
    {
        "session_id": "default",
        "resume_from": 8          // 可选，默认 8
    }

    响应：NDJSON 流式输出（与 /chat/completions 格式一致）
    """
```

### 4.4 前端交互设计

按钮位置：在对话面板底部输入框区域，当 `isTyping === false` 且对话中包含 `</Answer>` 时显示。

```
┌─────────────────────────────────────────────────────────────┐
│  中间面板（对话区域）                                        │
│                                                             │
│  ... 对话内容 ...                                           │
│                                                             │
│  <Answer>                                                   │
│  本次分析共完成 9 轮...                                      │
│  </Answer>                                                  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐    │
│  │  📎  Ask anything...                          ▶ ■  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────┐                        │
│  │  🔄 重新生成报告 (Round 8-10)  │  ← 新增按钮            │
│  └─────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

按钮行为：
1. **显示条件**：`!isTyping && messages 中包含 </Answer>`
2. **点击后**：按钮文字变为「正在重新生成...」+ 旋转图标，禁用状态
3. **请求**：`POST /chat/regenerate { session_id, resume_from: 8 }`
4. **流式接收**：在对话面板追加新的 AI 消息，实时显示 Round 8/9/10 输出
5. **完成后**：按钮恢复可点击状态，刷新文件列表

## 5. 实现路径

### Phase 1：Backend 层实现

| 步骤 | 文件 | 内容 |
|------|------|------|
| 1.1 | `demo/backend_helpers.py` | 新增 `cleanup_rounds_from()` 函数 |
| 1.2 | `demo/backend.py` | 新增 `rebuild_minimal_context()` 函数 |
| 1.3 | `demo/backend.py` | 修改 `bot_stream()` 增加 `resume_from` 参数和分支逻辑 |
| 1.4 | `demo/backend.py` | 新增 `reload_round_io_rules()` 函数（刷新全局配置） |
| 1.5 | `demo/backend.py` | 新增 `@app.post("/chat/regenerate")` 路由 |

### Phase 2：前端实现

| 步骤 | 文件 | 内容 |
|------|------|------|
| 2.1 | `demo/chat/lib/config.ts` | 新增 `CHAT_REGENERATE` endpoint |
| 2.2 | `demo/chat/components/three-panel-interface.tsx` | 新增 `isRegenerating` 状态变量 |
| 2.3 | 同上 | 新增 `handleRegenerate()` 函数（调用 `/chat/regenerate`，流式接收） |
| 2.4 | 同上 | 在输入框下方添加「重新生成报告」按钮 |

### Phase 3：端到端测试

1. 完整执行一次 Round 1~10
2. 点击「重新生成报告」
3. 验证 Round 8~10 正确重新生成
4. 验证旧文件被正确清理
5. 验证新报告内容正确
6. 验证文件列表刷新

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重建的最小上下文不够，模型偏离任务 | Round 8/9 生成质量下降 | Round 8/9 是模板驱动，模型只需按模板执行代码，对上下文依赖低 |
| Round 1~7 的 CSV/PNG 文件被误删 | 需要从头重跑 | `cleanup_rounds_from()` 只删除 execute_round_N.txt + README + 报告，不删 CSV/PNG |
| 并发重跑冲突 | 文件损坏 | 同一 session 同时只允许一个执行（已有 stop_flag 机制） |
| `round_io_rules.json` 修改后未生效 | 重跑使用旧配置 | 重跑前调用 `reload_round_io_rules()` 刷新全局配置 |

---

> 文档状态：✅ 代码分析完成，所有待确认事项已解答，可进入实现阶段
