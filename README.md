# Matplot Studio

Matplot Studio 是一个面向 Python 用户与科研人员的本地 Web 应用：代码是事实来源，右侧属性面板负责快速调整常用 Matplotlib 参数，画布随修改重新渲染。

## 已实现

- 项目 / plot 左侧导航；支持导入或删除项目、向指定项目导入单个 `plot.py` 或递归扫描文件夹、删除单个 plot；一个 plot 对应一个 `Figure` 与一个 `plot.py`
- Python 代码编辑、自动保存、`Ctrl/⌘ + Enter` 手动运行
- 从规范代码自动读取属性，并将修改写回 `PLOT_SETTINGS`
- 属性添加、删除、类型校验和 revision 冲突保护
- SVG 实时预览以及缩放、平移、适应窗口
- PNG、SVG、PDF 图片导出，600 DPI PNG 一键复制到剪贴板，以及 CSV、JSON 数据导出
- 独立 Python 子进程渲染、超时终止和 traceback 展示
- 可新建空项目，也可导入符合契约的项目或独立 `plot.py`

## 启动

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m matplot_studio
```

随后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。也可以通过环境变量指定位置：

```bash
MATPLOT_STUDIO_PORT=8080 MATPLOT_STUDIO_WORKSPACE=/path/to/workspace python -m matplot_studio
```

当前版本定位为本机单用户工具，会执行工作区内受信任的 Python 代码，不应直接暴露到公网。

`workspace/` 是仅供本机使用的运行目录，并已从 Git 中排除。项目代码、内嵌数据、渲染图片和原始绘图脚本不会随本仓库发布；需要共享图表时，请先单独审查其代码和数据。

## Plot 目录与代码契约

```text
workspace/
└── project-id/
    ├── project.json
    └── plots/
        └── plot-id/
            └── plot.py
```

每个 `plot.py` 必须自包含，并定义：

- `PLOT_META`：名称、版本和数据来源说明
- `PLOT_SCHEMA`：属性面板可添加或编辑的属性目录
- `PLOT_SETTINGS`：当前启用的属性值，也是属性面板唯一会自动改写的代码块
- `prepare_data()`：同文件内的数据准备或确定性演示数据
- `render(data, settings)`：返回且只返回一个 Matplotlib `Figure`

应用负责渲染和导出，因此 `plot.py` 不应调用 `show()`、`savefig()` 或 `close()`。完整格式见 `.codex/skills/matplot-studio-converter/references/plot-contract.md`。

项目导入时可选择包含上述结构的 ZIP，或直接选择项目根文件夹。ZIP 可以包含项目所需的二进制资源；文件夹导入用于 UTF-8 文本项目。导入前会校验 `project.json`、目录结构和每个 `plot.py` 的代码契约，重名项目会自动获得新的项目编号。

也可以在左侧某个现有项目上选择“导入图表”：直接选择一个规范 `plot.py`，或选择任意文件夹并递归查找其中所有名为 `plot.py` 的文件。整批文件会先完成契约与 ID 冲突校验，再一次性加入项目。

## 转换原始绘图代码

项目内提供了两个 skills：

- `$matplot-studio-converter`：将已有 Matplotlib 绘图脚本转换为规范 `plot.py`。
- `$matplot-studio-generator`：从用户授权的原始数据出发，完成数据处理、图表设计，并直接生成规范 `plot.py` 或完整项目。

两者都会把渲染所需数据和处理逻辑放进同一个 `plot.py`，执行静态校验和 smoke 渲染；缺少真实依赖或数据时，应生成确定性的演示数据并明确标注，而不是留下无法运行的本地 import。

## 验证

```bash
python -m unittest discover -s tests -v
python .codex/skills/matplot-studio-converter/scripts/validate_plot.py \
  --strict-conversion --smoke path/to/plot.py
```
