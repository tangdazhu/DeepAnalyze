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
    """返回生成综合数据分析报告的代码骨架（含耗时统计、交叉分析、统计发现、可视化解读、结论建议）"""
    template = f'''
**请使用以下 Python 框架构建综合分析报告（仅可微调变量/样式，不得删除核心语句）：**

```python
import re
from pathlib import Path
from datetime import datetime
import pandas as pd

generated_dir = Path("generated")
if not generated_dir.exists():
    raise FileNotFoundError(f"目录不存在：{{generated_dir.resolve()}}")

csv_files = sorted(generated_dir.glob("*.csv"))
png_files = sorted(generated_dir.glob("*.png"))

# ── 读取各轮耗时 ──
round_times = []
total_elapsed = 0.0
for log_file in sorted(generated_dir.glob("execute_round_*.txt")):
    elapsed = None
    start_time = None
    end_time = None
    round_name = log_file.stem.replace("execute_round_", "Round ")
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"Elapsed:\\s*([\\d.]+)s", line)
            if m:
                elapsed = float(m.group(1))
            m2 = re.match(r"Start:\\s*(.+)", line)
            if m2:
                start_time = m2.group(1).strip()
            m3 = re.match(r"End:\\s*(.+)", line)
            if m3:
                end_time = m3.group(1).strip()
    if elapsed is not None:
        total_elapsed += elapsed
        round_times.append((round_name, start_time or "-", end_time or "-", elapsed))

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
cross_tables = []
cat_cols = [c for c in cols if df[c].dtype == "object"]
num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]

cross_school_pay = pd.DataFrame()
if {{"school", "bool"}}.issubset(df.columns):
    cross_school_pay = pd.crosstab(df["school"], df["bool"], margins=True)

organ_absense = pd.DataFrame()
if {{"organ", "month"}}.issubset(df.columns):
    organ_absense = df.groupby("organ")["month"].agg(["mean", "median", "count"])
    organ_absense = organ_absense.sort_values("mean", ascending=False)

# ── 为每个 CSV 生成摘要描述 ──
csv_summaries = {{}}
for csv_f in csv_files:
    try:
        tmp_df = pd.read_csv(csv_f)
        n_rows, n_cols = tmp_df.shape
        col_list = ", ".join(tmp_df.columns[:6])
        if len(tmp_df.columns) > 6:
            col_list += " 等"
        summary_parts = [f"共 {{n_rows}} 行 {{n_cols}} 列（{{col_list}}）"]
        for tc in tmp_df.columns:
            if pd.api.types.is_numeric_dtype(tmp_df[tc]):
                summary_parts.append(
                    f"{{tc}} 均值={{float(tmp_df[tc].mean()):.2f}}，"
                    f"范围=[{{float(tmp_df[tc].min()):.2f}}, {{float(tmp_df[tc].max()):.2f}}]"
                )
                break
        csv_summaries[csv_f.stem] = "；".join(summary_parts)
    except Exception:
        csv_summaries[csv_f.stem] = "（读取失败）"

# ── 构造 Markdown ──
md = []
md.append("# 综合数据分析报告")
md.append("")
md.append(f"生成时间：{{datetime.now():%Y-%m-%d %H:%M:%S}}")
md.append("")

# 1. 执行耗时统计
md.append("## 1. 执行耗时统计")
md.append("")
if round_times:
    total_min = total_elapsed / 60
    md.append(f"**总耗时**：{{total_elapsed:.1f}} 秒（{{total_min:.1f}} 分钟），共 {{len(round_times)}} 轮")
    md.append("")
    md.append("| 轮次 | 开始时间 | 结束时间 | 耗时（秒） |")
    md.append("|------|----------|----------|-----------|")
    for rname, st, et, el in round_times:
        md.append(f"| {{rname}} | {{st}} | {{et}} | {{el:.1f}} |")
    md.append("")
    slowest = max(round_times, key=lambda x: x[3])
    fastest = min(round_times, key=lambda x: x[3])
    md.append(f"- **最慢轮次**：{{slowest[0]}}（{{slowest[3]:.1f}}s）")
    md.append(f"- **最快轮次**：{{fastest[0]}}（{{fastest[3]:.1f}}s）")
    md.append(f"- **平均每轮**：{{total_elapsed / len(round_times):.1f}}s")
else:
    md.append("（未找到执行日志，无法统计耗时）")
md.append("")

# 2. 数据概况
md.append("## 2. 数据概况")
md.append(f"- **数据来源**：`multi_table_join_result.csv`（{{total}} 行，{{len(cols)}} 列）")
md.append(f"- **字段列表**：{{', '.join(cols)}}")
md.append(f"- **CSV 文件数**：{{len(csv_files)}}，**PNG 图表数**：{{len(png_files)}}")
md.append("")
md.append("| 字段 | 唯一值 | 缺失数 | 缺失率 |")
md.append("|------|--------|--------|--------|")
for c, nuniq, missing, miss_pct in col_stats:
    md.append(f"| {{c}} | {{nuniq}} | {{missing}} | {{miss_pct}} |")
md.append("")

# 3. 交叉分析
md.append("## 3. 交叉分析")
md.append("")
if not cross_school_pay.empty:
    md.append("### 3.1 学校 × 缴费状态")
    md.append(cross_school_pay.to_markdown())
    md.append("")
    if "neg" in cross_school_pay.columns and "All" in cross_school_pay.columns:
        rates = (cross_school_pay["neg"] / cross_school_pay["All"]).drop("All", errors="ignore")
        top_school = rates.idxmax()
        top_rate = f"{{rates.max() * 100:.1f}}%"
        md.append(f"**发现**：欠费率最高的学校为 **{{top_school}}**（{{top_rate}}）。")
    md.append("")

if not organ_absense.empty:
    md.append("### 3.2 参军机构 × 缺勤月数")
    md.append("")
    md.append("| 机构 | 平均缺勤月数 | 中位数 | 人数 |")
    md.append("|------|-------------|--------|------|")
    for org, row in organ_absense.iterrows():
        md.append(f"| {{org}} | {{row['mean']:.1f}} | {{row['median']:.1f}} | {{int(row['count'])}} |")
    md.append("")
    top_org = organ_absense.index[0]
    top_mean = organ_absense.iloc[0]["mean"]
    md.append(f"**发现**：平均缺勤月数最高的机构为 **{{top_org}}**（{{top_mean:.1f}} 个月）。")
    md.append("")

# 4. 统计发现
md.append("## 4. 统计发现")
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

# 5. 可视化图表解读
md.append("## 5. 可视化图表解读")
md.append("")
for png in sorted(png_files):
    md.append(f"### {{png.stem}}")
    md.append(f"![{{png.stem}}]({{png.name}})")
    md.append("")
    # 尝试找到同名 CSV 并生成数据解读
    csv_key = png.stem
    if csv_key in csv_summaries:
        md.append(f"**数据概要**：{{csv_summaries[csv_key]}}")
        md.append("")
    # 根据图表名称中的关键词生成解读
    stem_lower = png.stem.lower()
    if "dist" in stem_lower or "distribution" in stem_lower:
        md.append("**解读**：该图展示了数据的分布特征，可观察各类别的频次差异和集中趋势。"
                  "频次较高的类别代表数据中的主要群体，应重点关注。")
    elif "join" in stem_lower or "multi" in stem_lower:
        md.append("**解读**：该图基于多表关联结果，展示了跨数据源的综合视图。"
                  "可用于发现不同维度之间的关联模式。")
    elif "count" in stem_lower or "total" in stem_lower:
        md.append("**解读**：该图展示了计数/汇总统计结果，可直观比较各分组的数量差异。")
    elif "trend" in stem_lower or "time" in stem_lower:
        md.append("**解读**：该图展示了时间序列趋势，可观察数据随时间的变化规律。")
    else:
        md.append("**解读**：该图展示了数据的可视化分析结果，请结合上下文统计数据进行解读。")
    md.append("")

# 6. 结论与建议
md.append("## 6. 结论与建议")
md.append("")
md.append("### 6.1 核心发现")
findings = []
# 基于缺失率发现
high_missing = [(c, miss_pct) for c, _, missing, miss_pct in col_stats if missing > 0]
if high_missing:
    for c, pct in high_missing:
        findings.append(f"字段 **{{c}}** 存在缺失（缺失率 {{pct}}），建议在后续分析中进行缺失值处理")
else:
    findings.append("所有字段均无缺失值，数据质量良好")
# 基于类别分布发现
for c in cat_cols:
    vc = df[c].value_counts()
    if len(vc) == 1:
        findings.append(f"字段 **{{c}}** 仅有 1 个取值（{{vc.index[0]}}），该字段无区分度，可考虑剔除")
    elif vc.iloc[0] / total > 0.7:
        findings.append(f"字段 **{{c}}** 中 **{{vc.index[0]}}** 占比超过 70%（{{vc.iloc[0]}}/{{total}}），分布严重偏斜")
# 基于数值分布发现
for c in num_cols:
    q1 = float(df[c].quantile(0.25))
    q3 = float(df[c].quantile(0.75))
    iqr = q3 - q1
    outliers = int(((df[c] < q1 - 1.5 * iqr) | (df[c] > q3 + 1.5 * iqr)).sum())
    if outliers > 0:
        findings.append(f"字段 **{{c}}** 存在 {{outliers}} 个离群值（IQR 方法），建议进一步排查")
if not findings:
    findings.append("数据整体分布均匀，未发现显著异常")
for i, f_item in enumerate(findings, 1):
    md.append(f"{{i}}. {{f_item}}")
md.append("")

md.append("### 6.2 建议措施")
suggestions = []
if high_missing:
    suggestions.append("**数据清洗**：对存在缺失的字段进行填充（均值/众数）或删除处理")
if any(df[c].value_counts().iloc[0] / total > 0.7 for c in cat_cols if len(df[c].value_counts()) > 0):
    suggestions.append("**特征筛选**：对分布严重偏斜的类别字段评估是否保留，避免引入噪声")
if not cross_school_pay.empty:
    suggestions.append("**分组对比**：针对不同学校的缴费状态差异，建议深入分析欠费原因并制定差异化催缴策略")
if not organ_absense.empty:
    suggestions.append("**风险预警**：对平均缺勤月数较高的机构（如 {{top_org}}）重点关注，评估其对学业完成率的影响")
suggestions.append("**持续监控**：建议定期更新数据并重新运行分析流程，跟踪关键指标的变化趋势")
if not suggestions:
    suggestions.append("数据质量良好，建议保持当前数据采集流程")
for s in suggestions:
    md.append(f"- {{s}}")
md.append("")

report_path = generated_dir / "{md_filename}"
report_path.write_text("\\n".join(md), encoding="utf-8")
print(f"✅ 综合分析报告已写入：{{report_path.name}}")
print(f"   报告包含 {{len(md)}} 行 Markdown，覆盖 6 个章节")
```

- ❗ Markdown 必须通过 `md` 列表逐行构建，禁止 `md_template = \\"""...\\"""` 写死整段 Markdown。
- ❗ 必须读取 multi_table_join_result.csv 并做交叉分析，禁止只列文件清单。
- ❗ 必须包含 ## 执行耗时统计、## 数据概况、## 交叉分析、## 统计发现、## 可视化图表解读、## 结论与建议 等段落。
- ❗ 可视化图表解读必须包含数据概要和分析结论，不能只放图片。
- ❗ 结论与建议必须基于实际数据生成，不能使用占位符文字。
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
