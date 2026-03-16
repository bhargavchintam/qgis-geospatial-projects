"""
Composite Risk Index Calculator

Combines flood hazard (susceptibility) and vulnerability into a
unified risk index using the standard risk framework:

    Risk = Hazard × Vulnerability

Supports multiple classification schemes and scenario analysis.
"""

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import shape
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path

from .utils import write_raster, normalize_array, ensure_directory

logger = logging.getLogger(__name__)


RISK_CLASSES = {
    5: "Very High",
    4: "High",
    3: "Moderate",
    2: "Low",
    1: "Very Low",
}


class RiskCalculator:
    """
    Composite flood risk index computation.

    Risk = f(Hazard, Vulnerability)

    Supports both multiplicative and matrix-based risk combination.
    """

    def __init__(self, method: str = "multiplicative"):
        """
        Args:
            method: risk combination method
                - "multiplicative": Risk = Hazard × Vulnerability
                - "geometric_mean": Risk = √(Hazard × Vulnerability)
                - "matrix": 5×5 risk matrix lookup
        """
        self.method = method

    def compute(
        self,
        hazard: np.ndarray,
        vulnerability: np.ndarray,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Compute composite risk index.

        Args:
            hazard: flood susceptibility/hazard array [0, 1]
            vulnerability: vulnerability index array [0, 1]
            output_path: optional output path
            profile: rasterio profile

        Returns:
            Risk index array [0, 1]
        """
        logger.info(f"Computing risk index (method: {self.method})")

        # Ensure same shape
        if hazard.shape != vulnerability.shape:
            from scipy.ndimage import zoom
            factors = (
                hazard.shape[0] / vulnerability.shape[0],
                hazard.shape[1] / vulnerability.shape[1],
            )
            vulnerability = zoom(vulnerability, factors, order=1)

        if self.method == "multiplicative":
            risk = hazard * vulnerability
        elif self.method == "geometric_mean":
            risk = np.sqrt(hazard * vulnerability)
        elif self.method == "matrix":
            risk = self._matrix_method(hazard, vulnerability)
        else:
            raise ValueError(f"Unknown method: {self.method}")

        risk = normalize_array(risk)

        logger.info(
            f"Risk index — Mean: {np.nanmean(risk):.4f}, "
            f"Max: {np.nanmax(risk):.4f}, "
            f"High risk area: {np.sum(risk >= 0.6) / risk.size * 100:.1f}%"
        )

        if output_path and profile:
            write_raster(risk, profile, output_path)
            logger.info(f"Risk raster saved to: {output_path}")

        return risk

    def _matrix_method(
        self, hazard: np.ndarray, vulnerability: np.ndarray
    ) -> np.ndarray:
        """
        5×5 risk matrix combination.

        Discretizes hazard and vulnerability into 5 classes each,
        then looks up risk from a predefined matrix.
        """
        # Risk matrix (hazard rows × vulnerability columns)
        # Values 1-5 representing Very Low to Very High risk
        risk_matrix = np.array([
            [1, 1, 2, 2, 3],  # Very Low hazard
            [1, 2, 2, 3, 3],  # Low hazard
            [2, 2, 3, 3, 4],  # Moderate hazard
            [2, 3, 3, 4, 4],  # High hazard
            [3, 3, 4, 4, 5],  # Very High hazard
        ])

        # Discretize to 0-4 indices
        h_class = np.clip((hazard * 5).astype(int), 0, 4)
        v_class = np.clip((vulnerability * 5).astype(int), 0, 4)

        # Lookup
        risk = risk_matrix[h_class, v_class].astype(np.float64)

        # Normalize to [0, 1]
        return (risk - 1) / 4

    def classify(
        self,
        risk: np.ndarray,
        thresholds: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Classify risk index into discrete risk classes.

        Args:
            risk: risk index array [0, 1]
            thresholds: classification thresholds

        Returns:
            Classified risk array (1-5)
        """
        if thresholds is None:
            thresholds = {
                "very_high": 0.8,
                "high": 0.6,
                "moderate": 0.4,
                "low": 0.2,
            }

        classified = np.ones_like(risk, dtype=np.int8)  # Very Low
        classified = np.where(risk >= thresholds["low"], 2, classified)
        classified = np.where(risk >= thresholds["moderate"], 3, classified)
        classified = np.where(risk >= thresholds["high"], 4, classified)
        classified = np.where(risk >= thresholds["very_high"], 5, classified)
        classified = np.where(np.isnan(risk), 0, classified)

        return classified

    def classify_and_export(
        self,
        risk: np.ndarray,
        output_path: str,
        profile: Optional[dict] = None,
    ) -> gpd.GeoDataFrame:
        """
        Classify risk and export as vector polygons.

        Args:
            risk: risk index array
            output_path: path for output GeoPackage
            profile: rasterio profile

        Returns:
            GeoDataFrame with risk zone polygons
        """
        classified = self.classify(risk)

        if profile is None:
            logger.warning("No profile provided; cannot vectorize")
            return None

        mask = classified > 0
        results = rasterio_shapes(
            classified.astype(np.int16),
            mask=mask,
            transform=profile["transform"],
        )

        geometries, classes, labels = [], [], []
        for geom, value in results:
            val = int(value)
            if val in RISK_CLASSES:
                geometries.append(shape(geom))
                classes.append(val)
                labels.append(RISK_CLASSES[val])

        gdf = gpd.GeoDataFrame(
            {
                "risk_class": classes,
                "risk_label": labels,
                "geometry": geometries,
            },
            crs=profile["crs"],
        )

        gdf["area_m2"] = gdf.geometry.area
        gdf["area_km2"] = gdf["area_m2"] / 1e6

        # Dissolve by class
        gdf_dissolved = gdf.dissolve(by="risk_class", as_index=False)
        gdf_dissolved["risk_label"] = gdf_dissolved["risk_class"].map(RISK_CLASSES)
        gdf_dissolved["area_m2"] = gdf_dissolved.geometry.area
        gdf_dissolved["area_km2"] = gdf_dissolved["area_m2"] / 1e6

        ensure_directory(Path(output_path).parent)
        gdf_dissolved.to_file(output_path, driver="GPKG")
        logger.info(f"Risk zones exported to: {output_path}")

        return gdf_dissolved

    def compute_exposure_statistics(
        self,
        risk: np.ndarray,
        population_raster: str,
        profile: dict,
    ) -> Dict:
        """
        Estimate population exposure by risk class.

        Args:
            risk: classified risk array
            population_raster: path to population density raster
            profile: rasterio profile

        Returns:
            dict with population counts per risk class
        """
        from .utils import read_raster

        pop_data, _ = read_raster(population_raster)

        if pop_data.shape != risk.shape:
            from scipy.ndimage import zoom
            factors = (risk.shape[0] / pop_data.shape[0], risk.shape[1] / pop_data.shape[1])
            pop_data = zoom(pop_data, factors, order=1)

        classified = self.classify(risk)
        pixel_area_km2 = (profile["transform"][0] ** 2) / 1e6

        exposure = {}
        for class_id, class_name in RISK_CLASSES.items():
            mask = classified == class_id
            pop_in_zone = np.nansum(pop_data[mask]) * pixel_area_km2
            area_km2 = np.sum(mask) * pixel_area_km2

            exposure[class_name] = {
                "estimated_population": int(pop_in_zone),
                "area_km2": round(float(area_km2), 2),
            }

        logger.info("Population exposure by risk class:")
        for name, data in exposure.items():
            logger.info(
                f"  {name}: ~{data['estimated_population']:,} people, "
                f"{data['area_km2']:.1f} km²"
            )

        return exposure
