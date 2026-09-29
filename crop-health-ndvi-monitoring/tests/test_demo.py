"""End-to-end test at tiny size: synthetic season -> pipeline -> figures/map. Must stay under 10 s."""

import json
import time
from pathlib import Path

import numpy as np
import pytest
import rasterio

from src.pipeline import run_pipeline
from src.synthetic_data import BAND_NAMES, generate_demo_data
from src.utils import load_config
from src.visualize import build_web_map, plot_hero

PROJECT_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("demo")
    t0 = time.time()
    data = generate_demo_data(size=40, seed=7, out_dir=tmp / "data")
    config = load_config(PROJECT_DIR / "config.yaml")
    res = run_pipeline(config, data["sentinel_dir"], fields=data["fields"], out_dir=tmp / "out",
                       block_size=4, run_comparison=False)
    return {"tmp": tmp, "data": data, "res": res, "config": config, "elapsed": time.time() - t0}


def test_synthetic_data_layout(demo_run):
    data = demo_run["data"]
    scene_dirs = sorted(Path(data["sentinel_dir"]).glob("S2A_MSIL2A_*_demo"))
    assert len(scene_dirs) == 14
    assert scene_dirs[0].name.startswith("S2A_MSIL2A_20240405T170000")
    assert scene_dirs[-1].name.startswith("S2A_MSIL2A_20241020T170000")
    files = {p.name for p in scene_dirs[0].iterdir()}
    assert files == {f"{b}.tif" for b in BAND_NAMES} | {"SCL.tif"}
    with rasterio.open(scene_dirs[0] / "B08.tif") as src:
        assert src.dtypes[0] == "uint16"
        assert src.crs.to_epsg() == 32615
        assert src.res == (10.0, 10.0)
        arr = src.read(1)
        assert 1 <= arr.min() and arr.max() <= 10000
    with rasterio.open(scene_dirs[0] / "B05.tif") as src:
        assert src.res == (20.0, 20.0)
    assert data["fields_path"].exists()
    assert set(data["fields"]["crop"].unique()) <= {"corn", "soybean"}
    assert len(data["fields"]) >= 6
    assert len(data["cloud_dates"]) in (2, 3)
    assert 4 <= len(data["patches"]) <= 6


def test_pipeline_shapes_and_ranges(demo_run):
    res = demo_run["res"]
    n = 40
    assert len(res["scenes"]) == 14
    assert res["ndvi_stack"].shape == (14, n, n)
    for scene in res["scenes"]:
        for idx in ("ndvi", "evi", "savi", "ndre", "ndwi"):
            arr = scene[idx]
            assert arr.shape == (n, n)
            assert np.nanmin(arr) >= -1.0 and np.nanmax(arr) <= 1.0
    assert res["phenology"]["parameters"].shape == (6, n, n)
    pv = res["peak_metrics"]["peak_value"]
    assert 0.3 < np.nanmean(pv[res["field_mask"]]) < 0.95
    pd_ = res["peak_metrics"]["peak_doy"]
    assert np.all((pd_[~np.isnan(pd_)] >= 96) & (pd_[~np.isnan(pd_)] <= 294))
    assert res["anomaly_mask"].shape == (n, n) and res["anomaly_mask"].dtype == bool
    assert 0.0 <= res["anomaly_stats"]["anomalous_percent"] <= 50.0
    # the assessment scene is the latest one under the cloud limit
    cloud_max = demo_run["config"]["sentinel"]["cloud_cover_max"]
    assert res["scenes"][res["assessment_idx"]]["cloud_percent"] <= cloud_max
    assert all(s["cloud_percent"] > cloud_max for s in res["scenes"][res["assessment_idx"] + 1:])


def test_field_outputs(demo_run):
    res = demo_run["res"]
    t = res["field_table"]
    assert len(t) == len(res["fields"])
    assert set(t["health_class"].unique()) <= {"Excellent", "Good", "Moderate", "Poor", "Very Poor", "No Data"}
    assert t["mean_ndvi"].between(-1, 1).all()
    assert "peak_doy" in t.columns and "anomaly_pct" in t.columns and "ndre_stress" in t.columns
    df = res["stats_df"]
    assert set(df["index"].unique()) == {"ndvi", "evi", "savi", "ndre", "ndwi"}
    assert df["date"].nunique() == 14
    s = res["summary"]
    assert s["n_fields"] == len(t)
    assert sum(s["assessment"]["health_distribution"].values()) <= len(t)
    assert len(s["assessment"]["top_stressed_fields"]) <= 5
    assert "last_period" in s and s["last_period"]["fields_declining"] >= 0


def test_files_written(demo_run):
    out = demo_run["tmp"] / "out"
    for name in ("field_health_report.csv", "field_change_report.csv", "field_phenology.csv",
                 "fields_assessment.geojson", "rasters/anomaly_map.tif", "rasters/peak_ndvi.tif",
                 "rasters/peak_doy.tif", "rasters/ndvi_20240920.tif", "rasters/ndvi_expected_baseline.tif"):
        assert (out / name).exists(), name
    with rasterio.open(out / "rasters" / "anomaly_map.tif") as src:
        assert src.dtypes[0] == "uint8"
        vals = np.unique(src.read(1))
        assert set(vals.tolist()) <= {0, 1, 255}
    json.dumps(demo_run["res"]["summary"], default=str)  # summary is serialisable


def test_figure_and_map(demo_run):
    res, config, tmp = demo_run["res"], demo_run["config"], demo_run["tmp"]
    hero = plot_hero(res, config, tmp / "hero.png")
    assert Path(hero).stat().st_size > 10_000
    m = build_web_map(res, config)
    html = m._repr_html_()
    assert "Fields (health class)" in html and len(html) < 5_000_000


def test_runtime_budget(demo_run):
    assert demo_run["elapsed"] < 10.0, f"pipeline took {demo_run['elapsed']:.1f} s"
