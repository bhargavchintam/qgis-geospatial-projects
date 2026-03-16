"""
Field-Level Zonal Statistics

Computes per-parcel crop health statistics by aggregating raster
vegetation indices over vector field boundaries. Generates
management-zone level reports for precision agriculture.
"""

import numpy as np
import geopandas as gpd
import pandas as pd
from rasterstats import zonal_stats
import logging
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime

from .utils import load_config, write_raster, ensure_directory

logger = logging.getLogger(__name__)


class ZonalFieldStats:
    """
    Computes per-field zonal statistics for crop health monitoring.

    Aggregates pixel-level vegetation indices to field/parcel boundaries,
    producing management-ready reports with health classifications.
    """

    def __init__(
        self,
        field_boundaries_path: str,
        config_path: str = "config.yaml",
    ):
        """
        Args:
            field_boundaries_path: path to field boundary vector file
            config_path: path to configuration YAML
        """
        self.config = load_config(config_path)
        self.fields = gpd.read_file(field_boundaries_path)

        if "field_id" not in self.fields.columns:
            self.fields["field_id"] = [f"F{i:04d}" for i in range(len(self.fields))]

        logger.info(
            f"Loaded {len(self.fields)} field boundaries from {field_boundaries_path}"
        )

    def compute(
        self,
        scenes: List[Dict],
        indices: Optional[List[str]] = None,
        output_csv: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Compute per-field statistics for multiple scenes and indices.

        Args:
            scenes: list of scene dicts with computed indices and profiles
            indices: list of index names to analyze
            output_csv: optional path to save report as CSV

        Returns:
            DataFrame with per-field, per-date statistics
        """
        if indices is None:
            indices = ["ndvi"]

        all_records = []

        for scene in scenes:
            scene_date = scene.get("date", datetime.now())
            profile = scene.get("profile")

            for index_name in indices:
                if index_name not in scene:
                    continue

                raster_data = scene[index_name]

                # Write temporary raster for zonal_stats
                temp_path = f"/tmp/temp_{index_name}_{scene_date.strftime('%Y%m%d')}.tif"
                if profile:
                    write_raster(raster_data, profile, temp_path)

                    # Compute zonal stats
                    fields_projected = self.fields.to_crs(profile["crs"])
                    stats = zonal_stats(
                        fields_projected,
                        temp_path,
                        stats=["mean", "median", "std", "min", "max", "count",
                               "percentile_10", "percentile_90"],
                    )

                    for i, stat in enumerate(stats):
                        record = {
                            "field_id": self.fields.iloc[i]["field_id"],
                            "date": scene_date.strftime("%Y-%m-%d"),
                            "index": index_name,
                            "mean": round(stat.get("mean", np.nan), 4),
                            "median": round(stat.get("median", np.nan), 4),
                            "std": round(stat.get("std", np.nan), 4),
                            "min": round(stat.get("min", np.nan), 4),
                            "max": round(stat.get("max", np.nan), 4),
                            "p10": round(stat.get("percentile_10", np.nan), 4),
                            "p90": round(stat.get("percentile_90", np.nan), 4),
                            "pixel_count": stat.get("count", 0),
                            "coefficient_of_variation": round(
                                stat.get("std", 0) / stat.get("mean", 1) * 100, 2
                            ) if stat.get("mean", 0) > 0 else 0,
                        }

                        # Health classification based on mean NDVI
                        if index_name == "ndvi":
                            record["health_class"] = self._classify_health(
                                stat.get("mean", 0)
                            )

                        all_records.append(record)

        df = pd.DataFrame(all_records)

        if output_csv:
            ensure_directory(Path(output_csv).parent)
            df.to_csv(output_csv, index=False)
            logger.info(f"Field report saved to: {output_csv}")

        logger.info(
            f"Computed zonal stats: {len(df)} records "
            f"({len(self.fields)} fields × {len(scenes)} dates × {len(indices)} indices)"
        )

        return df

    def _classify_health(self, mean_ndvi: float) -> str:
        """Classify field health based on mean NDVI."""
        classes = self.config["classification"]["health_classes"]

        if mean_ndvi >= classes["excellent"]["min"]:
            return "Excellent"
        elif mean_ndvi >= classes["good"]["min"]:
            return "Good"
        elif mean_ndvi >= classes["moderate"]["min"]:
            return "Moderate"
        elif mean_ndvi >= classes["poor"]["min"]:
            return "Poor"
        else:
            return "Very Poor"

    def compute_change_report(
        self,
        scenes: List[Dict],
        index_name: str = "ndvi",
    ) -> pd.DataFrame:
        """
        Compute inter-date change statistics per field.

        Calculates the change in mean index value between consecutive
        acquisition dates, useful for tracking growth or decline.

        Args:
            scenes: list of chronologically sorted scene dicts
            index_name: index to track

        Returns:
            DataFrame with per-field change metrics
        """
        # First compute regular stats
        stats_df = self.compute(scenes, indices=[index_name])

        if stats_df.empty:
            return pd.DataFrame()

        # Pivot to get dates as columns
        pivot = stats_df.pivot_table(
            index="field_id",
            columns="date",
            values="mean",
            aggfunc="first",
        )

        # Compute changes between consecutive dates
        change_records = []
        dates = sorted(pivot.columns)

        for i in range(1, len(dates)):
            prev_date = dates[i - 1]
            curr_date = dates[i]

            for field_id in pivot.index:
                prev_val = pivot.loc[field_id, prev_date]
                curr_val = pivot.loc[field_id, curr_date]

                if pd.isna(prev_val) or pd.isna(curr_val):
                    continue

                change = curr_val - prev_val
                pct_change = (change / prev_val * 100) if prev_val != 0 else 0

                change_records.append({
                    "field_id": field_id,
                    "period": f"{prev_date} → {curr_date}",
                    "previous_ndvi": round(prev_val, 4),
                    "current_ndvi": round(curr_val, 4),
                    "absolute_change": round(change, 4),
                    "percent_change": round(pct_change, 2),
                    "trend": "improving" if change > 0.02 else (
                        "declining" if change < -0.02 else "stable"
                    ),
                })

        change_df = pd.DataFrame(change_records)

        # Summary
        if not change_df.empty:
            improving = (change_df["trend"] == "improving").sum()
            declining = (change_df["trend"] == "declining").sum()
            stable = (change_df["trend"] == "stable").sum()
            logger.info(
                f"Change report: {improving} improving, "
                f"{declining} declining, {stable} stable field-periods"
            )

        return change_df

    def generate_summary(
        self,
        stats_df: pd.DataFrame,
        output_path: Optional[str] = None,
    ) -> Dict:
        """
        Generate an overall summary of field health across all dates.

        Args:
            stats_df: DataFrame from compute()
            output_path: optional path to save JSON summary

        Returns:
            dict with aggregated health metrics
        """
        ndvi_stats = stats_df[stats_df["index"] == "ndvi"]

        if ndvi_stats.empty:
            return {}

        # Latest date stats
        latest_date = ndvi_stats["date"].max()
        latest = ndvi_stats[ndvi_stats["date"] == latest_date]

        # Health distribution
        if "health_class" in latest.columns:
            health_dist = latest["health_class"].value_counts().to_dict()
        else:
            health_dist = {}

        summary = {
            "n_fields": len(self.fields),
            "n_dates_analyzed": ndvi_stats["date"].nunique(),
            "date_range": {
                "start": ndvi_stats["date"].min(),
                "end": ndvi_stats["date"].max(),
            },
            "latest_assessment": {
                "date": latest_date,
                "mean_ndvi_all_fields": round(float(latest["mean"].mean()), 4),
                "std_ndvi_all_fields": round(float(latest["mean"].std()), 4),
                "health_distribution": health_dist,
            },
            "season_statistics": {
                "peak_mean_ndvi": round(float(ndvi_stats.groupby("date")["mean"].mean().max()), 4),
                "peak_date": ndvi_stats.groupby("date")["mean"].mean().idxmax(),
            },
        }

        if output_path:
            import json
            ensure_directory(Path(output_path).parent)
            with open(output_path, "w") as f:
                json.dump(summary, f, indent=2, default=str)

        return summary
