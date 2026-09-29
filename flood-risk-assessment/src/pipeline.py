"""
End-to-end flood risk pipeline.

    DEM fill -> slope -> D8 flow direction -> flow accumulation -> TWI ->
    streams -> distance to streams -> AHP flood susceptibility ->
    vulnerability -> risk (classify, vectorise, exposure) -> return-period scenarios

``run_pipeline`` is the single entry point used by demo.py, app.py,
scripts/run_pipeline.py and the tests, so the logic lives in one place.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np

from .dem_processor import DEMProcessor
from .flood_susceptibility import FloodSusceptibility
from .risk_calculator import RISK_CLASSES, RiskCalculator
from .utils import ensure_directory, load_config, read_raster, write_raster
from .vulnerability import VulnerabilityAssessor

logger = logging.getLogger(__name__)


def run_pipeline(
    config: Union[str, Path, dict],
    data: Dict,
    out_dir: Optional[Union[str, Path]] = None,
    stream_threshold: Optional[int] = None,
    risk_method: Optional[str] = None,
    high_risk_threshold: Optional[float] = None,
    return_periods: Optional[list] = None,
    write_outputs: bool = True,
) -> Dict:
    """
    Run the full pipeline on one scene.

    Args:
        config: config.yaml path or dict
        data: dict with input paths as returned by ``synthetic_data.generate_demo_data``
              (keys: dem, rainfall, ksat, nlcd, population, infrastructure, census_svi)
        out_dir: where rasters/vectors are written (only when write_outputs)
        stream_threshold: flow accumulation threshold in cells (default from config)
        risk_method: multiplicative | geometric_mean | matrix (default from config)
        high_risk_threshold: risk index value that starts the "High" class
        return_periods: list of return periods for the scenarios (default from config)
        write_outputs: write GeoTIFFs / GeoPackages to out_dir

    Returns:
        dict with arrays (dem_filled, slope, flow_dir, flow_acc, twi, streams,
        river_distance, susceptibility, vulnerability, risk, risk_classes),
        GeoDataFrames (streams_gdf, risk_zones, facilities), the raster
        profile, statistics (ahp, susceptibility_stats, vulnerability_stats,
        exposure, scenarios, facilities_at_risk) and a flat 'summary' dict.
    """
    cfg = load_config(config)
    out_dir = Path(out_dir) if out_dir is not None else None
    if write_outputs and out_dir is None:
        raise ValueError("out_dir is required when write_outputs=True")
    raster_dir = ensure_directory(out_dir / "rasters") if write_outputs else None
    vector_dir = ensure_directory(out_dir / "vectors") if write_outputs else None

    def rpath(name):
        return str(raster_dir / name) if write_outputs else None

    stream_threshold = int(stream_threshold or cfg["stream_network"]["accumulation_threshold"])
    risk_cfg = cfg.get("risk", {})
    risk_method = risk_method or risk_cfg.get("method", "geometric_mean")
    thresholds = dict(risk_cfg.get("classification", {"very_high": 0.8, "high": 0.6,
                                                       "moderate": 0.4, "low": 0.2}))
    if high_risk_threshold is not None:
        thresholds["high"] = float(high_risk_threshold)
        thresholds["very_high"] = max(thresholds["very_high"], thresholds["high"] + 0.1)
    return_periods = list(return_periods or cfg["scenarios"]["return_periods"])

    # ---------------------------------------------------------- 1. hydrology
    dem = DEMProcessor(cfg, dem_path=data["dem"])
    profile = dem.profile
    dem_original = dem.dem.copy()
    dem_filled = dem.fill_sinks(output_path=rpath("dem_filled.tif"))
    slope = dem.compute_slope(output_path=rpath("slope.tif"))
    flow_dir = dem.compute_flow_direction(output_path=rpath("flow_direction.tif"))
    flow_acc = dem.compute_flow_accumulation(flow_dir, output_path=rpath("flow_accumulation.tif"))
    twi = dem.compute_twi(flow_acc, slope, output_path=rpath("twi.tif"))
    streams = dem.extract_stream_network(flow_acc, threshold=stream_threshold,
                                         output_path=rpath("streams.tif"))
    river_distance = dem.compute_distance_to_streams(streams, output_path=rpath("river_distance.tif"))
    streams_gdf = dem.streams_to_vector(streams, flow_dir, flow_acc)
    if write_outputs and len(streams_gdf):
        streams_gdf.to_file(vector_dir / "streams.gpkg", driver="GPKG")

    # ----------------------------------------------------- 2. susceptibility
    susc_model = FloodSusceptibility(cfg)
    susceptibility, susc_stats = susc_model.compute(
        twi=twi, slope=slope, river_distance=river_distance, rainfall=data["rainfall"],
        elevation=dem_filled, soil_perm=data["ksat"], lulc=data["nlcd"],
        profile=profile, output_path=rpath("flood_susceptibility.tif"),
    )

    # ------------------------------------------------------- 3. vulnerability
    vuln_model = VulnerabilityAssessor(cfg)
    vulnerability, vuln_stats = vuln_model.compute(
        population=data["population"], infrastructure=data["infrastructure"],
        socioeconomic=data["census_svi"], profile=profile,
        output_path=rpath("vulnerability.tif"),
    )

    # ---------------------------------------------------------------- 4. risk
    risk_calc = RiskCalculator(method=risk_method, thresholds=thresholds)
    risk = risk_calc.compute(susceptibility, vulnerability, output_path=rpath("flood_risk.tif"),
                             profile=profile)
    risk_classes = risk_calc.classify(risk)
    if write_outputs:
        write_raster(risk_classes.astype(np.float64), profile, raster_dir / "flood_risk_classes.tif")
    risk_zones = risk_calc.classify_and_export(
        risk, str(vector_dir / "flood_risk_zones.gpkg") if write_outputs else None, profile=profile
    )
    exposure = risk_calc.compute_exposure_statistics(risk, data["population"], profile)
    n_facilities_at_risk, facilities = risk_calc.facilities_at_risk(risk_zones, data["infrastructure"])
    if write_outputs:
        facilities.to_file(vector_dir / "facilities_risk.gpkg", driver="GPKG")

    # ----------------------------------------------------------- 5. scenarios
    scenarios = {}
    valid = np.sum(~np.isnan(risk))
    for rp in return_periods:
        hazard_rp = susc_model.run_scenario(susceptibility, rp)
        risk_rp = risk_calc.compute(hazard_rp, vulnerability,
                                    output_path=rpath(f"risk_{rp}yr.tif"), profile=profile)
        classes_rp = risk_calc.classify(risk_rp)
        exposure_rp = risk_calc.compute_exposure_statistics(risk_rp, data["population"], profile)
        scenarios[int(rp)] = {
            "factor": float(cfg["scenarios"]["return_period_factors"].get(rp, 1.0)),
            "mean_risk": round(float(np.nanmean(risk_rp)), 4),
            "high_risk_percent": round(float(np.sum(classes_rp >= 4) / valid * 100), 2),
            "very_high_risk_percent": round(float(np.sum(classes_rp == 5) / valid * 100), 2),
            "population_high_very_high": int(
                exposure_rp["High"]["estimated_population"] + exposure_rp["Very High"]["estimated_population"]
            ),
        }

    # ------------------------------------------------------------- summary
    pixel_km2 = (abs(profile["transform"][0]) * abs(profile["transform"][4])) / 1e6
    total_pop = int(round(np.nansum(read_raster(data["population"])[0]) * pixel_km2))
    summary = {
        "grid": f"{risk.shape[0]} x {risk.shape[1]} cells at {dem.resolution:.0f} m",
        "area_km2": round(float(risk.size * pixel_km2), 2),
        "sink_cells_filled": int(np.sum((dem_filled - dem_original) > 1e-6)),
        "stream_threshold_cells": stream_threshold,
        "stream_cells": int(np.sum(streams > 0)),
        "stream_length_km": round(float(streams_gdf["length_m"].sum() / 1000), 2) if len(streams_gdf) else 0.0,
        "ahp_weights": {k: round(v, 4) for k, v in susc_model.ahp.get_weight_dict().items()},
        "ahp_lambda_max": susc_model.consistency["lambda_max"],
        "ahp_CI": susc_model.consistency["CI"],
        "ahp_CR": susc_model.consistency["CR"],
        "ahp_consistent": susc_model.consistency["is_consistent"],
        "susceptibility_class_pct": {k: v["area_percent"] for k, v in susc_stats.items()},
        "mean_susceptibility": round(float(np.nanmean(susceptibility)), 4),
        "mean_vulnerability": vuln_stats["mean_vulnerability"],
        "risk_method": risk_method,
        "risk_thresholds": thresholds,
        "mean_risk": round(float(np.nanmean(risk)), 4),
        "risk_class_pct": {name: exposure[name]["area_pct"] for name in RISK_CLASSES.values()},
        "risk_class_km2": {name: exposure[name]["area_km2"] for name in RISK_CLASSES.values()},
        "high_very_high_pct": round(exposure["High"]["area_pct"] + exposure["Very High"]["area_pct"], 2),
        "total_population": total_pop,
        "population_high_very_high": int(
            exposure["High"]["estimated_population"] + exposure["Very High"]["estimated_population"]
        ),
        "facilities_total": int(len(facilities)),
        "facilities_high_very_high": n_facilities_at_risk,
        "facilities_by_type_at_risk": facilities[facilities["risk_class"] >= 4]["type"].value_counts().to_dict()
        if "type" in facilities.columns else {},
        "scenario_high_risk_pct": {rp: s["high_risk_percent"] for rp, s in scenarios.items()},
    }

    return {
        "profile": profile,
        "resolution": dem.resolution,
        "dem": dem_original,
        "dem_filled": dem_filled,
        "slope": slope,
        "flow_dir": flow_dir,
        "flow_acc": flow_acc,
        "twi": twi,
        "streams": streams,
        "river_distance": river_distance,
        "streams_gdf": streams_gdf,
        "susceptibility": susceptibility,
        "susceptibility_stats": susc_stats,
        "criterion_means": susc_model.criterion_means,
        "vulnerability": vulnerability,
        "vulnerability_stats": vuln_stats,
        "risk": risk,
        "risk_classes": risk_classes,
        "risk_zones": risk_zones,
        "exposure": exposure,
        "facilities": facilities,
        "facilities_at_risk": n_facilities_at_risk,
        "scenarios": scenarios,
        "ahp": {"weights": summary["ahp_weights"], **susc_model.consistency},
        "summary": summary,
    }
