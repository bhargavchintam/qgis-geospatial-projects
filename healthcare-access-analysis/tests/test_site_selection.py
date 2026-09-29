"""
Unit tests for greedy maximal-covering site selection.
"""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from src.accessibility import coverage_stats, two_step_fcca
from src.site_selection import candidate_nodes_from_grid, greedy_max_coverage, sites_to_gdf


@pytest.fixture(scope="module")
def demand(small_graph):
    x0, y0 = small_graph.graph["origin_xy"]
    extent = small_graph.graph["extent_m"]
    n = 12
    bs = extent / n
    rows = [{"block_id": r * n + c, "population": 400 + 7 * c + 3 * r,
             "geometry": box(x0 + c * bs, y0 + r * bs, x0 + (c + 1) * bs, y0 + (r + 1) * bs)}
            for r in range(n) for c in range(n)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=small_graph.graph["crs"])


@pytest.fixture(scope="module")
def existing(small_graph):
    # one facility in the north-west corner region
    return [n for n, d in small_graph.nodes(data=True) if d["row"] == 12 and d["col"] == 2]


class TestCandidates:
    def test_candidates_keep_distance_from_existing(self, small_graph, existing):
        cands = candidate_nodes_from_grid(small_graph, existing, every=4, min_dist_m=1000)
        assert len(cands) > 0
        ex = existing[0]
        ex_xy = np.array([small_graph.nodes[ex]["x"], small_graph.nodes[ex]["y"]])
        for c in cands:
            xy = np.array([small_graph.nodes[c]["x"], small_graph.nodes[c]["y"]])
            assert np.linalg.norm(xy - ex_xy) >= 1000
            assert small_graph.nodes[c]["row"] % 4 == 2 and small_graph.nodes[c]["col"] % 4 == 2


class TestGreedy:
    def test_picks_k_sites_and_coverage_never_decreases(self, small_graph, demand, existing):
        thr = 3.0
        cands = candidate_nodes_from_grid(small_graph, existing, every=4, min_dist_m=1000)
        before = coverage_stats(two_step_fcca(
            demand, _fac(small_graph, existing), small_graph, threshold_min=thr), thr)
        chosen = greedy_max_coverage(small_graph, demand, cands, existing, k=2, threshold_min=thr)
        assert len(chosen) == 2
        assert len({c["node"] for c in chosen}) == 2
        assert all(c["node"] in cands for c in chosen)
        pcts = [before["pct_population_covered"]] + [c["pct_covered_after"] for c in chosen]
        assert all(b >= a for a, b in zip(pcts, pcts[1:]))
        assert chosen[0]["new_population"] >= chosen[1]["new_population"] > 0
        # cumulative bookkeeping is consistent
        assert chosen[1]["cumulative_covered"] == pytest.approx(
            before["population_covered"] + chosen[0]["new_population"] + chosen[1]["new_population"])

    def test_greedy_result_matches_recomputed_coverage(self, small_graph, demand, existing):
        thr = 3.0
        cands = candidate_nodes_from_grid(small_graph, existing, every=4, min_dist_m=1000)
        chosen = greedy_max_coverage(small_graph, demand, cands, existing, k=2, threshold_min=thr)
        after_nodes = existing + [c["node"] for c in chosen]
        after = coverage_stats(two_step_fcca(
            demand, _fac(small_graph, after_nodes), small_graph, threshold_min=thr), thr)
        assert after["pct_population_covered"] == pytest.approx(chosen[-1]["pct_covered_after"], abs=1e-6)

    def test_first_site_is_the_best_single_choice(self, small_graph, demand, existing):
        """Greedy step 1 must equal the best single candidate by brute force."""
        thr = 3.0
        cands = candidate_nodes_from_grid(small_graph, existing, every=4, min_dist_m=1000)
        chosen = greedy_max_coverage(small_graph, demand, cands, existing, k=1, threshold_min=thr)
        best = max(
            (coverage_stats(two_step_fcca(demand, _fac(small_graph, existing + [c]), small_graph,
                                          threshold_min=thr), thr)["population_covered"], c)
            for c in cands)
        assert best[0] == pytest.approx(chosen[0]["cumulative_covered"])

    def test_stops_when_nothing_left_to_cover(self, small_graph, demand, existing):
        cands = candidate_nodes_from_grid(small_graph, existing, every=4, min_dist_m=1000)
        chosen = greedy_max_coverage(small_graph, demand, cands, existing, k=3, threshold_min=60)
        assert chosen == []

    def test_sites_to_gdf(self, small_graph, demand, existing):
        cands = candidate_nodes_from_grid(small_graph, existing, every=4, min_dist_m=1000)
        chosen = greedy_max_coverage(small_graph, demand, cands, existing, k=2, threshold_min=3.0)
        gdf = sites_to_gdf(chosen, small_graph.graph["crs"], beds=150)
        assert len(gdf) == 2 and (gdf["beds"] == 150).all()
        assert str(gdf.crs) == "EPSG:32611"
        assert sites_to_gdf([], small_graph.graph["crs"]).empty


def _fac(G, nodes):
    from shapely.geometry import Point
    return gpd.GeoDataFrame(
        {"name": [f"f{n}" for n in nodes], "beds": [100.0] * len(nodes)},
        geometry=[Point(G.nodes[n]["x"], G.nodes[n]["y"]) for n in nodes], crs=G.graph["crs"])
