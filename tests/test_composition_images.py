from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pymupdf
from PIL import Image
from pydantic import ValidationError

from matplot_studio.app import create_app
from matplot_studio.composition import Composition, CompositionStore, Panel, render_composition
from matplot_studio.composition_images import CompositionImages
from matplot_studio.rendering import Renderer
from matplot_studio.storage import ProjectStore, StorageError


def image_bytes(format="PNG"):
    mode = "RGB" if format == "JPEG" else "RGBA"
    image = Image.new(mode, (120, 80), (200, 50, 30) if mode == "RGB" else (200, 50, 30, 90))
    stream = io.BytesIO()
    image.save(stream, format=format)
    return stream.getvalue()


SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 80">
<rect x="10" y="10" width="220" height="60" fill="#3388cc" fill-opacity="0.5"/>
<path d="M 30 40 L 200 40 L 180 20" fill="none" stroke="black"/>
</svg>'''


def pdf_bytes(pages=1, encrypted=False, rotation=0, cropped=False, annotated=False):
    with pymupdf.open() as document:
        for _ in range(pages):
            page = document.new_page(width=240, height=80)
            page.draw_rect(pymupdf.Rect(10, 10, 230, 70), fill=(0.2, 0.5, 0.8))
            page.insert_text((30, 45), "Schematic")
            if annotated:
                page.add_ink_annot([[(40, 50), (80, 20), (120, 50)]])
            if cropped:
                page.set_cropbox(pymupdf.Rect(5, 5, 235, 75))
            page.set_rotation(rotation)
        return document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256 if encrypted else pymupdf.PDF_ENCRYPT_NONE,
                                owner_pw="owner" if encrypted else None, user_pw="secret" if encrypted else None)


class CompositionImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name))
        self.project = self.store.create_project("Paper")["id"]
        self.images = CompositionImages(self.store)

    def test_formats_alpha_persistence_and_duplicate_names(self):
        for format in ["PNG", "JPEG", "WEBP", "TIFF"]:
            with self.subTest(format=format):
                imported = self.images.import_image(self.project, f"Sketch.{format.lower()}", image_bytes(format))
                info, content = CompositionImages(ProjectStore(Path(self.temp.name))).read(self.project, imported["id"])
                self.assertEqual(info, imported)
                with Image.open(io.BytesIO(content)) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (120, 80))
                    if format != "JPEG":
                        self.assertEqual(image.getpixel((0, 0))[3], 90)
        first = self.images.import_image(self.project, "same.png", image_bytes())
        second = self.images.import_image(self.project, "same.png", image_bytes())
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.images.list(self.project)), 6)

    def test_camera_orientation_is_applied(self):
        image = Image.new("RGB", (80, 120), "white")
        exif = Image.Exif()
        exif[274] = 6
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        imported = self.images.import_image(self.project, "photo.jpg", buffer.getvalue())
        self.assertEqual((imported["width"], imported["height"]), (120, 80))

    def test_svg_pdf_vector_exports_preview_and_persistence(self):
        renderer = Mock()
        for format, content in [("svg", SVG), ("pdf", pdf_bytes())]:
            with self.subTest(format=format):
                info = self.images.import_image(self.project, f"Sketch.{format}", content)
                reopened = CompositionImages(ProjectStore(self.store.workspace))
                metadata, stored = reopened.read(self.project, info["id"])
                self.assertEqual(metadata, info)
                self.assertEqual((info["width"], info["height"]), (240, 80))
                self.assertEqual(info["format"], format)
                self.assertTrue(stored.startswith(b"%PDF"))
                with Image.open(io.BytesIO(reopened.preview(self.project, info["id"]))) as preview:
                    self.assertAlmostEqual(preview.width / preview.height, 3)
                    self.assertEqual(preview.mode, "RGBA")
                    if format == "svg":
                        self.assertEqual(preview.getpixel((0, 0))[3], 0)
                layout = Composition(name="Vector", rows=1, columns=1, labels="none", panels=[
                    {"image": info["id"], "row": 1, "column": 1},
                ])
                saved = CompositionStore(self.store).save(self.project, layout)
                self.assertEqual(CompositionStore(self.store).read(self.project, saved["id"])["layout"], layout.model_dump())
                exported = render_composition(self.store, renderer, self.project, layout, "pdf")
                with pymupdf.open(stream=exported, filetype="pdf") as document:
                    self.assertGreaterEqual(len(document[0].get_drawings()), 1)
                    self.assertEqual(document[0].get_images(), [])
                    if format == "pdf":
                        self.assertIn("Schematic", document[0].get_text())
                svg = render_composition(self.store, renderer, self.project, layout, "svg")
                self.assertIn(b"<path", svg)
                self.assertNotIn(b"<image", svg)
                self.assertTrue(render_composition(self.store, renderer, self.project, layout, "png", 72).startswith(b"\x89PNG"))
        renderer.export_image.assert_not_called()

    def test_pdf_rotations_crop_and_ink_annotations_are_preserved(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                content = pdf_bytes(rotation=rotation, cropped=True, annotated=True)
                info = self.images.import_image(self.project, "Sketch.pdf", content)
                _, stored = self.images.read(self.project, info["id"])
                with pymupdf.open(stream=content, filetype="pdf") as original, pymupdf.open(stream=stored, filetype="pdf") as imported:
                    self.assertEqual(original[0].rect, imported[0].rect)
                    # Compare visible output, catching rotation / crop clipping and lost annotations.
                    self.assertEqual(original[0].get_pixmap(alpha=True).samples, imported[0].get_pixmap(alpha=True).samples)
                    self.assertIn("Schematic", imported[0].get_text())

    def test_invalid_vectors_are_actionable_and_atomic(self):
        cases = [
            ("multi.pdf", pdf_bytes(pages=2), "单页"),
            ("locked.pdf", pdf_bytes(encrypted=True), "加密"),
            ("broken.pdf", b"%PDF-broken", "导入失败"),
            ("broken.svg", b"<svg", "导入失败"),
            ("external.svg", SVG.replace(b"</svg>", b'<image href="https://example.com/img.png"/></svg>'), "外部"),
            ("script.svg", SVG.replace(b"</svg>", b'<script>alert(1)</script></svg>'), "静态"),
            ("entity.svg", b'<!DOCTYPE svg [<!ENTITY a "test">]>' + SVG, "实体"),
            ("style.svg", SVG.replace(b"</svg>", b'<style>@import "https://example.com/style.css";</style></svg>'), "外部"),
        ]
        for name, content, message in cases:
            with self.subTest(name=name), self.assertRaises(StorageError) as error:
                self.images.import_image(self.project, name, content)
            self.assertEqual(error.exception.status_code, 422)
            self.assertIn(message, str(error.exception))
        self.assertEqual(self.images.list(self.project), [])

    def test_legacy_png_metadata_remains_usable(self):
        info = self.images.import_image(self.project, "old.png", image_bytes())
        del info["format"], info["unit"]
        path = self.store.project_path(self.project) / "composition-images" / info["id"] / "image.json"
        path.write_text(json.dumps(info))
        self.assertEqual(self.images.read(self.project, info["id"])[0], info)
        self.assertEqual(self.images.preview(self.project, info["id"]), image_bytes())
        layout = Composition(name="Old", panels=[{"image": info["id"], "row": 1, "column": 1}])
        with pymupdf.open(stream=render_composition(self.store, Mock(), self.project, layout, "pdf"), filetype="pdf") as document:
            self.assertEqual(len(document[0].get_images()), 1)

    def test_invalid_content_limits_and_paths_leave_no_partial_import(self):
        for payload in [b"not an image", b'<svg xmlns="http://www.w3.org/2000/svg"/>', image_bytes("GIF")]:
            with self.assertRaises(StorageError):
                self.images.import_image(self.project, "test.png", payload)
        with patch("matplot_studio.composition_images.MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(StorageError):
                self.images.import_image(self.project, "large.png", image_bytes())
        with patch("matplot_studio.composition_images.MAX_IMPORT_BODY_BYTES", 1):
            with self.assertRaises(StorageError) as error:
                self.images.import_image(self.project, "large.png", image_bytes())
            self.assertEqual(error.exception.status_code, 413)
        with self.assertRaises(StorageError):
            self.images.read(self.project, "../outside")
        self.assertEqual(self.images.list(self.project), [])

    def test_exactly_one_source_and_old_layout_compatibility(self):
        self.assertEqual(Panel(plot="plot", row=1, column=1).plot, "plot")
        self.assertEqual(Panel(image="image", row=1, column=1).image, "image")
        for source in [{}, {"plot": "plot", "image": "image"}]:
            with self.assertRaises(ValidationError):
                Panel(**source, row=1, column=1)

    def test_mixed_vector_and_raster_exports_and_reopen(self):
        plot = self.store.create_plot(self.project, "Chart")
        imported = self.images.import_image(self.project, "Sketch.png", image_bytes())
        layout = Composition(name="Mixed figure", rows=1, columns=2, panels=[
            {"plot": plot.plot, "row": 1, "column": 1},
            {"image": imported["id"], "row": 1, "column": 2},
        ])
        saved = CompositionStore(self.store).save(self.project, layout)
        reopened = CompositionStore(self.store).read(self.project, saved["id"])
        self.assertEqual(reopened["layout"]["panels"][1]["image"], imported["id"])
        renderer = Renderer(timeout_seconds=30)
        pdf = render_composition(self.store, renderer, self.project, layout, "pdf")
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            page = document[0]
            self.assertGreater(len(page.get_drawings()), 10)
            self.assertTrue(page.get_images()[0][1], "Transparent image must retain its alpha mask")
            self.assertIn("b", page.get_text())
        svg = render_composition(self.store, renderer, self.project, layout, "svg")
        self.assertIn(b"<image", svg)
        png = render_composition(self.store, renderer, self.project, layout, "png", 150)
        self.assertTrue(png.startswith(b"\x89PNG"))
        # Images are reusable project assets; removing a layout never removes the image.
        CompositionStore(self.store).delete(self.project, saved["id"], saved["revision"])
        self.assertEqual(self.images.read(self.project, imported["id"])[0], imported)

    def test_image_only_layout_and_missing_asset(self):
        imported = self.images.import_image(self.project, "Sketch.png", image_bytes())
        layout = Composition(name="Sketch", panels=[{"image": imported["id"], "row": 1, "column": 1}])
        renderer = Mock()
        self.assertTrue(render_composition(self.store, renderer, self.project, layout, "pdf").startswith(b"%PDF"))
        renderer.export_image.assert_not_called()
        other = self.store.create_project("Other")["id"]
        with self.assertRaises(StorageError) as missing:
            CompositionStore(self.store).save(other, layout)
        self.assertEqual(missing.exception.status_code, 404)

    def test_upload_and_image_routes(self):
        class Request:
            headers = {}

            async def stream(self):
                yield image_bytes()

        app = create_app(workspace=self.store.workspace)
        endpoints = {route.name: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
        imported = asyncio.run(endpoints["import_composition_image"](self.project, Request(), "Sketch.png"))
        self.assertEqual(endpoints["list_composition_images"](self.project)["images"], [imported])
        response = endpoints["get_composition_image"](self.project, imported["id"])
        self.assertEqual(response.media_type, "image/png")
        self.assertTrue(response.body.startswith(b"\x89PNG"))
        for name, payload in [("Sketch.svg", SVG), ("Sketch.pdf", pdf_bytes())]:
            class VectorRequest:
                headers = {}

                async def stream(self):
                    yield payload

            imported = asyncio.run(endpoints["import_composition_image"](self.project, VectorRequest(), name))
            response = endpoints["get_composition_image"](self.project, imported["id"])
            self.assertEqual(response.media_type, "image/png")
            self.assertTrue(response.body.startswith(b"\x89PNG"))

    def test_library_references_block_deletion_until_layout_is_saved_without_asset(self):
        image = self.images.import_image(self.project,"used.svg",SVG)
        other = self.images.import_image(self.project,"unused.pdf",pdf_bytes())
        layouts = CompositionStore(self.store)
        first = layouts.save(self.project,Composition(name="Figure 1",panels=[
            {"image":image["id"],"row":1,"column":1}, {"image":image["id"],"row":1,"column":2}]))
        second = layouts.save(self.project,Composition(name="Figure 2",panels=[{"image":image["id"],"row":1,"column":1}]))
        library = {item["id"]:item for item in self.images.library(self.project)}
        self.assertEqual({item["name"] for item in library[image["id"]]["used_by"]},{"Figure 1","Figure 2"})
        self.assertEqual(len(library[image["id"]]["used_by"]),2)
        self.assertEqual(library[other["id"]]["used_by"],[])
        with self.assertRaises(StorageError) as blocked:
            self.images.delete(self.project,image["id"])
        self.assertEqual(blocked.exception.code,"image_in_use")
        self.assertEqual(blocked.exception.status_code,409)
        self.assertTrue(self.images.preview(self.project,image["id"]).startswith(b"\x89PNG"))
        replacement = Composition(name="Figure 1",panels=[{"image":other["id"],"row":1,"column":1}])
        layouts.save(self.project,replacement,first["id"],first["revision"])
        layouts.delete(self.project,second["id"],second["revision"])
        self.assertEqual(self.images.delete(self.project,image["id"]),{"id":image["id"],"name":"used.svg"})
        self.assertEqual([item["id"] for item in self.images.list(self.project)],[other["id"]])
        with self.assertRaises(StorageError):
            layouts.save(self.project,Composition(name="Stale draft",panels=[{"image":image["id"],"row":1,"column":1}]))

    def test_asset_deletion_routes_and_project_boundaries(self):
        app = create_app(workspace=self.store.workspace)
        endpoints = {route.name:route.endpoint for route in app.routes if hasattr(route,"endpoint")}
        image = self.images.import_image(self.project,"unused.png",image_bytes())
        other = self.store.create_project("Other")["id"]
        with self.assertRaises(StorageError):
            endpoints["delete_composition_image"](other,image["id"])
        with self.assertRaises(StorageError):
            endpoints["delete_composition_image"](self.project,"../outside")
        self.assertEqual(endpoints["composition_image_library"](self.project)["images"],[{**image,"used_by":[]}])
        result = endpoints["delete_composition_image"](self.project,image["id"])
        self.assertEqual(result["deleted"]["id"],image["id"])
        self.assertEqual(endpoints["composition_image_library"](self.project)["images"],[])
        for reader in [self.images.read,self.images.preview,self.images.delete]:
            with self.assertRaises(StorageError) as missing:
                reader(self.project,image["id"])
            self.assertEqual(missing.exception.status_code,404)

    def test_delete_refuses_to_guess_when_a_saved_layout_is_corrupt(self):
        image = self.images.import_image(self.project,"keep.png",image_bytes())
        directory = self.store.project_path(self.project) / "compositions"
        directory.mkdir()
        (directory / "broken.json").write_text("not json")
        with self.assertRaises(StorageError):
            self.images.delete(self.project,image["id"])
        self.assertEqual(self.images.read(self.project,image["id"])[0],image)


if __name__ == "__main__":
    unittest.main()
