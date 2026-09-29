#!/usr/bin/env python3
"""
Flood Risk Assessment: full pipeline runner for real (or demo) data.

Reads the input layer paths from config.yaml (dem.source + inputs.*),
runs src.pipeline.run_pipeline and writes rasters, vectors and a JSON
report. To run on your own data, edit the paths in config.yaml.

Usage:
    python scripts/run_pipeline.py --config config.yaml --output results/run
    python scripts/run_pipeline.py --figures   # also write figures + web map
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
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / f"pipeline_{timestamp}.log"),
        ],
    )


def inputs_from_config(config: dict, base_dir: Path) -> dict:
    """Resolve the layer paths in config.yaml relative to the project folder."""
    def resolve(p):
        p = Path(p)
        return str(p if p.is_absolute() else base_dir / p)

    inputs = config["inputs"]
    data = {
        "dem": resolve(config["dem"]["source"]),
        "rainfall": resolve(inputs["rainfall"]),
        "ksat": resolve(inputs["soil_permeability"]),
        "nlcd": resolve(inputs["lulc"]),
        "population": resolve(inputs["population"]),
        "infrastructure": resolve(inputs["infrastructure"]),
        "census_svi": resolve(inputs["socioeconomic"]),
    }
    missing = [k for k, v in data.items() if not Path(v).exists()]
    if missing:
        raise FileNotFoundError(
            f"Input layers not found for {missing}. Run `python demo.py` for the synthetic scene "
            "or point config.yaml to your own files."
        )
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Flood Risk Assessment Pipeline")
    parser.add_argument("--config", default=str(PROJECT_DIR / "config.yaml"))
    parser.add_argument("--output", default=str(PROJECT_DIR / "results" / "run"))
    parser.add_argument("--figures", action="store_true", help="also write figures and the web map")
    args = parser.parse_args()

    output_dir = ensure_directory(args.output)
    setup_logging(output_dir)
    logger = logging.getLogger("pipeline")

    config = load_config(args.config)
    data = inputs_from_config(config, PROJECT_DIR)

    logger.info("Running flood risk pipeline")
    results = run_pipeline(config, data, out_dir=output_dir)

    report = {
        "timestamp": datetime.now().isoformat(),
        "inputs": data,
        "summary": results["summary"],
        "ahp": results["ahp"],
        "susceptibility": results["susceptibility_stats"],
        "vulnerability": results["vulnerability_stats"],
        "exposure": results["exposure"],
        "scenarios": results["scenarios"],
    }
    stats_dir = ensure_directory(output_dir / "statistics")
    with open(stats_dir / "pipeline_results.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    if args.figures:
        from src.visualize import build_web_map, make_all_figures

        make_all_figures(results, output_dir / "figures")
        build_web_map(results).save(str(output_dir / "map.html"))

    logger.info("PIPELINE COMPLETE. Results saved to: %s", output_dir)


if __name__ == "__main__":
    main()
