---
name: matplot-studio-converter
description: Convert existing Matplotlib scripts into self-contained Matplot Studio plot.py modules with editable property metadata. Use when adapting one or more Python figures for this repository's code/property/render workflow; do not use for ordinary Matplotlib debugging that does not target Matplot Studio.
---

# Matplot Studio Converter

把原始绘图代码改造成 Matplot Studio 可静态读取、回写属性并重复渲染的 `plot.py`，同时保持原分析语义。

开始转换前，完整阅读 [references/plot-contract.md](references/plot-contract.md)。它定义了应用实际支持的字段类型、删除属性的两种语义、数据自包含规则和动态表达式处理方式。

## 工作流程

1. 盘点原脚本产生的 Figure、数据来源、本地 helper、分析步骤和所有显式视觉参数。不要先重构或“修正”分析。
2. 每个 Figure 生成一个独立 `plot.py`；一个 Figure 内的多个 axes/subplots 保持在同一文件。直接接入已有项目时使用 `workspace/<project>/plots/<plot-id>/plot.py`，保证各 Figure 的 id 唯一且目录名等于 `PLOT_META.id`；多个文件不得互相导入。
3. 将该 Figure 所需的数据构造、清洗、统计和本地 helper 全部放进同一个 `plot.py`。不得依赖项目内其他 Python 文件、相邻数据文件、当前工作目录、环境变量、数据库或网络。`prepare_data()` 的返回值还必须可供应用导出：优先使用 DataFrame、`list[dict]` 或等长一维列字典以同时支持 CSV；复杂结构至少应可转为 JSON。
4. 若真实数据不能完整、合理地内嵌，保留原分析流程并换成确定性演示数据；在 `PLOT_META` 中设置 `data_mode="demo"` 和清楚的 `data_note`，不得把演示结果表述为真实结果。新产物同时声明 `data_export` 能力；复杂嵌套数据需明确 CSV 不可用。
5. 将能安全编辑的视觉属性登记到扁平的 `PLOT_SCHEMA`，把原脚本当前启用的值放入 `PLOT_SETTINGS`，并让 `render(data, settings)` 读取这些 path。尽量覆盖所有显式视觉参数，而不是只挑少数示例。
6. 保持源脚本的筛选、聚合、排序、统计方法、单位、分类顺序和不确定性计算不变。动态或数据依赖的表达式按契约处理，不能为了进入属性面板而冻结计算结果。
7. 去除 `show`、`savefig`、`close`、后端切换和全局样式修改；`render` 只构建并返回一个 `matplotlib.figure.Figure`，由应用管理显示和生命周期。
8. 除非用户明确要求覆盖，否则保留原文件。对每个产物先做静态校验，再做可信代码的 smoke 渲染：

```bash
python .codex/skills/matplot-studio-converter/scripts/validate_plot.py --strict-conversion path/to/plot.py
python .codex/skills/matplot-studio-converter/scripts/validate_plot.py --strict-conversion --smoke path/to/plot.py
```

若不能无语义变化地转换某项，保留原表达式并在交付说明中指出未暴露的属性及原因；不要猜测缺失的数据或业务逻辑。
