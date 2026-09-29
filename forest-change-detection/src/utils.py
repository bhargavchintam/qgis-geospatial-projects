"""
Shared I/O utilities for the Forest Change Detection pipeline.

All raster helpers work with rasterio profiles so that every output keeps the
same georeference (EPSG:32720, 20 m pixels) as the input scene.
"""

from pathlib import Path

import numpy as np
import rasterio
import yaml


def load_config(config_path) -> dict:
    """Load a YAML configuration file into a dict."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def ensure_directory(path) -> Path:
    """Create a directory (and parents) if missing and return it as a Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_raster(filepath, band: int = 1) -> tuple:
    """
    Read a single band from a raster.

    Float rasters have their nodata value replaced by NaN. Integer rasters
    (class maps, masks) are returned in their native dtype so that nodata
    (usually 0) stays a valid label.

    Returns
    -------
    (data, profile) : (np.ndarray of shape (rows, cols), dict)
    """
    with rasterio.open(filepath) as src:
        data = src.read(band)
        profile = src.profile.copy()
        nodata = src.nodata
        if np.issubdtype(data.dtype, np.floating) and nodata is not None:
            data = data.astype(np.float64)
            data[data == nodata] = np.nan
    return data, profile


def read_stack(filepath) -> tuple:
    """
    Read every band of a multiband raster.

    Returns
    -------
    (stack, profile) : (np.ndarray of shape (bands, rows, cols), dict)
    """
    with rasterio.open(filepath) as src:
        stack = src.read()
        profile = src.profile.copy()
        nodata = src.nodata
        if np.issubdtype(stack.dtype, np.floating) and nodata is not None:
            stack = stack.astype(np.float32)
            stack[stack == nodata] = np.nan
    return stack, profile


def single_band_profile(profile: dict, dtype, nodata=None) -> dict:
    """Return a copy of ``profile`` set up for one band of the given dtype."""
    out = dict(profile)
    out.update(driver="GTiff", count=1, dtype=np.dtype(dtype).name, nodata=nodata, compress="lzw")
    return out


def write_raster(data: np.ndarray, profile: dict, output_path, nodata=None, dtype=None) -> str:
    """
    Write a single-band raster.

    Parameters
    ----------
    data : 2-D array.
    profile : rasterio profile (crs, transform, width, height are used).
    output_path : destination GeoTIFF.
    nodata : nodata value to store (None keeps none).
    dtype : output dtype (defaults to ``data.dtype``).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dtype = np.dtype(dtype or data.dtype)
    out_profile = single_band_profile(profile, dtype, nodata)
    out_profile.update(width=data.shape[1], height=data.shape[0])
    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(data.astype(dtype), 1)
    return str(output_path)


def write_stack(stack: np.ndarray, profile: dict, output_path, band_names=None, nodata=None) -> str:
    """
    Write a multiband raster from an array of shape (bands, rows, cols).

    Band descriptions are stored when ``band_names`` is given.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_profile = dict(profile)
    out_profile.update(
        driver="GTiff",
        count=stack.shape[0],
        height=stack.shape[1],
        width=stack.shape[2],
        dtype=np.dtype(stack.dtype).name,
        nodata=nodata,
        compress="lzw",
    )
    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(stack)
        if band_names is not None:
            for i, name in enumerate(band_names, start=1):
                dst.set_band_description(i, str(name))
    return str(output_path)


def pixel_area_m2(profile: dict) -> float:
    """Area of one pixel in square metres from the profile transform."""
    t = profile["transform"]
    return abs(t.a * t.e)


def write_vector(gdf, output_path, driver: str = "GPKG", layer: str = None) -> str:
    """
    Write a GeoDataFrame to disk.

    GeoPackage files are SQLite databases. Some mounted or network file systems
    do not support SQLite locking, so the file is first written to a temporary
    directory and then copied into place.
    """
    import shutil
    import tempfile

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"driver": driver}
    if layer is not None:
        kwargs["layer"] = layer
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / output_path.name
        gdf.to_file(tmp_path, **kwargs)
        shutil.copyfile(tmp_path, output_path)
    return str(output_path)
