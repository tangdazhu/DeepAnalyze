# 配置文件说明

## common_words.json

⚠️ **此配置文件为必需项** ⚠️

此配置文件用于定义表名提取时需要过滤的常见词汇,避免将非表名的标识符误识别为数据库表名。

**重要**: 
- 配置文件缺失或格式错误时,后端服务会**拒绝启动**并抛出异常
- 不提供任何后备默认值,确保配置的明确性和可维护性

### 文件位置
```
demo/config/common_words.json
```

### 文件格式
JSON格式,包含以下结构:
```json
{
  "description": "配置文件描述",
  "categories": {
    "分类名称": ["词汇1", "词汇2", ...]
  }
}
```

### 配置分类

| 分类名称 | 说明 | 示例 |
|---------|------|------|
| `sql_system` | SQL系统表 | `sqlite_master`, `sqlite_sequence` |
| `sql_aliases` | SQL别名(单字母) | `a`, `b`, `c`, ... |
| `sql_keywords` | SQL关键字 | `select`, `from`, `where`, `join` |
| `system_tags` | 系统标签 | `execute`, `analyze`, `code` |
| `common_fields` | 常见字段名 | `name`, `id`, `type`, `status` |
| `composite_fields` | 组合字段名 | `disability_status`, `payment_status` |
| `file_extensions` | 文件扩展名 | `csv`, `png`, `json` |
| `file_keywords` | 文件相关关键词 | `summary`, `report`, `output` |
| `analysis_keywords` | 分析相关关键词 | `analysis`, `correlation`, `trend` |
| `python_keywords` | Python关键字 | `import`, `def`, `class`, `return` |
| `programming_languages` | 编程语言名 | `python`, `sql`, `java` |
| `python_libraries` | Python库名 | `pandas`, `numpy`, `matplotlib` |
| `pandas_methods` | Pandas方法名 | `read_csv`, `groupby`, `merge` |
| `matplotlib_methods` | Matplotlib方法名 | `plot`, `scatter`, `savefig` |
| `sqlite3_methods` | SQLite3方法名 | `connect`, `execute`, `commit` |
| `common_words` | 常见英文词汇 | `the`, `a`, `is`, `are` |
| `path_components` | 路径组件 | `home`, `workspace`, `demo` |
| `output_filenames` | 输出文件名 | `enrolled_summary`, `correlation_analysis` |

### 使用方法

#### 1. 添加新词汇
在对应分类的数组中添加新词汇:
```json
{
  "categories": {
    "common_fields": [
      "name",
      "id",
      "新字段名"
    ]
  }
}
```

#### 2. 添加新分类
在 `categories` 对象中添加新的分类:
```json
{
  "categories": {
    "custom_category": [
      "词汇1",
      "词汇2"
    ]
  }
}
```

#### 3. 重新加载配置
修改配置文件后,需要重启后端服务:
```bash
# 停止当前服务 (Ctrl+C)
cd ~/DeepAnalyze/demo
python backend.py
```

### 注意事项

1. **词汇格式**: 所有词汇使用小写字母
2. **编码**: 文件使用 UTF-8 编码
3. **语法**: 确保JSON格式正确,注意逗号和引号
4. **后备机制**: 如果配置文件加载失败,系统会使用最小必要的后备集合
5. **日志**: 配置加载状态会记录在 `logs/backend.log` 中

### 验证配置

启动后端服务后,检查日志输出:
```
[配置] 已加载 XXX 个常见词汇
```

如果看到此日志,说明配置文件加载成功。

### 故障排查

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| 服务启动失败 | 配置文件不存在 | 创建 `config/common_words.json` 文件 |
| 服务启动失败 | JSON格式错误 | 检查语法,使用JSON验证工具 |
| 服务启动失败 | categories为空 | 检查配置文件结构,确保有词汇列表 |
| 配置未生效 | 未重启服务 | 重启 backend.py |

**注意**: 配置文件加载失败会导致后端服务**无法启动**,这是设计行为,确保配置问题能被及时发现。

### 示例场景

#### 场景1: 添加项目特定字段
如果你的项目有特定字段名(如 `customer_type`, `order_status`),添加到 `composite_fields`:
```json
"composite_fields": [
  "disability_status",
  "payment_status",
  "customer_type",
  "order_status"
]
```

#### 场景2: 添加自定义库
如果使用了特定的Python库(如 `scikit-learn`),添加到 `python_libraries`:
```json
"python_libraries": [
  "pandas",
  "numpy",
  "sklearn",
  "scikit-learn"
]
```

#### 场景3: 过滤特定文件名模式
如果生成的文件名有特定模式,添加到 `output_filenames`:
```json
"output_filenames": [
  "enrolled_summary",
  "my_custom_report",
  "daily_analysis"
]
```
