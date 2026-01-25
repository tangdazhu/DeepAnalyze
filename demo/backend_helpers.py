# -*- coding: utf-8 -*-
"""
Backend helper functions for README and HTML validation
注意：所有字符串使用英文引号，避免语法错误
"""
import re
import textwrap
from pathlib import Path

README_SECTION_HEADERS = [
    "# 生成文件目录",
    "## HTML 报告",
    "## CSV 数据文件",
    "## PNG 可视化",
    "## 执行日志",
    "## 其他文件",
]

README_BULLET_PATTERN = re.compile(r"^- `?[^`]+\.[^`]+`?(?: \(\d+ bytes\))?$")


def build_filesystem_summary_template():
    """返回遍历 generated/ 并写入 README.md 的通用代码骨架"""
    template = '''
**请严格复制以下 Python 骨架（允许重命名变量，但不得删除核心语句）：**

```python
from pathlib import Path
from datetime import datetime

generated_dir = Path("generated")
if not generated_dir.exists():
    raise FileNotFoundError(f"目录不存在：{generated_dir.resolve()}")

readme_path = generated_dir / "README.md"
if not readme_path.exists():
    readme_path.touch()

files = sorted([p for p in generated_dir.iterdir() if p.is_file()])
total_files = len(files)

html_files = [f for f in files if f.suffix.lower() in {".html", ".htm"}]
csv_files = [f for f in files if f.suffix.lower() == ".csv"]
png_files = [f for f in files if f.suffix.lower() == ".png"]
log_files = [f for f in files if f.name.startswith("execute_round_")]
other_files = [
    f
    for f in files
    if f not in html_files + csv_files + png_files and f not in log_files
]

def format_items(items, placeholder):
    return [f"- `{f.name}` ({f.stat().st_size} bytes)" for f in items] or [placeholder]

lines = [
    "# 生成文件目录",
    f"共生成 {total_files} 个文件，全部存放于 `generated/` 目录。",
    f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
    "",
    "## HTML 报告",
]
lines += format_items(html_files, "- （无 HTML 报告）")

lines.append("")
lines.append("## CSV 数据文件")
lines += format_items(csv_files, "- （无 CSV 数据文件）")

lines.append("")
lines.append("## PNG 可视化")
lines += format_items(png_files, "- （无 PNG 可视化）")

lines.append("")
lines.append("## 执行日志")
lines += format_items(log_files, "- （无 execute_round_*.txt）")

lines.append("")
lines.append("## 其他文件")
lines += format_items(other_files, "- （无其他文件）")

readme_path = generated_dir / "README.md"
readme_path.write_text("\\n".join(lines), encoding="utf-8")
print(f"✅ README.md 已写入，列出了 {total_files} 个文件。")
```

- ❗ README 首行必须是 `# 生成文件目录`，禁止添加其他主标题。
- ❗ 所有分节标题必须使用 `##` 开头，禁止使用 `###`。
- ❗ 严禁 `README_CONTENT = """..."""` 等三引号常量写死 Markdown。
- ❗ 必须调用 `Path.write_text`（或等价写盘方法）真实写入 README.md。
'''
    return textwrap.dedent(template).strip()


def build_html_report_template(html_filename):
    """返回生成 HTML 报告的通用代码骨架"""
    template = f'''
**请使用以下 Python 框架构建 HTML（仅可微调变量/样式，不得删除核心语句）：**

```python
from pathlib import Path
from datetime import datetime
import re

generated_dir = Path("generated")
if not generated_dir.exists():
    raise FileNotFoundError(f"目录不存在：{{generated_dir.resolve()}}")

files = sorted([p for p in generated_dir.iterdir() if p.is_file()])
csv_files = [f for f in files if f.suffix.lower() == ".csv"]
png_files = [f for f in files if f.suffix.lower() == ".png"]
log_files = [f for f in files if f.name.startswith("execute_round_") and f.suffix == ".txt"]
readme_path = generated_dir / "README.md"

# 读取开始时间（从 bootstrap 日志）
start_time_str = None
end_time = datetime.now()
bootstrap_log = generated_dir / "execute_round_0_bootstrap.txt"
if bootstrap_log.exists():
    try:
        content = bootstrap_log.read_text(encoding="utf-8")
        # 查找第一个时间戳（格式：YYYY-MM-DD HH:MM:SS）
        match = re.search(r'(\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}})', content)
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
            duration_str = f"{{hours}} 小时 {{minutes}} 分钟 {{seconds}} 秒"
        elif minutes > 0:
            duration_str = f"{{minutes}} 分钟 {{seconds}} 秒"
        else:
            duration_str = f"{{seconds}} 秒"
    except Exception:
        duration_str = "计算失败"

def build_list(items, empty_text):
    if not items:
        return [f"<li>{{empty_text}}</li>"]
    entries = []
    for item in items:
        entries.append(
            f"<li><a href='{{item.name}}' target='_blank'>{{item.name}}</a> ({{item.stat().st_size}} bytes)</li>"
        )
    return entries

# 构建执行时间统计
time_stats = []
time_stats.append("<h2>执行时间统计</h2>")
time_stats.append("<ul>")
time_stats.append(f"<li><strong>开始时间</strong>: {{start_time_str or '未知'}}</li>")
time_stats.append(f"<li><strong>结束时间</strong>: {{end_time:%Y-%m-%d %H:%M:%S}}</li>")
time_stats.append(f"<li><strong>总执行时长</strong>: {{duration_str}}</li>")
time_stats.append("</ul>")

# 构建分析过程总结
analysis_summary = []
analysis_summary.append("<h2>分析过程总结</h2>")
analysis_summary.append("<ul>")
analysis_summary.append("<li><strong>Round 2-6</strong>: CSV 数据分析阶段，对多个数据文件进行了单表分析并生成汇总结果</li>")
analysis_summary.append("<li><strong>Round 7</strong>: SQLite 多表关联阶段，将五个表通过 name 字段进行 JOIN，生成综合分析结果</li>")
analysis_summary.append("<li><strong>Round 8</strong>: 文件系统总结阶段，遍历 generated 目录生成 README.md 索引文件</li>")
analysis_summary.append("<li><strong>Round 9</strong>: HTML 报告生成阶段，创建本可视化报告</li>")
analysis_summary.append("</ul>")

# 构建关键发现总结
key_findings = []
key_findings.append("<h2>关键发现</h2>")
key_findings.append("<ul>")
key_findings.append(f"<li>共处理 {{len([f for f in csv_files if 'summary' not in f.name and 'join' not in f.name])}} 个原始数据文件</li>")
key_findings.append(f"<li>生成 {{len([f for f in csv_files if 'summary' in f.name or 'join' in f.name])}} 个统计汇总文件</li>")
key_findings.append(f"<li>创建 {{len(png_files)}} 个数据可视化图表</li>")
key_findings.append(f"<li>记录 {{len(log_files)}} 个执行日志文件</li>")
key_findings.append("</ul>")

html_lines = [
    "<html>",
    "<head>",
    "  <meta charset='utf-8' />",
    "  <title>Student Loan Analysis Summary</title>",
    "  <style>",
    "    body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}",
    "    h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}",
    "    h2 {{ color: #34495e; margin-top: 30px; border-bottom: 2px solid #95a5a6; padding-bottom: 5px; }}",
    "    h3 {{ color: #555; margin-top: 20px; font-size: 1.1em; }}",
    "    section {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}",
    "    ul {{ line-height: 1.8; }}",
    "    li {{ margin: 5px 0; }}",
    "    a {{ color: #3498db; text-decoration: none; }}",
    "    a:hover {{ text-decoration: underline; }}",
    "    .timestamp {{ color: #7f8c8d; font-size: 0.9em; }}",
    "    .time-stat {{ color: #27ae60; font-weight: bold; }}",
    "    table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}",
    "    th {{ background-color: #3498db; color: white; border: 1px solid #2980b9; padding: 10px; text-align: left; }}",
    "    td {{ border: 1px solid #ddd; padding: 8px; }}",
    "    tr:nth-child(even) {{ background-color: #f9f9f9; }}",
    "    tr:hover {{ background-color: #f0f0f0; }}",
    "  </style>",
    "</head>",
    "<body>",
    "  <h1>Student Loan 多表分析总结报告</h1>",
    f"  <p class='timestamp'>报告生成时间：{{datetime.now():%Y-%m-%d %H:%M:%S}}</p>",
    "",
    "  <section id='summary'>",
    "    <h2>文件概览</h2>",
    f"    <p>本次分析共生成 {{len(files)}} 个文件，包括数据文件、可视化图表、执行日志和索引文档。</p>",
]
html_lines.extend(time_stats)
html_lines.extend(analysis_summary)
html_lines.extend(key_findings)
html_lines.append("  </section>")

html_lines.append("  <section id='visual'>")
html_lines.append("    <h2>PNG 可视化图表</h2>")
html_lines.append("    <ul>")
html_lines += build_list(png_files, "（无 PNG 文件）")
html_lines.append("    </ul>")
html_lines.append("  </section>")

html_lines.append("  <section id='data'>")
html_lines.append("    <h2>CSV 数据文件</h2>")
html_lines.append("    <ul>")
html_lines += build_list(csv_files, "（无 CSV 文件）")
html_lines.append("    </ul>")
html_lines.append("  </section>")

html_lines.append("  <section id='readme'>")
html_lines.append("    <h2>README 索引</h2>")
if readme_path.exists():
    html_lines.append(f"    <p><a href='{{readme_path.name}}'>{{readme_path.name}}</a> - 完整文件列表索引</p>")
else:
    html_lines.append("    <p>（未找到 README.md）</p>")
html_lines.append("  </section>")
html_lines.append("</body>")
html_lines.append("</html>")

html_path = generated_dir / "{html_filename}"
html_path.write_text("\\n".join(html_lines), encoding="utf-8")
print(f"✅ HTML 报告已写入：{{html_path.name}}")
```

- ❗ HTML 必须通过 `html_lines` 逐行构建，禁止 `html_template = \\"""...\\"""` 或 `print("<html>")` 写死整段 HTML。
- ❗ 需遍历 generated/ 下真实存在的 CSV/PNG/README 文件，并写入 `<li>` 列表。
- ❗ 必须包含 id='summary'、id='visual'、id='data'、id='readme' 四个 section。
'''
    return textwrap.dedent(template).strip()


def validate_readme_document(readme_text, generated_dir):
    """校验 README.md 是否满足通用结构与动态文件列表要求"""
    issues = []
    text = readme_text or ""
    normalized_text = re.sub(r"\*\*(\d+)\*\*", r"\1", text)

    stripped_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not stripped_lines or stripped_lines[0] != "# 生成文件目录":
        issues.append("README 必须以 # 生成文件目录 开头")

    # 检查必需章节
    for section in README_SECTION_HEADERS:
        if section not in text:
            issues.append(f"缺少段落：{section}")

    # 检查文件总数（允许 ±2 的误差，因为 README.md 和 execute_round_N.txt 在生成时还不存在）
    total_match = re.search(r"共生成\s*(\d+)\s*个文件", normalized_text)
    if not total_match:
        total_match = re.search(r"文件总数\s*[:：]?\s*(\d+)", normalized_text)
    if not total_match:
        total_match = re.search(
            r"A total of\s+(\d+)\s+files", normalized_text, re.IGNORECASE
        )
    actual_total = sum(1 for p in generated_dir.iterdir() if p.is_file())
    if not total_match:
        issues.append("缺少文件总数描述")
    else:
        try:
            reported = int(total_match.group(1))
            # 允许 ±2 的误差范围
            if abs(reported - actual_total) > 2:
                issues.append(
                    f"文件总数不匹配（README={reported}，实际={actual_total}）"
                )
        except ValueError:
            issues.append("文件总数格式无效")

    # 检查文件条目格式
    bullet_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("- ")
    ]
    for line in bullet_lines:
        if line.startswith("- （"):
            continue
        if not README_BULLET_PATTERN.match(line):
            issues.append("文件条目须使用正确格式")
            break

    # 检查执行日志（排除最新的 execute_round_N.txt，因为生成时它还不存在）
    log_files = sorted(
        f.name
        for f in generated_dir.iterdir()
        if f.is_file() and f.name.startswith("execute_round_")
    )
    if log_files:
        # 排除最新的日志文件（通常是当前轮次的）
        latest_log = log_files[-1] if log_files else None
        missing_logs = [
            name for name in log_files[:-1] if name not in text
        ]  # 只检查前 N-1 个日志
        if missing_logs:
            issues.append("未列出执行日志：" + ", ".join(missing_logs))

    # 校验是否列出实际生成的文件（排除最新日志，避免生成时尚不存在）
    actual_files = [f.name for f in generated_dir.iterdir() if f.is_file()]
    latest_log = log_files[-1] if log_files else None
    expected_names = [
        name for name in actual_files if not (latest_log and name == latest_log)
    ]
    text_lower = text.lower()
    missing_names = [name for name in expected_names if name.lower() not in text_lower]
    if missing_names:
        preview = ", ".join(missing_names[:8])
        if len(missing_names) > 8:
            preview += " 等"
        issues.append("未列出生成文件：" + preview)

    # 不强制要求列出 README.md 自身（因为生成时它还不存在）
    # 这是一个可选的最佳实践，但不应该作为校验失败的理由

    return (not issues), issues


def update_readme_after_html(generated_dir):
    """在 Round 9 HTML 生成后更新 README.md，包含 HTML 文件"""
    from pathlib import Path
    from datetime import datetime

    generated_path = Path(generated_dir)
    if not generated_path.exists():
        return

    files = sorted([p for p in generated_path.iterdir() if p.is_file()])
    total_files = len(files)

    html_files = [f for f in files if f.suffix.lower() in {".html", ".htm"}]
    csv_files = [f for f in files if f.suffix.lower() == ".csv"]
    png_files = [f for f in files if f.suffix.lower() == ".png"]
    log_files = [f for f in files if f.name.startswith("execute_round_")]
    other_files = [
        f
        for f in files
        if f not in html_files + csv_files + png_files and f not in log_files
    ]

    def format_items(items, placeholder):
        return [f"- `{f.name}` ({f.stat().st_size} bytes)" for f in items] or [
            placeholder
        ]

    lines = [
        "# 生成文件目录",
        f"共生成 {total_files} 个文件，全部存放于 `generated/` 目录。",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## HTML 报告",
    ]
    lines += format_items(html_files, "- （无 HTML 报告）")

    lines.append("")
    lines.append("## CSV 数据文件")
    lines += format_items(csv_files, "- （无 CSV 数据文件）")

    lines.append("")
    lines.append("## PNG 可视化")
    lines += format_items(png_files, "- （无 PNG 可视化）")

    lines.append("")
    lines.append("## 执行日志")
    lines += format_items(log_files, "- （无 execute_round_*.txt）")

    lines.append("")
    lines.append("## 其他文件")
    lines += format_items(other_files, "- （无其他文件）")

    readme_path = generated_path / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return True
