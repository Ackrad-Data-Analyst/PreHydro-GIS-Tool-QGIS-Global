import json
import shutil
import unittest
import uuid
from pathlib import Path

from fully_hydro_preparation_qgis.core import (
    create_workspace,
    elevation_conversion_factor,
    safe_project_name,
    threshold_cells,
    write_json,
    write_manifest,
)


class CoreTests(unittest.TestCase):
    def setUp(self):
        base = Path.cwd() / ".test-temp"
        base.mkdir(exist_ok=True)
        self.temporary = base / uuid.uuid4().hex
        self.temporary.mkdir()

    def tearDown(self):
        base = (Path.cwd() / ".test-temp").resolve()
        target = self.temporary.resolve()
        if target.parent == base and target.exists():
            shutil.rmtree(target)

    def test_safe_project_name(self):
        self.assertEqual(safe_project_name(" Zambia Flood / 01 "), "Zambia_Flood_01")
        with self.assertRaises(ValueError):
            safe_project_name("***")

    def test_threshold_cells_metric(self):
        self.assertEqual(threshold_cells(25, 10, 10, "metres"), 1012)

    def test_threshold_cells_feet(self):
        self.assertEqual(threshold_cells(25, 10, 10, "feet"), 10890)

    def test_threshold_rejects_degrees(self):
        with self.assertRaises(ValueError):
            threshold_cells(25, 0.0001, 0.0001, "degrees")

    def test_elevation_unit_conversion(self):
        self.assertAlmostEqual(elevation_conversion_factor("metres", "feet"), 3.280839895013123)
        self.assertAlmostEqual(elevation_conversion_factor("feet", "metres"), 0.3048)
        self.assertEqual(elevation_conversion_factor("metres", "meters"), 1.0)

    def test_workspace_and_manifests(self):
        paths = create_workspace(self.temporary, "Test Project")
        self.assertTrue(paths["root"].is_dir())
        self.assertTrue((paths["root"] / "HEC_RAS_GIS_Export").is_dir())
        payload = {
            "status": "COMPLETE_WITH_REVIEW",
            "completed_utc": "2026-09-04T00:00:00+00:00",
            "project_root": str(paths["root"]),
            "outputs": {"boundary": "boundary.gpkg"},
            "review_notes": ["Engineer review required."],
        }
        write_manifest(paths, payload)
        self.assertEqual(json.loads(paths["manifest"].read_text())["status"], "COMPLETE_WITH_REVIEW")
        self.assertIn("Engineer review required", paths["manifest_text"].read_text())
        with self.assertRaises(ValueError):
            create_workspace(self.temporary, "Test Project")

    def test_atomic_json(self):
        path = self.temporary / "report.json"
        write_json(path, {"ok": True})
        self.assertEqual(json.loads(path.read_text()), {"ok": True})


if __name__ == "__main__":
    unittest.main()
