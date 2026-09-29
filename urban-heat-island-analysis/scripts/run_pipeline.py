#!/usr/bin/env python3
"""
Urban Heat Island Analysis: full pipeline on REAL data.

Usage:
    python scripts/run_pipeline.py --config config.yaml --output results/real [--data data]

Expects these files in the data folder (all on the same 30 m grid and CRS):
    LC09_B10.TIF   Landsat 8/9 Collection 2 Level-2 ST_B10 (thermal)
    LC09_B4.TIF    SR_B4 red reflectance
    LC09_B5.TIF    SR_B5 NIR reflectance
    nlcd_lulc.tif  NLCD land cover codes
    impervious.tif NLCD impervious surface percent
    population_density.tif   people per km2
    parks_greenspace.gpkg    park polygons

For a no-download demo on a synthetic scene use ``python demo.py`` instead.
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run_pipeline, format_summary  # noqa: E402
from src.utils import ensure_directory, load_config  # noqa: E402
from src.visualize import make_all_figures, build_web_map  # noqa: E402


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


def main():
    parser = argparse.ArgumentParser(description="Urban Heat Island Analysis Pipeline (real data)")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to configuration YAML file")
    parser.add_argument("--output", type=str, default="results/real", help="Output directory for results")
    parser.add_argument("--data", type=str, default=None, help="Input data folder (default: config data_directory)")
    parser.add_argument("--figures", action="store_true", help="Also write figures and the Folium map into the output folder")
    args = parser.parse_args()

    setup_logging(args.output)
    config = load_config(args.config)
    data_dir = Path(args.data or config.get("data_directory", "data"))

    def pick(name: str, config_key: str) -> str:
        """File in the data folder, else the path named in config.yaml."""
        candidate = data_dir / name
        if candidate.exists():
            return str(candidate)
        return str(config["mitigation"].get(config_key, candidate))

    data = {
        "thermal": str(data_dir / "LC09_B10.TIF"),
        "red": str(data_dir / "LC09_B4.TIF"),
        "nir": str(data_dir / "LC09_B5.TIF"),
        "lulc": str(data_dir / "nlcd_lulc.tif"),
        "impervious": str(data_dir / "impervious.tif"),
        "population": pick("population_density.tif", "population_raster"),
        "parks": pick("parks_greenspace.gpkg", "greenspace_vector"),
    }
    missing = [p for p in data.values() if not Path(p).exists()]
    if missing:
        sys.exit("Missing input files:\n  " + "\n  ".join(missing))

    results = run_pipeline(data, config, args.output, study_area_name=config["study_area"]["name"])
    if args.figures:
        make_all_figures(results, Path(args.output) / "figures")
        build_web_map(results).save(str(Path(args.output) / "map.html"))

    print(format_summary(results["summary"]))
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
