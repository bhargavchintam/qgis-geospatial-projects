"""
Shared utilities for the Crop Health Monitoring pipeline.
"""

from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import rasterio
import yaml
from rasterio import features


def load_config(config_path: str) -> dict:
    """Load a YAML configuration file into a dict."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def read_raster(filepath: str) -> tuple:
    """Read band 1 of a raster as float64 with nodata converted to NaN."""
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
        if nodata is not None and not np.isnan(nodata):
            data[data == nodata] = np.nan
    return data, profile


def write_raster(
    data: np.ndarray,
    profile: dict,
    output_path: str,
    dtype: str = "float32",
    nodata=np.nan,
) -> str:
    """
    Write a single-band GeoTIFF.

    The caller's profile is copied, never mutated, so one profile can be
    shared safely across many writes of different dtypes.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_profile = dict(profile)
    out_profile.update(
        driver="GTiff", dtype=dtype, count=1, compress="lzw", nodata=nodata
    )
    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(np.asarray(data, dtype=dtype), 1)
    return str(output_path)


def normalize_array(arr: np.ndarray) -> np.ndarray:
    """Scale an array to [0, 1] ignoring NaNs."""
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if arr_max - arr_min == 0:
        return np.zeros_like(arr)
    return (arr - arr_min) / (arr_max - arr_min)


def ensure_directory(path: str) -> Path:
    """Create a directory (and parents) if missing and return it as a Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def rasterize_fields(
    fields, profile: dict, id_column: Optional[str] = None
) -> Tuple[np.ndarray, List]:
    """
    Burn field polygons into an integer raster aligned with ``profile``.

    Pixel value k+1 belongs to ``fields.iloc[k]``; 0 means no field (road,
    gap, outside). Returns ``(id_raster, ids)`` where ``ids[k]`` is the value
    of ``id_column`` for row k (or the row index when no column is given).
    """
    fields_proj = fields.to_crs(profile["crs"]) if fields.crs else fields
    shapes = [(geom, k + 1) for k, geom in enumerate(fields_proj.geometry)]
    id_raster = features.rasterize(
        shapes,
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    if id_column and id_column in fields_proj.columns:
        ids = list(fields_proj[id_column].values)
    else:
        ids = list(range(len(fields_proj)))
    return id_raster, ids
