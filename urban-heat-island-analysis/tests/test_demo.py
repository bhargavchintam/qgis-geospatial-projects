"""
End-to-end test of the demo pipeline on a tiny synthetic scene (< 10 s).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
import geopandas as gpd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.synthetic_data import generate_demo_data  # noqa: E402
from src.pipeline import run_pipeline, format_summary  # noqa: E402
from src.visualize import build_web_map, plot_hero  # noqa: E402

SIZE = 40


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """Generate a 40 x 40 scene and run the whole pipeline once for all tests."""
    base = tmp_path_factory.mktemp("uhi")
    data = generate_demo_data(size=SIZE, seed=7, out_dir=base / "data")
    results = run_pipeline(data, PROJECT_DIR / "config.yaml", base / "out")
    return {"data": data, "results": results, "base": base}


def test_synthetic_data_files_and_ranges(demo):
    data = demo["data"]
    for key in ["thermal", "red", "nir", "lulc", "impervious", "population", "parks"]:
        assert Path(data[key]).exists(), key

    with rasterio.open(data["thermal"]) as src:
        assert src.crs.to_epsg() == 32612
        assert src.shape == (SIZE, SIZE)
        assert abs(src.transform.a - 30.0) < 1e-6
        kelvin = src.read(1).astype(float) * 0.00341802 + 149.0
        assert 290 < kelvin.min() and kelvin.max() < 340

    with rasterio.open(data["red"]) as src:
        red = src.read(1)
        assert 0.0 <= red.min() and red.max() <= 1.0
    with rasterio.open(data["impervious"]) as src:
        imp = src.read(1)
        assert imp.min() >= 0 and imp.max() <= 100
    with rasterio.open(data["lulc"]) as src:
        codes = set(np.unique(src.read(1)).tolist())
        assert codes <= {11, 21, 22, 23, 24, 31, 41, 52, 71, 82}
        assert {24, 22, 11} <= codes

    parks = gpd.read_file(data["parks"])
    assert len(parks) == 7 and parks.crs.to_epsg() == 32612

    # the same scene comes back for the same seed
    again = generate_demo_data(size=SIZE, seed=7, out_dir=demo["base"] / "data_again")
    np.testing.assert_array_equal(again["arrays"]["lulc"], data["arrays"]["lulc"])


def test_pipeline_arrays(demo):
    r = demo["results"]
    lst, uhi, mpi = r["lst"], r["uhi"], r["mpi"]
    assert lst.shape == uhi.shape == mpi.shape == (SIZE, SIZE)

    assert np.isfinite(lst).all()
    assert 15 < np.nanmin(lst) and np.nanmax(lst) < 70
    assert 35 < np.nanmean(lst) < 55

    assert set(np.unique(uhi).tolist()) <= {-1, 0, 1, 2, 3, 4, 5}
    assert uhi.dtype == np.int16

    valid = mpi[~np.isnan(mpi)]
    assert valid.size > 0 and valid.min() >= 0.0 and valid.max() <= 1.0 + 1e-9

    # physical consistency: built-up land is hotter than vegetation and water
    lulc = r["lulc"]
    hot = np.nanmean(lst[np.isin(lulc, [23, 24])])
    cool = np.nanmean(lst[np.isin(lulc, [11, 41, 71, 82])])
    assert hot - cool > 5.0
    assert r["impervious_corr"]["pearson_r"] > 0.5
    assert r["impervious_corr"]["slope"] > 0


def test_pipeline_outputs_exist(demo):
    r = demo["results"]
    for key in ["lst", "anomaly", "uhi", "mpi", "uhi_zones", "priority_zones", "crosstab", "lst_by_lulc", "summary"]:
        assert Path(r["paths"][key]).exists(), key

    with rasterio.open(r["paths"]["uhi"]) as src:
        assert src.dtypes[0] == "int16" and src.nodata == -1
    with rasterio.open(r["paths"]["lst"]) as src:
        assert src.dtypes[0] == "float32"

    zones = gpd.read_file(r["paths"]["uhi_zones"])
    assert {"class_id", "class_name", "area_km2"} <= set(zones.columns)
    priority = gpd.read_file(r["paths"]["priority_zones"])
    assert {"priority_class", "priority_label", "area_ha"} <= set(priority.columns)
    assert set(priority["priority_label"]) <= {"High", "Medium", "Low"}

    with open(r["paths"]["summary"]) as f:
        summary = json.load(f)
    for key in ["lst", "uhi_area_percent", "lst_vs_impervious", "mpi", "priority_area_ha", "top_hottest_lulc"]:
        assert key in summary
    assert abs(sum(summary["uhi_area_percent"].values()) - 100.0) < 0.1
    assert len(summary["top_hottest_lulc"]) == 3
    assert summary["top_hottest_lulc"][0]["lulc_name"].startswith("Developed")
    assert "Mean LST" in format_summary(summary)


def test_figure_and_web_map(demo, tmp_path):
    r = demo["results"]
    png = plot_hero(r, tmp_path / "00_hero.png")
    assert png.exists() and png.stat().st_size > 10_000

    m = build_web_map(r)
    html = m.get_root().render()
    assert "Land surface temperature" in html
    assert "Mitigation priority zones" in html
    assert "Parks and green space" in html
    assert len(html.encode("utf-8")) < 5_000_000
