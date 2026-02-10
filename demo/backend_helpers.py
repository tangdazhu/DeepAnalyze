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
    """返回生成综合数据分析报告的代码骨架（含交叉分析、统计发现、可视化解读、结论建议）"""
    template = f'''
**请使用以下 Python 框架构建综合分析报告（仅可微调变量/样式，不得删除核心语句）：**

```python
from pathlib import Path
from datetime import datetime
import pandas as pd

generated_dir = Path("generated")
if not generated_dir.exists():
    raise FileNotFoundError(f"目录不存在：{{generated_dir.resolve()}}")

csv_files = sorted(generated_dir.glob("*.csv"))
png_files = sorted(generated_dir.glob("*.png"))

# ── 读取主数据 ──
df = pd.read_csv(generated_dir / "multi_table_join_result.csv")
print(f"✅ 读取 multi_table_join_result.csv，共 {{len(df)}} 行，列名：{{list(df.columns)}}")

def read_csv_safe(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()

total = len(df)
cols = list(df.columns)

# ── 各列基础统计 ──
col_stats = []
for c in cols:
    nuniq = int(df[c].nunique())
    missing = int(df[c].isnull().sum())
    miss_pct = f"{{missing / total * 100:.1f}}%"
    col_stats.append((c, nuniq, missing, miss_pct))

# ── 交叉分析 ──
cross_school_pay = pd.DataFrame()
if {{"school", "bool"}}.issubset(df.columns):
    cross_school_pay = pd.crosstab(df["school"], df["bool"], margins=True)

organ_absense = pd.DataFrame()
if {{"organ", "month"}}.issubset(df.columns):
    organ_absense = df.groupby("organ")["month"].agg(["mean", "median", "count"])
    organ_absense = organ_absense.sort_values("mean", ascending=False)

# ── 构造 Markdown ──
md = []
md.append("# 综合数据分析报告")
md.append("")
md.append(f"生成时间：{{datetime.now():%Y-%m-%d %H:%M:%S}}")
md.append("")

# 1. 数据概况
md.append("## 1. 数据概况")
md.append(f"- **数据来源**：`multi_table_join_result.csv`（{{total}} 行，{{len(cols)}} 列）")
md.append(f"- **字段列表**：{{', '.join(cols)}}")
md.append(f"- **CSV 文件数**：{{len(csv_files)}}，**PNG 图表数**：{{len(png_files)}}")
md.append("")
md.append("| 字段 | 唯一值 | 缺失数 | 缺失率 |")
md.append("|------|--------|--------|--------|")
for c, nuniq, missing, miss_pct in col_stats:
    md.append(f"| {{c}} | {{nuniq}} | {{missing}} | {{miss_pct}} |")
md.append("")

# 2. 交叉分析
md.append("## 2. 交叉分析")
md.append("")
if not cross_school_pay.empty:
    md.append("### 2.1 学校 × 缴费状态")
    md.append(cross_school_pay.to_markdown())
    md.append("")
    if "neg" in cross_school_pay.columns and "All" in cross_school_pay.columns:
        rates = (cross_school_pay["neg"] / cross_school_pay["All"]).drop("All", errors="ignore")
        top_school = rates.idxmax()
        top_rate = f"{{rates.max() * 100:.1f}}%"
        md.append(f"**发现**：欠费率最高的学校为 **{{top_school}}**（{{top_rate}}）。")
    md.append("")

if not organ_absense.empty:
    md.append("### 2.2 参军机构 × 缺勤月数")
    md.append("")
    md.append("| 机构 | 平均缺勤月数 | 中位数 | 人数 |")
    md.append("|------|-------------|--------|------|")
    for org, row in organ_absense.iterrows():
        md.append(f"| {{org}} | {{row['mean']:.1f}} | {{row['median']:.1f}} | {{int(row['count'])}} |")
    md.append("")

# 3. 统计发现
md.append("## 3. 统计发现")
md.append("")
for c in cols:
    if df[c].dtype == "object":
        vc = df[c].value_counts()
        top3 = vc.head(3)
        items = "; ".join(f"{{k}}={{int(v)}}" for k, v in top3.items())
        md.append(f"- **{{c}}** 共 {{int(vc.shape[0])}} 个类别，Top3：{{items}}")
for c in cols:
    if pd.api.types.is_numeric_dtype(df[c]):
        md.append(f"- **{{c}}** 均值={{float(df[c].mean()):.2f}}，中位数={{float(df[c].median()):.2f}}，"
                  f"Q25={{float(df[c].quantile(0.25)):.2f}}，Q75={{float(df[c].quantile(0.75)):.2f}}")
md.append("")

# 4. 可视化解读
md.append("## 4. 可视化图表解读")
md.append("")
for png in sorted(png_files):
    md.append(f"### {{png.stem}}")
    md.append(f"![{{png.stem}}]({{png.name}})")
    md.append("")

# 5. 结论与建议
md.append("## 5. 结论与建议")
md.append("")
md.append("1. 基于交叉分析结果，给出针对性建议")
md.append("2. 基于统计发现，指出需要关注的风险点")
md.append("3. 基于可视化图表，总结数据的整体特征")
md.append("")

report_path = generated_dir / "{md_filename}"
report_path.write_text("\\n".join(md), encoding="utf-8")
print(f"✅ 综合分析报告已写入：{{report_path.name}}")
```

- ❗ Markdown 必须通过 `md` 列表逐行构建，禁止 `md_template = \\"""...\\"""` 写死整段 Markdown。
- ❗ 必须读取 multi_table_join_result.csv 并做交叉分析，禁止只列文件清单。
- ❗ 必须包含 ## 数据概况、## 交叉分析、## 统计发现、## 可视化图表解读、## 结论与建议 等段落。
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
