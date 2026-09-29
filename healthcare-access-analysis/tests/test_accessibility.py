"""
Unit tests for the 2SFCA accessibility module.
"""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from src.accessibility import (coverage_stats, decay_weight, identify_underserved,
                               two_step_fcca)


@pytest.fixture(scope="module")
def demand_and_supply(small_graph):
    """10 x 10 demand squares over the small graph box and two hospitals."""
    x0, y0 = small_graph.graph["origin_xy"]
    extent = small_graph.graph["extent_m"]
    n = 10
    bs = extent / n
    rows = []
    for r in range(n):
        for c in range(n):
            rows.append({"block_id": r * n + c, "population": 500 + 10 * r + c,
                         "geometry": box(x0 + c * bs, y0 + r * bs, x0 + (c + 1) * bs, y0 + (r + 1) * bs)})
    demand = gpd.GeoDataFrame(rows, geometry="geometry", crs=small_graph.graph["crs"])
    hospitals = gpd.GeoDataFrame(
        {"name": ["A", "B"], "beds": [300, 150]},
        geometry=[Point(x0 + 0.25 * extent, y0 + 0.7 * extent), Point(x0 + 0.3 * extent, y0 + 0.45 * extent)],
        crs=small_graph.graph["crs"])
    return demand, hospitals


class TestDecay:
    def test_none_is_step_function(self):
        w = decay_weight(np.array([0, 5, 10, 10.1, 30]), 10, "none")
        np.testing.assert_array_equal(w, [1, 1, 1, 0, 0])

    def test_gaussian_is_one_at_zero_and_zero_at_threshold(self):
        w = decay_weight(np.array([0.0, 5.0, 10.0, 12.0]), 10, "gaussian")
        assert w[0] == pytest.approx(1.0)
        assert 0 < w[1] < 1
        assert w[2] == pytest.approx(0.0, abs=1e-12)
        assert w[3] == 0.0

    def test_unknown_decay_raises(self):
        with pytest.raises(ValueError):
            decay_weight(np.array([1.0]), 10, "linear")


class TestTwoStepFCA:
    def test_columns_and_ranges(self, small_graph, demand_and_supply):
        demand, hospitals = demand_and_supply
        out = two_step_fcca(demand, hospitals, small_graph, threshold_min=6, decay="gaussian")
        assert len(out) == len(demand)
        for col in ("tt_nearest_min", "access_score", "node", "nearest_node"):
            assert col in out.columns
        assert (out["access_score"] >= 0).all()
        assert (out["tt_nearest_min"] >= 0).all()

    def test_score_higher_near_hospitals(self, small_graph, demand_and_supply):
        demand, hospitals = demand_and_supply
        out = two_step_fcca(demand, hospitals, small_graph, threshold_min=6, decay="gaussian")
        near = out[out["tt_nearest_min"] <= 2.0]["access_score"]
        far = out[out["tt_nearest_min"] >= 5.0]["access_score"]
        assert len(near) > 0 and len(far) > 0
        assert near.mean() > far.mean()
        # blocks beyond the threshold get no access at all
        beyond = out[out["tt_nearest_min"] > 6.0]
        if len(beyond):
            assert (beyond["access_score"] == 0).all()

    def test_supply_is_conserved_without_decay(self, small_graph, demand_and_supply):
        """With decay='none', sum_i P_i * A_i equals the total beds within reach."""
        demand, hospitals = demand_and_supply
        out = two_step_fcca(demand, hospitals, small_graph, threshold_min=30, decay="none")
        total = float((out["population"] * out["access_score"] / 1000.0).sum())
        assert total == pytest.approx(float(hospitals["beds"].sum()), rel=1e-6)

    def test_more_beds_more_access(self, small_graph, demand_and_supply):
        demand, hospitals = demand_and_supply
        bigger = hospitals.copy()
        bigger["beds"] = bigger["beds"] * 2
        a = two_step_fcca(demand, hospitals, small_graph, threshold_min=8)
        b = two_step_fcca(demand, bigger, small_graph, threshold_min=8)
        np.testing.assert_allclose(b["access_score"].values, 2 * a["access_score"].values, rtol=1e-9)


class TestUnderservedAndCoverage:
    def test_underserved_flags(self, small_graph, demand_and_supply):
        demand, hospitals = demand_and_supply
        out = two_step_fcca(demand, hospitals, small_graph, threshold_min=6)
        out = identify_underserved(out, bottom_quantile=0.2, min_travel_min=6)
        assert out["underserved"].dtype == bool
        assert 0 < out["underserved"].sum() < len(out)
        # everything beyond the travel limit is underserved
        assert out.loc[out["tt_nearest_min"] > 6, "underserved"].all()
        # about a fifth of the population (at least) is flagged
        share = out.loc[out["underserved"], "population"].sum() / out["population"].sum()
        assert share >= 0.2 - 1e-9

    def test_fixed_threshold_reused(self, small_graph, demand_and_supply):
        demand, hospitals = demand_and_supply
        out = two_step_fcca(demand, hospitals, small_graph, threshold_min=6)
        a = identify_underserved(out, bottom_quantile=0.2, min_travel_min=6)
        b = identify_underserved(out, min_travel_min=6, score_threshold=float(a["score_threshold"].iloc[0]))
        assert (a["underserved"] == b["underserved"]).all()

    def test_coverage_percent_in_range(self, small_graph, demand_and_supply):
        demand, hospitals = demand_and_supply
        out = two_step_fcca(demand, hospitals, small_graph, threshold_min=6)
        for thr in (1, 6, 60):
            stats = coverage_stats(out, threshold_min=thr)
            assert 0.0 <= stats["pct_population_covered"] <= 100.0
            assert stats["population_covered"] <= stats["population_total"]
        assert coverage_stats(out, threshold_min=60)["pct_population_covered"] == pytest.approx(100.0)
        assert coverage_stats(out, threshold_min=6)["mean_access_score"] == pytest.approx(out["access_score"].mean())
