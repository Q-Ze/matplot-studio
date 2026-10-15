from __future__ import annotations

import asyncio
import io
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


if __name__ == "__main__":
    unittest.main()
