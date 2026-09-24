"""Timed Agg rendering in a disposable Python subprocess."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .storage import revision_for


MAX_ARTIFACT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    revision: str
    duration_ms: int
    svg: Optional[bytes] = None
    error_type: Optional[str] = None
    message: Optional[str] = None
    traceback: Optional[str] = None
    stdout: str = ""
    stderr: str = ""

    @property
    def content(self) -> Optional[bytes]:
        """Artifact bytes; ``svg`` is retained for compatibility with render callers."""

        return self.svg

    def public_dict(self, *, svg_url: Optional[str] = None) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "ok": self.ok,
            "revision": self.revision,
            "duration_ms": self.duration_ms,
        }
        if svg_url is not None and self.ok:
            value["svg_url"] = svg_url
        if self.stdout:
            value["stdout"] = self.stdout
        if self.stderr:
            value["stderr"] = self.stderr
        if not self.ok:
            value.update(
                {
                    "error_type": self.error_type or "RenderError",
                    "message": self.message or "渲染失败",
                    "traceback": self.traceback or "",
                }
            )
        return value


class Renderer:
    def __init__(self, *, timeout_seconds: float = 15.0):
        self.timeout_seconds = float(timeout_seconds)
        self._cache: Dict[Tuple[str, str], RenderResult] = {}
        self._lock = threading.RLock()
        self._worker_path = Path(__file__).with_name("render_worker.py")
        self._mpl_config_dir = Path(tempfile.gettempdir()) / "matplot-studio-mpl-cache"
        self._mpl_config_dir.mkdir(parents=True, exist_ok=True)

    def render(self, source_path: Path, source: str, *, force: bool = False) -> RenderResult:
        revision = revision_for(source)
        key = (str(source_path.resolve()), revision)
        with self._lock:
            if not force and key in self._cache:
                return self._cache[key]
        result = self._run(source_path, revision, operation="image", output_format="svg")
        with self._lock:
            self._cache[key] = result
            stale = [cache_key for cache_key in self._cache if cache_key[0] == key[0] and cache_key != key]
            for cache_key in stale:
                self._cache.pop(cache_key, None)
        return result

    def export_image(
        self,
        source_path: Path,
        source: str,
        output_format: str,
        *,
        dpi: Optional[int] = None,
    ) -> RenderResult:
        if output_format not in {"png", "svg", "pdf"}:
            raise ValueError(f"不支持的图片格式：{output_format}")
        if dpi is not None:
            if isinstance(dpi, bool) or not isinstance(dpi, int) or not 36 <= dpi <= 600:
                raise ValueError("PNG 导出 DPI 必须是 36 到 600 之间的整数")
            if output_format != "png":
                raise ValueError("DPI 参数仅适用于 PNG 图片导出")
        return self._run(
            source_path,
            revision_for(source),
            operation="image",
            output_format=output_format,
            dpi=dpi,
        )

    def export_data(self, source_path: Path, source: str, output_format: str) -> RenderResult:
        if output_format not in {"json", "csv"}:
            raise ValueError(f"不支持的数据格式：{output_format}")
        return self._run(source_path, revision_for(source), operation="data", output_format=output_format)

    def _run(
        self,
        source_path: Path,
        revision: str,
        *,
        operation: str,
        output_format: str,
        dpi: Optional[int] = None,
    ) -> RenderResult:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="matplot-studio-render-") as temp_dir:
            temp_path = Path(temp_dir)
            artifact_path = temp_path / f"artifact.{output_format}"
            result_path = temp_path / "result.json"
            env = os.environ.copy()
            env.update(
                {
                    "MPLBACKEND": "Agg",
                    "MPLCONFIGDIR": str(self._mpl_config_dir),
                    "PYTHONUTF8": "1",
                }
            )
            worker_arguments = [
                sys.executable,
                str(self._worker_path),
                operation,
                output_format,
                str(source_path),
                str(artifact_path),
                str(result_path),
            ]
            if dpi is not None:
                worker_arguments.append(str(dpi))
            process = subprocess.Popen(
                worker_arguments,
                cwd=str(source_path.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                worker_stdout, worker_stderr = process.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()
                worker_stdout, worker_stderr = process.communicate()
                return RenderResult(
                    ok=False,
                    revision=revision,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_type="RenderTimeout",
                    message=f"子进程运行超过 {self.timeout_seconds:g} 秒，已终止",
                    traceback="",
                    stdout=worker_stdout,
                    stderr=worker_stderr,
                )

            payload: Dict[str, Any] = {}
            if result_path.is_file():
                try:
                    loaded = json.loads(result_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        payload = loaded
                except (OSError, UnicodeError, json.JSONDecodeError):
                    payload = {}
            duration_ms = int((time.monotonic() - started) * 1000)
            if process.returncode == 0 and payload.get("ok") is True and artifact_path.is_file():
                content = artifact_path.read_bytes()
                if len(content) > MAX_ARTIFACT_BYTES:
                    return RenderResult(
                        ok=False,
                        revision=revision,
                        duration_ms=duration_ms,
                        error_type="OutputTooLarge",
                        message="导出结果超过 50 MiB",
                    )
                return RenderResult(
                    ok=True,
                    revision=revision,
                    duration_ms=duration_ms,
                    svg=content,
                    stdout=str(payload.get("stdout", "")),
                    stderr=str(payload.get("stderr", "")),
                )

            message = str(payload.get("message") or f"渲染子进程退出，状态码 {process.returncode}")
            return RenderResult(
                ok=False,
                revision=revision,
                duration_ms=duration_ms,
                error_type=str(payload.get("error_type") or "RenderProcessError"),
                message=message,
                traceback=str(payload.get("traceback") or ""),
                stdout=str(payload.get("stdout") or worker_stdout),
                stderr=str(payload.get("stderr") or worker_stderr),
            )
