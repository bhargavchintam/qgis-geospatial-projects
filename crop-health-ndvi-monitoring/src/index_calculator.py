"""
Vegetation Index Calculator

Computes multiple vegetation and water indices from multispectral
satellite imagery for crop health assessment.

Supported Indices:
    NDVI  — Normalized Difference Vegetation Index
    EVI   — Enhanced Vegetation Index
    SAVI  — Soil-Adjusted Vegetation Index
    NDRE  — Normalized Difference Red-Edge Index
    NDWI  — Normalized Difference Water Index
    GNDVI — Green NDVI
    CIre  — Chlorophyll Index Red-Edge
"""

import numpy as np
import logging
from typing import Optional

from .utils import write_raster

logger = logging.getLogger(__name__)


class IndexCalculator:
    """
    Computes vegetation and water indices from multispectral bands.

    All methods accept numpy arrays and return numpy arrays with the
    same shape. NaN values in input are propagated to output.
    """

    @staticmethod
    def _safe_divide(
        numerator: np.ndarray, denominator: np.ndarray
    ) -> np.ndarray:
        """Division with NaN for zero/near-zero denominators."""
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.where(
                np.abs(denominator) > 1e-10,
                numerator / denominator,
                np.nan,
            )
        return result

    def ndvi(
        self,
        nir: np.ndarray,
        red: np.ndarray,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Normalized Difference Vegetation Index.

        NDVI = (NIR - Red) / (NIR + Red)

        Range: [-1, 1]
        - Dense vegetation: 0.6 – 0.9
        - Sparse vegetation: 0.2 – 0.5
        - Bare soil: 0.0 – 0.2
        - Water: < 0

        Args:
            nir: Near-infrared band (Sentinel-2 B08, 842nm)
            red: Red band (Sentinel-2 B04, 665nm)
        """
        ndvi = self._safe_divide(nir - red, nir + red)
        ndvi = np.clip(ndvi, -1.0, 1.0)

        if output_path and profile:
            write_raster(ndvi, profile, output_path)

        return ndvi

    def evi(
        self,
        nir: np.ndarray,
        red: np.ndarray,
        blue: np.ndarray,
        G: float = 2.5,
        C1: float = 6.0,
        C2: float = 7.5,
        L: float = 1.0,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Enhanced Vegetation Index.

        EVI = G × (NIR - Red) / (NIR + C1×Red - C2×Blue + L)

        Reduces atmospheric and soil background effects.
        Better than NDVI in high-biomass regions (avoids saturation).

        Args:
            nir: Near-infrared band
            red: Red band
            blue: Blue band
            G: Gain factor (default 2.5)
            C1, C2: Atmospheric correction coefficients
            L: Canopy background adjustment
        """
        denominator = nir + C1 * red - C2 * blue + L
        evi = G * self._safe_divide(nir - red, denominator)
        evi = np.clip(evi, -1.0, 1.0)

        if output_path and profile:
            write_raster(evi, profile, output_path)

        return evi

    def savi(
        self,
        nir: np.ndarray,
        red: np.ndarray,
        L: float = 0.5,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Soil-Adjusted Vegetation Index.

        SAVI = ((NIR - Red) / (NIR + Red + L)) × (1 + L)

        Minimizes soil brightness influence on vegetation signal.
        Useful for sparse vegetation / early-season crop monitoring.

        Args:
            nir: Near-infrared band
            red: Red band
            L: Soil brightness correction factor (0 = dense veg, 1 = sparse)
        """
        savi = self._safe_divide(nir - red, nir + red + L) * (1 + L)
        savi = np.clip(savi, -1.0, 1.0)

        if output_path and profile:
            write_raster(savi, profile, output_path)

        return savi

    def ndre(
        self,
        nir: np.ndarray,
        red_edge: np.ndarray,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Normalized Difference Red-Edge Index.

        NDRE = (NIR - RedEdge) / (NIR + RedEdge)

        Sensitive to chlorophyll content and nitrogen status.
        Better than NDVI for mid-to-late season monitoring when
        canopy is fully closed and NDVI saturates.

        Args:
            nir: Near-infrared band (B08, 842nm)
            red_edge: Red-edge band (B05, 705nm)
        """
        ndre = self._safe_divide(nir - red_edge, nir + red_edge)
        ndre = np.clip(ndre, -1.0, 1.0)

        if output_path and profile:
            write_raster(ndre, profile, output_path)

        return ndre

    def ndwi(
        self,
        green: np.ndarray,
        nir: np.ndarray,
        output_path: Optional[str] = None,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Normalized Difference Water Index.

        NDWI = (Green - NIR) / (Green + NIR)

        Indicates crop water content / moisture stress.
        Positive values suggest high water content.

        Args:
            green: Green band (B03, 560nm)
            nir: Near-infrared band (B08, 842nm)
        """
        ndwi = self._safe_divide(green - nir, green + nir)
        ndwi = np.clip(ndwi, -1.0, 1.0)

        if output_path and profile:
            write_raster(ndwi, profile, output_path)

        return ndwi

    def gndvi(
        self,
        nir: np.ndarray,
        green: np.ndarray,
    ) -> np.ndarray:
        """
        Green Normalized Difference Vegetation Index.

        GNDVI = (NIR - Green) / (NIR + Green)

        More sensitive to chlorophyll concentration variations
        than standard NDVI. Useful for estimating nitrogen uptake.
        """
        gndvi = self._safe_divide(nir - green, nir + green)
        return np.clip(gndvi, -1.0, 1.0)

    def chlorophyll_index_red_edge(
        self,
        nir: np.ndarray,
        red_edge: np.ndarray,
    ) -> np.ndarray:
        """
        Chlorophyll Index Red-Edge (CIre).

        CIre = (NIR / RedEdge) - 1

        Directly proportional to leaf chlorophyll content.
        Useful for detecting nitrogen deficiency.
        """
        cire = self._safe_divide(nir, red_edge) - 1
        return np.clip(cire, -1.0, 10.0)

    def compute_all(
        self,
        scene: dict,
        indices: Optional[list] = None,
    ) -> dict:
        """
        Compute multiple indices for a scene.

        Args:
            scene: dict with band arrays keyed by band name
            indices: list of index names to compute (default: all)

        Returns:
            dict with computed index arrays
        """
        if indices is None:
            indices = ["ndvi", "evi", "savi", "ndre", "ndwi"]

        results = {}

        if "ndvi" in indices and "nir" in scene and "red" in scene:
            results["ndvi"] = self.ndvi(scene["nir"], scene["red"])

        if "evi" in indices and all(k in scene for k in ("nir", "red", "blue")):
            results["evi"] = self.evi(scene["nir"], scene["red"], scene["blue"])

        if "savi" in indices and "nir" in scene and "red" in scene:
            results["savi"] = self.savi(scene["nir"], scene["red"])

        if "ndre" in indices and "nir" in scene and "red_edge1" in scene:
            results["ndre"] = self.ndre(scene["nir"], scene["red_edge1"])

        if "ndwi" in indices and "green" in scene and "nir" in scene:
            results["ndwi"] = self.ndwi(scene["green"], scene["nir"])

        logger.info(f"Computed {len(results)} indices: {list(results.keys())}")
        return results

    def classify_health(
        self,
        ndvi: np.ndarray,
        config: dict,
    ) -> np.ndarray:
        """
        Classify crop health based on NDVI thresholds.

        Args:
            ndvi: NDVI array
            config: classification config with health_classes

        Returns:
            Classified array (1=VeryPoor, 2=Poor, 3=Moderate, 4=Good, 5=Excellent)
        """
        classes = config["classification"]["health_classes"]
        classified = np.zeros_like(ndvi, dtype=np.int8)

        classified = np.where(
            (ndvi >= classes["very_poor"]["min"]) & (ndvi < classes["very_poor"]["max"]),
            1, classified
        )
        classified = np.where(
            (ndvi >= classes["poor"]["min"]) & (ndvi < classes["poor"]["max"]),
            2, classified
        )
        classified = np.where(
            (ndvi >= classes["moderate"]["min"]) & (ndvi < classes["moderate"]["max"]),
            3, classified
        )
        classified = np.where(
            (ndvi >= classes["good"]["min"]) & (ndvi < classes["good"]["max"]),
            4, classified
        )
        classified = np.where(
            (ndvi >= classes["excellent"]["min"]) & (ndvi <= classes["excellent"]["max"]),
            5, classified
        )
        classified = np.where(np.isnan(ndvi), 0, classified)

        return classified
