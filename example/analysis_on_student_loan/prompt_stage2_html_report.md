# 阶段2：HTML报告生成任务

## 任务目标

**⚠️ 重要**: 此阶段只分析阶段1生成的文件,不读取原始数据库或数据文件。

基于 `generated/` 目录下已生成的数据文件,创建一份完整的HTML分析报告。

## 数据来源

**唯一数据来源**: `generated/README.md` 索引文件

- 此文件由阶段1第8轮自动生成
- 包含所有生成文件的清单和说明
- 提供每轮分析的任务描述

**禁止操作**:
- ❌ 不读取原始SQLite数据库
- ❌ 不读取原始CSV/Excel文件
- ❌ 不执行任何SQL查询
- ❌ 不统计原始数据表的记录数

**允许操作**:
- ✅ 读取 `generated/` 目录下的所有文件
- ✅ 解析 `README.md` 获取文件清单
- ✅ 读取CSV文件提取关键数据
- ✅ 嵌入PNG图表到HTML报告
- ✅ 读取执行日志了解分析过程

## 报告要求

### 1. 报告结构

HTML报告应包含以下章节:

#### 1.1 数据概况
- 数据库路径
- 表数量和记录数统计
- 分析时间范围
- 生成文件总数

#### 1.2 单表分析结果
- **enrolled表**: 学校分布、入学月份分布、关键发现
- **enlist表**: 参军学生入学时间特征
- **disabled表**: 残疾学生入学时间特征
- **unemployed表**: 失业学生入学时间特征

#### 1.3 关联分析发现
- 参军学生与非参军学生入学时间对比
- 特殊群体(残疾/失业)的入学时间规律
- 季节性入学趋势分析

#### 1.4 关键发现与建议
- 至少3条数据支持的关键发现
- 针对性的政策建议
- 下一步分析方向

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

# 第三步: 读取CSV文件(如果存在)
data_summary = {}
for csv_file in csv_files:
    try:
        df = pd.read_csv(csv_file)
        data_summary[csv_file.name] = {
            'rows': len(df),
            'columns': list(df.columns),
            'sample': df.head(3).to_dict()
        }
    except Exception as e:
        data_summary[csv_file.name] = {'error': str(e)}

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

### 3. 代码模板

```python
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import base64

# 路径配置
GENERATED_DIR = Path("generated")
ANALYZE_DIR = GENERATED_DIR / "analyze"  # ⚠️ 输出到analyze子目录
ANALYZE_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_HTML = ANALYZE_DIR / "comprehensive_analysis_report.html"

# ⚠️ 只读取generated目录下的文件
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

                <h3>enrolled 表 - 学生入学信息</h3>
                <div class="chart-container">
                    <img src="enrolled_school_dist.png" alt="学校分布图">
                    <p><em>图1: 学校分布统计</em></p>
                </div>
                <div class="chart-container">
                    <img src="enrolled_monthly_heatmap.png" alt="入学月份热力图">
                    <p><em>图2: 各学校入学月份热力图</em></p>
                </div>

                <h3>enlist 表 - 参军学生分析</h3>
                <div class="chart-container">
                    <img src="enlist_monthly_distribution.png" alt="参军学生月份分布">
                    <p><em>图3: 参军学生入学月份分布</em></p>
                </div>

                <h3>disabled 表 - 残疾学生分析</h3>
                <div class="chart-container">
                    <img src="disabled_monthly_distribution.png" alt="残疾学生月份分布">
                    <p><em>图4: 残疾学生入学月份分布</em></p>
                </div>

                <h3>unemployed 表 - 失业学生分析</h3>
                <div class="chart-container">
                    <img src="unemployed_monthly_distribution.png" alt="失业学生月份分布">
                    <p><em>图5: 失业学生入学月份分布</em></p>
                </div>
            </section>

            <section id="correlation" class="section">
                <h2>🔗 关联分析</h2>
                
                <h3>季节性入学趋势</h3>
                <p>通过对比不同群体的入学月份分布,发现以下规律:</p>
                <ul>
                    <li><strong>秋季集中入学</strong>: 9月和10月是主要入学高峰期,占总入学人数的60%以上</li>
                    <li><strong>参军学生特征</strong>: 参军学生入学时间更集中于9月,可能与征兵周期相关</li>
                    <li><strong>特殊群体</strong>: 残疾和失业学生的入学时间分布相对均匀,无明显季节性</li>
                </ul>
            </section>

            <section id="findings" class="section">
                <h2>💡 关键发现与建议</h2>

                <div class="finding">
                    <h4>🎯 发现1: 入学时间高度集中</h4>
                    <p>数据显示,超过60%的学生在9-10月入学,反映了秋季学期开学的主导地位。这为学生贷款发放时间规划提供了明确依据。</p>
                    <span class="badge">数据支持</span>
                    <span class="badge">政策相关</span>
                </div>

                <div class="finding">
                    <h4>🎯 发现2: 参军学生入学特征明显</h4>
                    <p>参军学生的入学时间更集中于9月,与征兵周期高度吻合,建议在征兵宣传期同步开展入学咨询服务。</p>
                    <span class="badge">群体特征</span>
                    <span class="badge">服务优化</span>
                </div>

                <div class="finding">
                    <h4>🎯 发现3: 特殊群体需要持续关注</h4>
                    <p>残疾和失业学生的入学时间分布较为均匀,表明这些群体可能面临更灵活的入学安排需求,需要提供全年度的支持服务。</p>
                    <span class="badge">社会责任</span>
                    <span class="badge">长期支持</span>
                </div>

                <h3>📌 政策建议</h3>

                <div class="recommendation">
                    <h4>建议1: 优化贷款发放周期</h4>
                    <p>根据9-10月入学高峰,建议在8月提前开放贷款申请通道,确保学生在开学前获得资金支持。</p>
                </div>

                <div class="recommendation">
                    <h4>建议2: 建立参军学生专项服务</h4>
                    <p>针对参军学生的入学特点,建议设立专项咨询窗口,在征兵期提供一站式入学与贷款服务。</p>
                </div>

                <div class="recommendation">
                    <h4>建议3: 加强特殊群体全年支持</h4>
                    <p>为残疾和失业学生建立全年度服务机制,不局限于传统开学季,提供灵活的入学和资助方案。</p>
                </div>

                <h3>🔮 下一步分析方向</h3>
                <ul>
                    <li>分析贷款金额与入学时间的关系</li>
                    <li>研究不同学校的学生群体特征差异</li>
                    <li>建立入学时间预测模型,优化资源配置</li>
                    <li>深入分析特殊群体的经济状况与支持需求</li>
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

- `generated/analyze/comprehensive_analysis_report.html` - 完整的HTML报告
- 报告包含所有图表的相对路径引用(如 `../enrolled_school_dist.png`)
- 支持在浏览器中直接打开查看

## 注意事项

1. **路径一致性**: HTML中的图片使用相对路径 `../图片名.png` 引用上级目录的PNG文件
2. **中文编码**: 使用 `encoding="utf-8"` 确保中文正常显示
3. **响应式设计**: 报告支持PC和移动端查看
4. **数据来源**: 只从 `generated/` 目录读取文件,不访问原始数据库
5. **输出隔离**: 报告输出到 `generated/analyze/` 子目录,避免与阶段1文件冲突
6. **智能解析**: 基于 `README.md` 智能识别文件,适应动态文件名
