# 综合数据分析报告

生成时间：2026-02-11 00:20:54

## 1. 执行耗时统计

**总耗时**：608.0 秒（10.1 分钟），共 8 轮

| 轮次 | 开始时间 | 结束时间 | 耗时（秒） |
|------|----------|----------|-----------|
| Round 2 | 2026-02-10 23:54:47 | 2026-02-10 23:57:52 | 185.3 |
| Round 3 | 2026-02-10 23:57:52 | 2026-02-10 23:58:59 | 66.9 |
| Round 4 | 2026-02-10 23:58:59 | 2026-02-11 00:00:06 | 66.4 |
| Round 5 | 2026-02-11 00:00:06 | 2026-02-11 00:01:05 | 59.0 |
| Round 6 | 2026-02-11 00:01:05 | 2026-02-11 00:02:22 | 77.3 |
| Round 7 | 2026-02-11 00:04:13 | 2026-02-11 00:05:28 | 75.1 |
| Round 8 | 2026-02-11 00:05:28 | 2026-02-11 00:06:46 | 78.0 |

| Round 9 | - | - | 0.0 |
- **最慢轮次**：Round 2（185.3s）
- **最快轮次**：Round 5（59.0s）
- **平均每轮**：86.9s

## 2. 数据概况
- **数据来源**：`multi_table_join_result.csv`（23 行，5 列）
- **字段列表**：name, school, bool, month, organ
- **CSV 文件数**：6，**PNG 图表数**：6

| 字段 | 唯一值 | 缺失数 | 缺失率 |
|------|--------|--------|--------|
| name | 23 | 0 | 0.0% |
| school | 5 | 0 | 0.0% |
| bool | 1 | 0 | 0.0% |
| month | 9 | 0 | 0.0% |
| organ | 7 | 0 | 0.0% |

## 3. 交叉分析

### 3.1 学校 × 缴费状态
| school   |   pos |   All |
|:---------|------:|------:|
| occ      |     6 |     6 |
| smc      |     8 |     8 |
| ucb      |     1 |     1 |
| uci      |     5 |     5 |
| ucla     |     3 |     3 |
| All      |    23 |    23 |


### 3.2 参军机构 × 缺勤月数

| 机构 | 平均缺勤月数 | 中位数 | 人数 |
|------|-------------|--------|------|
| foreign_legion | 6.0 | 6.0 | 1 |
| marines | 5.0 | 5.0 | 2 |
| fire_department | 4.3 | 5.0 | 9 |
| peace_corps | 4.0 | 4.0 | 3 |
| navy | 3.8 | 3.0 | 4 |
| army | 3.5 | 3.5 | 2 |
| air_force | 2.5 | 2.5 | 2 |

**发现**：平均缺勤月数最高的机构为 **foreign_legion**（6.0 个月）。

## 4. 统计发现

- **name** 共 23 个类别，Top3：student208=1; student248=1; student281=1
- **school** 共 5 个类别，Top3：smc=8; occ=6; uci=5
- **bool** 共 1 个类别，Top3：pos=23
- **organ** 共 7 个类别，Top3：fire_department=9; navy=4; peace_corps=3
- **month** 均值=4.09，中位数=4.00，Q25=2.50，Q75=6.00

## 5. 可视化图表解读

### absense_month_dist
![absense_month_dist](absense_month_dist.png)

**解读**：该图展示了 absense_month_dist 的可视化分析结果。

### disabled_vs_total
![disabled_vs_total](disabled_vs_total.png)

**解读**：该图展示了 disabled_vs_total 的可视化分析结果。

### enlist_organ_dist
![enlist_organ_dist](enlist_organ_dist.png)

**解读**：该图展示了 enlist_organ_dist 的可视化分析结果。

### enrolled_school_dist
![enrolled_school_dist](enrolled_school_dist.png)

**解读**：该图展示了 enrolled_school_dist 的可视化分析结果。

### multi_table_join_result
![multi_table_join_result](multi_table_join_result.png)

**数据概要**：共 23 行 5 列（name, school, bool, month, organ）；month 均值=4.09，范围=[0.00, 8.00]

**解读**：数据源 `multi_table_join_result.csv`（23 行 5 列）。 数值列 `month`：均值=4.09，中位数=4.00，范围 [0.00, 8.00]。 分类列 `name` 共 23 个取值，Top3：student208(1人, 4%); student248(1人, 4%); student281(1人, 4%)。 分类列 `school` 共 5 个取值，Top3：smc(8人, 35%); occ(6人, 26%); uci(5人, 22%)。 分类列 `bool` 共 1 个取值，Top3：pos(23人, 100%)。 分类列 `organ` 共 7 个取值，Top3：fire_department(9人, 39%); navy(4人, 17%); peace_corps(3人, 13%)。

### payment_status_dist
![payment_status_dist](payment_status_dist.png)

**解读**：该图展示了 payment_status_dist 的可视化分析结果。

## 6. 结论与建议

### 6.1 核心发现
1. 所有字段均无缺失值，数据质量良好
2. 字段 **bool** 仅有 1 个取值（pos），无区分度，可考虑剔除
3. 数值字段 **month**：均值=4.09，中位数=4.00，Q25=2.50，Q75=6.00
4. 学校×缴费状态交叉表中所有学生缴费状态一致，当前样本无差异
5. 参军机构中 **foreign_legion** 平均缺勤 6.0 个月（1 人），缺勤风险最高

### 6.2 建议措施
- **缺勤预警**：对平均缺勤月数较高的机构人员建立预警机制，关注其学业连续性
- **持续监控**：建议定期更新数据并重新运行分析流程，跟踪关键指标变化趋势
- **深入分析**：对分布异常的字段结合业务背景做进一步调研
