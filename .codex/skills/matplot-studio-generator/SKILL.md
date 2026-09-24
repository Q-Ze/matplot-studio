---
name: matplot-studio-generator
description: Generate new Matplot Studio figures and projects from authorized raw data by profiling, transforming, visualizing, and validating the result. Use when the task starts from data rather than an existing Matplotlib figure script; use matplot-studio-converter for script-to-contract conversion.
---

# Matplot Studio Generator

把一批原始数据转化为新的、可编辑且可重复渲染的 Matplot Studio 图表。这个 skill 负责数据理解、确定性处理、图表设计和规范文件生成；不是只给出绘图建议。

## 交付模式

先根据用户请求选择一种模式，并在交付说明中明确实际写入的位置：

- **仅生成图表文件**：输出一个或多个独立的 `plot.py`，不创建项目或修改 manifest。
- **加入现有项目**：写入 `workspace/<project>/plots/<plot-id>/plot.py`，并同步更新该项目的 `project.json`。
- **创建完整项目**：创建 `workspace/<project-id>/project.json`、`plots/<plot-id>/plot.py` 及所有图表条目。

如果用户没有授权修改项目，不要擅自创建项目、覆盖图表或上传数据。相同图表 id 不覆盖；应报告冲突并选择安全的新 id 或等待用户决定。

## 工作流程

1. **明确目标**：确定数据范围、分析问题、期望的图表数量、输出模式和格式；图表类型未指定时，根据数据结构和问题选择合理方案，并说明选择依据。
2. **检查输入**：只读取用户授权的数据路径。盘点文件格式、列名、单位、时间范围、类别、缺失值、重复行和异常值。不得访问网络、数据库、环境变量、密钥或未授权目录。
3. **设计处理**：保持原始单位和语义；明确排序、聚合、筛选、插值、归一化和异常值处理规则。所有随机步骤必须使用固定 seed。将重要假设、限制和数据覆盖范围写进 `PLOT_META.data_note` 和交付说明。
4. **选择视觉编码**：让图形回答用户的问题，避免双 y 轴、截断轴和无法比较的颜色编码造成误导。按 [references/data-to-figure.md](references/data-to-figure.md) 选择时间序列、分类比较、关系、分布或组成图，并为轴、单位、图例和注释提供清晰默认值。
5. **生成自包含 `plot.py`**：每个 Figure 一个文件；把渲染所需的数据、清洗、统计和本地 helper 放入同一文件。定义 `PLOT_META`、非空 `PLOT_SCHEMA`、`PLOT_SETTINGS`、无参 `prepare_data()` 和返回单个 Figure 的 `render(data, settings)`。完整字段要求见 [../matplot-studio-converter/references/plot-contract.md](../matplot-studio-converter/references/plot-contract.md)。
6. **处理数据规模与隐私**：优先嵌入渲染所需的最小确定性派生数据，而不是无用原始副本。数据规模过大、含敏感信息或无法合理内嵌时，未经用户明确同意不得复制到项目；改用结构相同、固定 seed 的演示数据，并标记 `data_mode="demo"`，不得把演示结果表述为真实结果。
7. **暴露可编辑属性**：把图像尺寸、布局、字体、颜色、轴范围、刻度、网格、线点柱填充、图例和注释等视觉参数放入扁平 `PLOT_SCHEMA` / `PLOT_SETTINGS`。筛选阈值、统计模型、窗口、聚合方法等分析参数留在代码中，除非用户明确要求编辑它们。
8. **写入项目**：只有在用户选择“加入现有项目”或“创建完整项目”时才修改目录。新建或更新 `project.json` 时，确保每个 manifest 图表都有对应目录和 `plot.py`，且目录名、manifest id 与 `PLOT_META.id` 一致。多个 Figure 不互相导入。
9. **验证交付**：对每个产物运行静态校验和可信代码的 smoke 渲染：

   ```bash
   python .codex/skills/matplot-studio-converter/scripts/validate_plot.py --strict-conversion path/to/plot.py
   python .codex/skills/matplot-studio-converter/scripts/validate_plot.py --strict-conversion --smoke path/to/plot.py
   ```

   同时检查 `prepare_data()` 可被数据导出规范化、Figure 尺寸和单位正确、无 `show()` / `savefig()` / `close()` / 外部数据读取，并确认没有产生未授权的副本。

## 交付说明

简要报告：输入文件和处理摘要、图表选择及关键假设、输出路径、数据是 `inline` 还是 `demo`、可编辑属性范围、数据导出能力、验证结果，以及任何未表达或未暴露的内容。不要把敏感原始数据复制到交付说明或日志中。
