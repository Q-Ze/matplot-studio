# Matplot Studio `plot.py` contract

## 1. Module shape

每个文件必须可独立导入，并在顶层以 Python 字面量定义一次：

```python
PLOT_META = {
    "id": "stable-kebab-id",
    "name": "Human-readable name",
    "description": "What the figure shows",
    "version": 1,
    "data_mode": "demo",
    "data_note": "Deterministic synthetic data; not research results.",
    "data_export": {"csv": True, "json": True, "note": "Tabular demo data."},
}

PLOT_SCHEMA = [
    {
        "path": "figure.size",
        "label": "Figure size",
        "group": "Figure",
        "type": "number_pair",
        "default": [7.2, 4.6],
        "min": 2,
        "max": 16,
        "step": 0.1,
        "required": True,
    },
]

PLOT_SETTINGS = {"figure.size": [7.2, 4.6]}


def prepare_data():
    ...


def render(data, settings):
    ...
    return fig
```

顶层只保留导入、字面量常量和函数定义，避免导入模块时执行数据读取或绘图。`prepare_data()` 无参数并返回渲染所需数据；`render(data, settings)` 同步执行并返回恰好一个 `matplotlib.figure.Figure`。多个 axes、inset 或 twin axes 仍属于同一 Figure。

`PLOT_META` 的 `id`、`name`、`description`、`version` 是稳定身份信息。新转换文件还必须写 `data_mode`：真实数据/数值已内嵌时用 `inline`，替代演示数据时用 `demo`。`demo` 必须有直白的 `data_note`。同时写 `data_export={"csv": bool, "json": True, "note": str}`；它描述 `prepare_data()` 的导出能力，不应被渲染逻辑依赖。

直接加入应用工作区时，文件位置为 `workspace/<project>/plots/<plot-id>/plot.py`，目录 `<plot-id>` 必须等于 `PLOT_META.id`。一次拆分得到的每个 Figure 使用不同的 kebab-case id，并把相应条目加入既有 `project.json`；若用户只要求生成转换文件而未授权接入项目，不要擅自创建项目或改 manifest。

## 2. Property schema

`PLOT_SCHEMA` 是非空属性目录；每项必须包含唯一的 `path`、非空 `label`、`group`、受支持的 `type` 和字面量 `default`。支持的类型为：

- `number`, `integer`, `string`, `text`, `boolean`, `color`
- `select`：同时提供非空 `options`；选项可为值，或包含 `value` 的字典
- `number_pair`, `string_list`, `color_list`

数值类型可带 `min`、`max`、正数 `step`。`required: true` 表示属性不可删除，且 path 必须存在于 `PLOT_SETTINGS`；省略或设为 false 表示可删除。

`PLOT_SETTINGS` 是当前启用覆盖值的扁平字典，其键必须是 schema path 的子集。它不是嵌套配置。应用只重写这个顶层字面量，因此不要把当前值复制到别处作为另一个事实来源。

path 使用稳定、语义化的小写点路径，例如：

- `figure.size`, `figure.facecolor`, `layout.wspace`
- `axes.main.title`, `axes.main.x_range`, `axes.main.grid`
- `series.observed.color`, `series.fit.linewidth`
- `legend.location`, `typography.tick_size`

不要使用运行顺序索引（如 `line.0.color`）指代具有业务名称的对象。循环生成且身份不稳定的对象应共用一个语义设置，或继续留在代码中。

### 删除属性的语义

转换时为每个可选 path 明确选择一种方式：

1. **稳定基线回退**：适用于大多数属性。先用 schema default 建立配置，再覆盖启用值；删除属性后回到声明的基线。

   ```python
   def _resolved(settings):
       values = {field["path"]: field["default"] for field in PLOT_SCHEMA}
       values.update(settings or {})
       return values
   ```

2. **Matplotlib 原生默认**：当“不调用 setter”与显式传入 default 的含义不同，直接检查原始 `settings` 中是否存在 path。删除后必须跳过该 setter；schema 的 `default` 仅作为重新添加时的建议值。

   ```python
   if "axes.main.grid" in settings:
       ax.grid(bool(settings["axes.main.grid"]))
   ```

不要把第二类 path 先经 `_resolved` 补齐再判断存在性。`required` 属性使用第一类语义。

## 3. What to expose

暴露所有能保持含义且能由支持类型表达的显式视觉参数，包括画布尺寸/颜色、布局间距、标题和标签、字体、轴范围/尺度、刻度参数、网格、spines、线/点/柱/填充样式、图例和注释。分析参数（筛选阈值、窗口、bootstrap 次数、模型参数等）不属于视觉属性；除非产品契约另行扩展，不要移动到 `PLOT_SETTINGS`。

处理动态值时遵守：

- 原值是字面量：提取到一个稳定 path，并用 `settings` 读取替换原位置。
- 原值由若干可编辑视觉输入推导：只暴露有意义的输入，公式继续在 `render` 中计算。例如标题字号 `+ 2` 保留为公式。
- 原值依赖数据、循环状态、统计结果或调用时上下文：保留表达式，不把某次运行结果冻结成设置。
- formatter、locator 或其他对象：暴露其可编辑标量参数，而不是尝试序列化对象。
- 条件分支只有在一个设置能控制所有分支且不改变行为时才合并；否则保留分支。
- 支持类型无法无损表达时，保留代码并省略该 schema 项；禁止 `eval` 或用字符串生成 Python 代码。

## 4. Data and semantic fidelity

同一个 `plot.py` 必须包含 Figure 使用的全部本地 helper、数据定义和数据准备逻辑。不得保留 `from .helper ...`、`import _local_module` 或对相邻项目模块的导入，也不得读取本地 CSV/Excel/Parquet/JSON、依赖 cwd、数据库、网络、密钥或环境变量。允许使用应用环境已安装的常规第三方包。

真实输入若已是规模合理的字面数据，应将其放入 `prepare_data()`（或同文件的字面量常量）并设 `data_mode="inline"`。若输入缺失、过大、受限或依赖不可用系统，则：

- 使用固定字面量，或使用固定 seed 的局部生成器（如 `np.random.default_rng(42)`）；不得使用当前时间或未设 seed 的随机数。
- 保持列名、形状、类别、单位和边界情况足以走通原分析与绘图路径。
- 保留原筛选、派生变量、聚合、统计估计、误差区间和排序逻辑；只替换输入数据。
- 标注 `data_mode="demo"` 和 `data_note`，清楚说明数据是确定性合成数据且不代表研究结果。

`prepare_data()` 的返回值同时是“导出数据”的来源：

- 优先返回 pandas DataFrame、`list[dict[str, scalar]]`，或 `dict[str, 等长一维序列]`。这三种形状可同时导出 CSV 和 JSON，声明 `data_export.csv=True`。
- NumPy 标量/数组、pandas 对象、日期时间、字典和列表可由应用规范化为 JSON；其中所有值最终都必须能转换成有限数值、字符串、boolean、null、列表或字符串键字典。
- 多面板、分组数组等复杂嵌套数据至少必须支持 JSON。若不能无损压平为上述表格形状，声明 `data_export.csv=False`，并在 `data_export.note` 与交付说明中指出 CSV 不可用及原因；不要为了 CSV 改变 render 所需的数据语义。
- 图片 SVG/PNG/PDF 由应用从返回的 Figure 导出；`plot.py` 仍不得调用 `savefig`。

转换不能借机改变分析语义或美化结果。若原脚本生成多个 Figure，按 Figure 拆分，每个新文件复制其所需的最小数据/分析逻辑，不能通过导入另一个 plot 共享实现。

## 5. Rendering discipline

- 不调用 `show`、`savefig`、`close`、`pause`、`ion/ioff` 或切换 Matplotlib backend。
- 不修改全局 `rcParams`，不使用进程级 `style.use`；用 Figure/Axes setter 或局部 context。
- 不在导入时绘图、读取数据或创建运行时对象。
- `render` 每次调用都新建一个 Figure，不缓存 Figure，不写文件，不改变 `data` 或 `settings`。
- Web 应用负责选择无界面 backend、渲染、关闭旧 Figure、错误展示与缩放查看。

交付前运行静态验证；对可信代码再运行 `--smoke`，确认数据准备、Figure 返回值和实际 draw 都成功。
