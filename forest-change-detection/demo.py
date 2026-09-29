#!/usr/bin/env python
"""
One-command demo: synthetic Rondônia scene -> Random Forest land cover ->
accuracy assessment -> forest change (post-classification + dNBR) -> MMU ->
loss polygons -> statistics, figures and the Folium web map.

    python demo.py [--size 200] [--seed 42] [--out results/demo]
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.pipeline import run_pipeline  # noqa: E402
from src.report import summary_lines  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src.utils import ensure_directory, load_config  # noqa: E402
from src.visualize import build_web_map, save_all_figures  # noqa: E402


def build_summary(results: dict, size: int, seed: int, cfg: dict, runtime_s: float) -> dict:
    acc = results["accuracy"]
    stats = results["stats"]
    per_class = {
        row["name"]: {"producers_accuracy": float(row["producers_accuracy"]),
                      "users_accuracy": float(row["users_accuracy"]),
                      "n_reference": int(row["n_reference"])}
        for _, row in acc["per_class"].iterrows()
    }
    top3 = results["importances"].head(3)
    return {
        "study_area": cfg["study_area"]["name"],
        "crs": cfg["study_area"]["crs"],
        "size_px": size,
        "pixel_size_m": cfg["study_area"]["pixel_size_m"],
        "seed": seed,
        "dates": cfg["dates"],
        "runtime_s": round(runtime_s, 2),
        "overall_accuracy": acc["overall_accuracy"],
        "kappa": acc["kappa"],
        "n_test_samples": acc["n_samples"],
        "per_class_accuracy": per_class,
        "forest_area_t1_ha": stats["forest_area_t1_ha"],
        "forest_area_t2_ha": stats["forest_area_t2_ha"],
        "forest_loss_ha": stats["forest_loss_ha"],
        "forest_loss_pct_of_t1": stats["forest_loss_pct_of_t1"],
        "annual_loss_rate_pct": stats["annual_loss_rate_pct"],
        "forest_gain_ha": stats["forest_gain_ha"],
        "n_loss_patches": stats["n_loss_patches"],
        "mean_patch_ha": stats["mean_patch_ha"],
        "max_patch_ha": stats["max_patch_ha"],
        "loss_share_near_roads_pct": stats["loss_share_near_roads_pct"],
        "road_distance_m": stats["road_distance_m"],
        "evidence_rule": stats["evidence_rule"],
        "dnbr_loss_threshold": stats["dnbr_loss_threshold"],
        "mmu_ha": stats["mmu_ha"],
        "mmu_pixels": stats["mmu_pixels"],
        "post_classification_loss_ha": stats["post_classification_loss_ha"],
        "dnbr_loss_ha": stats["dnbr_loss_ha"],
        "synthetic_truth_loss_ha": stats["truth_loss_ha"],
        "synthetic_truth_detected_pct": stats["truth_loss_detected_pct"],
        "false_alarm_ha": stats["false_alarm_ha"],
        "top3_features": {k: float(v) for k, v in top3.items()},
        "class_area_t1_ha": stats["class_area_t1_ha"],
        "class_area_t2_ha": stats["class_area_t2_ha"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Forest change detection demo (synthetic Sentinel-2 scene)")
    parser.add_argument("--size", type=int, default=None, help="raster size in pixels (default from config: 200)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="results/demo")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    cfg = load_config(ROOT / "config.yaml")
    size = args.size or int(cfg["study_area"]["default_size_px"])
    out_dir = ensure_directory(ROOT / args.out)
    fig_dir = ROOT / "docs" / "figures"
    cd = cfg["change_detection"]
    cl = cfg["classification"]

    print(f"[1/5] Generating synthetic scene ({size}x{size} px, seed {args.seed}) -> {out_dir / 'data'}")
    data = generate_demo_data(size=size, seed=args.seed, out_dir=out_dir / "data",
                              clearing_intensity=float(cfg["synthetic"]["clearing_intensity"]),
                              pixel_size=float(cfg["study_area"]["pixel_size_m"]))

    print("[2/5] Indices, Random Forest (both dates), accuracy, change detection, MMU, vectorise")
    results = run_pipeline(
        data, out_dir=out_dir,
        forest_class=int(cfg["classes"]["forest_class"]),
        n_per_class=int(cl["n_samples_per_class"]),
        n_estimators=int(cl["random_forest"]["n_estimators"]),
        seed=args.seed,
        dnbr_loss_threshold=float(cd["dnbr_loss_threshold"]),
        evidence_rule=str(cd["evidence_rule"]),
        mmu_ha=float(cd["min_mapping_unit_ha"]),
        road_distance_m=float(cd["road_distance_m"]),
        years=float(cfg["dates"]["years_between"]),
    )

    print(f"[3/5] Figures -> {fig_dir}")
    save_all_figures(results, fig_dir, dates=cfg["dates"])

    map_path = ROOT / "docs" / "map.html"
    print(f"[4/5] Web map -> {map_path}")
    build_web_map(results, dates=cfg["dates"]).save(str(map_path))

    runtime = time.perf_counter() - t0
    summary = build_summary(results, size, args.seed, cfg, runtime)
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[5/5] Summary -> {out_dir / 'summary.json'}")
    print()
    for line in summary_lines(results["stats"], results["accuracy"], results["importances"],
                              header=f"Forest change summary  ({size}x{size} px, seed {args.seed}, "
                                     f"{cfg['dates']['t1']} -> {cfg['dates']['t2']})"):
        print(line)
    print(f" Runtime: {runtime:.1f} s")
    return summary


if __name__ == "__main__":
    main()
