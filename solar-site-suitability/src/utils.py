"""
Shared utilities for the Solar Site Suitability pipeline.

Raster I/O, min-max normalisation, vector rasterisation and Euclidean
distance rasters. All distances are in metres because the study area is
projected in a UTM CRS (EPSG:32612).
"""

import shutil
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from rasterio import features
from rasterio.transform import array_bounds
from scipy import ndimage


def load_config(config_path: str) -> dict:
    """Load a YAML configuration file and return it as a dict."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config


def read_raster(filepath: str) -> tuple:
    """Read band 1 of a raster and return (array as float64, profile).

    Nodata pixels are converted to NaN.
    """
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
        if nodata is not None and not np.isnan(nodata):
            data[data == nodata] = np.nan
    return data, profile


def write_raster(data: np.ndarray, profile: dict, output_path: str,
                 nodata=None) -> str:
    """Write a 2-D numpy array to a single-band LZW GeoTIFF.

    Float arrays are written as float32 with NaN nodata. Integer and boolean
    arrays are written as int32; nodata is only set when ``nodata`` is given
    (so a 0/1 mask keeps its zeros visible in QGIS).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(data)
    profile = profile.copy()
    if np.issubdtype(data.dtype, np.integer) or data.dtype == bool:
        data = data.astype(np.int32)
        profile.update(dtype=rasterio.int32, count=1, compress="lzw")
        if nodata is None:
            profile.pop("nodata", None)
        else:
            profile.update(nodata=int(nodata))
    else:
        data = data.astype(np.float32)
        profile.update(dtype=rasterio.float32, count=1, compress="lzw",
                       nodata=np.nan if nodata is None else nodata)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data, 1)
    return str(output_path)


def write_vector(gdf: gpd.GeoDataFrame, output_path: str, driver: str = "GPKG") -> str:
    """Write a GeoDataFrame to disk (GeoPackage by default).

    GeoPackage is an SQLite database and SQLite cannot write on some
    network / FUSE mounted folders (no file locking). To stay robust the
    file is first written into a temporary directory and then copied to
    ``output_path``.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / output_path.name
        gdf.to_file(tmp_path, driver=driver)
        shutil.copyfile(tmp_path, output_path)
    return str(output_path)


def normalize_array(arr: np.ndarray, invert: bool = False) -> np.ndarray:
    """Min-max normalise an array to [0, 1], ignoring NaN.

    If ``invert`` is True high input values map to low scores. A constant
    array returns zeros.
    """
    arr = np.asarray(arr, dtype=np.float64)
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if arr_max - arr_min == 0:
        return np.zeros_like(arr)
    normalized = (arr - arr_min) / (arr_max - arr_min)
    if invert:
        normalized = 1.0 - normalized
    return normalized


def ensure_directory(path: str) -> Path:
    """Create a directory (and parents) if it does not exist."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def raster_bounds(profile: dict) -> tuple:
    """Return (west, south, east, north) of a raster profile in its CRS."""
    return array_bounds(profile["height"], profile["width"], profile["transform"])


def pixel_size(profile: dict) -> float:
    """Return the pixel edge length in CRS units (metres for UTM)."""
    t = profile["transform"]
    return float(abs(t.a))


def pixel_area_ha(profile: dict) -> float:
    """Return the area of one pixel in hectares."""
    t = profile["transform"]
    return float(abs(t.a * t.e)) / 10_000.0


def rasterize_vector(gdf: gpd.GeoDataFrame, profile: dict, burn_value: int = 1,
                     all_touched: bool = True) -> np.ndarray:
    """Burn vector geometries into a uint8 raster on the profile grid.

    Args:
        gdf: GeoDataFrame in the same CRS as the profile.
        profile: rasterio profile (height, width, transform).
        burn_value: value written where a geometry touches a pixel.
        all_touched: burn every pixel a line or polygon edge touches
            (keeps thin lines continuous).

    Returns:
        uint8 array, ``burn_value`` on features and 0 elsewhere.
    """
    shape = (profile["height"], profile["width"])
    if gdf is None or len(gdf) == 0:
        return np.zeros(shape, dtype=np.uint8)
    geoms = [g for g in gdf.geometry if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(shape, dtype=np.uint8)
    return features.rasterize(
        ((g, burn_value) for g in geoms),
        out_shape=shape,
        transform=profile["transform"],
        fill=0,
        all_touched=all_touched,
        dtype="uint8",
    )


def distance_raster(gdf: gpd.GeoDataFrame, profile: dict) -> np.ndarray:
    """Euclidean distance (metres) from every pixel to the nearest feature.

    The features are rasterised first, then
    ``scipy.ndimage.distance_transform_edt`` is run on the background with
    the pixel size as sampling so the result is in metres. Pixels on a
    feature get distance 0. If the GeoDataFrame is empty every pixel gets
    a large finite distance (the diagonal of the raster).
    """
    burned = rasterize_vector(gdf, profile, burn_value=1)
    t = profile["transform"]
    sampling = (abs(t.e), abs(t.a))
    if burned.sum() == 0:
        diag = np.hypot(profile["height"] * abs(t.e), profile["width"] * abs(t.a))
        return np.full(burned.shape, diag, dtype=np.float64)
    return ndimage.distance_transform_edt(burned == 0, sampling=sampling).astype(np.float64)
