"""
End-to-end UHI pipeline runner.

Chains the four analysis modules in order and collects every output in
one dict so ``demo.py``, ``app.py`` and the tests share the same code:

    LSTProcessor.compute_lst -> compute_lst_anomaly
    UHIClassifier.classify -> vectorize_zones
    LULCCorrelator.cross_tabulate -> compute_lst_by_lulc -> compute_impervious_correlation
    MitigationMapper.generate -> classify_priority_zones
"""

import json
import logging
from pathlib import Path
from typing import Dict, Union

import numpy as np
import geopandas as gpd

from .lst_processor import LSTProcessor
from .uhi_classifier import UHIClassifier, UHI_CLASSES
from .lulc_correlator import LULCCorrelator
from .mitigation_mapper import MitigationMapper
from .utils import read_raster, write_raster, ensure_directory

logger = logging.getLogger(__name__)

# NLCD codes treated as the "rural" reference for the UHI baseline
RURAL_CODES = [41, 42, 43, 52, 71, 81, 82]


def run_pipeline(
    data: Dict,
    config: Union[str, Path, dict],
    out_dir: Union[str, Path],
    study_area_name: str = "Phoenix, AZ (synthetic)",
) -> Dict:
    """
    Run the full chain on one scene.

    Args:
        data: dict with file paths ``thermal``, ``red``, ``nir``, ``lulc``,
            ``impervious``, ``population``, ``parks`` (the dict returned by
            ``synthetic_data.generate_demo_data`` works directly)
        config: path to config.yaml or an already-loaded config dict
        out_dir: folder for rasters/, vectors/, statistics/ and summary.json

    Returns:
        dict with keys
            lst, anomaly, uhi, mpi       numpy arrays (float, float, int16, float)
            lulc, impervious, population numpy arrays read from the inputs
            profile                      rasterio profile of the outputs
            uhi_stats, mpi_stats         per-class dicts from the modules
            uhi_gdf, priority_gdf        dissolved zone polygons
            parks_gdf                    park polygons (input)
            crosstab, lst_by_lulc        pandas DataFrames
            impervious_corr              dict with pearson_r, slope, ...
            rural_baseline_c             LST baseline used for the anomaly
            summary                      dict of headline metrics
            paths                        dict of every file written
    """
    out_dir = ensure_directory(out_dir)
    raster_dir = ensure_directory(out_dir / "rasters")
    vector_dir = ensure_directory(out_dir / "vectors")
    stats_dir = ensure_directory(out_dir / "statistics")
    paths = {}

    # Step 1: Land surface temperature and its anomaly vs the rural baseline
    processor = LSTProcessor(config)
    paths["lst"] = str(raster_dir / "lst_celsius.tif")
    lst, profile = processor.compute_lst(
        thermal_band=data["thermal"],
        red_band=data["red"],
        nir_band=data["nir"],
        output_path=paths["lst"],
    )

    lulc, _ = read_raster(data["lulc"])
    rural_mask = np.isin(lulc, RURAL_CODES)
    anomaly = processor.compute_lst_anomaly(lst, rural_mask=rural_mask)
    baseline = float(processor.last_baseline)
    paths["anomaly"] = write_raster(anomaly, profile, raster_dir / "lst_anomaly.tif")

    # Step 2: UHI classes and their polygons
    classifier = UHIClassifier(config)
    paths["uhi"] = str(raster_dir / "uhi_classified.tif")
    uhi, uhi_stats = classifier.classify(lst, profile=profile, output_path=paths["uhi"])
    paths["uhi_zones"] = str(vector_dir / "uhi_zones.gpkg")
    uhi_gdf = classifier.vectorize_zones(uhi, profile, output_path=paths["uhi_zones"])

    # Step 3: Land cover relationships
    correlator = LULCCorrelator(config)
    crosstab = correlator.cross_tabulate(uhi, data["lulc"])
    paths["crosstab"] = str(stats_dir / "uhi_lulc_crosstab.csv")
    crosstab.to_csv(paths["crosstab"], index=False)

    lst_by_lulc = correlator.compute_lst_by_lulc(lst, data["lulc"])
    paths["lst_by_lulc"] = str(stats_dir / "lst_by_lulc.csv")
    lst_by_lulc.to_csv(paths["lst_by_lulc"], index=False)

    impervious_corr = correlator.compute_impervious_correlation(lst, data["impervious"])
    impervious, _ = read_raster(data["impervious"])

    # Step 4: Mitigation priority index and zones
    mapper = MitigationMapper(config)
    paths["mpi"] = str(raster_dir / "mitigation_priority.tif")
    mpi, mpi_stats = mapper.generate(
        uhi_zones=uhi,
        lst_anomaly=anomaly,
        population_raster=data["population"],
        greenspace_vector=data["parks"],
        profile=profile,
        output_path=paths["mpi"],
    )
    paths["priority_zones"] = str(vector_dir / "mitigation_priority_zones.gpkg")
    priority_gdf = mapper.classify_priority_zones(mpi, profile, output_path=paths["priority_zones"])

    parks_gdf = gpd.read_file(data["parks"])
    if parks_gdf.crs != profile["crs"]:
        parks_gdf = parks_gdf.to_crs(profile["crs"])
    population, _ = read_raster(data["population"])

    results = {
        "lst": lst,
        "anomaly": anomaly,
        "uhi": uhi,
        "mpi": mpi,
        "lulc": lulc,
        "impervious": impervious,
        "population": population,
        "profile": profile,
        "uhi_stats": uhi_stats,
        "mpi_stats": mpi_stats,
        "uhi_gdf": uhi_gdf,
        "priority_gdf": priority_gdf,
        "parks_gdf": parks_gdf,
        "crosstab": crosstab,
        "lst_by_lulc": lst_by_lulc,
        "impervious_corr": impervious_corr,
        "rural_baseline_c": baseline,
        "paths": paths,
    }
    results["summary"] = build_summary(results, study_area_name)

    paths["summary"] = str(out_dir / "summary.json")
    with open(paths["summary"], "w") as f:
        json.dump(results["summary"], f, indent=2)

    return results


def build_summary(results: Dict, study_area_name: str) -> Dict:
    """Collect the headline numbers that the demo prints and the README quotes."""
    lst = results["lst"]
    profile = results["profile"]
    uhi_stats = results["uhi_stats"]
    mpi_stats = results["mpi_stats"]
    corr = results["impervious_corr"]
    lst_by_lulc = results["lst_by_lulc"]
    priority_gdf = results["priority_gdf"]

    pixel_area_ha = abs(profile["transform"].a * profile["transform"].e) / 10000.0

    def zone_area_ha(label: str) -> float:
        if priority_gdf.empty:
            return 0.0
        sel = priority_gdf[priority_gdf["priority_label"] == label]
        return round(float(sel["area_ha"].sum()), 2) if not sel.empty else 0.0

    uhi_area = {name: uhi_stats[name]["area_percent"] for _, name in sorted(UHI_CLASSES.items())}
    strong_plus = round(uhi_area.get("Strong", 0.0) + uhi_area.get("Extreme", 0.0), 2)

    hottest = lst_by_lulc.head(3)[["lulc_name", "mean_lst"]].to_dict("records")
    coolest = lst_by_lulc.tail(3).iloc[::-1][["lulc_name", "mean_lst"]].to_dict("records")

    return {
        "study_area": study_area_name,
        "grid": {
            "size_px": [int(profile["height"]), int(profile["width"])],
            "resolution_m": float(abs(profile["transform"].a)),
            "area_km2": round(float(profile["height"] * profile["width"] * pixel_area_ha / 100.0), 2),
            "crs": str(profile["crs"]),
        },
        "lst": {
            "mean_c": round(float(np.nanmean(lst)), 2),
            "max_c": round(float(np.nanmax(lst)), 2),
            "min_c": round(float(np.nanmin(lst)), 2),
            "std_c": round(float(np.nanstd(lst)), 2),
            "rural_baseline_c": round(results["rural_baseline_c"], 2),
            "max_anomaly_c": round(float(np.nanmax(results["anomaly"])), 2),
        },
        "uhi_area_percent": uhi_area,
        "uhi_strong_plus_extreme_percent": strong_plus,
        "lst_vs_impervious": {
            "pearson_r": corr["pearson_r"],
            "slope_c_per_percent": corr["slope"],
            "intercept_c": corr["intercept"],
            "p_value": corr["p_value"],
            "n_samples": corr["n_samples"],
            "interpretation": corr["interpretation"],
        },
        "mpi": {
            "high_percent": mpi_stats["high_priority"]["percent"],
            "medium_percent": mpi_stats["medium_priority"]["percent"],
            "low_percent": mpi_stats["low_priority"]["percent"],
            "mean_mpi": mpi_stats["mean_mpi"],
        },
        "priority_area_ha": {
            "high": zone_area_ha("High"),
            "medium": zone_area_ha("Medium"),
            "low": zone_area_ha("Low"),
        },
        "top_hottest_lulc": hottest,
        "coolest_lulc": coolest,
    }


def format_summary(summary: Dict) -> str:
    """Plain-text summary table for the terminal."""
    lines = []
    add = lines.append
    add("=" * 62)
    add(f"Urban Heat Island Analysis: {summary['study_area']}")
    add("=" * 62)
    g = summary["grid"]
    add(f"Grid: {g['size_px'][0]} x {g['size_px'][1]} px at {g['resolution_m']:.0f} m "
        f"({g['area_km2']} km2), {g['crs']}")
    add("")
    add(f"{'Metric':<40}{'Value':>20}")
    add("-" * 62)
    l = summary["lst"]
    add(f"{'Mean LST (deg C)':<40}{l['mean_c']:>20.2f}")
    add(f"{'Max LST (deg C)':<40}{l['max_c']:>20.2f}")
    add(f"{'Min LST (deg C)':<40}{l['min_c']:>20.2f}")
    add(f"{'Rural baseline LST (deg C)':<40}{l['rural_baseline_c']:>20.2f}")
    add(f"{'Max UHI intensity above rural (deg C)':<40}{l['max_anomaly_c']:>20.2f}")
    add("-" * 62)
    for name, pct in summary["uhi_area_percent"].items():
        add(f"{'UHI class ' + name + ' (% area)':<40}{pct:>20.2f}")
    add(f"{'Strong + Extreme UHI (% area)':<40}{summary['uhi_strong_plus_extreme_percent']:>20.2f}")
    add("-" * 62)
    c = summary["lst_vs_impervious"]
    add(f"{'LST vs impervious Pearson r':<40}{c['pearson_r']:>20.3f}")
    add(f"{'LST vs impervious slope (deg C per %)':<40}{c['slope_c_per_percent']:>20.4f}")
    add(f"{'Samples used':<40}{c['n_samples']:>20d}")
    add("-" * 62)
    m = summary["mpi"]
    add(f"{'MPI high priority (% area)':<40}{m['high_percent']:>20.2f}")
    add(f"{'MPI medium priority (% area)':<40}{m['medium_percent']:>20.2f}")
    add(f"{'MPI low priority (% area)':<40}{m['low_percent']:>20.2f}")
    a = summary["priority_area_ha"]
    add(f"{'High priority zone area (ha)':<40}{a['high']:>20.2f}")
    add(f"{'Medium priority zone area (ha)':<40}{a['medium']:>20.2f}")
    add("-" * 62)
    add("Top 3 hottest land cover classes (mean LST):")
    for i, row in enumerate(summary["top_hottest_lulc"], start=1):
        add(f"  {i}. {row['lulc_name']:<34}{row['mean_lst']:>8.2f} deg C")
    add("Coolest land cover classes (mean LST):")
    for i, row in enumerate(summary["coolest_lulc"], start=1):
        add(f"  {i}. {row['lulc_name']:<34}{row['mean_lst']:>8.2f} deg C")
    add("=" * 62)
    return "\n".join(lines)
