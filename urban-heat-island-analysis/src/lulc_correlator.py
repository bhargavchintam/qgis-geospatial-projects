"""
Land Use / Land Cover Correlation Engine

Performs spatial correlation analysis between UHI intensity zones
and LULC categories to identify which land use types contribute
most to urban heat accumulation.
"""

import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path

from .utils import load_config, read_raster

logger = logging.getLogger(__name__)


# NLCD Land Cover Class Mapping
NLCD_CLASSES = {
    11: "Open Water",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
}

# Official NLCD legend colours (used by figures and the Folium map)
NLCD_COLORS = {
    11: "#466b9f",
    21: "#dec5c5",
    22: "#d99282",
    23: "#eb0000",
    24: "#ab0000",
    31: "#b3ac9f",
    41: "#68ab5f",
    42: "#1c5f2c",
    43: "#b5c58f",
    52: "#ccb879",
    71: "#dfdfc2",
    81: "#dcd939",
    82: "#ab6c28",
    90: "#b8d9eb",
    95: "#6c9fb8",
}


class LULCCorrelator:
    """
    Analyzes spatial relationships between UHI intensity and LULC categories.

    Computes cross-tabulation matrices, per-class LST distributions,
    and impervious surface fraction correlations.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)

    def cross_tabulate(
        self,
        uhi_classified: np.ndarray,
        lulc_raster_path: str,
    ) -> pd.DataFrame:
        """
        Cross-tabulate UHI zones with LULC classes.

        Creates a contingency table showing the distribution of each
        LULC class across UHI intensity zones.

        Args:
            uhi_classified: classified UHI zone array
            lulc_raster_path: path to NLCD or similar LULC raster

        Returns:
            DataFrame with cross-tabulation results (rows=LULC, cols=UHI)
        """
        logger.info("Computing UHI × LULC cross-tabulation")

        lulc, _ = read_raster(lulc_raster_path)

        # Flatten arrays for tabulation
        uhi_flat = uhi_classified.flatten()
        lulc_flat = lulc.flatten()

        # Filter valid pixels
        valid = (uhi_flat >= 0) & (~np.isnan(lulc_flat)) & (lulc_flat > 0)
        uhi_valid = uhi_flat[valid].astype(int)
        lulc_valid = lulc_flat[valid].astype(int)

        # Build cross-tabulation
        from .uhi_classifier import UHI_CLASSES

        records = []
        for lulc_code in np.unique(lulc_valid):
            lulc_mask = lulc_valid == lulc_code
            lulc_name = NLCD_CLASSES.get(int(lulc_code), f"Class {int(lulc_code)}")

            row = {"lulc_code": int(lulc_code), "lulc_name": lulc_name}

            for class_id, class_name in UHI_CLASSES.items():
                uhi_mask = uhi_valid == class_id
                overlap = np.sum(lulc_mask & uhi_mask)
                row[class_name] = int(overlap)

            row["total"] = int(np.sum(lulc_mask))
            records.append(row)

        df = pd.DataFrame(records)
        df = df.sort_values("total", ascending=False)

        logger.info(f"Cross-tabulation computed for {len(df)} LULC classes")
        return df

    def compute_lst_by_lulc(
        self,
        lst: np.ndarray,
        lulc_raster_path: str,
    ) -> pd.DataFrame:
        """
        Compute LST statistics for each LULC class.

        Args:
            lst: LST array in Celsius
            lulc_raster_path: path to LULC raster

        Returns:
            DataFrame with per-class LST statistics
        """
        logger.info("Computing LST distributions per LULC class")

        lulc, _ = read_raster(lulc_raster_path)

        records = []
        for lulc_code in np.unique(lulc[~np.isnan(lulc)]):
            code = int(lulc_code)
            if code == 0:
                continue

            mask = lulc == code
            class_lst = lst[mask & ~np.isnan(lst)]

            if len(class_lst) == 0:
                continue

            records.append({
                "lulc_code": code,
                "lulc_name": NLCD_CLASSES.get(code, f"Class {code}"),
                "pixel_count": len(class_lst),
                "mean_lst": round(float(np.mean(class_lst)), 2),
                "median_lst": round(float(np.median(class_lst)), 2),
                "std_lst": round(float(np.std(class_lst)), 2),
                "max_lst": round(float(np.max(class_lst)), 2),
                "min_lst": round(float(np.min(class_lst)), 2),
                "p90_lst": round(float(np.percentile(class_lst, 90)), 2),
                "p10_lst": round(float(np.percentile(class_lst, 10)), 2),
            })

        columns = [
            "lulc_code", "lulc_name", "pixel_count", "mean_lst", "median_lst",
            "std_lst", "max_lst", "min_lst", "p90_lst", "p10_lst",
        ]
        df = pd.DataFrame(records, columns=columns)
        df = df.sort_values("mean_lst", ascending=False).reset_index(drop=True)
        logger.info(f"LST statistics computed for {len(df)} LULC classes")
        return df

    def compute_impervious_correlation(
        self,
        lst: np.ndarray,
        impervious_raster_path: str,
        sample_size: int = 50000,
    ) -> Dict:
        """
        Compute correlation between LST and impervious surface percentage.

        Args:
            lst: LST array in Celsius
            impervious_raster_path: path to impervious surface raster (0–100%)
            sample_size: number of random samples for correlation analysis

        Returns:
            dict with Pearson r, p-value, and regression coefficients
        """
        from scipy import stats as sp_stats

        logger.info("Computing LST–impervious surface correlation")

        imperv, _ = read_raster(impervious_raster_path)

        # Flatten and filter valid pixels
        lst_flat = lst.flatten()
        imp_flat = imperv.flatten()

        valid = ~np.isnan(lst_flat) & ~np.isnan(imp_flat) & (imp_flat >= 0)
        lst_valid = lst_flat[valid]
        imp_valid = imp_flat[valid]

        # Random subsample for efficiency
        if len(lst_valid) > sample_size:
            rng = np.random.default_rng(42)
            indices = rng.choice(len(lst_valid), sample_size, replace=False)
            lst_valid = lst_valid[indices]
            imp_valid = imp_valid[indices]

        if len(lst_valid) < 3 or np.std(imp_valid) == 0:
            raise ValueError(
                "Need at least 3 valid pixels with varying imperviousness "
                "to compute the LST-impervious correlation"
            )

        # Pearson correlation
        r, p_value = sp_stats.pearsonr(imp_valid, lst_valid)

        # Linear regression
        fit = sp_stats.linregress(imp_valid, lst_valid)
        slope, intercept, std_err = fit.slope, fit.intercept, fit.stderr

        result = {
            "pearson_r": round(float(r), 4),
            "p_value": float(p_value),
            "slope": round(float(slope), 4),
            "intercept": round(float(intercept), 2),
            "std_error": round(float(std_err), 4),
            "n_samples": len(lst_valid),
            "interpretation": self._interpret_correlation(r),
        }

        logger.info(
            f"Impervious–LST correlation: r={result['pearson_r']}, "
            f"p={result['p_value']:.2e}, slope={result['slope']}°C/%"
        )

        return result

    @staticmethod
    def _interpret_correlation(r: float) -> str:
        """Provide human-readable interpretation of correlation strength."""
        abs_r = abs(r)
        if abs_r >= 0.8:
            strength = "very strong"
        elif abs_r >= 0.6:
            strength = "strong"
        elif abs_r >= 0.4:
            strength = "moderate"
        elif abs_r >= 0.2:
            strength = "weak"
        else:
            strength = "very weak"

        direction = "positive" if r > 0 else "negative"
        return f"{strength.capitalize()} {direction} correlation"
