"""
Shared utilities for the Flood Risk Assessment pipeline.
"""

import os
import yaml
import numpy as np
import rasterio
from rasterio.transform import from_bounds
import geopandas as gpd
from pathlib import Path


def load_config(config_path: str) -> dict:
    """Load and validate YAML configuration file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config


def read_raster(filepath: str) -> tuple:
    """Read a raster file and return (array, profile)."""
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
    return data, profile


def write_raster(data: np.ndarray, profile: dict, output_path: str) -> str:
    """Write a numpy array to a GeoTIFF."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(dtype=rasterio.float64, count=1, compress="lzw", nodata=np.nan)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data, 1)
    return str(output_path)


def normalize_array(arr: np.ndarray, invert: bool = False) -> np.ndarray:
    """Min-max normalize array to [0, 1]. If invert, high values → low scores."""
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if arr_max - arr_min == 0:
        return np.zeros_like(arr)
    normalized = (arr - arr_min) / (arr_max - arr_min)
    if invert:
        normalized = 1.0 - normalized
    return normalized


def reclassify_raster(
    data: np.ndarray, scheme: list, default_score: float = 0.0
) -> np.ndarray:
    """
    Reclassify raster values based on a scheme.

    Args:
        data: input raster array
        scheme: list of dicts with 'range' [min, max] and 'score'
        default_score: score for values not matching any range

    Returns:
        Reclassified array with scores
    """
    result = np.full_like(data, default_score, dtype=np.float64)
    for rule in scheme:
        low, high = rule["range"]
        score = rule["score"]
        mask = (data >= low) & (data < high)
        result[mask] = score
    # Normalize scores to [0, 1] (assuming max score is 5)
    max_score = max(r["score"] for r in scheme)
    if max_score > 0:
        result = result / max_score
    return result


def ensure_directory(path: str) -> Path:
    """Create directory if it doesn't exist."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
