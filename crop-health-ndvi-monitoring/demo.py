#!/usr/bin/env python3
"""
One-command demo: synthetic Sentinel-2 season -> full crop health pipeline.

    python demo.py [--size 200] [--seed 42] [--out results/demo]

Writes scene rasters and field polygons to <out>/data, pipeline rasters/CSVs
to <out>, figures to docs/figures, the Folium map to docs/map.html and a
summary to <out>/summary.json.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.pipeline import run_pipeline  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src.utils import load_config  # noqa: E402
from src.visualize import build_web_map, make_all_figures  # noqa: E402


def print_summary(summary: dict, data: dict, runtime: float) -> None:
    a = summary["assessment"]
    ph = summary["phenology"]
    an = a["anomaly"]
    print("\n=== Crop health demo summary (synthetic Story County, Iowa) ===")
    print(f"Scenes loaded: {len(summary['scenes'])}   fields: {summary['n_fields']}   "
          f"grid: {data['profile']['width']}x{data['profile']['height']} px at 10 m")
    print("Cloud/shadow % per date: " + ", ".join(
        f"{s['date'][5:]}={s['cloud_percent']:.0f}%" + ("" if s["usable"] else "*") for s in summary["scenes"]))
    print("  (* = above cloud_cover_max, not used for assessment)")
    print(f"Assessment scene (latest usable): {a['date']}")
    print(f"Phenology (block fit, block={ph['block_size']} px): mean peak NDVI {ph['mean_peak_ndvi']:.3f}, "
          f"mean peak DOY {ph['mean_peak_doy']:.0f}, mean season length {ph['mean_season_length_days']:.0f} days, "
          f"mean R2 {ph['mean_r_squared']:.3f}")
    if "peak_by_crop" in ph:
        for crop, v in ph["peak_by_crop"].items():
            print(f"  {crop:8s}: {v['n_fields']:2d} fields, peak NDVI {v['mean_peak_ndvi']:.3f} at DOY {v['mean_peak_doy']:.0f}")
    print(f"Anomalies ({an['method']}, z < {an.get('z_threshold', '-')}, min {an['min_cluster_ha']} ha): "
          f"{an['anomalous_percent']:.2f}% of crop area in {an['n_clusters']} clusters "
          f"(anomalous NDVI {an['anomalous_mean_ndvi']}, normal {an['normal_mean_ndvi']})")
    if a.get("anomaly_comparison"):
        c = a["anomaly_comparison"]
        print(f"  comparison {c['method']}: {c['anomalous_percent']:.2f}% in {c['n_clusters']} clusters")
    hd = a["health_distribution"]
    print("Fields per health class at assessment date: " + ", ".join(f"{k} {v}" for k, v in hd.items()))
    print("Top 5 most stressed fields (mean NDVI): " + ", ".join(
        f"{f['field_id']} {f['mean_ndvi']:.3f} ({f.get('crop', '')}, {f['health_class']})" for f in a["top_stressed_fields"]))
    print(f"Red-edge (NDRE) stress flags: {len(a['ndre_stress_fields'])} fields {a['ndre_stress_fields']}")
    if "last_period" in summary:
        lp = summary["last_period"]
        print(f"Fields declining in last period ({lp['period']}): {lp['fields_declining']} of "
              f"{lp['fields_declining'] + lp['fields_improving'] + lp['fields_stable']} with data")
    print(f"Runtime: {runtime:.1f} s")


def main():
    parser = argparse.ArgumentParser(description="Crop health monitoring demo")
    parser.add_argument("--size", type=int, default=200, help="scene size in 10 m pixels")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="results/demo")
    parser.add_argument("--block-size", type=int, default=5, help="phenology fit block size (px)")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    out_dir = (PROJECT_DIR / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(PROJECT_DIR / "config.yaml")

    print(f"[1/4] Generating synthetic season ({args.size}x{args.size}, seed {args.seed}) -> {out_dir / 'data'}")
    data = generate_demo_data(size=args.size, seed=args.seed, out_dir=out_dir / "data")
    print(f"      {len(data['dates'])} scenes, {len(data['fields'])} fields, cloudy dates: "
          + ", ".join(d.strftime('%Y-%m-%d') for d in data["cloud_dates"]))

    print("[2/4] Running pipeline: load -> indices -> phenology -> anomalies -> field statistics")
    res = run_pipeline(
        config, data["sentinel_dir"], fields=data["fields"], out_dir=out_dir,
        block_size=args.block_size, anomaly_method=config["anomaly"].get("method", "z_score"),
    )

    docs = PROJECT_DIR / "docs"
    if not args.no_figures:
        print(f"[3/4] Writing figures -> {docs / 'figures'}")
        make_all_figures(res, config, docs / "figures")
    print(f"[4/4] Writing web map -> {docs / 'map.html'}")
    docs.mkdir(parents=True, exist_ok=True)
    build_web_map(res, config).save(str(docs / "map.html"))

    runtime = time.time() - t0
    summary = dict(res["summary"])
    summary["run"] = {"size": args.size, "seed": args.seed, "block_size": args.block_size,
                      "runtime_seconds": round(runtime, 1), "out_dir": str(out_dir)}
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print_summary(summary, data, runtime)
    print(f"Summary written to {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
