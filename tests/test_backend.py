from __future__ import annotations

import asyncio
import io
import json
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from matplot_studio.app import create_app
from matplot_studio.contracts import ContractError, apply_settings_patch, validate_plot_source
from matplot_studio.rendering import Renderer
from matplot_studio.storage import (
    MAX_IMPORT_FILES,
    MAX_IMPORT_FILE_BYTES,
    ProjectStore,
    StorageError,
)


VALID_PLOT = '''\
import matplotlib.pyplot as plt

PLOT_META = {"id": "demo", "name": "Demo", "description": "Test plot", "version": 1, "data_mode": "inline"}
PLOT_SCHEMA = [
    {"path": "figure.size", "label": "Size", "group": "Figure", "type": "number_pair", "default": [4, 3], "min": 2, "max": 10, "required": True},
    {"path": "line.color", "label": "Color", "group": "Line", "type": "color", "default": "#336699"},
    {"path": "line.visible", "label": "Visible", "group": "Line", "type": "boolean", "default": True},
]
PLOT_SETTINGS = {
    "figure.size": [4, 3],
    "line.color": "#336699",
}

def prepare_data():
    return [0, 1, 4]

def render(data, settings):
    values = {item["path"]: item.get("default") for item in PLOT_SCHEMA}
    values.update(settings)
    fig, ax = plt.subplots(figsize=values["figure.size"])
    if values["line.visible"]:
        ax.plot(data, color=values["line.color"])
    return fig
'''


def import_project_files(*, prefix: str = "", plot_source: str = VALID_PLOT):
    manifest = {
        "id": "imported-project",
        "name": "Imported project",
        "description": "Imported in a test",
        "plots": [{"id": "demo", "name": "Demo"}],
    }
    return {
        f"{prefix}project.json": json.dumps(manifest),
        f"{prefix}plots/demo/plot.py": plot_source,
    }


def plot_source(plot_id: str, name: str) -> str:
    return VALID_PLOT.replace('"id": "demo"', f'"id": "{plot_id}"').replace(
        '"name": "Demo"',
        f'"name": "{name}"',
    )


def zip_payload(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def png_size_and_dpi(payload: bytes):
    """Read the PNG dimensions and physical-resolution chunk without Pillow."""

    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    width = height = None
    dpi = None
    offset = 8
    while offset + 12 <= len(payload):
        chunk_length = int.from_bytes(payload[offset : offset + 4], "big")
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_data = payload[offset + 8 : offset + 8 + chunk_length]
        if len(chunk_data) != chunk_length:
            break
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", chunk_data[:8])
        elif chunk_type == b"pHYs" and chunk_length == 9:
            pixels_x, pixels_y, unit = struct.unpack(">IIB", chunk_data)
            if unit == 1:
                dpi = (pixels_x * 0.0254, pixels_y * 0.0254)
        offset += 12 + chunk_length
        if chunk_type == b"IEND":
            break
    return (width, height), dpi


class StreamingRequest:
    def __init__(self, content_type: str, body: bytes):
        self.headers = {"content-type": content_type, "content-length": str(len(body))}
        self.body = body

    async def stream(self):
        midpoint = len(self.body) // 2
        yield self.body[:midpoint]
        yield self.body[midpoint:]


class TemporaryWorkspace(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="matplot-studio-test-")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.plot_path = self.workspace / "demo-project" / "plots" / "demo" / "plot.py"
        self.plot_path.parent.mkdir(parents=True)
        (self.workspace / "demo-project" / "project.json").write_text(
            json.dumps(
                {
                    "id": "ignored-id",
                    "name": "Demo project",
                    "plots": [{"id": "demo", "name": "Manifest title"}],
                }
            ),
            encoding="utf-8",
        )
        self.plot_path.write_text(VALID_PLOT, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()


class ContractTests(unittest.TestCase):
    def test_reads_literal_contract(self):
        contract = validate_plot_source(VALID_PLOT)
        self.assertEqual(contract.meta["id"], "demo")
        self.assertEqual(contract.settings["line.color"], "#336699")
        self.assertEqual(len(contract.schema), 3)

    def test_patch_sets_and_unsets_only_settings(self):
        updated, settings = apply_settings_patch(
            VALID_PLOT,
            set_values={"line.color": "#ff0000", "line.visible": False},
            unset_paths=["line.color"],
        )
        self.assertEqual(settings, {"figure.size": [4, 3], "line.visible": False})
        self.assertIn("def prepare_data():", updated)
        self.assertEqual(validate_plot_source(updated).settings, settings)

    def test_rejects_dynamic_settings_and_wrong_types(self):
        with self.assertRaises(ContractError):
            validate_plot_source(VALID_PLOT.replace('PLOT_SETTINGS = {', 'PLOT_SETTINGS = dict({'))
        with self.assertRaises(ContractError):
            apply_settings_patch(VALID_PLOT, set_values={"line.visible": "yes"}, unset_paths=[])

    def test_enforces_numeric_bounds_and_required_settings(self):
        with self.assertRaises(ContractError):
            apply_settings_patch(VALID_PLOT, set_values={"figure.size": [1, 3]}, unset_paths=[])
        with self.assertRaises(ContractError):
            apply_settings_patch(VALID_PLOT, set_values={}, unset_paths=["figure.size"])

    def test_requires_complete_meta(self):
        with self.assertRaises(ContractError):
            validate_plot_source(VALID_PLOT.replace(', "description": "Test plot"', ""))


class StorageTests(TemporaryWorkspace):
    def test_lists_manifest_and_reads_plot(self):
        store = ProjectStore(self.workspace)
        projects = store.list_projects()
        self.assertEqual(projects[0]["id"], "demo-project")
        self.assertEqual(projects[0]["plots"][0]["id"], "demo")
        self.assertTrue(projects[0]["plots"][0]["valid"])
        document = store.read_plot("demo-project", "demo")
        self.assertEqual(len(document.revision), 64)

    def test_revision_conflict_does_not_overwrite(self):
        store = ProjectStore(self.workspace)
        original = store.read_plot("demo-project", "demo")
        changed = VALID_PLOT.replace("Demo\"", "Changed\"")
        saved = store.write_plot("demo-project", "demo", changed, original.revision)
        with self.assertRaises(StorageError) as caught:
            store.write_plot("demo-project", "demo", VALID_PLOT, original.revision)
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertEqual(store.read_plot("demo-project", "demo").revision, saved.revision)

    def test_rejects_path_traversal(self):
        store = ProjectStore(self.workspace)
        with self.assertRaises(StorageError):
            store.read_plot("..", "demo")
        with self.assertRaises(StorageError):
            store.read_plot("demo-project", "../demo")

    def test_app_exposes_backend_routes(self):
        app = create_app(workspace=self.workspace, web_directory=self.root / "web", render_timeout=10)
        methods_and_paths = {(method, route.path) for route in app.routes for method in getattr(route, "methods", set())}
        self.assertIn(("GET", "/api/projects"), methods_and_paths)
        self.assertIn(("POST", "/api/projects"), methods_and_paths)
        self.assertIn(("POST", "/api/projects/import"), methods_and_paths)
        self.assertIn(("DELETE", "/api/projects/{project}"), methods_and_paths)
        self.assertIn(("POST", "/api/projects/{project}/plots"), methods_and_paths)
        self.assertIn(("POST", "/api/projects/{project}/plots/import"), methods_and_paths)
        self.assertIn(("DELETE", "/api/projects/{project}/plots/{plot}"), methods_and_paths)
        self.assertIn(("PUT", "/api/projects/{project}/plots/{plot}/code"), methods_and_paths)
        self.assertIn(("PATCH", "/api/projects/{project}/plots/{plot}/settings"), methods_and_paths)
        self.assertIn(("POST", "/api/projects/{project}/plots/{plot}/render"), methods_and_paths)
        self.assertIn(("GET", "/api/projects/{project}/plots/{plot}/export/image"), methods_and_paths)
        self.assertIn(("GET", "/api/projects/{project}/plots/{plot}/export/data"), methods_and_paths)

    def test_imports_browser_file_list_and_allocates_unique_project_slug(self):
        store = ProjectStore(self.workspace)
        items = [
            {"path": path, "content": content}
            for path, content in import_project_files(prefix="chosen-folder/").items()
        ]
        files = store.files_from_json_manifest(items)

        first = store.import_project(files)
        second = store.import_project(files)

        self.assertEqual(first["id"], "imported-project")
        self.assertEqual(second["id"], "imported-project-2")
        self.assertEqual(first["plots"][0]["id"], "demo")
        self.assertTrue(first["plots"][0]["valid"])
        saved_manifest = json.loads(
            (self.workspace / "imported-project" / "project.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved_manifest["id"], "imported-project")

    def test_import_endpoint_accepts_zip_and_json_directory_payloads(self):
        app = create_app(workspace=self.workspace, web_directory=self.root / "web", render_timeout=10)
        endpoint = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", "") == "/api/projects/import"
        )

        archive = zip_payload(import_project_files(prefix="archive-root/"))
        zip_result = asyncio.run(endpoint(StreamingRequest("application/zip", archive)))
        self.assertEqual(zip_result["project"]["id"], "imported-project")

        browser_payload = json.dumps(
            {
                "files": [
                    {"path": path, "content": content}
                    for path, content in import_project_files(prefix="picked-root/").items()
                ]
            }
        ).encode("utf-8")
        json_result = asyncio.run(
            endpoint(StreamingRequest("application/json; charset=utf-8", browser_payload))
        )
        self.assertEqual(json_result["project"]["id"], "imported-project-2")

    def test_zip_import_rejects_traversal_absolute_paths_and_symlinks(self):
        dangerous_archives = []
        for path in ("../outside.txt", "/absolute.txt", "C:/windows.txt", "folder\\escape.txt"):
            dangerous_archives.append(zip_payload({path: "bad"}))

        symlink_buffer = io.BytesIO()
        with zipfile.ZipFile(symlink_buffer, "w") as archive:
            link = zipfile.ZipInfo("project-link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "project.json")
        dangerous_archives.append(symlink_buffer.getvalue())

        for archive in dangerous_archives:
            with self.subTest(archive=archive[:20]):
                with self.assertRaises(StorageError):
                    ProjectStore.files_from_zip(archive)

        self.assertFalse((self.root / "outside.txt").exists())

    def test_import_rejects_oversized_files(self):
        with self.assertRaises(StorageError) as caught:
            ProjectStore.files_from_json_manifest(
                [{"path": "project.json", "content": "x" * (MAX_IMPORT_FILE_BYTES + 1)}]
            )
        self.assertEqual(caught.exception.status_code, 413)

        oversized_zip = zip_payload({"project.json": "x" * (MAX_IMPORT_FILE_BYTES + 1)})
        with self.assertRaises(StorageError) as caught:
            ProjectStore.files_from_zip(oversized_zip)
        self.assertEqual(caught.exception.status_code, 413)

        with self.assertRaises(StorageError):
            ProjectStore.files_from_json_manifest(
                [
                    {"path": f"files/{index}.txt", "content": ""}
                    for index in range(MAX_IMPORT_FILES + 1)
                ]
            )

    def test_invalid_import_leaves_no_partial_project(self):
        store = ProjectStore(self.workspace)
        before = {path.name for path in self.workspace.iterdir()}
        bad_source = VALID_PLOT.replace('"id": "demo"', '"id": "different"')
        files = {
            path: content.encode("utf-8")
            for path, content in import_project_files(plot_source=bad_source).items()
        }

        with self.assertRaises(StorageError) as caught:
            store.import_project(files)

        self.assertEqual(caught.exception.code, "invalid_project_import")
        self.assertEqual({path.name for path in self.workspace.iterdir()}, before)
        self.assertFalse(any(path.name.startswith(".import-") for path in self.workspace.iterdir()))

    def test_imports_single_and_recursively_selected_plot_files(self):
        store = ProjectStore(self.workspace)
        items = [
            {"path": "plot.py", "content": plot_source("alpha", "Alpha")},
            {"path": "chosen/nested/plot.py", "content": plot_source("beta", "Beta")},
        ]

        files = store.plot_files_from_json_manifest(items)
        plots = store.import_plots("demo-project", files)

        self.assertEqual([item["id"] for item in plots], ["alpha", "beta"])
        self.assertEqual(
            set(plots[0]),
            {"id", "name", "description", "valid", "revision"},
        )
        self.assertTrue((self.workspace / "demo-project" / "plots" / "alpha" / "plot.py").is_file())
        self.assertTrue((self.workspace / "demo-project" / "plots" / "beta" / "plot.py").is_file())
        manifest = json.loads(
            (self.workspace / "demo-project" / "project.json").read_text(encoding="utf-8")
        )
        self.assertEqual([item["id"] for item in manifest["plots"]], ["demo", "alpha", "beta"])

    def test_plot_import_endpoint_accepts_json_file_and_directory_payload(self):
        app = create_app(workspace=self.workspace, web_directory=self.root / "web", render_timeout=10)
        endpoint = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", "") == "/api/projects/{project}/plots/import"
        )
        payload = json.dumps(
            {
                "files": [
                    {"path": "picked/one/plot.py", "content": plot_source("one", "One")},
                    {"path": "picked/two/plot.py", "content": plot_source("two", "Two")},
                ]
            }
        ).encode("utf-8")

        result = asyncio.run(endpoint("demo-project", StreamingRequest("application/json", payload)))

        self.assertEqual([item["id"] for item in result["plots"]], ["one", "two"])

    def test_plot_import_rejects_wrong_filename_duplicate_ids_and_existing_ids(self):
        store = ProjectStore(self.workspace)
        with self.assertRaises(StorageError) as caught:
            store.plot_files_from_json_manifest(
                [{"path": "selected/chart.py", "content": VALID_PLOT}]
            )
        self.assertEqual(caught.exception.code, "invalid_plot_import")

        original_manifest = (self.workspace / "demo-project" / "project.json").read_bytes()
        duplicate_files = {
            "a/plot.py": plot_source("same", "First").encode("utf-8"),
            "b/plot.py": plot_source("same", "Second").encode("utf-8"),
        }
        with self.assertRaises(StorageError) as caught:
            store.import_plots("demo-project", duplicate_files)
        self.assertEqual(caught.exception.code, "invalid_plot_import")
        self.assertFalse((self.workspace / "demo-project" / "plots" / "same").exists())

        with self.assertRaises(StorageError) as caught:
            store.import_plots("demo-project", {"plot.py": VALID_PLOT.encode("utf-8")})
        self.assertEqual(caught.exception.code, "plot_already_exists")
        self.assertEqual(
            (self.workspace / "demo-project" / "project.json").read_bytes(),
            original_manifest,
        )

    def test_invalid_or_non_utf8_plot_import_leaves_no_partial_plots(self):
        store = ProjectStore(self.workspace)
        plots_path = self.workspace / "demo-project" / "plots"
        before = {path.name for path in plots_path.iterdir()}

        invalid_contract = plot_source("bad", "Bad").replace("def render(data, settings):", "def wrong():")
        for files in (
            {
                "good/plot.py": plot_source("good", "Good").encode("utf-8"),
                "bad/plot.py": invalid_contract.encode("utf-8"),
            },
            {"bad-encoding/plot.py": b"\xff\xfe"},
        ):
            with self.subTest(paths=list(files)), self.assertRaises(StorageError):
                store.import_plots("demo-project", files)
            self.assertEqual({path.name for path in plots_path.iterdir()}, before)

    def test_plot_import_rolls_back_directories_when_manifest_write_fails(self):
        store = ProjectStore(self.workspace)
        project_path = self.workspace / "demo-project"
        original_manifest = (project_path / "project.json").read_bytes()
        files = {
            "a/plot.py": plot_source("alpha", "Alpha").encode("utf-8"),
            "b/plot.py": plot_source("beta", "Beta").encode("utf-8"),
        }

        with patch.object(store, "_atomic_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.import_plots("demo-project", files)

        self.assertEqual((project_path / "project.json").read_bytes(), original_manifest)
        self.assertFalse((project_path / "plots" / "alpha").exists())
        self.assertFalse((project_path / "plots" / "beta").exists())
        self.assertFalse(any(path.name.startswith(".plot-import-") for path in project_path.iterdir()))

    def test_deletes_plot_and_synchronizes_manifest_including_last_plot(self):
        store = ProjectStore(self.workspace)

        deleted = store.delete_plot("demo-project", "demo")

        self.assertEqual(deleted["type"], "plot")
        self.assertEqual(deleted["id"], "demo")
        self.assertFalse(self.plot_path.parent.exists())
        manifest = json.loads(
            (self.workspace / "demo-project" / "project.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["plots"], [])
        self.assertEqual(ProjectStore(self.workspace).list_projects()[0]["plots"], [])

    def test_plot_delete_rolls_back_when_manifest_update_fails(self):
        store = ProjectStore(self.workspace)
        original_manifest = (self.workspace / "demo-project" / "project.json").read_bytes()

        with patch.object(store, "_atomic_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.delete_plot("demo-project", "demo")

        self.assertTrue(self.plot_path.is_file())
        self.assertEqual(
            (self.workspace / "demo-project" / "project.json").read_bytes(),
            original_manifest,
        )

    def test_deletes_project_and_reports_missing_or_unsafe_targets(self):
        store = ProjectStore(self.workspace)

        for project, plot in (("..", "demo"), ("demo-project", "../demo")):
            with self.subTest(project=project, plot=plot), self.assertRaises(StorageError) as caught:
                store.delete_plot(project, plot)
            self.assertEqual(caught.exception.code, "invalid_path")

        deleted = store.delete_project("demo-project")

        self.assertEqual(deleted["type"], "project")
        self.assertEqual(deleted["id"], "demo-project")
        self.assertEqual(deleted["plot_count"], 1)
        self.assertFalse((self.workspace / "demo-project").exists())
        with self.assertRaises(StorageError) as caught:
            store.delete_project("demo-project")
        self.assertEqual(caught.exception.code, "project_not_found")

    def test_delete_plot_reports_missing_project_and_plot(self):
        store = ProjectStore(self.workspace)
        with self.assertRaises(StorageError) as caught:
            store.delete_plot("missing", "demo")
        self.assertEqual(caught.exception.code, "project_not_found")
        with self.assertRaises(StorageError) as caught:
            store.delete_plot("demo-project", "missing")
        self.assertEqual(caught.exception.code, "plot_not_found")

    def test_creates_unique_projects_and_self_contained_plots(self):
        store = ProjectStore(self.workspace)
        first = store.create_project("新研究")
        second = store.create_project("新研究")
        self.assertEqual(first["id"], "project")
        self.assertEqual(second["id"], "project-2")

        document = store.create_plot(first["id"], "My First Plot")
        self.assertEqual(document.plot, "my-first-plot")
        self.assertEqual(document.contract.meta["data_mode"], "demo")
        self.assertIn("def prepare_data():", document.code)
        result = Renderer(timeout_seconds=30).render(document.path, document.code, force=True)
        self.assertTrue(result.ok, result.traceback)

    def test_export_routes_set_download_headers_and_mime_types(self):
        app = create_app(workspace=self.workspace, web_directory=self.root / "web", render_timeout=30)
        endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}

        image = endpoints["/api/projects/{project}/plots/{plot}/export/image"](
            "demo-project", "demo", "png"
        )
        self.assertEqual(image.media_type, "image/png")
        self.assertEqual(image.headers["content-disposition"], 'attachment; filename="demo.png"')
        self.assertTrue(image.body.startswith(b"\x89PNG"))

        data = endpoints["/api/projects/{project}/plots/{plot}/export/data"](
            "demo-project", "demo", "json"
        )
        self.assertEqual(data.media_type, "application/json")
        self.assertEqual(json.loads(data.body.decode("utf-8")), [0, 1, 4])

    def test_export_route_rejects_dpi_for_non_png_and_out_of_range_values(self):
        app = create_app(workspace=self.workspace, web_directory=self.root / "web", render_timeout=30)
        endpoint = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", "") == "/api/projects/{project}/plots/{plot}/export/image"
        )

        with self.assertRaises(StorageError) as caught:
            endpoint("demo-project", "demo", "svg", 144)
        self.assertEqual(caught.exception.code, "invalid_export_dpi")
        self.assertEqual(caught.exception.status_code, 422)

        for invalid_dpi in (35, 601):
            with self.subTest(dpi=invalid_dpi), self.assertRaises(StorageError) as caught:
                endpoint("demo-project", "demo", "png", invalid_dpi)
            self.assertEqual(caught.exception.code, "invalid_export_dpi")

    def test_data_export_policy_can_disable_csv(self):
        source = VALID_PLOT.replace(
            '"data_mode": "inline"}',
            '"data_mode": "inline", "data_export": {"json": True, "csv": False, "note": "Rows have unequal shapes"}}',
        )
        self.plot_path.write_text(source, encoding="utf-8")
        app = create_app(workspace=self.workspace, web_directory=self.root / "web", render_timeout=30)
        endpoint = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", "") == "/api/projects/{project}/plots/{plot}/export/data"
        )
        with self.assertRaises(StorageError) as caught:
            endpoint("demo-project", "demo", "csv")
        self.assertEqual(caught.exception.code, "data_export_disabled")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("unequal", caught.exception.message)


class RenderingTests(TemporaryWorkspace):
    def test_renders_svg_in_subprocess(self):
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        result = Renderer(timeout_seconds=30).render(document.path, document.code, force=True)
        self.assertTrue(result.ok, result.traceback)
        self.assertIsNotNone(result.svg)
        self.assertIn(b"<svg", result.svg or b"")

    def test_runtime_error_contains_traceback(self):
        broken = VALID_PLOT.replace("return [0, 1, 4]", 'raise RuntimeError("demo boom")')
        self.plot_path.write_text(broken, encoding="utf-8")
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        result = Renderer(timeout_seconds=30).render(document.path, document.code, force=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertIn("demo boom", result.traceback or "")

    def test_exports_png_svg_and_pdf(self):
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        renderer = Renderer(timeout_seconds=30)
        signatures = {"png": b"\x89PNG", "svg": b"<?xml", "pdf": b"%PDF"}
        for output_format, signature in signatures.items():
            with self.subTest(output_format=output_format):
                result = renderer.export_image(document.path, document.code, output_format)
                self.assertTrue(result.ok, result.traceback)
                self.assertTrue((result.content or b"").startswith(signature))

    def test_png_export_dpi_controls_pixels_and_physical_metadata(self):
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        result = Renderer(timeout_seconds=30).export_image(
            document.path,
            document.code,
            "png",
            dpi=600,
        )
        self.assertTrue(result.ok, result.traceback)

        size, dpi = png_size_and_dpi(result.content or b"")
        self.assertEqual(size, (2400, 1800))
        self.assertIsNotNone(dpi)
        self.assertAlmostEqual((dpi or (0, 0))[0], 600, delta=0.02)
        self.assertAlmostEqual((dpi or (0, 0))[1], 600, delta=0.02)

    def test_renderer_rejects_invalid_or_non_png_dpi(self):
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        renderer = Renderer(timeout_seconds=30)

        for invalid_dpi in (35, 601, 72.5, True):
            with self.subTest(dpi=invalid_dpi), self.assertRaises(ValueError):
                renderer.export_image(document.path, document.code, "png", dpi=invalid_dpi)
        for output_format in ("svg", "pdf"):
            with self.subTest(output_format=output_format), self.assertRaises(ValueError):
                renderer.export_image(document.path, document.code, output_format, dpi=144)

    def test_exports_numpy_columns_as_json_and_csv(self):
        source = VALID_PLOT.replace(
            "import matplotlib.pyplot as plt",
            "import matplotlib.pyplot as plt\nimport numpy as np",
        ).replace(
            "return [0, 1, 4]",
            'return {"x": np.array([1, 2, 3]), "score": np.array([0.25, 0.5, 0.75])}',
        )
        self.plot_path.write_text(source, encoding="utf-8")
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        renderer = Renderer(timeout_seconds=30)

        json_result = renderer.export_data(document.path, document.code, "json")
        self.assertTrue(json_result.ok, json_result.traceback)
        self.assertEqual(json.loads((json_result.content or b"").decode("utf-8"))["x"], [1, 2, 3])

        csv_result = renderer.export_data(document.path, document.code, "csv")
        self.assertTrue(csv_result.ok, csv_result.traceback)
        csv_text = (csv_result.content or b"").decode("utf-8")
        self.assertIn("x,score", csv_text)
        self.assertIn("2,0.5", csv_text)

    def test_exports_pandas_dataframe_when_available(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas is not installed")
        source = VALID_PLOT.replace(
            "import matplotlib.pyplot as plt",
            "import matplotlib.pyplot as plt\nimport pandas as pd",
        ).replace(
            "return [0, 1, 4]",
            'return pd.DataFrame({"year": [2024, 2025], "value": [1.5, 2.5]})',
        )
        self.plot_path.write_text(source, encoding="utf-8")
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        renderer = Renderer(timeout_seconds=30)
        json_result = renderer.export_data(document.path, document.code, "json")
        csv_result = renderer.export_data(document.path, document.code, "csv")
        self.assertTrue(json_result.ok, json_result.traceback)
        self.assertTrue(csv_result.ok, csv_result.traceback)
        self.assertEqual(json.loads((json_result.content or b"").decode("utf-8"))[0]["year"], 2024)
        self.assertIn("year,value", (csv_result.content or b"").decode("utf-8"))

    def test_csv_reports_non_tabular_data(self):
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        result = Renderer(timeout_seconds=30).export_data(document.path, document.code, "csv")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "DataExportError")
        self.assertIn("list[dict]", result.message or "")

    def test_export_timeout_is_reported(self):
        source = VALID_PLOT.replace(
            "return [0, 1, 4]",
            'import time\n    time.sleep(2)\n    return [0, 1, 4]',
        )
        self.plot_path.write_text(source, encoding="utf-8")
        document = ProjectStore(self.workspace).read_plot("demo-project", "demo")
        result = Renderer(timeout_seconds=0.1).export_data(document.path, document.code, "json")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "RenderTimeout")


if __name__ == "__main__":
    unittest.main()
