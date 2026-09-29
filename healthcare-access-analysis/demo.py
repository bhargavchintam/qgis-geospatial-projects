"""
One-command demo: healthcare accessibility and facility site selection.

    python demo.py [--size 40] [--seed 42] [--out results/demo]

Generates a synthetic Fresno-like city (road network, census blocks,
hospitals), computes drive-time isochrones, 2SFCA access scores, underserved
blocks and two greedy maximal-covering sites, then writes GeoPackages, CSVs,
summary.json, figures (docs/figures) and the Folium map (docs/map.html).
"""

import argparse
import json
import time
from pathlib import Path

import matplotlib.pyplot as plt

from src.pipeline import run_pipeline
from src.synthetic_data import generate_demo_data
from src.utils import ensure_directory, load_config, save_gdf
from src.visualize import (build_web_map, plot_access_score, plot_coverage_before_after,
                           plot_hero, plot_isochrones, plot_road_network,
                           plot_travel_time_choropleth, plot_underserved_and_sites)

ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description="Healthcare accessibility demo")
    parser.add_argument("--size", type=int, default=None, help="grid nodes per side (default from config: 40)")
    parser.add_argument("--seed", type=int, default=None, help="random seed (default 42)")
    parser.add_argument("--out", type=str, default="results/demo", help="output folder")
    parser.add_argument("--no-figures", action="store_true", help="skip figures and web map")
    args = parser.parse_args()

    cfg = load_config(ROOT / "config.yaml")
    net_cfg, ana_cfg = cfg["network"], cfg["analysis"]
    size = args.size or int(net_cfg["grid_nodes"])
    seed = args.seed if args.seed is not None else int(net_cfg["seed"])
    threshold = float(ana_cfg["threshold_min"])
    out_dir = ensure_directory(ROOT / args.out)
    fig_dir = ensure_directory(ROOT / cfg["output"]["figures"])
    t0 = time.time()

    # 1. synthetic data ---------------------------------------------------
    data = generate_demo_data(
        size=size, seed=seed, out_dir=out_dir / "data",
        spacing_m=float(net_cfg["spacing_m"]),
        block_size_m=float(cfg["demand"]["block_size_m"]),
        density_per_km2=float(cfg["demand"]["density_per_km2"]),
        removal_fraction=float(net_cfg["removal_fraction"]),
    )
    t_data = time.time() - t0

    # 2. full pipeline ----------------------------------------------------
    res = run_pipeline(
        data,
        threshold_min=threshold,
        decay=ana_cfg["decay"],
        k_new_sites=int(ana_cfg["k_new_sites"]),
        breaks_min=ana_cfg["isochrone_breaks_min"],
        bottom_quantile=float(ana_cfg["underserved_bottom_quantile"]),
        new_site_beds=float(cfg["facilities"]["new_site_beds"]),
        candidate_every=int(ana_cfg["candidate_every_nth_node"]),
        candidate_min_dist_m=float(ana_cfg["candidate_min_dist_m"]),
    )
    t_pipe = time.time() - t0 - t_data

    # 3. write outputs ----------------------------------------------------
    save_gdf(res["nodes_tt"], out_dir / "nodes_travel_time.gpkg")
    save_gdf(res["isochrones"], out_dir / "isochrones.gpkg")
    save_gdf(res["isochrones_after"], out_dir / "isochrones_after.gpkg")
    save_gdf(res["blocks_before"], out_dir / "blocks_access.gpkg")
    save_gdf(res["blocks_after"], out_dir / "blocks_access_after.gpkg")
    save_gdf(res["hospitals"], out_dir / "hospitals_snapped.gpkg")
    if len(res["sites"]):
        save_gdf(res["sites"], out_dir / "proposed_sites.gpkg")
    res["blocks_before"].drop(columns="geometry").to_csv(out_dir / "blocks_access.csv", index=False)
    res["blocks_after"].drop(columns="geometry").to_csv(out_dir / "blocks_access_after.csv", index=False)
    res["sites"].drop(columns="geometry").to_csv(out_dir / "proposed_sites.csv", index=False)
    with open(out_dir / "coverage_steps.csv", "w") as f:
        f.write("step,pct_population_covered\n")
        for label, pct in res["coverage_steps"]:
            f.write(f"{label},{pct:.3f}\n")

    # 4. figures and web map ----------------------------------------------
    if not args.no_figures:
        roads, iso, hosp, sites, river = res["roads"], res["isochrones"], res["hospitals"], res["sites"], res["river"]
        blocks_b = res["blocks_before"]
        figs = [
            plot_hero(roads, iso, blocks_b, hosp, sites, river, fig_dir / "00_hero.png", threshold),
            plot_road_network(roads, hosp, river, fig_dir / "01_road_network.png"),
            plot_isochrones(iso, roads, hosp, river, fig_dir / "02_isochrones.png"),
            plot_travel_time_choropleth(blocks_b, hosp, fig_dir / "03_travel_time_choropleth.png"),
            plot_access_score(blocks_b, hosp, fig_dir / "04_access_score.png", threshold),
            plot_underserved_and_sites(blocks_b, hosp, sites, river, roads,
                                       fig_dir / "05_underserved_and_new_sites.png"),
            plot_coverage_before_after(res["coverage_steps"], threshold,
                                       fig_dir / "06_coverage_before_after.png"),
        ]
        for fig in figs:
            plt.close(fig)
        m = build_web_map(roads, iso, blocks_b, hosp, sites, river, threshold,
                          centre_lonlat=data["centre_lonlat"])
        map_path = ROOT / cfg["output"]["web_map"]
        map_path.parent.mkdir(parents=True, exist_ok=True)
        m.save(str(map_path))

    # 5. summary ----------------------------------------------------------
    G = res["graph"]
    cb, ca = res["coverage_before"], res["coverage_after"]
    und_b = res["blocks_before"][res["blocks_before"]["underserved"]]
    und_a = res["blocks_after"][res["blocks_after"]["underserved"]]
    n_bridges = int(res["roads"]["bridge"].sum())
    summary = {
        "study_area": cfg["study_area"]["name"],
        "crs": data["crs"],
        "grid_nodes": size,
        "seed": seed,
        "network": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "bridges": n_bridges,
            "edges_by_class": res["roads"]["highway"].value_counts().to_dict(),
            "total_length_km": round(float(res["roads"]["length_m"].sum()) / 1000.0, 1),
        },
        "blocks": int(len(res["blocks_before"])),
        "population_total": int(cb["population_total"]),
        "hospitals": int(len(res["hospitals"])),
        "total_beds": int(res["hospitals"]["beds"].sum()),
        "threshold_min": threshold,
        "decay": res["decay"],
        "pct_population_within_threshold_before": round(cb["pct_population_covered"], 2),
        "pct_population_within_threshold_after": round(ca["pct_population_covered"], 2),
        "mean_access_score_before": round(cb["mean_access_score"], 3),
        "mean_access_score_after": round(ca["mean_access_score"], 3),
        "pop_weighted_access_score_before": round(cb["pop_weighted_access_score"], 3),
        "pop_weighted_access_score_after": round(ca["pop_weighted_access_score"], 3),
        "mean_travel_time_min_before": round(float(res["blocks_before"]["tt_nearest_min"].mean()), 2),
        "max_travel_time_min_before": round(float(res["blocks_before"]["tt_nearest_min"].max()), 2),
        "underserved_blocks_before": int(len(und_b)),
        "underserved_population_before": int(und_b["population"].sum()),
        "underserved_blocks_after": int(len(und_a)),
        "underserved_population_after": int(und_a["population"].sum()),
        "isochrone_area_km2": {f"{int(r.min_minutes)}-{int(r.max_minutes)}": round(float(r.area_km2), 2)
                               for r in res["isochrones"].itertuples()},
        "candidate_sites": int(len(res["candidates"])),
        "proposed_sites": [
            {"step": c["step"], "node": int(c["node"]), "x": round(c["x"], 1), "y": round(c["y"], 1),
             "newly_covered_population": int(round(c["new_population"])),
             "pct_covered_after": round(c["pct_covered_after"], 2)}
            for c in res["chosen"]
        ],
        "runtime_s": round(time.time() - t0, 2),
        "runtime_breakdown_s": {"data": round(t_data, 2), "pipeline": round(t_pipe, 2)},
    }
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n=== Healthcare accessibility demo: summary ===")
    print(f"Study area           : {summary['study_area']} ({data['crs']})")
    print(f"Network              : {summary['network']['nodes']:,} nodes, {summary['network']['edges']:,} edges, "
          f"{n_bridges} bridges, {summary['network']['total_length_km']} km of road")
    print(f"Demand               : {summary['blocks']} blocks, {summary['population_total']:,} residents")
    print(f"Supply               : {summary['hospitals']} hospitals, {summary['total_beds']} beds "
          f"(catchment {threshold:g} min, decay {res['decay']})")
    print(f"Coverage (<= {threshold:g} min) : before {cb['pct_population_covered']:.1f} %  ->  "
          f"after {ca['pct_population_covered']:.1f} %")
    print(f"Mean access score    : before {cb['mean_access_score']:.2f}  ->  after {ca['mean_access_score']:.2f} "
          f"beds per 1,000 residents (pop-weighted {cb['pop_weighted_access_score']:.2f} -> {ca['pop_weighted_access_score']:.2f})")
    print(f"Underserved blocks   : {len(und_b)} blocks, {int(und_b['population'].sum()):,} residents "
          f"(after new sites: {len(und_a)} blocks, {int(und_a['population'].sum()):,})")
    for c in res["chosen"]:
        print(f"Proposed site {c['step']}      : node {c['node']} at x={c['x']:.0f}, y={c['y']:.0f}  "
              f"newly covered {int(round(c['new_population'])):,} people  ->  {c['pct_covered_after']:.1f} % covered")
    if not res["chosen"]:
        print("Proposed sites       : none needed (all residents already within the threshold)")
    print(f"Outputs              : {out_dir}  |  figures: {fig_dir}  |  map: {ROOT / cfg['output']['web_map']}")
    print(f"Runtime              : {summary['runtime_s']} s")


if __name__ == "__main__":
    main()
