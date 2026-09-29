"""
Two-step floating catchment area (2SFCA) accessibility.

Step 1 (supply side): for each facility j with supply S_j (beds), find every
demand unit k whose road travel time d_kj is within the threshold d0 and
compute the supply-to-demand ratio

    R_j = S_j / sum_k( P_k * f(d_kj) )

Step 2 (demand side): for each demand unit i, sum the ratios of every
facility within the threshold

    A_i = sum_j( R_j * f(d_ij) )

f(d) is 1 inside the catchment for ``decay="none"`` or a Gaussian weight
(1 at d=0, 0 at d=d0) for ``decay="gaussian"``. A_i is reported as beds per
1,000 residents (``access_score``).
"""

import math

import geopandas as gpd
import networkx as nx
import numpy as np

from .catchment import compute_travel_times, snap_points_to_nodes


def decay_weight(minutes, threshold_min: float, decay: str = "gaussian"):
    """
    Distance-decay weight f(d) for travel time ``minutes`` (scalar or array).

    * ``none``: 1 if d <= d0 else 0 (classic 2SFCA).
    * ``gaussian``: (exp(-0.5 (d/d0)^2) - exp(-0.5)) / (1 - exp(-0.5)) inside
      the catchment, 0 outside. Equals 1 at d = 0 and 0 at d = d0.
    """
    d = np.asarray(minutes, dtype=float)
    inside = d <= threshold_min
    if decay == "none":
        return inside.astype(float)
    if decay == "gaussian":
        e_half = math.exp(-0.5)
        w = (np.exp(-0.5 * (d / threshold_min) ** 2) - e_half) / (1.0 - e_half)
        return np.where(inside, np.clip(w, 0.0, 1.0), 0.0)
    raise ValueError(f"Unknown decay '{decay}', use 'none' or 'gaussian'")


def travel_time_matrix(G: nx.Graph, facility_nodes, demand_nodes, cutoff_min: float,
                       weight: str = "travel_time_s") -> np.ndarray:
    """
    Minutes from each facility (rows) to each demand node (columns), inf when
    farther than ``cutoff_min``. One bounded Dijkstra per facility.
    """
    demand_nodes = np.asarray(demand_nodes)
    col_of = {}
    for i, nd in enumerate(demand_nodes):
        col_of.setdefault(int(nd), []).append(i)
    M = np.full((len(facility_nodes), len(demand_nodes)), np.inf)
    for r, f in enumerate(facility_nodes):
        if f not in G:
            continue
        dist = nx.single_source_dijkstra_path_length(G, f, cutoff=cutoff_min * 60.0, weight=weight)
        for nd, sec in dist.items():
            for c in col_of.get(nd, ()):
                M[r, c] = sec / 60.0
    return M


def two_step_fcca(
    demand_gdf: gpd.GeoDataFrame,
    facilities_gdf: gpd.GeoDataFrame,
    G: nx.Graph,
    threshold_min: float = 15.0,
    decay: str = "gaussian",
    population_col: str = "population",
    supply_col: str = "beds",
) -> gpd.GeoDataFrame:
    """
    Two-step floating catchment area accessibility.

    Returns a copy of ``demand_gdf`` with columns:
      node            snapped network node of the polygon centroid
      tt_nearest_min  road travel time to the nearest facility (minutes)
      nearest_node    node of that facility
      access_score    beds per 1,000 residents reachable within the threshold
    """
    demand = snap_points_to_nodes(G, demand_gdf)
    facilities = snap_points_to_nodes(G, facilities_gdf)
    fac_nodes = [int(nd) for nd in facilities["node"].values]
    dem_nodes = [int(nd) for nd in demand["node"].values]
    pop = demand[population_col].astype(float).values
    supply = facilities[supply_col].astype(float).values

    M = travel_time_matrix(G, fac_nodes, dem_nodes, threshold_min)
    W = decay_weight(M, threshold_min, decay)            # facilities x demand

    # step 1: supply-to-demand ratio per facility
    weighted_pop = W @ pop                                 # sum_k P_k f(d_kj)
    with np.errstate(divide="ignore", invalid="ignore"):
        R = np.where(weighted_pop > 0, supply / weighted_pop, 0.0)

    # step 2: sum the ratios of every facility within reach of each demand unit
    A = W.T @ R                                            # sum_j R_j f(d_ij)

    tt = compute_travel_times(G, fac_nodes)
    demand["tt_nearest_min"] = [tt[nd][0] for nd in dem_nodes]
    demand["nearest_node"] = [tt[nd][1] for nd in dem_nodes]
    demand["access_score"] = A * 1000.0
    return demand


def identify_underserved(
    gdf: gpd.GeoDataFrame,
    score_col: str = "access_score",
    population_col: str = "population",
    bottom_quantile: float = 0.2,
    min_travel_min: float = 15.0,
    tt_col: str = "tt_nearest_min",
    score_threshold: float = None,
) -> gpd.GeoDataFrame:
    """
    Flag underserved demand units.

    A unit is underserved when it has residents and either (a) its access
    score is at or below the population-weighted ``bottom_quantile`` of all
    scores, or (b) its nearest facility is farther than ``min_travel_min``.
    Pass ``score_threshold`` to reuse a fixed score cut-off (for example the
    before-state threshold when comparing a scenario with new facilities).
    Adds a boolean column ``underserved`` (and ``score_threshold``) and
    returns a copy.
    """
    out = gdf.copy()
    pop = out[population_col].astype(float).values
    score = out[score_col].astype(float).values
    if score_threshold is not None:
        threshold = float(score_threshold)
    else:
        order = np.argsort(score, kind="stable")
        cum = np.cumsum(pop[order])
        total = cum[-1] if len(cum) else 0.0
        if total > 0:
            k = int(np.searchsorted(cum, bottom_quantile * total, side="left"))
            k = min(k, len(order) - 1)
            threshold = score[order[k]]
        else:
            threshold = -np.inf
    low_score = score <= threshold
    far = out[tt_col].astype(float).values > min_travel_min if tt_col in out else np.zeros(len(out), bool)
    out["underserved"] = (pop > 0) & (low_score | far)
    out["score_threshold"] = float(threshold)
    return out


def coverage_stats(
    gdf: gpd.GeoDataFrame,
    threshold_min: float = 15.0,
    tt_col: str = "tt_nearest_min",
    population_col: str = "population",
    score_col: str = "access_score",
) -> dict:
    """
    Population coverage summary.

    Returns dict with population_total, population_covered (within
    ``threshold_min`` of a facility), pct_population_covered (0..100),
    mean_access_score (simple mean over units) and
    pop_weighted_access_score (mean experienced by an average resident).
    """
    pop = gdf[population_col].astype(float).values
    tt = gdf[tt_col].astype(float).values
    total = float(pop.sum())
    covered = float(pop[tt <= threshold_min].sum())
    stats = {
        "threshold_min": float(threshold_min),
        "population_total": total,
        "population_covered": covered,
        "pct_population_covered": 100.0 * covered / total if total > 0 else 0.0,
    }
    if score_col in gdf:
        score = gdf[score_col].astype(float).values
        stats["mean_access_score"] = float(np.mean(score)) if len(score) else 0.0
        stats["pop_weighted_access_score"] = float((score * pop).sum() / total) if total > 0 else 0.0
    return stats
