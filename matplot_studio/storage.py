"""Filesystem-backed projects and optimistic revision handling."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .contracts import ContractError, PlotContract, validate_plot_source


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_CODE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_BODY_BYTES = 20 * 1024 * 1024
MAX_IMPORT_FILES = 256
MAX_IMPORT_FILE_BYTES = MAX_CODE_BYTES
MAX_IMPORT_TOTAL_BYTES = 16 * 1024 * 1024
MAX_IMPORT_PATH_LENGTH = 512


class StorageError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass(frozen=True)
class PlotDocument:
    project: str
    plot: str
    path: Path
    code: str
    revision: str
    contract: PlotContract


def revision_for(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"不支持的 JSON 常量：{value}")


class ProjectStore:
    """A deliberately small disk store; plot code is the source of truth."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _check_name(value: str, kind: str) -> None:
        if value in {".", ".."} or not SAFE_NAME.fullmatch(value):
            raise StorageError("invalid_path", f"无效的{kind}名称", status_code=400)

    def _inside_workspace(self, path: Path) -> Path:
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            raise StorageError("invalid_path", "路径超出工作区", status_code=400)
        return resolved

    def project_path(self, project: str) -> Path:
        self._check_name(project, "项目")
        return self._inside_workspace(self.workspace / project)

    def plot_path(self, project: str, plot: str) -> Path:
        self._check_name(plot, "图表")
        project_path = self.project_path(project)
        return self._inside_workspace(project_path / "plots" / plot / "plot.py")

    def _load_project_meta(self, project_path: Path) -> Dict[str, Any]:
        meta_path = project_path / "project.json"
        if not meta_path.is_file():
            raise StorageError("project_not_found", "项目不存在", status_code=404)
        try:
            value = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StorageError("invalid_project", f"无法读取 project.json：{exc}", status_code=500)
        if not isinstance(value, dict):
            raise StorageError("invalid_project", "project.json 顶层必须是对象", status_code=500)
        return value

    @staticmethod
    def _validate_display_text(value: str, field: str, *, required: bool = True) -> str:
        if not isinstance(value, str):
            raise StorageError("invalid_input", f"{field} 必须是字符串", status_code=422)
        value = value.strip()
        if required and not value:
            raise StorageError("invalid_input", f"{field} 不能为空", status_code=422)
        if len(value) > 200:
            raise StorageError("invalid_input", f"{field} 不能超过 200 个字符", status_code=422)
        return value

    @staticmethod
    def _slug_base(name: str, fallback: str) -> str:
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold()).strip("-")
        return (slug or fallback)[:80].rstrip("-")

    @staticmethod
    def _unique_slug(parent: Path, base: str) -> str:
        candidate = base
        suffix = 2
        while (parent / candidate).exists():
            ending = f"-{suffix}"
            candidate = base[: 80 - len(ending)].rstrip("-") + ending
            suffix += 1
        return candidate

    def create_project(self, name: str, description: str = "") -> Dict[str, Any]:
        name = self._validate_display_text(name, "name")
        description = self._validate_display_text(description, "description", required=False)
        with self._lock:
            slug = self._unique_slug(self.workspace, self._slug_base(name, "project"))
            project_path = self._inside_workspace(self.workspace / slug)
            project_path.mkdir()
            (project_path / "plots").mkdir()
            manifest = {"id": slug, "name": name, "description": description, "plots": []}
            self._atomic_write(project_path / "project.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            return manifest

    @staticmethod
    def _import_error(message: str, *, status_code: int = 422, **extra: Any) -> StorageError:
        return StorageError("invalid_project_import", message, status_code=status_code, extra=extra)

    @staticmethod
    def _plot_import_error(message: str, *, status_code: int = 422, **extra: Any) -> StorageError:
        return StorageError("invalid_plot_import", message, status_code=status_code, extra=extra)

    @classmethod
    def _normalize_import_path(cls, value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise cls._import_error("导入文件的 path 必须是非空字符串")
        if len(value) > MAX_IMPORT_PATH_LENGTH:
            raise cls._import_error("导入文件路径过长", path=value[:80])
        if "\x00" in value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
            raise cls._import_error("导入文件路径不能是绝对路径或包含反斜杠", path=value)
        raw_parts = value.split("/")
        if any(part in {"", ".", ".."} for part in raw_parts):
            raise cls._import_error("导入文件路径包含不安全的目录段", path=value)
        for part in raw_parts:
            try:
                encoded_part = part.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise cls._import_error("导入文件路径不是有效的 UTF-8 文本", path=value) from exc
            if len(encoded_part) > 255:
                raise cls._import_error("导入文件路径中的名称过长", path=value)
        normalized = PurePosixPath(*raw_parts).as_posix()
        if normalized in {"", "."}:
            raise cls._import_error("导入文件路径不能为空")
        return normalized

    @classmethod
    def _normalize_import_files(cls, files: Mapping[str, bytes]) -> Dict[str, bytes]:
        if not isinstance(files, Mapping):
            raise cls._import_error("导入文件清单必须是映射")
        normalized_files: Dict[str, bytes] = {}
        collision_keys: Dict[str, str] = {}
        component_spellings: Dict[str, str] = {}
        for raw_path, content in files.items():
            path = cls._normalize_import_path(raw_path)
            if not isinstance(content, bytes):
                raise cls._import_error("导入文件内容必须是 bytes", path=path)
            collision_key = unicodedata.normalize("NFC", path).casefold()
            previous = collision_keys.get(collision_key)
            if previous is not None:
                raise cls._import_error("导入内容包含重复或大小写冲突的文件路径", path=path, conflicts_with=previous)
            collision_keys[collision_key] = path
            normalized_files[path] = content

            parts = PurePosixPath(path).parts
            for length in range(1, len(parts) + 1):
                component_path = PurePosixPath(*parts[:length]).as_posix()
                component_key = unicodedata.normalize("NFC", component_path).casefold()
                previous_spelling = component_spellings.get(component_key)
                if previous_spelling is not None and previous_spelling != component_path:
                    raise cls._import_error(
                        "导入路径的目录名称存在大小写或 Unicode 冲突",
                        path=component_path,
                        conflicts_with=previous_spelling,
                    )
                component_spellings[component_key] = component_path

        file_paths = set(collision_keys)
        for path in file_paths:
            parts = PurePosixPath(path).parts
            for length in range(1, len(parts)):
                parent = PurePosixPath(*parts[:length]).as_posix()
                parent_key = unicodedata.normalize("NFC", parent).casefold()
                if parent_key in file_paths:
                    raise cls._import_error(
                        "同一路径不能同时作为文件和目录",
                        path=collision_keys[path],
                        conflicts_with=collision_keys[parent_key],
                    )
        return normalized_files

    @classmethod
    def _validate_import_limits(cls, files: Mapping[str, bytes]) -> None:
        if not files:
            raise cls._import_error("导入内容中没有文件")
        if len(files) > MAX_IMPORT_FILES:
            raise cls._import_error(
                f"导入文件数不能超过 {MAX_IMPORT_FILES}",
                status_code=413,
                limit=MAX_IMPORT_FILES,
            )
        total = 0
        for path, content in files.items():
            size = len(content)
            if size > MAX_IMPORT_FILE_BYTES:
                raise cls._import_error(
                    f"单个导入文件不能超过 {MAX_IMPORT_FILE_BYTES // (1024 * 1024)} MiB",
                    status_code=413,
                    path=path,
                    limit=MAX_IMPORT_FILE_BYTES,
                )
            total += size
            if total > MAX_IMPORT_TOTAL_BYTES:
                raise cls._import_error(
                    f"导入文件总大小不能超过 {MAX_IMPORT_TOTAL_BYTES // (1024 * 1024)} MiB",
                    status_code=413,
                    limit=MAX_IMPORT_TOTAL_BYTES,
                )

    @classmethod
    def _strip_optional_project_directory(cls, files: Mapping[str, bytes]) -> Dict[str, bytes]:
        if "project.json" in files:
            return dict(files)

        candidates = [path for path in files if len(PurePosixPath(path).parts) == 2 and path.endswith("/project.json")]
        if len(candidates) != 1:
            raise cls._import_error("导入内容必须包含 project.json")
        prefix = PurePosixPath(candidates[0]).parts[0]
        if any(PurePosixPath(path).parts[0] != prefix for path in files):
            raise cls._import_error("project.json 只能位于根目录或唯一的顶层项目目录中")

        stripped: Dict[str, bytes] = {}
        for path, content in files.items():
            parts = PurePosixPath(path).parts
            if len(parts) < 2:
                raise cls._import_error("顶层项目目录中不能混入同级文件", path=path)
            relative = PurePosixPath(*parts[1:]).as_posix()
            if relative in stripped:
                raise cls._import_error("导入内容包含重复文件路径", path=relative)
            stripped[relative] = content
        return stripped

    @classmethod
    def _files_from_json_manifest(cls, items: Any) -> Dict[str, bytes]:
        if not isinstance(items, list):
            raise cls._import_error("JSON 请求必须包含 files 数组")
        if len(items) > MAX_IMPORT_FILES:
            raise cls._import_error(
                f"导入文件数不能超过 {MAX_IMPORT_FILES}",
                status_code=413,
                limit=MAX_IMPORT_FILES,
            )
        files: Dict[str, bytes] = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise cls._import_error(f"files[{index}] 必须是对象")
            if set(item) != {"path", "content"}:
                raise cls._import_error(f"files[{index}] 只能包含 path 和 content")
            path = cls._normalize_import_path(item.get("path"))
            content = item.get("content")
            if not isinstance(content, str):
                raise cls._import_error(f"files[{index}].content 必须是文本")
            try:
                encoded = content.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise cls._import_error(f"files[{index}].content 不是有效的 UTF-8 文本") from exc
            if path in files:
                raise cls._import_error("导入内容包含重复文件路径", path=path)
            files[path] = encoded
        cls._validate_import_limits(files)
        return cls._normalize_import_files(files)

    @classmethod
    def files_from_json_manifest(cls, items: Any) -> Dict[str, bytes]:
        """Validate a browser project-directory payload and return byte contents."""

        return cls._strip_optional_project_directory(cls._files_from_json_manifest(items))

    @classmethod
    def plot_files_from_json_manifest(cls, items: Any) -> Dict[str, bytes]:
        """Validate selected ``plot.py`` files while preserving their relative paths."""

        try:
            files = cls._files_from_json_manifest(items)
        except StorageError as exc:
            if exc.code != "invalid_project_import":
                raise
            raise cls._plot_import_error(
                exc.message,
                status_code=exc.status_code,
                **exc.extra,
            ) from exc
        for path in files:
            if PurePosixPath(path).name != "plot.py":
                raise cls._plot_import_error(
                    "仅可导入文件名严格为 plot.py 的文件",
                    path=path,
                )
        return files

    @classmethod
    def files_from_zip(cls, payload: bytes) -> Dict[str, bytes]:
        """Extract a bounded ZIP into memory without trusting member paths or modes."""

        if not isinstance(payload, bytes):
            raise cls._import_error("ZIP 请求正文必须是二进制数据")
        if len(payload) > MAX_IMPORT_BODY_BYTES:
            raise cls._import_error(
                f"上传内容不能超过 {MAX_IMPORT_BODY_BYTES // (1024 * 1024)} MiB",
                status_code=413,
                limit=MAX_IMPORT_BODY_BYTES,
            )
        files: Dict[str, bytes] = {}
        try:
            with zipfile.ZipFile(io.BytesIO(payload), mode="r") as archive:
                members = archive.infolist()
                if len(members) > MAX_IMPORT_FILES:
                    raise cls._import_error(
                        f"ZIP 条目数不能超过 {MAX_IMPORT_FILES}",
                        status_code=413,
                        limit=MAX_IMPORT_FILES,
                    )
                file_members = [member for member in members if not member.is_dir()]
                if len(file_members) > MAX_IMPORT_FILES:
                    raise cls._import_error(
                        f"导入文件数不能超过 {MAX_IMPORT_FILES}",
                        status_code=413,
                        limit=MAX_IMPORT_FILES,
                    )

                declared_total = 0
                for member in members:
                    member_path = member.filename[:-1] if member.is_dir() and member.filename.endswith("/") else member.filename
                    cls._normalize_import_path(member_path)
                    mode = (member.external_attr >> 16) & 0xFFFF
                    file_type = stat.S_IFMT(mode)
                    if stat.S_ISLNK(mode):
                        raise cls._import_error("ZIP 中不能包含符号链接", path=member.filename)
                    if member.is_dir():
                        if file_type not in {0, stat.S_IFDIR}:
                            raise cls._import_error("ZIP 中包含不支持的特殊文件", path=member.filename)
                        continue
                    if file_type not in {0, stat.S_IFREG}:
                        raise cls._import_error("ZIP 中只能包含普通文件", path=member.filename)
                    if member.flag_bits & 0x1:
                        raise cls._import_error("不支持加密 ZIP 文件", path=member.filename)
                    if member.file_size > MAX_IMPORT_FILE_BYTES:
                        raise cls._import_error(
                            f"单个导入文件不能超过 {MAX_IMPORT_FILE_BYTES // (1024 * 1024)} MiB",
                            status_code=413,
                            path=member.filename,
                            limit=MAX_IMPORT_FILE_BYTES,
                        )
                    declared_total += member.file_size
                    if declared_total > MAX_IMPORT_TOTAL_BYTES:
                        raise cls._import_error(
                            f"导入文件总大小不能超过 {MAX_IMPORT_TOTAL_BYTES // (1024 * 1024)} MiB",
                            status_code=413,
                            limit=MAX_IMPORT_TOTAL_BYTES,
                        )

                    path = cls._normalize_import_path(member.filename)
                    if path in files:
                        raise cls._import_error("ZIP 中包含重复文件路径", path=path)
                    with archive.open(member, mode="r") as handle:
                        content = handle.read(MAX_IMPORT_FILE_BYTES + 1)
                    if len(content) != member.file_size or len(content) > MAX_IMPORT_FILE_BYTES:
                        raise cls._import_error("ZIP 文件大小信息无效", path=path)
                    files[path] = content
        except StorageError:
            raise
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise cls._import_error(f"无法读取 ZIP：{exc}") from exc

        cls._validate_import_limits(files)
        return cls._strip_optional_project_directory(cls._normalize_import_files(files))

    @classmethod
    def _validated_import(
        cls,
        files: Mapping[str, bytes],
    ) -> Tuple[Dict[str, bytes], Dict[str, Any], List[Dict[str, Any]]]:
        files = cls._normalize_import_files(files)
        files = cls._strip_optional_project_directory(files)
        files = cls._normalize_import_files(files)
        cls._validate_import_limits(files)
        manifest_bytes = files.get("project.json")
        if manifest_bytes is None:
            raise cls._import_error("导入内容必须包含 project.json")
        try:
            manifest = json.loads(
                manifest_bytes.decode("utf-8"),
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise cls._import_error(f"project.json 不是有效的 UTF-8 JSON：{exc}") from exc
        if not isinstance(manifest, dict):
            raise cls._import_error("project.json 顶层必须是对象")

        try:
            project_id = cls._validate_display_text(manifest.get("id"), "project.json.id")
            name = cls._validate_display_text(manifest.get("name"), "project.json.name")
            description = cls._validate_display_text(
                manifest.get("description", ""),
                "project.json.description",
                required=False,
            )
        except StorageError as exc:
            raise cls._import_error(exc.message) from exc
        manifest_plots = manifest.get("plots")
        if not isinstance(manifest_plots, list):
            raise cls._import_error("project.json.plots 必须是数组")

        manifest_ids: List[str] = []
        for index, item in enumerate(manifest_plots):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise cls._import_error(f"project.json.plots[{index}].id 必须是字符串")
            plot_id = item["id"]
            try:
                cls._check_name(plot_id, "图表")
            except StorageError as exc:
                raise cls._import_error("project.json.plots 中包含无效的图表 id", plot=plot_id) from exc
            if plot_id in manifest_ids:
                raise cls._import_error("project.json.plots 包含重复 id", plot=plot_id)
            manifest_ids.append(plot_id)

        actual_ids = set()
        for path in files:
            parts = PurePosixPath(path).parts
            if parts[0] != "plots":
                continue
            if len(parts) < 3:
                raise cls._import_error("plots 下的文件必须位于 plots/<id>/ 中", path=path)
            plot_id = parts[1]
            try:
                cls._check_name(plot_id, "图表")
            except StorageError as exc:
                raise cls._import_error("plots 目录中包含无效的图表 id", plot=plot_id) from exc
            actual_ids.add(plot_id)
        if not actual_ids:
            raise cls._import_error("项目中至少需要一个 plots/<id>/plot.py")
        if set(manifest_ids) != actual_ids:
            raise cls._import_error(
                "project.json.plots 必须与 plots 目录中的图表一致",
                manifest_plots=manifest_ids,
                directory_plots=sorted(actual_ids),
            )

        contracts: Dict[str, PlotContract] = {}
        for plot_id in manifest_ids:
            source_path = f"plots/{plot_id}/plot.py"
            source_bytes = files.get(source_path)
            if source_bytes is None:
                raise cls._import_error("每个图表目录都必须包含 plot.py", plot=plot_id)
            try:
                source = source_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise cls._import_error("plot.py 必须是 UTF-8 文本", plot=plot_id) from exc
            contract = validate_plot_source(source, filename=source_path)
            if contract.meta["id"] != plot_id:
                raise cls._import_error(
                    "plot 目录名称必须与 PLOT_META.id 一致",
                    plot=plot_id,
                    meta_id=contract.meta["id"],
                )
            contracts[plot_id] = contract

        normalized_manifest = {
            "id": project_id,
            "name": name,
            "description": description,
            "plots": [
                {
                    "id": plot_id,
                    "name": contracts[plot_id].meta["name"],
                    "description": contracts[plot_id].meta["description"],
                }
                for plot_id in manifest_ids
            ],
        }
        normalized_files = dict(files)
        normalized_files["project.json"] = (
            json.dumps(normalized_manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        plot_summaries = []
        for plot_id in manifest_ids:
            source = normalized_files[f"plots/{plot_id}/plot.py"].decode("utf-8")
            plot_summary = dict(contracts[plot_id].meta)
            plot_summary.update({"id": plot_id, "valid": True, "revision": revision_for(source)})
            plot_summaries.append(plot_summary)
        return normalized_files, normalized_manifest, plot_summaries

    def import_project(self, files: Mapping[str, bytes]) -> Dict[str, Any]:
        """Validate and atomically install one self-contained Matplot Studio project."""

        normalized_files, manifest, plot_summaries = self._validated_import(files)
        staging_path: Optional[Path] = None
        with self._lock:
            base_source = manifest["id"] if isinstance(manifest.get("id"), str) else manifest["name"]
            slug = self._unique_slug(self.workspace, self._slug_base(base_source, "project"))
            destination = self._inside_workspace(self.workspace / slug)
            try:
                staging_path = Path(tempfile.mkdtemp(prefix=".import-", dir=str(self.workspace))).resolve()
                self._inside_workspace(staging_path)
                for relative, content in normalized_files.items():
                    target = staging_path.joinpath(*PurePosixPath(relative).parts)
                    self._inside_workspace(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)

                installed_manifest = dict(manifest)
                installed_manifest["id"] = slug
                self._atomic_write(
                    staging_path / "project.json",
                    json.dumps(installed_manifest, ensure_ascii=False, indent=2) + "\n",
                )
                os.replace(staging_path, destination)
                staging_path = None
            finally:
                if staging_path is not None:
                    shutil.rmtree(staging_path, ignore_errors=True)
            project_summary = {key: value for key, value in manifest.items() if key != "plots"}
            project_summary.update({"id": slug, "plots": plot_summaries})
            return project_summary

    @classmethod
    def _validated_plot_import(
        cls,
        files: Mapping[str, bytes],
    ) -> List[Tuple[str, str, PlotContract, Dict[str, Any]]]:
        """Validate all selected plot modules before any project state is changed."""

        try:
            normalized_files = cls._normalize_import_files(files)
            cls._validate_import_limits(normalized_files)
        except StorageError as exc:
            if exc.code != "invalid_project_import":
                raise
            raise cls._plot_import_error(
                exc.message,
                status_code=exc.status_code,
                **exc.extra,
            ) from exc
        validated: List[Tuple[str, str, PlotContract, Dict[str, Any]]] = []
        seen_ids: Dict[str, str] = {}
        for path, source_bytes in normalized_files.items():
            if PurePosixPath(path).name != "plot.py":
                raise cls._plot_import_error(
                    "仅可导入文件名严格为 plot.py 的文件",
                    path=path,
                )
            try:
                source = source_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise cls._plot_import_error("plot.py 必须是 UTF-8 文本", path=path) from exc
            try:
                contract = validate_plot_source(source, filename=path)
            except ContractError as exc:
                extra: Dict[str, Any] = {"path": path}
                if exc.line is not None:
                    extra["line"] = exc.line
                if exc.field is not None:
                    extra["field"] = exc.field
                raise cls._plot_import_error(exc.message, **extra) from exc

            plot_id = contract.meta["id"]
            try:
                cls._check_name(plot_id, "图表")
            except StorageError as exc:
                raise cls._plot_import_error(
                    "PLOT_META.id 不是安全的图表 ID",
                    path=path,
                    plot=plot_id,
                ) from exc
            previous_path = seen_ids.get(plot_id)
            if previous_path is not None:
                raise cls._plot_import_error(
                    "多个 plot.py 使用了相同的 PLOT_META.id",
                    path=path,
                    plot=plot_id,
                    conflicts_with=previous_path,
                )
            seen_ids[plot_id] = path
            summary = {
                "id": plot_id,
                "name": contract.meta["name"],
                "description": contract.meta["description"],
                "valid": True,
                "revision": revision_for(source),
            }
            validated.append((plot_id, source, contract, summary))
        return validated

    def import_plots(self, project: str, files: Mapping[str, bytes]) -> List[Dict[str, Any]]:
        """Atomically add one or more self-contained plot modules to a project."""

        validated = self._validated_plot_import(files)
        with self._lock:
            project_path = self.project_path(project)
            manifest = self._load_project_meta(project_path)
            manifest_plots = manifest.get("plots")
            if not isinstance(manifest_plots, list):
                raise StorageError("invalid_project", "project.json.plots 必须是数组", status_code=500)

            manifest_ids = {
                item["id"]
                for item in manifest_plots
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            plots_path = self._inside_workspace(project_path / "plots")
            plots_path.mkdir(exist_ok=True)
            conflicts = [
                plot_id
                for plot_id, _source, _contract, _summary in validated
                if plot_id in manifest_ids or os.path.lexists(plots_path / plot_id)
            ]
            if conflicts:
                raise StorageError(
                    "plot_already_exists",
                    "目标项目中已存在同 ID 的图表",
                    status_code=409,
                    extra={"plots": conflicts},
                )

            summaries = [dict(item[3]) for item in validated]
            imported_manifest_items = [
                {
                    "id": summary["id"],
                    "name": summary["name"],
                    "description": summary["description"],
                }
                for summary in summaries
            ]
            updated_manifest = dict(manifest)
            updated_manifest["id"] = project
            updated_manifest["plots"] = [*manifest_plots, *imported_manifest_items]
            manifest_text = json.dumps(updated_manifest, ensure_ascii=False, indent=2) + "\n"

            staging_path: Optional[Path] = None
            moved_ids: List[str] = []
            try:
                staging_path = Path(
                    tempfile.mkdtemp(prefix=".plot-import-", dir=str(project_path))
                ).resolve()
                self._inside_workspace(staging_path)
                for plot_id, source, _contract, _summary in validated:
                    staged_dir = staging_path / plot_id
                    staged_dir.mkdir()
                    (staged_dir / "plot.py").write_bytes(source.encode("utf-8"))

                for plot_id, _source, _contract, _summary in validated:
                    os.replace(staging_path / plot_id, plots_path / plot_id)
                    moved_ids.append(plot_id)
                self._atomic_write(project_path / "project.json", manifest_text)
            except Exception:
                if staging_path is not None:
                    for plot_id in reversed(moved_ids):
                        installed = plots_path / plot_id
                        if installed.exists():
                            os.replace(installed, staging_path / plot_id)
                raise
            finally:
                if staging_path is not None:
                    shutil.rmtree(staging_path, ignore_errors=True)
            return summaries

    def delete_project(self, project: str) -> Dict[str, Any]:
        """Remove a project after atomically moving it out of the visible workspace."""

        with self._lock:
            project_path = self.project_path(project)
            manifest = self._load_project_meta(project_path)
            manifest_plots = manifest.get("plots")
            plot_count = len(manifest_plots) if isinstance(manifest_plots, list) else 0
            name = manifest.get("name") if isinstance(manifest.get("name"), str) else project

            tombstone = Path(tempfile.mkdtemp(prefix=".delete-project-", dir=str(self.workspace)))
            tombstone.rmdir()
            os.replace(project_path, tombstone)
            shutil.rmtree(tombstone, ignore_errors=True)
            return {
                "type": "project",
                "id": project,
                "name": name,
                "plot_count": plot_count,
            }

    def delete_plot(self, project: str, plot: str) -> Dict[str, Any]:
        """Delete one plot and update its project manifest as one recoverable operation."""

        with self._lock:
            self._check_name(plot, "图表")
            project_path = self.project_path(project)
            manifest = self._load_project_meta(project_path)
            source_path = self.plot_path(project, plot)
            plot_dir = source_path.parent
            if not source_path.is_file():
                raise StorageError("plot_not_found", "图表不存在", status_code=404)

            manifest_plots = manifest.get("plots")
            if not isinstance(manifest_plots, list):
                raise StorageError("invalid_project", "project.json.plots 必须是数组", status_code=500)
            manifest_item = next(
                (
                    item
                    for item in manifest_plots
                    if isinstance(item, dict) and item.get("id") == plot
                ),
                {},
            )
            name = manifest_item.get("name") if isinstance(manifest_item.get("name"), str) else plot
            description = (
                manifest_item.get("description")
                if isinstance(manifest_item.get("description"), str)
                else ""
            )
            updated_manifest = dict(manifest)
            updated_manifest["plots"] = [
                item
                for item in manifest_plots
                if not (isinstance(item, dict) and item.get("id") == plot)
            ]
            manifest_text = json.dumps(updated_manifest, ensure_ascii=False, indent=2) + "\n"

            plots_path = self._inside_workspace(project_path / "plots")
            tombstone = Path(tempfile.mkdtemp(prefix=".delete-plot-", dir=str(plots_path)))
            tombstone.rmdir()
            os.replace(plot_dir, tombstone)
            try:
                self._atomic_write(project_path / "project.json", manifest_text)
            except Exception:
                os.replace(tombstone, plot_dir)
                raise
            shutil.rmtree(tombstone, ignore_errors=True)
            return {
                "type": "plot",
                "project": project,
                "id": plot,
                "name": name,
                "description": description,
            }

    def create_plot(self, project: str, name: str, description: str = "") -> PlotDocument:
        name = self._validate_display_text(name, "name")
        description = self._validate_display_text(description, "description", required=False)
        with self._lock:
            project_path = self.project_path(project)
            manifest = self._load_project_meta(project_path)
            plots_path = self._inside_workspace(project_path / "plots")
            plots_path.mkdir(exist_ok=True)
            slug = self._unique_slug(plots_path, self._slug_base(name, "plot"))
            plot_dir = self._inside_workspace(plots_path / slug)
            plot_dir.mkdir()
            source = self._starter_plot_source(slug, name, description or "New Matplot Studio figure")
            validate_plot_source(source)
            self._atomic_write(plot_dir / "plot.py", source)

            manifest_plots = manifest.get("plots")
            if not isinstance(manifest_plots, list):
                manifest_plots = []
            manifest["id"] = project
            manifest["plots"] = [*manifest_plots, {"id": slug, "name": name, "description": description}]
            self._atomic_write(
                project_path / "project.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            return self.read_plot(project, slug)

    @staticmethod
    def _starter_plot_source(plot_id: str, name: str, description: str) -> str:
        meta = {
            "id": plot_id,
            "name": name,
            "description": description,
            "version": 1,
            "data_mode": "demo",
            "data_note": "Deterministic demo data embedded in prepare_data().",
            "data_export": {"csv": True, "json": True, "note": "One row per x value."},
        }
        return f'''"""Self-contained Matplot Studio starter plot."""

import matplotlib.pyplot as plt


PLOT_META = {meta!r}

PLOT_SCHEMA = [
    {{"path": "figure.size", "label": "Figure size", "group": "Figure", "type": "number_pair", "default": [7.0, 4.5], "min": 2, "max": 16, "step": 0.1, "required": True}},
    {{"path": "axes.title", "label": "Title", "group": "Axes", "type": "string", "default": {name!r}, "required": True}},
    {{"path": "axes.xlabel", "label": "X-axis label", "group": "Axes", "type": "string", "default": "X"}},
    {{"path": "axes.ylabel", "label": "Y-axis label", "group": "Axes", "type": "string", "default": "Y"}},
    {{"path": "line.color", "label": "Line color", "group": "Line", "type": "color", "default": "#3B6FB6"}},
    {{"path": "line.width", "label": "Line width", "group": "Line", "type": "number", "default": 2.0, "min": 0.1, "max": 10, "step": 0.1}},
    {{"path": "line.marker", "label": "Marker", "group": "Line", "type": "select", "default": "o", "options": ["o", "s", "^", "none"]}},
    {{"path": "axes.grid", "label": "Show grid", "group": "Axes", "type": "boolean", "default": True}},
]

# <matplot-studio:settings>
PLOT_SETTINGS = {{
    "figure.size": [7.0, 4.5],
    "axes.title": {name!r},
    "axes.xlabel": "X",
    "axes.ylabel": "Y",
    "line.color": "#3B6FB6",
    "line.width": 2.0,
    "line.marker": "o",
    "axes.grid": True,
}}
# </matplot-studio:settings>


def _resolved(settings):
    values = {{field["path"]: field["default"] for field in PLOT_SCHEMA}}
    values.update(settings or {{}})
    return values


def prepare_data():
    """Replace this deterministic demo data with data kept in this file."""
    x = list(range(12))
    y = [0.18 * value ** 2 + 1.6 * value + 3 for value in x]
    return {{"x": x, "y": y}}


def render(data, settings):
    """Build and return one Matplotlib Figure."""
    s = _resolved(settings)
    fig, ax = plt.subplots(figsize=tuple(s["figure.size"]))
    marker = None if s["line.marker"] == "none" else s["line.marker"]
    ax.plot(data["x"], data["y"], color=s["line.color"], linewidth=s["line.width"], marker=marker)
    ax.set(title=s["axes.title"], xlabel=s["axes.xlabel"], ylabel=s["axes.ylabel"])
    if s["axes.grid"]:
        ax.grid(True, alpha=0.25)
    else:
        ax.grid(False)
    fig.tight_layout()
    return fig
'''

    def list_projects(self) -> List[Dict[str, Any]]:
        projects: List[Dict[str, Any]] = []
        with self._lock:
            for child in sorted(self.workspace.iterdir(), key=lambda path: path.name.casefold()):
                if not child.is_dir() or not SAFE_NAME.fullmatch(child.name):
                    continue
                try:
                    child = self._inside_workspace(child)
                    meta = self._load_project_meta(child)
                except StorageError:
                    continue
                plots_path = child / "plots"
                plots: List[Dict[str, Any]] = []
                manifest_plots = meta.get("plots", [])
                manifest_by_id = {
                    item["id"]: item
                    for item in manifest_plots
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                } if isinstance(manifest_plots, list) else {}
                if plots_path.is_dir():
                    plot_dirs = {}
                    for candidate in plots_path.iterdir():
                        if not candidate.is_dir() or not SAFE_NAME.fullmatch(candidate.name):
                            continue
                        try:
                            candidate = self._inside_workspace(candidate)
                        except StorageError:
                            continue
                        if (candidate / "plot.py").is_file():
                            plot_dirs[candidate.name] = candidate
                    manifest_order = [item["id"] for item in manifest_plots if isinstance(item, dict) and item.get("id") in plot_dirs]
                    remaining = sorted(set(plot_dirs) - set(manifest_order), key=str.casefold)
                    for plot_id in manifest_order + remaining:
                        plot_dir = plot_dirs[plot_id]
                        source_path = plot_dir / "plot.py"
                        plot_info: Dict[str, Any] = {"id": plot_dir.name, "name": plot_dir.name}
                        plot_info.update(manifest_by_id.get(plot_dir.name, {}))
                        try:
                            source = source_path.read_text(encoding="utf-8")
                            contract = validate_plot_source(source, filename=str(source_path))
                            plot_info.update(contract.meta)
                            plot_info["id"] = plot_dir.name
                            plot_info["valid"] = True
                            plot_info["revision"] = revision_for(source)
                        except Exception as exc:
                            plot_info["valid"] = False
                            plot_info["error"] = str(exc)
                        plots.append(plot_info)
                project_info: Dict[str, Any] = {"id": child.name, "name": child.name}
                project_info.update({key: value for key, value in meta.items() if key != "plots"})
                project_info["id"] = child.name
                project_info["plots"] = plots
                projects.append(project_info)
        return projects

    def read_plot(self, project: str, plot: str) -> PlotDocument:
        with self._lock:
            project_path = self.project_path(project)
            self._load_project_meta(project_path)
            path = self.plot_path(project, plot)
            if not path.is_file():
                raise StorageError("plot_not_found", "图表不存在", status_code=404)
            try:
                code = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise StorageError("read_failed", f"无法读取 plot.py：{exc}", status_code=500)
            contract = validate_plot_source(code, filename=str(path))
            return PlotDocument(project, plot, path, code, revision_for(code), contract)

    def write_plot(self, project: str, plot: str, code: str, expected_revision: Optional[str]) -> PlotDocument:
        if not isinstance(code, str):
            raise StorageError("invalid_code", "code 必须是字符串", status_code=422)
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise StorageError("code_too_large", "plot.py 不能超过 2 MiB", status_code=413)
        with self._lock:
            current = self.read_plot(project, plot)
            if expected_revision is not None and expected_revision != current.revision:
                raise StorageError(
                    "revision_conflict",
                    "代码已被其他编辑更新，请重新载入后再保存",
                    status_code=409,
                    extra={"current_revision": current.revision},
                )
            validate_plot_source(code)
            self._atomic_write(current.path, code)
            return self.read_plot(project, plot)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        descriptor = -1
        temp_name: Optional[str] = None
        try:
            descriptor, temp_name = tempfile.mkstemp(prefix=".plot-", suffix=".tmp", dir=str(path.parent))
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                descriptor = -1
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
