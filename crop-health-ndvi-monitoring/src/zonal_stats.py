"""
Field-Level Zonal Statistics

Computes per-parcel crop health statistics by aggregating raster
vegetation indices over vector field boundaries. Generates
management-zone level reports for precision agriculture.
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterstats import zonal_stats

from .utils import ensure_directory, load_config, rasterize_fields, write_raster

logger = logging.getLogger(__name__)

HEALTH_CLASSES = ["Excellent", "Good", "Moderate", "Poor", "Very Poor"]


def _r(value, ndigits: int = 4):
    """Round a rasterstats value, mapping None to NaN."""
    return round(value, ndigits) if value is not None else np.nan


class ZonalFieldStats:
    """
    Computes per-field zonal statistics for crop health monitoring.

    Aggregates pixel-level vegetation indices to field/parcel boundaries,
    producing management-ready reports with health classifications.
    """

    def __init__(
        self,
        field_boundaries_path=None,
        config_path: str = "config.yaml",
        config: Optional[dict] = None,
        fields: Optional[gpd.GeoDataFrame] = None,
    ):
        """
        Args:
            field_boundaries_path: path to a field boundary vector file
            config_path: path to configuration YAML
            config: already-loaded configuration dict (overrides config_path)
            fields: already-loaded GeoDataFrame (overrides field_boundaries_path)
        """
        self.config = config if config is not None else load_config(config_path)
        if fields is not None:
            self.fields = fields.copy()
        elif field_boundaries_path is not None:
            self.fields = gpd.read_file(field_boundaries_path)
        else:
            raise ValueError("Provide field_boundaries_path or fields")

        if "field_id" not in self.fields.columns:
            self.fields["field_id"] = [f"F{i:04d}" for i in range(len(self.fields))]
        self.fields = self.fields.reset_index(drop=True)
        logger.info(f"Loaded {len(self.fields)} field boundaries")

    # ------------------------------------------------------------------ core
    def compute(
        self,
        scenes: List[Dict],
        indices: Optional[List[str]] = None,
        output_csv: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Compute per-field statistics for multiple scenes and indices.

        Index rasters are written to a temporary directory (removed on exit)
        so ``rasterstats`` can read them with their georeference.

        Returns:
            DataFrame with per-field, per-date, per-index statistics
        """
        indices = indices or ["ndvi"]
        stat_names = ["mean", "median", "std", "min", "max", "count", "percentile_10", "percentile_90"]
        all_records = []

        with tempfile.TemporaryDirectory(prefix="zonal_") as tmp_dir:
            for scene in scenes:
                scene_date = scene.get("date", datetime.now())
                profile = scene.get("profile")
                if profile is None:
                    continue
                fields_projected = self.fields.to_crs(profile["crs"])
                cloud_pct = scene.get("cloud_percent", 0.0)

                for index_name in indices:
                    if index_name not in scene:
                        continue
                    temp_path = Path(tmp_dir) / f"{index_name}_{scene_date.strftime('%Y%m%d')}.tif"
                    write_raster(scene[index_name], profile, str(temp_path))
                    stats = zonal_stats(fields_projected, str(temp_path), stats=stat_names)

                    for i, stat in enumerate(stats):
                        mean = stat.get("mean")
                        std = stat.get("std")
                        record = {
                            "field_id": self.fields.iloc[i]["field_id"],
                            "date": scene_date.strftime("%Y-%m-%d"),
                            "index": index_name,
                            "mean": _r(mean),
                            "median": _r(stat.get("median")),
                            "std": _r(std),
                            "min": _r(stat.get("min")),
                            "max": _r(stat.get("max")),
                            "p10": _r(stat.get("percentile_10")),
                            "p90": _r(stat.get("percentile_90")),
                            "pixel_count": int(stat.get("count") or 0),
                            "coefficient_of_variation": round(std / mean * 100, 2)
                            if (mean and std is not None and mean > 0) else np.nan,
                            "scene_cloud_percent": cloud_pct,
                        }
                        if "crop" in self.fields.columns:
                            record["crop"] = self.fields.iloc[i]["crop"]
                        if index_name == "ndvi":
                            record["health_class"] = self._classify_health(mean) if mean is not None else "No Data"
                        all_records.append(record)

        df = pd.DataFrame(all_records)
        if output_csv:
            ensure_directory(Path(output_csv).parent)
            df.to_csv(output_csv, index=False)
            logger.info(f"Field report saved to: {output_csv}")

        logger.info(
            f"Computed zonal stats: {len(df)} records "
            f"({len(self.fields)} fields x {len(scenes)} dates x {len(indices)} indices)"
        )
        return df

    def _classify_health(self, mean_ndvi: float) -> str:
        """Classify field health based on mean NDVI (config thresholds)."""
        classes = self.config["classification"]["health_classes"]
        if mean_ndvi is None or np.isnan(mean_ndvi):
            return "No Data"
        if mean_ndvi >= classes["excellent"]["min"]:
            return "Excellent"
        if mean_ndvi >= classes["good"]["min"]:
            return "Good"
        if mean_ndvi >= classes["moderate"]["min"]:
            return "Moderate"
        if mean_ndvi >= classes["poor"]["min"]:
            return "Poor"
        return "Very Poor"

    # -------------------------------------------------------------- reports
    def compute_change_report(
        self,
        scenes: Optional[List[Dict]] = None,
        index_name: str = "ndvi",
        stats_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Compute inter-date change statistics per field.

        Pass ``stats_df`` (from ``compute``) to avoid recomputing the zonal
        statistics; otherwise ``scenes`` is required.

        Returns:
            DataFrame with per-field, per-period change metrics
        """
        if stats_df is None:
            if scenes is None:
                raise ValueError("Provide scenes or stats_df")
            stats_df = self.compute(scenes, indices=[index_name])
        stats_df = stats_df[stats_df["index"] == index_name]
        if stats_df.empty:
            return pd.DataFrame()

        pivot = stats_df.pivot_table(index="field_id", columns="date", values="mean", aggfunc="first")
        dates = sorted(pivot.columns)
        change_records = []
        for i in range(1, len(dates)):
            prev_date, curr_date = dates[i - 1], dates[i]
            for field_id in pivot.index:
                prev_val = pivot.loc[field_id, prev_date]
                curr_val = pivot.loc[field_id, curr_date]
                if pd.isna(prev_val) or pd.isna(curr_val):
                    continue
                change = curr_val - prev_val
                pct_change = (change / prev_val * 100) if prev_val != 0 else 0
                change_records.append({
                    "field_id": field_id,
                    "period": f"{prev_date} -> {curr_date}",
                    "period_start": prev_date,
                    "period_end": curr_date,
                    "previous_ndvi": round(prev_val, 4),
                    "current_ndvi": round(curr_val, 4),
                    "absolute_change": round(change, 4),
                    "percent_change": round(pct_change, 2),
                    "trend": "improving" if change > 0.02 else ("declining" if change < -0.02 else "stable"),
                })

        change_df = pd.DataFrame(change_records)
        if not change_df.empty:
            counts = change_df["trend"].value_counts()
            logger.info(
                f"Change report: {counts.get('improving', 0)} improving, "
                f"{counts.get('declining', 0)} declining, {counts.get('stable', 0)} stable field-periods"
            )
        return change_df

    def field_table(
        self,
        stats_df: pd.DataFrame,
        date: str,
        indices: Optional[List[str]] = None,
    ) -> gpd.GeoDataFrame:
        """
        One row per field for a given date: geometry + mean of each index
        (columns ``mean_<index>``), NDVI health class and pixel count.
        """
        indices = indices or sorted(stats_df["index"].unique())
        day = stats_df[stats_df["date"] == date]
        table = self.fields.copy()
        for index_name in indices:
            sub = day[day["index"] == index_name].set_index("field_id")
            table[f"mean_{index_name}"] = table["field_id"].map(sub["mean"])
            if index_name == "ndvi":
                table["health_class"] = table["field_id"].map(sub["health_class"]).fillna("No Data")
                table["std_ndvi"] = table["field_id"].map(sub["std"])
                table["pixel_count"] = table["field_id"].map(sub["pixel_count"]).fillna(0).astype(int)
        table["date"] = date
        return table

    def anomaly_fraction_per_field(self, anomaly_mask: np.ndarray, profile: dict) -> pd.Series:
        """Percent of each field's pixels flagged anomalous (index = field_id)."""
        id_raster, ids = rasterize_fields(self.fields, profile, "field_id")
        flat = id_raster.ravel()
        n = len(ids)
        total = np.bincount(flat[flat > 0], minlength=n + 1)[1:]
        flagged = np.bincount(flat[(flat > 0) & anomaly_mask.ravel()], minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            pct = np.where(total > 0, flagged / total * 100.0, np.nan)
        return pd.Series(np.round(pct, 2), index=ids, name="anomaly_pct")

    @staticmethod
    def flag_ndre_stress(table: pd.DataFrame, z_threshold: float = -1.0) -> pd.DataFrame:
        """
        Flag fields whose NDRE is low for their NDVI (possible nitrogen stress).

        A line NDRE = a * NDVI + b is fitted across all fields; fields whose
        residual is below ``z_threshold`` standard deviations are flagged.
        Adds columns ``ndre_residual`` and ``ndre_stress``.
        """
        table = table.copy()
        ok = table[["mean_ndvi", "mean_ndre"]].notna().all(axis=1)
        table["ndre_residual"] = np.nan
        table["ndre_stress"] = False
        if ok.sum() >= 3:
            x = table.loc[ok, "mean_ndvi"].values
            y = table.loc[ok, "mean_ndre"].values
            a, b = np.polyfit(x, y, 1)
            resid = y - (a * x + b)
            std = resid.std() if resid.std() > 0 else 1e-9
            table.loc[ok, "ndre_residual"] = np.round(resid, 4)
            table.loc[ok, "ndre_stress"] = resid / std < z_threshold
        return table

    def generate_summary(
        self,
        stats_df: pd.DataFrame,
        output_path: Optional[str] = None,
        change_df: Optional[pd.DataFrame] = None,
        assessment_date: Optional[str] = None,
        top_n: int = 5,
    ) -> Dict:
        """
        Overall field-health summary.

        Includes the health-class counts at the assessment date (default: the
        latest date), the ``top_n`` lowest-NDVI fields, and the number of
        fields declining in the last period of ``change_df`` if given.
        """
        ndvi_stats = stats_df[stats_df["index"] == "ndvi"]
        if ndvi_stats.empty:
            return {}

        date = assessment_date or ndvi_stats["date"].max()
        latest = ndvi_stats[(ndvi_stats["date"] == date) & ndvi_stats["mean"].notna()]
        health_dist = {c: int((latest["health_class"] == c).sum()) for c in HEALTH_CLASSES}
        stressed = latest.nsmallest(top_n, "mean")[["field_id", "mean", "health_class"] + (["crop"] if "crop" in latest else [])]
        daily_mean = ndvi_stats.groupby("date")["mean"].mean()

        summary = {
            "n_fields": int(len(self.fields)),
            "n_dates_analyzed": int(ndvi_stats["date"].nunique()),
            "date_range": {"start": ndvi_stats["date"].min(), "end": ndvi_stats["date"].max()},
            "assessment": {
                "date": date,
                "mean_ndvi_all_fields": round(float(latest["mean"].mean()), 4) if len(latest) else None,
                "std_ndvi_all_fields": round(float(latest["mean"].std()), 4) if len(latest) > 1 else None,
                "health_distribution": health_dist,
                "top_stressed_fields": stressed.rename(columns={"mean": "mean_ndvi"}).to_dict("records"),
            },
            "season_statistics": {
                "peak_mean_ndvi": round(float(daily_mean.max()), 4),
                "peak_date": str(daily_mean.idxmax()),
            },
        }

        if change_df is not None and not change_df.empty:
            last_period = change_df["period"].iloc[-1]
            last = change_df[change_df["period"] == last_period]
            summary["last_period"] = {
                "period": last_period,
                "fields_declining": int((last["trend"] == "declining").sum()),
                "fields_improving": int((last["trend"] == "improving").sum()),
                "fields_stable": int((last["trend"] == "stable").sum()),
            }

        if output_path:
            ensure_directory(Path(output_path).parent)
            with open(output_path, "w") as f:
                json.dump(summary, f, indent=2, default=str)
        return summary
