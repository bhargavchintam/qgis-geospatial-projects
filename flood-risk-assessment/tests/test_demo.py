"""
End-to-end test at a tiny size: synthetic scene -> full pipeline -> figures + web map.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from src.pipeline import run_pipeline
from src.synthetic_data import FACILITY_TYPES, generate_demo_data
from src.visualize import build_web_map, make_all_figures

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG = PROJECT_DIR / "config.yaml"
SIZE = 40


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    data = generate_demo_data(size=SIZE, seed=7, out_dir=out / "data")
    results = run_pipeline(CONFIG, data, out_dir=out, stream_threshold=30)
    return data, results, out


class TestSyntheticData:
    def test_files_and_georeferencing(self, scene):
        data, _, _ = scene
        for key in ["dem", "rainfall", "ksat", "nlcd", "population", "infrastructure", "census_svi", "boundary"]:
            assert Path(data[key]).exists(), key
        with rasterio.open(data["dem"]) as src:
            assert src.crs.to_string() == "EPSG:32615"
            assert src.width == SIZE and src.height == SIZE
            assert abs(src.transform.a - 30.0) < 1e-6
            dem = src.read(1)
        assert 5.0 <= dem.min() and dem.max() <= 60.0
        with rasterio.open(data["rainfall"]) as src:
            rain = src.read(1)
        assert 250 <= rain.min() and rain.max() <= 400
        assert data["profile"]["crs"] == "EPSG:32615"

    def test_vectors(self, scene):
        data, _, _ = scene
        infra = data["infrastructure_gdf"]
        assert 20 <= len(infra) <= 30
        assert set(infra["type"]).issubset(set(FACILITY_TYPES))
        census = data["census_gdf"]
        assert len(census) == 100
        assert census["RPL_THEMES"].between(0, 1).all()
        # same bbox for rasters and vectors
        w, s, e, n = data["bounds"]
        assert tuple(np.round(data["boundary_gdf"].total_bounds, 3)) == tuple(np.round((w, s, e, n), 3))

    def test_deterministic(self, tmp_path):
        a = generate_demo_data(size=20, seed=3, out_dir=tmp_path / "a")["arrays"]["dem"]
        b = generate_demo_data(size=20, seed=3, out_dir=tmp_path / "b")["arrays"]["dem"]
        np.testing.assert_array_equal(a, b)


class TestPipeline:
    def test_shapes_and_ranges(self, scene):
        _, res, _ = scene
        for key in ["dem_filled", "slope", "twi", "streams", "river_distance", "susceptibility",
                    "vulnerability", "risk"]:
            assert res[key].shape == (SIZE, SIZE), key
        for key in ["susceptibility", "vulnerability", "risk"]:
            arr = res[key]
            assert np.nanmin(arr) >= 0.0 and np.nanmax(arr) <= 1.0, key
        assert np.all(res["dem_filled"] >= res["dem"] - 1e-9)
        assert res["flow_acc"].max() > 10
        assert set(np.unique(res["risk_classes"])).issubset({0, 1, 2, 3, 4, 5})

    def test_ahp_and_summary(self, scene):
        _, res, _ = scene
        ahp = res["ahp"]
        assert ahp["is_consistent"] and ahp["CR"] < 0.10
        assert abs(sum(ahp["weights"].values()) - 1.0) < 1e-3  # weights are rounded to 4 dp
        s = res["summary"]
        assert abs(sum(s["risk_class_pct"].values()) - 100) < 0.5
        assert s["population_high_very_high"] <= s["total_population"]
        assert 0 <= s["facilities_high_very_high"] <= s["facilities_total"]
        assert len(res["scenarios"]) == 4
        high = [res["scenarios"][rp]["high_risk_percent"] for rp in (10, 50, 100, 500)]
        assert high == sorted(high)  # more extreme return period -> more high-risk area
        json.dumps(s, default=str)  # summary must be serialisable

    def test_outputs_written(self, scene):
        _, res, out = scene
        for name in ["dem_filled.tif", "twi.tif", "flood_susceptibility.tif", "vulnerability.tif",
                     "flood_risk.tif", "risk_500yr.tif"]:
            assert (out / "rasters" / name).exists(), name
        assert (out / "vectors" / "flood_risk_zones.gpkg").exists()
        assert (out / "vectors" / "facilities_risk.gpkg").exists()
        assert len(res["risk_zones"]) >= 1
        assert {"risk_class", "risk_label", "area_km2"} <= set(res["risk_zones"].columns)


class TestVisualisation:
    def test_figures_and_map(self, scene, tmp_path):
        data, res, _ = scene
        figs = make_all_figures(res, tmp_path / "figures")
        assert len(figs) == 8
        for p in figs.values():
            assert Path(p).exists() and Path(p).stat().st_size > 5_000
        m = build_web_map(res, boundary=data["boundary_gdf"])
        html = m.get_root().render()
        assert "Flood risk index" in html and "Critical infrastructure" in html
        assert len(html.encode()) < 5_000_000
