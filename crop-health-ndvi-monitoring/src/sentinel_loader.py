"""
Sentinel-2 Data Loader & Preprocessor

Handles loading, preprocessing, and organizing multi-temporal
Sentinel-2 Level-2A imagery for crop monitoring analysis.
"""

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
import geopandas as gpd
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import re

from .utils import load_config, read_raster, write_raster, ensure_directory

logger = logging.getLogger(__name__)


class SentinelLoader:
    """
    Loads and preprocesses Sentinel-2 multi-temporal imagery.

    Handles:
    - Scene discovery from directory structure
    - Band loading with scale factor application
    - 20m → 10m resampling for RedEdge/SWIR bands
    - Cloud masking using SCL band
    - Temporal compositing
    """

    # Sentinel-2 L2A Scene Classification Layer values
    SCL_CLOUD_CLASSES = {
        0: "No Data",
        1: "Saturated/Defective",
        2: "Dark Area Pixels",
        3: "Cloud Shadows",
        8: "Cloud Medium Probability",
        9: "Cloud High Probability",
        10: "Thin Cirrus",
    }
    SCL_VALID_CLASSES = {4, 5, 6, 7, 11}  # Vegetation, Bare, Water, Snow, Unclassified

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.sentinel_cfg = self.config["sentinel"]
        self.scale_factor = self.sentinel_cfg.get("scale_factor", 10000)
        self.band_mapping = self.sentinel_cfg["bands"]

    def load_time_series(
        self,
        data_dir: str,
        date_range: Optional[Tuple[str, str]] = None,
    ) -> List[Dict]:
        """
        Load a time series of Sentinel-2 scenes from a directory.

        Expects directory structure:
            data_dir/
                S2A_MSIL2A_20240415_*/
                    B02.tif, B03.tif, ..., SCL.tif
                S2A_MSIL2A_20240501_*/
                    ...

        Args:
            data_dir: root directory containing scene folders
            date_range: optional (start, end) date filter ("YYYY-MM-DD")

        Returns:
            List of scene dicts with band arrays and metadata
        """
        data_path = Path(data_dir)
        if not data_path.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")

        # Discover scene directories
        scene_dirs = sorted(data_path.glob("S2*_MSIL2A_*"))
        logger.info(f"Found {len(scene_dirs)} Sentinel-2 scenes in {data_dir}")

        if date_range:
            start = datetime.strptime(date_range[0], "%Y-%m-%d")
            end = datetime.strptime(date_range[1], "%Y-%m-%d")
        else:
            season = self.config["growing_season"]
            start = datetime.strptime(season["start"], "%Y-%m-%d")
            end = datetime.strptime(season["end"], "%Y-%m-%d")

        scenes = []
        for scene_dir in scene_dirs:
            # Extract date from directory name
            date_match = re.search(r"(\d{8})", scene_dir.name)
            if not date_match:
                continue

            scene_date = datetime.strptime(date_match.group(1), "%Y%m%d")
            if not (start <= scene_date <= end):
                continue

            scene = self._load_scene(scene_dir, scene_date)
            if scene is not None:
                scenes.append(scene)

        logger.info(f"Loaded {len(scenes)} scenes within date range")
        return scenes

    def _load_scene(
        self, scene_dir: Path, scene_date: datetime
    ) -> Optional[Dict]:
        """
        Load all bands for a single scene.

        Applies scale factor to convert DN → reflectance [0, 1],
        resamples 20m bands to 10m, and applies cloud mask.
        """
        logger.info(f"Loading scene: {scene_dir.name} ({scene_date.date()})")

        scene = {
            "date": scene_date,
            "directory": str(scene_dir),
            "bands": {},
        }

        # Reference 10m profile (from any 10m band)
        ref_profile = None

        for band_name, band_id in self.band_mapping.items():
            band_path = scene_dir / f"{band_id}.tif"
            alt_path = scene_dir / f"{band_id}_10m.tif"

            if band_path.exists():
                path = band_path
            elif alt_path.exists():
                path = alt_path
            else:
                logger.warning(f"Band {band_id} not found in {scene_dir.name}")
                continue

            band_data, band_profile = read_raster(str(path))

            # Apply scale factor to get reflectance
            band_data = band_data / self.scale_factor

            # Clip to valid reflectance range
            band_data = np.clip(band_data, 0, 1)

            # Resample 20m bands to 10m if needed
            if ref_profile is None and band_id in ("B02", "B03", "B04", "B08"):
                ref_profile = band_profile
            elif ref_profile is not None and band_data.shape != (
                ref_profile["height"],
                ref_profile["width"],
            ):
                band_data = self._resample_to_10m(
                    band_data, band_profile, ref_profile
                )

            scene["bands"][band_name] = band_data

        if ref_profile:
            scene["profile"] = ref_profile

        # Apply cloud mask if SCL band exists
        scl_path = scene_dir / "SCL.tif"
        if scl_path.exists():
            scene = self._apply_cloud_mask(scene, str(scl_path), ref_profile)

        # Create convenience accessors
        for band_name in self.band_mapping:
            if band_name in scene["bands"]:
                scene[band_name] = scene["bands"][band_name]

        return scene

    def _resample_to_10m(
        self,
        data: np.ndarray,
        src_profile: dict,
        dst_profile: dict,
    ) -> np.ndarray:
        """Resample a 20m band to 10m resolution using bilinear interpolation."""
        dst_shape = (dst_profile["height"], dst_profile["width"])

        destination = np.empty(dst_shape, dtype=np.float64)

        reproject(
            source=data,
            destination=destination,
            src_transform=src_profile["transform"],
            dst_transform=dst_profile["transform"],
            src_crs=src_profile["crs"],
            dst_crs=dst_profile["crs"],
            resampling=Resampling.bilinear,
        )

        return destination

    def _apply_cloud_mask(
        self, scene: Dict, scl_path: str, ref_profile: dict
    ) -> Dict:
        """
        Apply cloud mask using the Scene Classification Layer (SCL).

        Masks pixels classified as cloud, cloud shadow, cirrus,
        or other non-valid classes.
        """
        scl_data, scl_profile = read_raster(scl_path)

        # Resample SCL to 10m if needed
        if scl_data.shape != (ref_profile["height"], ref_profile["width"]):
            scl_data = self._resample_to_10m(scl_data, scl_profile, ref_profile)

        # Create valid pixel mask
        valid_mask = np.isin(scl_data.astype(int), list(self.SCL_VALID_CLASSES))

        cloud_pct = (1 - np.sum(valid_mask) / valid_mask.size) * 100
        logger.info(f"Cloud cover: {cloud_pct:.1f}%")

        # Apply mask to all bands
        for band_name in scene["bands"]:
            scene["bands"][band_name] = np.where(
                valid_mask, scene["bands"][band_name], np.nan
            )
            if band_name in scene:
                scene[band_name] = scene["bands"][band_name]

        scene["cloud_percent"] = cloud_pct
        scene["valid_mask"] = valid_mask

        return scene

    def create_temporal_composite(
        self,
        scenes: List[Dict],
        method: str = "median",
        index_name: str = "ndvi",
    ) -> np.ndarray:
        """
        Create a temporal composite from multiple scenes.

        Args:
            scenes: list of scene dicts with computed indices
            method: compositing method ("median", "mean", "max")
            index_name: name of the index to composite

        Returns:
            Composite array
        """
        logger.info(f"Creating {method} composite of {index_name} from {len(scenes)} scenes")

        stacked = np.array([s[index_name] for s in scenes if index_name in s])

        if method == "median":
            composite = np.nanmedian(stacked, axis=0)
        elif method == "mean":
            composite = np.nanmean(stacked, axis=0)
        elif method == "max":
            composite = np.nanmax(stacked, axis=0)
        else:
            raise ValueError(f"Unknown compositing method: {method}")

        return composite
