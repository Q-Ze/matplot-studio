"""Static validation and source rewriting for the plot module contract."""

from __future__ import annotations

import ast
import copy
import math
import pprint
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


ALLOWED_PROPERTY_TYPES = {
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
KEBAB_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ContractError(ValueError):
    """Raised when plot.py does not satisfy the editable plot contract."""

    def __init__(self, message: str, *, line: Optional[int] = None, field: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.field = field

    def as_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"code": "invalid_plot_contract", "message": self.message}
        if self.line is not None:
            result["line"] = self.line
        if self.field is not None:
            result["field"] = self.field
        return result


@dataclass(frozen=True)
class PlotContract:
    meta: Dict[str, Any]
    schema: List[Dict[str, Any]]
    settings: Dict[str, Any]
    settings_node: ast.AST


def _assignment_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _assignment_value(node: ast.AST) -> Optional[ast.AST]:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def _literal_assignment(tree: ast.Module, name: str) -> Tuple[Any, ast.AST]:
    matches = [node for node in tree.body if _assignment_name(node) == name]
    if not matches:
        raise ContractError(f"缺少顶层字面量 {name}", field=name)
    if len(matches) > 1:
        raise ContractError(f"{name} 只能在顶层定义一次", line=getattr(matches[1], "lineno", None), field=name)
    node = matches[0]
    value_node = _assignment_value(node)
    if value_node is None:
        raise ContractError(f"{name} 必须有值", line=getattr(node, "lineno", None), field=name)
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError):
        raise ContractError(
            f"{name} 必须是可静态读取的 Python 字面量",
            line=getattr(node, "lineno", None),
            field=name,
        )
    return value, node


def _function_nodes(tree: ast.Module, name: str) -> List[ast.AST]:
    return [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]


def _validate_functions(tree: ast.Module) -> None:
    prepare_nodes = _function_nodes(tree, "prepare_data")
    render_nodes = _function_nodes(tree, "render")
    if len(prepare_nodes) != 1:
        raise ContractError("必须在顶层定义且只定义一个 prepare_data()", field="prepare_data")
    if len(render_nodes) != 1:
        raise ContractError("必须在顶层定义且只定义一个 render(data, settings)", field="render")

    prepare = prepare_nodes[0]
    render = render_nodes[0]
    if isinstance(prepare, ast.AsyncFunctionDef) or isinstance(render, ast.AsyncFunctionDef):
        raise ContractError("prepare_data 和 render 必须是同步函数")

    prepare_args = prepare.args  # type: ignore[attr-defined]
    if prepare_args.posonlyargs or prepare_args.args or prepare_args.vararg or prepare_args.kwonlyargs:
        raise ContractError("prepare_data() 不能声明参数", line=prepare.lineno, field="prepare_data")

    render_args = render.args  # type: ignore[attr-defined]
    positional = list(render_args.posonlyargs) + list(render_args.args)
    required = len(positional) - len(render_args.defaults)
    has_required_keyword_only = any(default is None for default in render_args.kw_defaults)
    if required > 2 or len(positional) < 2 or render_args.vararg is not None or has_required_keyword_only:
        raise ContractError("render 必须可按 render(data, settings) 调用", line=render.lineno, field="render")


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def _validate_json_value(value: Any, field: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if _is_number(value):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, field)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json_value(item, field)
        return
    raise ContractError(f"{field} 含有不能通过 API 返回的值", field=field)


def _validate_value(path: str, kind: str, value: Any, item: Mapping[str, Any]) -> None:
    valid = True
    if kind == "number":
        valid = _is_number(value)
    elif kind == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind in {"string", "text", "color"}:
        valid = isinstance(value, str)
    elif kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "select":
        valid = isinstance(value, (str, int, float, bool)) and not isinstance(value, (dict, list, tuple))
        options = item.get("options")
        if not isinstance(options, list) or not options:
            raise ContractError(f"select 属性 {path!r} 必须提供非空 options", field=path)
        option_values = [option.get("value") if isinstance(option, dict) else option for option in options]
        valid = valid and value in option_values
    elif kind == "number_pair":
        valid = isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_number(part) for part in value)
    elif kind in {"string_list", "color_list"}:
        valid = isinstance(value, (list, tuple)) and all(isinstance(part, str) for part in value)
    if not valid:
        raise ContractError(f"属性 {path!r} 的值不符合 {kind} 类型", field=path)

    bounded_values: Sequence[Any] = value if kind == "number_pair" else [value]
    if kind in {"number", "integer", "number_pair"}:
        minimum = item.get("min")
        maximum = item.get("max")
        if minimum is not None and not _is_number(minimum):
            raise ContractError(f"属性 {path!r} 的 min 必须是有限数字", field=path)
        if maximum is not None and not _is_number(maximum):
            raise ContractError(f"属性 {path!r} 的 max 必须是有限数字", field=path)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ContractError(f"属性 {path!r} 的 min 不能大于 max", field=path)
        if minimum is not None and any(part < minimum for part in bounded_values):
            raise ContractError(f"属性 {path!r} 不能小于 {minimum}", field=path)
        if maximum is not None and any(part > maximum for part in bounded_values):
            raise ContractError(f"属性 {path!r} 不能大于 {maximum}", field=path)


def _validate_schema(schema: Any, settings: Any) -> None:
    if not isinstance(schema, list):
        raise ContractError("PLOT_SCHEMA 必须是 list[dict]", field="PLOT_SCHEMA")
    if not isinstance(settings, dict) or not all(isinstance(key, str) for key in settings):
        raise ContractError("PLOT_SETTINGS 必须是以字符串为键的扁平字典", field="PLOT_SETTINGS")

    seen = set()
    for index, item in enumerate(schema):
        if not isinstance(item, dict):
            raise ContractError(f"PLOT_SCHEMA[{index}] 必须是字典", field="PLOT_SCHEMA")
        path = item.get("path")
        kind = item.get("type")
        for required_key in ("path", "label", "group", "type", "default"):
            if required_key not in item:
                raise ContractError(
                    f"PLOT_SCHEMA[{index}] 缺少必需字段 {required_key}",
                    field="PLOT_SCHEMA",
                )
        if not isinstance(path, str) or not path.strip():
            raise ContractError(f"PLOT_SCHEMA[{index}].path 必须是非空字符串", field="PLOT_SCHEMA")
        if not isinstance(item.get("label"), str) or not item["label"].strip():
            raise ContractError(f"属性 {path!r} 的 label 必须是非空字符串", field=path)
        if not isinstance(item.get("group"), str) or not item["group"].strip():
            raise ContractError(f"属性 {path!r} 的 group 必须是非空字符串", field=path)
        if path in seen:
            raise ContractError(f"属性 path {path!r} 重复", field=path)
        seen.add(path)
        if kind not in ALLOWED_PROPERTY_TYPES:
            raise ContractError(f"属性 {path!r} 使用了不支持的类型 {kind!r}", field=path)
        if item.get("required") is True and path not in settings:
            raise ContractError(f"必需属性 {path!r} 必须出现在 PLOT_SETTINGS", field=path)
        if path in settings:
            _validate_value(path, kind, settings[path], item)
        if "default" in item:
            _validate_value(path, kind, item["default"], item)

    unknown = sorted(set(settings) - seen)
    if unknown:
        raise ContractError(
            "PLOT_SETTINGS 含有未在 PLOT_SCHEMA 声明的键：" + ", ".join(repr(key) for key in unknown),
            field="PLOT_SETTINGS",
        )


def validate_plot_source(source: str, *, filename: str = "plot.py") -> PlotContract:
    """Parse source without executing it and return its editable literals."""

    if not isinstance(source, str):
        raise ContractError("代码必须是文本")
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ContractError(
            exc.msg,
            line=exc.lineno,
            field="syntax",
        )

    meta, _ = _literal_assignment(tree, "PLOT_META")
    schema, _ = _literal_assignment(tree, "PLOT_SCHEMA")
    settings, settings_node = _literal_assignment(tree, "PLOT_SETTINGS")
    if not isinstance(meta, dict):
        raise ContractError("PLOT_META 必须是字典", field="PLOT_META")
    for key in ("id", "name", "description"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise ContractError(f"PLOT_META.{key} 必须是非空字符串", field=f"PLOT_META.{key}")
    if not KEBAB_ID.fullmatch(meta["id"]):
        raise ContractError("PLOT_META.id 必须是 kebab-case", field="PLOT_META.id")
    if not isinstance(meta.get("version"), int) or isinstance(meta.get("version"), bool) or meta["version"] < 1:
        raise ContractError("PLOT_META.version 必须是正整数", field="PLOT_META.version")
    if "data_mode" in meta and meta["data_mode"] not in {"inline", "demo"}:
        raise ContractError("PLOT_META.data_mode 只能是 inline 或 demo", field="PLOT_META.data_mode")
    if meta.get("data_mode") == "demo" and (
        not isinstance(meta.get("data_note"), str) or not meta["data_note"].strip()
    ):
        raise ContractError("demo 数据必须提供非空 PLOT_META.data_note", field="PLOT_META.data_note")
    data_export = meta.get("data_export")
    if data_export is not None:
        if not isinstance(data_export, dict):
            raise ContractError("PLOT_META.data_export 必须是字典", field="PLOT_META.data_export")
        for export_format in ("json", "csv"):
            if export_format in data_export and not isinstance(data_export[export_format], bool):
                raise ContractError(
                    f"PLOT_META.data_export.{export_format} 必须是 boolean",
                    field=f"PLOT_META.data_export.{export_format}",
                )
        if "note" in data_export and (
            not isinstance(data_export["note"], str) or not data_export["note"].strip()
        ):
            raise ContractError("PLOT_META.data_export.note 必须是非空字符串", field="PLOT_META.data_export.note")
    _validate_json_value(meta, "PLOT_META")
    _validate_json_value(schema, "PLOT_SCHEMA")
    _validate_json_value(settings, "PLOT_SETTINGS")
    _validate_schema(schema, settings)
    _validate_functions(tree)
    return PlotContract(meta=meta, schema=schema, settings=settings, settings_node=settings_node)


def validate_setting_value(schema: Sequence[Mapping[str, Any]], path: str, value: Any) -> None:
    item = next((candidate for candidate in schema if candidate.get("path") == path), None)
    if item is None:
        raise ContractError(f"未知属性 path：{path!r}", field=path)
    _validate_value(path, str(item["type"]), value, item)


def apply_settings_patch(
    source: str,
    *,
    set_values: Mapping[str, Any],
    unset_paths: Iterable[str],
) -> Tuple[str, Dict[str, Any]]:
    """Update only the top-level PLOT_SETTINGS assignment in source."""

    contract = validate_plot_source(source)
    updated: MutableMapping[str, Any] = copy.deepcopy(contract.settings)
    schema_by_path = {item["path"]: item for item in contract.schema}
    schema_paths = set(schema_by_path)

    for path, value in set_values.items():
        if not isinstance(path, str):
            raise ContractError("属性 path 必须是字符串", field="PLOT_SETTINGS")
        validate_setting_value(contract.schema, path, value)
        updated[path] = copy.deepcopy(value)
    for path in unset_paths:
        if path not in schema_paths:
            raise ContractError(f"未知属性 path：{path!r}", field=str(path))
        if schema_by_path[path].get("required") is True:
            raise ContractError(f"必需属性 {path!r} 不能删除", field=path)
        updated.pop(path, None)

    node = contract.settings_node
    start_line = getattr(node, "lineno", None)
    end_line = getattr(node, "end_lineno", None)
    start_col = getattr(node, "col_offset", None)
    end_col = getattr(node, "end_col_offset", None)
    if None in (start_line, end_line, start_col, end_col):
        raise ContractError("无法定位 PLOT_SETTINGS", field="PLOT_SETTINGS")

    rendered = "PLOT_SETTINGS = " + pprint.pformat(dict(updated), width=100, sort_dicts=False)
    lines = source.splitlines(keepends=True)

    def char_column(line: str, byte_column: int) -> int:
        return len(line.encode("utf-8")[:byte_column].decode("utf-8", errors="ignore"))

    first_index = int(start_line) - 1
    last_index = int(end_line) - 1
    first = lines[first_index]
    last = lines[last_index]
    start_char = char_column(first, int(start_col))
    end_char = char_column(last, int(end_col))
    replacement = first[:start_char] + rendered + last[end_char:]
    new_source = "".join(lines[:first_index]) + replacement + "".join(lines[last_index + 1 :])
    validate_plot_source(new_source)
    return new_source, dict(updated)
