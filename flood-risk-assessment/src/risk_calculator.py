"""
Composite Risk Index Calculator

Combines flood hazard (susceptibility) and vulnerability into one risk
index following the standard framework Risk = f(Hazard, Vulnerability),
then classifies it, vectorises the zones, and estimates exposure
(population and critical facilities) per class.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import shape

from .utils import as_array, ensure_directory, normalize_array, write_raster

logger = logging.getLogger(__name__)

RISK_CLASSES = {5: "Very High", 4: "High", 3: "Moderate", 2: "Low", 1: "Very Low"}
DEFAULT_THRESHOLDS = {"very_high": 0.8, "high": 0.6, "moderate": 0.4, "low": 0.2}
METHODS = ("multiplicative", "geometric_mean", "matrix")


class RiskCalculator:
    """
    Composite flood risk index.

    Methods:
        multiplicative : Risk = H * V
        geometric_mean : Risk = sqrt(H * V)   (default in the demo)
        matrix         : 5 x 5 risk matrix lookup on H and V classes
    """

    def __init__(self, method: str = "multiplicative", thresholds: Optional[dict] = None):
        if method not in METHODS:
            raise ValueError(f"Unknown method: {method}. Choose from {METHODS}")
        self.method = method
        self.thresholds = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)

    def compute(
        self,
        hazard: np.ndarray,
        vulnerability: np.ndarray,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
        normalize: bool = False,
    ) -> np.ndarray:
        """
        Compute the risk index in [0, 1].

        Both inputs are expected in [0, 1], so the product is already in
        [0, 1]. ``normalize=True`` additionally min-max stretches the
        result; it is off by default so that return-period scenarios
        (which scale the hazard) keep their absolute differences.
        """
        logger.info(f"Computing risk index (method: {self.method})")
        if hazard.shape != vulnerability.shape:
            from scipy.ndimage import zoom

            vulnerability = zoom(
                vulnerability,
                (hazard.shape[0] / vulnerability.shape[0], hazard.shape[1] / vulnerability.shape[1]),
                order=1,
            )

        h = np.clip(hazard, 0, 1)
        v = np.clip(vulnerability, 0, 1)
        if self.method == "multiplicative":
            risk = h * v
        elif self.method == "geometric_mean":
            risk = np.sqrt(h * v)
        else:
            risk = self._matrix_method(h, v)

        if normalize:
            risk = normalize_array(risk)
        risk = np.where(np.isnan(hazard) | np.isnan(vulnerability), np.nan, risk)

        high_pct = np.nansum(risk >= self.thresholds["high"]) / np.sum(~np.isnan(risk)) * 100
        logger.info(
            f"Risk index: mean {np.nanmean(risk):.4f}, max {np.nanmax(risk):.4f}, "
            f"high+very high area {high_pct:.1f}%"
        )
        if output_path and profile:
            write_raster(risk, profile, output_path)
        return risk

    @staticmethod
    def _matrix_method(hazard: np.ndarray, vulnerability: np.ndarray) -> np.ndarray:
        """5 x 5 risk matrix (hazard rows x vulnerability columns), scaled to [0, 1]."""
        risk_matrix = np.array([
            [1, 1, 2, 2, 3],  # Very Low hazard
            [1, 2, 2, 3, 3],  # Low hazard
            [2, 2, 3, 3, 4],  # Moderate hazard
            [2, 3, 3, 4, 4],  # High hazard
            [3, 3, 4, 4, 5],  # Very High hazard
        ])
        h_class = np.clip((np.nan_to_num(hazard) * 5).astype(int), 0, 4)
        v_class = np.clip((np.nan_to_num(vulnerability) * 5).astype(int), 0, 4)
        return (risk_matrix[h_class, v_class].astype(np.float64) - 1) / 4

    def classify(self, risk: np.ndarray, thresholds: Optional[dict] = None) -> np.ndarray:
        """Classify the risk index into 1 (Very Low) .. 5 (Very High); 0 = nodata."""
        t = self.thresholds if thresholds is None else thresholds
        classified = np.ones(risk.shape, dtype=np.int8)
        classified[risk >= t["low"]] = 2
        classified[risk >= t["moderate"]] = 3
        classified[risk >= t["high"]] = 4
        classified[risk >= t["very_high"]] = 5
        classified[np.isnan(risk)] = 0
        return classified

    def classify_and_export(
        self, risk: np.ndarray, output_path: Optional[str] = None, profile: Optional[dict] = None
    ) -> gpd.GeoDataFrame:
        """
        Classify the risk index and vectorise it into one dissolved polygon
        per class with area columns. Written as GeoPackage when
        ``output_path`` is given.
        """
        if profile is None:
            raise ValueError("A rasterio profile is required to vectorise the risk classes")
        classified = self.classify(risk)
        results = rasterio_shapes(
            classified.astype(np.int16), mask=classified > 0, transform=profile["transform"]
        )
        geometries, classes = [], []
        for geom, value in results:
            if int(value) in RISK_CLASSES:
                geometries.append(shape(geom))
                classes.append(int(value))

        gdf = gpd.GeoDataFrame({"risk_class": classes, "geometry": geometries}, crs=profile["crs"])
        gdf = gdf.dissolve(by="risk_class", as_index=False).sort_values("risk_class")
        gdf["risk_label"] = gdf["risk_class"].map(RISK_CLASSES)
        gdf["area_km2"] = (gdf.geometry.area / 1e6).round(3)
        gdf["area_pct"] = (gdf["area_km2"] / gdf["area_km2"].sum() * 100).round(2)
        gdf = gdf[["risk_class", "risk_label", "area_km2", "area_pct", "geometry"]].reset_index(drop=True)

        if output_path:
            ensure_directory(Path(output_path).parent)
            gdf.to_file(output_path, driver="GPKG")
            logger.info(f"Risk zones exported to: {output_path}")
        return gdf

    def compute_exposure_statistics(
        self, risk: np.ndarray, population: Union[str, Path, np.ndarray], profile: dict
    ) -> Dict:
        """
        Estimated population (density x pixel area) and area per risk class.

        Args:
            risk: risk index array
            population: population density raster (people/km2), path or array
            profile: rasterio profile (pixel size from the transform)
        """
        pop_data = as_array(population)
        if pop_data.shape != risk.shape:
            from scipy.ndimage import zoom

            pop_data = zoom(pop_data, (risk.shape[0] / pop_data.shape[0],
                                       risk.shape[1] / pop_data.shape[1]), order=1)

        classified = self.classify(risk)
        pixel_area_km2 = (abs(profile["transform"][0]) * abs(profile["transform"][4])) / 1e6
        exposure = {}
        for class_id, class_name in RISK_CLASSES.items():
            mask = classified == class_id
            exposure[class_name] = {
                "estimated_population": int(round(np.nansum(pop_data[mask]) * pixel_area_km2)),
                "area_km2": round(float(np.sum(mask) * pixel_area_km2), 3),
                "area_pct": round(float(np.sum(mask) / np.sum(classified > 0) * 100), 2),
            }
        for name, data in exposure.items():
            logger.info(
                f"  {name}: ~{data['estimated_population']:,} people, {data['area_km2']:.2f} km2"
            )
        return exposure

    @staticmethod
    def facilities_at_risk(
        risk_zones: gpd.GeoDataFrame,
        infrastructure: Union[str, Path, gpd.GeoDataFrame],
        classes: Tuple[str, ...] = ("High", "Very High"),
    ) -> Tuple[int, gpd.GeoDataFrame]:
        """
        Spatial join of facility points onto the dissolved risk zones.

        Returns (number of facilities in ``classes``, facilities GeoDataFrame
        with 'risk_class' and 'risk_label' columns).
        """
        gdf = infrastructure if isinstance(infrastructure, gpd.GeoDataFrame) else gpd.read_file(infrastructure)
        if gdf.crs != risk_zones.crs:
            gdf = gdf.to_crs(risk_zones.crs)
        joined = gpd.sjoin(
            gdf, risk_zones[["risk_class", "risk_label", "geometry"]], how="left", predicate="intersects"
        )
        # a point on a shared boundary can match two zones: keep the higher class
        joined = joined.sort_values("risk_class", ascending=False)
        joined = joined[~joined.index.duplicated(keep="first")].sort_index()
        joined = joined.drop(columns=[c for c in ("index_right",) if c in joined.columns])
        joined["risk_class"] = joined["risk_class"].fillna(0).astype(int)
        joined["risk_label"] = joined["risk_label"].fillna("Outside")
        count = int(joined["risk_label"].isin(classes).sum())
        logger.info(f"Facilities in {classes}: {count} of {len(joined)}")
        return count, joined
