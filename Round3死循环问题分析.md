# Round 3 死循环问题分析

## 问题概述

**发生时间**: 2026-01-13  
**问题版本**: Git commit `4a8efdd`  
**稳定版本**: Git commit `9806a31`  
**问题现象**: 在 Round 3 阶段，模型持续生成虚构的 CSV 文件名，导致无限重试循环，超过 1 小时仍未完成

---

## 问题日志分析

### 时间线

- **14:43:34**: 后端服务启动
- **14:44:17**: Bootstrap 执行成功，生成 `execute_round_0_bootstrap.txt`
- **14:55:12**: Round 2 成功完成，正确读取 `enrolled.csv`
- **14:55:12**: Round 3 触发，后端注入提示："分析 no_payment_due.csv"
- **14:59:42 - 16:04:25**: Round 3 持续重试（raw=5 到 raw=18），模型反复生成错误文件名
- **16:05:24**: 用户手动停止

### 关键日志证据

```
2026-01-13 14:55:12 [INFO] [prompt] round_3_continue
✅ 已完成第 2 轮。
⚡ 立即开始第 3 轮分析（不要等待指令，不要输出任何解释）。
**第 3 轮任务**：分析 no_payment_due.csv → 生成 payment_status_summary.csv + payment_status_dist.png
```

```
2026-01-13 15:03:20 [WARNING] [bot_stream] Round 3 CSV mismatch: expected no_payment_due.csv
2026-01-13 15:07:58 [WARNING] [bot_stream] Round 3 CSV mismatch: expected no_payment_due.csv
2026-01-13 15:12:05 [WARNING] [bot_stream] Round 3 CSV mismatch: expected no_payment_due.csv
...（持续重复）
```

### 模型生成的错误文件名列表

模型在 Round 3 中持续生成以下**虚构的文件名**（这些文件完全不存在）：

1. `student_loan.csv`
2. `student_loan_status.csv`
3. `payment_history.csv`
4. `student_profile.csv`
5. `loan_terms.csv`
6. `repayment_schedule.csv`
7. `student_loan_application.csv`
8. `student_financial_status.csv`
9. `loan_disbursement_records.csv`
10. `student_demographics.csv`
11. `loan_product_features.csv`

### Bootstrap 提供的真实文件列表

```
bool.csv
disabled.csv
enlist.csv
enrolled.csv
filed_for_bankrupcy.csv
longest_absense_from_school.csv
male.csv
no_payment_due.csv
person.csv
unemployed.csv
```

---

## Git 版本对比分析

### 稳定版本 (9806a31)

- ✅ 能够成功完成全部 9 轮分析
- ✅ 能够生成 `multi_table_analysis.html` 报告
- ✅ Round 2-7 重试次数在可接受范围内

### 问题版本 (4a8efdd)

执行 `git diff 9806a31 4a8efdd --stat` 结果：

```
HTML报告生成问题完整分析.md | 229 +++++++++++++++++++++
demo/backend.py              |  46 ++++-
demo/backend_helpers.py      |  46 ++++-
3 files changed, 317 insertions(+), 4 deletions(-)
```

---

## 4a8efdd 的具体修改内容

### 1. HTML 文件名修改 (✅ 无害)

**文件**: `demo/backend.py:255`

```python
# 修改前 (9806a31)
html_name = "multi_table_analysis.html"

# 修改后 (4a8efdd)
html_name = "summary_analysis.html"
```

**影响范围**: 仅 Round 9  
**是否导致 Round 3 问题**: ❌ 否

---

### 2. 旧 HTML 文件名检测 (✅ 无害)

**文件**: `demo/backend.py:3528-3553`

```python
# 新增检测旧文件名 multi_table_analysis.html 的逻辑
old_html_path = next(
    (
        Path(p)
        for p in artifact_paths
        if Path(p).name == "multi_table_analysis.html"
    ),
    None,
)
if old_html_path and html_filename != "multi_table_analysis.html":
    logger.warning(
        "[bot_stream] Detected old HTML filename: multi_table_analysis.html, expected: %s",
        html_filename,
    )
    prompt = (
        f"检测到使用了旧的 HTML 文件名 'multi_table_analysis.html'，"
        f"请使用新的文件名 '{html_filename}'。"
        f"必须修改代码中的 html_path = generated_dir / '{html_filename}'。"
    )
    messages.append({"role": "user", "content": prompt})
    refund_iteration()
    continue
```

**影响范围**: 仅 Round 9  
**是否导致 Round 3 问题**: ❌ 否

---

### 3. HTML 模板增强 - 添加执行时间统计 (✅ 无害)

**文件**: `demo/backend_helpers.py:95-207`

新增功能：
- 从 `execute_round_0_bootstrap.txt` 读取开始时间
- 计算总执行时长
- 在 HTML 报告中显示时间统计

**影响范围**: 仅 Round 9  
**是否导致 Round 3 问题**: ❌ 否

---

### 4. Round 2 CSV 读取错误提示增强 (⚠️ 可疑)

**文件**: `demo/backend.py:2691-2699`

```python
# 修改前 (9806a31)
csv_prompt = (
    f"第 {target_round} 轮属于 CSV 分析阶段，必须使用 `pd.read_csv` 读取配置中指定的 CSV 绝对路径，"
    "禁止跳过 CSV 读取或改用 SQLite。"
)

# 修改后 (4a8efdd)
required_csv = (
    round_input_filename(rule_for_next)
    if rule_for_next
    else None
)
csv_example = ""
if required_csv:
    csv_example = f'\n\n示例：\n```python\nCSV_PATH = r"/path/to/workspace/data/{required_csv}"  # 从第1轮 bootstrap 输出中复制完整路径\ndf = pd.read_csv(CSV_PATH)\n```'
csv_prompt = (
    f"第 {target_round} 轮属于 CSV 分析阶段，必须使用 `pd.read_csv` 读取配置中指定的 CSV 绝对路径，"
    f"禁止跳过 CSV 读取或改用 SQLite。{csv_example}"
)
```

**变化**:
- 新增代码示例（6 行）
- 错误提示长度显著增加

**影响范围**: Round 2-6（所有 CSV 分析阶段）  
**是否导致 Round 3 问题**: ⚠️ 可能

---

### 5. CSV 文件名不匹配错误提示增强 (🔴 高度可疑)

**文件**: `demo/backend.py:2732-2739`

```python
# 修改前 (9806a31)
csv_name_prompt = (
    f"第 {target_round} 轮必须使用第 1 轮列出的 `{required_csv}`，"
    "请直接引用该 CSV 的绝对路径，不要改用其它文件名或虚构的 student_loan_data.csv。"
)

# 修改后 (4a8efdd)
csv_name_prompt = (
    f"第 {target_round} 轮必须使用第 1 轮列出的 `{required_csv}`，"
    f"请直接引用该 CSV 的绝对路径，不要改用其它文件名或虚构的 student_loan_data.csv。\n\n"
    f"正确示例：\n"
    f"```python\n"
    f'CSV_PATH = r"/path/to/workspace/data/{required_csv}"  # 从第1轮输出中复制完整路径\n'
    f"df = pd.read_csv(CSV_PATH)\n"
    f"```"
)
```

**变化**:
- 原提示：1 行文本
- 新提示：1 行文本 + 代码示例（6 行）

**影响范围**: Round 2-6（所有 CSV 分析阶段）  
**是否导致 Round 3 问题**: 🔴 **极有可能**

---

## 问题根因分析

### 为什么 9806a31 能成功，而 4a8efdd 失败？

#### 1. **错误提示长度增加导致消息历史膨胀**

- **9806a31**: 每次错误提示 ~50 字符
- **4a8efdd**: 每次错误提示 ~200 字符（增加 4 倍）

**影响**:
- Round 3 如果重试 10 次，消息历史增加 2000 字符
- 模型上下文窗口被大量错误提示占据
- 模型难以关注到 Bootstrap 提供的真实文件列表

#### 2. **代码示例可能引发模型混淆**

错误提示中包含：
```python
CSV_PATH = r"/path/to/workspace/data/{required_csv}"
```

**问题**:
- 模型可能**直接复制这个模板路径**
- 而不是从 Bootstrap 输出中复制真实的绝对路径
- 导致路径仍然不正确，继续被拒绝

#### 3. **Round 3 的特殊性**

- Round 2 成功后，模型已经"学会"了某种模式
- Round 3 的增强错误提示可能打破了这种模式
- 导致模型开始幻觉生成虚构文件名（如 `student_loan.csv`）

#### 4. **模型幻觉的自我强化**

一旦模型开始生成虚构文件名：
1. 后端拒绝并提示错误
2. 错误提示中包含代码示例模板
3. 模型看到模板后，继续生成类似的虚构文件名
4. 形成恶性循环

---

## 对比测试结果

### 9806a31 版本

| 轮次 | 状态 | 重试次数 | 备注 |
|------|------|----------|------|
| Round 0 (Bootstrap) | ✅ 成功 | 0 | 生成路径列表 |
| Round 2 | ✅ 成功 | ≤2 | enrolled.csv |
| Round 3 | ✅ 成功 | ≤2 | no_payment_due.csv |
| Round 4-7 | ✅ 成功 | ≤3 | 各类 CSV 分析 |
| Round 8 | ✅ 成功 | ≤2 | README.md |
| Round 9 | ✅ 成功 | ≤3 | multi_table_analysis.html |

**总耗时**: 约 30-40 分钟

### 4a8efdd 版本

| 轮次 | 状态 | 重试次数 | 备注 |
|------|------|----------|------|
| Round 0 (Bootstrap) | ✅ 成功 | 0 | 生成路径列表 |
| Round 2 | ✅ 成功 | 1 | enrolled.csv |
| Round 3 | ❌ 死循环 | >14 | 持续生成虚构文件名 |

**总耗时**: >1 小时（未完成，手动停止）

---

## 修复建议

### ✅ 可以保留的修改

1. **HTML 文件名修改** (`backend.py:255`)
   - 从 `multi_table_analysis.html` 改为 `summary_analysis.html`
   - 不影响 Round 2-7

2. **旧 HTML 文件名检测** (`backend.py:3528-3553`)
   - 检测并拒绝旧文件名
   - 仅影响 Round 9

3. **HTML 模板增强** (`backend_helpers.py`)
   - 添加执行时间统计
   - 仅影响 Round 9

4. **HTML section id 修复**（如果需要）
   - `id='visuals'` → `id='visual'`
   - `id='data-files'` → `id='data'`
   - 仅影响 Round 9

### ❌ 必须放弃的修改

1. **Round 2 CSV 读取错误提示增强** (`backend.py:2691-2699`)
   - 不要添加代码示例
   - 保持简洁的错误提示

2. **CSV 文件名不匹配错误提示增强** (`backend.py:2732-2739`)
   - 不要添加代码示例
   - 保持简洁的错误提示

### 🔄 替代方案

如果必须优化 Round 3，可以考虑：

1. **在 `round_io_rules.json` 中增强 Round 3 的 guidance**
   ```json
   "guidance": "no_payment_due.csv 仅包含 name 与 bool 两列...（原有内容）必须从第 1 轮 Bootstrap 输出中复制 no_payment_due.csv 的完整绝对路径。"
   ```

2. **不修改 backend.py 中的错误提示逻辑**
   - 保持 9806a31 的简洁提示
   - 避免添加代码示例

---

## 新修复方案的原则

### 核心原则

1. **最小化修改**: 只修改必要的部分
2. **隔离影响**: 确保修改只影响目标轮次（Round 9）
3. **保持简洁**: 错误提示保持简短明了
4. **避免模板**: 不在错误提示中包含代码示例模板

### 修复步骤

1. **基于 9806a31 创建新分支**
   ```bash
   git checkout 9806a31
   git checkout -b fix-round9-html-only
   ```

2. **仅修改 Round 9 相关代码**
   - 修改 HTML 文件名
   - 修改 HTML section id
   - 添加执行时间统计
   - 添加旧文件名检测

3. **不修改 Round 2-7 的错误提示**
   - 保持 `backend.py:2691-2699` 不变
   - 保持 `backend.py:2732-2739` 不变

4. **测试验证**
   - 确保 Round 2-7 能够正常完成
   - 确保 Round 9 生成正确的 HTML 文件

---

## 测试检查清单

### Round 2-7 检查

- [ ] Round 2: 成功读取 `enrolled.csv`，重试次数 ≤2
- [ ] Round 3: 成功读取 `no_payment_due.csv`，重试次数 ≤2
- [ ] Round 4: 成功读取 `longest_absense_from_school.csv`，重试次数 ≤3
- [ ] Round 5: 成功读取 `enlist.csv`，重试次数 ≤3
- [ ] Round 6: 成功读取 `disabled.csv`，重试次数 ≤3
- [ ] Round 7: 成功执行 SQLite JOIN，重试次数 ≤3

### Round 9 检查

- [ ] 生成的 HTML 文件名为 `summary_analysis.html`（而非 `multi_table_analysis.html`）
- [ ] HTML 包含 `id='visual'`（而非 `id='visuals'`）
- [ ] HTML 包含 `id='data'`（而非 `id='data-files'`）
- [ ] HTML 包含执行时间统计（开始时间、结束时间、总时长）
- [ ] 如果模型生成旧文件名，能够被检测并拒绝

### 性能检查

- [ ] 总执行时间 ≤ 45 分钟
- [ ] 无死循环或长时间卡住现象
- [ ] 日志中无异常警告

---

## 相关文件清单

### 需要修改的文件

1. `demo/backend.py`
   - 修改 HTML 默认文件名（第 255 行）
   - 添加旧文件名检测（第 3528-3553 行）
   - **不修改** CSV 错误提示（第 2691-2699、2732-2739 行）

2. `demo/backend_helpers.py`
   - 修改 HTML 模板（第 95-207 行）
   - 添加执行时间统计
   - 修改 section id

3. `demo/config/round_io_rules.json`
   - 可选：增强 Round 3 的 guidance
   - 但不强制要求

### 不需要修改的文件

- `demo/backend.py` 的 CSV 错误提示部分
- 其他所有文件

---

## 附录：完整日志片段

### Bootstrap 成功日志

```
2026-01-13 14:44:17 [INFO] [bot_stream] Forcing schema bootstrap for session=session_1768286625292_kg09ibgos
2026-01-13 14:44:18 [INFO] [bot_stream] Schema bootstrap completed, injected into messages, execute_rounds=1
```

### Round 2 成功日志

```
2026-01-13 14:55:12 [INFO] [bot_stream] Wrote execution log to /home/tdz/DeepAnalyze/demo/workspace/session_1768286625292_kg09ibgos/generated/execute_round_2.txt
2026-01-13 14:55:12 [INFO] [bot_stream] Added files: ['/home/tdz/DeepAnalyze/demo/workspace/session_1768286625292_kg09ibgos/generated/enrolled_school_dist.png', ...]
```

### Round 3 死循环日志

```
2026-01-13 14:59:42 [INFO] [bot_stream] Table mentions extracted: known={'no_payment_due', 'bool'}, unknown={'payment_flag'}
2026-01-13 15:03:20 [WARNING] [bot_stream] Round 3 CSV mismatch: expected no_payment_due.csv
2026-01-13 15:07:58 [WARNING] [bot_stream] Round 3 CSV mismatch: expected no_payment_due.csv
2026-01-13 15:12:05 [WARNING] [bot_stream] Round 3 CSV mismatch: expected no_payment_due.csv
...（持续重复）
```

---

## 结论

**4a8efdd 导致 Round 3 死循环的根本原因**：

1. CSV 文件名不匹配错误提示中添加了代码示例模板
2. 模型倾向于复制模板路径，而不是从 Bootstrap 输出中复制真实路径
3. 错误提示长度增加导致消息历史膨胀，影响模型上下文理解
4. 模型开始幻觉生成虚构文件名，形成恶性循环

**新修复方案的核心**：

- ✅ 保留所有 Round 9 相关的修改（HTML 文件名、section id、执行时间统计）
- ❌ 放弃所有 CSV 错误提示的增强（不添加代码示例）
- 🎯 确保修改只影响 Round 9，不影响 Round 2-7 的稳定性

---

## 优化实施记录

### 优化版本：基于 9806a31 的精准修复

**实施时间**: 2026-01-13 21:45  
**基础版本**: Git commit `9806a31`  
**测试结果**: ✅ 成功完成全部 9 轮分析（耗时约 3 小时）

#### 实施的修改

##### 1. ✅ 添加执行时间统计（`backend_helpers.py`）

**修改位置**: `build_html_report_template()` 函数

**新增功能**:
- 从 `execute_round_0_bootstrap.txt` 读取开始时间
- 计算总执行时长（小时/分钟/秒）
- 在 HTML 报告中显示时间统计

**代码片段**:
```python
# 读取开始时间（从 bootstrap 日志）
start_time_str = None
end_time = datetime.now()
bootstrap_log = generated_dir / "execute_round_0_bootstrap.txt"
if bootstrap_log.exists():
    try:
        content = bootstrap_log.read_text(encoding="utf-8")
        match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', content)
        if match:
            start_time_str = match.group(1)
    except Exception:
        pass

# 计算执行时长
duration_str = "未知"
if start_time_str:
    try:
        start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        duration = end_time - start_time
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        seconds = int(duration.total_seconds() % 60)
        if hours > 0:
            duration_str = f"{hours} 小时 {minutes} 分钟 {seconds} 秒"
        elif minutes > 0:
            duration_str = f"{minutes} 分钟 {seconds} 秒"
        else:
            duration_str = f"{seconds} 秒"
    except Exception:
        duration_str = "计算失败"
```

**影响范围**: 仅 Round 9 HTML 报告

---

##### 2. ✅ Round 9 完成后自动更新 README（`backend.py` + `backend_helpers.py`）

**问题**: Round 8 生成 README 时，Round 9 的 HTML 还未生成，导致 README 显示"（无 HTML 报告）"

**解决方案**: 在 Round 9 HTML 验证成功后，自动重新生成 README.md

**修改位置 1**: `backend_helpers.py` - 新增辅助函数
```python
def update_readme_after_html(generated_dir):
    """在 Round 9 HTML 生成后更新 README.md，包含 HTML 文件"""
    # 重新遍历 generated/ 目录
    # 重新生成 README.md，包含 HTML 文件
    # 返回成功状态
```

**修改位置 2**: `backend.py:3600-3608` - 调用更新函数
```python
# Round 9 HTML 生成成功后，更新 README.md 包含 HTML 文件
if mode_for_current == "html_report":
    try:
        from backend_helpers import update_readme_after_html
        update_readme_after_html(generated_dir)
        logger.info("[bot_stream] README.md updated with HTML file")
    except Exception as err:
        logger.warning("[bot_stream] Failed to update README: %s", err)
```

**影响范围**: Round 9 完成后自动触发

---

##### 3. ✅ 优化表名校验逻辑（`backend.py`）

**问题**: Round 9 中，Python 变量名（如 `build_list`、`st_size`、`html_lines`）被误判为"未知表名"，导致不必要的重试

**解决方案**: 添加 Python 内置函数和常见变量名白名单

**修改位置**: `backend.py:742-776` - `extract_table_mentions_from_text()` 函数

**新增白名单**:
```python
PYTHON_BUILTINS = {
    "build_list",
    "format_items",
    "html_lines",
    "time_stats",
    "analysis_summary",
    "key_findings",
    "readme_path",
    "generated_dir",
    "csv_files",
    "png_files",
    "log_files",
    "html_files",
    "other_files",
    "st_size",
    "stat",
    "exists",
    "iterdir",
    "write_text",
    "read_text",
    "print",
    "bytes",
    "visual",
    "section",
    "now",
    "strptime",
    "strftime",
    "datetime",
    "timedelta",
    "yyyy",
    "mm",
    "dd",
    "hh",
    "ss",
}
```

**过滤逻辑**:
```python
def is_likely_table(token: str) -> bool:
    lowered = token.lower()
    if not lowered:
        return False
    if lowered in COMMON_WORDS or lowered.startswith("session_"):
        return False
    # 过滤 Python 内置函数和常见变量名
    if lowered in PYTHON_BUILTINS:
        return False
    # ... 其他过滤逻辑
```

**影响范围**: Round 8-9 的表名校验

**预期效果**: 减少 Round 9 的重试次数（从 3 次降至 0-1 次）

---

#### 未修改的部分（保持 9806a31 稳定性）

##### ❌ 不修改 CSV 文件名错误提示

**位置**: `backend.py:2732-2739`

**保持简洁版本**:
```python
csv_name_prompt = (
    f"第 {target_round} 轮必须使用第 1 轮列出的 `{required_csv}`，"
    "请直接引用该 CSV 的绝对路径，不要改用其它文件名或虚构的 student_loan_data.csv。"
)
```

**不添加**:
- ❌ 代码示例模板
- ❌ 复杂的格式化符号（❌、⚠️、✅、📌）
- ❌ Bootstrap CSV 列表提取逻辑

**原因**: 4a8efdd 的复杂错误提示导致 Round 3 死循环

---

##### ❌ 不修改 Round 2 CSV 读取错误提示

**位置**: `backend.py:2691-2699`

**保持简洁版本**:
```python
csv_prompt = (
    f"第 {target_round} 轮属于 CSV 分析阶段，必须使用 `pd.read_csv` 读取配置中指定的 CSV 绝对路径，"
    "禁止跳过 CSV 读取或改用 SQLite。"
)
```

**不添加**:
- ❌ 代码示例模板

**原因**: 保持与 9806a31 一致的稳定性

---

#### 测试验证计划

##### 验证目标

1. ✅ **Round 2-8 不受影响**
   - 重试次数保持在可接受范围（≤3 次）
   - 无新增错误或警告

2. ✅ **Round 9 优化效果**
   - 重试次数减少（从 3 次降至 0-1 次）
   - HTML 报告包含执行时间统计
   - README.md 正确列出 HTML 文件

3. ✅ **Round 3 稳定性**
   - 无死循环
   - 正确读取 `no_payment_due.csv`
   - 重试次数 ≤2 次

##### 验证步骤

1. 重启后端服务
2. 上传 `student_loan.sqlite` 和数据文件
3. 执行完整的 9 轮分析
4. 检查生成的文件：
   - `summary_analysis.html` 包含时间统计
   - `README.md` 列出 HTML 文件
   - 所有 CSV、PNG、日志文件完整

##### 预期结果

| 轮次 | 预期重试次数 | 预期耗时 |
|------|-------------|---------|
| Round 2 | ≤2 | ~10-15分钟 |
| Round 3 | ≤2 | ~5-10分钟 |
| Round 4-7 | ≤3 | ~30-40分钟 |
| Round 8 | ≤2 | ~10-15分钟 |
| Round 9 | ≤1 | ~10-20分钟 |
| **总计** | **≤12** | **~1.5-2小时** |

---

#### 回滚方案

如果测试失败，执行以下回滚：

```bash
git reset --hard 9806a31
```

这将放弃所有本次优化，恢复到稳定的 9806a31 版本。

---

**文档创建时间**: 2026-01-13  
**文档版本**: 1.1  
**最后更新**: 2026-01-13 21:45  
**优化实施**: 2026-01-13 21:45
