from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

import pymupdf
from pydantic import ValidationError

from matplot_studio.app import create_app
from matplot_studio.composition import Composition, CompositionStore, render_composition
from matplot_studio.rendering import Renderer, RenderResult
from matplot_studio.storage import ProjectStore, StorageError


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name))
        self.project = self.store.create_project("Paper")["id"]
        self.plot = self.store.create_plot(self.project, "Panel")
        self.saved = CompositionStore(self.store)
        self.layout = Composition(name="Figure 1", panels=[
            {"plot": self.plot.plot, "row": 1, "column": 1, "colspan": 2},
            {"plot": self.plot.plot, "row": 2, "column": 1},
        ])

    def test_save_reopen_update_conflict_and_delete(self):
        item = self.saved.save(self.project, self.layout)
        reopened = CompositionStore(ProjectStore(Path(self.temp.name))).read(self.project, item["id"])
        self.assertEqual(reopened, item)
        updated = self.saved.save(self.project, self.layout.model_copy(update={"name": "Figure 2"}), item["id"], item["revision"])
        with self.assertRaises(StorageError) as conflict:
            self.saved.save(self.project, self.layout, item["id"], item["revision"])
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(len(self.saved.list(self.project)), 1)
        with self.assertRaises(StorageError):
            self.saved.delete(self.project, item["id"], item["revision"])
        self.saved.delete(self.project, item["id"], updated["revision"])
        self.assertEqual(self.saved.list(self.project), [])
        self.assertTrue(self.plot.path.exists())

    def test_rejects_overlap_overflow_nonfinite_and_unusable_dimensions(self):
        cases = [
            {"panels": [{"plot": self.plot.plot, "row": 1, "column": 1}] * 2},
            {"panels": [{"plot": self.plot.plot, "row": 2, "column": 2, "colspan": 2}]},
            {"width_mm": float("nan")}, {"width_mm": float("inf")},
            {"margin_mm": 40, "width_mm": 85}, {"gap_mm": 40, "height_mm": 30},
            {"rows": 1.5}, {"name": " "}, {"panels": []},
        ]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Composition.model_validate({**self.layout.model_dump(), **change})

    def test_path_and_missing_source_protection(self):
        with self.assertRaises(StorageError):
            self.saved.read(self.project, "../outside")
        item = self.saved.save(self.project, self.layout)
        self.store.delete_plot(self.project, self.plot.plot)
        # Keep the saved layout editable even when a referenced plot is removed.
        self.assertEqual(self.saved.read(self.project, item["id"]), item)
        with self.assertRaises(StorageError) as missing:
            render_composition(self.store, Mock(), self.project, self.layout)
        self.assertEqual(missing.exception.code, "plot_not_found")

    def test_render_failure_and_pixel_budget(self):
        renderer = Mock()
        renderer.export_image.return_value = RenderResult(False, "revision", 1, message="boom")
        with self.assertRaises(StorageError) as failed:
            render_composition(self.store, renderer, self.project, self.layout)
        self.assertIn("boom", failed.exception.message)
        huge = self.layout.model_copy(update={"width_mm": 400, "height_mm": 400})
        with self.assertRaises(StorageError) as failed:
            render_composition(self.store, renderer, self.project, huge, "png", 600)
        self.assertEqual(failed.exception.code, "image_too_large")

    def test_vector_exports_labels_dimensions_and_source_refresh(self):
        renderer = Renderer(timeout_seconds=30)
        original_source = self.plot.path.read_text()
        pdf = render_composition(self.store, renderer, self.project, self.layout, "pdf")
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            page = doc[0]
            self.assertAlmostEqual(page.rect.width, 180 * 72 / 25.4, places=3)
            self.assertAlmostEqual(page.rect.height, 140 * 72 / 25.4, places=3)
            self.assertIn("a", page.get_text())
            self.assertIn("b", page.get_text())
            self.assertGreater(len(page.get_drawings()), 10)
            self.assertFalse(page.get_images(), "Vector panels must not be rasterized")
        svg = render_composition(self.store, renderer, self.project, self.layout, "svg")
        self.assertTrue(ET.fromstring(svg).tag.endswith("svg"))
        self.assertNotIn(b"<image", svg)
        png = render_composition(self.store, renderer, self.project, self.layout, "png", 150)
        pix = pymupdf.Pixmap(png)
        self.assertAlmostEqual(pix.width, 180 / 25.4 * 150, delta=1)
        self.assertAlmostEqual(pix.height, 140 / 25.4 * 150, delta=1)
        self.assertEqual(pix.xres, 150)
        # Rendering must use the current source, even if the saved layout is unchanged.
        self.plot.path.write_text(original_source.replace("return fig", 'fig.text(0.3, 0.5, "UPDATED_SOURCE")\n    return fig'))
        updated = render_composition(self.store, renderer, self.project, self.layout, "pdf")
        with pymupdf.open(stream=updated, filetype="pdf") as doc:
            self.assertIn("UPDATED_SOURCE", doc[0].get_text())

    def test_export_route_headers_and_revision(self):
        app = create_app(workspace=self.store.workspace)
        endpoints = {route.name: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
        item = endpoints["create_composition"](self.project, self.layout)
        self.assertEqual(endpoints["list_compositions"](self.project)["compositions"], [item])
        with self.assertRaises(StorageError):
            endpoints["export_composition"](self.project, item["id"], "pdf", 300, "old")
        response = endpoints["export_composition"](self.project, item["id"], "pdf", 300, item["revision"])
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertTrue(response.body.startswith(b"%PDF"))

    def test_labels_overlay_the_visible_image_without_changing_its_geometry(self):
        renderer = Mock()
        with pymupdf.open() as source:
            page = source.new_page(width=200, height=100)
            page.draw_rect(page.rect, fill=(0.6, 0.8, 1), color=None)
            renderer.export_image.return_value = RenderResult(True, "source", 0, svg=source.tobytes())
        layout = Composition(name="Overlay", width_mm=100, height_mm=100, rows=1, columns=1,
                             panels=[{"plot": self.plot.plot, "row": 1, "column": 1}])
        rectangles = []
        for labels in ["none", "lower", "upper", "parentheses", "custom"]:
            settings = layout.model_dump()
            settings["labels"] = labels
            settings["panels"][0]["label"] = "Panel A"
            configured = Composition.model_validate(settings)
            result = render_composition(self.store, renderer, self.project, configured, "pdf")
            with pymupdf.open(stream=result, filetype="pdf") as doc:
                page = doc[0]
                rect = page.get_drawings()[0]["rect"]
                rectangles.append(tuple(rect))
                if labels != "none":
                    label_rect = page.search_for(configured.panel_label(0))[0]
                    self.assertTrue(rect.contains(label_rect), (rect, label_rect))
                    self.assertLess(label_rect.y0 - rect.y0, 3)
                    # Black glyph pixels on an opaque blue panel prove the label is on top.
                    pix = page.get_pixmap(clip=label_rect, matrix=pymupdf.Matrix(2, 2))
                    self.assertTrue(any(max(pix.samples[i:i + 3]) < 80 for i in range(0, len(pix.samples), 3)))
        for rect in rectangles[1:]:
            for actual, expected in zip(rect, rectangles[0]):
                self.assertAlmostEqual(actual, expected, places=4)

    def test_small_cells_do_not_reserve_space_for_labels(self):
        layout = self.layout.model_dump()
        layout.update(width_mm=30, height_mm=30, margin_mm=0, gap_mm=0, rows=3, columns=3, label_size=24)
        self.assertEqual(Composition.model_validate(layout).height_mm, 30)


if __name__ == "__main__":
    unittest.main()
