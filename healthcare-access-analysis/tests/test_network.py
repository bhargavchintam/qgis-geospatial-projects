"""
Unit tests for the synthetic road-network builder.
"""

import networkx as nx
import numpy as np
import pytest

from src.network_builder import (CLASS_RANK, SPEED_KPH, build_synthetic_network,
                                 network_to_gdf, river_to_gdf)


class TestGraphStructure:
    def test_graph_is_connected(self, small_graph):
        """Every node must be routable from every other node."""
        assert nx.is_connected(small_graph)
        assert small_graph.number_of_nodes() > 200

    def test_node_attributes(self, small_graph):
        for _, d in small_graph.nodes(data=True):
            assert "x" in d and "y" in d
            assert np.isfinite(d["x"]) and np.isfinite(d["y"])

    def test_edge_attributes_and_positive_travel_time(self, small_graph):
        for u, v, d in small_graph.edges(data=True):
            assert d["length_m"] > 0
            assert d["travel_time_s"] > 0
            assert d["highway"] in CLASS_RANK
            assert d["speed_kph"] == SPEED_KPH[d["highway"]]

    def test_all_four_road_classes_present(self, small_graph):
        classes = {d["highway"] for _, _, d in small_graph.edges(data=True)}
        assert classes == {"residential", "secondary", "primary", "motorway"}

    def test_faster_classes_have_lower_time_per_metre(self, small_graph):
        per_m = {}
        for _, _, d in small_graph.edges(data=True):
            per_m.setdefault(d["highway"], []).append(d["travel_time_s"] / d["length_m"])
        means = {k: np.mean(v) for k, v in per_m.items()}
        assert means["motorway"] < means["primary"] < means["secondary"] < means["residential"]


class TestRiverAndBridges:
    def test_exactly_three_bridges(self, small_graph):
        bridges = [(u, v) for u, v, d in small_graph.edges(data=True) if d.get("bridge")]
        assert len(bridges) == 3

    def test_only_bridges_cross_the_river(self, small_graph):
        edges, _ = network_to_gdf(small_graph)
        band = small_graph.graph["river"]
        crossing = edges[edges.intersects(band)]
        assert len(crossing) == 3
        assert crossing["bridge"].all()

    def test_bridge_rows_are_distinct(self):
        for n in (10, 15, 25, 40, 45):
            G = build_synthetic_network(n=n, seed=1)
            rows = G.graph["bridge_rows"]
            assert len(set(rows)) == 3
            assert all(0 <= r < n for r in rows)


class TestGeoDataFrames:
    def test_network_to_gdf_shapes_and_crs(self, small_graph):
        edges, nodes = network_to_gdf(small_graph)
        assert len(edges) == small_graph.number_of_edges()
        assert len(nodes) == small_graph.number_of_nodes()
        assert str(edges.crs) == "EPSG:32611" and str(nodes.crs) == "EPSG:32611"
        assert (edges.geom_type == "LineString").all()
        assert (nodes.geom_type == "Point").all()
        # geometry length matches the stored attribute (rounded to mm)
        np.testing.assert_allclose(edges.geometry.length.values, edges["length_m"].values, atol=1e-3)

    def test_river_gdf(self, small_graph):
        river = river_to_gdf(small_graph)
        assert len(river) == 1
        assert river.geometry.iloc[0].area > 0


class TestDeterminism:
    def test_same_seed_same_graph(self):
        a = build_synthetic_network(n=12, seed=3)
        b = build_synthetic_network(n=12, seed=3)
        assert sorted(a.edges) == sorted(b.edges)

    def test_different_seed_different_gaps(self):
        a = build_synthetic_network(n=20, seed=3)
        b = build_synthetic_network(n=20, seed=4)
        assert sorted(a.edges) != sorted(b.edges)

    def test_tiny_n_rejected(self):
        with pytest.raises(ValueError):
            build_synthetic_network(n=4)
