"""
Greedy maximal covering location (MCLP) for new facility sites.

Given demand units with population, existing facilities and a set of candidate
network nodes, pick k candidates one at a time. At every step the candidate
that brings the largest population newly within ``threshold_min`` of a
facility is chosen. The greedy heuristic is within (1 - 1/e) of the optimal
coverage for this submodular objective.
"""

import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from .catchment import compute_travel_times, snap_points_to_nodes


def candidate_nodes_from_grid(
    G: nx.Graph,
    existing_facility_nodes,
    every: int = 4,
    min_dist_m: float = 1000.0,
) -> list:
    """
    Candidate sites: every ``every``-th grid row and column node (uses node
    ``row``/``col`` attributes when present, otherwise every ``every``-th node
    in id order) that lies at least ``min_dist_m`` from any existing facility.
    """
    nodes = list(G.nodes)
    if all("row" in G.nodes[nd] and "col" in G.nodes[nd] for nd in nodes[:5]):
        cands = [nd for nd in nodes
                 if G.nodes[nd]["row"] % every == every // 2
                 and G.nodes[nd]["col"] % every == every // 2]
    else:
        cands = nodes[::every]
    existing = [int(nd) for nd in existing_facility_nodes if nd in G]
    if existing and cands:
        ex_xy = np.array([[G.nodes[nd]["x"], G.nodes[nd]["y"]] for nd in existing])
        tree = cKDTree(ex_xy)
        c_xy = np.array([[G.nodes[nd]["x"], G.nodes[nd]["y"]] for nd in cands])
        dist, _ = tree.query(c_xy)
        cands = [nd for nd, dd in zip(cands, dist) if dd >= min_dist_m]
    return cands


def greedy_max_coverage(
    G: nx.Graph,
    demand_gdf: gpd.GeoDataFrame,
    candidate_nodes,
    existing_facility_nodes,
    k: int = 2,
    threshold_min: float = 15.0,
    population_col: str = "population",
    weight: str = "travel_time_s",
) -> list:
    """
    Greedy maximal covering location problem.

    Returns a list (length <= k) of dicts, one per chosen site in order:
      step, node, x, y, new_population (newly covered by this site),
      cumulative_covered, pct_covered_after.
    Stops early when no candidate adds any new coverage.
    """
    demand = snap_points_to_nodes(G, demand_gdf)
    dem_nodes = np.array([int(nd) for nd in demand["node"].values])
    pop = demand[population_col].astype(float).values
    total = float(pop.sum())
    cutoff_s = threshold_min * 60.0

    tt = compute_travel_times(G, existing_facility_nodes, weight=weight)
    covered = np.array([tt[nd][0] <= threshold_min for nd in dem_nodes], dtype=bool)

    # reach set of every candidate (demand indices within the threshold)
    col_of = {}
    for i, nd in enumerate(dem_nodes):
        col_of.setdefault(int(nd), []).append(i)
    reach = {}
    for c in candidate_nodes:
        if c not in G:
            continue
        dist = nx.single_source_dijkstra_path_length(G, c, cutoff=cutoff_s, weight=weight)
        idx = [i for nd in dist for i in col_of.get(nd, ())]
        reach[int(c)] = np.array(sorted(set(idx)), dtype=int)

    chosen = []
    for step in range(1, k + 1):
        best_node, best_gain = None, 0.0
        for c in sorted(reach):
            idx = reach[c]
            gain = float(pop[idx][~covered[idx]].sum()) if len(idx) else 0.0
            if gain > best_gain:
                best_node, best_gain = c, gain
        if best_node is None:
            break
        covered[reach[best_node]] = True
        del reach[best_node]
        chosen.append({
            "step": step,
            "node": best_node,
            "x": float(G.nodes[best_node]["x"]),
            "y": float(G.nodes[best_node]["y"]),
            "new_population": best_gain,
            "cumulative_covered": float(pop[covered].sum()),
            "pct_covered_after": 100.0 * float(pop[covered].sum()) / total if total > 0 else 0.0,
        })
    return chosen


def sites_to_gdf(chosen: list, crs, beds: float = 200.0) -> gpd.GeoDataFrame:
    """Turn the greedy result into a point GeoDataFrame (with a beds column)."""
    from shapely.geometry import Point

    if not chosen:
        return gpd.GeoDataFrame(
            {"step": [], "node": [], "name": [], "beds": [], "new_population": [],
             "pct_covered_after": []},
            geometry=[], crs=crs,
        )
    return gpd.GeoDataFrame(
        {
            "step": [c["step"] for c in chosen],
            "node": [c["node"] for c in chosen],
            "name": [f"Proposed site {c['step']}" for c in chosen],
            "beds": [float(beds)] * len(chosen),
            "new_population": [c["new_population"] for c in chosen],
            "pct_covered_after": [c["pct_covered_after"] for c in chosen],
        },
        geometry=[Point(c["x"], c["y"]) for c in chosen],
        crs=crs,
    )
