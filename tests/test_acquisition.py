import unittest

from fully_hydro_preparation_qgis.acquisition import (
    _copernicus_name,
    _overpass_geojson,
    _worldcover_cell,
    _worldcover_name,
)


class AcquisitionTests(unittest.TestCase):
    def test_copernicus_tile_names(self):
        self.assertEqual(
            _copernicus_name(-15, 28, 10),
            "Copernicus_DSM_COG_10_S15_00_E028_00_DEM",
        )
        self.assertEqual(
            _copernicus_name(19, -88, 30),
            "Copernicus_DSM_COG_30_N19_00_W088_00_DEM",
        )

    def test_worldcover_grid(self):
        self.assertEqual(_worldcover_cell(-13.2), -15)
        self.assertEqual(_worldcover_cell(28.4), 27)
        self.assertEqual(_worldcover_name(-15, 27), "S15E027")

    def test_overpass_conversion(self):
        payload = [{
            "id": 42,
            "tags": {"highway": "primary", "name": "Test Road"},
            "geometry": [{"lat": -15.0, "lon": 28.0}, {"lat": -15.1, "lon": 28.1}],
        }]
        collection = _overpass_geojson(payload, "highway")
        self.assertEqual(len(collection["features"]), 1)
        self.assertEqual(collection["features"][0]["geometry"]["coordinates"][0], [28.0, -15.0])
        self.assertEqual(collection["features"][0]["properties"]["osm_id"], 42)


if __name__ == "__main__":
    unittest.main()
