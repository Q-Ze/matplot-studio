"""Project-owned raster illustrations for figure composition."""

from __future__ import annotations

import io
import json
import os
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import MAX_IMPORT_BODY_BYTES, StorageError


MAX_IMAGE_PIXELS = 25_000_000


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
            png = self.store._inside_workspace(directory / "image.png")
            meta = self.store._inside_workspace(directory / "image.json")
            if not png.is_file() or not meta.is_file():
                raise StorageError("image_not_found", "导入的示意图不存在，请重新选择图片", status_code=404)
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
                if not isinstance(info, dict) or not isinstance(info.get("name"), str):
                    raise ValueError("图片信息格式无效")
                return {**info, "id": image}, png.read_bytes() if include_content else None
            except (OSError, ValueError) as exc:
                raise StorageError("invalid_image", f"无法读取示意图：{exc}", status_code=422) from exc

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
        try:
            with Image.open(io.BytesIO(content)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP", "TIFF"}:
                    raise ValueError("请选择 PNG、JPG、WebP 或 TIFF 图片")
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
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
            raise StorageError("invalid_image", f"图片导入失败：{exc}", status_code=422) from exc
        if len(encoded) > MAX_IMPORT_BODY_BYTES:
            raise StorageError("image_too_large", "解码后的图片过大，请先缩小图片", status_code=413)
        info = {"id": uuid.uuid4().hex, "name": name, "width": width, "height": height}
        with self.store._lock:
            root = self._directory(project)
            root.mkdir(exist_ok=True)
            destination = self._path(project, info["id"])
            with tempfile.TemporaryDirectory(prefix=".image-import-", dir=root) as temporary:
                staging = Path(temporary) / "asset"
                staging.mkdir()
                (staging / "image.png").write_bytes(encoded)
                (staging / "image.json").write_text(json.dumps(info, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(staging, destination)
        return info
