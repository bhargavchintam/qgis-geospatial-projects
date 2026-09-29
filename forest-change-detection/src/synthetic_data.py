"""
Synthetic two-date Sentinel-2 scene for Rondônia, Brazil.

The scene mimics the "arc of deforestation": dense forest at T1 (2019-07-15)
with a river, two roads and a few pasture blocks. At T2 (2024-07-15) fishbone
clearing strips appear perpendicular to the roads, plus blob-shaped clearings,
and some old pasture regrows into secondary vegetation. Two cloud blobs cover
part of the T2 image.

Georeference: EPSG:32720 (UTM zone 20S), 20 m pixels, scene centred near
lon -62.9, lat -10.9. Default 200 x 200 px = 4 km x 4 km.

Reflectance model: each land-cover class has a mean reflectance for the six
bands B02, B03, B04, B08, B11, B12. Smooth multiplicative texture, per-pixel
noise and a gentle illumination field are added so the image looks natural.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from rasterio import features
from rasterio.crs import CRS
from rasterio.transform import from_bounds, xy
from scipy.ndimage import gaussian_filter
from shapely import affinity
from shapely.geometry import LineString, Point, box

from .indices import BAND_NAMES
from .utils import ensure_directory, write_raster, write_stack, write_vector

CENTER_LON, CENTER_LAT = -62.9, -10.9
EPSG_CODE = 32720
PIXEL_SIZE = 20.0

# Mean surface reflectance per class for B02, B03, B04, B08, B11, B12
CLASS_MEANS = {
    1: (0.020, 0.045, 0.030, 0.350, 0.150, 0.080),  # Forest
    2: (0.050, 0.080, 0.090, 0.300, 0.280, 0.200),  # Pasture / cleared
    3: (0.050, 0.055, 0.050, 0.020, 0.010, 0.008),  # Water (sediment-laden river)
    4: (0.120, 0.160, 0.200, 0.250, 0.380, 0.350),  # Bare soil / road
    5: (0.030, 0.060, 0.055, 0.330, 0.210, 0.130),  # Regrowth
}
# Secondary end-member per class. Each pixel mixes CLASS_MEANS with CLASS_ALT by a
# smooth random fraction, giving realistic within-class variation (dry vs green
# pasture, young vs older regrowth, dense vs degraded forest, wet vs dry soil).
CLASS_ALT = {
    1: (0.024, 0.050, 0.036, 0.330, 0.170, 0.095),  # degraded / open forest
    2: (0.040, 0.075, 0.070, 0.320, 0.250, 0.165),  # green pasture
    3: (0.040, 0.045, 0.035, 0.030, 0.015, 0.010),  # clearer water
    4: (0.090, 0.130, 0.160, 0.240, 0.320, 0.280),  # damp soil / gravel
    5: (0.036, 0.070, 0.070, 0.320, 0.240, 0.160),  # young regrowth (pasture-like)
}
CLOUD_MEAN = (0.70, 0.70, 0.70, 0.72, 0.55, 0.45)


# --------------------------------------------------------------------------- geometry helpers
def scene_bounds(size: int, pixel_size: float = PIXEL_SIZE) -> tuple:
    """(west, south, east, north) in EPSG:32720 for a square scene centred on the study point."""
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG_CODE}", always_xy=True)
    cx, cy = transformer.transform(CENTER_LON, CENTER_LAT)
    half = size * pixel_size / 2.0
    return (cx - half, cy - half, cx + half, cy + half)


def _px_to_map(col, row, transform):
    """Pixel (col, row) -> map (x, y) at the pixel centre."""
    scalar = np.ndim(col) == 0 and np.ndim(row) == 0
    xs, ys = xy(transform, np.atleast_1d(np.asarray(row, dtype=float)),
                np.atleast_1d(np.asarray(col, dtype=float)), offset="center")
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if scalar:
        return float(xs[0]), float(ys[0])
    return xs, ys


def _rasterize(geoms, transform, shape) -> np.ndarray:
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(shape, dtype=bool)
    arr = features.rasterize(((g, 1) for g in geoms), out_shape=shape, transform=transform,
                             fill=0, dtype="uint8", all_touched=False)
    return arr.astype(bool)


def _smooth_field(rng, shape, sigma, std) -> np.ndarray:
    """Zero-mean smooth random field with the requested standard deviation."""
    f = gaussian_filter(rng.normal(size=shape), sigma=sigma)
    s = f.std()
    return f / s * std if s > 0 else np.zeros(shape)


def _rotated_rect(cx, cy, half_w, half_h, angle_deg):
    return affinity.rotate(box(cx - half_w, cy - half_h, cx + half_w, cy + half_h), angle_deg)


def _ellipse(cx, cy, r, ratio, angle_deg):
    e = affinity.scale(Point(cx, cy).buffer(r, quad_segs=12), xfact=1.0, yfact=ratio)
    return affinity.rotate(e, angle_deg)


# --------------------------------------------------------------------------- landscape
def build_landscape(size: int, rng, transform, pixel_size: float = PIXEL_SIZE,
                    clearing_intensity: float = 1.0) -> dict:
    """
    Build the T1 / T2 truth rasters, the T2 cloud mask and the vector layers.

    Returns dict with ``reference_t1``, ``reference_t2`` (uint8), ``cloud_mask_t2``
    (bool), ``roads`` and ``river`` (GeoDataFrames in EPSG:32720).
    """
    shape = (size, size)
    px = pixel_size
    crs = f"EPSG:{EPSG_CODE}"
    inten = float(np.clip(clearing_intensity, 0.25, 4.0))

    # --- river: sinuous line crossing west -> east in the southern half
    cols = np.arange(0, size + 1, 2, dtype=float)
    wobble = _smooth_field(rng, (cols.size,), sigma=max(2, size / 16), std=0.03 * size)
    rows = size * 0.68 + 0.10 * size * np.sin(2 * np.pi * cols / size * 1.2 + 0.8) + wobble
    rx, ry = _px_to_map(cols, rows, transform)
    river_line = LineString(np.column_stack([rx, ry]))
    river_gdf = gpd.GeoDataFrame({"name": ["Rio Sintetico"], "type": ["river"]},
                                 geometry=[river_line], crs=crs)
    river_mask = _rasterize([river_line.buffer(1.5 * px)], transform, shape)

    # --- roads: main road (west-east) and feeder road (north-south)
    ax0, ay0 = _px_to_map(0, 0.40 * size, transform)
    ax1, ay1 = _px_to_map(size, 0.30 * size, transform)
    road_a = LineString([(float(ax0), float(ay0)), (float(ax1), float(ay1))])
    bx0, by0 = _px_to_map(0.62 * size, 0, transform)
    bx1, by1 = _px_to_map(0.70 * size, size, transform)
    road_b = LineString([(float(bx0), float(by0)), (float(bx1), float(by1))])
    roads_gdf = gpd.GeoDataFrame({"road_id": [1, 2], "name": ["BR main road", "feeder road"],
                                  "type": ["primary", "secondary"]},
                                 geometry=[road_a, road_b], crs=crs)
    road_mask = _rasterize([road_a.buffer(1.0 * px), road_b.buffer(1.0 * px)], transform, shape)

    # --- T1 pasture blocks (old clearings)
    block_centres = [(0.20, 0.15), (0.82, 0.18), (0.14, 0.86), (0.86, 0.90), (0.42, 0.52)]
    blocks = []
    for fx, fy in block_centres:
        cx, cy = _px_to_map(fx * size + rng.uniform(-0.03, 0.03) * size,
                            fy * size + rng.uniform(-0.03, 0.03) * size, transform)
        half_w = rng.uniform(0.045, 0.075) * size * px
        half_h = rng.uniform(0.035, 0.065) * size * px
        blocks.append(_rotated_rect(float(cx), float(cy), half_w, half_h, rng.uniform(-20, 20)))
    block_mask = _rasterize(blocks, transform, shape)

    ref_t1 = np.ones(shape, dtype=np.uint8)
    ref_t1[block_mask] = 2
    ref_t1[river_mask] = 3
    ref_t1[road_mask] = 4

    # --- T2 fishbone strips perpendicular to the roads
    strips = []

    def add_strips(line, t_values):
        p0 = np.array(line.coords[0])
        p1 = np.array(line.coords[-1])
        d = p1 - p0
        d = d / np.linalg.norm(d)
        n = np.array([-d[1], d[0]])
        for t in t_values:
            centre = p0 + t * (p1 - p0)
            jitter = np.deg2rad(rng.uniform(-8, 8))
            nj = np.array([n[0] * np.cos(jitter) - n[1] * np.sin(jitter),
                           n[0] * np.sin(jitter) + n[1] * np.cos(jitter)])
            side = rng.random()
            l1 = rng.uniform(6, 20) * np.sqrt(inten) * px if side > 0.25 else 0.0
            l2 = rng.uniform(6, 20) * np.sqrt(inten) * px if side < 0.75 else 0.0
            if l1 == 0 and l2 == 0:
                l1 = 10 * px
            width = rng.uniform(2.5, 4.0) * px
            seg = LineString([tuple(centre - nj * l1), tuple(centre + nj * l2)])
            strips.append(seg.buffer(width / 2.0, cap_style="flat"))

    n_a = int(np.clip(round(9 * inten), 3, 24))
    n_b = int(np.clip(round(6 * inten), 2, 16))
    add_strips(road_a, np.linspace(0.08, 0.92, n_a) + rng.uniform(-0.015, 0.015, n_a))
    add_strips(road_b, np.linspace(0.06, 0.55, n_b) + rng.uniform(-0.015, 0.015, n_b))

    # --- T2 blob clearings
    n_blobs = int(np.clip(round(8 * inten), 3, 24))
    blobs = []
    for _ in range(n_blobs):
        cx, cy = _px_to_map(rng.uniform(0.08, 0.92) * size, rng.uniform(0.08, 0.92) * size, transform)
        r = rng.uniform(3.0, 8.0) * np.sqrt(inten) * px
        blobs.append(_ellipse(float(cx), float(cy), r, rng.uniform(0.5, 1.0), rng.uniform(0, 180)))
    clearing_mask = _rasterize(strips + blobs, transform, shape)

    # --- regrowth: three of the old pasture blocks become secondary vegetation
    regrow_idx = [0, 2, 3]
    regrow_mask = _rasterize([blocks[i] for i in regrow_idx], transform, shape)

    ref_t2 = ref_t1.copy()
    ref_t2[clearing_mask & (ref_t1 == 1)] = 2
    ref_t2[regrow_mask & (ref_t1 == 2)] = 5
    ref_t2[river_mask] = 3
    ref_t2[road_mask] = 4

    # --- clouds at T2 (two blobs)
    clouds = []
    for fx, fy in [(rng.uniform(0.15, 0.45), rng.uniform(0.15, 0.45)),
                   (rng.uniform(0.55, 0.85), rng.uniform(0.55, 0.85))]:
        cx, cy = _px_to_map(fx * size, fy * size, transform)
        r = rng.uniform(0.035, 0.055) * size * px
        clouds.append(_ellipse(float(cx), float(cy), r, rng.uniform(0.6, 1.0), rng.uniform(0, 180)))
    cloud_mask = _rasterize(clouds, transform, shape)

    return {
        "reference_t1": ref_t1,
        "reference_t2": ref_t2,
        "cloud_mask_t2": cloud_mask,
        "roads": roads_gdf,
        "river": river_gdf,
    }


# --------------------------------------------------------------------------- spectra
def spectral_stack(reference: np.ndarray, rng, cloud_mask=None, texture_sigma: float = 3.0,
                   texture_std: float = 0.10, pixel_noise: float = 0.05,
                   band_noise_std: float = 0.05, illumination=None) -> np.ndarray:
    """
    Simulate a (6, rows, cols) float32 reflectance stack (0..1) from a class raster.

    * per-pixel mixing between two end-members per class (smooth random fraction),
    * shared smooth texture (canopy density / soil brightness) across bands,
    * a small independent smooth field per band,
    * white per-pixel noise,
    * optional multiplicative ``illumination`` field,
    * bright cloud pixels where ``cloud_mask`` is True.
    """
    ref = np.asarray(reference)
    rows, cols = ref.shape
    shape = (rows, cols)
    texture = _smooth_field(rng, shape, texture_sigma, texture_std)
    mix = np.clip(0.5 + _smooth_field(rng, shape, 6.0, 0.35), 0.0, 1.0)
    stack = np.zeros((6, rows, cols), dtype=np.float32)
    for b in range(6):
        band = np.zeros(shape, dtype=np.float64)
        for cls, means in CLASS_MEANS.items():
            sel = ref == cls
            band[sel] = (1.0 - mix[sel]) * means[b] + mix[sel] * CLASS_ALT[cls][b]
        band *= (1.0 + texture)
        band *= (1.0 + _smooth_field(rng, shape, 2.0, band_noise_std))
        band *= (1.0 + rng.normal(0.0, pixel_noise, shape))
        if illumination is not None:
            band *= illumination
        if cloud_mask is not None and np.any(cloud_mask):
            n_cloud = int(np.count_nonzero(cloud_mask))
            band[cloud_mask] = CLOUD_MEAN[b] * (1.0 + rng.normal(0.0, 0.05, n_cloud))
        stack[b] = np.clip(band, 0.0, 1.0).astype(np.float32)
    return stack


# --------------------------------------------------------------------------- public entry point
def generate_demo_data(size: int = 200, seed: int = 42, out_dir=None,
                       clearing_intensity: float = 1.0, pixel_size: float = PIXEL_SIZE) -> dict:
    """
    Generate the synthetic two-date scene and write it to ``out_dir``.

    Parameters
    ----------
    size : raster width and height in pixels (default 200 -> 4 km x 4 km at 20 m).
    seed : random seed (deterministic output).
    out_dir : folder for the files (created if missing). If None nothing is written.
    clearing_intensity : multiplier (0.5 .. 2.0) on the number and size of T2 clearings.
    pixel_size : pixel size in metres (20 m).

    Returns
    -------
    dict with keys
        ``t1_stack``, ``t2_stack``            (6, size, size) float32 reflectance arrays
        ``reference_t1``, ``reference_t2``    uint8 truth class rasters (1..5)
        ``cloud_mask_t2``                     bool cloud mask for T2
        ``roads``, ``river``                  GeoDataFrames (EPSG:32720)
        ``profile``                           rasterio profile of the 6-band stacks
        ``class_profile``                     profile for single-band uint8 rasters (nodata 0)
        ``bounds``                            (west, south, east, north) in EPSG:32720
        ``crs``                               "EPSG:32720"
        ``pixel_size``                        pixel size in metres
        ``pixel_area_ha``                     area of one pixel in hectares
        ``dates``                             {"t1": "2019-07-15", "t2": "2024-07-15", "years": 5.0}
        ``paths``                             dict of written files (empty if out_dir is None):
                                              t1_stack, t2_stack, reference_t1, reference_t2,
                                              cloud_mask_t2, roads, river
    """
    size = int(size)
    rng = np.random.default_rng(seed)
    west, south, east, north = scene_bounds(size, pixel_size)
    transform = from_bounds(west, south, east, north, size, size)
    crs = CRS.from_epsg(EPSG_CODE)
    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 6, "crs": crs, "transform": transform,
        "width": size, "height": size, "nodata": None, "compress": "lzw",
    }
    class_profile = dict(profile, dtype="uint8", count=1, nodata=0)

    land = build_landscape(size, rng, transform, pixel_size, clearing_intensity)
    illum_t1 = 1.0 + _smooth_field(rng, (size, size), sigma=max(4, size / 4), std=0.02)
    illum_t2 = 0.98 + _smooth_field(rng, (size, size), sigma=max(4, size / 4), std=0.03)
    t1_stack = spectral_stack(land["reference_t1"], rng, illumination=illum_t1)
    t2_stack = spectral_stack(land["reference_t2"], rng, cloud_mask=land["cloud_mask_t2"],
                              illumination=illum_t2)

    paths = {}
    if out_dir is not None:
        out_dir = ensure_directory(out_dir)
        paths["t1_stack"] = write_stack(t1_stack, profile, out_dir / "t1_stack.tif", BAND_NAMES)
        paths["t2_stack"] = write_stack(t2_stack, profile, out_dir / "t2_stack.tif", BAND_NAMES)
        paths["reference_t1"] = write_raster(land["reference_t1"], class_profile,
                                             out_dir / "reference_t1.tif", nodata=0, dtype="uint8")
        paths["reference_t2"] = write_raster(land["reference_t2"], class_profile,
                                             out_dir / "reference_t2.tif", nodata=0, dtype="uint8")
        paths["cloud_mask_t2"] = write_raster(land["cloud_mask_t2"].astype(np.uint8), class_profile,
                                              out_dir / "cloud_mask_t2.tif", nodata=None, dtype="uint8")
        paths["roads"] = write_vector(land["roads"], out_dir / "roads.gpkg", layer="roads")
        paths["river"] = write_vector(land["river"], out_dir / "river.gpkg", layer="river")

    return {
        "t1_stack": t1_stack,
        "t2_stack": t2_stack,
        "reference_t1": land["reference_t1"],
        "reference_t2": land["reference_t2"],
        "cloud_mask_t2": land["cloud_mask_t2"],
        "roads": land["roads"],
        "river": land["river"],
        "profile": profile,
        "class_profile": class_profile,
        "bounds": (west, south, east, north),
        "crs": f"EPSG:{EPSG_CODE}",
        "pixel_size": float(pixel_size),
        "pixel_area_ha": float(pixel_size * pixel_size / 10000.0),
        "dates": {"t1": "2019-07-15", "t2": "2024-07-15", "years": 5.0},
        "paths": paths,
    }
