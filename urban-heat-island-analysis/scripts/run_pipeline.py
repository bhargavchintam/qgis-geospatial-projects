#!/usr/bin/env python3
"""
Urban Heat Island Analysis — Full Pipeline Runner

Usage:
    python scripts/run_pipeline.py --config config.yaml --output results/

    # Or run inside QGIS Python Console:
    exec(open('scripts/run_pipeline.py').read())
"""

import argparse
import logging
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lst_processor import LSTProcessor
from src.uhi_classifier import UHIClassifier
from src.lulc_correlator import LULCCorrelator
from src.mitigation_mapper import MitigationMapper
from src.utils import ensure_directory, load_config


def setup_logging(output_dir: str) -> None:
    """Configure logging to both console and file."""
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
    """
    Execute the full UHI analysis pipeline.

    Args:
        config_path: path to configuration YAML
        output_dir: directory for all outputs

    Returns:
        dict with pipeline results and statistics
    """
    logger = logging.getLogger("pipeline")
    config = load_config(config_path)

    output_dir = ensure_directory(output_dir)
    raster_dir = ensure_directory(output_dir / "rasters")
    vector_dir = ensure_directory(output_dir / "vectors")
    stats_dir = ensure_directory(output_dir / "statistics")

    results = {"timestamp": datetime.now().isoformat(), "config": config_path}

    # ─── Step 1: Land Surface Temperature ──────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Land Surface Temperature Derivation")
    logger.info("=" * 60)

    lst_processor = LSTProcessor(config_path)

    # Use configured or command-line data paths
    data_dir = Path(config.get("data_directory", "data"))
    lst, profile = lst_processor.compute_lst(
        thermal_band=str(data_dir / "LC09_B10.TIF"),
        red_band=str(data_dir / "LC09_B4.TIF"),
        nir_band=str(data_dir / "LC09_B5.TIF"),
        output_path=str(raster_dir / "lst_celsius.tif"),
    )

    lst_anomaly = lst_processor.compute_lst_anomaly(lst)

    results["lst"] = {
        "mean": round(float(lst[~(lst != lst)].mean()), 2),
        "max": round(float(lst[~(lst != lst)].max()), 2),
        "min": round(float(lst[~(lst != lst)].min()), 2),
    }

    # ─── Step 2: UHI Classification ───────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: UHI Zone Classification")
    logger.info("=" * 60)

    classifier = UHIClassifier(config_path)
    uhi_zones, uhi_stats = classifier.classify(
        lst,
        profile=profile,
        output_path=str(raster_dir / "uhi_classified.tif"),
    )

    uhi_vectors = classifier.vectorize_zones(
        uhi_zones,
        profile,
        output_path=str(vector_dir / "uhi_zones.gpkg"),
    )

    results["uhi_classification"] = uhi_stats

    # ─── Step 3: LULC Correlation ─────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: LULC Correlation Analysis")
    logger.info("=" * 60)

    correlator = LULCCorrelator(config_path)

    lulc_path = str(data_dir / "nlcd_lulc.tif")
    cross_tab = correlator.cross_tabulate(uhi_zones, lulc_path)
    cross_tab.to_csv(stats_dir / "uhi_lulc_crosstab.csv", index=False)

    lst_by_lulc = correlator.compute_lst_by_lulc(lst, lulc_path)
    lst_by_lulc.to_csv(stats_dir / "lst_by_lulc.csv", index=False)

    results["lulc_correlation"] = {
        "top_hot_classes": lst_by_lulc.head(3)[["lulc_name", "mean_lst"]].to_dict("records")
    }

    # ─── Step 4: Mitigation Priority Mapping ──────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: Mitigation Priority Mapping")
    logger.info("=" * 60)

    mapper = MitigationMapper(config_path)
    mpi, mpi_stats = mapper.generate(
        uhi_zones=uhi_zones,
        lst_anomaly=lst_anomaly,
        population_raster=config["mitigation"]["population_raster"],
        greenspace_vector=config["mitigation"]["greenspace_vector"],
        profile=profile,
        output_path=str(raster_dir / "mitigation_priority.tif"),
    )

    priority_zones = mapper.classify_priority_zones(
        mpi,
        profile,
        output_path=str(vector_dir / "mitigation_priority_zones.gpkg"),
    )

    results["mitigation"] = mpi_stats

    # ─── Save Results ─────────────────────────────────────────────
    results_path = stats_dir / "pipeline_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Results saved to: {output_dir}")
    logger.info("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Urban Heat Island Analysis Pipeline"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration YAML file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="results",
        help="Output directory for results",
    )
    args = parser.parse_args()

    setup_logging(args.output)
    run_pipeline(args.config, args.output)


if __name__ == "__main__":
    main()
