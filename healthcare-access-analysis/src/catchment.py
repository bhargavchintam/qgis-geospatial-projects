"""
Travel-time catchments on a road network.

* ``snap_points_to_nodes``: nearest graph node for each point (KD-tree).
* ``compute_travel_times``: multi-source Dijkstra from all facilities.
* ``isochrone_polygons``: non-overlapping travel-time bands built from the
  reached (and partially reached) road segments.
"""

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from shapely.ops import substring


def _node_arrays(G: nx.Graph):
    nodes = np.array(list(G.nodes))
    xy = np.array([[G.nodes[nd]["x"], G.nodes[nd]["y"]] for nd in nodes], dtype=float)
    return nodes, xy


def snap_points_to_nodes(G: nx.Graph, points_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Snap point (or polygon centroid) features to the nearest network node.

    Returns a copy of ``points_gdf`` with two new columns: ``node`` (graph
    node id) and ``snap_dist_m`` (straight-line distance to that node).
    """
    nodes, xy = _node_arrays(G)
    tree = cKDTree(xy)
    geom = points_gdf.geometry
    if not (geom.geom_type == "Point").all():
        geom = geom.centroid
    pts = np.column_stack([geom.x.values, geom.y.values])
    dist, idx = tree.query(pts)
    out = points_gdf.copy()
    out["node"] = nodes[idx]
    out["snap_dist_m"] = dist
    return out


def compute_travel_times(G: nx.Graph, facility_nodes, weight: str = "travel_time_s") -> dict:
    """
    Minimum travel time from the nearest facility to every node.

    Uses ``networkx.multi_source_dijkstra`` so the whole network is solved in
    one pass. Returns ``{node: (minutes, nearest_facility_node)}``; nodes that
    cannot be reached get ``(inf, None)``.
    """
    sources = set(int(nd) for nd in facility_nodes)
    sources = {s for s in sources if s in G}
    result = {nd: (np.inf, None) for nd in G.nodes}
    if not sources:
        return result
    dist, paths = nx.multi_source_dijkstra(G, sources, weight=weight)
    for nd, seconds in dist.items():
        result[nd] = (seconds / 60.0, paths[nd][0])
    return result


def travel_time_series(travel_times: dict):
    """Split the compute_travel_times dict into (minutes dict, facility dict)."""
    minutes = {nd: v[0] for nd, v in travel_times.items()}
    facility = {nd: v[1] for nd, v in travel_times.items()}
    return minutes, facility


def _reached_segments(G: nx.Graph, minutes: dict, limit_min: float) -> list:
    """
    Geometry of every road segment reached within ``limit_min`` minutes.
    Segments with only one end inside the limit are cut at the point where
    the travel budget runs out (linear along the segment).
    """
    segs = []
    for u, v, d in G.edges(data=True):
        tu = minutes.get(u, np.inf)
        tv = minutes.get(v, np.inf)
        if tu > limit_min and tv > limit_min:
            continue
        near, far = (u, v) if tu <= tv else (v, u)
        t_near = min(tu, tv)
        edge_min = float(d.get("travel_time_s", 0.0)) / 60.0
        frac = 1.0 if edge_min <= 0 else min(1.0, (limit_min - t_near) / edge_min)
        geom = d.get("geometry")
        if geom is None:
            x1, y1 = G.nodes[near]["x"], G.nodes[near]["y"]
            x2, y2 = G.nodes[far]["x"], G.nodes[far]["y"]
            if frac >= 1.0:
                segs.append(LineString([(x1, y1), (x2, y2)]))
            else:
                segs.append(LineString([(x1, y1), (x1 + frac * (x2 - x1), y1 + frac * (y2 - y1))]))
        else:
            if frac >= 1.0:
                segs.append(geom)
            else:
                # orient the line so it starts at the near node
                sx, sy = geom.coords[0]
                if abs(sx - G.nodes[near]["x"]) + abs(sy - G.nodes[near]["y"]) > 1e-6:
                    geom = geom.reverse()
                segs.append(substring(geom, 0.0, frac * geom.length))
    return segs


def isochrone_polygons(
    G: nx.Graph,
    travel_times: dict,
    breaks_min=(5, 10, 15, 20, 30),
    buffer_m: float = None,
) -> gpd.GeoDataFrame:
    """
    Build travel-time bands (isochrones) from network travel times.

    For each break, all road segments reachable within that many minutes are
    buffered by ``buffer_m`` and unioned. Each band is then differenced with
    the next smaller band so bands do not overlap. Rows are ordered from the
    largest break to the smallest, so drawing them in order puts the small
    (fast) band on top.

    Returns GeoDataFrame with columns min_minutes, max_minutes, area_km2 and
    geometry (Polygon/MultiPolygon).
    """
    if buffer_m is None:
        buffer_m = 0.6 * float(G.graph.get("spacing_m", 250.0))
    crs = G.graph.get("crs")
    minutes = {nd: v[0] if isinstance(v, tuple) else v for nd, v in travel_times.items()}
    breaks = sorted(float(b) for b in breaks_min)

    cumulative = []
    for b in breaks:
        segs = _reached_segments(G, minutes, b)
        if not segs:
            cumulative.append(shapely.Polygon())
            continue
        buffered = shapely.buffer(np.array(segs, dtype=object), buffer_m, quad_segs=6)
        cumulative.append(shapely.union_all(buffered))

    rows = []
    for i in range(len(breaks) - 1, -1, -1):
        geom = cumulative[i]
        if i > 0 and not cumulative[i - 1].is_empty:
            geom = geom.difference(cumulative[i - 1])
        rows.append({
            "min_minutes": breaks[i - 1] if i > 0 else 0.0,
            "max_minutes": breaks[i],
            "area_km2": geom.area / 1e6,
            "geometry": geom,
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
