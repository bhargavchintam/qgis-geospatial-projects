"""
Mitigation Priority Mapper

Generates a composite Mitigation Priority Index (MPI) map by combining:
  - Thermal anomaly intensity
  - Population density / exposure
  - Green space deficit

The MPI identifies areas where cooling interventions (green roofs,
tree planting, reflective surfaces) would have the greatest impact.
"""

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
import logging
from typing import Optional, Tuple, List, Dict
from pathlib import Path

from .utils import (
    load_config,
    read_raster,
    write_raster,
    normalize_array,
    ensure_directory,
)

logger = logging.getLogger(__name__)


class MitigationMapper:
    """
    Generates Mitigation Priority Index maps for urban heat management.

    MPI = w₁ × Normalized_Thermal_Anomaly
        + w₂ × Normalized_Population_Density
        + w₃ × Green_Space_Deficit_Score
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.weights = self.config["mitigation"]["weights"]

        # Validate weights sum to 1.0
        weight_sum = sum(self.weights.values())
        if not np.isclose(weight_sum, 1.0):
            logger.warning(
                f"Mitigation weights sum to {weight_sum:.2f}, expected 1.0. Normalizing."
            )
            for key in self.weights:
                self.weights[key] /= weight_sum

    def generate(
        self,
        uhi_zones: np.ndarray,
        lst_anomaly: np.ndarray,
        population_raster: str,
        greenspace_vector: str,
        profile: dict,
        output_path: Optional[str] = None,
    ) -> Tuple[np.ndarray, dict]:
        """
        Generate the Mitigation Priority Index map.

        Args:
            uhi_zones: classified UHI zone array
            lst_anomaly: LST anomaly array (°C above baseline)
            population_raster: path to population density raster
            greenspace_vector: path to green space polygons (GeoPackage/SHP)
            profile: rasterio profile for spatial reference
            output_path: optional path to save MPI raster

        Returns:
            tuple: (MPI array [0–1], priority statistics dict)
        """
        logger.info("Generating Mitigation Priority Index map")

        # Component 1: Normalized thermal anomaly
        thermal_score = self._compute_thermal_score(lst_anomaly)

        # Component 2: Normalized population density
        pop_score = self._compute_population_score(population_raster)

        # Component 3: Green space deficit
        green_deficit_score = self._compute_green_deficit_score(
            greenspace_vector, profile
        )

        # Ensure all arrays have the same shape
        target_shape = thermal_score.shape
        pop_score = self._resize_to_match(pop_score, target_shape)
        green_deficit_score = self._resize_to_match(green_deficit_score, target_shape)

        # Composite MPI
        mpi = (
            self.weights["thermal_anomaly"] * thermal_score
            + self.weights["population_density"] * pop_score
            + self.weights["green_space_deficit"] * green_deficit_score
        )

        # Only compute MPI where UHI is at least "Mild" (class >= 2)
        mpi = np.where(uhi_zones >= 2, mpi, 0.0)

        # Normalize final MPI to [0, 1]
        mpi = normalize_array(mpi)

        # Preserve NaN mask
        nan_mask = np.isnan(lst_anomaly) | np.isnan(thermal_score)
        mpi = np.where(nan_mask, np.nan, mpi)

        if output_path:
            write_raster(mpi, profile, output_path)
            logger.info(f"MPI raster saved to: {output_path}")

        stats = self._compute_priority_statistics(mpi, uhi_zones)
        return mpi, stats

    def _compute_thermal_score(self, lst_anomaly: np.ndarray) -> np.ndarray:
        """
        Normalize thermal anomaly to [0, 1] score.

        Only positive anomalies (warmer than baseline) contribute.
        """
        thermal = np.where(lst_anomaly > 0, lst_anomaly, 0.0)
        return normalize_array(thermal)

    def _compute_population_score(self, population_raster: str) -> np.ndarray:
        """
        Load and normalize population density raster.

        Higher population density = higher priority for mitigation
        (more people exposed to heat stress).
        """
        pop_data, _ = read_raster(population_raster)
        pop_data = np.where(pop_data < 0, 0, pop_data)  # Remove negative values
        return normalize_array(pop_data)

    def _compute_green_deficit_score(
        self,
        greenspace_vector: str,
        profile: dict,
        buffer_m: float = 400,
    ) -> np.ndarray:
        """
        Compute green space deficit score.

        Areas farther from existing green spaces receive higher deficit scores.
        Uses a buffered proximity analysis.

        Args:
            greenspace_vector: path to green space polygon layer
            profile: rasterio profile for rasterization reference
            buffer_m: buffer distance in meters for green space accessibility

        Returns:
            Green space deficit array [0, 1]
        """
        logger.info("Computing green space deficit score")

        gdf = gpd.read_file(greenspace_vector)

        # Reproject to raster CRS if needed
        raster_crs = profile["crs"]
        if gdf.crs != raster_crs:
            gdf = gdf.to_crs(raster_crs)

        # Buffer green spaces to create "access zones"
        gdf_buffered = gdf.copy()
        gdf_buffered["geometry"] = gdf.buffer(buffer_m)

        # Rasterize green space presence (1 = within access zone, 0 = outside)
        transform = profile["transform"]
        height = profile["height"]
        width = profile["width"]

        green_presence = rasterize(
            [(geom, 1) for geom in gdf_buffered.geometry],
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )

        # Deficit = inverse of presence (areas without nearby green space)
        green_deficit = 1.0 - green_presence.astype(np.float64)

        return green_deficit

    def _resize_to_match(
        self, arr: np.ndarray, target_shape: tuple
    ) -> np.ndarray:
        """Resize array to match target shape using nearest-neighbor interpolation."""
        if arr.shape == target_shape:
            return arr

        from scipy.ndimage import zoom

        zoom_factors = (
            target_shape[0] / arr.shape[0],
            target_shape[1] / arr.shape[1],
        )
        return zoom(arr, zoom_factors, order=0)

    def _compute_priority_statistics(
        self, mpi: np.ndarray, uhi_zones: np.ndarray
    ) -> Dict:
        """Compute summary statistics for the MPI output."""
        valid = ~np.isnan(mpi)

        # Priority classification
        high_priority = np.sum((mpi >= 0.7) & valid)
        medium_priority = np.sum((mpi >= 0.4) & (mpi < 0.7) & valid)
        low_priority = np.sum((mpi > 0) & (mpi < 0.4) & valid)
        total = np.sum(valid)

        stats = {
            "total_pixels": int(total),
            "high_priority": {
                "count": int(high_priority),
                "percent": round(float(high_priority / total * 100), 2) if total > 0 else 0,
            },
            "medium_priority": {
                "count": int(medium_priority),
                "percent": round(float(medium_priority / total * 100), 2) if total > 0 else 0,
            },
            "low_priority": {
                "count": int(low_priority),
                "percent": round(float(low_priority / total * 100), 2) if total > 0 else 0,
            },
            "mean_mpi": round(float(np.nanmean(mpi)), 4),
            "max_mpi": round(float(np.nanmax(mpi)), 4),
        }

        logger.info(
            f"MPI Summary — High: {stats['high_priority']['percent']}%, "
            f"Medium: {stats['medium_priority']['percent']}%, "
            f"Low: {stats['low_priority']['percent']}%"
        )

        return stats

    def classify_priority_zones(
        self,
        mpi: np.ndarray,
        profile: dict,
        output_path: str,
        thresholds: Optional[dict] = None,
    ) -> gpd.GeoDataFrame:
        """
        Classify MPI into discrete priority zones and vectorize.

        Args:
            mpi: MPI array [0, 1]
            profile: rasterio profile
            output_path: path for output GeoPackage
            thresholds: dict with 'high' and 'medium' thresholds

        Returns:
            GeoDataFrame with priority zone polygons
        """
        if thresholds is None:
            thresholds = {"high": 0.7, "medium": 0.4}

        from rasterio.features import shapes as rasterio_shapes
        from shapely.geometry import shape

        # Classify
        priority_raster = np.zeros_like(mpi, dtype=np.int8)
        priority_raster = np.where(mpi >= thresholds["high"], 3, priority_raster)
        priority_raster = np.where(
            (mpi >= thresholds["medium"]) & (mpi < thresholds["high"]),
            2,
            priority_raster,
        )
        priority_raster = np.where(
            (mpi > 0) & (mpi < thresholds["medium"]), 1, priority_raster
        )
        priority_raster = np.where(np.isnan(mpi), -1, priority_raster)

        # Vectorize
        mask = priority_raster > 0
        results = rasterio_shapes(
            priority_raster.astype(np.int16),
            mask=mask,
            transform=profile["transform"],
        )

        priority_labels = {3: "High", 2: "Medium", 1: "Low"}
        geometries, classes, labels = [], [], []

        for geom, value in results:
            val = int(value)
            if val in priority_labels:
                geometries.append(shape(geom))
                classes.append(val)
                labels.append(priority_labels[val])

        gdf = gpd.GeoDataFrame(
            {"priority_class": classes, "priority_label": labels, "geometry": geometries},
            crs=profile["crs"],
        )

        gdf["area_m2"] = gdf.geometry.area
        gdf["area_ha"] = gdf["area_m2"] / 10000

        # Dissolve by priority class
        gdf_dissolved = gdf.dissolve(by="priority_class", as_index=False)
        gdf_dissolved["area_m2"] = gdf_dissolved.geometry.area
        gdf_dissolved["area_ha"] = gdf_dissolved["area_m2"] / 10000

        gdf_dissolved.to_file(output_path, driver="GPKG")
        logger.info(f"Priority zones saved to: {output_path}")

        return gdf_dissolved
