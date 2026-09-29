"""
End-to-end test at a tiny size (n = 15, a 3.75 km box). Must finish in < 10 s.
"""

import time

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest

from src.pipeline import run_pipeline
from src.synthetic_data import generate_demo_data
from src.visualize import build_web_map, plot_hero


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    t0 = time.time()
    data = generate_demo_data(size=15, seed=1, out_dir=out / "data")
    res = run_pipeline(data, threshold_min=4.0, decay="gaussian", k_new_sites=2,
                       breaks_min=(1, 2, 4, 6, 8))
    return {"data": data, "res": res, "out": out, "elapsed": time.time() - t0}


def test_runs_fast(demo):
    assert demo["elapsed"] < 10.0


def test_generated_files_exist_and_load(demo):
    d = demo["data"]
    for key in ("roads_path", "nodes_path", "blocks_path", "hospitals_path", "river_path"):
        gdf = gpd.read_file(d[key])
        assert len(gdf) > 0
        assert str(gdf.crs) == "EPSG:32611"


def test_data_shapes_and_ranges(demo):
    d = demo["data"]
    G = d["graph"]
    assert nx.is_connected(G)
    assert G.number_of_nodes() > 150 and G.number_of_edges() > G.number_of_nodes()
    blocks = d["blocks_gdf"]
    assert len(blocks) == 8 * 8                    # 3.75 km / 500 m rounds to 8 blocks per side
    assert (blocks["population"] >= 0).all()
    assert blocks["population"].sum() == pytest.approx(5000 * 3.75 ** 2, rel=0.01)
    assert blocks["median_income"].between(22000, 160000).all()
    assert blocks["svi"].between(0, 1).all()
    hosp = d["hospitals_gdf"]
    assert len(hosp) == 5
    assert hosp["beds"].between(120, 600).all()
    minx, miny, maxx, maxy = d["bounds"]
    assert maxx - minx == pytest.approx(3750) and maxy - miny == pytest.approx(3750)
    assert hosp.within(gpd.GeoSeries([blocks.union_all()], crs=blocks.crs).iloc[0]).all()


def test_pipeline_outputs(demo):
    res = demo["res"]
    b = res["blocks_before"]
    assert {"tt_nearest_min", "access_score", "underserved"} <= set(b.columns)
    assert (b["access_score"] >= 0).all() and np.isfinite(b["tt_nearest_min"]).all()
    assert 0 <= res["coverage_before"]["pct_population_covered"] <= 100
    assert res["coverage_after"]["pct_population_covered"] >= res["coverage_before"]["pct_population_covered"]
    iso = res["isochrones"]
    assert len(iso) == 5 and list(iso["max_minutes"]) == [8, 6, 4, 2, 1]
    assert len(res["sites"]) == len(res["chosen"]) <= 2
    assert res["coverage_steps"][0][0] == "Existing"


def test_figure_and_map_build(demo, tmp_path):
    import matplotlib.pyplot as plt

    res, d = demo["res"], demo["data"]
    fig = plot_hero(res["roads"], res["isochrones"], res["blocks_before"], res["hospitals"],
                    res["sites"], res["river"], tmp_path / "hero.png", threshold_min=4)
    plt.close(fig)
    assert (tmp_path / "hero.png").stat().st_size > 10_000
    m = build_web_map(res["roads"], res["isochrones"], res["blocks_before"], res["hospitals"],
                      res["sites"], res["river"], 4, centre_lonlat=d["centre_lonlat"])
    m.save(str(tmp_path / "map.html"))
    assert (tmp_path / "map.html").stat().st_size < 5_000_000
