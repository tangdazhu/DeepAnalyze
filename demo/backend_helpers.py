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


def build_markdown_report_template(md_filename):
    """返回生成 Markdown 分析报告的通用代码骨架"""
    template = f'''
**请使用以下 Python 框架构建 Markdown（仅可微调变量/样式，不得删除核心语句）：**

```python
from pathlib import Path
import pandas as pd

generated_dir = Path("generated")
if not generated_dir.exists():
    raise FileNotFoundError(f"目录不存在：{{generated_dir.resolve()}}")

files = sorted([p for p in generated_dir.iterdir() if p.is_file()])
csv_files = [f for f in files if f.suffix.lower() == ".csv"]
png_files = [f for f in files if f.suffix.lower() == ".png"]
log_files = [f for f in files if f.name.startswith("execute_round_") and f.suffix == ".txt"]
md_files = [f for f in files if f.suffix.lower() == ".md"]
readme_path = generated_dir / "README.md"

def to_plain_number(val):
    """将 numpy/pandas 标量转为普通 Python 数值，避免出现 np.int64 等不可读内容。"""
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    try:
        if hasattr(val, "item"):
            return val.item()
    except Exception:
        pass
    return val

def build_file_list(items, empty_text):
    if not items:
        return [f"- {{empty_text}}"]
    return [f"- `{{f.name}}` ({{f.stat().st_size}} bytes)" for f in items]

markdown_lines = []
markdown_lines.append("# 多表分析总结报告")
markdown_lines.append("")

markdown_lines.append("## 文件概览")
markdown_lines.append(f"本次分析共生成 {{len(files)}} 个文件，全部存放于 `generated/` 目录。")
markdown_lines.append("")

markdown_lines.append("## 分析过程总结")
markdown_lines.append("- **Round 2-6**: CSV 数据分析阶段，对多个数据文件进行了单表分析并生成汇总结果")
markdown_lines.append("- **Round 7**: SQLite 多表关联阶段，将五个表通过 name 字段进行 JOIN，生成综合分析结果")
markdown_lines.append("- **Round 8**: 文件系统总结阶段，遍历 generated 目录生成 README.md 索引文件")
markdown_lines.append("- **Round 9**: 报告生成阶段，创建本分析总结报告")
markdown_lines.append("")

markdown_lines.append("## 关键发现")
markdown_lines.append(f"- 共处理 {{len([f for f in csv_files if 'summary' not in f.name and 'join' not in f.name])}} 个原始数据文件")
markdown_lines.append(f"- 生成 {{len([f for f in csv_files if 'summary' in f.name or 'join' in f.name])}} 个统计汇总文件")
markdown_lines.append(f"- 创建 {{len(png_files)}} 个数据可视化图表")
markdown_lines.append(f"- 记录 {{len(log_files)}} 个执行日志文件")
markdown_lines.append("")

# 构建数据洞察（若 join 结果存在）
join_path = generated_dir / "multi_table_join_result.csv"
if join_path.exists():
    try:
        df_join = pd.read_csv(join_path)
    except Exception:
        df_join = pd.DataFrame()

    if not df_join.empty:
        markdown_lines.append("## 数据洞察（基于 multi_table_join_result.csv）")
        markdown_lines.append(f"- **样本规模**：{{len(df_join)}} 行，{{len(df_join.columns)}} 列")
        markdown_lines.append(f"- **列名**：{{', '.join(map(str, df_join.columns.tolist()))}}")

        missing_rate = df_join.isna().mean().sort_values(ascending=False)
        top_missing = missing_rate.head(3)
        top_items = [f"{{col}}={{rate:.2%}}" for col, rate in top_missing.items()]
        markdown_lines.append(f"- **缺失率 Top3**：{{', '.join(top_items)}}")

        cat_cols = df_join.select_dtypes(exclude="number").columns.tolist()
        num_cols = df_join.select_dtypes(include="number").columns.tolist()

        if cat_cols:
            col = cat_cols[0]
            vc = df_join[col].astype(str).value_counts(dropna=False)
            topk = vc.head(3)
            parts = [f"{{k}}={{int(to_plain_number(v) or 0)}}" for k, v in topk.items()]
            markdown_lines.append(f"- **类别分布示例**：字段 `{{col}}` Top3={{'; '.join(parts)}}（共{{len(vc)}}类）")

        if num_cols:
            col = num_cols[0]
            s = df_join[col]
            mean_val = to_plain_number(s.mean())
            median_val = to_plain_number(s.median())
            q25 = to_plain_number(s.quantile(0.25))
            q75 = to_plain_number(s.quantile(0.75))
            markdown_lines.append(f"- **数值分布示例**：字段 `{{col}}` mean={{mean_val}}, median={{median_val}}, p25={{q25}}, p75={{q75}}")

        markdown_lines.append("")

markdown_lines.append("## 可视化图表")
markdown_lines += build_file_list(png_files, "（无 PNG 文件）")
markdown_lines.append("")

markdown_lines.append("## 数据文件")
markdown_lines += build_file_list(csv_files, "（无 CSV 文件）")
markdown_lines.append("")

markdown_lines.append("## README 索引")
if readme_path.exists():
    markdown_lines.append(f"- `{{readme_path.name}}` - 完整文件列表索引")
else:
    markdown_lines.append("- （未找到 README.md）")
markdown_lines.append("")

report_path = generated_dir / "{md_filename}"
report_path.write_text("\\n".join(markdown_lines), encoding="utf-8")
print(f"✅ Markdown 报告已写入：{{report_path.name}}")
```

- ❗ Markdown 必须通过 `markdown_lines` 逐行构建，禁止 `md_template = \\"""...\\"""` 或 `print("#")` 写死整段 Markdown。
- ❗ 需遍历 generated/ 下真实存在的 CSV/PNG/README 文件，并写入列表。
- ❗ 必须包含 ## 文件概览、## 分析过程总结、## 关键发现、## 数据洞察、## 可视化图表、## 数据文件、## README 索引 等段落。
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


def update_readme_after_report(generated_dir):
    """在 Markdown 报告生成后更新 README.md，包含报告文件"""
    from pathlib import Path
    from datetime import datetime

    generated_path = Path(generated_dir)
    if not generated_path.exists():
        return

    files = sorted([p for p in generated_path.iterdir() if p.is_file()])
    total_files = len(files)

    md_report_files = [
        f for f in files if f.suffix.lower() == ".md" and f.name.lower() != "readme.md"
    ]
    csv_files = [f for f in files if f.suffix.lower() == ".csv"]
    png_files = [f for f in files if f.suffix.lower() == ".png"]
    log_files = [f for f in files if f.name.startswith("execute_round_")]
    other_files = [
        f
        for f in files
        if f not in md_report_files + csv_files + png_files
        and f not in log_files
        and f.name.lower() != "readme.md"
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
        "## Markdown 报告",
    ]
    lines += format_items(md_report_files, "- （无 Markdown 报告）")

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
