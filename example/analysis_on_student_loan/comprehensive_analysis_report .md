# 综合数据分析报告

生成时间：2026-02-10 14:19:59

## 1. 数据概况
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

## 2. 交叉分析

### 2.1 学校 × 缴费状态
| school   |   pos |   All |
|:---------|------:|------:|
| occ      |     6 |     6 |
| smc      |     8 |     8 |
| ucb      |     1 |     1 |
| uci      |     5 |     5 |
| ucla     |     3 |     3 |
| All      |    23 |    23 |


### 2.2 参军机构 × 缺勤月数

| 机构 | 平均缺勤月数 | 中位数 | 人数 |
|------|-------------|--------|------|
| foreign_legion | 6.0 | 6.0 | 1 |
| marines | 5.0 | 5.0 | 2 |
| fire_department | 4.3 | 5.0 | 9 |
| peace_corps | 4.0 | 4.0 | 3 |
| navy | 3.8 | 3.0 | 4 |
| army | 3.5 | 3.5 | 2 |
| air_force | 2.5 | 2.5 | 2 |

## 3. 统计发现

- **name** 共 23 个类别，Top3：student208=1; student248=1; student281=1
- **school** 共 5 个类别，Top3：smc=8; occ=6; uci=5
- **bool** 共 1 个类别，Top3：pos=23
- **organ** 共 7 个类别，Top3：fire_department=9; navy=4; peace_corps=3
- **month** 均值=4.09，中位数=4.00，Q25=2.50，Q75=6.00

## 4. 可视化图表解读

### absense_month_dist
![absense_month_dist](absense_month_dist.png)

### disabled_vs_total
![disabled_vs_total](disabled_vs_total.png)

### enlist_organ_dist
![enlist_organ_dist](enlist_organ_dist.png)

### enrolled_school_month_dist
![enrolled_school_month_dist](enrolled_school_month_dist.png)

### multi_table_join_result
![multi_table_join_result](multi_table_join_result.png)

### payment_status_dist
![payment_status_dist](payment_status_dist.png)

## 5. 结论与建议

1. 基于交叉分析结果，给出针对性建议
2. 基于统计发现，指出需要关注的风险点
3. 基于可视化图表，总结数据的整体特征
