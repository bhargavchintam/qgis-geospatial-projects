"""
Shared utilities for the UHI analysis pipeline.
"""

import os
import yaml
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
import geopandas as gpd
from pathlib import Path


def load_config(config_path: str) -> dict:
    """Load and validate YAML configuration file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    _validate_config(config)
    return config


def _validate_config(config: dict) -> None:
    """Validate required configuration keys."""
    required_sections = ["study_area", "landsat", "classification", "output"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required config section: '{section}'")

    bbox = config["study_area"].get("bbox", [])
    if len(bbox) != 4:
        raise ValueError("Bounding box must have 4 coordinates [west, south, east, north]")


def read_raster(filepath: str) -> tuple:
    """
    Read a raster file and return array + metadata.

    Returns:
        tuple: (numpy array, rasterio profile dict)
    """
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        # Mask nodata
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
    return data, profile


def write_raster(data: np.ndarray, profile: dict, output_path: str) -> str:
    """
    Write a numpy array to a GeoTIFF raster file.

    Args:
        data: 2D numpy array
        profile: rasterio profile dict with CRS, transform, etc.
        output_path: path for the output GeoTIFF

    Returns:
        str: path to the written file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile.update(
        dtype=rasterio.float64,
        count=1,
        compress="lzw",
        nodata=np.nan,
    )

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data, 1)

    return str(output_path)


def normalize_array(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize an array to [0, 1], ignoring NaNs."""
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if arr_max - arr_min == 0:
        return np.zeros_like(arr)
    return (arr - arr_min) / (arr_max - arr_min)


def clip_raster_to_boundary(
    raster_path: str, boundary_path: str, output_path: str
) -> str:
    """
    Clip a raster to a vector boundary using rasterio.mask.

    Args:
        raster_path: input raster filepath
        boundary_path: vector boundary filepath (GeoPackage, Shapefile)
        output_path: clipped raster output path

    Returns:
        str: path to clipped raster
    """
    from rasterio.mask import mask as rasterio_mask

    boundary = gpd.read_file(boundary_path)

    with rasterio.open(raster_path) as src:
        # Reproject boundary to raster CRS if needed
        if boundary.crs != src.crs:
            boundary = boundary.to_crs(src.crs)

        geometries = boundary.geometry.values
        out_image, out_transform = rasterio_mask(
            src, geometries, crop=True, nodata=np.nan
        )
        out_profile = src.profile.copy()
        out_profile.update(
            height=out_image.shape[1],
            width=out_image.shape[2],
            transform=out_transform,
            nodata=np.nan,
        )

    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(out_image)

    return output_path


def compute_zonal_stats(
    raster_path: str, zones_path: str, stats: list = None
) -> gpd.GeoDataFrame:
    """
    Compute zonal statistics of a raster over vector zones.

    Args:
        raster_path: input raster filepath
        zones_path: vector zones filepath
        stats: list of statistics to compute (default: mean, max, min, std, count)

    Returns:
        GeoDataFrame with zonal statistics columns appended
    """
    from rasterstats import zonal_stats

    if stats is None:
        stats = ["mean", "max", "min", "std", "count"]

    zones = gpd.read_file(zones_path)
    results = zonal_stats(zones, raster_path, stats=stats, geojson_out=True)

    return gpd.GeoDataFrame.from_features(results)


def ensure_directory(path: str) -> Path:
    """Create directory if it doesn't exist and return Path object."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
