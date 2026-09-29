#!/usr/bin/env python3
"""
Crop Health Monitoring: run the full pipeline on your own Sentinel-2 scenes.

    python scripts/run_pipeline.py --config config.yaml --output results/real \
        [--data-dir data/sentinel2] [--fields data/field_boundaries.geojson] [--figures]

Defaults for --data-dir and --fields come from config.yaml (study_area.sentinel_dir
and study_area.field_boundaries). Scene folders must be named S2*_MSIL2A_<YYYYMMDD>*
and contain B02.tif ... B12.tif plus SCL.tif (uint16 DN, reflectance x 10000).
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.pipeline import run_pipeline  # noqa: E402
from src.utils import ensure_directory, load_config  # noqa: E402


def setup_logging(output_dir: Path) -> None:
    log_dir = ensure_directory(output_dir / "logs")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / f"pipeline_{timestamp}.log")],
    )


def main():
    parser = argparse.ArgumentParser(description="Crop Health Monitoring Pipeline (real data)")
    parser.add_argument("--config", default=str(PROJECT_DIR / "config.yaml"))
    parser.add_argument("--output", default="results/real")
    parser.add_argument("--data-dir", default=None, help="folder of S2*_MSIL2A_* scene folders")
    parser.add_argument("--fields", default=None, help="field polygons (GeoJSON / GeoPackage / Shapefile)")
    parser.add_argument("--block-size", type=int, default=None, help="phenology fit block size (px)")
    parser.add_argument("--method", default=None, choices=[None, "z_score", "isolation_forest", "lof"])
    parser.add_argument("--figures", action="store_true", help="also write figures and the web map to --output")
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_directory(args.output)
    setup_logging(output_dir)
    logger = logging.getLogger("pipeline")

    data_dir = args.data_dir or config["study_area"].get("sentinel_dir", "data/sentinel2")
    fields = args.fields or config["study_area"]["field_boundaries"]
    method = args.method or config["anomaly"].get("method", "z_score")
    logger.info(f"Scenes: {data_dir} | fields: {fields} | anomaly method: {method}")

    res = run_pipeline(config, data_dir, fields_path=fields, out_dir=output_dir,
                       block_size=args.block_size, anomaly_method=method)

    if args.figures:
        from src.visualize import build_web_map, make_all_figures
        make_all_figures(res, config, output_dir / "figures")
        build_web_map(res, config).save(str(output_dir / "map.html"))

    with open(output_dir / "summary.json", "w") as f:
        json.dump(res["summary"], f, indent=2, default=str)
    logger.info(f"PIPELINE COMPLETE. Results saved to: {output_dir}")


if __name__ == "__main__":
    main()
