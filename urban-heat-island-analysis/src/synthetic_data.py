"""
Synthetic Landsat 8/9 style scene for the demo (Phoenix, Arizona).

The generator builds a small, physically consistent city scene in
EPSG:32612 (UTM zone 12N) at 30 m resolution, centred on downtown
Phoenix (-112.07, 33.45). It writes the same file set the real pipeline
expects, so ``demo.py``, ``app.py`` and the tests all run offline:

    LC09_B4.TIF             red surface reflectance (0..1, float32)
    LC09_B5.TIF             NIR surface reflectance (0..1, float32)
    LC09_B10.TIF            Collection 2 L2SP thermal DN, uint16,
                            Kelvin = DN * 0.00341802 + 149.0
    nlcd_lulc.tif           NLCD land cover codes (uint8)
    impervious.tif          impervious surface percent 0..100 (uint8)
    population_density.tif  people per km2 (float32)
    parks_greenspace.gpkg   park polygons (EPSG:32612)

Scene layout: a dense downtown core (NLCD 24) ringed by medium (23) and
low (22) intensity development, a developed open-space fringe (21),
desert shrub (52) at the edges, an irrigated cropland strip (82) on the
east side, a sinuous river (11) with barren banks (31) across the south,
and seven parks (41 tree-covered, 71 grass). NDVI, imperviousness,
population and brightness temperature are all derived from that land
cover, so vegetation is cool and impervious surfaces are hot.
"""

from pathlib import Path
from typing import Dict

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from scipy import ndimage
import geopandas as gpd
from shapely.geometry import Point
from shapely import affinity
from pyproj import Transformer

from .utils import write_vector, prepare_output

CENTER_LON = -112.07
CENTER_LAT = 33.45
EPSG = 32612
RESOLUTION_M = 30.0

# Landsat Collection 2 Level-2 surface temperature scaling
L2_SCALE = 0.00341802
L2_OFFSET = 149.0

# Parks as ellipses in grid fractions: (cx, cy, rx, ry, nlcd_code, name)
PARKS = [
    (0.30, 0.60, 0.075, 0.045, 41, "Riverside Park"),
    (0.52, 0.42, 0.035, 0.028, 71, "Civic Plaza Green"),
    (0.73, 0.28, 0.050, 0.040, 41, "North Grove Park"),
    (0.24, 0.30, 0.045, 0.045, 71, "Westgate Fields"),
    (0.66, 0.60, 0.040, 0.035, 41, "Encanto Woods"),
    (0.14, 0.50, 0.040, 0.030, 71, "Desert View Green"),
    (0.82, 0.50, 0.060, 0.035, 71, "Palm Links Golf Course"),
]

# Per-class design values (NLCD code -> value)
IMPERVIOUS_BASE = {11: 0, 21: 12, 22: 35, 23: 65, 24: 90, 31: 3, 41: 2, 52: 1, 71: 4, 82: 2}
NDVI_BASE = {11: -0.12, 21: 0.30, 22: 0.24, 23: 0.16, 24: 0.08, 31: 0.10, 41: 0.68, 52: 0.16, 71: 0.50, 82: 0.60}
BRIGHTNESS_BASE = {11: 26.0, 41: 28.0, 71: 30.0, 82: 31.0, 21: 38.0, 22: 40.0, 52: 41.0, 23: 44.0, 31: 45.0, 24: 46.0}
POP_BASE = {11: 0, 21: 900, 22: 3200, 23: 5500, 24: 3000, 31: 0, 41: 0, 52: 10, 71: 0, 82: 20}
BAND_SUM = {11: 0.12, 21: 0.36, 22: 0.36, 23: 0.36, 24: 0.36, 31: 0.45, 41: 0.42, 52: 0.40, 71: 0.42, 82: 0.40}


def _smooth_noise(rng: np.random.Generator, shape, sigma: float, amplitude: float) -> np.ndarray:
    """Gaussian-smoothed white noise rescaled to a standard deviation of ``amplitude``."""
    field = ndimage.gaussian_filter(rng.standard_normal(shape), sigma)
    std = field.std()
    if std == 0:
        return np.zeros(shape)
    return field / std * amplitude


def _lookup(lulc: np.ndarray, table: dict, default: float = 0.0) -> np.ndarray:
    out = np.full(lulc.shape, default, dtype=np.float64)
    for code, value in table.items():
        out[lulc == code] = value
    return out


def _write(path: Path, data: np.ndarray, profile: dict, dtype: str, nodata) -> str:
    path = prepare_output(path)
    prof = dict(profile)
    prof.update(dtype=dtype, nodata=nodata, compress="lzw")
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(np.asarray(data).astype(dtype), 1)
    return str(path)


def utm_bounds(size: int, resolution_m: float = RESOLUTION_M) -> tuple:
    """UTM bounding box (west, south, east, north) of ``size`` pixels centred on downtown Phoenix."""
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG}", always_xy=True)
    cx, cy = to_utm.transform(CENTER_LON, CENTER_LAT)
    half = size * resolution_m / 2.0
    # snap to a whole-metre grid so the transform is tidy
    cx, cy = round(cx), round(cy)
    return (cx - half, cy - half, cx + half, cy + half)


def generate_demo_data(size: int = 200, seed: int = 42, out_dir=None) -> Dict:
    """
    Generate the synthetic Phoenix scene and write it to ``out_dir``.

    Args:
        size: grid width and height in pixels (30 m each)
        seed: random seed (fixed seed = identical scene every run)
        out_dir: output folder (created if missing)

    Returns:
        dict with keys
            thermal, red, nir       paths to LC09_B10.TIF, LC09_B4.TIF, LC09_B5.TIF
            lulc                    path to nlcd_lulc.tif
            impervious              path to impervious.tif
            population              path to population_density.tif
            parks                   path to parks_greenspace.gpkg
            profile                 rasterio profile (float32, EPSG:32612, 30 m)
            bounds                  (west, south, east, north) in EPSG:32612
            center_lonlat           (lon, lat) of the scene centre
            size, seed              the inputs
            arrays                  dict of in-memory design arrays:
                                    lulc, ndvi, impervious, population,
                                    brightness_temp_c, urban_distance
    """
    if out_dir is None:
        out_dir = Path("results") / "demo" / "data"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    west, south, east, north = utm_bounds(size)
    transform = from_bounds(west, south, east, north, size, size)
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "count": 1,
        "width": size,
        "height": size,
        "crs": CRS.from_epsg(EPSG),
        "transform": transform,
        "nodata": np.nan,
    }

    # ------------------------------------------------------------------
    # 1. Land cover layout (grid fractions: fx east, fy south from top)
    # ------------------------------------------------------------------
    rows, cols = np.mgrid[0:size, 0:size]
    fx = (cols + 0.5) / size
    fy = (rows + 0.5) / size

    # distance from the downtown core, with a wobbly edge
    d = np.hypot(fx - 0.50, fy - 0.45) + _smooth_noise(rng, (size, size), size * 0.08, 0.04)

    lulc = np.full((size, size), 52, dtype=np.uint8)          # desert shrub
    lulc[d < 0.58] = 21                                       # open-space fringe
    lulc[d < 0.48] = 22                                       # low intensity
    lulc[d < 0.30] = 23                                       # medium intensity
    lulc[d < 0.17] = 24                                       # downtown core

    # irrigated cropland strip on the east edge (only outside the city)
    crop_edge = 0.86 + _smooth_noise(rng, (size, size), size * 0.06, 0.015)
    lulc[(fx > crop_edge) & (d > 0.46)] = 82

    # river with barren banks across the southern third
    river_y = 0.72 + 0.04 * np.sin(2 * np.pi * 1.3 * fx + 0.5) + _smooth_noise(rng, (size, size), size * 0.1, 0.006)
    river_dist = np.abs(fy - river_y)
    lulc[river_dist < 0.030] = 31                             # dry banks
    lulc[river_dist < 0.012] = 11                             # open water

    # parks (never over water or the river banks)
    park_id = np.zeros((size, size), dtype=np.int16)
    for pid, (cx, cy, rx, ry, code, _name) in enumerate(PARKS, start=1):
        inside = ((fx - cx) / rx) ** 2 + ((fy - cy) / ry) ** 2 <= 1.0
        inside &= ~np.isin(lulc, [11, 31])
        lulc[inside] = code
        park_id[inside] = pid

    # ------------------------------------------------------------------
    # 2. Impervious surface percent (consistent with land cover)
    # ------------------------------------------------------------------
    imp_base = _lookup(lulc, IMPERVIOUS_BASE)
    developed = np.isin(lulc, [21, 22, 23, 24])
    imperv = imp_base + _smooth_noise(rng, (size, size), 2.0, 7.0)
    imperv += np.where(developed, 8.0 * np.clip(1.0 - d / 0.7, 0, 1), 0.0)
    imperv = np.clip(imperv, 0, 100)
    imperv[lulc == 11] = 0
    imp_dev = imperv - imp_base  # local deviation from the class mean

    # ------------------------------------------------------------------
    # 3. NDVI and the red / NIR bands that reproduce it exactly
    # ------------------------------------------------------------------
    ndvi_base = _lookup(lulc, NDVI_BASE)
    ndvi = ndvi_base + _smooth_noise(rng, (size, size), 1.5, 0.04)
    ndvi -= np.where(developed, 0.0015 * imp_dev, 0.0)
    ndvi = np.clip(ndvi, -0.3, 0.9)
    ndvi_dev = ndvi - ndvi_base

    band_sum = _lookup(lulc, BAND_SUM) * (1.0 + _smooth_noise(rng, (size, size), 2.0, 0.05))
    band_sum = np.clip(band_sum, 0.02, 0.95)
    red = np.clip(band_sum * (1.0 - ndvi) / 2.0, 0.0, 1.0)
    nir = np.clip(band_sum * (1.0 + ndvi) / 2.0, 0.0, 1.0)

    # ------------------------------------------------------------------
    # 4. Brightness temperature (deg C) -> Landsat L2SP thermal DN
    # ------------------------------------------------------------------
    dome = 4.0 * np.exp(-((d / 0.45) ** 2))                  # urban heat dome
    bt_c = (
        _lookup(lulc, BRIGHTNESS_BASE)
        + dome
        + 0.05 * imp_dev                                       # more pavement, hotter
        - 8.0 * ndvi_dev                                       # greener, cooler
        + _smooth_noise(rng, (size, size), 2.0, 1.0)
    )
    # the TIRS sensor is 100 m native, resampled to 30 m: soften the edges
    bt_c = ndimage.gaussian_filter(bt_c, 1.0)
    thermal_dn = np.round((bt_c + 273.15 - L2_OFFSET) / L2_SCALE).astype(np.uint16)
    thermal_dn = np.clip(thermal_dn, 1, 65535)

    # ------------------------------------------------------------------
    # 5. Population density (people per km2), highest in residential zones
    # ------------------------------------------------------------------
    pop = _lookup(lulc, POP_BASE) * np.exp(0.35 * _smooth_noise(rng, (size, size), 6.0, 1.0))
    for _ in range(3):  # apartment clusters inside the residential ring
        while True:
            r, c = rng.integers(0, size, 2)
            if lulc[r, c] in (22, 23):
                break
        blob = np.exp(-(((rows - r) ** 2 + (cols - c) ** 2) / (2 * (size * 0.03) ** 2)))
        pop += 4000.0 * blob * np.isin(lulc, [22, 23, 24])
    pop[np.isin(lulc, [11, 31, 41, 71])] = 0.0
    pop = np.clip(pop, 0, None)

    # ------------------------------------------------------------------
    # 6. Write rasters and the parks vector
    # ------------------------------------------------------------------
    paths = {
        "thermal": _write(out_dir / "LC09_B10.TIF", thermal_dn, profile, "uint16", 0),
        "red": _write(out_dir / "LC09_B4.TIF", red, profile, "float32", -9999.0),
        "nir": _write(out_dir / "LC09_B5.TIF", nir, profile, "float32", -9999.0),
        "lulc": _write(out_dir / "nlcd_lulc.tif", lulc, profile, "uint8", 0),
        "impervious": _write(out_dir / "impervious.tif", np.round(imperv), profile, "uint8", 255),
        "population": _write(out_dir / "population_density.tif", pop, profile, "float32", -9999.0),
    }

    park_rows = []
    for pid, (cx, cy, rx, ry, code, name) in enumerate(PARKS, start=1):
        centre = Point(west + cx * size * RESOLUTION_M, north - cy * size * RESOLUTION_M)
        geom = affinity.scale(centre.buffer(1.0, 32), rx * size * RESOLUTION_M, ry * size * RESOLUTION_M)
        park_rows.append(
            {
                "park_id": pid,
                "name": name,
                "park_type": "Tree-covered park" if code == 41 else "Grass park",
                "nlcd_code": code,
                "area_ha": round(geom.area / 10000.0, 2),
                "geometry": geom,
            }
        )
    parks = gpd.GeoDataFrame(park_rows, crs=f"EPSG:{EPSG}")
    paths["parks"] = write_vector(parks, out_dir / "parks_greenspace.gpkg", layer="parks_greenspace")

    return {
        **paths,
        "profile": profile,
        "bounds": (west, south, east, north),
        "center_lonlat": (CENTER_LON, CENTER_LAT),
        "size": size,
        "seed": seed,
        "arrays": {
            "lulc": lulc,
            "ndvi": ndvi,
            "impervious": imperv,
            "population": pop,
            "brightness_temp_c": bt_c,
            "urban_distance": d,
            "park_id": park_id,
        },
    }
