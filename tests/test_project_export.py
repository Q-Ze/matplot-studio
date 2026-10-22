import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from matplot_studio.app import ProjectExport, create_app
from matplot_studio.contracts import ContractError
from matplot_studio.rendering import Renderer
from matplot_studio.storage import MAX_IMPORT_FILE_BYTES, ProjectStore, StorageError


class ProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "source")
        self.project = self.store.create_project("Export study", "研究说明")["id"]
        self.a = self.store.create_plot(self.project, "Figure A")
        self.b = self.store.create_plot(self.project, "Figure B")
        self.c = self.store.create_plot(self.project, "Figure C")
        self.path = self.store.project_path(self.project)

    def put(self, relative, content):
        path = self.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_subset_roundtrip_retains_code_settings_binary_and_shared_files(self):
        self.put(f"plots/{self.a.path.parent.name}/data/样本.bin", b"\x00\xff\x01")
        self.put(f"plots/{self.a.path.parent.name}/helper.py", b"VALUE = 4\n")
        self.put("data/shared.csv", b"x,y\n1,2\n")
        self.put("helpers.py", b"VALUE = 8\n")
        self.put("README.md", "项目说明".encode())
        for relative in [".env", ".git/config", "__pycache__/cached.pyc",
                         f"plots/{self.a.path.parent.name}/.DS_Store", f"plots/{self.a.path.parent.name}/__pycache__/plot.pyc",
                         "compositions/example.json", "composition-images/example/image.png"]:
            self.put(relative, b"excluded")
        before = (self.path / "project.json").read_bytes()
        payload = self.store.export_project(self.project, [self.c.plot, self.a.plot])
        files = self.store.files_from_zip(payload)
        self.assertEqual(set(files), {"project.json", f"plots/{self.a.path.parent.name}/plot.py", f"plots/{self.c.path.parent.name}/plot.py",
                                     f"plots/{self.a.path.parent.name}/data/样本.bin", f"plots/{self.a.path.parent.name}/helper.py",
                                     "data/shared.csv", "helpers.py", "README.md"})
        manifest = json.loads(files["project.json"])
        self.assertEqual([item["id"] for item in manifest["plots"]], [self.c.plot, self.a.plot])
        self.assertEqual(manifest["plots"][1]["name"], "Figure A")
        self.assertEqual(manifest["description"], "研究说明")
        self.assertEqual(files[f"plots/{self.a.path.parent.name}/plot.py"], self.a.path.read_bytes())
        self.assertEqual(before, (self.path / "project.json").read_bytes())
        destination = ProjectStore(self.root / "destination")
        imported = destination.import_project(files)
        restored = destination.read_plot(imported["id"], self.a.plot)
        self.assertEqual(restored.code, self.a.code)
        self.assertEqual((restored.path.parent / "data/样本.bin").read_bytes(), b"\x00\xff\x01")
        result = Renderer(timeout_seconds=15).render(restored.path, restored.code)
        self.assertTrue(result.ok, result.message)

    def test_export_names_directories_by_display_name_without_rewriting_code(self):
        original = self.a.code.replace("PLOT_META = {", "PLOT_META: dict = {")
        original = original.replace("'id': 'figure-a'", "'id': 'old-id', '说明': '保留中文', 'id': 'copied-id'  # 保留注释\n")
        original += "\n# copied-id is used elsewhere too\nREFERENCE = 'copied-id'\n"
        original = original.replace("\n", "\r\n")
        self.a.path.write_bytes(original.encode("utf-8"))
        self.put(f"plots/{self.a.path.parent.name}/data/copied-id.csv", b"copied-id,1\n")
        original_manifest = (self.path / "project.json").read_bytes()
        payload = self.store.export_project(self.project, [self.b.plot, self.a.plot])
        files = self.store.files_from_zip(payload)
        manifest = json.loads(files["project.json"])
        self.assertEqual([item["id"] for item in manifest["plots"]], [self.b.plot, "copied-id"])
        target = ProjectStore(self.root / "imported")
        imported = target.import_project(files)
        self.assertEqual(files["plots/Figure A/plot.py"], original.encode("utf-8"))
        self.assertEqual(target.read_plot(imported["id"], "copied-id").contract.meta["id"], "copied-id")
        self.assertEqual(files["plots/Figure A/data/copied-id.csv"], b"copied-id,1\n")
        self.assertEqual(self.a.path.read_bytes(), original.encode("utf-8"))
        self.assertEqual((self.path / "project.json").read_bytes(), original_manifest)

    def test_export_rejects_duplicate_ids_and_handles_swapped_directory_names(self):
        self.b.path.write_bytes(self.a.path.read_bytes())
        with self.assertRaises(StorageError) as error:
            self.store.export_project(self.project, [self.a.plot, self.b.plot])
        self.assertEqual(error.exception.code, "duplicate_plot_id")
        self.a.path.write_bytes(self.b.code.encode())
        files = self.store.files_from_zip(self.store.export_project(self.project, [self.a.plot, self.b.plot]))
        self.assertEqual(files[f"plots/{self.a.path.parent.name}/plot.py"], self.a.code.encode())
        self.assertEqual(files[f"plots/{self.b.path.parent.name}/plot.py"], self.b.code.encode())

    def test_full_project_and_current_saved_settings(self):
        self.store.write_plot(self.project, self.a.plot, self.a.code.replace("#3B6FB6", "#112233"), self.a.revision)
        payload = self.store.export_project(self.project, [self.a.plot, self.b.plot, self.c.plot])
        files = self.store.files_from_zip(payload)
        self.assertIn(b"#112233", files[f"plots/{self.a.path.parent.name}/plot.py"])
        self.assertEqual(len(json.loads(files["project.json"])["plots"]), 3)

    def test_selection_validation_and_unselected_invalid_plot(self):
        for ids in [[], [self.a.plot, self.a.plot], ["../escape"], ["missing"]]:
            with self.subTest(ids=ids), self.assertRaises(StorageError):
                self.store.export_project(self.project, ids)
        self.b.path.write_text("invalid python!", encoding="utf-8")
        self.assertTrue(self.store.export_project(self.project, [self.a.plot]).startswith(b"PK"))
        with self.assertRaises(ContractError):
            self.store.export_project(self.project, [self.b.plot])
        for payload in [{"plots": []}, {"plots": [4]}, {"plots": [self.a.plot], "extra": True}]:
            with self.assertRaises(ValidationError):
                ProjectExport.model_validate(payload)

    def test_links_cannot_include_files_outside_selected_folders(self):
        secret = self.root / "outside.txt"
        secret.write_text("not part of project")
        for relative, target in [(f"plots/{self.a.path.parent.name}/external", secret),
                                 (f"plots/{self.a.path.parent.name}/other-plot", self.b.path.parent),
                                 ("shared-link", self.b.path.parent)]:
            link = self.path / relative
            link.symlink_to(target)
            with self.subTest(relative=relative), self.assertRaises(StorageError) as error:
                self.store.export_project(self.project, [self.a.plot])
            self.assertEqual(error.exception.code, "invalid_project_export")
            link.unlink()
        linked_project = self.store.workspace / "linked-project"
        linked_project.symlink_to(self.path)
        with self.assertRaises(StorageError):
            self.store.export_project("linked-project", [self.a.plot])

    def test_limits_refuse_an_archive_that_cannot_be_imported(self):
        self.put(f"plots/{self.a.path.parent.name}/too-big.bin", b"x" * (MAX_IMPORT_FILE_BYTES + 1))
        with self.assertRaises(StorageError) as error:
            self.store.export_project(self.project, [self.a.plot])
        self.assertEqual(error.exception.status_code, 413)
        (self.a.path.parent / "too-big.bin").unlink()
        with patch("matplot_studio.storage.MAX_IMPORT_FILES", 2):
            with self.assertRaises(StorageError):
                self.store.export_project(self.project, [self.a.plot, self.b.plot])

    def test_endpoint_download_headers_and_zip_contents(self):
        app = create_app(workspace=self.store.workspace)
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "name", "") == "export_project")
        response = endpoint(self.project, ProjectExport(plots=[self.b.plot]))
        self.assertEqual(response.media_type, "application/zip")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("attachment;", response.headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            self.assertEqual(set(archive.namelist()), {"project.json", f"plots/{self.b.path.parent.name}/plot.py"})


if __name__ == "__main__":
    unittest.main()
