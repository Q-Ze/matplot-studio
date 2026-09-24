"""FastAPI application for editing and rendering Matplotlib plot modules."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import ContractError, apply_settings_patch
from .rendering import RenderResult, Renderer
from .storage import MAX_IMPORT_BODY_BYTES, PlotDocument, ProjectStore, StorageError


class CodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    revision: Optional[str] = None


class CreateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""


class SettingOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["set", "unset"]
    path: str
    value: Any = None


class SettingsPatch(BaseModel):
    """Accept batch operations as well as the convenient set/unset maps."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    revision: Optional[str] = None
    set_values: Dict[str, Any] = Field(default_factory=dict, alias="set")
    unset_paths: List[str] = Field(default_factory=list, alias="unset")
    operations: List[SettingOperation] = Field(default_factory=list)
    op: Optional[Literal["set", "unset"]] = None
    path: Optional[str] = None
    value: Any = None

    @model_validator(mode="after")
    def validate_single_operation(self) -> "SettingsPatch":
        if (self.op is None) != (self.path is None):
            raise ValueError("op 和 path 必须同时提供")
        return self

    def normalized(self) -> tuple[Dict[str, Any], List[str]]:
        values = dict(self.set_values)
        removed = list(self.unset_paths)
        operations = list(self.operations)
        if self.op is not None and self.path is not None:
            operations.append(SettingOperation(op=self.op, path=self.path, value=self.value))
        for operation in operations:
            if operation.op == "set":
                values[operation.path] = operation.value
                if operation.path in removed:
                    removed.remove(operation.path)
            else:
                values.pop(operation.path, None)
                if operation.path not in removed:
                    removed.append(operation.path)
        return values, removed


def _revision_from_header(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    return normalized


def _expected_revision(body_revision: Optional[str], if_match: Optional[str]) -> Optional[str]:
    header_revision = _revision_from_header(if_match)
    if body_revision is not None and header_revision is not None and body_revision != header_revision:
        raise StorageError("revision_mismatch", "请求正文与 If-Match 的 revision 不一致", status_code=400)
    return body_revision if body_revision is not None else header_revision


def _svg_url(document: PlotDocument) -> str:
    project = quote(document.project, safe="")
    plot = quote(document.plot, safe="")
    return f"/api/projects/{project}/plots/{plot}/render.svg?revision={document.revision}"


def _plot_payload(document: PlotDocument) -> Dict[str, Any]:
    return {
        "project": document.project,
        "plot": document.plot,
        "code": document.code,
        "revision": document.revision,
        "meta": document.contract.meta,
        "schema": document.contract.schema,
        "settings": document.contract.settings,
        "svg_url": _svg_url(document),
    }


def _render_payload(document: PlotDocument, result: RenderResult) -> Dict[str, Any]:
    return result.public_dict(svg_url=_svg_url(document))


async def _read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise StorageError("invalid_request", "Content-Length 无效", status_code=400) from exc
        if declared_length < 0:
            raise StorageError("invalid_request", "Content-Length 无效", status_code=400)
        if declared_length > MAX_IMPORT_BODY_BYTES:
            raise StorageError(
                "import_too_large",
                f"上传内容不能超过 {MAX_IMPORT_BODY_BYTES // (1024 * 1024)} MiB",
                status_code=413,
                extra={"limit": MAX_IMPORT_BODY_BYTES},
            )

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_IMPORT_BODY_BYTES:
            raise StorageError(
                "import_too_large",
                f"上传内容不能超过 {MAX_IMPORT_BODY_BYTES // (1024 * 1024)} MiB",
                status_code=413,
                extra={"limit": MAX_IMPORT_BODY_BYTES},
            )
    return bytes(body)


def create_app(
    *,
    workspace: Optional[Path] = None,
    web_directory: Optional[Path] = None,
    render_timeout: Optional[float] = None,
) -> FastAPI:
    package_root = Path(__file__).resolve().parent.parent
    configured_workspace = workspace or Path(os.environ.get("MATPLOT_STUDIO_WORKSPACE", package_root / "workspace"))
    configured_web = web_directory or package_root / "web"
    if render_timeout is None:
        try:
            render_timeout = float(os.environ.get("MATPLOT_STUDIO_RENDER_TIMEOUT", "15"))
        except ValueError:
            render_timeout = 15.0

    store = ProjectStore(Path(configured_workspace))
    renderer = Renderer(timeout_seconds=max(0.1, float(render_timeout)))
    app = FastAPI(title="Matplot Studio", version="0.1.0")
    app.state.store = store
    app.state.renderer = renderer
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "PUT", "PATCH", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(ContractError)
    def contract_error_handler(_request: Request, exc: ContractError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": exc.as_dict()})

    @app.exception_handler(StorageError)
    def storage_error_handler(_request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.as_dict()})

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True}

    @app.get("/api/projects")
    def projects() -> Dict[str, Any]:
        return {"projects": store.list_projects()}

    @app.post("/api/projects", status_code=201)
    def create_project(item: CreateItem) -> Dict[str, Any]:
        return {"project": store.create_project(item.name, item.description)}

    @app.post("/api/projects/import", status_code=201)
    async def import_project(request: Request) -> Dict[str, Any]:
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        body = await _read_limited_body(request)
        if media_type == "application/zip":
            files = store.files_from_zip(body)
        elif media_type == "application/json":
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise StorageError(
                    "invalid_project_import",
                    f"请求正文不是有效的 UTF-8 JSON：{exc}",
                    status_code=422,
                ) from exc
            if not isinstance(payload, dict) or set(payload) != {"files"}:
                raise StorageError(
                    "invalid_project_import",
                    "JSON 请求必须是仅包含 files 的对象",
                    status_code=422,
                )
            files = store.files_from_json_manifest(payload["files"])
        else:
            raise StorageError(
                "unsupported_media_type",
                "项目导入仅支持 application/zip 或 application/json",
                status_code=415,
            )
        return {"project": store.import_project(files)}

    @app.delete("/api/projects/{project}")
    def delete_project(project: str) -> Dict[str, Any]:
        return {"deleted": store.delete_project(project)}

    @app.post("/api/projects/{project}/plots/import", status_code=201)
    async def import_plots(project: str, request: Request) -> Dict[str, Any]:
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        if media_type != "application/json":
            raise StorageError(
                "unsupported_media_type",
                "图表导入仅支持 application/json",
                status_code=415,
            )
        body = await _read_limited_body(request)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StorageError(
                "invalid_plot_import",
                f"请求正文不是有效的 UTF-8 JSON：{exc}",
                status_code=422,
            ) from exc
        if not isinstance(payload, dict) or set(payload) != {"files"}:
            raise StorageError(
                "invalid_plot_import",
                "JSON 请求必须是仅包含 files 的对象",
                status_code=422,
            )
        files = store.plot_files_from_json_manifest(payload["files"])
        return {"plots": store.import_plots(project, files)}

    @app.post("/api/projects/{project}/plots", status_code=201)
    def create_plot(project: str, item: CreateItem) -> Dict[str, Any]:
        document = store.create_plot(project, item.name, item.description)
        render_result = renderer.render(document.path, document.code, force=True)
        result = _plot_payload(document)
        result["render"] = _render_payload(document, render_result)
        return result

    @app.get("/api/projects/{project}/plots/{plot}")
    def get_plot(project: str, plot: str) -> Dict[str, Any]:
        return _plot_payload(store.read_plot(project, plot))

    @app.delete("/api/projects/{project}/plots/{plot}")
    def delete_plot(project: str, plot: str) -> Dict[str, Any]:
        return {"deleted": store.delete_plot(project, plot)}

    def save_code_impl(
        project: str,
        plot: str,
        update: CodeUpdate,
        if_match: Optional[str],
    ) -> Dict[str, Any]:
        expected = _expected_revision(update.revision, if_match)
        document = store.write_plot(project, plot, update.code, expected)
        render_result = renderer.render(document.path, document.code, force=True)
        result = _plot_payload(document)
        result["render"] = _render_payload(document, render_result)
        return result

    @app.put("/api/projects/{project}/plots/{plot}/code")
    def save_code(
        project: str,
        plot: str,
        update: CodeUpdate,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
    ) -> Dict[str, Any]:
        return save_code_impl(project, plot, update, if_match)

    @app.put("/api/projects/{project}/plots/{plot}", include_in_schema=False)
    def save_code_alias(
        project: str,
        plot: str,
        update: CodeUpdate,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
    ) -> Dict[str, Any]:
        return save_code_impl(project, plot, update, if_match)

    @app.patch("/api/projects/{project}/plots/{plot}/settings")
    def patch_settings(
        project: str,
        plot: str,
        patch: SettingsPatch,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
    ) -> Dict[str, Any]:
        expected = _expected_revision(patch.revision, if_match)
        current = store.read_plot(project, plot)
        if expected is not None and expected != current.revision:
            raise StorageError(
                "revision_conflict",
                "代码已被其他编辑更新，请重新载入后再保存",
                status_code=409,
                extra={"current_revision": current.revision},
            )
        set_values, unset_paths = patch.normalized()
        updated_code, _settings = apply_settings_patch(
            current.code,
            set_values=set_values,
            unset_paths=unset_paths,
        )
        document = store.write_plot(project, plot, updated_code, current.revision)
        render_result = renderer.render(document.path, document.code, force=True)
        result = _plot_payload(document)
        result["render"] = _render_payload(document, render_result)
        return result

    @app.post("/api/projects/{project}/plots/{plot}/render")
    def render_plot(project: str, plot: str, force: bool = Query(default=True)) -> JSONResponse:
        document = store.read_plot(project, plot)
        render_result = renderer.render(document.path, document.code, force=force)
        status_code = 200 if render_result.ok else 422
        return JSONResponse(status_code=status_code, content=_render_payload(document, render_result))

    @app.get("/api/projects/{project}/plots/{plot}/render.svg")
    def render_svg(project: str, plot: str, revision: Optional[str] = Query(default=None)) -> Response:
        document = store.read_plot(project, plot)
        if revision is not None and revision != document.revision:
            raise StorageError(
                "revision_conflict",
                "请求的渲染版本已经过期",
                status_code=409,
                extra={"current_revision": document.revision},
            )
        result = renderer.render(document.path, document.code)
        if not result.ok or result.svg is None:
            return JSONResponse(status_code=422, content={"error": result.public_dict()})
        return Response(
            content=result.svg,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "no-store",
                "ETag": f'"{document.revision}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/projects/{project}/plots/{plot}/export/image")
    def export_image(
        project: str,
        plot: str,
        format: Literal["png", "svg", "pdf"] = Query(default="png"),
        dpi: Annotated[Optional[int], Query(ge=36, le=600)] = None,
    ) -> Response:
        if dpi is not None:
            if isinstance(dpi, bool) or not isinstance(dpi, int) or not 36 <= dpi <= 600:
                raise StorageError(
                    "invalid_export_dpi",
                    "PNG 导出 DPI 必须是 36 到 600 之间的整数",
                    status_code=422,
                    extra={"dpi": dpi},
                )
            if format != "png":
                raise StorageError(
                    "invalid_export_dpi",
                    "DPI 参数仅适用于 PNG 图片导出",
                    status_code=422,
                    extra={"format": format},
                )
        document = store.read_plot(project, plot)
        result = renderer.export_image(document.path, document.code, format, dpi=dpi)
        if not result.ok or result.content is None:
            return JSONResponse(status_code=422, content={"error": result.public_dict()})
        media_types = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}
        return Response(
            content=result.content,
            media_type=media_types[format],
            headers={
                "Content-Disposition": f'attachment; filename="{document.plot}.{format}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/projects/{project}/plots/{plot}/export/data")
    def export_data(
        project: str,
        plot: str,
        format: Literal["json", "csv"] = Query(default="json"),
    ) -> Response:
        document = store.read_plot(project, plot)
        export_policy = document.contract.meta.get("data_export")
        if isinstance(export_policy, dict) and export_policy.get(format) is False:
            note = export_policy.get("note")
            message = str(note) if isinstance(note, str) and note.strip() else f"此图表不支持 {format.upper()} 数据导出"
            raise StorageError("data_export_disabled", message, status_code=422, extra={"format": format})
        result = renderer.export_data(document.path, document.code, format)
        if not result.ok or result.content is None:
            return JSONResponse(status_code=422, content={"error": result.public_dict()})
        media_types = {"json": "application/json", "csv": "text/csv; charset=utf-8"}
        return Response(
            content=result.content,
            media_type=media_types[format],
            headers={
                "Content-Disposition": f'attachment; filename="{document.plot}-data.{format}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    app.mount("/", StaticFiles(directory=str(configured_web), html=True, check_dir=False), name="web")
    return app


app = create_app()
