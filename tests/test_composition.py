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
from matplot_studio.composition_images import CompositionImages
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

    def test_weighted_widths_roundtrip_and_vector_export(self):
        panels = []
        for column, width in enumerate([50, 40, 30], 1):
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="30"><rect width="{width}" height="30" fill="#3388aa"/></svg>'
            image = CompositionImages(self.store).import_image(self.project, f"{column}.svg", svg.encode())
            panels.append({"image": image["id"], "row": 1, "column": column})
        layout = Composition(name="5:4:3", rows=1, columns=3, width_mm=120, height_mm=30,
                             margin_mm=0, gap_mm=0, labels="none", row_width_ratios=[[5,4,3]], panels=panels)
        self.assertEqual([layout.panel_box(panel) for panel in layout.panels],
                         [(0,0,50,30), (50,0,40,30), (90,0,30,30)])
        item = self.saved.save(self.project, layout)
        restored = Composition.model_validate(self.saved.read(self.project, item["id"])["layout"])
        self.assertEqual(restored.row_width_ratios, [[5,4,3]])
        with pymupdf.open(stream=render_composition(self.store, Mock(), self.project, restored, "pdf"), filetype="pdf") as document:
            rectangles = [drawing["rect"] for drawing in document[0].get_drawings()]
            self.assertEqual(len(rectangles), 3)
            for rect, (x, width) in zip(rectangles, [(0,50),(50,40),(90,30)]):
                self.assertAlmostEqual(rect.x0 * 25.4 / 72, x, places=3)
                self.assertAlmostEqual(rect.width * 25.4 / 72, width, places=3)
                self.assertAlmostEqual(rect.height * 25.4 / 72, 30, places=3)
            self.assertFalse(document[0].get_images())
        self.assertIn(b"<path", render_composition(self.store, Mock(), self.project, restored, "svg"))
        self.assertTrue(render_composition(self.store, Mock(), self.project, restored, "png", 72).startswith(b"\x89PNG"))

    def test_ratio_validation_and_cross_row_alignment(self):
        data = dict(name="Ratios", rows=2, columns=3, width_mm=134, margin_mm=4, gap_mm=3,
                    row_width_ratios=[[5,4,3],[6,3,3]],
                    panels=[{"plot": self.plot.plot, "row":1,"column":1,"rowspan":2,"colspan":2}])
        layout = Composition(**data)
        self.assertEqual(layout.column_widths(1), [50,40,30])
        self.assertEqual(layout.column_widths(2), [60,30,30])
        self.assertEqual(layout.panel_box(layout.panels[0])[2], 93)
        for ratios in [[[5,4,3]], [[5,4],[5,4]], [[0,4,3],[6,3,3]], [[float("nan"),4,3],[6,3,3]],
                       [[float("inf"),4,3],[6,3,3]], [[1000,1,1],[6,3,3]], [[5,4,3],[3,4,5]]]:
            with self.subTest(ratios=ratios), self.assertRaises(ValidationError):
                Composition(**{**data,"row_width_ratios":ratios})
        legacy = self.layout.model_dump()
        del legacy["row_width_ratios"]
        restored = Composition.model_validate(legacy)
        self.assertEqual(restored.column_widths(1), [84.5,84.5])

    def test_row_height_ratios_persist_and_export_exact_heights(self):
        panels = []
        for row, height in enumerate([60,30],1):
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="{height}"><rect width="60" height="{height}" fill="#3388aa"/></svg>'
            image = CompositionImages(self.store).import_image(self.project,f"row-{row}.svg",svg.encode())
            panels.append({"image":image["id"],"row":row,"column":1})
        layout = Composition(name="Rows 2:1",width_mm=68,height_mm=101,margin_mm=4,gap_mm=3,
                             rows=2,columns=1,row_height_ratios=[2,1],panels=panels,labels="none")
        self.assertEqual(layout.row_heights(),[60,30])
        self.assertEqual([layout.panel_box(panel) for panel in layout.panels],[(4,4,60,60),(4,67,60,30)])
        saved = self.saved.save(self.project,layout)
        restored = Composition.model_validate(self.saved.read(self.project,saved["id"])["layout"])
        self.assertEqual(restored.row_height_ratios,[2,1])
        with pymupdf.open(stream=render_composition(self.store,Mock(),self.project,restored,"pdf"),filetype="pdf") as document:
            rectangles = [drawing["rect"] for drawing in document[0].get_drawings()]
            self.assertEqual(len(rectangles),2)
            for rect,(y,height) in zip(rectangles,[(4,60),(67,30)]):
                self.assertAlmostEqual(rect.y0*25.4/72,y,places=3)
                self.assertAlmostEqual(rect.height*25.4/72,height,places=3)
            self.assertFalse(document[0].get_images())
        self.assertIn(b"<path",render_composition(self.store,Mock(),self.project,restored,"svg"))
        self.assertTrue(render_composition(self.store,Mock(),self.project,restored,"png",72).startswith(b"\x89PNG"))

    def test_invalid_row_heights_and_legacy_equal_rows(self):
        data = self.layout.model_dump()
        for ratios in ([2], [2,1,3], [0,1], [-1,1], [float("nan"),1], [float("inf"),1], [100,1], [1001,1001]):
            with self.subTest(ratios=ratios), self.assertRaises(ValidationError):
                Composition.model_validate({**data,"row_height_ratios":ratios})
        del data["row_height_ratios"]
        self.assertEqual(Composition.model_validate(data).row_heights(),[64.5,64.5])

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

    def test_label_offsets_avoid_long_ylabel_without_moving_artwork(self):
        renderer = Mock()
        ylabel = "Share of literature"
        with pymupdf.open() as source:
            height = pymupdf.get_text_length(ylabel, fontname="helv", fontsize=12) + 2
            page = source.new_page(width=200, height=height)
            page.draw_rect(page.rect, fill=(0.9,0.95,1), color=None)
            page.insert_text((14,height-1),ylabel,fontsize=12,rotate=90)
            renderer.export_image.return_value = RenderResult(True,"source",0,svg=source.tobytes())
        layout = Composition(name="Label placement",width_mm=180,height_mm=100,rows=1,columns=2,labels="upper",panels=[
            {"plot":self.plot.plot,"row":1,"column":1}, {"plot":self.plot.plot,"row":1,"column":2}])
        def inspect(configured):
            with pymupdf.open(stream=render_composition(self.store,renderer,self.project,configured,"pdf"),filetype="pdf") as document:
                page = document[0]
                spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
                         for line in block["lines"] for span in line["spans"]]
                return ({text:pymupdf.Rect(next(span["bbox"] for span in spans if span["text"]==text)) for text in ["A","B"]},
                        page.search_for(ylabel),[tuple(drawing["rect"]) for drawing in page.get_drawings()])
        before, before_labels, before_artwork = inspect(layout)
        self.assertTrue(before["A"].intersects(before_labels[0]))
        moved = layout.model_dump()
        moved["panels"][0].update(label_offset_x_mm=8,label_offset_y_mm=2)
        configured = Composition.model_validate(moved)
        after, after_labels, after_artwork = inspect(configured)
        self.assertFalse(after["A"].intersects(after_labels[0]))
        self.assertAlmostEqual(after["A"].x0-before["A"].x0,8*72/25.4,places=3)
        self.assertAlmostEqual(after["A"].y0-before["A"].y0,2*72/25.4,places=3)
        self.assertEqual(after["B"],before["B"])
        self.assertEqual(after_labels,before_labels)
        self.assertEqual(after_artwork,before_artwork)
        saved = self.saved.save(self.project,configured)
        self.assertEqual(self.saved.read(self.project,saved["id"])["layout"]["panels"][0]["label_offset_x_mm"],8)
        self.assertIn(b"<path",render_composition(self.store,renderer,self.project,configured,"svg"))
        self.assertTrue(render_composition(self.store,renderer,self.project,configured,"png",72).startswith(b"\x89PNG"))
        moved["panels"][0]["label_offset_x_mm"] = -40
        with self.assertRaises(StorageError) as error:
            render_composition(self.store,renderer,self.project,Composition.model_validate(moved),"pdf")
        self.assertEqual(error.exception.code,"label_out_of_bounds")

    def test_labels_cross_panels_and_stay_above_all_artwork(self):
        renderer = Mock()
        with pymupdf.open() as source:
            page = source.new_page(width=100, height=100)
            page.draw_rect(page.rect, fill=(0.6, 0.8, 1), color=None)
            renderer.export_image.return_value = RenderResult(True, "source", 0, svg=source.tobytes())
        layout = Composition(name="Floating labels", width_mm=60, height_mm=30,
                             margin_mm=0, gap_mm=0, rows=1, columns=2, labels="upper", panels=[
            {"plot": self.plot.plot, "row": 1, "column": 1, "label_offset_x_mm": 32},
            {"plot": self.plot.plot, "row": 1, "column": 2, "label_offset_x_mm": -25}])
        with pymupdf.open(stream=render_composition(self.store, renderer, self.project, layout, "pdf"), filetype="pdf") as doc:
            page = doc[0]
            a, b = page.search_for("A")[0], page.search_for("B")[0]
            self.assertGreater(a.x0, page.rect.width / 2)
            self.assertLess(b.x1, page.rect.width / 2)
            self.assertEqual(len(page.get_drawings()), 2)
            for rect in [a, b]:
                self.assertTrue(page.rect.contains(rect))
                pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(2, 2))
                self.assertTrue(any(max(pix.samples[i:i + 3]) < 80 for i in range(0, len(pix.samples), 3)))
        self.assertIn(b"<path", render_composition(self.store, renderer, self.project, layout, "svg"))
        self.assertTrue(render_composition(self.store, renderer, self.project, layout, "png", 72).startswith(b"\x89PNG"))
        # A custom label may be wider than its source panel when it fits the page.
        layout.labels = "custom"
        layout.panels[0].label = "Wide shared label"
        layout.panels[0].label_offset_x_mm = 0
        layout.label_size = 16
        with pymupdf.open(stream=render_composition(self.store, renderer, self.project, layout, "pdf"), filetype="pdf") as doc:
            rect = doc[0].search_for("Wide shared label")[0]
            self.assertGreater(rect.width, doc[0].rect.width / 2)
            self.assertTrue(doc[0].rect.contains(rect))
        # All four outer edges still protect the full text from being clipped.
        layout.labels = "upper"
        layout.label_size = 10
        for dx, dy in [(-2, 0), (59, 0), (0, -2), (0, 29)]:
            layout.panels[0].label_offset_x_mm = dx
            layout.panels[0].label_offset_y_mm = dy
            with self.subTest(dx=dx, dy=dy), self.assertRaises(StorageError) as error:
                render_composition(self.store, renderer, self.project, layout, "pdf")
            self.assertEqual(error.exception.code, "label_out_of_bounds")
            self.assertIn("整张拼图", str(error.exception))

    def test_unified_labels_align_mixed_artwork_and_move_together(self):
        other = self.store.create_plot(self.project, "Tall panel")
        renderer = Mock()
        sources = []
        for width, height in [(200, 50), (50, 200)]:
            with pymupdf.open() as source:
                page = source.new_page(width=width, height=height)
                page.draw_rect(page.rect, fill=(0.6, 0.8, 1), color=None)
                sources.append(source.tobytes())
        renderer.export_image.side_effect = lambda path, *args, **kwargs: RenderResult(
            True, "source", 0, svg=sources[0 if path == self.plot.path else 1])
        layout = Composition(name="Unified labels", width_mm=120, height_mm=100,
                             rows=2, columns=2, row_height_ratios=[2, 1], labels="upper",
                             label_position_mode="aligned", panels=[
            {"plot": self.plot.plot if i % 2 == 0 else other.plot,
             "row": i // 2 + 1, "column": i % 2 + 1,
             "label_offset_x_mm": -100 if i % 2 else 100,
             "label_offset_y_mm": i * 10} for i in range(4)])
        def inspect():
            with pymupdf.open(stream=render_composition(self.store, renderer, self.project, layout, "pdf"), filetype="pdf") as doc:
                return ([doc[0].search_for(label)[0] for label in "ABCD"],
                        [tuple(drawing["rect"]) for drawing in doc[0].get_drawings()])
        before, artwork = inspect()
        for a, b in [(0, 1), (2, 3)]:
            self.assertAlmostEqual(before[a].y0, before[b].y0, places=4)
        for a, b in [(0, 2), (1, 3)]:
            self.assertAlmostEqual(before[a].x0, before[b].x0, places=4)
        layout.label_offset_x_mm, layout.label_offset_y_mm = 8, 2
        after, moved_artwork = inspect()
        self.assertEqual(artwork, moved_artwork)
        for a, b in zip(before, after):
            self.assertAlmostEqual(b.x0 - a.x0, 8 * 72 / 25.4, places=3)
            self.assertAlmostEqual(b.y0 - a.y0, 2 * 72 / 25.4, places=3)
        layout.panels[1].skip_label = True
        saved = self.saved.save(self.project, layout)
        restored = Composition.model_validate(self.saved.read(self.project, saved["id"])["layout"])
        self.assertEqual(restored.label_position_mode, "aligned")
        self.assertEqual((restored.label_offset_x_mm, restored.label_offset_y_mm), (8, 2))
        self.assertTrue(restored.panels[1].skip_label)
        with pymupdf.open(stream=render_composition(self.store, renderer, self.project, restored, "pdf"), filetype="pdf") as doc:
            self.assertEqual(doc[0].get_text().split(), ["A", "B", "C"])
        self.assertIn(b"<path", render_composition(self.store, renderer, self.project, restored, "svg"))
        self.assertTrue(render_composition(self.store, renderer, self.project, restored, "png", 72).startswith(b"\x89PNG"))
        layout.label_offset_x_mm = -10
        with self.assertRaises(StorageError) as error:
            render_composition(self.store, renderer, self.project, layout, "pdf")
        self.assertEqual(error.exception.code, "label_out_of_bounds")

    def test_label_offsets_validate_and_default_for_old_layouts(self):
        data = self.layout.model_dump()
        for key in ["label_position_mode", "label_offset_x_mm", "label_offset_y_mm"]:
            del data[key]
        self.assertEqual(Composition.model_validate(data).label_position_mode, "legacy")
        for key in ["label_offset_x_mm", "label_offset_y_mm"]:
            for value in [float("nan"), float("inf"), 401, -401]:
                with self.assertRaises(ValidationError):
                    Composition.model_validate({**data, key: value})
        for panel in data["panels"]:
            del panel["label_offset_x_mm"],panel["label_offset_y_mm"]
        self.assertEqual(Composition.model_validate(data).panels[0].label_offset_x_mm,0)
        for value in [-400, -80, 80, 400]:
            data["panels"][0]["label_offset_x_mm"] = value
            self.assertEqual(Composition.model_validate(data).panels[0].label_offset_x_mm, value)
        for value in [float("nan"),float("inf"),401,-401]:
            data["panels"][0]["label_offset_y_mm"] = value
            with self.assertRaises(ValidationError):
                Composition.model_validate(data)

    def test_skip_labels_continue_numbering_in_all_modes(self):
        layout = Composition(name="Shared labels",rows=1,columns=4,panels=[
            {"plot":self.plot.plot,"row":1,"column":column,"label":f"Group {column}"} for column in range(1,5)])
        original_boxes = [layout.panel_box(panel) for panel in layout.panels]
        for skips, expected in [([False,True,False,False],["A","","B","C"]),
                                ([True,False,True,False],["","A","","B"]),
                                ([False,True,True,False],["A","","","B"]),
                                ([True]*4,[""]*4)]:
            for panel,skip in zip(layout.panels,skips): panel.skip_label=skip
            for mode in ["upper","lower","parentheses","custom","none"]:
                layout.labels=mode
                actual = [layout.panel_label(index) for index in range(4)]
                if mode=="upper": self.assertEqual(actual,expected)
                elif mode=="lower": self.assertEqual(actual,[text.lower() for text in expected])
                elif mode=="parentheses": self.assertEqual(actual,[f"({text.lower()})" if text else "" for text in expected])
                elif mode=="custom": self.assertEqual(actual,["" if skip else f"Group {index+1}" for index,skip in enumerate(skips)])
                else: self.assertEqual(actual,[""]*4)
        self.assertEqual([layout.panel_box(panel) for panel in layout.panels],original_boxes)
        for panel in layout.panels: panel.skip_label=False
        layout.labels="upper"
        self.assertEqual([layout.panel_label(index) for index in range(4)],list("ABCD"))
        data = layout.model_dump()
        for panel in data["panels"]: del panel["skip_label"]
        self.assertFalse(Composition.model_validate(data).panels[0].skip_label)

    def test_skipped_labels_persist_and_do_not_remove_artwork(self):
        renderer = Mock()
        with pymupdf.open() as source:
            page=source.new_page(width=100,height=100)
            page.draw_rect(page.rect,fill=(0.8,0.9,1),color=None)
            renderer.export_image.return_value=RenderResult(True,"source",0,svg=source.tobytes())
        layout = Composition(name="Shared A",rows=1,columns=3,labels="upper",panels=[
            {"plot":self.plot.plot,"row":1,"column":column,"skip_label":column==2,
             "label":"Keep me","label_offset_x_mm":-40 if column==2 else 0} for column in range(1,4)])
        saved=self.saved.save(self.project,layout)
        restored=Composition.model_validate(self.saved.read(self.project,saved["id"])["layout"])
        self.assertTrue(restored.panels[1].skip_label)
        self.assertEqual(restored.panels[1].label,"Keep me")
        self.assertEqual(restored.panels[1].label_offset_x_mm,-40)
        with pymupdf.open(stream=render_composition(self.store,renderer,self.project,restored,"pdf"),filetype="pdf") as document:
            self.assertEqual(document[0].get_text().split(),["A","B"])
            self.assertEqual(len(document[0].get_drawings()),3)
        self.assertIn(b"<path",render_composition(self.store,renderer,self.project,restored,"svg"))
        self.assertTrue(render_composition(self.store,renderer,self.project,restored,"png",72).startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
