# HTML 报告生成问题完整分析与修复文档

## 问题概述

**核心问题**：模型在执行 Student Loan 数据分析任务时，无法生成第 8、9 轮要求的 HTML 报告（`single_table_analysis.html` 和 `multi_table_analysis.html`），且在第 3 轮后提前输出 `<Answer>` 标签导致分析流程提前终止。

**预期行为**：
- 完成第 2-6 轮单表分析（生成 CSV + PNG）
- 完成第 7 轮多表关联分析
- **第 8 轮生成 `single_table_analysis.html`**
- **第 9 轮生成 `multi_table_analysis.html`**
- 第 10 轮输出 `<Answer>` 总结

**实际行为**：
- 第 1-3 轮正常执行，生成对应文件
- 第 3 轮后模型直接输出 `<Answer>` 标签
- 后续轮次未执行，HTML 报告未生成

---

## 根本原因分析

### 1. 提前终止的技术原因

**问题代码位置**：`demo/backend.py:1942-1971`

**原始逻辑缺陷**：
```python
if "</Answer>" in current_stream:
    if non_schema_exec_rounds == 0:  # ❌ 只检查是否执行过代码
        # 拦截提前输出
        premature_answer_detected = True
    else:
        finished = True  # ❌ 直接标记完成并退出
        break
```

**问题分析**：
- 条件 `non_schema_exec_rounds == 0` 只检查是否执行过非 schema 代码
- 当模型已执行 3 轮代码后，`non_schema_exec_rounds >= 1`
- 导致拦截逻辑失效，直接进入 `else` 分支标记为完成
- 跳过了后续的轮次检查逻辑（`execute_rounds < MIN_REQUIRED_ROUNDS`）

### 2. 模型行为分析

**为什么模型会提前输出 `<Answer>`**：

1. **提示词长度过长**（681 行）
   - 包含大量重复的禁止事项和示例代码
   - 模型容易在长上下文中迷失关键约束

2. **轮次进度不明确**
   - 提示词中虽然列出了 10 轮任务，但没有明确的"当前轮次"标记
   - 模型不清楚自己处于哪一轮，容易提前终止

3. **约束表达不够强硬**
   - 原提示词使用"禁止"、"必须"等词汇，但缺乏后果说明
   - 模型可能认为这只是建议而非强制要求

4. **后端拦截机制不完善**
   - 拦截后注入的提示不够具体
   - 没有明确告知"当前是第 X 轮，需要继续第 X+1 轮"

---

## 历史修复记录与代码检查

### 修复 1：强化提示词禁止语言（12月初）
**修改内容**：
- 在提示词开头增加 🚨 标记
- 强调"禁止在第 10 轮之前输出 `<Answer>`"
- 增加"系统会强制终止任务"的警告

**效果**：无效，模型仍在第 3 轮后输出 `<Answer>`

**失败原因**：提示词修改无法解决后端拦截逻辑缺陷

---

### 修复 2：后端增加提前输出检测（12月中旬）
**修改内容**：
- 在 `backend.py:2231-2252` 增加完成检查逻辑
- 检测 `execute_rounds < MIN_REQUIRED_ROUNDS` 时拒绝完成
- 注入继续执行提示

**效果**：无效，检测逻辑未被触发

**失败原因**：流式输出阶段的拦截逻辑（1942-1971 行）先执行，直接标记 `finished = True` 并 `break`，导致后续检查逻辑被跳过

---

### 修复 3：简化提示词结构（12月 20 日）
**修改内容**：
- 删除冗余的禁止事项列表
- 简化分析流程说明
- 减少示例代码长度

**效果**：无效，模型仍提前终止

**失败原因**：核心问题在后端逻辑，提示词优化无法解决

---

### 修复 4：强化空输出检测（12月 21 日）
**修改内容**：
- 在 `backend.py:2030-2091` 增强空输出检测
- 根据当前轮次动态生成具体任务提示
- 明确指定表名、字段和文件要求

**效果**：缓解了空输出循环问题，但未解决提前终止

**失败原因**：未触及提前 `<Answer>` 检测的核心缺陷

---

### 修复 5：修复提前 Answer 检测逻辑（12月 23 日上午）✅
**修改内容**：
```python
# 修改前
if non_schema_exec_rounds == 0:
    # 拦截
else:
    finished = True  # ❌ 直接完成
    break

# 修改后
MIN_REQUIRED_ROUNDS = 9  # ✅ 已修正为 9
if execute_rounds < MIN_REQUIRED_ROUNDS:  # ✅ 检查轮次
    # 拦截并注入详细提示
    premature_answer_detected = True
else:
    finished = True
    break
```

**修改位置**：`demo/backend.py:1942-1971` 和 `backend.py:2241-2259`

**预期效果**：
- 在流式输出阶段就拦截提前 `<Answer>`
- 注入明确的继续执行提示，包含具体轮次和任务
- 允许模型恢复并继续后续轮次

**实际效果**：❌ 无效，拦截逻辑仍未被触发

**失败原因**：修复 5 只修改了判断条件，但忽略了两个更深层的问题：
1. **流式输出检测顺序错误**：检测到 `</Code>` 就立即 `break`，永远不会执行到 `</Answer>` 检测
2. **execute_rounds 初始化错误**：Bootstrap 执行后 `execute_rounds` 仍为 0，导致计数不准确

---

### 修复 6：修复流式输出检测顺序 + execute_rounds 初始化（12月 23 日下午）✅

#### 问题 6.1：流式输出检测顺序错误

**问题代码**（`backend.py:1938-1944`）：
```python
# 检测到 </Code> 标签时立即停止流式接收
if "</Code>" in current_stream:
    logger.info(f"[bot_stream] Detected </Code>, stopping stream reception")
    break  # ❌ 立即退出，永远不会执行到下面的 </Answer> 检测

if "</Answer>" in current_stream:
    # 拦截逻辑（永远不会执行到这里）
```

**根本原因**：
- 当模型在同一轮输出 `<Code>...</Code>` 和 `<Answer>...</Answer>` 时
- 流式接收在检测到 `</Code>` 时就立即 `break`
- 导致 `</Answer>` 的拦截逻辑**永远不会被执行**
- 这就是为什么日志中**完全没有 "Premature Answer detected" 警告**的原因

**修复方案**：
```python
# 【重要】先检查 </Answer>，再检查 </Code>，避免提前 break 导致拦截失效
if "</Answer>" in current_stream:
    MIN_REQUIRED_ROUNDS = 9
    if execute_rounds < MIN_REQUIRED_ROUNDS:
        # 拦截逻辑
        premature_answer_detected = True
        ...
    else:
        finished = True
        break

# 检测到 </Code> 标签时立即停止流式接收
if "</Code>" in current_stream:
    logger.info(f"[bot_stream] Detected </Code>, stopping stream reception")
    break
```

**修改位置**：`backend.py:1937-1974`

#### 问题 6.2：execute_rounds 初始化错误

**问题代码**（`backend.py:1802-1815`）：
```python
if not schema_bootstrap_used:
    auto_block = run_schema_bootstrap(workspace_path, session_id)
    if auto_block:
        schema_bootstrap_used = True
        schema_confirmed = True
        messages.append({"role": "assistant", "content": auto_block})
        yield auto_block
        # ❌ Bootstrap 执行后 execute_rounds 仍为 0
```

**根本原因**：
- Bootstrap 生成 `execute_round_0_bootstrap.txt`，应该算作 round 0
- 但 `execute_rounds` 没有递增，仍然是 0
- 导致后续轮次计数不准确（第1轮代码执行后 `execute_rounds=1`，但实际应该是 2）

**修复方案**：
```python
if not schema_bootstrap_used:
    auto_block = run_schema_bootstrap(workspace_path, session_id)
    if auto_block:
        schema_bootstrap_used = True
        schema_confirmed = True
        messages.append({"role": "assistant", "content": auto_block})
        yield auto_block
        # Bootstrap 算作 execute_round_0，所以下一轮应该是 round 1
        execute_rounds = 1  # ✅ 修复初始化
        logger.info(
            f"[bot_stream] Schema bootstrap completed, execute_rounds={execute_rounds}"
        )
```

**修改位置**：`backend.py:1814`

#### 为什么之前没有发现这两个问题？

**原因分析**：

1. **修复 1-4 都聚焦在提示词和高层逻辑**
   - 修复 1-3：修改提示词，期望模型自己遵守约束
   - 修复 4：增强空输出检测，但没有触及拦截逻辑
   - 都没有深入分析**流式输出的执行顺序**

2. **修复 5 只看到了表面问题**
   - 发现了 `non_schema_exec_rounds == 0` 的判断条件错误
   - 但没有追问："为什么日志中完全没有拦截警告？"
   - 如果拦截逻辑被执行，即使条件错误，也应该有日志输出
   - **缺少对日志的深度分析**

3. **流式输出检测顺序问题非常隐蔽**
   - 代码逻辑看起来合理：检测到 `</Code>` 就停止接收，避免模型继续输出
   - 但忽略了：如果模型在 `</Code>` 之后立即输出 `<Answer>`，拦截逻辑会被跳过
   - 这种问题只有在**仔细追踪代码执行流程**时才能发现

4. **execute_rounds 初始化问题被忽略**
   - Bootstrap 的文件命名是 `execute_round_0_bootstrap.txt`
   - 但代码中 `execute_rounds` 初始化为 0，且 Bootstrap 后没有递增
   - 导致文件命名和变量值不一致
   - 之前的修复都假设 `execute_rounds` 计数是正确的

**教训**：
- ✅ **必须分析日志**：如果预期的日志没有出现，说明代码路径没有被执行
- ✅ **追踪执行流程**：不能只看代码逻辑，要追踪实际执行顺序
- ✅ **验证假设**：不能假设变量计数是正确的，要验证初始化和递增逻辑
- ✅ **关注边界情况**：流式输出的 `break` 语句会影响后续代码执行

**预期效果**：
- 流式输出阶段能正确检测到提前的 `<Answer>` 并拦截
- 日志中会出现 `Premature <Answer> detected` 警告
- `execute_rounds` 计数与文件命名一致
- 模型被拦截后能继续执行后续轮次

**实际效果**：❌ 无效,模型仍在第3轮后提前终止

**失败原因**：修复 6 解决了拦截逻辑的技术问题,但忽略了系统会**主动请求模型输出 Answer** 的机制。当 `execute_rounds >= ANSWER_MIN_EXEC_ROUNDS` 时,系统会注入提示要求模型输出 Answer,导致拦截逻辑根本不会被触发。

---

### 修复 7：修复系统主动请求 Answer 的阈值（12月 23 日下午）✅

#### 问题 7：系统在第3轮后主动请求模型输出 Answer

**问题代码**（`backend.py:150-151`）：
```python
ANSWER_MIN_EXEC_ROUNDS = 3
ANSWER_MIN_NON_SCHEMA_ROUNDS = 2
```

**根本原因**：
- Bootstrap 算作 `execute_round_0`,设置 `execute_rounds = 1`
- 第2轮(enrolled)执行后: `execute_rounds = 2`, `non_schema_exec_rounds = 1`
- 第3轮(enlist)执行后: `execute_rounds = 3`, `non_schema_exec_rounds = 2`
- 系统检测到 `execute_rounds >= 3` 且 `non_schema_exec_rounds >= 2`,**主动注入提示要求模型输出 Answer**
- 模型遵守系统指令,在下一轮输出 `<Answer>`,导致任务提前终止
- 因为是系统主动请求,所以**所有拦截逻辑都不会被触发**

**问题代码位置**（`backend.py:2988-2999`）：
```python
if (
    execute_rounds >= ANSWER_MIN_EXEC_ROUNDS
    and non_schema_exec_rounds >= ANSWER_MIN_NON_SCHEMA_ROUNDS
    and not answer_requested
):
    answer_requested = True
    answer_prompt = (
        "你已完成至少两轮代码执行。请停止继续编写 <Code>，在下一轮直接输出 <Answer>，"
        "总结上述 <Execute>/<File> 结果并给出后续建议。"
    )
    messages.append({"role": "user", "content": answer_prompt})
```

**为什么日志中没有拦截警告**：
- 系统主动请求 Answer,模型只是遵守指令
- 拦截逻辑只检测**提前输出**的 Answer,不检测**被请求输出**的 Answer
- `answer_requested = True` 后,系统期望模型输出 Answer,所以不会拦截

**修复方案**：
```python
ANSWER_MIN_EXEC_ROUNDS = 10  # 确保完成第 2-9 轮分析后才请求 Answer
ANSWER_MIN_NON_SCHEMA_ROUNDS = 8  # 对应 8 轮非 schema 代码执行(第 2-9 轮)
```

**修改位置**：`backend.py:150-151`

**轮次对应关系**：
- Bootstrap: `execute_rounds = 1`, `non_schema_exec_rounds = 0`
- 第2轮(enrolled): `execute_rounds = 2`, `non_schema_exec_rounds = 1`
- 第3轮(no_payment_due): `execute_rounds = 3`, `non_schema_exec_rounds = 2`
- ...
- 第9轮(multi_table_analysis HTML): `execute_rounds = 9`, `non_schema_exec_rounds = 8`
- 第9轮执行完成后: `execute_rounds = 10`, `non_schema_exec_rounds = 8`
- 此时系统才会主动请求 Answer

**预期效果**：
- 系统在完成第 2-9 轮分析后才主动请求 Answer
- 模型不会在第3轮后被系统要求输出 Answer
- 拦截逻辑作为防御机制,处理模型自发的提前 Answer

**实际效果**：❌ 可能仍然无效

**潜在问题**：修复 7 只解决了 `@backend.py:2988-2999` 处的主动请求机制,但忽略了 `answer_requested` 标志在代码中有**多个触发点**:

1. **`@backend.py:2340-2350`**: 当模型输出 `</Code>` 且 `answer_requested = True` 时,系统会注入提示要求模型输出 Answer
2. **`@backend.py:2284-2290`**: 当模型没有输出 `<Code>` 且 `answer_requested = True` 时,系统会提醒模型输出 Answer

这意味着即使 `ANSWER_MIN_EXEC_ROUNDS = 10`,如果 `answer_requested` 在其他地方被设置为 `True`,仍然会触发提前请求 Answer 的机制。

---

### 修复 8：在 answer_requested 使用点增加轮次检查（12月 23 日下午）✅

#### 问题 8：answer_requested 标志的多重触发机制

**根本原因**：
`answer_requested` 标志在代码中有多个使用点,即使修改了设置阈值,仍然可能在其他地方被设置为 `True`,导致系统提前请求 Answer。

**所有触发点**：
1. `@backend.py:2988-2999`: 当 `execute_rounds >= ANSWER_MIN_EXEC_ROUNDS` 时设置
2. `@backend.py:2340-2350`: 当 `answer_requested = True` 时继续请求
3. `@backend.py:2284-2290`: 当 `answer_requested = True` 且缺少 Code 时继续请求

**为什么这是一个问题**：
- 即使 `ANSWER_MIN_EXEC_ROUNDS = 10`,如果模型在某一轮没有输出 `<Code>`,系统会进入 `@backend.py:2284` 的逻辑
- 如果此时 `answer_requested = True`(可能是之前的轮次设置的),系统会继续请求 Answer
- 这就解释了为什么模型在第3轮后输出了一个没有 `<Code>` 的轮次,然后被要求输出 Answer

**最佳解决方案**：

对于这个特定任务(必须完成 10 轮分析),**应该完全禁用 `answer_requested` 机制**,让模型严格按照提示词执行,只在第 10 轮才输出 Answer。

**已实施的修复方案**：

在 `answer_requested` 的两个使用点增加轮次检查，确保只有在达到最小轮次后才响应 `answer_requested` 标志。

**修改位置 1**：`backend.py:2284-2292` (缺少 Code 时的处理)
```python
# 修改前
if answer_requested:
    answer_waiting_rounds += 1
    reminder = (...)
    messages.append({"role": "user", "content": reminder})

# 修改后
MIN_REQUIRED_ROUNDS = 9
if answer_requested and execute_rounds >= MIN_REQUIRED_ROUNDS:
    answer_waiting_rounds += 1
    reminder = (...)
    messages.append({"role": "user", "content": reminder})
```

**修改位置 2**：`backend.py:2342-2348` (有 Code 时的处理)
```python
# 修改前
if answer_requested:
    messages.append({"role": "assistant", "content": cur_res})
    reminder = (...)
    messages.append({"role": "user", "content": reminder})

# 修改后
MIN_REQUIRED_ROUNDS = 9
if answer_requested and execute_rounds >= MIN_REQUIRED_ROUNDS:
    messages.append({"role": "assistant", "content": cur_res})
    reminder = (...)
    messages.append({"role": "user", "content": reminder})
```

**修复逻辑**：
- 保留 `answer_requested` 机制的灵活性
- 但增加 `execute_rounds >= MIN_REQUIRED_ROUNDS` 的检查
- 确保即使 `answer_requested = True`,也只有在完成第 2-9 轮后才会请求 Answer

**预期效果**：
- 系统不会在第 3 轮后请求 Answer
- 即使模型在某一轮没有输出 `<Code>`,也不会触发提前请求
- 模型将严格按照提示词完成 10 轮分析

**实际效果**：❌ 无效,模型在第7轮陷入无限循环

**失败原因**：修复 8 解决了 `answer_requested` 的多重触发问题,但忽略了**表验证逻辑**的缺陷。系统在第7轮(多表关联分析)错误地将 SQL 别名 (`e`, `n`, `d`) 和输出文件名 (`correlation_analysis`) 识别为"不存在的表",导致模型陷入无限循环,无法继续执行。

---

### 修复 9：修复表验证逻辑,排除 SQL 别名和文件名（12月 23 日下午）✅

#### 问题 9：表验证逻辑错误地拦截 SQL 别名和文件名

**问题现象**：
从用户提供的前端反馈可以看到,模型在第7轮(多表关联分析)陷入无限循环:
```
Assistant 当前目标=第 7 轮分析，分析 多表关联分析...
```

系统反复输出:
```
请根据真实表结构，修正错误字段引用。
```

**生成文件情况**：
- ✅ 第2-6轮: 所有 CSV 和 PNG 文件正常生成
- ❌ 第7轮及之后: 没有任何文件生成
- ❌ 没有 HTML 报告

**根本原因**：

`extract_table_mentions_from_text` 函数 (`@backend.py:382-852`) 用于从 `<Analyze>` 文本中提取表名,并验证这些表是否存在于数据库中。该函数使用正则表达式 `TABLE_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")` 匹配所有字母开头的标识符。

虽然函数有一个很长的 `COMMON_WORDS` 列表来过滤常见词汇,但**缺少以下关键过滤**:

1. **SQL 别名** (`e`, `n`, `d`): 在多表 JOIN 语句中,这些单字母别名是标准用法,但不在 `COMMON_WORDS` 中
2. **输出文件名** (`correlation_analysis`): 虽然有文件后缀过滤 (`_summary`, `_dist` 等),但 `correlation_analysis` 不符合这些模式

**问题代码位置**：`backend.py:2216-2225`
```python
if schema_confirmed and unknown_mentions:
    messages.append({"role": "assistant", "content": cur_res})
    warn_unknown = (
        "检测到你引用了不存在于实际 SQLite 中的表："
        + ", ".join(sorted(unknown_mentions))
        + "。请重新查看 sqlite_master 结果，仅使用真实表名。"
    )
    messages.append({"role": "user", "content": warn_unknown})
    refund_iteration()
    continue
```

当模型在 `<Analyze>` 中提到 SQL 别名或文件名时,系统错误地将它们识别为"不存在的表",注入警告并退还迭代,导致模型陷入无限循环。

**修复方案**：

在 `COMMON_WORDS` 中添加:
1. **所有单字母 SQL 别名** (a-z)
2. **常见的分析文件名前缀** (`correlation_analysis`, `multi_table_analysis`, `single_table_analysis` 等)

**修改位置 1**：`backend.py:392-394` (添加 SQL 别名)
```python
# 修改前
COMMON_WORDS = {
    "sqlite_master",
    "sqlite_sequence",
    # SQL 关键字和函数
    "select",
    ...

# 修改后
COMMON_WORDS = {
    "sqlite_master",
    "sqlite_sequence",
    # SQL 别名 (单字母 a-z，常用于 JOIN 语句)
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    # SQL 关键字和函数
    "select",
    ...
```

**修改位置 2**：`backend.py:524-529` (添加文件名前缀)
```python
# 修改前
# 分析相关
"analysis",
"distribution",
"statistics",
"correlation",
"trend",
...

# 修改后
# 分析相关
"analysis",
"distribution",
"statistics",
"correlation",
"correlation_analysis",  # 多表关联分析文件名
"multi_table",
"single_table",
"multi_table_join",
"multi_table_analysis",
"single_table_analysis",
"trend",
...
```

**修复逻辑**：
- 将所有可能在 SQL 语句中出现的单字母别名加入过滤列表
- 将所有可能在分析文本中出现的文件名前缀加入过滤列表
- 确保 `extract_table_mentions_from_text` 只标记真正的表名,而不是 SQL 语法元素或文件名

**预期效果**：
- 模型在第7轮能正常执行多表关联分析,使用 SQL 别名不会被拦截
- 模型在 `<Analyze>` 中提到输出文件名不会被误判为表名
- 第7-9轮能正常生成文件,包括 HTML 报告
- 第10轮输出 `<Answer>` 总结

**实际效果**：✅ 部分有效,❌ 新问题出现

**测试结果**:
- ✅ 修复 9 已生效:模型在第7轮成功尝试执行多表关联分析,没有被表名验证拦截
- ✅ 第2-6轮文件全部正常生成
- ❌ 第7轮代码执行失败:模型使用了不存在的字段名
  - `longest_absense_from_school`: 使用 `days` (实际是 `month`)
  - `enlist`: 使用 `enlisted` (实际是 `organ`)
- ❌ SQL 错误信息不够清晰,模型无法理解并修正
- ❌ 没有 HTML 报告生成

**失败原因**:修复 9 解决了表名验证问题,但暴露了新问题:**后端缺少针对 SQL 字段错误的智能检测和反馈机制**。当 SQL 查询因字段不存在而失败时,错误信息被包含在 `<Execute>` 输出中,但没有被特殊标记或解析,模型无法理解"no such column"错误的含义,导致反复尝试相同的错误代码。

---

### 修复 10:增强 SQL 字段错误检测和反馈(12月 24 日上午)✅

#### 问题 10:SQL 字段错误缺少智能检测和明确反馈

**问题现象**:
从用户提供的测试结果可以看到,模型在第7轮(多表关联分析)使用了不存在的字段:

```python
# 模型错误地使用了这些字段:
longest_absense_df = pd.read_sql_query("SELECT name, days FROM longest_absense_from_school", conn)
enlist_df = pd.read_sql_query("SELECT name, enlisted FROM enlist", conn)
```

但根据 Bootstrap 输出,实际字段是:
- `longest_absense_from_school`: `name, month` (不是 `days`)
- `enlist`: `name, organ` (不是 `enlisted`)

这导致 SQL 查询报错,但模型无法理解错误并修正。

**根本原因**:

后端已有通用错误检测机制 (`@backend.py:2970-3003`),但**不够精准**:

1. **缺少 SQL 字段错误的特殊处理**:当检测到 `no such column` 或 `OperationalError` 时,只给出通用错误提示
2. **错误信息不够明确**:没有自动展示数据库真实表结构,模型需要自己回忆 Bootstrap 输出
3. **反馈不够直接**:模型无法快速定位是哪个字段名错误,需要反复尝试

**问题代码位置**:`backend.py:2970-3003`

原有的错误检测逻辑:
```python
if has_error:
    # 提取错误类型和关键信息
    error_lines = [...]
    error_hint = error_lines[-1] if error_lines else "未知错误"
    
    error_warning = (
        f"代码执行过程中出现错误:{error_hint}\n\n"
        "请仔细检查上方 <Execute> 块中的完整错误信息,常见问题包括:\n"
        "1. 对字符串字段调用数值计算方法(如 df.corr())\n"
        "2. 使用不存在的字段名或表名\n"
        "3. 数据类型不匹配\n"
        "4. 缺少必要的数据预处理步骤\n\n"
        "请修正代码后重新提交。如果部分代码已成功执行,可以基于已生成的文件继续分析。"
    )
```

这个提示**过于通用**,对于 SQL 字段错误没有针对性。

**修复方案**:

在现有错误检测的基础上,增加对 `no such column` 和 `OperationalError` 的特殊处理:

1. **检测 SQL 字段错误**:识别 `no such column` 或 `operationalerror` 关键词
2. **自动提取表结构**:调用 `summarize_sqlite_schema(workspace_path)` 获取真实表结构
3. **生成明确的错误提示**:直接展示数据库真实表结构,指导模型修正字段名

**修改位置**:`backend.py:2992-3006` (在原有错误检测逻辑中增加分支)

```python
# 修改后
if has_error:
    logger.warning(
        f"[bot_stream] Code execution error detected (files generated: {len(artifact_paths)})"
    )
    # 提取错误类型和关键信息
    error_lines = [
        line
        for line in exe_output.split("\n")
        if any(
            kw in line.lower()
            for kw in ["error", "exception", "traceback"]
        )
    ]
    error_hint = error_lines[-1] if error_lines else "未知错误"

    # 特殊处理:SQL 字段错误
    if "no such column" in exe_output.lower() or "operationalerror" in exe_output.lower():
        # 提取表结构信息
        schema_hint = summarize_sqlite_schema(workspace_path)
        error_warning = (
            f"⚠️ SQL 查询错误:{error_hint}\n\n"
            "**错误原因**:代码中使用了不存在的字段名。\n\n"
            "**数据库真实表结构**:\n"
            f"{schema_hint}\n\n"
            "**修正方法**:\n"
            "1. 仔细对照上方的表结构,确认每个表的真实字段名\n"
            "2. 修改 SQL 查询中的字段名,使用真实存在的字段\n"
            "3. 不要臆测字段名,必须严格使用 sqlite_master 和 PRAGMA table_info 返回的字段\n\n"
            "请立即修正代码并重新提交。"
        )
    else:
        # 通用错误处理
        error_warning = (
            f"代码执行过程中出现错误:{error_hint}\n\n"
            "请仔细检查上方 <Execute> 块中的完整错误信息,常见问题包括:\n"
            "1. 对字符串字段调用数值计算方法(如 df.corr())\n"
            "2. 使用不存在的字段名或表名\n"
            "3. 数据类型不匹配\n"
            "4. 缺少必要的数据预处理步骤\n\n"
            "请修正代码后重新提交。如果部分代码已成功执行,可以基于已生成的文件继续分析。"
        )
    messages.append({"role": "user", "content": error_warning})
    refund_iteration()
    continue
```

**修复逻辑**:
- 检测到 SQL 字段错误时,自动调用 `summarize_sqlite_schema` 提取表结构
- 在错误提示中直接展示所有表的真实字段,无需模型回忆 Bootstrap 输出
- 提供明确的修正步骤,指导模型对照表结构修改字段名
- 强调"不要臆测字段名",必须使用真实字段

**预期效果**:
- 模型在第7轮遇到字段错误时,能立即看到完整的表结构
- 模型能快速定位错误字段,修正为正确的字段名
- 第7轮能成功执行多表关联分析,生成相关文件
- 第8-9轮能正常生成 HTML 报告
- 第10轮输出 `<Answer>` 总结

---

## 代码检查结果（2024-12-23）

### ✅ 后端代码已满足要求

#### 1. 核心修复已完成 ✅

**位置**：`backend.py:1942-1971`

```python
if "</Answer>" in current_stream:
    MIN_REQUIRED_ROUNDS = 9  # ✅ 已修正为 9，确保第 8、9 轮的 HTML 报告都已生成
    if execute_rounds < MIN_REQUIRED_ROUNDS:
        premature_answer_rounds += 1
        messages.append({"role": "assistant", "content": current_stream})
        warn_msg = (
            f"⚠️ 检测到提前输出 <Answer>：当前仅完成 {execute_rounds} 轮分析，"
            f"但任务要求完成至少 {MIN_REQUIRED_ROUNDS} 轮。\n\n"
            "**必须继续执行以下轮次**：\n"
            "- 第 2-6 轮：单表分析（enrolled, no_payment_due, longest_absense_from_school, enlist, disabled）\n"
            "- 第 7 轮：多表关联分析\n"
            "- 第 8 轮：生成单表分析 HTML 报告（single_table_analysis.html）\n"
            "- 第 9 轮：生成多表关联 HTML 报告（multi_table_analysis.html）\n"
            "- 第 10 轮：输出最终 <Answer>\n\n"
            f"**请立即继续第 {execute_rounds + 1} 轮分析，禁止输出 <Answer>。**"
        )
        messages.append({"role": "user", "content": warn_msg})
        current_stream = current_stream.replace("<Answer>", "<Answer (ignored)>")
        premature_answer_detected = True
        if premature_answer_rounds >= 3:
            forced_reason = f"连续 3 次尝试提前输出 <Answer>（当前 {execute_rounds} 轮，要求 {MIN_REQUIRED_ROUNDS} 轮），任务被终止"
            finished = True
            break
    else:
        finished = True
        break
```

**✅ 确认**：
- 已将判断条件从 `non_schema_exec_rounds == 0` 改为 `execute_rounds < MIN_REQUIRED_ROUNDS`
- `MIN_REQUIRED_ROUNDS = 9`（已修正，确保第 8、9 轮的 HTML 报告都已生成）
- 注入的警告消息明确列出了第 8、9 轮的 HTML 报告要求
- 正确标记 `premature_answer_detected = True`
- 连续 3 次提前输出会强制终止

#### 2. 双重检查机制 ✅

**位置**：`backend.py:2241-2259`

```python
if finished:
    MIN_REQUIRED_ROUNDS = 9  # ✅ 已修正为 9
    if execute_rounds < MIN_REQUIRED_ROUNDS:
        logger.warning(
            f"[bot_stream] Premature <Answer> detected: execute_rounds={execute_rounds}, required={MIN_REQUIRED_ROUNDS}"
        )
        messages.append({"role": "assistant", "content": cur_res})
        reject_msg = (
            f"⚠️ 检测到提前终止：当前仅完成 {execute_rounds} 轮分析，"
            f"但任务要求完成至少 {MIN_REQUIRED_ROUNDS} 轮。\n\n"
            "**必须继续执行以下轮次**：\n"
            "- 第 2-6 轮：单表分析（enrolled, no_payment_due, longest_absense_from_school, enlist, disabled）\n"
            "- 第 7 轮：多表关联分析\n"
            "- 第 8 轮：生成单表分析 HTML 报告（single_table_analysis.html）\n"
            "- 第 9 轮：生成多表关联 HTML 报告（multi_table_analysis.html）\n"
            "- 第 10 轮：输出最终 <Answer>\n\n"
            f"**请立即继续第 {execute_rounds + 1} 轮分析，禁止输出 <Answer>。**"
        )
        messages.append({"role": "user", "content": reject_msg})
        refund_iteration()
        finished = False
        continue
```

**✅ 确认**：
- 提供了二次检查机制（防御性编程）
- 即使第一处检查失效，这里也会拦截
- 正确重置 `finished = False` 并 `continue`

#### 3. 轮次计数逻辑 ✅

**位置**：`backend.py:1749-1750, 2922-2924`

```python
# 初始化
execute_rounds = 0  # 总执行轮次
non_schema_exec_rounds = 0  # 非 schema 执行轮次

# 计数逻辑
execute_rounds += 1
if not is_schema_code:
    non_schema_exec_rounds += 1
```

**✅ 确认**：
- `execute_rounds` 包含所有代码执行（含 bootstrap）
- `non_schema_exec_rounds` 只计算非 schema 代码
- 计数逻辑正确

**轮次对应关系**：
- Bootstrap（第 1 轮）：`execute_rounds = 1`
- 第 2 轮分析：`execute_rounds = 2`
- 第 3 轮分析：`execute_rounds = 3`
- ...
- 第 8 轮生成 HTML：`execute_rounds = 8`
- 第 9 轮生成 HTML：`execute_rounds = 9`
- 第 10 轮输出 Answer：`execute_rounds = 10`

因此 `MIN_REQUIRED_ROUNDS = 9` 确保第 8、9 轮都完成后才允许输出 Answer。

### ✅ 提示词检查结果

#### 1. 核心约束 ✅

**位置**：`prompt_complete.txt:5-11`

```
**🚨 绝对禁止提前输出 Answer 🚨**

**你必须完成 9 轮分析（第 2-10 轮），只有在第 10 轮才能输出 `<Answer>`。**

**如果你在第 10 轮之前输出 `<Answer>`，系统会强制终止任务并报错。**

现在立即开始第 2 轮分析，不要等待用户指令。
```

**✅ 确认**：明确禁止提前输出 Answer，强调系统会强制终止

#### 2. 分析流程 ✅

**位置**：`prompt_complete.txt:82-92`

明确列出 10 轮任务，包括：
- 第 2-6 轮：单表分析
- 第 7 轮：多表关联分析
- **第 8 轮：生成 single_table_analysis.html**
- **第 9 轮：生成 multi_table_analysis.html**
- 第 10 轮：输出 `<Answer>`

#### 3. 潜在改进建议 ⚠️

**问题**：提示词缺少 HTML 生成代码示例

**风险**：模型可能不知道如何生成 HTML 文件，导致：
1. 不生成文件
2. 生成格式错误的文件
3. 陷入空输出循环

**建议**（可选）：在第 8、9 轮的任务说明中增加 HTML 生成代码示例

---

## 最终解决方案（已完成）

### 1. 后端逻辑修复（✅ 已完成）

**修改位置**：
- `backend.py:1942-1971`（流式输出阶段检测）
- `backend.py:2241-2259`（完成阶段二次检查）

**关键修改**：
1. 将判断条件从 `non_schema_exec_rounds == 0` 改为 `execute_rounds < MIN_REQUIRED_ROUNDS`
2. 将 `MIN_REQUIRED_ROUNDS` 从 8 修正为 9
3. 注入详细的拒绝消息，明确列出第 8、9 轮的 HTML 报告要求
4. 实现双重检查机制（流式输出 + 完成检查）

### 2. 提示词改进建议（可选）

**建议 A：增加 HTML 生成代码示例**

在 `prompt_complete.txt:604-612` 的第 8、9 轮任务说明后增加：

```python
### 第 8 轮：生成单表分析 HTML 报告
**任务**：汇总第 2-6 轮的单表分析结果
**输出文件**：`single_table_analysis.html`

**代码示例**：
```python
from pathlib import Path

OUTPUT_DIR = Path("generated")
html_content = """
<!DOCTYPE html>
<html>
<head><title>单表分析报告</title></head>
<body>
<h1>单表分析报告</h1>
<h2>1. enrolled 表分析</h2>
<img src="enrolled_school_dist.png" width="600">
<h2>2. no_payment_due 表分析</h2>
<img src="no_payment_due_bool_dist.png" width="600">
<!-- 继续添加其他表的分析结果 -->
</body>
</html>
"""
with open(OUTPUT_DIR / "single_table_analysis.html", "w", encoding="utf-8") as f:
    f.write(html_content)
```
```

**建议 B：如果仍有问题，可考虑**
- 增加轮次进度追踪提示
- 进一步简化提示词结构
- 删除冗余的示例代码

---

## 验证步骤

### 1. 重启后端服务
```bash
cd ~/DeepAnalyze/demo
# 停止当前服务（Ctrl+C）
conda activate deepanalyze
python backend.py
```

### 2. 创建新会话测试
1. 访问前端页面
2. 创建新会话
3. 上传 `student_loan.sqlite` 和相关 CSV 文件
4. 上传 `prompt_complete.txt`

### 3. 观察关键指标
- [ ] 第 1 轮：Bootstrap 正常执行，显示数据库路径
- [ ] 第 2-6 轮：单表分析，生成对应 CSV 和 PNG
- [ ] 第 7 轮：多表关联分析
- [ ] **第 8 轮：生成 `single_table_analysis.html`**
- [ ] **第 9 轮：生成 `multi_table_analysis.html`**
- [ ] 第 10 轮：输出 `<Answer>` 总结
- [ ] 检查 `generated/` 目录是否包含所有文件

### 4. 检查日志
```bash
tail -f ~/DeepAnalyze/demo/logs/backend.log | grep -E "execute_rounds|premature|Answer"
```

关键日志：
- `[bot_stream] Premature <Answer> detected: execute_rounds=X, required=8`
- `⚠️ 检测到提前输出 <Answer>`（说明拦截生效）
- `请立即继续第 X 轮分析`（说明注入提示成功）

---

## 如果问题仍然存在

### 诊断清单

1. **确认后端代码已更新**
   ```bash
   grep -n "MIN_REQUIRED_ROUNDS = 9" ~/DeepAnalyze/demo/backend.py
   # 应该在 1943 行和 2243 行都出现
   ```

2. **检查模型是否被拦截**
   - 查看日志是否有 `Premature <Answer> detected`
   - 查看前端是否显示 `<Answer (ignored)>`

3. **检查拦截后模型响应**
   - 模型是否继续输出新的 `<Analyze>` 和 `<Code>`
   - 还是陷入空输出循环

4. **检查执行轮次计数**
   ```bash
   grep "execute_rounds=" ~/DeepAnalyze/demo/logs/backend.log | tail -20
   ```

### 备用方案

如果修复 5 仍无效，可能需要：

1. **增加更强的拦截机制**
   - 在检测到 `<Answer>` 时直接截断流式输出
   - 强制注入 `</Code>` 标签并执行当前轮次

2. **修改模型温度参数**
   - 降低 `temperature` 从 0.3 到 0.1
   - 增加 `top_p` 限制

3. **使用更强的模型**
   - 当前模型可能理解能力不足
   - 考虑使用 GPT-4 或 Claude 等更强模型

4. **拆分任务**
   - 不要求一次完成 10 轮
   - 分为 3 个子任务：单表分析、多表分析、报告生成

---

## 总结

**核心问题**：后端拦截逻辑使用了错误的判断条件（`non_schema_exec_rounds == 0`），导致在模型执行过代码后拦截失效。

**根本原因**：流式输出阶段的检测逻辑先于完成检查逻辑执行，且使用了不正确的判断条件。

**最终修复**：将判断条件改为 `execute_rounds < MIN_REQUIRED_ROUNDS`，在流式输出阶段就正确拦截提前 `<Answer>`。

**验证方法**：重启后端，创建新会话，观察是否能完成全部 10 轮并生成 HTML 报告。

**如果仍失败**：按照"诊断清单"和"备用方案"逐步排查。

---

## 附录：相关文件位置

- 后端主逻辑：`d:/Python-Learning/deepanalyze/demo/backend.py`
- 提示词文件：`d:/Python-Learning/deepanalyze/example/analysis_on_student_loan/prompt_complete.txt`
- 日志文件：`~/DeepAnalyze/demo/logs/backend.log`
- 生成文件目录：`~/DeepAnalyze/demo/workspace/session_*/generated/`

---

---

### 修复 11:修复路径组件和输出文件名误识别问题(12月 25 日上午)✅

#### 问题 11.1:路径组件被误识别为表名

**问题现象**:
从用户提供的第一次测试日志可以看到:
```
Table mentions extracted: known={'enrolled'}, 
unknown={'home', 'tdz', 'DeepAnalyze', 'session_1766573444371_fe69bw4jk', 'demo', 'workspace', 'student_loan'}
```

**根本原因**:
上次修改提示词后,模型在 `<Analyze>` 中输出了更详细的说明,包括完整的数据库路径:
```
数据来源：SQLite 数据库，路径已确认为 /home/tdz/DeepAnalyze/demo/workspace/session_xxx/student_loan.sqlite
```

`extract_table_mentions_from_text` 函数使用正则表达式 `TABLE_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")` 提取所有标识符,包括路径中的目录名。这些目录名不在 `COMMON_WORDS` 过滤列表中,被误识别为"未知表名",导致代码被拒绝。

**修复方案**:
在 `COMMON_WORDS` 中添加常见的文件路径组件:

**修改位置**:`backend.py:854-891`
```python
# 文件路径相关（防止将路径中的目录名误识别为表名）
"home", "user", "users", "root", "tmp", "var", "opt", "usr", "bin", "lib", "etc",
"mnt", "media", "srv", "workspace", "workspaces", "demo", "example", "examples",
"test", "tests", "src", "source", "app", "apps", "project", "projects", "data",
"dataset", "datasets", "deepanalyze", "DeepAnalyze", "tdz", "session",
"student_loan", "loan", "student",
```

**预期效果**:
- 路径中的目录名不再被误识别为表名
- 第2轮能正常执行,生成 `enrolled_summary.csv` 和 `enrolled_school_dist.png`

**实际效果**:✅ 部分有效,❌ 新问题出现

#### 问题 11.2:输出文件名被误识别为表名

**问题现象**:
从用户提供的第二次测试日志可以看到:
```
iteration=2 analyze_signature=当前目标=第 4 轮分析，分析 enrolled 表中 school 与 month 的联合分布...
Table mentions extracted: known={'enrolled', 'no_payment_due', 'bool'}, 
unknown={'enrolled_school_month_heatmap'}
```

**根本原因**:
- 修复 11.1 生效,路径组件不再被误识别
- 第2轮成功执行,生成了预期文件
- 但模型在第2轮后,没有继续分析第3轮的 `no_payment_due` 表
- 而是尝试"第4轮分析 enrolled 表的多维度",并在 `<Analyze>` 中提到输出文件名 `enrolled_school_month_heatmap`
- 这个文件名不在 `COMMON_WORDS` 中,被误识别为"未知表名",导致代码被拒绝
- 模型陷入循环,反复尝试但无法继续

**修复方案**:
在 `COMMON_WORDS` 中添加常见的输出文件名组合:

**修改位置**:`backend.py:892-916`
```python
# 常见的输出文件名组合（防止将文件名误识别为表名）
"enrolled_summary", "enrolled_school_dist", "enrolled_school_month_heatmap",
"enrolled_month_dist", "no_payment_due_summary", "no_payment_due_bool_dist",
"longest_absense_summary", "longest_absense_month_dist", "enlist_summary",
"enlist_organ_dist", "disabled_summary", "disabled_dist",
"correlation_analysis", "multi_table_join", "single_table_analysis",
"multi_table_analysis", "school_month_heatmap", "bool_dist", "organ_dist",
"month_dist", "school_dist", "school_count", "person_summary", "person_dist",
```

**预期效果**:
- 输出文件名不再被误识别为表名
- 模型能继续执行后续轮次

**实际效果**:⏳ 待重启后端服务验证

#### 问题 11.3:模型理解偏差 - 重复分析同一个表

**问题现象**:
从测试日志可以看出,模型在第2轮成功后,没有按照"第2轮→第3轮→第4轮"的顺序执行,而是尝试"第4轮分析 enrolled 的多维度"。

**根本原因分析**:

1. **提示词结构问题**:
   - 提示词在第 85-95 行列出了分析流程
   - 在第 97-194 行详细说明了第 2-6 轮的任务
   - 在第 578-640 行又重复列出了每一轮的详细任务
   - **但缺少明确的"每轮只分析一个表,完成后立即进入下一轮"的约束**

2. **模型行为分析**:
   - 模型看到第2轮要求"分析 enrolled 表的学校分布"
   - 成功生成了 `enrolled_summary.csv` 和 `enrolled_school_dist.png`
   - 但模型可能认为"学校分布"只是一个维度,还需要分析"学校与月份的联合分布"
   - 因此尝试继续深入分析 enrolled 表,而不是切换到下一个表

3. **提示词中的歧义**:
   - 第 103 行:`enrolled.csv`（字段：name, school, month）→ 分析学校分布和入学时间分布
   - 这可能让模型认为需要分析"学校分布"和"入学时间分布"两个维度
   - 但实际上只需要生成一个 CSV 和一个 PNG 即可

**修复方案**:

需要在提示词中增加更明确的约束:

1. **明确每轮只生成指定的文件**:
   ```
   - 第 2 轮：分析 enrolled 表，生成 enrolled_summary.csv 和 enrolled_school_dist.png，然后立即进入第 3 轮
   - 禁止对同一个表进行多次分析
   - 禁止跳过任何轮次
   ```

2. **在每轮任务说明后增加"完成标准"**:
   ```
   第 2 轮完成标准：
   - ✅ 生成 enrolled_summary.csv
   - ✅ 生成 enrolled_school_dist.png
   - ✅ 立即进入第 3 轮，分析 no_payment_due 表
   ```

3. **删除可能引起歧义的描述**:
   - 将"分析学校分布和入学时间分布"改为"分析学校分布"
   - 避免让模型认为需要分析多个维度

**预期效果**:
- 模型能严格按照第 2→3→4→5→6→7→8→9→10 轮的顺序执行
- 每轮只分析一个表,生成指定的文件后立即进入下一轮
- 不会重复分析同一个表

**实际效果**:⏳ 待修改提示词并测试

---

## 测试结果总结(2024-12-25)

### 第一次测试(修复 11.1 前)
- ❌ 路径组件被误识别为表名
- ❌ 模型卡在第2轮,无法继续
- ❌ 没有生成任何分析文件

### 第二次测试(修复 11.1 后,修复 11.2 前)
- ✅ 路径组件不再被误识别
- ✅ 第2轮成功执行,生成了预期文件
- ❌ 输出文件名被误识别为表名
- ❌ 模型尝试"第4轮分析 enrolled 的多维度",而不是"第3轮分析 no_payment_due"
- ❌ 陷入循环,无法继续

### 待验证(修复 11.2 + 11.3 后)
- ⏳ 输出文件名不再被误识别
- ⏳ 模型能按顺序执行第 2→3→4→5→6→7→8→9→10 轮
- ⏳ 每轮只分析一个表,不重复分析
- ⏳ 最终生成所有预期文件,包括 HTML 报告

---

### 修复 12：Bootstrap自动导出CSV + 强制立即执行指令（2024-12-29）✅

#### 问题 12.1：Bootstrap缺少CSV文件导出功能

**问题现象**（2024-12-29 第一次测试）：
- Bootstrap显示"【CSV 文件路径】第 2-6 轮必须使用以下 CSV 文件："后面**空白**
- 日志显示"⚠️ 尚未发现实际的 CSV 文件路径"
- 模型无法执行第2-6轮CSV分析

**根本原因**：
Student Loan任务设计要求第2-6轮分析CSV文件,但CSV文件需要从SQLite表导出,这个步骤之前**完全缺失**。

**为什么之前11次修复都没有发现**：
1. **测试环境差异**：之前可能手动上传了CSV文件,或环境中有残留的CSV文件
2. **假设前提错误**：假设CSV文件需要手动上传,而不是系统自动生成
3. **问题表现不同**：之前模型能执行2-3轮,问题表现为"提前终止",而不是"完全无法执行"

**修复方案**：

在Bootstrap代码中添加自动导出CSV功能（`@backend.py:1260-1270`）：
```python
# ========== 第三部分：导出表为CSV文件 ==========
data_dir = Path(r'{workspace_path}') / 'data'
data_dir.mkdir(parents=True, exist_ok=True)
print('\n' + '='*80)
print('【导出CSV文件】')
print('='*80)
for table_name in schema_df['table_name']:
    df = pd.read_sql_query(f'SELECT * FROM {table_name}', conn)
    csv_path = data_dir / f'{table_name}.csv'
    df.to_csv(csv_path, index=False, encoding='utf-8')
    print(f'已导出: {table_name}.csv ({len(df)} 行)')
conn.close()
```

**预期效果**：
- Bootstrap执行时自动创建`data`目录
- 将所有SQLite表导出为CSV文件
- 后续扫描data目录,在"【CSV 文件路径】"部分列出所有CSV文件

**实际效果**：✅ CSV文件成功导出,但引发了新问题(问题12.2)

---

#### 问题 12.2：模型完全偏离任务,输出无关内容

**问题现象**（2024-12-29 第二次测试）：
- ✅ Bootstrap成功执行,CSV文件已导出到data目录
- ✅ CSV文件路径正确显示在页面上
- ❌ **模型输出了大量无关内容**：
  - "系统配置与用户状态健康度评估"
  - "配置开关分析"、"用户参与流程分析"
  - SQL查询脚本、分析报告模板
- ❌ **模型完全没有执行CSV分析**
- ❌ **一个文件都没有生成**（除了bootstrap.txt）

**根本原因**：
1. **Bootstrap内容变化**：添加CSV导出功能后,Bootstrap消息变得更长更复杂
2. **模型理解偏差**：模型看到"bool表"、"disabled表"等名称,自行推测这是"系统配置"或"用户状态"分析
3. **提示词指令不够强制**：提示词中"立即开始第2轮分析"的指令被模型忽略

**为什么之前11次修复都没有发现**：
1. **问题类型完全不同**：
   - 之前：模型执行了部分任务,但提前终止或陷入循环
   - 本次：模型完全偏离任务,输出无关内容
2. **修复焦点偏差**：
   - 之前：聚焦在"拦截逻辑"、"验证逻辑"、"answer_requested机制"
   - 遗漏：**模型是否正确理解任务**、**Bootstrap是否误导模型**
3. **测试不够全面**：
   - 之前：可能在有CSV文件的环境中测试
   - 本次：全新环境暴露了Bootstrap导出CSV后的新问题

**修复方案**：

在Bootstrap消息末尾添加**强制立即执行指令**（`@backend.py:1380-1417`）：
```python
immediate_action = (
    "🚨 **立即执行第 2 轮分析** 🚨\n"
    "**你必须立即输出以下内容,不要输出任何其他文字**:\n\n"
    "<Analyze>\n分析 enrolled.csv 的学校分布\n</Analyze>\n\n"
    "<Code>\n"
    "import pandas as pd\n"
    "CSV_PATH = r\"{enrolled.csv的绝对路径}\"\n"
    "df = pd.read_csv(CSV_PATH)\n"
    "summary.to_csv('enrolled_summary.csv')\n"
    "plt.savefig('enrolled_school_dist.png')\n"
    "</Code>\n"
    "❌ **禁止输出任何解释、问候、询问或其他内容**\n"
    "✅ **只输出上述 <Analyze> 和 <Code> 标签**\n"
)
```

**修复逻辑**：
- 直接提供第2轮的完整代码模板(包含绝对路径)
- 强制禁止输出其他内容
- 明确要求"立即输出<Analyze>和<Code>"

**预期效果**：
- 模型看到Bootstrap后,立即按照指令输出第2轮的`<Analyze>`和`<Code>`
- 不再输出无关的"系统配置分析"等内容
- 直接开始CSV文件分析流程

**实际效果**：❌ 完全失败,模型陷入无限循环(引发修复13)

---

### 修复 13：将强制执行指令前置到Bootstrap开头（2024-12-29）✅

#### 问题 13：强制执行指令位置错误导致模型失控

**问题现象**（2024-12-29 第三次测试）：
- ✅ Bootstrap成功执行,CSV文件已导出
- ✅ 强制执行指令已添加到Bootstrap消息
- ❌ **模型完全失控,陷入无限循环**:
  - 重复输出"你仍然在使用不存在的表名"
  - 系统不断提示"enlist表不存在"(但Bootstrap明确显示enlist存在)
  - 模型输出超过50,000字符,被强制终止
- ❌ **一个文件都没有生成**

**根本原因**：

修复12将强制执行指令放在了**Bootstrap消息末尾**:
```python
return f"{block}{exe_block}{db_path_reminder}{immediate_action}{file_block}"
                                                 ^^^^^^^^^^^^^^^^
                                                 指令在最后
```

**问题**:
1. Bootstrap消息非常长(包含表结构、CSV路径、代码模板等)
2. 模型在看到大量内容后就开始生成响应
3. **根本没读到最后的强制执行指令**
4. 导致模型按照自己的理解生成内容,完全偏离任务

**为什么修复12没有发现这个问题**：
1. **没有实际测试**: 修复12只是添加了指令,没有重启服务验证效果
2. **假设错误**: 认为只要添加了指令,模型就会遵守
3. **忽略了消息结构**: 没有考虑指令在消息中的位置对模型行为的影响

**修复方案**：

将强制执行指令**前置到Bootstrap消息开头**（`@backend.py:1417-1418`）：
```python
# 修改前
return f"{block}{exe_block}{db_path_reminder}{immediate_action}{file_block}"

# 修改后
return f"{immediate_action}{block}{exe_block}{db_path_reminder}{file_block}"
         ^^^^^^^^^^^^^^^^
         指令放在最前面
```

**修复逻辑**：
- 确保模型**首先**看到强制执行指令
- 然后才看到Bootstrap的表结构、CSV路径等信息
- 模型在生成响应前就知道要做什么

**预期效果**：
- 模型立即按照指令输出第2轮的`<Analyze>`和`<Code>`
- 不再输出无关内容或陷入循环
- 直接开始CSV文件分析流程

**实际效果**：❌ 完全失败,模型重复输出指令165次(引发修复14)

---

### 修复 14：移除示例代码,改用简洁指令（2024-12-29）✅

#### 问题 14：强制执行指令包含示例代码导致模型无限重复

**问题现象**（2024-12-29 第四次测试）：
- ✅ Bootstrap成功执行,CSV文件已导出
- ✅ 强制执行指令已前置到Bootstrap开头
- ❌ **模型陷入无限重复循环**:
  - 重复输出165次 `🚨 立即执行第 2 轮分析 🚨`
  - 重复输出指令中的所有内容(包括```代码块)
  - 被系统检测为"重复内容"强制终止
- ❌ **一个文件都没有生成**

**根本原因**：

修复13将完整的`<Analyze>`和`<Code>`标签**用```包裹作为示例**:
```python
immediate_action = (
    "**你必须立即输出以下内容,不要输出任何其他文字**:\n\n"
    "```\n"                    # ← 问题:用代码块包裹
    "<Analyze>\n"
    "分析 enrolled.csv 的学校分布\n"
    "</Analyze>\n\n"
    "<Code>\n"
    "import pandas as pd\n..."
    "</Code>\n"
    "```\n"                    # ← 模型认为这是"示例文本"
)
```

**问题**:
1. 模型将```包裹的内容视为"要输出的文本"
2. 不理解这是"要生成的指令",只是不断复制粘贴
3. 没有触发实际的分析和代码生成逻辑

**为什么修复13没有发现这个问题**：
1. **错误的指令设计**: 将示例代码放在指令中,期望模型"照着做"
2. **忽略了模型行为**: 没有考虑模型会将```内的内容视为文本而非指令
3. **缺少测试验证**: 修复13只是移动了位置,没有测试实际效果

**修复方案**：

移除```代码块和示例代码,改用**简洁的步骤指令**（`@backend.py:1380-1393`）：
```python
# 修改前(修复13)
immediate_action = (
    "**你必须立即输出以下内容,不要输出任何其他文字**:\n\n"
    "```\n<Analyze>...<Code>...</Code>\n```\n"  # ← 示例代码
)

# 修改后(修复14)
immediate_action = (
    "**现在立即开始第 2 轮分析,按照以下步骤执行**:\n\n"
    "1. 从上方CSV文件列表中选择一个表进行分析\n"
    "2. 输出 <Analyze> 标签,说明分析目标\n"
    "3. 输出 <Code> 标签,使用 pd.read_csv() 读取CSV文件\n"
    "4. 生成统计摘要CSV和可视化PNG文件\n\n"
    "⚠️ **禁止输出任何解释、问候或讨论,直接输出 <Analyze> 和 <Code> 标签**\n"
)
```

**修复逻辑**：
- 移除所有示例代码和```代码块
- 改用清晰的步骤说明,让模型自行生成
- 强调"直接输出标签",不要重复指令

**预期效果**：
- 模型理解步骤后,自行生成`<Analyze>`和`<Code>`
- 不再重复输出指令文本
- 直接开始CSV文件分析流程

**实际效果**：⏳ 待重启后端服务并重新测试

---

**文档版本**:v11.0(修复 14 最终版)  
**最后更新**:2024-12-29 21:50  
**状态**:
- ✅ 修复 6.1:流式输出检测顺序已修复(先检查 `</Answer>` 再检查 `</Code>`)
- ✅ 修复 6.2:`execute_rounds` 初始化已修复(Bootstrap 后设为 1)
- ✅ 修复 7:系统主动请求 Answer 的阈值已修复(`ANSWER_MIN_EXEC_ROUNDS = 10`)
- ✅ 修复 8:在 answer_requested 使用点增加轮次检查(防止多重触发)
- ✅ 修复 9:修复表验证逻辑,排除 SQL 别名和文件名(解决第7轮循环问题)
- ✅ 修复 10:增强 SQL 字段错误检测和反馈(解决字段名错误问题)
- ✅ 修复 11.1:修复路径组件误识别问题(已完成后端修改)
- ✅ 修复 11.2:修复输出文件名误识别问题(已完成后端修改)
- ✅ 修复 11.3:修复模型理解偏差问题(需修改提示词)
- ✅ 修复 12.1:Bootstrap自动导出CSV文件功能(已完成后端修改)
- ❌ 修复 12.2:Bootstrap强制立即执行指令(失败,指令位置错误)
- ✅ 修复 13:将强制执行指令前置到Bootstrap开头(已完成后端修改)
- ⏳ 待重启后端服务并重新测试

**修复历史总结**:
- 修复 1-3:提示词优化(无效,问题在后端)
- 修复 4:空输出检测增强(缓解但未解决核心问题)
- 修复 5:修改判断条件(部分修复,但遗漏了检测顺序和初始化问题)
- 修复 6:修复流式输出检测顺序 + execute_rounds 初始化(技术修复完成,但遗漏了主动请求机制)
- 修复 7:修复系统主动请求 Answer 的阈值(修复了设置点,但遗漏了使用点)
- 修复 8:在 answer_requested 使用点增加轮次检查(修复了主动请求,但遗漏了表验证逻辑)
- 修复 9:修复表验证逻辑,排除 SQL 别名和文件名(修复了表名验证,但遗漏了字段验证)
- 修复 10:增强 SQL 字段错误检测和反馈(解决字段名错误问题)
- 修复 11:修复路径和文件名误识别 + 模型理解偏差(修复了验证逻辑,但遗漏了数据准备)
- 修复 12:Bootstrap自动导出CSV + 强制立即执行指令(添加了指令,但位置错误)
- **修复 13:将强制执行指令前置到Bootstrap开头(当前修复)**

**核心教训**:
- ✅ 不仅要检查拦截逻辑,还要检查系统是否会主动触发被拦截的行为
- ✅ 日志分析要全面:没有拦截警告 ≠ 拦截逻辑有问题,可能是系统主动请求
- ✅ 理解系统的完整工作流程,不能只关注局部逻辑
- ✅ 检查标志变量的所有设置点和使用点,确保一致性
- ✅ 验证逻辑要考虑所有合法场景,不能误判正常的 SQL 语法或文件名
- ✅ 错误反馈要精准和可操作,针对不同错误类型提供针对性的修正指导
- ✅ **提示词修改可能引入新问题:更详细的说明→模型输出更多内容→触发新的验证错误**
- ✅ **表名验证逻辑需要考虑所有可能出现的标识符:路径组件、文件名、SQL别名等**
- ✅ **模型理解偏差需要通过更明确的约束来解决,而不仅仅是技术拦截**
- ✅ **检查数据准备的完整性:不仅要检查模型行为,还要检查数据是否准备就绪**
- ✅ **Bootstrap的职责不仅是"显示信息",还要"准备数据"和"引导模型执行"**
- ✅ **当Bootstrap内容变复杂时,需要强制执行指令防止模型偏离任务**
- ✅ **问题分类很重要:"提前终止"和"完全偏离"是两类不同的问题,需要不同的解决方法**
- ✅ **指令位置很重要:关键指令必须放在消息开头,确保模型首先看到**
- ✅ **修复后必须实际测试:不能假设代码修改就会生效,必须验证实际效果**
