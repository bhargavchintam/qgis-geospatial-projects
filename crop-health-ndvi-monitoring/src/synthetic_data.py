"""
Synthetic Sentinel-2 season for Story County, Iowa.

Builds a small, fully offline multi-temporal Level-2A style dataset that the
real pipeline consumes unchanged:

* one scene folder per date  ``S2A_MSIL2A_YYYYMMDDT170000_demo/`` holding the
  ten reflectance bands (B02..B12) plus the scene classification layer (SCL)
  as uint16 GeoTIFFs (DN = reflectance x 10000, SCL classes as integers);
* a GeoJSON of corn / soybean field polygons tiling the scene with road gaps.

Reflectances are driven by a per-field double-logistic NDVI phenology
(corn peaks ~0.85 near DOY 200, soybean later and lower), a per-pixel texture
field, growing stress patches, nitrogen-stressed fields with a weaker red-edge
signal, and cloud / shadow blobs on three dates.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_bounds
from scipy import ndimage
from shapely.geometry import box

from .utils import rasterize_fields

STUDY_AREA_LONLAT = (-93.62, 42.03)  # Story County, Iowa
CRS = "EPSG:32615"  # UTM zone 15N
PIXEL_SIZE_M = 10.0

BAND_NAMES = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
BANDS_20M = {"B05", "B06", "B07", "B8A", "B11", "B12"}
IDX = {b: i for i, b in enumerate(BAND_NAMES)}

# Spectral endmembers (surface reflectance, 0..1) for the ten bands above.
SOIL = np.array([0.050, 0.070, 0.100, 0.115, 0.125, 0.130, 0.130, 0.135, 0.220, 0.170])
GREEN_VEG = np.array([0.025, 0.055, 0.025, 0.120, 0.300, 0.400, 0.450, 0.470, 0.170, 0.070])
SENESCENT_VEG = np.array([0.060, 0.100, 0.140, 0.200, 0.300, 0.340, 0.360, 0.370, 0.320, 0.220])
CLOUD = np.array([0.62, 0.60, 0.58, 0.58, 0.57, 0.57, 0.56, 0.56, 0.45, 0.40])

SEASON_START = datetime(2024, 4, 5)
SEASON_END = datetime(2024, 10, 20)
N_DATES = 14

# Sentinel-2 SCL classes used here
SCL_SHADOW, SCL_VEG, SCL_BARE, SCL_CLOUD_MED, SCL_CLOUD_HIGH = 3, 4, 5, 8, 9


def acquisition_dates() -> List[datetime]:
    """14 dates from 2024-04-05 to 2024-10-20, roughly every 15 days."""
    span = (SEASON_END - SEASON_START).days
    offsets = np.round(np.linspace(0, span, N_DATES)).astype(int)
    return [SEASON_START + timedelta(days=int(o)) for o in offsets]


def double_logistic(doy, a1, a2, a3, a4, a5, a6):
    """Same phenology model the analysis fits: baseline + rise - fall."""
    return a1 + a2 * (
        1.0 / (1.0 + np.exp(-a3 * (doy - a4))) - 1.0 / (1.0 + np.exp(-a5 * (doy - a6)))
    )


def scene_profile(size: int) -> dict:
    """rasterio profile for a size x size, 10 m grid centred on the study area."""
    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    cx, cy = to_utm.transform(*STUDY_AREA_LONLAT)
    half = size * PIXEL_SIZE_M / 2.0
    west = np.floor((cx - half) / 10.0) * 10.0
    south = np.floor((cy - half) / 10.0) * 10.0
    east = west + size * PIXEL_SIZE_M
    north = south + size * PIXEL_SIZE_M
    transform = from_bounds(west, south, east, north, size, size)
    return dict(
        driver="GTiff",
        dtype="uint16",
        count=1,
        width=size,
        height=size,
        crs=rasterio.crs.CRS.from_string(CRS),
        transform=transform,
        nodata=0,
        compress="lzw",
    )


def _split_positions(n_cells: int, size: int, rng: np.random.Generator) -> np.ndarray:
    """Jittered cell boundaries in pixel units, from 0 to size."""
    edges = np.linspace(0, size, n_cells + 1)
    cell = size / n_cells
    edges[1:-1] += rng.uniform(-cell / 6.0, cell / 6.0, n_cells - 1)
    return np.round(edges).astype(int)


def make_fields(size: int, profile: dict, rng: np.random.Generator) -> gpd.GeoDataFrame:
    """
    Rectangular fields on a jittered grid with road gaps, some merged with a
    neighbour. Columns: field_id, crop, truth_n_stress, area_ha, geometry.
    """
    n_cols = int(np.clip(round(size / 28), 3, 8))
    n_rows = int(np.clip(round(size / 32), 3, 8))
    gap = max(1, int(round(size / 100)))  # half road width in pixels
    col_edges = _split_positions(n_cols, size, rng)
    row_edges = _split_positions(n_rows, size, rng)

    # cell -> [r0, r1, c0, c1] in pixel indices (exclusive upper bounds)
    cells = {}
    for r in range(n_rows):
        for c in range(n_cols):
            cells[(r, c)] = [row_edges[r] + gap, row_edges[r + 1] - gap,
                             col_edges[c] + gap, col_edges[c + 1] - gap]

    merged_into = {}
    order = list(cells.keys())
    rng.shuffle(order)
    for (r, c) in order:
        if (r, c) in merged_into:
            continue
        right, down = (r, c + 1), (r + 1, c)
        if right in cells and right not in merged_into and rng.random() < 0.22:
            cells[(r, c)][3] = cells[right][3]
            merged_into[right] = (r, c)
        elif down in cells and down not in merged_into and rng.random() < 0.12:
            cells[(r, c)][1] = cells[down][1]
            merged_into[down] = (r, c)

    tr = profile["transform"]
    west, north = tr.c, tr.f
    px = PIXEL_SIZE_M
    records = []
    k = 0
    for key in sorted(cells.keys()):
        if key in merged_into:
            continue
        r0, r1, c0, c1 = cells[key]
        if r1 - r0 < 3 or c1 - c0 < 3:
            continue
        geom = box(west + c0 * px, north - r1 * px, west + c1 * px, north - r0 * px)
        k += 1
        records.append({
            "field_id": f"F{k:03d}",
            "crop": "corn" if rng.random() < 0.55 else "soybean",
            "area_ha": round(geom.area / 10_000.0, 2),
            "geometry": geom,
        })
    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=CRS)

    n_stress = max(1, int(round(len(gdf) * 0.12)))
    stressed = rng.choice(len(gdf), size=n_stress, replace=False)
    gdf["truth_n_stress"] = False
    gdf.loc[gdf.index[stressed], "truth_n_stress"] = True
    return gdf


def field_phenology_params(gdf: gpd.GeoDataFrame, rng: np.random.Generator) -> np.ndarray:
    """One (a1..a6) parameter row per field; corn peaks ~0.85 near DOY 200."""
    n = len(gdf)
    params = np.zeros((n, 6))
    for i, crop in enumerate(gdf["crop"].values):
        if crop == "corn":
            a1 = rng.normal(0.17, 0.015)
            peak = rng.normal(0.85, 0.02)
            a3 = rng.normal(0.105, 0.010)
            a4 = rng.normal(153, 4)
            a5 = rng.normal(0.080, 0.008)
            a6 = rng.normal(272, 4)
        else:  # soybean: later green-up, lower peak, faster senescence
            a1 = rng.normal(0.15, 0.015)
            peak = rng.normal(0.78, 0.025)
            a3 = rng.normal(0.115, 0.010)
            a4 = rng.normal(170, 4)
            a5 = rng.normal(0.110, 0.010)
            a6 = rng.normal(266, 4)
        if gdf["truth_n_stress"].iloc[i]:
            peak -= 0.05
        # amplitude so that the curve maximum lands on the intended peak
        t = np.arange(90, 320)
        shape = double_logistic(t, 0.0, 1.0, a3, a4, a5, a6).max()
        a2 = (peak - a1) / shape
        params[i] = [a1, a2, a3, a4, a5, a6]
    return params


def make_stress_patches(size: int, gdf, id_raster, rng) -> List[dict]:
    """4 to 6 gaussian stress blobs placed inside fields, growing over the season."""
    n_patches = int(rng.integers(4, 7))
    patches = []
    field_pixels = np.argwhere(id_raster > 0)
    for _ in range(n_patches):
        r, c = field_pixels[rng.integers(len(field_pixels))]
        patches.append({
            "row": float(r),
            "col": float(c),
            "radius": size * rng.uniform(0.035, 0.065),  # final radius (px)
            "start_doy": float(rng.uniform(150, 215)),
            "duration": float(rng.uniform(35, 70)),
            "depth": float(rng.uniform(0.55, 0.85)),
        })
    return patches


def vigor_field(size: int, patches: List[dict], doy: float) -> np.ndarray:
    """Per-pixel vigour in [0, 1]: 1 = healthy, lower inside stress patches."""
    rr, cc = np.mgrid[0:size, 0:size]
    vigor = np.ones((size, size))
    for p in patches:
        growth = np.clip((doy - p["start_doy"]) / p["duration"], 0.0, 1.0)
        if growth <= 0:
            continue
        radius = p["radius"] * (0.3 + 0.7 * growth)
        d2 = (rr - p["row"]) ** 2 + (cc - p["col"]) ** 2
        blob = np.exp(-d2 / (2.0 * radius ** 2))
        vigor *= 1.0 - p["depth"] * growth * blob
    return vigor


def cloud_masks(size: int, rng, coverage: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (cloud_core, cloud_edge, shadow) boolean masks for one date."""
    noise = ndimage.gaussian_filter(rng.normal(size=(size, size)), sigma=size * 0.06)
    thr = np.quantile(noise, 1.0 - coverage)
    cloud = noise > thr
    core = noise > np.quantile(noise, 1.0 - 0.6 * coverage)
    edge = cloud & ~core
    dy, dx = int(round(size * 0.05)), int(round(-size * 0.04))
    shadow = np.roll(np.roll(cloud, dy, axis=0), dx, axis=1) & ~cloud
    return core, edge, shadow


def _solve_vegetation_fraction(target_ndvi, veg_em, soil_em):
    """Vegetation fraction f so that a linear soil/veg mix has the target NDVI."""
    nir_v, red_v = veg_em[IDX["B08"]], veg_em[IDX["B04"]]
    nir_s, red_s = soil_em[IDX["B08"]], soil_em[IDX["B04"]]
    A = (nir_v - red_v) - (nir_s - red_s)
    B = nir_s - red_s
    C = (nir_v + red_v) - (nir_s + red_s)
    D = nir_s + red_s
    f = (target_ndvi * D - B) / (A - target_ndvi * C)
    return np.clip(f, 0.0, 1.0)


def _block_mean(arr: np.ndarray, b: int = 2) -> np.ndarray:
    h, w = arr.shape
    return arr[: h - h % b, : w - w % b].reshape(h // b, b, w // b, b).mean(axis=(1, 3))


def _block_max(arr: np.ndarray, b: int = 2) -> np.ndarray:
    h, w = arr.shape
    return arr[: h - h % b, : w - w % b].reshape(h // b, b, w // b, b).max(axis=(1, 3))


def generate_demo_data(size: int = 200, seed: int = 42, out_dir=None) -> Dict:
    """
    Generate the synthetic Story County season and write it to disk.

    Args:
        size: scene width/height in 10 m pixels (rounded up to an even number).
        seed: RNG seed; the whole dataset is deterministic for a given seed.
        out_dir: root output folder (``results/demo/data`` in the demo).

    Returns a dict with:
        ``sentinel_dir``   Path of the folder holding one scene sub-folder per date
        ``fields_path``    Path of the field polygons GeoJSON (EPSG:32615)
        ``fields``         the field GeoDataFrame (field_id, crop, truth_n_stress, area_ha)
        ``dates``          list of 14 datetime acquisition dates
        ``doy``            numpy array of day-of-year for each date
        ``profile``        rasterio profile of the 10 m grid (uint16 DN)
        ``ndvi_true``      float array [time, rows, cols] of the noise-free target NDVI
        ``cloud_percent``  list of % pixels covered by cloud or shadow per date
        ``cloud_dates``    list of dates that carry cloud blobs
        ``patches``        list of stress patch dicts (row, col, radius, start_doy, ...)
        ``field_params``   array [n_fields, 6] of the true double-logistic parameters
    """
    size = int(size) + int(size) % 2
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir) if out_dir is not None else Path("results/demo/data")
    sentinel_dir = out_dir / "sentinel2"
    sentinel_dir.mkdir(parents=True, exist_ok=True)

    profile = scene_profile(size)
    dates = acquisition_dates()
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)

    # --- fields, phenology, stress ---------------------------------------
    fields = make_fields(size, profile, rng)
    fields_path = out_dir / "fields.geojson"
    fields.to_file(fields_path, driver="GeoJSON")
    id_raster, _ = rasterize_fields(fields, profile)
    params = field_phenology_params(fields, rng)
    patches = make_stress_patches(size, fields, id_raster, rng)

    # static per-pixel texture (soil variability) and N-stress raster
    texture = ndimage.gaussian_filter(rng.normal(size=(size, size)), sigma=max(2.0, size / 60))
    texture = 1.0 + 0.05 * texture / (texture.std() + 1e-9)
    n_stress_raster = np.zeros((size, size), dtype=bool)
    stressed_ids = np.where(fields["truth_n_stress"].values)[0] + 1
    n_stress_raster = np.isin(id_raster, stressed_ids)

    # cloud dates: both October scenes plus one mid-season date
    mid = int(rng.integers(3, 10))
    cloud_idx = {mid, N_DATES - 2, N_DATES - 1}
    cloud_cov = {i: float(rng.uniform(0.20, 0.45)) for i in cloud_idx}

    ndvi_true = np.zeros((N_DATES, size, size), dtype=np.float32)
    cloud_percent = []
    road_mask = id_raster == 0
    fid = np.maximum(id_raster - 1, 0)  # field index per pixel (roads -> 0, masked below)

    for ti, (date, d) in enumerate(zip(dates, doy)):
        # per-pixel phenology from the owning field
        p = params[fid]  # (H, W, 6)
        ndvi_pheno = double_logistic(d, p[..., 0], p[..., 1], p[..., 2], p[..., 3], p[..., 4], p[..., 5])
        senescence = 1.0 / (1.0 + np.exp(-p[..., 4] * (d - p[..., 5])))  # 0 green -> 1 brown
        baseline = p[..., 0]
        vigor = vigor_field(size, patches, d)
        target = baseline + (ndvi_pheno - baseline) * vigor * texture
        # road corridors: grassy verge, weak seasonality
        target = np.where(road_mask, 0.18 + 0.10 * np.exp(-((d - 190) / 60.0) ** 2), target)
        target = target + rng.normal(0.0, 0.012, size=(size, size))
        target = np.clip(target, 0.05, 0.92)
        ndvi_true[ti] = target

        # spectral mixing: soil + (green/brown) vegetation
        sen = np.where(road_mask, 0.3, senescence)[..., None]
        veg_em = (1.0 - sen) * GREEN_VEG + sen * SENESCENT_VEG  # (H, W, 10)
        f = _solve_vegetation_fraction(target, np.moveaxis(veg_em, -1, 0), SOIL[:, None, None])
        refl = f[..., None] * veg_em + (1.0 - f[..., None]) * SOIL  # (H, W, 10)

        # nitrogen stress: weaker red-edge absorption (higher B05/B06) -> lower NDRE
        ns = n_stress_raster * np.clip(f, 0, 1)
        refl[..., IDX["B05"]] *= 1.0 + 0.30 * ns
        refl[..., IDX["B06"]] *= 1.0 + 0.08 * ns

        # atmosphere/brightness and band noise
        refl *= rng.normal(1.0, 0.03)
        refl *= rng.normal(1.0, 0.02, size=refl.shape)

        scl = np.where(target < 0.25, SCL_BARE, SCL_VEG).astype(np.uint16)

        if ti in cloud_idx:
            core, edge, shadow = cloud_masks(size, rng, cloud_cov[ti])
            cloud_col = CLOUD * rng.normal(1.0, 0.03)
            refl[core] = cloud_col + rng.normal(0, 0.02, size=(core.sum(), 10))
            refl[edge] = 0.45 * refl[edge] + 0.55 * cloud_col
            refl[shadow] *= 0.45
            scl[core] = SCL_CLOUD_HIGH
            scl[edge] = SCL_CLOUD_MED
            scl[shadow] = SCL_SHADOW
            cloud_percent.append(round(100.0 * (core | edge | shadow).mean(), 2))
        else:
            cloud_percent.append(0.0)

        refl = np.clip(refl, 0.0001, 1.0)
        dn = np.clip(np.round(refl * 10000.0), 1, 10000).astype(np.uint16)

        scene_dir = sentinel_dir / f"S2A_MSIL2A_{date.strftime('%Y%m%d')}T170000_demo"
        scene_dir.mkdir(parents=True, exist_ok=True)
        prof20 = dict(profile)
        b = profile["transform"].c, profile["transform"].f
        prof20.update(width=size // 2, height=size // 2,
                      transform=from_bounds(b[0], b[1] - size * PIXEL_SIZE_M,
                                            b[0] + size * PIXEL_SIZE_M, b[1], size // 2, size // 2))
        for band in BAND_NAMES:
            arr = dn[..., IDX[band]]
            if band in BANDS_20M:  # native 20 m bands are written at 20 m
                arr20 = np.round(_block_mean(arr.astype(float))).astype(np.uint16)
                with rasterio.open(scene_dir / f"{band}.tif", "w", **prof20) as dst:
                    dst.write(arr20, 1)
            else:
                with rasterio.open(scene_dir / f"{band}.tif", "w", **profile) as dst:
                    dst.write(arr, 1)
        scl_prof = dict(prof20)
        scl_prof.update(nodata=None)
        with rasterio.open(scene_dir / "SCL.tif", "w", **scl_prof) as dst:
            dst.write(_block_max(scl).astype(np.uint16), 1)

    return {
        "sentinel_dir": sentinel_dir,
        "fields_path": fields_path,
        "fields": fields,
        "dates": dates,
        "doy": doy,
        "profile": profile,
        "ndvi_true": ndvi_true,
        "cloud_percent": cloud_percent,
        "cloud_dates": [dates[i] for i in sorted(cloud_idx)],
        "patches": patches,
        "field_params": params,
    }
