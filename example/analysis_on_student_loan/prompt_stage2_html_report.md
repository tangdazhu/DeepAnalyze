# 阶段2：数据分析结果综合报告

## ⚠️ 重要警告

系统会自动执行 bootstrap 并提供数据库路径和表结构信息，**但你必须完全忽略这些信息**。

**绝对禁止的操作**：
- ❌ **不要使用** bootstrap 提供的数据库路径（如 `/path/to/student_loan.sqlite`）
- ❌ **不要执行** 任何 SQL 查询（`SELECT`、`JOIN`、`COUNT` 等）
- ❌ **不要使用** `sqlite3.connect()` 或 `pd.read_sql_query()`
- ❌ **不要读取** `data/` 目录下的原始 CSV 文件
- ❌ **不要访问** 原始数据库中的任何表

**唯一允许的操作**：
- ✅ **只读取** `generated/` 目录下的 CSV 文件（阶段1的分析结果）
- ✅ **只读取** `generated/` 目录下的 PNG 图表
- ✅ **只读取** `generated/` 目录下的 TXT 日志文件
- ✅ **只新增** `comprehensive_analysis_report.html` 报告文件

---

## 任务目标

**核心任务**: 分析阶段1的数据分析结果，对已生成的数据文件进行二次分析，形成学生贷款分布情况的综合报告。

**⚠️ 重要**: 此阶段只分析阶段1生成的文件，不读取原始数据库或数据文件。

基于 `generated/` 目录下的 CSV 数据文件和 PNG 可视化图表，提取关键统计指标，分析学生贷款的分布特征，形成一份数据驱动的 HTML 综合报告。

## 数据来源

**主要数据来源**: `generated/` 目录下的分析结果文件

1. **CSV 数据文件** - 包含阶段1的统计汇总结果
   - `enrolled_summary.csv` - 学生入学信息统计
   - `enlist_summary.csv` - 参军学生统计
   - `disabled_count.csv` - 残疾学生统计
   - `payment_status_summary.csv` - 还款状态统计
   - `absense_summary.csv` - 缺勤月份统计
   - `multi_table_join_result.csv` - 多表关联分析结果（**核心数据源**）

2. **PNG 可视化图表** - 展示数据分布情况
   - 各类分布图、对比图、趋势图

3. **README.md** - 文件清单索引

**禁止操作**:
- ❌ 不读取原始SQLite数据库
- ❌ 不读取原始CSV/Excel文件
- ❌ 不执行任何SQL查询
- ❌ 不统计原始数据表的记录数
- ❌ **不删除 `generated/` 目录下的任何文件**
- ❌ **不修改 `generated/` 目录下的现有文件**（只能新增报告文件）

**允许操作**:
- ✅ 读取 `generated/` 目录下的所有文件（只读模式）
- ✅ 解析 `README.md` 获取文件清单
- ✅ 读取CSV文件提取关键数据
- ✅ 嵌入PNG图表到HTML报告
- ✅ 读取执行日志了解分析过程
- ✅ 在 `generated/` 目录下新增报告文件（如 `comprehensive_analysis_report.html`）

## 报告要求

### 1. 报告结构

HTML报告应包含以下章节:

#### 1.1 执行概况
- 从 `execute_round_0_bootstrap.txt` 提取数据库路径和开始时间
- 从 `README.md` 统计生成文件总数
- 从 `summary_analysis.html` 提取执行时长
- 展示阶段1的分析轮次和任务完成情况

#### 1.2 学生贷款分布分析（基于阶段1的分析结果）

**从 CSV 文件中提取关键统计指标**：

- **学校分布**: 读取 `enrolled_summary.csv`，统计各学校的学生数量分布
  - Top 学校排名
  - 学校数量统计
  - 展示 `enrolled_school_dist.png` 图表

- **参军学生特征**: 读取 `enlist_summary.csv`，分析参军学生的分布
  - 参军学生数量
  - 所属学院/组织分布
  - 展示 `enlist_organ_dist.png` 图表

- **残疾学生统计**: 读取 `disabled_count.csv`，统计残疾学生情况
  - 残疾学生总数
  - 占比分析
  - 展示 `disabled_vs_total.png` 对比图

- **还款状态分布**: 读取 `payment_status_summary.csv`，分析还款状态
  - pos/neg 状态分布
  - 无需还款学生占比
  - 展示 `payment_status_dist.png` 图表

- **缺勤月份分布**: 读取 `absense_summary.csv`，分析缺勤特征
  - 缺勤月份分布
  - 高峰月份识别
  - 展示 `absense_month_dist.png` 图表

#### 1.3 多维度关联分析（核心分析）

**从 `multi_table_join_result.csv` 进行深度分析**：

- **数据结构分析**
  - 读取 CSV 文件，识别所有字段（name, school, organ, bool, month 等）
  - 统计总记录数
  - 识别数据完整性

- **学校 × 群体交叉分析**
  - 各学校的参军学生分布
  - 各学校的残疾学生分布
  - 各学校的还款状态分布

- **群体特征对比**
  - 参军 vs 非参军学生的特征对比
  - 残疾 vs 非残疾学生的特征对比
  - 不同还款状态学生的特征对比

- **缺勤模式分析**
  - 不同群体的缺勤月份分布
  - 识别高风险群体（缺勤时间长的学生）

- **可视化展示**
  - 展示 `multi_table_join_result.png` 综合分析图表

#### 1.4 关键发现与建议（基于实际数据）

**⚠️ 所有发现必须基于实际读取的 CSV 数据，不得虚构**

- **数据支持的关键发现**
  - 从 `multi_table_join_result.csv` 中统计得出的实际数字
  - 例如："共有 X 名学生，其中 Y 名参军（占比 Z%）"
  - 例如："残疾学生共 M 名，主要分布在 N 所学校"
  - 例如："pos 状态学生 P 名，neg 状态学生 Q 名"

- **分布特征总结**
  - 学校分布的集中度或分散度
  - 特殊群体的占比和分布规律
  - 还款状态的整体情况

- **政策建议**（基于数据发现）
  - 针对高占比群体的支持建议
  - 针对分布不均的资源配置建议
  - 针对高风险群体的关注建议

### 2. 技术要求

#### 2.1 数据读取
```python
import pandas as pd
from pathlib import Path
import re

# 第一步: 读取README.md获取文件清单
GENERATED_DIR = Path("generated")
readme_path = GENERATED_DIR / "README.md"

with open(readme_path, "r", encoding="utf-8") as f:
    readme_content = f.read()

# 第二步: 智能解析文件清单
csv_files = list(GENERATED_DIR.glob("*.csv"))
png_files = list(GENERATED_DIR.glob("*.png"))
txt_files = list(GENERATED_DIR.glob("execute_round_*.txt"))

# 第三步: 读取核心数据文件 multi_table_join_result.csv
multi_table_csv = GENERATED_DIR / "multi_table_join_result.csv"
if multi_table_csv.exists():
    df_multi = pd.read_csv(multi_table_csv)
    
    # 提取关键统计指标
    total_students = len(df_multi)
    
    # 学校分布统计
    school_dist = df_multi['school'].value_counts() if 'school' in df_multi.columns else None
    
    # 参军学生统计
    enlist_count = len(df_multi[df_multi['organ'].notna()]) if 'organ' in df_multi.columns else 0
    
    # 残疾学生统计（假设有 disabled 相关字段）
    # 根据实际字段调整
    
    # 还款状态统计
    payment_dist = df_multi['bool'].value_counts() if 'bool' in df_multi.columns else None
    
    # 缺勤月份统计
    absense_dist = df_multi['month'].value_counts() if 'month' in df_multi.columns else None
    
    print(f"✅ 成功读取多表关联数据: {total_students} 条记录")
    print(f"   字段列表: {list(df_multi.columns)}")
else:
    print("⚠️ 未找到 multi_table_join_result.csv")

# 第四步: 读取其他汇总CSV文件
enrolled_summary = pd.read_csv(GENERATED_DIR / "enrolled_summary.csv") if (GENERATED_DIR / "enrolled_summary.csv").exists() else None
disabled_count = pd.read_csv(GENERATED_DIR / "disabled_count.csv") if (GENERATED_DIR / "disabled_count.csv").exists() else None

# ⚠️ 禁止读取原始数据库
# ❌ 错误示例: sqlite3.connect(DB_PATH)
# ❌ 错误示例: pd.read_sql_query("SELECT COUNT(*) FROM table", conn)
```

#### 2.2 图片嵌入
```python
# 方案1: 使用相对路径(推荐)
<img src="enrolled_school_dist.png" alt="学校分布图">

# 方案2: Base64编码嵌入
import base64
with open("generated/enrolled_school_dist.png", "rb") as f:
    img_data = base64.b64encode(f.read()).decode()
    img_tag = f'<img src="data:image/png;base64,{img_data}">'
```

#### 2.3 样式设计
- 使用现代化CSS框架(如Bootstrap或自定义样式)
- 响应式设计,支持移动端查看
- 清晰的章节导航
- 数据表格使用条纹样式和悬停效果

### 3. 数据分析示例

**从 `multi_table_join_result.csv` 提取学生贷款分布情况**：

```python
import pandas as pd
from pathlib import Path

GENERATED_DIR = Path("generated")

# 读取核心数据
df = pd.read_csv(GENERATED_DIR / "multi_table_join_result.csv")

# 1. 学校分布分析
print("=== 学校分布分析 ===")
school_counts = df['school'].value_counts()
print(f"共有 {len(school_counts)} 所学校")
print(f"学生总数: {len(df)}")
print(f"\nTop 5 学校:")
print(school_counts.head())

# 2. 参军学生分布
print("\n=== 参军学生分布 ===")
enlist_students = df[df['organ'].notna()]
print(f"参军学生数: {len(enlist_students)}")
print(f"参军学生占比: {len(enlist_students)/len(df)*100:.2f}%")
if len(enlist_students) > 0:
    organ_dist = enlist_students['organ'].value_counts()
    print(f"参军学生所属组织分布:\n{organ_dist}")

# 3. 还款状态分析
print("\n=== 还款状态分析 ===")
payment_dist = df['bool'].value_counts()
print(f"还款状态分布:\n{payment_dist}")
print(f"pos 状态占比: {payment_dist.get('pos', 0)/len(df)*100:.2f}%")
print(f"neg 状态占比: {payment_dist.get('neg', 0)/len(df)*100:.2f}%")

# 4. 缺勤月份分析
print("\n=== 缺勤月份分析 ===")
absense_dist = df['month'].value_counts().sort_index()
print(f"缺勤月份分布:\n{absense_dist}")
print(f"缺勤高峰月份: {absense_dist.idxmax()}")

# 5. 交叉分析：学校 × 参军状态
print("\n=== 学校 × 参军状态交叉分析 ===")
cross_analysis = pd.crosstab(df['school'], df['organ'].notna(), margins=True)
print(cross_analysis)
```

### 4. 完整代码模板

```python
import pandas as pd
from pathlib import Path
from datetime import datetime

# 路径配置
GENERATED_DIR = Path("generated")
OUTPUT_HTML = GENERATED_DIR / "comprehensive_analysis_report.html"

# ⚠️ 重要：只读取 generated 目录下的文件，不删除、不修改
# ✅ 允许：读取现有文件（CSV、PNG、TXT）
# ✅ 允许：新增报告文件（comprehensive_analysis_report.html）
# ❌ 禁止：删除任何现有文件
# ❌ 禁止：修改任何现有文件（如 README.md、summary_analysis.html 等）

csv_files = list(GENERATED_DIR.glob("*.csv"))
png_files = list(GENERATED_DIR.glob("*.png"))
txt_files = list(GENERATED_DIR.glob("execute_round_*.txt"))

# 读取README.md获取元数据
readme_path = GENERATED_DIR / "README.md"
if readme_path.exists():
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_content = f.read()
    # 从README提取文件数量信息
    import re
    csv_count_match = re.search(r'CSV文件数量.*?(\d+)', readme_content)
    png_count_match = re.search(r'PNG图表数量.*?(\d+)', readme_content)
    csv_count = int(csv_count_match.group(1)) if csv_count_match else len(csv_files)
    png_count = int(png_count_match.group(1)) if png_count_match else len(png_files)
else:
    csv_count = len(csv_files)
    png_count = len(png_files)

# 智能读取CSV文件(动态文件名)
data_insights = []
for csv_file in csv_files:
    try:
        df = pd.read_csv(csv_file)
        data_insights.append({
            'file': csv_file.name,
            'rows': len(df),
            'columns': len(df.columns),
            'summary': df.describe(include='all').to_dict() if len(df) > 0 else {}
        })
    except Exception as e:
        data_insights.append({'file': csv_file.name, 'error': str(e)})

# 计算关键指标(基于生成的文件,不查询原始数据库)
total_files = len(csv_files) + len(png_files)
analysis_rounds = len(txt_files) - 1  # 排除bootstrap

# ❌ 禁止的操作示例:
# with sqlite3.connect(DB_PATH, timeout=30) as conn:  # 不要这样做!
#     tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)

# 生成HTML报告
html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>学生贷款数据综合分析报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        .header .meta {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        .nav {{
            background: #f8f9fa;
            padding: 15px 40px;
            border-bottom: 2px solid #e9ecef;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .nav a {{
            color: #667eea;
            text-decoration: none;
            margin-right: 20px;
            font-weight: 500;
            transition: color 0.3s;
        }}
        .nav a:hover {{ color: #764ba2; }}
        .content {{
            padding: 40px;
        }}
        .section {{
            margin-bottom: 50px;
        }}
        .section h2 {{
            color: #667eea;
            font-size: 2em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
        }}
        .section h3 {{
            color: #764ba2;
            font-size: 1.5em;
            margin: 30px 0 15px 0;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
            text-align: center;
            transition: transform 0.3s;
        }}
        .stat-card:hover {{
            transform: translateY(-5px);
        }}
        .stat-card .number {{
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }}
        .stat-card .label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        table th {{
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }}
        table td {{
            padding: 12px 15px;
            border-bottom: 1px solid #e9ecef;
        }}
        table tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        table tr:hover {{
            background: #e9ecef;
        }}
        .chart-container {{
            margin: 30px 0;
            text-align: center;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        .finding {{
            background: #e8f5e9;
            border-left: 4px solid #4caf50;
            padding: 20px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .finding h4 {{
            color: #2e7d32;
            margin-bottom: 10px;
        }}
        .recommendation {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 20px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .recommendation h4 {{
            color: #f57c00;
            margin-bottom: 10px;
        }}
        .footer {{
            background: #f8f9fa;
            padding: 30px;
            text-align: center;
            color: #6c757d;
            border-top: 2px solid #e9ecef;
        }}
        .badge {{
            display: inline-block;
            padding: 5px 10px;
            background: #667eea;
            color: white;
            border-radius: 20px;
            font-size: 0.85em;
            margin: 5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 学生贷款数据综合分析报告</h1>
            <div class="meta">
                <p>生成时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</p>
                <p>数据库: student_loan.sqlite</p>
            </div>
        </div>

        <div class="nav">
            <a href="#overview">数据概况</a>
            <a href="#single-table">单表分析</a>
            <a href="#correlation">关联分析</a>
            <a href="#findings">关键发现</a>
        </div>

        <div class="content">
            <section id="overview" class="section">
                <h2>📈 数据概况</h2>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="label">CSV数据文件</div>
                        <div class="number">{csv_count}</div>
                    </div>
                    <div class="stat-card">
                        <div class="label">PNG可视化图表</div>
                        <div class="number">{png_count}</div>
                    </div>
                    <div class="stat-card">
                        <div class="label">分析轮次</div>
                        <div class="number">{analysis_rounds}</div>
                    </div>
                    <div class="stat-card">
                        <div class="label">总文件数</div>
                        <div class="number">{total_files}</div>
                    </div>
                </div>

                <h3>生成文件统计</h3>
                <table>
                    <thead>
                        <tr>
                            <th>文件名</th>
                            <th>类型</th>
                            <th>大小</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"<tr><td>{f.name}</td><td>{'CSV数据' if f.suffix == '.csv' else 'PNG图表'}</td><td>{f.stat().st_size:,} bytes</td></tr>" for f in (csv_files + png_files)[:20]])}
                    </tbody>
                </table>
            </section>

            <section id="single-table" class="section">
                <h2>📋 单表分析结果</h2>

                <!-- 动态插入所有PNG图表 -->
                {''.join([f'''
                <h3>{f.stem.replace('_', ' ').title()}</h3>
                <div class="chart-container">
                    <img src="{f.name}" alt="{f.stem}">
                    <p><em>{f.stem.replace('_', ' ')}</em></p>
                </div>
                ''' for f in png_files if f.name != 'multi_table_join_result.png'])}
            </section>

            <section id="correlation" class="section">
                <h2>🔗 关联分析</h2>
                
                <h3>多表关联结果</h3>
                <div class="chart-container">
                    <img src="multi_table_join_result.png" alt="多表关联分析">
                    <p><em>多表 JOIN 结果可视化</em></p>
                </div>
                
                <p>基于 multi_table_join_result.csv 的关联分析:</p>
                <ul>
                    <li>从CSV文件中读取实际的关联数据</li>
                    <li>分析不同群体的分布特征</li>
                    <li>识别数据中的关联模式</li>
                </ul>
            </section>

            <section id="findings" class="section">
                <h2>💡 关键发现与建议</h2>

                <p><strong>⚠️ 重要</strong>: 以下发现需要基于实际读取的CSV数据生成，不要使用虚构数据。</p>

                <!-- 从 multi_table_join_result.csv 读取数据后动态生成发现 -->
                <div class="finding">
                    <h4>🎯 发现示例: 基于实际数据的分析</h4>
                    <p>从 CSV 文件中提取关键统计指标，例如：</p>
                    <ul>
                        <li>各学校的学生数量分布</li>
                        <li>不同群体（参军、残疾、还款状态）的人数统计</li>
                        <li>缺勤月份的分布特征</li>
                    </ul>
                    <span class="badge">数据驱动</span>
                </div>

                <h3>📌 分析建议</h3>
                <p>建议从以下角度进行深入分析：</p>
                <ul>
                    <li>读取 multi_table_join_result.csv，统计各维度的分布情况</li>
                    <li>对比不同学校的学生群体特征</li>
                    <li>分析特殊群体（参军、残疾）的占比和分布</li>
                    <li>识别数据中的异常值或特殊模式</li>
                </ul>
            </section>
        </div>

        <div class="footer">
            <p><strong>DeepAnalyze 阶段2报告</strong> - 基于阶段1生成文件的智能分析</p>
            <p>本报告基于 {total_files} 个生成文件自动创建</p>
            <p>数据来源: generated/ 目录 | 报告位置: generated/analyze/</p>
            <p>© 2025 DeepAnalyze Project. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""

# 保存HTML报告到analyze子目录
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"✅ HTML报告已生成: {OUTPUT_HTML}")
print(f"📊 分析了 {analysis_rounds} 轮数据处理")
print(f"📁 基于 {total_files} 个生成文件")
print(f"🎨 包含 {len(png_files)} 个可视化图表")
print(f"📂 报告保存在: generated/analyze/ 目录")
```

## 执行方式

### 方式1: 在DeepAnalyze系统中执行

将此提示词文件上传到系统,作为新的分析任务:

```bash
# 在前端选择 prompt_stage2_html_report.md
# 系统会自动读取 generated/ 目录下的文件并生成报告
```

### 方式2: 独立Python脚本

将上述代码模板保存为 `generate_html_report.py`,直接执行:

```bash
cd ~/DeepAnalyze/demo/workspace/session_XXXXX
python generate_html_report.py
```

## 输出文件

- `generated/comprehensive_analysis_report.html` - 完整的HTML报告
- 报告包含所有图表的相对路径引用(如 `enrolled_school_dist.png`)
- 支持在浏览器中直接打开查看

## 注意事项

1. **文件保护（最重要）**: 
   - ❌ **禁止删除** `generated/` 目录下的任何文件
   - ❌ **禁止修改** 现有文件（如 `README.md`、`summary_analysis.html`、所有 CSV/PNG 文件）
   - ✅ **只允许新增** 报告文件（`comprehensive_analysis_report.html`）
   - ✅ **只读模式** 读取所有现有文件

2. **路径一致性**: HTML中的图片使用相对路径 `图片名.png` 引用同目录的PNG文件

3. **中文编码**: 使用 `encoding="utf-8"` 确保中文正常显示

4. **响应式设计**: 报告支持PC和移动端查看

5. **数据来源**: 只从 `generated/` 目录读取文件,不访问原始数据库

6. **动态文件名**: 使用 `glob()` 动态识别实际生成的文件,不硬编码文件名

7. **数据驱动**: 所有分析结论必须基于实际读取的CSV数据,不使用虚构数据
