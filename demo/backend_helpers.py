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

def _find_best_csv(png_stem, csv_files_list):
    """为 PNG 找到最佳匹配的 CSV：先同名，再关键词模糊匹配"""
    exact = generated_dir / f"{{png_stem}}.csv"
    if exact.exists():
        return exact
    stem_lower = png_stem.lower()
    keywords = [w for w in re.split(r"[_\\-\\s]+", stem_lower) if len(w) > 2]
    best_path, best_score = None, 0
    for cf in csv_files_list:
        cf_lower = cf.stem.lower()
        score = sum(1 for kw in keywords if kw in cf_lower)
        if score > best_score:
            best_score = score
            best_path = cf
    return best_path if best_score > 0 else None

def _build_interp(png_stem, matched_csv, df_main):
    """基于匹配的 CSV 和主表数据，生成有业务含义的图表解读"""
    parts = []
    stem_lower = png_stem.lower()
    local_df = None
    if matched_csv and matched_csv.exists():
        try:
            local_df = pd.read_csv(matched_csv)
            parts.append(f"数据源 `{{matched_csv.name}}`（{{len(local_df)}} 行 {{len(local_df.columns)}} 列）。")
        except Exception:
            pass
    # 数值列统计
    src = local_df if local_df is not None else df_main
    _nc = [c for c in src.columns if pd.api.types.is_numeric_dtype(src[c])]
    for c in _nc:
        _mean, _med = float(src[c].mean()), float(src[c].median())
        _min, _max = float(src[c].min()), float(src[c].max())
        parts.append(f"`{{c}}` 均值={{_mean:.2f}}，中位数={{_med:.2f}}，范围[{{_min:.2f}}, {{_max:.2f}}]。")
    # 分类列分布
    _cc = [c for c in src.columns if src[c].dtype == "object"]
    for c in _cc:
        _vc = src[c].value_counts()
        _n = len(src)
        _top3 = "; ".join(f"{{k}}({{int(v)}}人,{{v/_n*100:.0f}}%)" for k, v in _vc.head(3).items())
        parts.append(f"`{{c}}` 共 {{len(_vc)}} 个取值，Top3：{{_top3}}。")
    # 业务含义推断
    if any(kw in stem_lower for kw in ["absense", "absent", "month"]):
        if _nc:
            c0 = _nc[0]
            high_cnt = int((src[c0] >= 6).sum()) if c0 in src.columns else 0
            parts.append(f"缺勤月数反映学业连续性风险。")
            if high_cnt > 0:
                parts.append(f"其中 {{high_cnt}} 人缺勤≥6个月，属长期离校群体，学业中断和还款违约风险较高。")
    elif any(kw in stem_lower for kw in ["disabled", "残障"]):
        parts.append("残障学生群体虽占比较小，但可能面临更大的就业困难和还款压力，建议纳入贷款减免或延期还款政策的优先考虑范围。")
    elif any(kw in stem_lower for kw in ["enlist", "organ", "参军"]):
        if _cc:
            _vc = src[_cc[0]].value_counts()
            parts.append(f"参军机构分布反映学生服役去向集中度，**{{_vc.index[0]}}** 占比最高（{{int(_vc.iloc[0])}}人），不同机构学生可能适用不同的贷款减免政策。")
    elif any(kw in stem_lower for kw in ["school", "enrolled", "学校"]):
        if _cc:
            _vc = src[_cc[0]].value_counts()
            parts.append(f"学校分布显示学生集中度，**{{_vc.index[0]}}** 学生最多（{{int(_vc.iloc[0])}}人），不同学校的学费水平和就业前景差异可能影响贷款违约风险。")
    elif any(kw in stem_lower for kw in ["payment", "bool", "缴费"]):
        if _cc:
            _vc = src[_cc[0]].value_counts()
            if len(_vc) == 1:
                parts.append(f"所有学生缴费状态均为 **{{_vc.index[0]}}**（100%），表明当前政策执行覆盖全面，无欠费记录。")
            else:
                parts.append(f"缴费状态分布直接反映贷款还款健康度，是风险管理的核心指标。")
    elif any(kw in stem_lower for kw in ["join", "multi", "关联"]):
        parts.append("多表关联结果整合了学校、缴费状态、缺勤月数、服役机构等多维信息，可用于识别高风险借款人的共同特征。")
    if not parts:
        parts.append(f"该图展示了 {{png_stem}} 的可视化分析结果，请结合上下文数据进行业务解读。")
    return " ".join(parts)

for png in sorted(png_files):
    md.append(f"### {{png.stem}}")
    md.append(f"![{{png.stem}}]({{png.name}})")
    md.append("")
    csv_key = png.stem
    if csv_key in csv_summaries:
        md.append(f"**数据概要**：{{csv_summaries[csv_key]}}")
        md.append("")
    matched_csv = _find_best_csv(png.stem, csv_files)
    interp = _build_interp(png.stem, matched_csv, df)
    md.append(f"**解读**：{{interp}}")
    md.append("")

# 6. 结论与建议
md.append("## 6. 结论与建议")
md.append("")
md.append("### 6.1 核心发现")
findings = []
high_missing = [(c, miss_pct) for c, _, missing, miss_pct in col_stats if missing > 0]

# ── 主题 1：缺勤风险 ──
for c in num_cols:
    _mean = float(df[c].mean())
    _med = float(df[c].median())
    q1, q3 = float(df[c].quantile(0.25)), float(df[c].quantile(0.75))
    high_cnt = int((df[c] >= q3 + (q3 - q1)).sum())
    findings.append(
        f"**缺勤风险突出**：数值字段 **{{c}}** 中位数={{_med:.1f}}，均值={{_mean:.2f}}，"
        f"Q25={{q1:.1f}}，Q75={{q3:.1f}}。"
        + (f"其中 {{high_cnt}} 人处于高值区间（≥{{q3+(q3-q1):.1f}}），属高风险群体，学业中断风险较高，建议建立学业预警机制。"
           if high_cnt > 0 else "分布较为集中，暂无极端高值个体。")
    )

# ── 主题 2：残障群体关注 ──
_disabled_csvs = [f for f in csv_files if "disabled" in f.stem.lower()]
if _disabled_csvs:
    try:
        _dis_df = pd.read_csv(_disabled_csvs[0])
        _dis_nc = [c for c in _dis_df.columns if pd.api.types.is_numeric_dtype(_dis_df[c])]
        if _dis_nc:
            _dis_total = int(_dis_df[_dis_nc[0]].sum()) if len(_dis_nc) >= 1 else 0
            findings.append(
                f"**残障学生群体需特殊关注**：残障学生数据显示共 {{_dis_total}} 人，"
                f"尽管占比可能较小，但该群体面临更大的就业困难和还款压力，"
                f"建议将其纳入贷款减免或延期还款政策的优先考虑范围，保障其教育权益。"
            )
    except Exception:
        pass

# ── 主题 3：学校与机构分布集中度 ──
_school_findings = []
_organ_findings = []
for c in cat_cols:
    vc = df[c].value_counts()
    top_name = vc.index[0]
    top_cnt = int(vc.iloc[0])
    top_pct = vc.iloc[0] / total * 100
    if len(vc) > 1:
        _item = f"**{{c}}** 中 **{{top_name}}** 占比最高（{{top_cnt}}人，{{top_pct:.0f}}%）"
        if any(kw in c.lower() for kw in ["school", "enrolled"]):
            _school_findings.append(_item)
        elif any(kw in c.lower() for kw in ["organ", "enlist"]):
            _organ_findings.append(_item)
        else:
            _school_findings.append(_item)
if _school_findings or _organ_findings:
    parts = []
    if _school_findings:
        parts.append("、".join(_school_findings))
    if _organ_findings:
        parts.append("、".join(_organ_findings))
    findings.append(
        f"**学校与机构分布不均**：{{'；'.join(parts)}}。"
        f"不同学校和机构在学业连续性与服役去向上的差异显著，建议针对高占比群体制定差异化管理策略。"
    )

# ── 主题 4：缴费/还款健康度 ──
for c in cat_cols:
    vc = df[c].value_counts()
    if len(vc) == 1:
        findings.append(
            f"**缴费状态整体健康**：所有学生 **{{c}}** 均为 **{{vc.index[0]}}**（100%），"
            f"无欠费记录，政策执行覆盖全面，但需持续监控防止未来出现分化。"
        )
if not cross_school_pay.empty:
    if "neg" in cross_school_pay.columns and "All" in cross_school_pay.columns:
        rates = (cross_school_pay["neg"] / cross_school_pay["All"]).drop("All", errors="ignore")
        top_s = rates.idxmax()
        findings.append(
            f"**欠费风险集中**：交叉分析显示 **{{top_s}}** 欠费率最高（{{rates.max()*100:.1f}}%），"
            f"建议对该校加强财务干预和学生帮扶。"
        )

# ── 主题 5：交叉分析——机构缺勤差异 ──
if not organ_absense.empty:
    _top_org = organ_absense.index[0]
    _top_mean = organ_absense.iloc[0]["mean"]
    _top_cnt = int(organ_absense.iloc[0]["count"])
    _bot_org = organ_absense.index[-1]
    _bot_mean = organ_absense.iloc[-1]["mean"]
    findings.append(
        f"**机构间缺勤差异显著**：**{{_top_org}}** 平均缺勤 {{_top_mean:.1f}} 个月（{{_top_cnt}} 人），"
        f"而 **{{_bot_org}}** 仅 {{_bot_mean:.1f}} 个月，提示不同服役机构对学业连续性影响不同。"
    )

# ── 数据质量（兜底） ──
if high_missing:
    for c, pct in high_missing:
        findings.append(f"**数据质量**：字段 **{{c}}** 存在缺失（缺失率 {{pct}}），可能影响分析准确性")
elif not findings:
    findings.append("数据整体质量良好，所有字段均无缺失值")

for i, f_item in enumerate(findings, 1):
    md.append(f"{{i}}. {{f_item}}")
md.append("")

md.append("### 6.2 建议措施")
suggestions = []
# 缺勤相关
for c in num_cols:
    q1, q3 = float(df[c].quantile(0.25)), float(df[c].quantile(0.75))
    high_cnt = int((df[c] >= q3 + (q3 - q1)).sum())
    if high_cnt > 0:
        suggestions.append(
            f"**学业预警**：对 **{{c}}** 高值群体（{{high_cnt}} 人）建立预警机制，联合学工部门开展学业支持计划，防止学业中断"
        )
# 残障群体
if _disabled_csvs:
    suggestions.append("**特殊群体帮扶**：将残障学生纳入贷款减免或延期还款政策的优先考虑范围，保障其教育权益")
# 学校/机构管理
if _school_findings or _organ_findings:
    suggestions.append("**差异化管理**：针对高占比学校和机构的学生群体，制定差异化的学业支持与管理策略")
# 缴费相关
if not cross_school_pay.empty:
    if "neg" in cross_school_pay.columns:
        suggestions.append("**财务干预**：针对欠费率较高的学校深入分析原因，制定针对性催收或帮扶策略")
    else:
        suggestions.append("**政策延续**：当前缴费状态良好，建议维持现有政策并建立预警机制，防止未来出现欠费分化")
# 通用建议
if high_missing:
    suggestions.append("**数据治理**：对缺失字段进行填充或删除处理，确保后续建模数据完整性")
suggestions.append("**持续监控**：建议定期更新数据并重新运行分析流程，动态跟踪关键指标变化趋势，提升管理精细化水平")
suggestions.append("**流程模块化**：将本分析流程模块化，支持未来快速扩展至其他学生群体或分析维度")
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


def fix_report_unresolved_placeholders(generated_dir):
    """检测并修复 generated/ 下 .md 报告中未展开的模板变量（如 {png.name}）。

    模型有时不严格遵循 f-string 模板，导致 Markdown 中出现字面量
    ``{png.name}``、``{png.stem}`` 等，前端渲染时会 404。
    本函数扫描所有非 README 的 .md 文件，将这些占位符替换为实际的
    PNG 文件列表。

    Returns:
        修复过的文件名列表（空列表表示无需修复）。
    """
    from pathlib import Path

    generated_path = Path(generated_dir)
    if not generated_path.exists():
        return []

    png_files = sorted(generated_path.glob("*.png"))
    if not png_files:
        return []

    fixed_files = []
    placeholder_patterns = [
        "{png.name}",
        "{png.stem}",
        "{png}",
        "{p.name}",
        "{p.stem}",
    ]

    for md_file in generated_path.glob("*.md"):
        if md_file.name.lower() == "readme.md":
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        has_placeholder = any(ph in content for ph in placeholder_patterns)
        if not has_placeholder:
            continue

        # 替换策略：找到包含占位符的图片引用行，替换为实际 PNG 列表
        lines = content.splitlines()
        new_lines = []
        placeholder_section_replaced = False

        for line in lines:
            if any(ph in line for ph in placeholder_patterns):
                if not placeholder_section_replaced:
                    # 第一次遇到占位符行，替换为所有 PNG 的图片引用
                    for png in png_files:
                        new_lines.append(f"### {png.stem}")
                        new_lines.append(f"![{png.stem}]({png.name})")
                        new_lines.append("")
                    placeholder_section_replaced = True
                # 跳过原始占位符行
            else:
                new_lines.append(line)

        new_content = "\n".join(new_lines)
        if new_content != content:
            md_file.write_text(new_content, encoding="utf-8")
            fixed_files.append(md_file.name)

    return fixed_files


def patch_report_round9_timing(generated_dir: str) -> bool:
    """在 markdown_report 代码执行后，将报告中缺失的轮次耗时从 execute_round_*.txt 回填。

    报告模板在代码执行时只能读取到已有的 execute_round_*.txt（不含自身），
    本函数在代码执行完毕后由 backend 调用，扫描所有 execute_round_*.txt，
    将报告中尚未包含的轮次耗时追加到耗时统计表中，并更新总耗时和轮次数。

    Returns:
        True 表示成功回填，False 表示无需或无法回填。
    """
    import re as _re
    from pathlib import Path as _Path

    gen_dir = _Path(generated_dir)
    report_candidates = list(gen_dir.glob("comprehensive_analysis_report*.md"))
    if not report_candidates:
        return False
    report_path = report_candidates[0]

    try:
        content = report_path.read_text(encoding="utf-8")
    except Exception:
        return False

    # 找出报告中已有的 Round 编号
    existing_rounds = set(_re.findall(r"Round\s+(\d+)", content))

    # 扫描所有 execute_round_*.txt，找出报告中缺失的
    missing_rounds = []
    for log_file in sorted(gen_dir.glob("execute_round_*.txt")):
        m_num = _re.search(r"execute_round_(\d+)\.txt", log_file.name)
        if not m_num:
            continue
        round_num = m_num.group(1)
        if round_num in existing_rounds or round_num == "0":
            continue
        # 解析耗时
        elapsed, start_ts, end_ts = None, None, None
        try:
            for line in log_file.read_text(encoding="utf-8").splitlines():
                m = _re.match(r"Elapsed:\s*([\d.]+)s", line)
                if m:
                    elapsed = float(m.group(1))
                m2 = _re.match(r"Start:\s*(.+)", line)
                if m2:
                    start_ts = m2.group(1).strip()
                m3 = _re.match(r"End:\s*(.+)", line)
                if m3:
                    end_ts = m3.group(1).strip()
        except Exception:
            continue
        if elapsed is not None:
            missing_rounds.append((round_num, start_ts, end_ts, elapsed))

    if not missing_rounds:
        return False

    lines = content.splitlines()
    new_lines = []
    patched = False
    total_added_elapsed = sum(r[3] for r in missing_rounds)
    for line in lines:
        if line.startswith("- **最慢轮次**") and not patched:
            for rnum, start_ts, end_ts, elapsed in missing_rounds:
                new_lines.append(
                    f"| Round {rnum} | {start_ts or '-'} | {end_ts or '-'} | {elapsed:.1f} |"
                )
            patched = True
        if line.startswith("**总耗时**") and patched:
            m_total = _re.match(r"\*\*总耗时\*\*：([\d.]+)\s*秒.*共\s*(\d+)\s*轮", line)
            if m_total:
                old_total = float(m_total.group(1))
                old_rounds = int(m_total.group(2))
                new_total = old_total + total_added_elapsed
                new_rounds = old_rounds + len(missing_rounds)
                new_min = new_total / 60
                line = f"**总耗时**：{new_total:.1f} 秒（{new_min:.1f} 分钟），共 {new_rounds} 轮"
        new_lines.append(line)

    if patched:
        report_path.write_text("\n".join(new_lines), encoding="utf-8")
    return patched


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


def cleanup_rounds_from(generated_dir, from_round: int) -> list[str]:
    """删除 >= from_round 的轮次产出文件，为重跑做准备。

    删除规则：
    - execute_round_{N}.txt（N >= from_round）
    - README.md（Round 8 产出）
    - comprehensive_analysis_report*.md（Round 9 产出）

    不删除：
    - CSV 文件（Round 1~7 产出）
    - PNG 文件（Round 1~7 产出）
    - execute_round_0_bootstrap.txt

    Args:
        generated_dir: generated/ 目录路径（str 或 Path）
        from_round: 从哪一轮开始清理（含该轮）

    Returns:
        被删除的文件名列表
    """
    import re as _re
    from pathlib import Path as _Path

    gen_dir = _Path(generated_dir)
    if not gen_dir.exists():
        return []

    deleted = []

    # 删除 execute_round_{N}.txt（N >= from_round）
    for f in sorted(gen_dir.glob("execute_round_*.txt")):
        m = _re.search(r"execute_round_(\d+)\.txt", f.name)
        if not m:
            continue
        round_num = int(m.group(1))
        if round_num >= from_round:
            f.unlink()
            deleted.append(f.name)

    # 删除 README.md（Round 8 产出）
    if from_round <= 8:
        readme = gen_dir / "README.md"
        if readme.exists():
            readme.unlink()
            deleted.append("README.md")

    # 删除 comprehensive_analysis_report*.md（Round 9 产出）
    if from_round <= 9:
        for f in gen_dir.glob("comprehensive_analysis_report*.md"):
            f.unlink()
            deleted.append(f.name)

    return deleted
