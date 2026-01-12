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

README_BULLET_PATTERN = re.compile(r"^- `[^`]+` \(\d+ bytes\)$")


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

- ❗ 严禁 `README_CONTENT = \\"""...\\"""` 等三引号常量写死 Markdown。
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

generated_dir = Path("generated")
if not generated_dir.exists():
    raise FileNotFoundError(f"目录不存在：{{generated_dir.resolve()}}")

files = sorted([p for p in generated_dir.iterdir() if p.is_file()])
csv_files = [f for f in files if f.suffix.lower() == ".csv"]
png_files = [f for f in files if f.suffix.lower() == ".png"]
readme_path = generated_dir / "README.md"

def build_list(items, empty_text):
    if not items:
        return [f"<li>{{empty_text}}</li>"]
    entries = []
    for item in items:
        entries.append(
            f"<li><a href='{{item.name}}' target='_blank'>{{item.name}}</a> ({{item.stat().st_size}} bytes)</li>"
        )
    return entries

html_lines = [
    "<html>",
    "<head>",
    "  <meta charset='utf-8' />",
    "  <title>multi_table_analysis</title>",
    "</head>",
    "<body>",
    f"  <section id='summary'><h1>生成文件概览</h1><p>共 {{len(files)}} 个文件，更新时间 {{datetime.now():%Y-%m-%d %H:%M:%S}}</p></section>",
    "  <section id='visuals'><h2>PNG 可视化</h2>",
]
html_lines += build_list(png_files, "（无 PNG 文件）")
html_lines.append("  </section>")

html_lines.append("  <section id='data-files'><h2>CSV 数据文件</h2>")
html_lines += build_list(csv_files, "（无 CSV 文件）")
html_lines.append("  </section>")

html_lines.append("  <section id='readme'><h2>README</h2>")
if readme_path.exists():
    html_lines.append(f"    <p><a href='{{readme_path.name}}'>{{readme_path.name}}</a></p>")
else:
    html_lines.append("    <p>（未找到 README.md）</p>")
html_lines.append("  </section>")
html_lines.append("</body>")
html_lines.append("</html>")

html_path = generated_dir / "{html_filename}"
html_path.write_text("\\n".join(html_lines), encoding="utf-8")
print(f"✅ HTML 报告已写入：{{html_path.resolve()}}")
```

- ❗ HTML 必须通过 `html_lines` 逐行构建，禁止 `html_template = \\"""...\\"""` 或 `print("<html>")` 写死整段 HTML。
- ❗ 需遍历 generated/ 下真实存在的 CSV/PNG/README 文件，并写入 `<li>` 列表。
'''
    return textwrap.dedent(template).strip()


def validate_readme_document(readme_text, generated_dir):
    """校验 README.md 是否满足通用结构与动态文件列表要求"""
    issues = []
    text = readme_text or ""

    # 检查必需章节
    for section in README_SECTION_HEADERS:
        if section not in text:
            issues.append(f"缺少段落：{section}")

    # 检查文件总数
    total_match = re.search(r"共生成\s+(\d+)\s+个文件", text)
    actual_total = sum(1 for p in generated_dir.iterdir() if p.is_file())
    if not total_match:
        issues.append("缺少文件总数描述")
    else:
        try:
            reported = int(total_match.group(1))
            if reported != actual_total:
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

    # 检查执行日志
    log_files = sorted(
        f.name
        for f in generated_dir.iterdir()
        if f.is_file() and f.name.startswith("execute_round_")
    )
    if log_files:
        missing_logs = [name for name in log_files if name not in text]
        if missing_logs:
            issues.append("未列出执行日志：" + ", ".join(missing_logs))

    # 检查 README 自身
    if "README.md" not in text:
        issues.append("README.md 本身需在其他文件段列出")

    return (not issues), issues
