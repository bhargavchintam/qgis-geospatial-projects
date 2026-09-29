"""End-to-end test of the demo pipeline at a tiny size (must run in < 10 s)."""

import time

import numpy as np
import rasterio

from src.pipeline import run_pipeline
from src.synthetic_data import generate_demo_data
from src.utils import load_config
from src.visualize import build_web_map, fig_hero, save_fig
from tests.conftest import PROJECT_DIR


def test_pipeline_end_to_end_small(tmp_path):
    t0 = time.time()
    size = 40
    data = generate_demo_data(size=size, seed=7, out_dir=tmp_path / "data")
    for key in ["dem", "ghi", "landuse", "transmission_lines", "roads", "substations",
                "residential", "protected_areas"]:
        assert (tmp_path / "data" / (key + (".tif" if key in ("dem", "ghi", "landuse") else ".gpkg"))).exists(), key
    assert data["profile"]["height"] == size and data["profile"]["width"] == size
    assert data["profile"]["crs"].to_epsg() == 32612
    assert data["resolution"] == 18000.0 / size

    with rasterio.open(data["dem"]) as src:
        dem = src.read(1)
        assert src.crs.to_epsg() == 32612
    assert dem.shape == (size, size)
    assert 700 < dem.min() < 1000 and 1500 < dem.max() < 2300
    with rasterio.open(data["ghi"]) as src:
        ghi = src.read(1)
    assert 5.6 <= ghi.min() and ghi.max() <= 6.8
    with rasterio.open(data["landuse"]) as src:
        lu = src.read(1)
    assert set(np.unique(lu)) <= {1, 2, 3, 4, 5}
    assert (lu == 1).mean() > 0.5

    config = load_config(PROJECT_DIR / "config.yaml")
    results = run_pipeline(data, config, out_dir=tmp_path / "out")

    for key in ["slope", "aspect", "hillshade", "index", "mask", "reasons", "classes"]:
        assert np.asarray(results[key]).shape == (size, size), key
    assert results["slope"].min() >= 0
    index = results["index"]
    assert np.nanmin(index) >= 0 and np.nanmax(index) <= 1
    assert np.isnan(index[~results["mask"]]).all()
    assert not np.isnan(index[results["mask"]]).any()
    assert set(np.unique(results["classes"])) <= {0, 1, 2, 3, 4, 5}
    assert results["consistency"]["is_consistent"]
    assert abs(sum(results["weights"].values()) - 1.0) < 1e-9

    summary = results["summary"]
    assert 0 < summary["pct_area_excluded"] < 100
    assert summary["n_candidate_sites"] >= 1
    assert summary["total_capacity_mw"] > 0
    sites = results["sites"]
    assert (sites["capacity_mw"] > 0).all()
    assert (sites["area_ha"] >= config["site_extraction"]["min_area_ha"]).all()
    assert list(sites["rank"]) == list(range(1, len(sites) + 1))

    out = tmp_path / "out"
    for name in ["suitability_index.tif", "suitability_classes.tif", "constraints_mask.tif",
                 "constraint_reasons.tif", "candidate_sites.gpkg", "candidate_sites.csv",
                 "ahp_weights.csv", "summary.json"]:
        assert (out / name).exists(), name

    # Web map and one figure build without error
    html = build_web_map(results).get_root().render()
    assert "Suitability index" in html and len(html) < 5_000_000
    save_fig(fig_hero(results), tmp_path / "hero.png")
    assert (tmp_path / "hero.png").stat().st_size > 10_000

    assert time.time() - t0 < 10.0


def test_generate_is_deterministic(tmp_path):
    a = generate_demo_data(size=30, seed=3, out_dir=tmp_path / "a")
    b = generate_demo_data(size=30, seed=3, out_dir=tmp_path / "b")
    np.testing.assert_array_equal(a["arrays"]["dem"], b["arrays"]["dem"])
    np.testing.assert_array_equal(a["arrays"]["landuse"], b["arrays"]["landuse"])
