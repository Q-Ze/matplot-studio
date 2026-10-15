"""Project-owned raster and vector illustrations for figure composition."""

from __future__ import annotations

import io
import json
import math
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import MAX_IMPORT_BODY_BYTES, StorageError
from .pdf_support import PDF_LOCK


MAX_IMAGE_PIXELS = 25_000_000


def _svg_content(content):
    """Only pass self-contained, static SVG artwork to MuPDF."""
    if b"<!entity" in content.replace(b"\x00", b"").lower():
        raise ValueError("SVG 不支持 XML 实体，请另存为普通 SVG")
    root = ET.fromstring(content)
    if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
        raise ValueError("文件不是有效的 SVG 图片")
    if not root.get("viewBox") and not (root.get("width") and root.get("height")):
        raise ValueError("SVG 缺少画布尺寸，请设置 width/height 或 viewBox")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script", "foreignobject", "animate", "animatetransform", "animatemotion", "set"}:
            raise ValueError("请将 SVG 导出为静态图片，并将 HTML 内容转换为路径")
        for key, value in element.attrib.items():
            key = key.rsplit("}", 1)[-1].lower()
            if key.startswith("on") or key == "base":
                raise ValueError("SVG 不支持脚本或外部资源，请导出为自包含的 SVG")
            if key == "href" and not (value.startswith("#") or (
                tag == "image" and re.match(r"^data:image/(?:png|jpeg|webp);base64,", value, re.I)
            )):
                raise ValueError("SVG 引用了外部资源，请先嵌入图片并将字体转换为路径")
        styles = " ".join(element.attrib.values()) + " " + (element.text or "")
        if "@import" in styles.lower() or any(
            not target.strip(" \t\r\n\"'").startswith("#")
            for target in re.findall(r"url\s*\((.*?)\)", styles, re.I | re.S)
        ):
            raise ValueError("SVG 引用了外部样式或资源，请导出为自包含的 SVG")
    # Serialization also removes document type declarations / processing instructions.
    return ET.tostring(root, encoding="utf-8")


def _vector_image(content, source_format):
    import pymupdf

    if source_format == "svg":
        content = _svg_content(content)
    with PDF_LOCK, pymupdf.open(stream=content, filetype=source_format) as source:
        if source.needs_pass:
            raise ValueError("PDF 已加密，请先导出未加密的单页 PDF")
        if len(source) != 1:
            raise ValueError("仅支持单页 PDF，请将需要的页面单独导出后导入")
        if source_format == "pdf" and (source[0].first_annot or source[0].first_widget):
            if not hasattr(source, "bake"):
                raise ValueError("此 PDF 含批注，请先将批注合并到页面后导入，或升级 PyMuPDF")
            source.bake()
        rect = source[0].rect
        if not all(math.isfinite(v) and 0 < v <= 14400 for v in (rect.width, rect.height)):
            raise ValueError("矢量图片画布尺寸无效或过大，请调整后重新导入")
        # Convert SVG paths to PDF; PDF pages are copied without links, scripts,
        # attachments or document actions. Never rasterize the stored artwork.
        converted = source.convert_to_pdf() if source_format == "svg" else None
        with pymupdf.open(stream=converted, filetype="pdf") if converted else pymupdf.open() as document:
            if converted is None:
                page = document.new_page(width=rect.width, height=rect.height)
                rotation = source[0].rotation
                source[0].set_rotation(0)
                if source[0].get_contents():
                    page.show_pdf_page(page.rect, source, 0, rotate=-rotation)
            page = document[0]
            encoded = document.tobytes(garbage=4, deflate=True)
            scale = min(2, 1600 / max(page.rect.width, page.rect.height))
            preview = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=True).tobytes("png")
            return encoded, preview, page.rect.width, page.rect.height


class CompositionImages:
    def __init__(self, store):
        self.store = store

    def _directory(self, project):
        root = self.store.project_path(project)
        self.store._load_project_meta(root)
        return self.store._inside_workspace(root / "composition-images")

    def _path(self, project, image):
        self.store._check_name(image, "示意图")
        return self.store._inside_workspace(self._directory(project) / image)

    def read(self, project, image, *, include_content=True):
        with self.store._lock:
            directory = self._path(project, image)
            meta = self.store._inside_workspace(directory / "image.json")
            if not meta.is_file():
                raise StorageError("image_not_found", "导入的示意图不存在，请重新选择图片", status_code=404)
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
                if not isinstance(info, dict) or not isinstance(info.get("name"), str):
                    raise ValueError("图片信息格式无效")
                source = self.store._inside_workspace(directory / ("image.pdf" if info.get("format") in {"svg", "pdf"} else "image.png"))
                if not source.is_file():
                    raise StorageError("image_not_found", "导入的示意图不存在，请重新选择图片", status_code=404)
                return {**info, "id": image}, source.read_bytes() if include_content else None
            except (OSError, ValueError) as exc:
                raise StorageError("invalid_image", f"无法读取示意图：{exc}", status_code=422) from exc

    def preview(self, project, image):
        with self.store._lock:
            info, _ = self.read(project, image, include_content=False)
            filename = "preview.png" if info.get("format") in {"svg", "pdf"} else "image.png"
            try:
                return self.store._inside_workspace(self._path(project, image) / filename).read_bytes()
            except OSError as exc:
                raise StorageError("invalid_image", "无法读取示意图预览，请重新导入", status_code=422) from exc

    def list(self, project):
        with self.store._lock:
            root = self._directory(project)
            if not root.exists():
                return []
            return [self.read(project, entry.name, include_content=False)[0] for entry in sorted(root.iterdir())
                    if entry.is_dir() and not entry.name.startswith(".")]

    def import_image(self, project, filename, content):
        self._directory(project)
        if len(content) > MAX_IMPORT_BODY_BYTES:
            raise StorageError("image_too_large", "图片文件不能超过 20 MiB", status_code=413)
        name = self.store._validate_display_text(filename.replace("\\", "/").rsplit("/", 1)[-1], "图片名称")
        source_format = "png"
        preview = None
        try:
            if content.lstrip().startswith(b"%PDF-"):
                source_format = "pdf"
            elif content.lstrip().startswith(b"<") or Path(name).suffix.lower() == ".svg":
                source_format = "svg"
            if source_format in {"svg", "pdf"}:
                encoded, preview, width, height = _vector_image(content, source_format)
            else:
                encoded, width, height = self._raster_image(content)
        except (RuntimeError, ET.ParseError, UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
            raise StorageError("invalid_image", f"图片导入失败：{exc}", status_code=422) from exc
        if len(encoded) > MAX_IMPORT_BODY_BYTES:
            raise StorageError("image_too_large", "转换后的图片过大，请先简化或缩小图片", status_code=413)
        info = {"id": uuid.uuid4().hex, "name": name, "width": width, "height": height,
                "format": source_format, "unit": "pt" if preview else "px"}
        with self.store._lock:
            root = self._directory(project)
            root.mkdir(exist_ok=True)
            destination = self._path(project, info["id"])
            with tempfile.TemporaryDirectory(prefix=".image-import-", dir=root) as temporary:
                staging = Path(temporary) / "asset"
                staging.mkdir()
                (staging / ("image.pdf" if preview else "image.png")).write_bytes(encoded)
                if preview:
                    (staging / "preview.png").write_bytes(preview)
                (staging / "image.json").write_text(json.dumps(info, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(staging, destination)
        return info

    @staticmethod
    def _raster_image(content):
        with Image.open(io.BytesIO(content)) as original:
            if original.format not in {"PNG", "JPEG", "WEBP", "TIFF"}:
                raise ValueError("请选择 PNG、JPG、WebP、TIFF、SVG 或单页 PDF 图片")
            if original.width * original.height > MAX_IMAGE_PIXELS:
                raise ValueError("图片不能超过 2500 万像素，请先缩小图片")
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("不支持动画或多页图片，请导出为单张图片")
            oriented = ImageOps.exif_transpose(original)
            mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
            pixels = oriented.convert(mode)
            pixels.info.clear()
            buffer = io.BytesIO()
            pixels.save(buffer, format="PNG")
            encoded = buffer.getvalue()
            width, height = pixels.size
            return encoded, width, height
