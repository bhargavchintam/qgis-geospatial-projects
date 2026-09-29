"""
End-to-end analysis pipeline shared by demo.py, app.py and the tests.

generate data -> snap hospitals -> travel times -> isochrones -> 2SFCA ->
underserved blocks -> greedy site selection -> coverage after each new site.
"""

import geopandas as gpd
import pandas as pd

from .accessibility import coverage_stats, identify_underserved, two_step_fcca
from .catchment import compute_travel_times, isochrone_polygons, snap_points_to_nodes
from .site_selection import candidate_nodes_from_grid, greedy_max_coverage, sites_to_gdf


def run_pipeline(
    data: dict,
    threshold_min: float = 15.0,
    decay: str = "gaussian",
    k_new_sites: int = 2,
    breaks_min=(5, 10, 15, 20, 30),
    bottom_quantile: float = 0.2,
    new_site_beds: float = 200.0,
    candidate_every: int = 4,
    candidate_min_dist_m: float = 1000.0,
) -> dict:
    """
    Run the full analysis on the output of ``generate_demo_data``.

    Returns a dict with keys
      graph, roads, nodes, river, hospitals (with node + snap_dist_m)
      travel_times          {node: (minutes, nearest facility node)}
      nodes_tt              nodes GeoDataFrame with tt_min column
      isochrones            bands GeoDataFrame (before new sites)
      blocks_before         blocks with tt_nearest_min, access_score, underserved
      blocks_after          same after adding the proposed sites
      sites                 proposed sites GeoDataFrame
      chosen                raw greedy result (list of dicts)
      candidates            candidate node ids
      coverage_before / coverage_after   coverage_stats dicts
      coverage_steps        [(label, pct_covered), ...] for the bar chart
      isochrones_after      bands GeoDataFrame with new sites included
    """
    G = data["graph"]
    blocks = data["blocks_gdf"]
    hospitals = snap_points_to_nodes(G, data["hospitals_gdf"])
    hosp_nodes = [int(n) for n in hospitals["node"].values]

    travel_times = compute_travel_times(G, hosp_nodes)
    nodes_tt = data["nodes_gdf"].copy()
    nodes_tt["tt_min"] = [travel_times[int(n)][0] for n in nodes_tt["node"].values]
    nodes_tt["nearest_node"] = [travel_times[int(n)][1] for n in nodes_tt["node"].values]
    isochrones = isochrone_polygons(G, travel_times, breaks_min=breaks_min)

    blocks_before = two_step_fcca(blocks, hospitals, G, threshold_min=threshold_min, decay=decay)
    blocks_before = identify_underserved(blocks_before, bottom_quantile=bottom_quantile,
                                         min_travel_min=threshold_min)
    coverage_before = coverage_stats(blocks_before, threshold_min)

    candidates = candidate_nodes_from_grid(G, hosp_nodes, every=candidate_every,
                                           min_dist_m=candidate_min_dist_m)
    chosen = greedy_max_coverage(G, blocks, candidates, hosp_nodes, k=k_new_sites,
                                 threshold_min=threshold_min) if k_new_sites > 0 else []
    sites = sites_to_gdf(chosen, data["crs"], beds=new_site_beds)

    coverage_steps = [("Existing", coverage_before["pct_population_covered"])]
    for c in chosen:
        coverage_steps.append((f"+ Site {c['step']}", c["pct_covered_after"]))

    if len(sites):
        fac_after = gpd.GeoDataFrame(
            pd.concat([hospitals[["name", "beds", "geometry"]], sites[["name", "beds", "geometry"]]],
                      ignore_index=True),
            geometry="geometry", crs=data["crs"])
    else:
        fac_after = hospitals[["name", "beds", "geometry"]]
    blocks_after = two_step_fcca(blocks, fac_after, G, threshold_min=threshold_min, decay=decay)
    # reuse the before-state score cut-off so the two states are comparable
    blocks_after = identify_underserved(blocks_after, min_travel_min=threshold_min,
                                        score_threshold=float(blocks_before["score_threshold"].iloc[0]))
    coverage_after = coverage_stats(blocks_after, threshold_min)
    fac_after_nodes = hosp_nodes + [int(c["node"]) for c in chosen]
    isochrones_after = isochrone_polygons(G, compute_travel_times(G, fac_after_nodes),
                                          breaks_min=breaks_min)

    return {
        "graph": G,
        "roads": data["roads_gdf"],
        "nodes": data["nodes_gdf"],
        "river": data.get("river_gdf"),
        "hospitals": hospitals,
        "travel_times": travel_times,
        "nodes_tt": nodes_tt,
        "isochrones": isochrones,
        "blocks_before": blocks_before,
        "blocks_after": blocks_after,
        "sites": sites,
        "chosen": chosen,
        "candidates": candidates,
        "coverage_before": coverage_before,
        "coverage_after": coverage_after,
        "coverage_steps": coverage_steps,
        "isochrones_after": isochrones_after,
        "threshold_min": float(threshold_min),
        "decay": decay,
    }
