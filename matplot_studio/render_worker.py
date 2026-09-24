"""Private subprocess entry point used to execute one trusted local plot module."""

from __future__ import annotations

import contextlib
import csv
import datetime as datetime_module
import importlib.util
import io
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any, Dict


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class DataExportError(TypeError):
    """Raised when prepare_data() cannot be represented in the requested format."""


def _is_pandas_dataframe(value: Any) -> bool:
    return value.__class__.__name__ == "DataFrame" and value.__class__.__module__.startswith("pandas")


def _is_pandas_series(value: Any) -> bool:
    return value.__class__.__name__ == "Series" and value.__class__.__module__.startswith("pandas")


def _json_value(value: Any) -> Any:
    """Convert common scientific Python values into strict JSON values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime_module.date, datetime_module.time, datetime_module.datetime)):
        return value.isoformat()
    if _is_pandas_dataframe(value):
        return _json_value(value.to_dict(orient="records"))
    if _is_pandas_series(value):
        return _json_value(value.tolist())

    # NumPy scalars and arrays expose item()/tolist() without requiring the
    # user's plot to import NumPy under a particular name.
    module_name = value.__class__.__module__
    if module_name.startswith("pandas.") and value.__class__.__name__ in {"NAType", "NaTType"}:
        return None
    if module_name == "numpy" or module_name.startswith("numpy."):
        if hasattr(value, "tolist"):
            converted = value.tolist()
        elif hasattr(value, "item"):
            converted = value.item()
        else:
            raise DataExportError(f"不支持的 NumPy 数据类型：{type(value).__name__}")
        return _json_value(converted)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    raise DataExportError(f"JSON 无法序列化 prepare_data() 中的 {type(value).__name__}")


def _csv_scalar(value: Any) -> Any:
    converted = _json_value(value)
    if converted is None:
        return ""
    if isinstance(converted, (dict, list)):
        raise DataExportError("CSV 单元格必须是标量，不能包含嵌套字典或列表")
    return converted


def _csv_from_records(records: Any) -> str:
    if not records:
        return ""
    if not all(isinstance(record, dict) for record in records):
        raise DataExportError("CSV 的 list 数据必须是 list[dict]")
    columns = []
    seen = set()
    for record in records:
        for key in record:
            label = str(key)
            if label not in seen:
                columns.append(label)
                seen.add(label)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        normalized = {str(key): _csv_scalar(value) for key, value in record.items()}
        writer.writerow(normalized)
    return output.getvalue()


def _one_dimensional_column(value: Any, name: str) -> list[Any]:
    if _is_pandas_series(value):
        return list(value.tolist())
    module_name = value.__class__.__module__
    if module_name == "numpy" or module_name.startswith("numpy."):
        ndim = getattr(value, "ndim", None)
        if ndim != 1:
            raise DataExportError(f"CSV 列 {name!r} 必须是一维数组")
        return list(value.tolist())
    if isinstance(value, (list, tuple)):
        return list(value)
    raise DataExportError(f"CSV 列 {name!r} 必须是 list、tuple、一维 NumPy 数组或 pandas Series")


def _csv_value(value: Any) -> str:
    if _is_pandas_dataframe(value):
        return value.to_csv(index=False)
    if isinstance(value, list):
        return _csv_from_records(value)
    if isinstance(value, dict):
        if not value:
            return ""
        columns = {str(name): _one_dimensional_column(column, str(name)) for name, column in value.items()}
        lengths = {len(column) for column in columns.values()}
        if len(lengths) > 1:
            raise DataExportError("CSV 的各列长度必须一致")
        row_count = next(iter(lengths), 0)
        records = [
            {name: _csv_scalar(column[index]) for name, column in columns.items()}
            for index in range(row_count)
        ]
        return _csv_from_records(records) if records else ",".join(columns) + ("\r\n" if columns else "")
    raise DataExportError("CSV 仅支持 pandas DataFrame、list[dict] 或等长一维列组成的 dict")


def _load_plot_module(source_path: Path) -> Any:
    sys.path.insert(0, str(source_path.parent))
    spec = importlib.util.spec_from_file_location("_matplot_studio_user_plot", str(source_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入 plot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) not in {6, 7}:
        return 2
    operation = sys.argv[1]
    output_format = sys.argv[2]
    source_path = Path(sys.argv[3]).resolve()
    output_path = Path(sys.argv[4]).resolve()
    result_path = Path(sys.argv[5]).resolve()
    dpi_argument = sys.argv[6] if len(sys.argv) == 7 else None
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        from matplotlib.figure import Figure

        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            module = _load_plot_module(source_path)
            prepare_data = getattr(module, "prepare_data", None)
            if not callable(prepare_data):
                raise TypeError("plot.py 未提供有效的 prepare_data")
            data = prepare_data()
            if operation == "image":
                if output_format not in {"svg", "png", "pdf"}:
                    raise ValueError(f"不支持的图片格式：{output_format}")
                dpi = None
                if dpi_argument is not None:
                    if output_format != "png":
                        raise ValueError("DPI 参数仅适用于 PNG 图片导出")
                    try:
                        dpi = int(dpi_argument)
                    except ValueError as exc:
                        raise ValueError("PNG 导出 DPI 必须是整数") from exc
                    if not 36 <= dpi <= 600:
                        raise ValueError("PNG 导出 DPI 必须在 36 到 600 之间")
                render = getattr(module, "render", None)
                settings = getattr(module, "PLOT_SETTINGS", None)
                if not callable(render) or not isinstance(settings, dict):
                    raise TypeError("plot.py 未提供有效的 render 和 PLOT_SETTINGS")
                figure = render(data, dict(settings))
                if not isinstance(figure, Figure):
                    raise TypeError("render(data, settings) 必须返回 matplotlib.figure.Figure")
                savefig_options = {"format": output_format}
                if dpi is not None:
                    savefig_options["dpi"] = dpi
                figure.savefig(str(output_path), **savefig_options)
                figure.clear()
            elif operation == "data":
                if output_format == "json":
                    output_path.write_text(
                        json.dumps(_json_value(data), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8",
                    )
                elif output_format == "csv":
                    with output_path.open("w", encoding="utf-8", newline="") as handle:
                        handle.write(_csv_value(data))
                else:
                    raise ValueError(f"不支持的数据格式：{output_format}")
            else:
                raise ValueError(f"不支持的子进程操作：{operation}")
        _write_json(
            result_path,
            {
                "ok": True,
                "stdout": captured_stdout.getvalue(),
                "stderr": captured_stderr.getvalue(),
            },
        )
        return 0
    except BaseException as exc:
        _write_json(
            result_path,
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": captured_stdout.getvalue(),
                "stderr": captured_stderr.getvalue(),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
