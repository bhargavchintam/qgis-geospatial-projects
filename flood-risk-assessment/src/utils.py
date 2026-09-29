"""
Shared utilities for the Flood Risk Assessment pipeline.
"""

from pathlib import Path
from typing import Union

import numpy as np
import rasterio
import yaml

PathLike = Union[str, Path]


def load_config(config: Union[PathLike, dict]) -> dict:
    """Load a YAML configuration file, or pass a config dict straight through."""
    if isinstance(config, dict):
        return config
    config_path = Path(config)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def read_raster(filepath: PathLike) -> tuple:
    """Read band 1 of a raster and return (float64 array with NaN nodata, profile)."""
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
        if nodata is not None and not np.isnan(nodata):
            data[data == nodata] = np.nan
    return data, profile


def as_array(source: Union[PathLike, np.ndarray]) -> np.ndarray:
    """Return a float64 array from either an in-memory array or a raster path."""
    if isinstance(source, np.ndarray):
        return source.astype(np.float64, copy=False)
    data, _ = read_raster(source)
    return data


def write_raster(data: np.ndarray, profile: dict, output_path: PathLike) -> str:
    """Write a 2-D numpy array to a float32 GeoTIFF (NaN = nodata)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_profile = dict(profile)
    out_profile.update(
        driver="GTiff", dtype=rasterio.float32, count=1, compress="lzw", nodata=np.nan
    )
    out_profile["height"], out_profile["width"] = data.shape
    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(np.asarray(data, dtype=np.float32), 1)
    return str(output_path)


def normalize_array(arr: np.ndarray, invert: bool = False) -> np.ndarray:
    """Min-max normalize an array to [0, 1]. If invert, high values map to low scores."""
    arr = np.asarray(arr, dtype=np.float64)
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if not np.isfinite(arr_max - arr_min) or arr_max - arr_min == 0:
        return np.zeros_like(arr)
    normalized = (arr - arr_min) / (arr_max - arr_min)
    if invert:
        normalized = 1.0 - normalized
    return normalized


def reclassify_raster(
    data: np.ndarray, scheme: list, default_score: float = 0.0
) -> np.ndarray:
    """
    Reclassify raster values with a list of {range: [lo, hi], score: s} rules.

    Values in [lo, hi) get the score. Scores are then divided by the largest
    score in the scheme so the result lies in [0, 1].
    """
    result = np.full_like(data, default_score, dtype=np.float64)
    for rule in scheme:
        low, high = rule["range"]
        mask = (data >= low) & (data < high)
        result[mask] = rule["score"]
    max_score = max(r["score"] for r in scheme)
    if max_score > 0:
        result = result / max_score
    result[np.isnan(data)] = np.nan
    return result


def ensure_directory(path: PathLike) -> Path:
    """Create a directory (and parents) if it does not exist."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
