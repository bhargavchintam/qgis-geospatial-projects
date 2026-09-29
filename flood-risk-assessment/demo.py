#!/usr/bin/env python3
"""
One-command demo: synthetic Harris County scene -> full flood risk pipeline.

    python demo.py [--size 200] [--seed 42] [--out results/demo] [--stream-threshold 400]

Writes data to results/demo/data, rasters/vectors to results/demo,
figures to docs/figures and the Folium map to docs/map.html, prints a
summary table and stores results/demo/summary.json.
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
from src.visualize import build_web_map, make_all_figures  # noqa: E402


def _fmt_pct(d: dict) -> str:
    return ", ".join(f"{k}: {v:.1f}%" for k, v in d.items())


def print_summary(s: dict, runtime: float) -> None:
    line = "-" * 72
    print(line)
    print("FLOOD RISK ASSESSMENT DEMO, synthetic Harris County (TX) scene")
    print(line)
    print(f"{'Grid':<34}{s['grid']} ({s['area_km2']:.1f} km2)")
    print(f"{'Sink cells filled':<34}{s['sink_cells_filled']:,}")
    print(f"{'Stream cells / length':<34}{s['stream_cells']:,} cells, {s['stream_length_km']:.1f} km "
          f"(threshold {s['stream_threshold_cells']} cells)")
    print()
    print("AHP weights (row geometric mean):")
    for k, v in s["ahp_weights"].items():
        print(f"  {k:<24}{v:.4f}")
    print(f"  lambda_max = {s['ahp_lambda_max']:.4f}, CI = {s['ahp_CI']:.4f}, CR = {s['ahp_CR']:.4f} "
          f"({'consistent' if s['ahp_consistent'] else 'INCONSISTENT'}, threshold 0.10)")
    print()
    print(f"{'Susceptibility class %':<34}{_fmt_pct(s['susceptibility_class_pct'])}")
    print(f"{'Mean susceptibility':<34}{s['mean_susceptibility']:.3f}")
    print(f"{'Mean vulnerability':<34}{s['mean_vulnerability']:.3f}")
    print(f"{'Risk method':<34}{s['risk_method']} (High >= {s['risk_thresholds']['high']}, "
          f"Very High >= {s['risk_thresholds']['very_high']})")
    print(f"{'Mean risk index':<34}{s['mean_risk']:.3f}")
    print("Risk classes (100-yr):")
    print(f"  {'class':<12}{'area %':>8}{'area km2':>11}")
    for name in ["Very Low", "Low", "Moderate", "High", "Very High"]:
        print(f"  {name:<12}{s['risk_class_pct'][name]:>8.2f}{s['risk_class_km2'][name]:>11.3f}")
    print(f"{'High + Very High area':<34}{s['high_very_high_pct']:.2f}%")
    print(f"{'Population (total)':<34}{s['total_population']:,}")
    print(f"{'Population in High + Very High':<34}{s['population_high_very_high']:,}")
    print(f"{'Facilities in High + Very High':<34}{s['facilities_high_very_high']} of {s['facilities_total']} "
          f"{s['facilities_by_type_at_risk']}")
    print("High-risk area by return period:")
    for rp, pct in s["scenario_high_risk_pct"].items():
        print(f"  {rp:>4}-yr  {pct:>6.2f}%")
    print(f"{'Runtime':<34}{runtime:.1f} s")
    print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Flood risk assessment demo")
    parser.add_argument("--size", type=int, default=200, help="grid size (cells per side)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="results/demo", help="output folder (relative to project)")
    parser.add_argument("--stream-threshold", type=int, default=None, help="flow accumulation threshold (cells)")
    parser.add_argument("--risk-method", default=None, choices=["multiplicative", "geometric_mean", "matrix"],
                        help="risk combination method (default from config.yaml)")
    parser.add_argument("--quiet", action="store_true", help="hide pipeline log lines")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()

    out_dir = (PROJECT_DIR / args.out).resolve()
    data_dir = out_dir / "data"
    fig_dir = PROJECT_DIR / "docs" / "figures"
    map_path = PROJECT_DIR / "docs" / "map.html"

    print(f"[1/4] Generating synthetic scene ({args.size}x{args.size}, seed {args.seed}) -> {data_dir}")
    data = generate_demo_data(size=args.size, seed=args.seed, out_dir=data_dir)

    print(f"[2/4] Running pipeline -> {out_dir}")
    results = run_pipeline(
        PROJECT_DIR / "config.yaml", data, out_dir=out_dir,
        stream_threshold=args.stream_threshold, risk_method=args.risk_method,
    )

    print(f"[3/4] Writing figures -> {fig_dir}")
    make_all_figures(results, fig_dir)

    print(f"[4/4] Writing web map -> {map_path}")
    m = build_web_map(results, boundary=data["boundary_gdf"])
    map_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(map_path))

    runtime = time.time() - t0
    summary = dict(results["summary"])
    summary.update({
        "size": args.size, "seed": args.seed, "runtime_s": round(runtime, 1),
        "scenarios": results["scenarios"], "exposure": results["exposure"],
        "susceptibility_stats": results["susceptibility_stats"],
        "vulnerability_stats": results["vulnerability_stats"],
        "outputs": {
            "data_dir": str(data_dir), "rasters": str(out_dir / "rasters"),
            "vectors": str(out_dir / "vectors"), "figures": str(fig_dir), "map": str(map_path),
        },
    })
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print_summary(results["summary"], runtime)


if __name__ == "__main__":
    main()
