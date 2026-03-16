#!/usr/bin/env python3
"""
Flood Risk Assessment — Full Pipeline Runner

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

from src.dem_processor import DEMProcessor
from src.flood_susceptibility import FloodSusceptibility
from src.vulnerability import VulnerabilityAssessor
from src.risk_calculator import RiskCalculator
from src.utils import ensure_directory, load_config


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

    results = {"timestamp": datetime.now().isoformat()}

    # ─── Step 1: DEM Hydrological Processing ──────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: DEM Hydrological Processing")
    logger.info("=" * 60)

    dem = DEMProcessor(config_path)
    dem.fill_sinks(output_path=str(raster_dir / "dem_filled.tif"))

    slope = dem.compute_slope(output_path=str(raster_dir / "slope.tif"))
    flow_dir = dem.compute_flow_direction(output_path=str(raster_dir / "flow_direction.tif"))
    flow_acc = dem.compute_flow_accumulation(flow_dir, output_path=str(raster_dir / "flow_accumulation.tif"))
    twi = dem.compute_twi(flow_acc, slope, output_path=str(raster_dir / "twi.tif"))

    streams = dem.extract_stream_network(flow_acc, threshold=1000, output_path=str(raster_dir / "streams.tif"))
    river_dist = dem.compute_distance_to_streams(streams, output_path=str(raster_dir / "river_distance.tif"))

    # ─── Step 2: Flood Susceptibility ─────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: AHP-Based Flood Susceptibility")
    logger.info("=" * 60)

    susceptibility = FloodSusceptibility(config_path)
    hazard_map, hazard_stats = susceptibility.compute(
        twi=twi,
        slope=str(raster_dir / "slope.tif"),
        river_distance=str(raster_dir / "river_distance.tif"),
        rainfall="data/rainfall_100yr.tif",
        elevation=config["dem"]["source"],
        soil_perm="data/ksat.tif",
        lulc="data/nlcd.tif",
        profile=dem.profile,
        output_path=str(raster_dir / "flood_susceptibility.tif"),
    )

    results["susceptibility"] = hazard_stats
    results["ahp_consistency"] = susceptibility.consistency

    # ─── Step 3: Vulnerability Assessment ─────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: Vulnerability Assessment")
    logger.info("=" * 60)

    vuln = VulnerabilityAssessor(config_path)
    vuln_map, vuln_stats = vuln.compute(
        population="data/population_density.tif",
        infrastructure="data/critical_infrastructure.gpkg",
        socioeconomic="data/census_svi.gpkg",
        profile=dem.profile,
        output_path=str(raster_dir / "vulnerability.tif"),
    )

    results["vulnerability"] = vuln_stats

    # ─── Step 4: Composite Risk ───────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: Composite Risk Index")
    logger.info("=" * 60)

    risk_calc = RiskCalculator(method="geometric_mean")
    risk_map = risk_calc.compute(
        hazard_map, vuln_map,
        output_path=str(raster_dir / "flood_risk.tif"),
        profile=dem.profile,
    )

    risk_zones = risk_calc.classify_and_export(
        risk_map, str(vector_dir / "flood_risk_zones.gpkg"), profile=dem.profile
    )

    exposure = risk_calc.compute_exposure_statistics(
        risk_map, "data/population_density.tif", dem.profile
    )
    results["exposure"] = exposure

    # ─── Step 5: Scenario Analysis ────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 5: Scenario Analysis")
    logger.info("=" * 60)

    scenario_results = {}
    for rp in config["scenarios"]["return_periods"]:
        scenario_hazard = susceptibility.run_scenario(hazard_map, rp)
        scenario_risk = risk_calc.compute(
            scenario_hazard, vuln_map,
            output_path=str(raster_dir / f"risk_{rp}yr.tif"),
            profile=dem.profile,
        )

        high_risk_pct = float(np.sum(scenario_risk >= 0.6) / scenario_risk.size * 100)
        scenario_results[f"{rp}_year"] = {
            "mean_risk": round(float(np.nanmean(scenario_risk)), 4),
            "high_risk_percent": round(high_risk_pct, 2),
        }

    results["scenarios"] = scenario_results

    # Save results
    import numpy as np  # noqa: needed for JSON serialization
    results_path = stats_dir / "pipeline_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Results saved to: {output_dir}")
    logger.info("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(description="Flood Risk Assessment Pipeline")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="results")
    args = parser.parse_args()

    setup_logging(args.output)
    run_pipeline(args.config, args.output)


if __name__ == "__main__":
    main()
