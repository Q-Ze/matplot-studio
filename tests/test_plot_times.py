import os
import tempfile
import unittest
from pathlib import Path

from matplot_studio.app import create_app
from matplot_studio.storage import ProjectStore


class PlotTimeTests(unittest.TestCase):
    def test_list_and_plot_payload_use_actual_modification_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectStore(Path(temporary))
            project = store.create_project("Time sorting")["id"]
            plot = store.create_plot(project,"Figure 1")
            os.utime(plot.path,(1700000000,1700000000))
            self.assertEqual(store.list_projects()[0]["plots"][0]["modified_at"],1700000000000)
            app = create_app(workspace=store.workspace)
            get_plot = next(route.endpoint for route in app.routes if getattr(route,"path",None)=="/api/projects/{project}/plots/{plot}" and "GET" in route.methods)
            self.assertEqual(get_plot(project,plot.plot)["modified_at"],1700000000000)
            store.write_plot(project,plot.plot,plot.code+"\n# Updated\n",plot.revision)
            self.assertGreater(store.list_projects()[0]["plots"][0]["modified_at"],1700000000000)
            # Invalid code is still listed with a usable file timestamp.
            plot.path.write_text("invalid python (")
            self.assertIsInstance(store.list_projects()[0]["plots"][0]["modified_at"],int)
