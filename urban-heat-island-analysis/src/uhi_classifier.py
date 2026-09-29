"""
UHI Zone Classifier

Classifies Urban Heat Island intensity zones from Land Surface Temperature
data using statistical threshold methods. Provides zonal statistics and
spatial correlation with Land Use / Land Cover categories.
"""

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path

from .utils import load_config, read_raster, write_raster, write_vector

logger = logging.getLogger(__name__)


# UHI intensity class labels
UHI_CLASSES = {
    5: "Extreme",
    4: "Strong",
    3: "Moderate",
    2: "Mild",
    1: "Neutral",
    0: "Cool Island",
}

# Colours shared by the figures, the Folium map and the QGIS style
UHI_COLORS = {
    0: "#2c7bb6",  # Cool Island
    1: "#ffffbf",  # Neutral
    2: "#fdae61",  # Mild
    3: "#f46d43",  # Moderate
    4: "#d73027",  # Strong
    5: "#a50026",  # Extreme
}


class UHIClassifier:
    """
    Classifies UHI zones based on LST deviation from the study area mean.

    Uses standard deviation thresholds (multipliers k from the config) to
    categorize each pixel:

        5 Extreme      LST >= mean + k_extreme  * std
        4 Strong       LST >= mean + k_strong   * std
        3 Moderate     LST >= mean + k_moderate * std
        2 Mild         LST >= mean + k_mild     * std
        1 Neutral      mean - k_mild * std <= LST < mean + k_mild * std
        0 Cool Island  LST <  mean - k_mild * std
       -1 nodata
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.thresholds = self.config["classification"]["uhi_thresholds"]

    def classify(
        self,
        lst: np.ndarray,
        profile: Optional[dict] = None,
        output_path: Optional[str] = None,
    ) -> Tuple[np.ndarray, dict]:
        """
        Classify LST array into UHI intensity zones.

        Args:
            lst: Land Surface Temperature array (°C)
            profile: rasterio profile (needed for output)
            output_path: optional path to save classified raster

        Returns:
            tuple: (classified array, class statistics dict)
        """
        logger.info("Classifying UHI intensity zones")

        mean_lst = np.nanmean(lst)
        std_lst = np.nanstd(lst)

        logger.info(f"LST distribution - Mean: {mean_lst:.2f}°C, Std: {std_lst:.2f}°C")

        # Initialize classification array
        classified = np.full(lst.shape, 0, dtype=np.int16)  # Default: Cool Island

        # Apply thresholds from lowest to highest.
        # Cool Island is the mirror of Mild (below mean - mild*std), so
        # Neutral is the band around the mean rather than "everything
        # above the mean" as the first version had it.
        classified = np.where(
            lst >= mean_lst - self.thresholds["mild"] * std_lst, 1, classified  # Neutral
        )
        classified = np.where(
            lst >= mean_lst + self.thresholds["mild"] * std_lst, 2, classified
        )
        classified = np.where(
            lst >= mean_lst + self.thresholds["moderate"] * std_lst, 3, classified
        )
        classified = np.where(
            lst >= mean_lst + self.thresholds["strong"] * std_lst, 4, classified
        )
        classified = np.where(
            lst >= mean_lst + self.thresholds["extreme"] * std_lst, 5, classified
        )

        # Preserve NaN mask
        classified = np.where(np.isnan(lst), -1, classified).astype(np.int16)

        if output_path and profile:
            # int16 with nodata -1 (the old code asked for int8 but the
            # writer overrode it to float64, so the class raster was never
            # a true integer raster)
            write_raster(classified, profile, output_path, dtype="int16", nodata=-1)
            logger.info(f"Classified raster saved to: {output_path}")

        return classified, self._compute_class_statistics(classified, lst)

    def _compute_class_statistics(
        self, classified: np.ndarray, lst: np.ndarray
    ) -> dict:
        """
        Compute per-class statistics.

        Args:
            classified: classified UHI zone array
            lst: original LST array (°C)

        Returns:
            dict with per-class stats (pixel count, area %, mean LST, max LST)
        """
        total_valid = np.sum(classified >= 0)
        stats = {}

        for class_id, class_name in UHI_CLASSES.items():
            mask = classified == class_id
            pixel_count = int(np.sum(mask))
            area_pct = (pixel_count / total_valid * 100) if total_valid > 0 else 0

            class_lst = lst[mask]
            stats[class_name] = {
                "class_id": class_id,
                "pixel_count": pixel_count,
                "area_percent": round(area_pct, 2),
                "mean_lst": round(float(np.nanmean(class_lst)), 2) if pixel_count > 0 else None,
                "max_lst": round(float(np.nanmax(class_lst)), 2) if pixel_count > 0 else None,
                "min_lst": round(float(np.nanmin(class_lst)), 2) if pixel_count > 0 else None,
            }

        # Log summary
        for name, s in stats.items():
            logger.info(
                f"  {name:>10}: {s['area_percent']:6.2f}% | "
                f"Mean: {s['mean_lst']}°C | Max: {s['max_lst']}°C"
            )

        return stats

    def vectorize_zones(
        self,
        classified: np.ndarray,
        profile: dict,
        output_path: Optional[str] = None,
        min_area_m2: float = 10000,
    ) -> gpd.GeoDataFrame:
        """
        Convert classified raster to vector polygons.

        Filters out small fragments below min_area_m2 threshold
        and dissolves adjacent pixels of the same class.

        Args:
            classified: classified raster array
            profile: rasterio profile with CRS and transform
            output_path: optional path for output GeoPackage
            min_area_m2: minimum polygon area to retain (m²)

        Returns:
            GeoDataFrame with one (multi)polygon per UHI class
        """
        logger.info("Vectorizing UHI zones")

        transform = profile["transform"]
        crs = profile["crs"]

        # Extract shapes
        mask = classified >= 0
        results = shapes(
            classified.astype(np.int16),
            mask=mask,
            transform=transform,
        )

        geometries = []
        values = []
        for geom, value in results:
            if int(value) in UHI_CLASSES:
                geometries.append(shape(geom))
                values.append(int(value))

        gdf = gpd.GeoDataFrame(
            {
                "class_id": values,
                "class_name": [UHI_CLASSES[v] for v in values],
                "geometry": geometries,
            },
            crs=crs,
        )

        # Compute area and filter
        gdf["area_m2"] = gdf.geometry.area
        gdf = gdf[gdf["area_m2"] >= min_area_m2].copy()

        if gdf.empty:
            gdf_dissolved = gpd.GeoDataFrame(
                {"class_id": [], "class_name": [], "area_m2": [], "area_km2": []},
                geometry=[],
                crs=crs,
            )
        else:
            # Dissolve by class
            gdf_dissolved = gdf.dissolve(by="class_id", as_index=False)
            gdf_dissolved["class_name"] = gdf_dissolved["class_id"].map(UHI_CLASSES)
            gdf_dissolved["area_m2"] = gdf_dissolved.geometry.area
            gdf_dissolved["area_km2"] = gdf_dissolved["area_m2"] / 1e6
            gdf_dissolved = gdf_dissolved.sort_values("class_id").reset_index(drop=True)

        # Save
        if output_path:
            write_vector(gdf_dissolved, output_path, layer="uhi_zones")
            logger.info(f"Vectorized UHI zones saved to: {output_path}")

        return gdf_dissolved

    def compute_statistics(
        self, classified: np.ndarray, lst: np.ndarray
    ) -> Dict:
        """
        Public method to compute and return class statistics.

        Args:
            classified: classified UHI zone array
            lst: original LST array

        Returns:
            Dictionary of per-class statistics
        """
        return self._compute_class_statistics(classified, lst)
