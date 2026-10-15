"""Saved scientific figure layouts and lossless PDF panel composition."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import ProjectStore, StorageError, revision_for
from .composition_images import CompositionImages


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    plot: Optional[str] = Field(default=None, min_length=1, max_length=128)
    image: Optional[str] = Field(default=None, min_length=1, max_length=128)
    row: int = Field(ge=1, le=6, strict=True)
    column: int = Field(ge=1, le=6, strict=True)
    rowspan: int = Field(default=1, ge=1, le=6, strict=True)
    colspan: int = Field(default=1, ge=1, le=6, strict=True)
    label: str = Field(default="", max_length=16, pattern=r"^[\x20-\x7e]*$")

    @model_validator(mode="after")
    def one_source(self):
        if (self.plot is None) == (self.image is None):
            raise ValueError("每张子图必须且只能选择一个图表或一张导入图片")
        return self


class Composition(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    width_mm: float = Field(default=180, ge=30, le=400)
    height_mm: float = Field(default=140, ge=30, le=400)
    rows: int = Field(default=2, ge=1, le=6, strict=True)
    columns: int = Field(default=2, ge=1, le=6, strict=True)
    margin_mm: float = Field(default=4, ge=0, le=40)
    gap_mm: float = Field(default=3, ge=0, le=40)
    labels: Literal["lower", "upper", "parentheses", "custom", "none"] = "lower"
    label_size: float = Field(default=10, ge=6, le=24)
    source_bounds: Literal["canvas", "tight"] = "tight"
    panels: list[Panel] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def valid_layout(self):
        cell_w = (self.width_mm - 2 * self.margin_mm - (self.columns - 1) * self.gap_mm) / self.columns
        cell_h = (self.height_mm - 2 * self.margin_mm - (self.rows - 1) * self.gap_mm) / self.rows
        if cell_w < 8 or cell_h < 8:
            raise ValueError("画布过小或间距过大：每格需至少保留 8 mm 绘图空间")
        occupied = set()
        for panel in self.panels:
            if panel.row + panel.rowspan - 1 > self.rows or panel.column + panel.colspan - 1 > self.columns:
                raise ValueError("子图位置或跨格范围超出网格")
            cells = {(r, c) for r in range(panel.row, panel.row + panel.rowspan)
                     for c in range(panel.column, panel.column + panel.colspan)}
            if occupied & cells:
                raise ValueError("子图位置重叠，请调整行列或跨格范围")
            occupied.update(cells)
        return self

    def panel_label(self, index):
        if self.labels == "none":
            return ""
        if self.labels == "custom":
            return self.panels[index].label
        letter = chr(ord("A" if self.labels == "upper" else "a") + index)
        return f"({letter})" if self.labels == "parentheses" else letter


class CompositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: Composition
    revision: str = Field(min_length=1)


class CompositionStore:
    def __init__(self, store: ProjectStore):
        self.store = store

    def _directory(self, project):
        root = self.store.project_path(project)
        self.store._load_project_meta(root)
        return self.store._inside_workspace(root / "compositions")

    def _path(self, project, composition):
        self.store._check_name(composition, "拼图")
        return self.store._inside_workspace(self._directory(project) / f"{composition}.json")

    def list(self, project):
        with self.store._lock:
            directory = self._directory(project)
            if not directory.exists():
                return []
            return [self.read(project, path.stem) for path in sorted(directory.glob("*.json"))]

    def read(self, project, composition):
        with self.store._lock:
            path = self._path(project, composition)
            if not path.is_file():
                raise StorageError("composition_not_found", "拼图不存在", status_code=404)
            try:
                source = path.read_text(encoding="utf-8")
                layout = Composition.model_validate_json(source)
            except (OSError, ValueError) as exc:
                raise StorageError("invalid_composition", f"无法读取拼图：{exc}", status_code=422) from exc
            return {"id": composition, "revision": revision_for(source), "layout": layout.model_dump()}

    def save(self, project, layout, composition=None, revision=None):
        with self.store._lock:
            directory = self._directory(project)
            if composition is not None:
                self.check_revision(project, composition, revision)
            for panel in layout.panels:
                if panel.plot:
                    self.store.read_plot(project, panel.plot)
                else:
                    CompositionImages(self.store).read(project, panel.image, include_content=False)
            composition = composition or uuid.uuid4().hex
            directory.mkdir(exist_ok=True)
            path = self._path(project, composition)
            self.store._atomic_write(path, json.dumps(layout.model_dump(), ensure_ascii=False, indent=2) + "\n")
            return self.read(project, composition)

    def check_revision(self, project, composition, revision):
        current = self.read(project, composition)
        if current["revision"] != revision:
            raise StorageError("revision_conflict", "拼图已被更新，请重新打开后再保存", status_code=409)

    def delete(self, project, composition, revision):
        with self.store._lock:
            self.check_revision(project, composition, revision)
            self._path(project, composition).unlink()


# MuPDF must not be used concurrently by FastAPI's worker threads.
_PDF_LOCK = threading.RLock()


def render_composition(store, renderer, project, layout, output_format="svg", dpi=300):
    """Render each trusted source in its usual timed subprocess; retain vector artwork."""
    if output_format == "png" and layout.width_mm * layout.height_mm * (dpi / 25.4) ** 2 > 80_000_000:
        raise StorageError("image_too_large", "PNG 超过 8000 万像素，请减小尺寸或 DPI", status_code=422)
    sources = {}
    images = {}
    for panel in layout.panels:
        if panel.image:
            if panel.image not in images:
                images[panel.image] = CompositionImages(store).read(project, panel.image)[1]
            continue
        if panel.plot in sources:
            continue
        document = store.read_plot(project, panel.plot)
        result = renderer.export_image(document.path, document.code, "pdf", bounds=layout.source_bounds)
        if not result.ok:
            raise StorageError("panel_render_failed", f"子图 {panel.plot} 渲染失败：{result.message}",
                               status_code=422, extra={"render": result.public_dict()})
        sources[panel.plot] = result.content

    import pymupdf

    pt = 72 / 25.4
    width, height = layout.width_mm * pt, layout.height_mm * pt
    margin, gap = layout.margin_mm * pt, layout.gap_mm * pt
    cell_w = (width - margin * 2 - gap * (layout.columns - 1)) / layout.columns
    cell_h = (height - margin * 2 - gap * (layout.rows - 1)) / layout.rows
    with _PDF_LOCK, pymupdf.open() as output:
        page = output.new_page(width=width, height=height)
        for index, panel in enumerate(layout.panels):
            x = margin + (panel.column - 1) * (cell_w + gap)
            y = margin + (panel.row - 1) * (cell_h + gap)
            w = cell_w * panel.colspan + gap * (panel.colspan - 1)
            h = cell_h * panel.rowspan + gap * (panel.rowspan - 1)
            label = layout.panel_label(index)
            if panel.image:
                pixmap = pymupdf.Pixmap(images[panel.image])
                scale = min(w / pixmap.width, h / pixmap.height)
                image_w, image_h = pixmap.width * scale, pixmap.height * scale
                image_x, image_y = x + (w - image_w) / 2, y + (h - image_h) / 2
                page.insert_image(pymupdf.Rect(image_x, image_y, image_x + image_w, image_y + image_h),
                                  stream=images[panel.image])
            else:
                with pymupdf.open(stream=sources[panel.plot], filetype="pdf") as source:
                    # Match the visible image rectangle, including contain-mode letterboxing.
                    scale = min(w / source[0].rect.width, h / source[0].rect.height)
                    image_w, image_h = source[0].rect.width * scale, source[0].rect.height * scale
                    image_x, image_y = x + (w - image_w) / 2, y + (h - image_h) / 2
                    if source[0].get_contents():
                        page.show_pdf_page(pymupdf.Rect(x, y, x + w, y + h), source, 0,
                                           keep_proportion=True)
            if label:
                inset = pt  # 1 mm inside the visible image, without reserving layout space.
                if pymupdf.get_text_length(label, fontname="hebo", fontsize=layout.label_size) > image_w - 2 * inset:
                    raise StorageError("label_too_wide", "自定义标注超出子图宽度，请缩短标注", status_code=422)
                page.insert_text((image_x + inset, image_y + inset + layout.label_size), label,
                                 fontsize=layout.label_size, fontname="hebo", overlay=True)
        if output_format == "pdf":
            return output.tobytes(garbage=4, deflate=True)
        if output_format == "svg":
            return page.get_svg_image(text_as_path=True).encode("utf-8")
        return page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")
