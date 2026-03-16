#!/usr/bin/env python3
"""
Crop Health Monitoring — Full Pipeline Runner

Usage:
    python scripts/run_pipeline.py --config config.yaml --output results/
"""

import argparse
import logging
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sentinel_loader import SentinelLoader
from src.index_calculator import IndexCalculator
from src.time_series import TimeSeriesAnalyzer
from src.anomaly_detector import AnomalyDetector
from src.zonal_stats import ZonalFieldStats
from src.utils import ensure_directory, load_config, write_raster


def setup_logging(output_dir: str) -> None:
    log_dir = ensure_directory(Path(output_dir) / "logs")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / f"pipeline_{timestamp}.log"),
        ],
    )


def run_pipeline(config_path: str, output_dir: str) -> dict:
    logger = logging.getLogger("pipeline")
    config = load_config(config_path)

    output_dir = ensure_directory(output_dir)
    raster_dir = ensure_directory(output_dir / "rasters")
    vector_dir = ensure_directory(output_dir / "vectors")
    stats_dir = ensure_directory(output_dir / "statistics")
    plots_dir = ensure_directory(output_dir / "plots")

    results = {"timestamp": datetime.now().isoformat()}

    # ─── Step 1: Load Sentinel-2 Time Series ──────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Loading Sentinel-2 Time Series")
    logger.info("=" * 60)

    loader = SentinelLoader(config_path)
    scenes = loader.load_time_series("data/sentinel2/")

    results["scenes_loaded"] = len(scenes)
    results["dates"] = [s["date"].strftime("%Y-%m-%d") for s in scenes]

    # ─── Step 2: Compute Vegetation Indices ───────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: Computing Vegetation Indices")
    logger.info("=" * 60)

    calculator = IndexCalculator()
    indices_to_compute = config["indices"]["compute"]

    for scene in scenes:
        computed = calculator.compute_all(scene, indices=indices_to_compute)
        scene.update(computed)

        # Save per-date index rasters
        date_str = scene["date"].strftime("%Y%m%d")
        for idx_name, idx_array in computed.items():
            if "profile" in scene:
                write_raster(
                    idx_array,
                    scene["profile"],
                    str(raster_dir / f"{idx_name}_{date_str}.tif"),
                )

    # ─── Step 3: Time Series & Phenology Analysis ─────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: Phenology Analysis")
    logger.info("=" * 60)

    ts_analyzer = TimeSeriesAnalyzer()

    dates, ndvi_stack, doy = ts_analyzer.extract_pixel_time_series(scenes, "ndvi")
    smoothed = ts_analyzer.smooth_time_series(ndvi_stack, method="savgol")
    phenology = ts_analyzer.fit_phenology_curve(doy, smoothed)
    peak_metrics = ts_analyzer.get_peak_metrics(phenology)

    import numpy as np

    results["phenology"] = {
        "mean_peak_doy": int(np.nanmean(peak_metrics["peak_doy"])),
        "mean_peak_ndvi": round(float(np.nanmean(peak_metrics["peak_value"])), 3),
        "mean_season_length": int(np.nanmean(peak_metrics["growing_season_length"])),
    }

    # Save peak metrics
    if scenes and "profile" in scenes[0]:
        profile = scenes[0]["profile"]
        write_raster(peak_metrics["peak_value"], profile, str(raster_dir / "peak_ndvi.tif"))
        write_raster(peak_metrics["peak_doy"], profile, str(raster_dir / "peak_doy.tif"))

    # ─── Step 4: Anomaly Detection ────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: Anomaly Detection")
    logger.info("=" * 60)

    detector = AnomalyDetector(config_path)

    # Detect anomalies on the latest scene
    latest_scene = scenes[-1]
    latest_ndvi = latest_scene.get("ndvi")

    if latest_ndvi is not None:
        # Use phenology-expected as baseline
        expected_latest = phenology["expected"][-1] if phenology["expected"].shape[0] > 0 else None

        anomaly_mask, anomaly_stats = detector.detect(
            current=latest_ndvi,
            baseline=expected_latest,
            profile=latest_scene.get("profile"),
            output_path=str(raster_dir / "anomaly_map.tif"),
        )

        results["anomalies"] = anomaly_stats

    # ─── Step 5: Field-Level Zonal Statistics ─────────────────────
    logger.info("=" * 60)
    logger.info("STEP 5: Field-Level Statistics")
    logger.info("=" * 60)

    field_boundaries = config["study_area"]["field_boundaries"]
    zonal = ZonalFieldStats(field_boundaries, config_path)

    field_report = zonal.compute(
        scenes,
        indices=indices_to_compute,
        output_csv=str(stats_dir / "field_health_report.csv"),
    )

    change_report = zonal.compute_change_report(scenes, index_name="ndvi")
    if not change_report.empty:
        change_report.to_csv(stats_dir / "field_change_report.csv", index=False)

    summary = zonal.generate_summary(
        field_report,
        output_path=str(stats_dir / "season_summary.json"),
    )
    results["field_summary"] = summary

    # ─── Save Pipeline Results ────────────────────────────────────
    results_path = stats_dir / "pipeline_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Results saved to: {output_dir}")
    logger.info("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(description="Crop Health Monitoring Pipeline")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="results")
    args = parser.parse_args()

    setup_logging(args.output)
    run_pipeline(args.config, args.output)


if __name__ == "__main__":
    main()
