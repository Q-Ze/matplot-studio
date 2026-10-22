import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matplot_studio.composition import Composition, CompositionStore
from matplot_studio.storage import ProjectStore, StorageError


class PlotIdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name))
        self.project = self.store.create_project("IDs")["id"]
        self.plot = self.store.create_plot(self.project, "Original")
        self.other = self.store.create_plot(self.project, "Other")
        self.root = self.store.project_path(self.project)
        self.layouts = CompositionStore(self.store)
        self.layout = self.layouts.save(self.project, Composition(name="Keep reference", panels=[
            {"plot": self.plot.plot, "row": 1, "column": 1, "skip_label": True}]))
        self.code = self.plot.code.replace("'id': 'original'", "'id': 'canonical-id'")

    def test_save_renames_entire_directory_manifest_and_composition(self):
        (self.plot.path.parent / "data.csv").write_bytes(b"x,y\n1,2\n")
        old_revision = self.layout["revision"]
        saved = self.store.write_plot(self.project, self.plot.plot, self.code, self.plot.revision)
        self.assertEqual(saved.plot, "canonical-id")
        self.assertEqual(saved.path.parent.name, "Original")
        self.assertEqual(saved.path.read_text(), self.code)
        self.assertEqual((saved.path.parent / "data.csv").read_bytes(), b"x,y\n1,2\n")
        ids = [item["id"] for item in json.loads((self.root / "project.json").read_text())["plots"]]
        self.assertEqual(ids, ["canonical-id", "other"])
        layout = self.layouts.read(self.project, self.layout["id"])
        self.assertEqual(layout["layout"]["panels"][0]["plot"], "canonical-id")
        self.assertTrue(layout["layout"]["panels"][0]["skip_label"])
        self.assertNotEqual(layout["revision"], old_revision)
        self.store.write_plot(self.project, saved.plot, saved.code + "\n# next save\n", saved.revision)
        self.assertEqual(self.store.list_projects()[0]["plots"][0]["id"], "canonical-id")

    def test_existing_mismatch_is_synchronized_on_save_and_display_rename(self):
        self.plot.path.write_text(self.code)
        current = self.store.read_plot(self.project, "original")
        saved = self.store.rename_plot(self.project, "original", "New display name", current.revision)
        self.assertEqual(saved.plot, "canonical-id")
        self.assertEqual(saved.contract.meta["name"], "New display name")
        self.assertEqual(self.layouts.read(self.project, self.layout["id"])["layout"]["panels"][0]["plot"], saved.plot)

    def test_occupied_target_and_revision_conflict_leave_everything_untouched(self):
        before = self.snapshot()
        code = self.code.replace("canonical-id", "other")
        with self.assertRaises(StorageError) as error:
            self.store.write_plot(self.project, "original", code, self.plot.revision)
        self.assertEqual(error.exception.code, "plot_already_exists")
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(StorageError):
            self.store.write_plot(self.project, "original", self.code, "stale")
        self.assertEqual(self.snapshot(), before)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_failed_reference_write_rolls_back_code_directory_and_manifest(self):
        before = self.snapshot()
        atomic = self.store._atomic_write
        def fail_manifest(path, text):
            if path.name == "project.json":
                raise OSError("disk full")
            atomic(path, text)
        with patch.object(self.store, "_atomic_write", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.store.write_plot(self.project, "original", self.code, self.plot.revision)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "plots/canonical-id").exists())

    def test_invalid_layout_blocks_rename_before_any_changes(self):
        (self.root / "compositions/broken.json").write_text("bad json")
        before = self.snapshot()
        with self.assertRaises(StorageError) as error:
            self.store.write_plot(self.project, "original", self.code, self.plot.revision)
        self.assertEqual(error.exception.code, "invalid_composition")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
