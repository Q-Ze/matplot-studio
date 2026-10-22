import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matplot_studio.app import PlotRename, ProjectRename, create_app
from matplot_studio.composition import Composition, CompositionStore
from matplot_studio.contracts import rename_plot_source, validate_plot_source
from matplot_studio.storage import ProjectStore, StorageError


class RenameTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ProjectStore(Path(temporary.name))
        self.project = self.store.create_project("原项目", "保留说明")
        self.plot = self.store.create_plot(self.project["id"], "原图表", "保留图表说明")

    def test_names_persist_without_changing_ids_settings_or_compositions(self):
        project, plot = self.project["id"], self.plot.plot
        layouts = CompositionStore(self.store)
        layout = layouts.save(project, Composition(name="Figure", panels=[{"plot": plot, "row": 1, "column": 1}]))
        original_source = self.plot.code
        updated = self.store.rename_plot(project, plot, "  新图表 'α'  ", self.plot.revision)
        self.store.rename_project(project, " 新项目 / 结果 ", "原项目")
        self.assertEqual(updated.plot, self.plot.plot)
        self.assertEqual(updated.path.parent.name, "新图表 'α'")
        self.assertFalse(self.plot.path.parent.exists())
        self.assertEqual(updated.contract.settings, self.plot.contract.settings)
        self.assertEqual(updated.contract.schema, self.plot.contract.schema)
        self.assertEqual(updated.contract.meta["name"], "新图表 'α'")
        self.assertEqual(updated.contract.meta["description"], "保留图表说明")
        self.assertEqual(layouts.read(project, layout["id"]), layout)
        self.assertNotEqual(updated.revision, self.plot.revision)
        listed = ProjectStore(self.store.workspace).list_projects()[0]
        self.assertEqual((listed["id"], listed["name"], listed["description"]), (project, "新项目 / 结果", "保留说明"))
        self.assertEqual(listed["plots"][0]["name"], "新图表 'α'")
        manifest = json.loads((self.store.project_path(project) / "project.json").read_text())
        self.assertEqual(manifest["plots"][0]["name"], "新图表 'α'")
        self.assertEqual(rename_plot_source(updated.code, "原图表"), original_source)

    def test_rewriting_retains_unicode_comments_and_annotations(self):
        source = self.plot.code.replace("PLOT_META = {", "PLOT_META: dict = {")
        source = source.replace("'name': '原图表'", "'name': '原图表'  # 名称注释\n")
        result = rename_plot_source(source, '中文 "quotes"\n第二行')
        self.assertEqual(validate_plot_source(result).meta["name"], '中文 "quotes"\n第二行')
        self.assertIn("# 名称注释\n", result)
        self.assertIn("PLOT_META: dict =", result)

    def test_stale_requests_cannot_overwrite_newer_names_or_code(self):
        project, plot = self.project["id"], self.plot.plot
        self.store.rename_project(project, "第一次改名", "原项目")
        with self.assertRaises(StorageError) as error:
            self.store.rename_project(project, "覆盖", "原项目")
        self.assertEqual(error.exception.status_code, 409)
        new_code = self.plot.code + "\n# 新修改\n"
        self.store.write_plot(project, plot, new_code, self.plot.revision)
        with self.assertRaises(StorageError) as error:
            self.store.rename_plot(project, plot, "覆盖", self.plot.revision)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.store.read_plot(project, plot).code, new_code)

    def test_manifest_write_failure_rolls_back_source(self):
        original_write = self.store._atomic_write

        def fail_manifest(path, text):
            if path.name == "project.json":
                raise OSError("disk unavailable")
            original_write(path, text)

        with patch.object(self.store, "_atomic_write", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.store.rename_plot(self.project["id"], self.plot.plot, "新名称", self.plot.revision)
        self.assertEqual(self.store.read_plot(self.project["id"], self.plot.plot).code, self.plot.code)
        self.assertEqual(self.store.list_projects()[0]["plots"][0]["name"], "原图表")

    def test_empty_long_missing_and_unsafe_targets(self):
        for name in ("  ", "a" * 201):
            with self.assertRaises(StorageError):
                self.store.rename_project(self.project["id"], name, "原项目")
            with self.assertRaises(StorageError):
                self.store.rename_plot(self.project["id"], self.plot.plot, name, self.plot.revision)
        for project in ("../outside", "missing"):
            with self.assertRaises(StorageError):
                self.store.rename_project(project, "新名称", "原项目")
        with self.assertRaises(StorageError):
            self.store.rename_plot(self.project["id"], "missing", "新名称", self.plot.revision)

    def test_routes_return_names_and_new_revision(self):
        app = create_app(workspace=self.store.workspace)
        endpoints = {route.name: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
        project = endpoints["rename_project"](self.project["id"], ProjectRename(name="项目改名", expected_name="原项目"))
        self.assertEqual(project["project"]["name"], "项目改名")
        plot = endpoints["rename_plot"](self.project["id"], self.plot.plot, PlotRename(name="图表改名", revision=self.plot.revision))
        self.assertEqual(plot["meta"]["name"], "图表改名")
        self.assertNotEqual(plot["revision"], self.plot.revision)
        self.assertEqual(plot["plot"], self.plot.plot)
