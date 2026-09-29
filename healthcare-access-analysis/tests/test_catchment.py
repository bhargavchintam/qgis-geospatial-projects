"""
Unit tests for travel times, point snapping and isochrone construction.
"""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from src.catchment import compute_travel_times, isochrone_polygons, snap_points_to_nodes


@pytest.fixture(scope="module")
def facility_nodes(small_graph):
    nodes = list(small_graph.nodes)
    return [nodes[len(nodes) // 2], nodes[5]]


class TestTravelTimes:
    def test_travel_time_at_facility_is_zero(self, small_graph, facility_nodes):
        tt = compute_travel_times(small_graph, facility_nodes)
        for f in facility_nodes:
            assert tt[f][0] == 0.0
            assert tt[f][1] == f

    def test_all_nodes_reached_and_non_negative(self, small_graph, facility_nodes):
        tt = compute_travel_times(small_graph, facility_nodes)
        assert len(tt) == small_graph.number_of_nodes()
        minutes = np.array([v[0] for v in tt.values()])
        assert np.all(np.isfinite(minutes)) and np.all(minutes >= 0)
        assert set(v[1] for v in tt.values()) <= set(facility_nodes)

    def test_neighbour_time_equals_edge_time(self, small_graph, facility_nodes):
        tt = compute_travel_times(small_graph, facility_nodes)
        f = facility_nodes[0]
        for nb in small_graph.neighbors(f):
            assert tt[nb][0] <= small_graph[f][nb]["travel_time_s"] / 60.0 + 1e-9

    def test_no_facilities_gives_inf(self, small_graph):
        tt = compute_travel_times(small_graph, [])
        assert all(np.isinf(v[0]) for v in tt.values())


class TestSnapping:
    def test_snap_returns_nearest_node(self, small_graph):
        nd = list(small_graph.nodes)[10]
        x, y = small_graph.nodes[nd]["x"], small_graph.nodes[nd]["y"]
        pts = gpd.GeoDataFrame({"id": [1, 2]}, geometry=[Point(x + 30, y - 20), Point(x, y)],
                               crs=small_graph.graph["crs"])
        snapped = snap_points_to_nodes(small_graph, pts)
        assert list(snapped["node"]) == [nd, nd]
        assert snapped["snap_dist_m"].iloc[0] == pytest.approx(np.hypot(30, 20))
        assert snapped["snap_dist_m"].iloc[1] == 0.0

    def test_snap_uses_centroid_for_polygons(self, small_graph):
        nd = list(small_graph.nodes)[20]
        x, y = small_graph.nodes[nd]["x"], small_graph.nodes[nd]["y"]
        poly = Point(x, y).buffer(40)
        gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs=small_graph.graph["crs"])
        assert snap_points_to_nodes(small_graph, gdf)["node"].iloc[0] == nd


class TestIsochrones:
    def test_bands_do_not_overlap_and_areas_increase(self, small_graph, facility_nodes):
        tt = compute_travel_times(small_graph, facility_nodes)
        breaks = [1, 2, 4, 6]
        iso = isochrone_polygons(small_graph, tt, breaks_min=breaks)
        for col in ("min_minutes", "max_minutes", "area_km2", "geometry"):
            assert col in iso.columns
        assert set(iso["max_minutes"]) == set(float(b) for b in breaks)
        # ordered largest to smallest
        assert list(iso["max_minutes"]) == sorted(iso["max_minutes"], reverse=True)
        # pairwise overlap is (numerically) zero
        geoms = list(iso.geometry)
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                assert geoms[i].intersection(geoms[j]).area < 1e-6 * max(geoms[i].area, 1.0)
        # cumulative reach grows with the break
        by_break = iso.sort_values("max_minutes")
        cumulative = np.cumsum(by_break["area_km2"].values)
        assert np.all(np.diff(cumulative) > 0)
        assert (by_break["area_km2"] > 0).all()

    def test_facility_inside_smallest_band(self, small_graph, facility_nodes):
        tt = compute_travel_times(small_graph, facility_nodes)
        iso = isochrone_polygons(small_graph, tt, breaks_min=[1, 3])
        smallest = iso[iso["max_minutes"] == 1.0].geometry.iloc[0]
        f = facility_nodes[0]
        assert smallest.contains(Point(small_graph.nodes[f]["x"], small_graph.nodes[f]["y"]))

    def test_crs_kept(self, small_graph, facility_nodes):
        tt = compute_travel_times(small_graph, facility_nodes)
        iso = isochrone_polygons(small_graph, tt, breaks_min=[2, 5])
        assert str(iso.crs) == "EPSG:32611"
