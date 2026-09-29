"""
Shared utilities for the UHI analysis pipeline.
"""

import copy
import yaml
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
import geopandas as gpd
from pathlib import Path
from typing import Optional, Union


def load_config(config: Union[str, Path, dict]) -> dict:
    """
    Load and validate the pipeline configuration.

    Accepts either a path to a YAML file or an already-loaded dict
    (the Streamlit app builds a dict with user-chosen thresholds and
    weights). A dict is deep-copied so callers are never mutated.
    """
    if isinstance(config, dict):
        cfg = copy.deepcopy(config)
    else:
        config_path = Path(config)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)

    _validate_config(cfg)
    return cfg


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
    Read band 1 of a raster and return (float64 array, rasterio profile).
    Nodata pixels are converted to NaN.
    """
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
        if nodata is not None and not (isinstance(nodata, float) and np.isnan(nodata)):
            data[data == nodata] = np.nan
    return data, profile


def prepare_output(output_path: Union[str, Path]) -> Path:
    """
    Make sure ``output_path`` can be (re)written.

    Creates the parent folder. If the file already exists it is removed,
    or truncated to zero bytes on file systems that forbid unlink (some
    mounted/network drives): GDAL then creates the file fresh instead of
    trying to delete it.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # include stale SQLite side files of a GeoPackage written earlier
    candidates = [output_path] + [
        output_path.with_name(output_path.name + suffix) for suffix in ("-journal", "-wal", "-shm")
    ]
    for path in candidates:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                open(path, "wb").close()
    return output_path


def write_raster(
    data: np.ndarray,
    profile: dict,
    output_path: str,
    dtype: Optional[str] = None,
    nodata=None,
) -> str:
    """
    Write a 2D numpy array to a single-band, LZW-compressed GeoTIFF.

    The caller's ``profile`` is copied, never mutated (the old version
    changed the dict in place, which silently turned every downstream
    raster into float64/NaN even when an integer class raster was wanted).

    Args:
        data: 2D numpy array
        profile: rasterio profile dict with CRS, transform, width, height
        output_path: path for the output GeoTIFF
        dtype: output dtype (default float32 with NaN nodata)
        nodata: nodata value (default NaN for float, must be given for ints)

    Returns:
        str: path to the written file
    """
    output_path = prepare_output(output_path)

    out_profile = dict(profile)
    if dtype is None:
        dtype = "float32"
        nodata = np.nan if nodata is None else nodata
    out_profile.update(
        driver="GTiff",
        dtype=dtype,
        count=1,
        compress="lzw",
        nodata=nodata,
        height=data.shape[0],
        width=data.shape[1],
    )
    # Tiling options from a source file may not fit a small array
    for key in ("blockxsize", "blockysize", "tiled", "interleave"):
        out_profile.pop(key, None)

    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(np.asarray(data).astype(dtype), 1)

    return str(output_path)


def write_vector(gdf: gpd.GeoDataFrame, output_path: str, layer: Optional[str] = None) -> str:
    """
    Write a GeoDataFrame to a GeoPackage.

    GeoPackage is SQLite, and some mounted or network file systems refuse
    SQLite's locking and journal files. The file is therefore always
    written in a local temporary folder and then copied byte-for-byte to
    ``output_path``, which only needs a plain sequential write.
    """
    import shutil
    import tempfile

    output_path = prepare_output(output_path)
    layer = layer or output_path.stem
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / output_path.name
        gdf.to_file(tmp_path, driver="GPKG", layer=layer)
        shutil.copyfile(tmp_path, output_path)
    return str(output_path)


def normalize_array(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize an array to [0, 1], ignoring NaNs."""
    arr = np.asarray(arr, dtype=np.float64)
    if np.all(np.isnan(arr)):
        return arr.copy()
    arr_min = np.nanmin(arr)
    arr_max = np.nanmax(arr)
    if arr_max - arr_min == 0:
        return np.where(np.isnan(arr), np.nan, 0.0)
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

    return gpd.GeoDataFrame.from_features(results, crs=zones.crs)


def ensure_directory(path: str) -> Path:
    """Create directory if it doesn't exist and return Path object."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def raster_bounds_wgs84(profile: dict) -> tuple:
    """
    Return (west, south, east, north) of a raster profile in EPSG:4326.
    Used by the Folium map so overlays line up with the base tiles.
    """
    from rasterio.warp import transform_bounds
    from rasterio.transform import array_bounds

    bounds = array_bounds(profile["height"], profile["width"], profile["transform"])
    return transform_bounds(profile["crs"], "EPSG:4326", *bounds)
