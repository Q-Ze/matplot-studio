import json
import tempfile
import unittest
from pathlib import Path

from matplot_studio.composition import Composition, CompositionStore
from matplot_studio.storage import ProjectStore, StorageError


class NamedDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "source")
        self.project = self.store.create_project("Names")["id"]

    def test_readable_names_duplicates_and_rename_keep_ids_and_references(self):
        first = self.store.create_plot(self.project, "实验 / α: Figure 1")
        second = self.store.create_plot(self.project, "实验 / α: Figure 1")
        self.assertEqual(first.path.parent.name, "实验 _ α_ Figure 1")
        self.assertNotEqual(first.path.parent.name, second.path.parent.name)
        self.assertIn(second.plot, second.path.parent.name)
        layouts = CompositionStore(self.store)
        saved = layouts.save(self.project, Composition(name="References", panels=[{"plot":first.plot,"row":1,"column":1}]))
        (first.path.parent / "数据.csv").write_bytes(b"x,y\n1,2\n")
        renamed = self.store.rename_plot(self.project, first.plot, "对照组", first.revision)
        self.assertEqual(renamed.plot, first.plot)
        self.assertEqual(renamed.path.parent.name, "对照组")
        self.assertEqual((renamed.path.parent / "数据.csv").read_bytes(), b"x,y\n1,2\n")
        self.assertEqual(layouts.read(self.project, saved["id"]), saved)
        self.assertEqual(self.store.read_plot(self.project, first.plot).path, renamed.path)
        self.assertEqual([item["id"] for item in self.store.list_projects()[0]["plots"]], [first.plot,second.plot])
        self.store.delete_plot(self.project, second.plot)
        self.assertTrue(renamed.path.exists())
        self.assertFalse(second.path.parent.exists())

    def test_export_import_same_names_safe_paths_and_exact_source_bytes(self):
        docs = [self.store.create_plot(self.project, name) for name in ["CON", "../α/β", "同名", "同名"]]
        data = self.store.export_project(self.project, [doc.plot for doc in docs])
        files = self.store.files_from_zip(data)
        manifest = json.loads(files["project.json"])
        directories = [item["directory"] for item in manifest["plots"]]
        self.assertEqual(len(set(directories)), 4)
        self.assertEqual(directories[0], "_CON")
        destination = ProjectStore(Path(self.temp.name) / "destination")
        imported = destination.import_project(files)
        for doc, directory in zip(docs, directories):
            self.assertNotIn("/", directory)
            self.assertEqual(files[f"plots/{directory}/plot.py"], doc.path.read_bytes())
            restored = destination.read_plot(imported["id"], doc.plot)
            self.assertEqual(restored.code, doc.code)
            self.assertEqual(restored.path.parent.name, directory)
        self.assertEqual(len(destination.list_projects()[0]["plots"]), 4)

    def test_directory_mapping_cannot_escape_or_alias_another_plot(self):
        doc = self.store.create_plot(self.project, "Example")
        files = self.store.files_from_zip(self.store.export_project(self.project, [doc.plot]))
        manifest = json.loads(files["project.json"])
        for invalid in ["../outside", "/outside", "a/b", "a\\b", ".hidden"]:
            manifest["plots"][0]["directory"] = invalid
            candidate = {**files,"project.json":json.dumps(manifest).encode()}
            with self.subTest(directory=invalid), self.assertRaises(StorageError):
                self.store.import_project(candidate)
        manifest["plots"][0]["directory"] = "Example"
        manifest["plots"].append({"id":"different", "directory":"Example"})
        with self.assertRaises(StorageError):
            self.store.import_project({**files, "project.json":json.dumps(manifest).encode()})


if __name__ == "__main__":
    unittest.main()
