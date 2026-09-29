#!/usr/bin/env python3
"""
One-command demo of the Urban Heat Island pipeline.

    python demo.py [--size 200] [--seed 42] [--out results/demo]

1. Builds a synthetic Phoenix, AZ Landsat scene (src/synthetic_data.py).
2. Runs the full chain through the src modules:
   LSTProcessor.compute_lst -> compute_lst_anomaly ->
   UHIClassifier.classify -> vectorize_zones ->
   LULCCorrelator.cross_tabulate -> compute_lst_by_lulc -> compute_impervious_correlation ->
   MitigationMapper.generate -> classify_priority_zones
3. Writes rasters, vectors and CSVs to results/demo/, figures to
   docs/figures/ and the Folium map to docs/map.html.
4. Prints a summary table and writes results/demo/summary.json.

Runs offline, deterministic for a given seed, from the project folder.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.synthetic_data import generate_demo_data  # noqa: E402
from src.pipeline import run_pipeline, format_summary  # noqa: E402
from src.visualize import make_all_figures, build_web_map  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Urban Heat Island analysis demo (synthetic Phoenix scene)")
    parser.add_argument("--size", type=int, default=200, help="grid size in pixels (30 m each), default 200")
    parser.add_argument("--seed", type=int, default=42, help="random seed, default 42")
    parser.add_argument("--out", type=str, default="results/demo", help="output folder, default results/demo")
    parser.add_argument("--no-figures", action="store_true", help="skip figures and the web map")
    return parser.parse_args(argv)


def main(argv=None) -> dict:
    args = parse_args(argv)
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_DIR / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(out_dir / "pipeline.log", mode="w")],
    )

    t0 = time.perf_counter()
    print(f"[1/4] Generating synthetic Phoenix scene ({args.size} x {args.size} px, seed {args.seed}) ...")
    data = generate_demo_data(size=args.size, seed=args.seed, out_dir=out_dir / "data")

    print("[2/4] Running LST -> UHI classes -> LULC correlation -> mitigation priority ...")
    results = run_pipeline(data, PROJECT_DIR / "config.yaml", out_dir)

    if not args.no_figures:
        print("[3/4] Writing figures to docs/figures/ ...")
        figures = make_all_figures(results, PROJECT_DIR / "docs" / "figures")
        print("[4/4] Building interactive map docs/map.html ...")
        map_path = PROJECT_DIR / "docs" / "map.html"
        map_path.parent.mkdir(parents=True, exist_ok=True)
        build_web_map(results).save(str(map_path))
    else:
        figures, map_path = [], None

    runtime = round(time.perf_counter() - t0, 2)
    summary = results["summary"]
    summary["seed"] = args.seed
    summary["runtime_s"] = runtime
    summary["outputs"] = {
        **results["paths"],
        "figures": [str(p) for p in figures],
        "map": str(map_path) if map_path else None,
    }
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print()
    print(format_summary(summary))
    print(f"Runtime: {runtime} s")
    print(f"Outputs: {out_dir}")
    if map_path:
        print(f"Figures: {PROJECT_DIR / 'docs' / 'figures'}")
        print(f"Web map: {map_path}")
    return summary


if __name__ == "__main__":
    main()
