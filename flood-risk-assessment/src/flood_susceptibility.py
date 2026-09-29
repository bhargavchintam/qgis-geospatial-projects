"""
Flood Susceptibility Mapping

Computes flood susceptibility with an AHP-weighted multi-criteria overlay
of terrain, hydrological and environmental factors. The result is a
composite susceptibility index in [0, 1].
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import numpy as np

from .ahp import AHPEngine
from .utils import as_array, load_config, normalize_array, reclassify_raster, write_raster

logger = logging.getLogger(__name__)

RasterLike = Union[str, Path, np.ndarray]

# NLCD class -> flood susceptibility score (higher = more flood prone)
NLCD_SCORES = {
    11: 0.3,   # Open Water (flood source)
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


class FloodSusceptibility:
    """
    AHP-based flood susceptibility mapping.

    Combines seven criteria layers with AHP-derived weights into a
    composite flood susceptibility index in [0, 1].
    """

    def __init__(self, config: Union[str, Path, dict] = "config.yaml"):
        self.config = load_config(config)
        self.ahp_cfg = self.config["ahp"]
        self.reclass_cfg = self.config["susceptibility"].get("reclassification", {})
        self.class_cfg = self.config["susceptibility"]["classification"]

        self.ahp = AHPEngine(
            pairwise_matrix=self.ahp_cfg["pairwise_matrix"],
            criteria_names=self.ahp_cfg["criteria_names"],
            consistency_threshold=self.ahp_cfg.get("consistency_threshold", 0.10),
        )
        self.weights = self.ahp.compute_weights()
        self.consistency = self.ahp.compute_consistency()
        if not self.consistency["is_consistent"]:
            raise ValueError(
                f"AHP matrix inconsistent: CR={self.consistency['CR']:.4f} "
                f"(threshold: {self.consistency['threshold']}). Revise pairwise comparisons."
            )

    def _score(self, name: str, data: np.ndarray, invert: bool) -> np.ndarray:
        """
        Reclassify with the config scheme if present, else min-max normalise
        after clipping to config['susceptibility']['percentile_clip'].
        """
        if name in self.reclass_cfg:
            return reclassify_raster(data, self.reclass_cfg[name])
        clip = self.config["susceptibility"].get("percentile_clip")
        if clip:
            lo, hi = np.nanpercentile(data, clip)
            data = np.clip(data, lo, hi)
        return normalize_array(data, invert=invert)

    def compute(
        self,
        twi: RasterLike,
        slope: RasterLike,
        river_distance: RasterLike,
        rainfall: RasterLike,
        elevation: RasterLike,
        soil_perm: RasterLike,
        lulc: RasterLike,
        profile: Optional[dict] = None,
        output_path: Optional[str] = None,
    ) -> Tuple[np.ndarray, dict]:
        """
        Compute the flood susceptibility index from the multi-criteria overlay.

        Every input can be a raster path or an in-memory array. All layers
        must share the same grid; a layer with a different shape is resampled
        bilinearly to the TWI grid.

        Args:
            twi: Topographic Wetness Index
            slope: slope in degrees (lower = more flood prone)
            river_distance: distance to streams in metres (closer = more prone)
            rainfall: design rainfall depth (higher = more prone)
            elevation: DEM in metres (lower = more prone)
            soil_perm: saturated hydraulic conductivity (lower = more prone)
            lulc: NLCD land cover codes
            profile: rasterio profile for the optional output
            output_path: optional GeoTIFF path

        Returns:
            (susceptibility array in [0, 1], class statistics dict)
        """
        logger.info("Computing flood susceptibility index")
        criteria = {
            "twi": self._score("twi", as_array(twi), invert=False),
            "slope": self._score("slope", as_array(slope), invert=True),
            "river_distance": self._score("river_distance", as_array(river_distance), invert=True),
            "rainfall": self._score("rainfall", as_array(rainfall), invert=False),
            "elevation": self._score("elevation", as_array(elevation), invert=True),
            "soil_permeability": self._score("soil_permeability", as_array(soil_perm), invert=True),
            "lulc": self._reclassify_lulc(as_array(lulc)),
        }

        target_shape = criteria["twi"].shape
        susceptibility = np.zeros(target_shape, dtype=np.float64)
        self.criterion_means: Dict[str, float] = {}
        for name, weight in self.ahp.get_weight_dict().items():
            if name not in criteria:
                logger.warning(f"No layer supplied for AHP criterion '{name}'; skipped")
                continue
            layer = criteria[name]
            if layer.shape != target_shape:
                from scipy.ndimage import zoom

                layer = zoom(layer, (target_shape[0] / layer.shape[0],
                                     target_shape[1] / layer.shape[1]), order=1)
            layer = np.nan_to_num(layer, nan=float(np.nanmean(layer)))
            susceptibility += weight * layer
            self.criterion_means[name] = round(float(np.mean(layer)), 4)
            logger.info(f"  {name}: weight={weight:.4f}, mean_score={np.mean(layer):.3f}")

        susceptibility = normalize_array(susceptibility)
        stats = self._compute_statistics(susceptibility)

        if output_path and profile:
            write_raster(susceptibility, profile, output_path)
            logger.info(f"Flood susceptibility map saved to: {output_path}")
        return susceptibility, stats

    @staticmethod
    def _reclassify_lulc(lulc: np.ndarray) -> np.ndarray:
        """Map NLCD codes to susceptibility scores (unknown codes get 0.5)."""
        result = np.full(lulc.shape, 0.5, dtype=np.float64)
        for code, score in NLCD_SCORES.items():
            result[lulc == code] = score
        return result

    def classify(self, susceptibility: np.ndarray) -> np.ndarray:
        """Discrete classes 1 (very low) .. 5 (very high) from config thresholds."""
        c = self.class_cfg
        classes = np.ones(susceptibility.shape, dtype=np.int8)
        classes[susceptibility >= c["low"]] = 2
        classes[susceptibility >= c["moderate"]] = 3
        classes[susceptibility >= c["high"]] = 4
        classes[susceptibility >= c["very_high"]] = 5
        classes[np.isnan(susceptibility)] = 0
        return classes

    def _compute_statistics(self, susceptibility: np.ndarray) -> dict:
        """Pixel count and area percent per susceptibility class."""
        classes = self.classify(susceptibility)
        total = int(np.sum(classes > 0))
        names = {1: "very_low", 2: "low", 3: "moderate", 4: "high", 5: "very_high"}
        stats = {}
        for value, name in names.items():
            count = int(np.sum(classes == value))
            stats[name] = {
                "pixel_count": count,
                "area_percent": round(count / total * 100, 2) if total > 0 else 0.0,
            }
        return stats

    def run_scenario(self, base_susceptibility: np.ndarray, return_period: int) -> np.ndarray:
        """
        Scale the 100-year susceptibility to another return period using the
        factors in config['scenarios']['return_period_factors'], clipped to [0, 1].
        """
        factors = self.config["scenarios"]["return_period_factors"]
        factor = float(factors.get(return_period, factors.get(str(return_period), 1.0)))
        scaled = np.clip(base_susceptibility * factor, 0, 1)
        logger.info(
            f"Scenario: {return_period}-year return period, factor={factor}, "
            f"mean susceptibility={np.nanmean(scaled):.3f}"
        )
        return scaled
