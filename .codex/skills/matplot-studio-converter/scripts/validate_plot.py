#!/usr/bin/env python3
"""Validate a Matplot Studio plot.py without executing it; optionally smoke-render it."""

from __future__ import annotations

import argparse
import ast
import copy
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import traceback
from typing import Any, Iterable, Mapping, Sequence


PROPERTY_TYPES = {
    "number",
    "integer",
    "string",
    "text",
    "boolean",
    "color",
    "select",
    "number_pair",
    "string_list",
    "color_list",
}
PATH_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MATPLOTLIB_SIDE_EFFECT_LEAVES = {"show", "savefig"}
MATPLOTLIB_SIDE_EFFECT_CALLS = {
    "matplotlib.pyplot.close",
    "matplotlib.pyplot.pause",
    "matplotlib.pyplot.ion",
    "matplotlib.pyplot.ioff",
    "matplotlib.pyplot.switch_backend",
    "matplotlib.style.use",
    "matplotlib.pyplot.style.use",
    "matplotlib.rc",
}
EXTERNAL_DATA_CALLS = {
    "open",
    "builtins.open",
    "numpy.load",
    "numpy.loadtxt",
    "numpy.genfromtxt",
    "pandas.read_csv",
    "pandas.read_excel",
    "pandas.read_feather",
    "pandas.read_hdf",
    "pandas.read_html",
    "pandas.read_json",
    "pandas.read_orc",
    "pandas.read_parquet",
    "pandas.read_pickle",
    "pandas.read_sas",
    "pandas.read_spss",
    "pandas.read_sql",
    "pandas.read_stata",
    "pandas.read_table",
    "requests.get",
    "requests.post",
    "requests.request",
    "sqlite3.connect",
    "sqlalchemy.create_engine",
    "urllib.request.urlopen",
    "urllib.request.urlretrieve",
    "os.getenv",
    "os.environ.get",
    "os.getcwd",
    "os.listdir",
    "os.scandir",
    "glob.glob",
    "glob.iglob",
    "pathlib.Path.cwd",
}
EXTERNAL_METHOD_LEAVES = {"read_text", "read_bytes"}
MAX_SVG_BYTES = 20 * 1024 * 1024


class ValidationError(Exception):
    """A contract violation with an optional source line."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line

    def render(self, path: Path) -> str:
        location = f"{path}:{self.line}" if self.line else str(path)
        return f"{location}: {self.message}"


def _assignment_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def _literal(tree: ast.Module, name: str) -> tuple[Any, ast.AST]:
    matches = [node for node in tree.body if _assignment_name(node) == name]
    if len(matches) != 1:
        detail = "缺少" if not matches else "重复定义"
        line = getattr(matches[-1], "lineno", None) if matches else None
        raise ValidationError(f"{detail}顶层字面量 {name}", line)
    node = matches[0]
    value_node = _assignment_value(node)
    try:
        value = ast.literal_eval(value_node) if value_node is not None else None
    except (ValueError, TypeError, SyntaxError):
        raise ValidationError(f"{name} 必须是可静态读取的 Python 字面量", getattr(node, "lineno", None))
    return value, node


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_api_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)) or _is_number(value):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_api_value(item) for item in value)
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return all(_is_api_value(item) for item in value.values())
    return False


def _is_select_scalar(value: Any) -> bool:
    return (
        isinstance(value, (str, bool))
        or isinstance(value, int) and not isinstance(value, bool)
        or isinstance(value, float) and math.isfinite(value)
    )


def _option_values(options: Any) -> list[Any]:
    if not isinstance(options, list) or not options:
        return []
    values: list[Any] = []
    for option in options:
        if isinstance(option, dict):
            if "value" not in option:
                return []
            option = option["value"]
        if not _is_select_scalar(option):
            return []
        values.append(option)
    return values


def _value_matches(kind: str, value: Any, field: Mapping[str, Any]) -> bool:
    if kind == "number":
        valid = _is_number(value)
    elif kind == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind in {"string", "text", "color"}:
        valid = isinstance(value, str)
    elif kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "select":
        valid = _is_select_scalar(value) and value in _option_values(field.get("options"))
    elif kind == "number_pair":
        valid = isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_number(item) for item in value)
    elif kind in {"string_list", "color_list"}:
        valid = isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)
    else:
        return False
    if not valid:
        return False

    numeric_values: Iterable[float]
    if kind in {"number", "integer"}:
        numeric_values = [float(value)]
    elif kind == "number_pair":
        numeric_values = [float(item) for item in value]
    else:
        numeric_values = []
    minimum, maximum = field.get("min"), field.get("max")
    if minimum is not None and (not _is_number(minimum) or any(item < minimum for item in numeric_values)):
        return False
    if maximum is not None and (not _is_number(maximum) or any(item > maximum for item in numeric_values)):
        return False
    return True


def _validate_meta(meta: Any, node: ast.AST, *, strict_conversion: bool) -> None:
    if not isinstance(meta, dict):
        raise ValidationError("PLOT_META 必须是字典", getattr(node, "lineno", None))
    for key in ("id", "name", "description"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise ValidationError(f"PLOT_META.{key} 必须是非空字符串", getattr(node, "lineno", None))
    if not ID_RE.fullmatch(meta["id"]):
        raise ValidationError("PLOT_META.id 必须是稳定的 kebab-case 标识", getattr(node, "lineno", None))
    if not isinstance(meta.get("version"), int) or isinstance(meta["version"], bool) or meta["version"] < 1:
        raise ValidationError("PLOT_META.version 必须是正整数", getattr(node, "lineno", None))
    data_mode = meta.get("data_mode")
    if strict_conversion and data_mode is None:
        raise ValidationError("新转换产物必须声明 PLOT_META.data_mode", getattr(node, "lineno", None))
    if data_mode is not None and data_mode not in {"inline", "demo"}:
        raise ValidationError("PLOT_META.data_mode 只能是 inline 或 demo", getattr(node, "lineno", None))
    if data_mode == "demo" and (not isinstance(meta.get("data_note"), str) or not meta["data_note"].strip()):
        raise ValidationError("演示数据必须在 PLOT_META.data_note 中明确说明", getattr(node, "lineno", None))
    export = meta.get("data_export")
    if strict_conversion and export is None:
        raise ValidationError("新转换产物必须声明 PLOT_META.data_export", getattr(node, "lineno", None))
    if export is not None:
        if not isinstance(export, dict):
            raise ValidationError("PLOT_META.data_export 必须是字典", getattr(node, "lineno", None))
        if not isinstance(export.get("csv"), bool) or export.get("json") is not True:
            raise ValidationError(
                "PLOT_META.data_export 必须包含 csv: bool 与 json: true",
                getattr(node, "lineno", None),
            )
        if not isinstance(export.get("note"), str) or not export["note"].strip():
            raise ValidationError("PLOT_META.data_export.note 必须是非空字符串", getattr(node, "lineno", None))


def _validate_schema(schema: Any, settings: Any, node: ast.AST) -> None:
    if not isinstance(schema, list):
        raise ValidationError("PLOT_SCHEMA 必须是 list[dict]", getattr(node, "lineno", None))
    if not schema:
        raise ValidationError("PLOT_SCHEMA 至少需要一个可编辑视觉属性", getattr(node, "lineno", None))
    if not isinstance(settings, dict) or not all(isinstance(key, str) for key in settings):
        raise ValidationError("PLOT_SETTINGS 必须是字符串 path 到值的扁平字典")

    paths: set[str] = set()
    for index, field in enumerate(schema):
        if not isinstance(field, dict):
            raise ValidationError(f"PLOT_SCHEMA[{index}] 必须是字典", getattr(node, "lineno", None))
        path = field.get("path")
        kind = field.get("type")
        if not isinstance(path, str) or not PATH_RE.fullmatch(path):
            raise ValidationError(f"PLOT_SCHEMA[{index}].path 必须是小写稳定点路径", getattr(node, "lineno", None))
        if path in paths:
            raise ValidationError(f"PLOT_SCHEMA 中 path {path!r} 重复", getattr(node, "lineno", None))
        paths.add(path)
        for text_key in ("label", "group"):
            if not isinstance(field.get(text_key), str) or not field[text_key].strip():
                raise ValidationError(f"属性 {path!r} 缺少非空 {text_key}", getattr(node, "lineno", None))
        if kind not in PROPERTY_TYPES:
            raise ValidationError(f"属性 {path!r} 使用不支持的类型 {kind!r}", getattr(node, "lineno", None))
        if "required" in field and not isinstance(field["required"], bool):
            raise ValidationError(f"属性 {path!r} 的 required 必须是 boolean", getattr(node, "lineno", None))
        if "default" not in field:
            raise ValidationError(f"属性 {path!r} 缺少 default", getattr(node, "lineno", None))
        if kind == "select" and not _option_values(field.get("options")):
            raise ValidationError(f"select 属性 {path!r} 必须提供非空 options", getattr(node, "lineno", None))
        step = field.get("step")
        if step is not None and (not _is_number(step) or step <= 0):
            raise ValidationError(f"属性 {path!r} 的 step 必须是正数", getattr(node, "lineno", None))
        minimum, maximum = field.get("min"), field.get("max")
        if minimum is not None and maximum is not None and (
            not _is_number(minimum) or not _is_number(maximum) or minimum > maximum
        ):
            raise ValidationError(f"属性 {path!r} 的 min/max 无效", getattr(node, "lineno", None))
        if not _value_matches(kind, field["default"], field):
            raise ValidationError(f"属性 {path!r} 的 default 不符合 {kind} 或数值范围", getattr(node, "lineno", None))
        if path in settings and not _value_matches(kind, settings[path], field):
            raise ValidationError(f"PLOT_SETTINGS[{path!r}] 不符合 {kind} 或数值范围", getattr(node, "lineno", None))
        if field.get("required") is True and path not in settings:
            raise ValidationError(f"required 属性 {path!r} 必须存在于 PLOT_SETTINGS", getattr(node, "lineno", None))

    unknown = sorted(set(settings) - paths)
    if unknown:
        raise ValidationError("PLOT_SETTINGS 含未声明 path：" + ", ".join(repr(path) for path in unknown))


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(matches) != 1:
        raise ValidationError(f"必须在顶层定义且只定义一次 {name}()")
    node = matches[0]
    if isinstance(node, ast.AsyncFunctionDef):
        raise ValidationError(f"{name}() 必须是同步函数", node.lineno)
    if node.decorator_list:
        raise ValidationError(f"{name}() 不得使用会在导入时执行的 decorator", node.lineno)
    return node


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                local_name = item.asname or item.name.split(".")[0]
                aliases[local_name] = item.name if item.asname else item.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _call_name(node: ast.AST, aliases: Mapping[str, str] | None = None) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append((aliases or {}).get(node.id, node.id))
    return ".".join(reversed(parts))


def _validate_functions(tree: ast.Module) -> None:
    prepare = _top_level_function(tree, "prepare_data")
    render = _top_level_function(tree, "render")
    p_args = prepare.args
    if p_args.posonlyargs or p_args.args or p_args.vararg or p_args.kwonlyargs or p_args.kwarg:
        raise ValidationError("prepare_data() 不得声明参数", prepare.lineno)
    r_args = render.args
    positional = list(r_args.posonlyargs) + list(r_args.args)
    if (
        [item.arg for item in positional] != ["data", "settings"]
        or r_args.defaults
        or r_args.vararg
        or r_args.kwonlyargs
        or r_args.kwarg
    ):
        raise ValidationError("render 必须使用精确签名 render(data, settings)", render.lineno)
    if not any(isinstance(node, ast.Return) and node.value is not None for node in ast.walk(render)):
        raise ValidationError("render 必须返回一个 Figure", render.lineno)


def _validate_top_level(tree: ast.Module) -> None:
    for index, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            continue
        if isinstance(node, ast.Expr) and index == 0 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = _assignment_value(node)
            try:
                ast.literal_eval(value) if value is not None else None
            except (ValueError, TypeError, SyntaxError):
                raise ValidationError("顶层赋值必须是字面量；运行时构造应放入函数", node.lineno)
            continue
        raise ValidationError("顶层只能包含导入、字面量常量和函数定义", getattr(node, "lineno", None))


def _validate_imports(tree: ast.Module, path: Path) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValidationError("不得使用相对导入；本地 helper 必须内联", node.lineno)
            modules = [node.module.split(".")[0]] if node.module else []
        elif isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        else:
            continue
        for module in modules:
            search_roots = list(path.resolve().parents)
            is_local = any(
                (root / f"{module}.py").exists() or (root / module).is_dir()
                for root in search_roots
            )
            if is_local:
                raise ValidationError(f"不得导入本地模块 {module!r}；请将所需逻辑内联", node.lineno)


def _validate_calls(tree: ast.Module) -> None:
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _call_name(node.value, aliases) == "os.environ":
            raise ValidationError("不得依赖环境变量；数据必须随 plot.py 自包含", node.lineno)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and _call_name(target.value, aliases) == "matplotlib.rcParams":
                    raise ValidationError("禁止修改全局 rcParams", node.lineno)
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func, aliases)
        leaf = name.split(".")[-1]
        if leaf in MATPLOTLIB_SIDE_EFFECT_LEAVES or name in MATPLOTLIB_SIDE_EFFECT_CALLS:
            raise ValidationError(f"禁止调用 {name or leaf}；Figure 生命周期由应用管理", node.lineno)
        if name == "matplotlib.use":
            raise ValidationError(f"禁止进程级 Matplotlib 配置 {name}", node.lineno)
        if name == "matplotlib.rcParams.update":
            raise ValidationError("禁止修改全局 rcParams", node.lineno)
        if name in EXTERNAL_DATA_CALLS or leaf in EXTERNAL_METHOD_LEAVES:
            raise ValidationError(f"检测到外部数据读取 {name or leaf}；数据必须随 plot.py 自包含", node.lineno)


def validate_source(source: str, path: Path, *, strict_conversion: bool = False) -> Mapping[str, Any]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ValidationError(f"语法错误：{exc.msg}", exc.lineno)
    _validate_top_level(tree)
    meta, meta_node = _literal(tree, "PLOT_META")
    schema, schema_node = _literal(tree, "PLOT_SCHEMA")
    settings, settings_node = _literal(tree, "PLOT_SETTINGS")
    for name, value, node in (
        ("PLOT_META", meta, meta_node),
        ("PLOT_SCHEMA", schema, schema_node),
        ("PLOT_SETTINGS", settings, settings_node),
    ):
        if not _is_api_value(value):
            raise ValidationError(f"{name} 含有不能通过 Web API 返回的值", getattr(node, "lineno", None))
    _validate_meta(meta, meta_node, strict_conversion=strict_conversion)
    _validate_schema(schema, settings, schema_node)
    _validate_functions(tree)
    _validate_imports(tree, path)
    _validate_calls(tree)
    return meta


def validate_file(path: Path, *, strict_conversion: bool = False) -> Mapping[str, Any]:
    if path.name != "plot.py":
        raise ValidationError("转换产物文件名必须是 plot.py")
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"无法读取文件：{exc}")
    meta = validate_source(source, path, strict_conversion=strict_conversion)
    if path.parent.parent.name == "plots" and path.parent.name != meta["id"]:
        raise ValidationError("plots/<plot-id>/plot.py 的目录名必须等于 PLOT_META.id")
    return meta


def _load_export_helpers() -> tuple[Any, Any]:
    """Load the application's exact scientific-value exporters without importing its package."""

    worker_path = next(
        (parent / "matplot_studio" / "render_worker.py" for parent in Path(__file__).resolve().parents
         if (parent / "matplot_studio" / "render_worker.py").is_file()),
        None,
    )
    if worker_path is None:
        raise ValidationError("找不到 matplot_studio/render_worker.py，无法验证数据导出")
    spec = importlib.util.spec_from_file_location("_matplot_studio_export_contract", worker_path)
    if spec is None or spec.loader is None:
        raise ValidationError("无法载入应用的数据导出契约")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._json_value, module._csv_value


def _smoke_worker(path: Path) -> None:
    """Run only inside the disposable smoke subprocess."""

    os.environ["MPLBACKEND"] = "Agg"
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    json_value, csv_value = _load_export_helpers()
    module_name = f"_matplot_studio_smoke_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValidationError("无法创建模块加载器")
    module = importlib.util.module_from_spec(spec)
    plt.close("all")
    try:
        spec.loader.exec_module(module)
        if plt.get_fignums() or any(isinstance(value, Figure) for value in vars(module).values()):
            raise ValidationError("plot.py 在导入阶段创建了 Figure")

        data = module.prepare_data()

        def snapshot(value: Any) -> str:
            return json.dumps(
                json_value(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )

        data_before = snapshot(data)
        if module.PLOT_META.get("data_mode") == "demo" and snapshot(module.prepare_data()) != data_before:
            raise ValidationError("demo 的 prepare_data() 必须产生确定性数据")
        export = module.PLOT_META.get("data_export")
        if isinstance(export, dict) and export.get("csv") is True:
            csv_value(data)

        original_module_settings = copy.deepcopy(module.PLOT_SETTINGS)

        def render_once(active_settings: Mapping[str, Any]) -> Figure:
            supplied = copy.deepcopy(dict(active_settings))
            supplied_before = copy.deepcopy(supplied)
            figure = module.render(data, supplied)
            if not isinstance(figure, Figure):
                raise ValidationError(f"render 返回了 {type(figure).__name__}，不是 matplotlib.figure.Figure")
            if supplied != supplied_before:
                raise ValidationError("render 修改了传入的 settings")
            if snapshot(data) != data_before:
                raise ValidationError("render 修改了 prepare_data() 返回的数据")
            if len(plt.get_fignums()) > 1:
                raise ValidationError("单次 render 创建了多个 pyplot Figure")
            output = io.BytesIO()
            figure.savefig(output, format="svg")
            if output.tell() > MAX_SVG_BYTES:
                raise ValidationError("SVG 渲染结果超过应用的 20 MiB 限制")
            width, height = figure.get_size_inches()
            if not (_is_number(float(width)) and _is_number(float(height)) and width > 0 and height > 0):
                raise ValidationError("Figure 尺寸无效")
            return figure

        first = render_once(original_module_settings)
        plt.close(first)
        optional_paths = {
            field["path"] for field in module.PLOT_SCHEMA if field.get("required") is not True
        }
        without_optional = {
            path: value for path, value in original_module_settings.items() if path not in optional_paths
        }
        second = render_once(without_optional)
        if second is first:
            raise ValidationError("render 重复返回缓存的 Figure；每次调用必须新建 Figure")
        if module.PLOT_SETTINGS != original_module_settings:
            raise ValidationError("render 修改了模块级 PLOT_SETTINGS")
        plt.close(second)
    finally:
        plt.close("all")


def smoke_render(path: Path, *, timeout: float) -> None:
    """Smoke-render trusted code in a time-limited child process."""

    command = [sys.executable, str(Path(__file__).resolve()), "--_smoke-worker", str(path.resolve())]
    process = subprocess.Popen(
        command,
        cwd=str(path.resolve().parent),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.communicate()
        raise ValidationError(f"smoke 超过 {timeout:g} 秒，已终止")
    if process.returncode != 0:
        detail = (stderr or stdout).strip()
        raise ValidationError("smoke 子进程失败" + (f"：\n{detail}" if detail else ""))


def _self_test() -> None:
    valid = '''\
PLOT_META = {"id": "demo-plot", "name": "Demo", "description": "Test", "version": 1,
             "data_mode": "demo", "data_note": "Deterministic synthetic test data.",
             "data_export": {"csv": False, "json": True, "note": "Nested test data."}}
PLOT_SCHEMA = [{"path": "figure.size", "label": "Size", "group": "Figure",
                "type": "number_pair", "default": [4, 3], "required": True}]
PLOT_SETTINGS = {"figure.size": [4, 3]}
def prepare_data():
    return [1, 2, 3]
def render(data, settings):
    return object()
'''
    validate_source(valid, Path("plot.py"), strict_conversion=True)
    invalid_sources = [
        valid.replace('PLOT_SETTINGS = {"figure.size": [4, 3]}', 'PLOT_SETTINGS = dict()'),
        valid.replace('PLOT_SETTINGS = {"figure.size": [4, 3]}', 'PLOT_SETTINGS = {"unknown.path": 1}'),
        valid.replace('return object()', 'show()\n    return object()'),
        valid.replace('def prepare_data():', 'from .helper import rows\ndef prepare_data():'),
        valid.replace('"data_mode": "demo", ', ''),
    ]
    for source in invalid_sources:
        try:
            validate_source(source, Path("plot.py"), strict_conversion=True)
        except ValidationError:
            continue
        raise AssertionError("validator self-test expected a failure")

    invalid_select = valid.replace(
        'PLOT_SCHEMA = [{"path": "figure.size", "label": "Size", "group": "Figure",\n'
        '                "type": "number_pair", "default": [4, 3], "required": True}]',
        'PLOT_SCHEMA = [{"path": "figure.size", "label": "Size", "group": "Figure",\n'
        '                "type": "select", "default": None, "options": [{}], "required": True}]',
    ).replace('PLOT_SETTINGS = {"figure.size": [4, 3]}', 'PLOT_SETTINGS = {"figure.size": None}')
    try:
        validate_source(invalid_select, Path("plot.py"), strict_conversion=True)
    except ValidationError:
        pass
    else:
        raise AssertionError("validator self-test expected malformed select options to fail")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="one or more plot.py files")
    parser.add_argument("--smoke", action="store_true", help="execute trusted code and draw with the Agg backend")
    parser.add_argument(
        "--strict-conversion",
        action="store_true",
        help="require provenance and export metadata for newly converted plots",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="smoke timeout per file in seconds (default: 30)")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_smoke-worker", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args._smoke_worker is not None:
        try:
            _smoke_worker(args._smoke_worker)
        except BaseException:
            traceback.print_exc()
            return 1
        return 0
    if args.self_test:
        _self_test()
        print("OK validator self-test")
    if not args.paths:
        if args.self_test:
            return 0
        _parser().error("请提供至少一个 plot.py")

    if args.timeout <= 0:
        _parser().error("--timeout 必须大于 0")
    cache_dir = tempfile.TemporaryDirectory(prefix="matplot-studio-mpl-") if args.smoke else None
    if cache_dir is not None:
        os.environ["MPLCONFIGDIR"] = cache_dir.name
    try:
        failed = False
        seen_ids: dict[str, Path] = {}
        for path in args.paths:
            try:
                meta = validate_file(path, strict_conversion=args.strict_conversion)
                previous = seen_ids.get(str(meta["id"]))
                if previous is not None and previous.resolve() != path.resolve():
                    raise ValidationError(
                        f"PLOT_META.id {meta['id']!r} 已被 {previous} 使用；每个 Figure 必须有唯一 id"
                    )
                seen_ids[str(meta["id"])] = path
                if args.smoke:
                    smoke_render(path, timeout=args.timeout)
            except Exception as exc:  # Report failures per file while allowing the remaining files to run.
                failed = True
                if isinstance(exc, ValidationError):
                    print(exc.render(path), file=sys.stderr)
                else:
                    print(f"{path}: smoke 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            else:
                suffix = " + smoke" if args.smoke else ""
                print(f"OK {path}{suffix}")
        return 1 if failed else 0
    finally:
        if cache_dir is not None:
            cache_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
