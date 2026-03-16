"""
Shared utilities for the Crop Health Monitoring pipeline.
"""

import yaml
import numpy as np
import rasterio
import geopandas as gpd
from pathlib import Path


def load_config(config_path: str) -> dict:
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def read_raster(filepath: str) -> tuple:
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
    return data, profile


def write_raster(data: np.ndarray, profile: dict, output_path: str) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(dtype=rasterio.float64, count=1, compress="lzw", nodata=np.nan)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data, 1)
    return str(output_path)


def normalize_array(arr: np.ndarray) -> np.ndarray:
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if arr_max - arr_min == 0:
        return np.zeros_like(arr)
    return (arr - arr_min) / (arr_max - arr_min)


def ensure_directory(path: str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
