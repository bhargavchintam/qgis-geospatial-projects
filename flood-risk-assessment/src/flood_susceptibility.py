"""
Flood Susceptibility Mapping

Computes flood susceptibility using AHP-weighted multi-criteria overlay.
Combines terrain, hydrological, and environmental factors into a
unified susceptibility index.
"""

import numpy as np
import rasterio
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path

from .ahp import AHPEngine
from .utils import (
    load_config,
    read_raster,
    write_raster,
    normalize_array,
    reclassify_raster,
    ensure_directory,
)

logger = logging.getLogger(__name__)


class FloodSusceptibility:
    """
    AHP-based flood susceptibility mapping.

    Combines multiple criteria layers with AHP-derived weights
    to produce a composite flood susceptibility index [0, 1].
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.ahp_cfg = self.config["ahp"]
        self.reclass_cfg = self.config["susceptibility"]["reclassification"]
        self.class_cfg = self.config["susceptibility"]["classification"]

        # Initialize AHP engine
        self.ahp = AHPEngine(
            pairwise_matrix=self.ahp_cfg["pairwise_matrix"],
            criteria_names=self.ahp_cfg["criteria_names"],
            consistency_threshold=self.ahp_cfg["consistency_threshold"],
        )

        # Compute and validate weights
        self.weights = self.ahp.compute_weights()
        self.consistency = self.ahp.compute_consistency()

        if not self.consistency["is_consistent"]:
            raise ValueError(
                f"AHP matrix inconsistent: CR={self.consistency['CR']:.4f} "
                f"(threshold: {self.consistency['threshold']}). "
                "Revise pairwise comparisons."
            )

    def compute(
        self,
        twi: np.ndarray,
        slope: str,
        river_distance: str,
        rainfall: str,
        elevation: str,
        soil_perm: str,
        lulc: str,
        profile: Optional[dict] = None,
        output_path: Optional[str] = None,
    ) -> Tuple[np.ndarray, dict]:
        """
        Compute flood susceptibility index from multi-criteria overlay.

        All raster inputs must cover the same extent and have the same
        dimensions. Use QGIS or rasterio to align/resample if needed.

        Args:
            twi: Topographic Wetness Index array (already computed)
            slope: path to slope raster (degrees)
            river_distance: path to distance-to-river raster (meters)
            rainfall: path to rainfall intensity raster
            elevation: path to DEM (meters)
            soil_perm: path to soil permeability raster (Ksat)
            lulc: path to LULC raster
            profile: rasterio profile for output
            output_path: optional output path

        Returns:
            tuple: (susceptibility array [0,1], statistics dict)
        """
        logger.info("Computing flood susceptibility index")
        logger.info(f"AHP weights: {self.ahp.get_weight_dict()}")

        # Load and standardize criteria layers
        criteria = {}

        # TWI — already an array; higher TWI = more flood prone
        criteria["twi"] = normalize_array(twi)

        # Slope — lower slope = more flood prone (invert)
        slope_data, slope_profile = read_raster(slope)
        if "slope" in self.reclass_cfg:
            criteria["slope"] = reclassify_raster(slope_data, self.reclass_cfg["slope"])
        else:
            criteria["slope"] = normalize_array(slope_data, invert=True)

        if profile is None:
            profile = slope_profile

        # Distance to rivers — closer = more flood prone (invert)
        dist_data, _ = read_raster(river_distance)
        if "river_distance" in self.reclass_cfg:
            criteria["river_distance"] = reclassify_raster(
                dist_data, self.reclass_cfg["river_distance"]
            )
        else:
            criteria["river_distance"] = normalize_array(dist_data, invert=True)

        # Rainfall intensity — higher = more flood prone
        rain_data, _ = read_raster(rainfall)
        criteria["rainfall"] = normalize_array(rain_data)

        # Elevation — lower = more flood prone (invert)
        elev_data, _ = read_raster(elevation)
        if "elevation" in self.reclass_cfg:
            criteria["elevation"] = reclassify_raster(
                elev_data, self.reclass_cfg["elevation"]
            )
        else:
            criteria["elevation"] = normalize_array(elev_data, invert=True)

        # Soil permeability — lower Ksat = more flood prone (invert)
        soil_data, _ = read_raster(soil_perm)
        criteria["soil_permeability"] = normalize_array(soil_data, invert=True)

        # LULC — reclassify based on imperviousness
        lulc_data, _ = read_raster(lulc)
        criteria["lulc"] = self._reclassify_lulc(lulc_data)

        # Weighted overlay
        weight_dict = self.ahp.get_weight_dict()
        susceptibility = np.zeros_like(criteria["twi"])

        for criterion_name, weight in weight_dict.items():
            if criterion_name in criteria:
                layer = criteria[criterion_name]
                # Resize if dimensions don't match
                if layer.shape != susceptibility.shape:
                    from scipy.ndimage import zoom
                    factors = (
                        susceptibility.shape[0] / layer.shape[0],
                        susceptibility.shape[1] / layer.shape[1],
                    )
                    layer = zoom(layer, factors, order=1)

                susceptibility += weight * layer
                logger.info(
                    f"  {criterion_name}: weight={weight:.4f}, "
                    f"mean_score={np.nanmean(layer):.3f}"
                )

        # Normalize to [0, 1]
        susceptibility = normalize_array(susceptibility)

        stats = self._compute_statistics(susceptibility)

        if output_path and profile:
            write_raster(susceptibility, profile, output_path)
            logger.info(f"Flood susceptibility map saved to: {output_path}")

        return susceptibility, stats

    def _reclassify_lulc(self, lulc: np.ndarray) -> np.ndarray:
        """
        Reclassify LULC to flood susceptibility scores.

        Impervious surfaces → high susceptibility
        Vegetation/water → low susceptibility
        """
        # NLCD-based scoring (higher = more flood prone)
        lulc_scores = {
            11: 0.3,   # Open Water — moderate (can be flood source)
            21: 0.5,   # Developed, Open Space
            22: 0.7,   # Developed, Low Intensity
            23: 0.85,  # Developed, Medium Intensity
            24: 1.0,   # Developed, High Intensity
            31: 0.6,   # Barren Land
            41: 0.15,  # Deciduous Forest
            42: 0.15,  # Evergreen Forest
            43: 0.15,  # Mixed Forest
            52: 0.25,  # Shrub/Scrub
            71: 0.3,   # Grassland/Herbaceous
            81: 0.35,  # Pasture/Hay
            82: 0.4,   # Cultivated Crops
            90: 0.2,   # Woody Wetlands
            95: 0.2,   # Emergent Herbaceous Wetlands
        }

        result = np.full_like(lulc, 0.5, dtype=np.float64)
        for code, score in lulc_scores.items():
            result[lulc == code] = score

        return result

    def _compute_statistics(self, susceptibility: np.ndarray) -> dict:
        """Compute susceptibility class statistics."""
        total = np.sum(~np.isnan(susceptibility))

        classes = {
            "very_high": susceptibility >= self.class_cfg["very_high"],
            "high": (susceptibility >= self.class_cfg["high"])
            & (susceptibility < self.class_cfg["very_high"]),
            "moderate": (susceptibility >= self.class_cfg["moderate"])
            & (susceptibility < self.class_cfg["high"]),
            "low": (susceptibility >= self.class_cfg["low"])
            & (susceptibility < self.class_cfg["moderate"]),
            "very_low": susceptibility < self.class_cfg["low"],
        }

        stats = {}
        for class_name, mask in classes.items():
            count = int(np.sum(mask))
            stats[class_name] = {
                "pixel_count": count,
                "area_percent": round(count / total * 100, 2) if total > 0 else 0,
            }

        return stats

    def run_scenario(
        self,
        base_susceptibility: np.ndarray,
        return_period: int,
    ) -> np.ndarray:
        """
        Scale susceptibility for a specific return period.

        Args:
            base_susceptibility: 100-year susceptibility map
            return_period: target return period (years)

        Returns:
            Scaled susceptibility array
        """
        factors = self.config["scenarios"]["return_period_factors"]
        factor = factors.get(return_period, 1.0)

        scaled = base_susceptibility * factor
        scaled = np.clip(scaled, 0, 1)

        logger.info(
            f"Scenario: {return_period}-year return period, "
            f"factor={factor}, mean susceptibility={np.nanmean(scaled):.3f}"
        )

        return scaled
