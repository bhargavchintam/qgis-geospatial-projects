"""
One-command demo: synthetic Kingman, AZ scene -> AHP suitability -> sites.

    python demo.py [--size N] [--seed 42] [--out results/demo]

Writes rasters/vectors/CSVs to results/demo/, figures to docs/figures/
and the Folium map to docs/map.html, then prints a summary and saves
results/demo/summary.json.
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.pipeline import run_pipeline  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src.utils import load_config  # noqa: E402
from src.visualize import build_web_map, make_all_figures  # noqa: E402


def print_summary(summary: dict, results: dict) -> None:
    line = "=" * 72
    print(line)
    print("UTILITY-SCALE SOLAR SITE SUITABILITY - SUMMARY")
    print(line)
    print(f"Study area : {summary['study_area']}")
    print(f"Grid       : {summary['grid_size'][0]} x {summary['grid_size'][1]} px at "
          f"{summary['resolution_m']:.0f} m ({summary['total_area_km2']:.0f} km2)")
    cons = summary["ahp_consistency"]
    print("\nAHP weights (row geometric mean):")
    for name, w in summary["ahp_weights"].items():
        print(f"  {name:<14} {w:6.3f}  ({100 * w:5.1f}%)")
    print(f"  lambda_max = {cons['lambda_max']:.4f}, CI = {cons['CI']:.4f}, "
          f"CR = {cons['CR']:.4f} -> {'consistent' if cons['is_consistent'] else 'NOT consistent'} (< 0.10)")

    print(f"\nConstraints: {summary['pct_area_excluded']:.2f}% of the study area excluded")
    for reason, pct in summary["pct_excluded_by_reason"].items():
        print(f"  {reason:<20} {pct:6.2f}%")

    print("\nSuitability classes (% of allowed area):")
    for label, pct in summary["class_area_pct_of_allowed"].items():
        print(f"  {label:<10} {pct:6.2f}%")

    print(f"\nCandidate sites (index >= {summary['site_threshold']:.2f}, >= {summary['min_site_area_ha']:.0f} ha): "
          f"{summary['n_candidate_sites']}")
    if summary["top_sites"]:
        print(f"  {'rank':>4} {'area_ha':>9} {'mean_suit':>9} {'cap_MW':>8} {'GWh/yr':>8} {'grid_km':>8}")
        for s in summary["top_sites"]:
            print(f"  {s['rank']:>4} {s['area_ha']:>9.1f} {s['mean_suitability']:>9.3f} "
                  f"{s['capacity_mw']:>8.1f} {s['annual_gwh']:>8.1f} {s['dist_to_grid_km']:>8.2f}")
    print(f"\nTotal developable capacity : {summary['total_capacity_mw']:.1f} MW "
          f"({summary['total_annual_gwh']:.1f} GWh/yr) across {summary['n_candidate_sites']} sites")
    print(f"Best site                  : {summary['best_site_mw']:.1f} MW")
    print(line)


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description="Solar site suitability demo")
    parser.add_argument("--size", type=int, default=200, help="grid size in pixels (default 200)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument("--out", type=str, default="results/demo", help="output folder")
    parser.add_argument("--no-figures", action="store_true", help="skip figures and web map")
    args = parser.parse_args(argv)

    t0 = time.time()
    config = load_config(PROJECT_DIR / "config.yaml")
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_DIR / out_dir
    fig_dir = PROJECT_DIR / config["output"].get("figures", "docs/figures")
    docs_dir = PROJECT_DIR / "docs"

    print(f"[1/4] Generating synthetic data ({args.size} x {args.size}, seed {args.seed}) ...")
    data = generate_demo_data(size=args.size, seed=args.seed, out_dir=out_dir / "data")

    print("[2/4] Running the suitability pipeline ...")
    results = run_pipeline(data, config, out_dir=out_dir)

    if not args.no_figures:
        print(f"[3/4] Writing figures to {fig_dir.relative_to(PROJECT_DIR)}/ ...")
        make_all_figures(results, fig_dir, top_n=int(config["site_extraction"].get("top_n", 10)))
        print("[4/4] Building the Folium web map docs/map.html ...")
        docs_dir.mkdir(parents=True, exist_ok=True)
        build_web_map(results, top_n=int(config["site_extraction"].get("top_n", 10))).save(str(docs_dir / "map.html"))

    summary = results["summary"]
    summary["runtime_s"] = round(time.time() - t0, 1)
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print_summary(summary, results)
    print(f"Outputs in {out_dir}  |  runtime {summary['runtime_s']} s")
    return results


if __name__ == "__main__":
    main()
