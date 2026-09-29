"""
End-to-end crop health pipeline (load -> indices -> phenology -> anomalies -> field stats).

``run_pipeline`` is the single entry point used by ``demo.py``, ``app.py`` and
the tests, so the orchestration logic is not duplicated anywhere.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from .anomaly_detector import AnomalyDetector
from .index_calculator import IndexCalculator
from .sentinel_loader import SentinelLoader
from .time_series import TimeSeriesAnalyzer
from .utils import ensure_directory, write_raster
from .zonal_stats import HEALTH_CLASSES, ZonalFieldStats

logger = logging.getLogger(__name__)


def select_assessment_scene(scenes, cloud_cover_max: float) -> int:
    """Index of the latest scene whose cloud cover is within the limit."""
    for i in range(len(scenes) - 1, -1, -1):
        if scenes[i].get("cloud_percent", 0.0) <= cloud_cover_max:
            return i
    return int(np.argmin([s.get("cloud_percent", 0.0) for s in scenes]))


def run_pipeline(
    config: dict,
    data_dir,
    fields_path=None,
    fields: Optional[gpd.GeoDataFrame] = None,
    out_dir=None,
    block_size: Optional[int] = None,
    anomaly_method: str = "z_score",
    z_threshold: Optional[float] = None,
    min_cluster_ha: Optional[float] = None,
    run_comparison: bool = True,
    write_outputs: bool = True,
) -> Dict:
    """
    Run the full pipeline on a folder of Sentinel-2 scenes.

    Args:
        config: loaded config.yaml dict
        data_dir: folder with ``S2*_MSIL2A_*`` scene sub-folders
        fields_path / fields: field polygons (path or GeoDataFrame)
        out_dir: where rasters/CSVs are written when ``write_outputs``
        block_size: phenology fit block size in pixels (1 = per pixel);
            defaults to ``config["phenology"]["block_size"]`` (5)
        anomaly_method: "z_score" or "isolation_forest"
        z_threshold, min_cluster_ha: overrides of the config values
        run_comparison: also run the other anomaly method and report its %

    Returns a dict with (main keys): scenes, dates, doy, ndvi_stack, smoothed,
    phenology, peak_metrics, field_fit, assessment_idx, assessment_date,
    baseline, anomaly_mask, anomaly_stats, comparison_stats, stats_df,
    change_df, field_table (GeoDataFrame), summary, profile, fields, indices.
    """
    if fields is None:
        if fields_path is None:
            raise ValueError("Provide fields_path or fields")
        fields = gpd.read_file(fields_path)
    fields = fields.reset_index(drop=True)
    out_dir = Path(out_dir) if out_dir is not None else None
    if write_outputs and out_dir is None:
        raise ValueError("out_dir is required when write_outputs=True")

    # 1. load scenes (DN -> reflectance, 20 m -> 10 m, SCL cloud mask)
    loader = SentinelLoader(config=config)
    scenes = loader.load_time_series(str(data_dir))
    if not scenes:
        raise RuntimeError(f"No scenes loaded from {data_dir}")
    profile = scenes[0]["profile"]

    # 2. vegetation indices per scene
    calc = IndexCalculator()
    indices = list(config.get("indices", {}).get("compute", ["ndvi", "evi", "savi", "ndre", "ndwi"]))
    for scene in scenes:
        scene.update(calc.compute_all(scene, indices=indices))

    # 3. phenology: stack -> smooth -> block fit -> peak metrics -> field curves
    ph_cfg = config.get("phenology", {})
    if block_size is None:
        block_size = int(ph_cfg.get("block_size", 5))
    ts = TimeSeriesAnalyzer()
    dates, ndvi_stack, doy = ts.extract_pixel_time_series(scenes, "ndvi")
    smoothed = ts.smooth_time_series(
        ndvi_stack, method=ph_cfg.get("smoothing", "savgol"),
        window_length=int(ph_cfg.get("window_length", 5)), polyorder=int(ph_cfg.get("polyorder", 2)),
    )
    field_fit = ts.fit_field_curves(fields, ndvi_stack, profile, doy=doy)
    field_mask = field_fit["field_id_raster"] > 0
    # block fit on crop pixels only, so road/verge pixels do not pull block means down
    phenology = ts.fit_phenology_curve(doy, np.where(field_mask, smoothed, np.nan), block_size=block_size)
    peak_metrics = ts.get_peak_metrics(phenology)

    # 4. anomalies on the latest usable scene vs the field phenology baseline
    cloud_max = float(config["sentinel"].get("cloud_cover_max", 15))
    a_idx = select_assessment_scene(scenes, cloud_max)
    a_scene = scenes[a_idx]
    a_date = a_scene["date"].strftime("%Y-%m-%d")
    baseline = field_fit["expected_raster"][a_idx]
    current = np.where(field_mask, a_scene["ndvi"], np.nan)  # only crop pixels are assessed

    detector = AnomalyDetector(config=config)
    anomaly_path = str(out_dir / "rasters" / "anomaly_map.tif") if write_outputs else None
    anomaly_mask, anomaly_stats = detector.detect(
        current=current, baseline=baseline, method=anomaly_method, profile=profile,
        output_path=anomaly_path, threshold=z_threshold, min_cluster_ha=min_cluster_ha,
    )
    comparison_stats = None
    if run_comparison:
        other = "isolation_forest" if anomaly_method != "isolation_forest" else "z_score"
        _, comparison_stats = detector.detect(
            current=current, baseline=baseline, method=other, profile=profile,
            threshold=z_threshold, min_cluster_ha=min_cluster_ha,
        )

    # 5. field statistics, change report, assessment table, summary
    zonal = ZonalFieldStats(fields=fields, config=config)
    stats_csv = str(out_dir / "field_health_report.csv") if write_outputs else None
    stats_df = zonal.compute(scenes, indices=indices, output_csv=stats_csv)
    change_df = zonal.compute_change_report(stats_df=stats_df)

    table = zonal.field_table(stats_df, a_date, indices=indices)
    table["anomaly_pct"] = table["field_id"].map(zonal.anomaly_fraction_per_field(anomaly_mask, profile))
    if "mean_ndre" in table.columns:
        table = zonal.flag_ndre_stress(table, z_threshold=float(config.get("classification", {}).get("ndre_stress_z", -1.0)))
    pheno_cols = ["field_id", "peak_doy", "peak_value", "greenup_doy", "senescence_doy", "season_length_days", "r_squared"]
    ft = field_fit["table"]
    table = table.merge(ft[[c for c in pheno_cols if c in ft.columns]], on="field_id", how="left")
    table = gpd.GeoDataFrame(table, geometry="geometry", crs=fields.crs)

    summary = zonal.generate_summary(stats_df, change_df=change_df, assessment_date=a_date)
    summary["assessment"]["anomaly"] = anomaly_stats
    if comparison_stats is not None:
        summary["assessment"]["anomaly_comparison"] = comparison_stats
    summary["assessment"]["ndre_stress_fields"] = (
        table.loc[table.get("ndre_stress", pd.Series(False, index=table.index)) == True, "field_id"].tolist()
    )
    summary["scenes"] = [
        {"date": s["date"].strftime("%Y-%m-%d"), "cloud_percent": float(s.get("cloud_percent", 0.0)),
         "usable": bool(s.get("cloud_percent", 0.0) <= cloud_max)}
        for s in scenes
    ]
    pv = np.where(field_mask, peak_metrics["peak_value"], np.nan)
    pdoy = np.where(field_mask, peak_metrics["peak_doy"], np.nan)
    slen = np.where(field_mask, peak_metrics["growing_season_length"], np.nan)
    summary["phenology"] = {
        "block_size": block_size,
        "fitted_fraction": round(float(phenology["fitted_fraction"]), 4),
        "mean_peak_ndvi": round(float(np.nanmean(pv)), 4),
        "mean_peak_doy": round(float(np.nanmean(pdoy)), 1),
        "mean_season_length_days": round(float(np.nanmean(slen)), 1),
        "mean_r_squared": round(float(np.nanmean(np.where(field_mask, phenology["r_squared"], np.nan))), 4),
        "field_mean_peak_ndvi": round(float(ft["peak_value"].mean()), 4) if "peak_value" in ft else None,
        "field_mean_peak_doy": round(float(ft["peak_doy"].mean()), 1) if "peak_doy" in ft else None,
    }
    if "crop" in table.columns and "peak_value" in table.columns:
        summary["phenology"]["peak_by_crop"] = {
            crop: {"mean_peak_ndvi": round(float(g["peak_value"].mean()), 4),
                   "mean_peak_doy": round(float(g["peak_doy"].mean()), 1), "n_fields": int(len(g))}
            for crop, g in table.groupby("crop")
        }

    # 6. outputs
    if write_outputs:
        raster_dir = ensure_directory(out_dir / "rasters")
        for scene in scenes:
            write_raster(scene["ndvi"], profile, str(raster_dir / f"ndvi_{scene['date'].strftime('%Y%m%d')}.tif"))
        write_raster(a_scene["ndvi"], profile, str(raster_dir / "ndvi_assessment.tif"))
        write_raster(baseline, profile, str(raster_dir / "ndvi_expected_baseline.tif"))
        write_raster(peak_metrics["peak_value"], profile, str(raster_dir / "peak_ndvi.tif"))
        write_raster(peak_metrics["peak_doy"], profile, str(raster_dir / "peak_doy.tif"))
        write_raster(peak_metrics["growing_season_length"], profile, str(raster_dir / "season_length_days.tif"))
        write_raster(phenology["r_squared"], profile, str(raster_dir / "phenology_r2.tif"))
        if not change_df.empty:
            change_df.to_csv(out_dir / "field_change_report.csv", index=False)
        ft.to_csv(out_dir / "field_phenology.csv", index=False)
        table.to_file(out_dir / "fields_assessment.geojson", driver="GeoJSON")

    return {
        "scenes": scenes, "dates": dates, "doy": doy, "ndvi_stack": ndvi_stack, "smoothed": smoothed,
        "phenology": phenology, "peak_metrics": peak_metrics, "field_fit": field_fit,
        "assessment_idx": a_idx, "assessment_date": a_date, "baseline": baseline, "current": current,
        "anomaly_mask": anomaly_mask, "anomaly_stats": anomaly_stats, "comparison_stats": comparison_stats,
        "stats_df": stats_df, "change_df": change_df, "field_table": table, "summary": summary,
        "profile": profile, "fields": fields, "indices": indices, "field_mask": field_mask,
        "health_classes": HEALTH_CLASSES,
    }
