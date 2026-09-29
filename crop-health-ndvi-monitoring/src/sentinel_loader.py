"""
Sentinel-2 Data Loader & Preprocessor

Handles loading, preprocessing, and organizing multi-temporal
Sentinel-2 Level-2A imagery for crop monitoring analysis.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from rasterio.warp import Resampling, reproject

from .utils import load_config, read_raster

logger = logging.getLogger(__name__)


class SentinelLoader:
    """
    Loads and preprocesses Sentinel-2 multi-temporal imagery.

    Handles:
    - Scene discovery from directory structure
    - Band loading with scale factor application
    - 20m -> 10m resampling for RedEdge/SWIR bands (bilinear)
    - Cloud masking using the SCL band (nearest-neighbour resampled)
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
    BANDS_10M = ("B02", "B03", "B04", "B08")

    def __init__(self, config_path: str = "config.yaml", config: Optional[dict] = None):
        self.config = config if config is not None else load_config(config_path)
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
                S2A_MSIL2A_20240415T170000_*/
                    B02.tif, B03.tif, ..., SCL.tif
                S2B_MSIL2A_20240501T170000_*/
                    ...

        Args:
            data_dir: root directory containing scene folders
            date_range: optional (start, end) date filter ("YYYY-MM-DD")

        Returns:
            List of scene dicts (sorted by date) with band arrays and metadata
        """
        data_path = Path(data_dir)
        if not data_path.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")

        scene_dirs = sorted(p for p in data_path.glob("S2*_MSIL2A_*") if p.is_dir())
        logger.info(f"Found {len(scene_dirs)} Sentinel-2 scenes in {data_dir}")

        if date_range:
            start = datetime.strptime(date_range[0], "%Y-%m-%d")
            end = datetime.strptime(date_range[1], "%Y-%m-%d")
        else:
            season = self.config["growing_season"]
            start = datetime.strptime(str(season["start"]), "%Y-%m-%d")
            end = datetime.strptime(str(season["end"]), "%Y-%m-%d")

        scenes = []
        for scene_dir in scene_dirs:
            # date = first 8-digit group after the product level, e.g. 20240405T170000
            date_match = re.search(r"MSIL2A_(\d{8})", scene_dir.name) or re.search(r"(\d{8})", scene_dir.name)
            if not date_match:
                continue
            scene_date = datetime.strptime(date_match.group(1), "%Y%m%d")
            if not (start <= scene_date <= end):
                continue
            scene = self._load_scene(scene_dir, scene_date)
            if scene is not None:
                scenes.append(scene)

        scenes.sort(key=lambda s: s["date"])
        logger.info(f"Loaded {len(scenes)} scenes within date range")
        return scenes

    def _find_band_file(self, scene_dir: Path, band_id: str) -> Optional[Path]:
        """Accept B04.tif, B04_10m.tif, *_B04_10m.tif, *_B04_20m.tif and .jp2 variants."""
        candidates = [scene_dir / f"{band_id}.tif", scene_dir / f"{band_id}_10m.tif",
                      scene_dir / f"{band_id}_20m.tif"]
        for c in candidates:
            if c.exists():
                return c
        for pattern in (f"*_{band_id}_*.tif", f"*{band_id}*.jp2"):
            hits = sorted(scene_dir.glob(pattern))
            if hits:
                return hits[0]
        return None

    def _load_scene(self, scene_dir: Path, scene_date: datetime) -> Optional[Dict]:
        """
        Load all bands for a single scene.

        Applies the scale factor to convert DN -> reflectance [0, 1],
        resamples 20 m bands to the 10 m grid, and applies the cloud mask.
        """
        logger.info(f"Loading scene: {scene_dir.name} ({scene_date.date()})")
        scene = {"date": scene_date, "directory": str(scene_dir), "bands": {}}

        paths = {name: self._find_band_file(scene_dir, bid) for name, bid in self.band_mapping.items()}
        missing = [self.band_mapping[n] for n, p in paths.items() if p is None]
        if missing:
            logger.warning(f"Bands {missing} not found in {scene_dir.name}")

        # Pass 1: reference 10 m profile from the first available 10 m band
        ref_profile = None
        for name, bid in self.band_mapping.items():
            if bid in self.BANDS_10M and paths.get(name) is not None:
                _, ref_profile = read_raster(str(paths[name]))
                break
        if ref_profile is None:
            logger.warning(f"No 10 m band found in {scene_dir.name}; scene skipped")
            return None
        ref_shape = (ref_profile["height"], ref_profile["width"])

        # Pass 2: load, scale, resample where needed
        for name, path in paths.items():
            if path is None:
                continue
            band_data, band_profile = read_raster(str(path))
            band_data = np.clip(band_data / self.scale_factor, 0, 1)
            if band_data.shape != ref_shape:
                band_data = self._resample_to_10m(band_data, band_profile, ref_profile)
            scene["bands"][name] = band_data

        scene["profile"] = ref_profile

        scl_path = scene_dir / "SCL.tif"
        if not scl_path.exists():
            hits = sorted(scene_dir.glob("*SCL*.tif"))
            scl_path = hits[0] if hits else scl_path
        if scl_path.exists():
            scene = self._apply_cloud_mask(scene, str(scl_path), ref_profile)
        else:
            scene["cloud_percent"] = 0.0
            scene["valid_mask"] = np.ones(ref_shape, dtype=bool)

        for name in scene["bands"]:
            scene[name] = scene["bands"][name]
        return scene

    def _resample_to_10m(
        self,
        data: np.ndarray,
        src_profile: dict,
        dst_profile: dict,
        resampling: Resampling = Resampling.bilinear,
    ) -> np.ndarray:
        """Resample a band onto the 10 m reference grid (bilinear by default)."""
        dst_shape = (dst_profile["height"], dst_profile["width"])
        destination = np.full(dst_shape, np.nan, dtype=np.float64)
        reproject(
            source=data.astype(np.float64),
            destination=destination,
            src_transform=src_profile["transform"],
            dst_transform=dst_profile["transform"],
            src_crs=src_profile["crs"],
            dst_crs=dst_profile["crs"],
            src_nodata=np.nan,
            dst_nodata=np.nan,
            resampling=resampling,
        )
        return destination

    def _apply_cloud_mask(self, scene: Dict, scl_path: str, ref_profile: dict) -> Dict:
        """
        Apply the cloud mask from the Scene Classification Layer (SCL).

        Pixels classified as cloud, cloud shadow, cirrus, saturated or no-data
        are set to NaN in every band. SCL is categorical, so it is resampled
        with nearest neighbour (bilinear would invent classes at cloud edges).
        """
        scl_data, scl_profile = read_raster(scl_path)
        if scl_data.shape != (ref_profile["height"], ref_profile["width"]):
            scl_data = self._resample_to_10m(scl_data, scl_profile, ref_profile, Resampling.nearest)

        scl_int = np.nan_to_num(scl_data, nan=0).astype(int)
        valid_mask = np.isin(scl_int, list(self.SCL_VALID_CLASSES))
        cloud_pct = float((1 - valid_mask.sum() / valid_mask.size) * 100)
        logger.info(f"Cloud cover: {cloud_pct:.1f}%")

        for name in scene["bands"]:
            scene["bands"][name] = np.where(valid_mask, scene["bands"][name], np.nan)

        scene["cloud_percent"] = round(cloud_pct, 2)
        scene["valid_mask"] = valid_mask
        scene["scl"] = scl_int
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
        with np.errstate(all="ignore"):
            if method == "median":
                return np.nanmedian(stacked, axis=0)
            if method == "mean":
                return np.nanmean(stacked, axis=0)
            if method == "max":
                return np.nanmax(stacked, axis=0)
        raise ValueError(f"Unknown compositing method: {method}")
