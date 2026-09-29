"""
Synthetic demo scene: a small Harris County, TX (Houston) coastal plain.

Everything is generated offline with a fixed seed, georeferenced in
EPSG:32615 (UTM 15N) at 30 m, centred on downtown Houston (-95.37, 29.76).
The scene has a gentle plain (5 to 60 m) sloping from north-west to
south-east, one meandering main bayou with two tributaries carved in, a
developed urban core, wetlands along the channel, cropland, forest patches,
a population surface, ~25 critical facilities and a census block grid with
a social vulnerability index.
"""

from pathlib import Path
from typing import Dict, Tuple

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from scipy.ndimage import distance_transform_edt, gaussian_filter
from shapely.geometry import LineString, Point, box

CRS = "EPSG:32615"
CENTER_X, CENTER_Y = 270_838.0, 3_294_545.0  # -95.37, 29.76 in UTM 15N
RESOLUTION = 30.0

FACILITY_TYPES = [
    "hospital",
    "fire_station",
    "police_station",
    "school",
    "emergency_shelter",
    "power_station",
    "water_treatment",
]


def _smooth_noise(rng: np.random.Generator, shape: Tuple[int, int], sigma: float) -> np.ndarray:
    """Unit-variance smooth random field."""
    field = gaussian_filter(rng.normal(size=shape), sigma)
    return field / (field.std() + 1e-12)


def _channel_path(rng: np.random.Generator, size: int, start, end, amplitude: float,
                  n_bends: float, n_pts: int = 400) -> np.ndarray:
    """Meandering polyline (row, col) between two points, sampled densely."""
    t = np.linspace(0.0, 1.0, n_pts)
    r = start[0] + (end[0] - start[0]) * t
    c = start[1] + (end[1] - start[1]) * t
    # perpendicular direction to the straight line
    dr, dc = end[0] - start[0], end[1] - start[1]
    norm = np.hypot(dr, dc) + 1e-9
    pr, pc = -dc / norm, dr / norm
    phase = rng.uniform(0, 2 * np.pi)
    wiggle = amplitude * np.sin(2 * np.pi * n_bends * t + phase) * np.sin(np.pi * t) ** 0.5
    wiggle += amplitude * 0.35 * gaussian_filter(rng.normal(size=n_pts), 25)
    r = r + pr * wiggle
    c = c + pc * wiggle
    r = np.clip(r, 0, size - 1)
    c = np.clip(c, 0, size - 1)
    return np.column_stack([r, c])


def _path_cells(path: np.ndarray) -> np.ndarray:
    """Unique (row, col) integer cells along a dense polyline, in order."""
    cells = np.round(path).astype(int)
    keep = np.ones(len(cells), dtype=bool)
    keep[1:] = np.any(cells[1:] != cells[:-1], axis=1)
    cells = cells[keep]
    # drop revisits so every cell has a single along-channel index
    seen, out = set(), []
    for rc in map(tuple, cells):
        if rc not in seen:
            seen.add(rc)
            out.append(rc)
    return np.array(out)


def _carve_channel(
    dem: np.ndarray,
    cells: np.ndarray,
    depth: float,
    valley_width_cells: float,
    min_drop: float,
    outlet_level: float = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Cut a channel into ``dem`` along ``cells`` (ordered upstream to downstream).

    The bed sits ``depth`` below the terrain and is forced to descend by at
    least ``min_drop`` per cell (running minimum), so it is never above
    ``terrain - depth`` and always drains to the last cell. If
    ``outlet_level`` is given (a tributary joining a main channel) the bed
    is additionally kept above that level so the junction drains the right
    way. A gaussian valley whose depth equals the local incision (terrain
    minus bed) is subtracted around the channel so the floodplain slopes
    toward it. Nothing is ever raised.

    Returns (carved dem, bed elevation per channel cell).
    """
    mask = np.zeros(dem.shape, dtype=bool)
    mask[cells[:, 0], cells[:, 1]] = True
    base_along = dem[cells[:, 0], cells[:, 1]]

    n_cells = len(cells)
    bed = np.minimum.accumulate(base_along - depth - min_drop * np.arange(n_cells))
    if outlet_level is not None:
        floor = outlet_level + min_drop * np.arange(n_cells)[::-1]
        bed = np.maximum(bed, floor)
    incision = np.maximum(base_along - bed, 0.0)

    order = np.full(dem.shape, -1, dtype=int)
    order[cells[:, 0], cells[:, 1]] = np.arange(n_cells)
    dist, (ir, ic) = distance_transform_edt(~mask, return_indices=True)
    t_near = order[ir, ic]
    carved = dem - incision[t_near] * np.exp(-(dist / valley_width_cells) ** 2)
    carved[mask] = np.minimum(carved[mask], bed[order[mask]])
    return carved, bed


def _write_tif(path: Path, arr: np.ndarray, profile: dict, dtype=np.float32, nodata=None) -> str:
    prof = dict(profile)
    prof.update(dtype=dtype, count=1, compress="lzw")
    if nodata is not None:
        prof["nodata"] = nodata
    else:
        prof.pop("nodata", None)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(np.asarray(arr, dtype=dtype), 1)
    return str(path)


def generate_demo_data(size: int = 200, seed: int = 42, out_dir: Path = Path("results/demo/data")) -> Dict:
    """
    Generate the synthetic Harris County scene.

    Args:
        size: grid size (size x size cells at 30 m)
        seed: random seed (fully deterministic)
        out_dir: output folder (created if missing)

    Returns a dict with these keys:
        dem, rainfall, ksat, nlcd, population, infrastructure, census_svi,
        boundary: file paths (GeoTIFF / GeoPackage) written into out_dir
        profile: rasterio profile shared by every raster (float32, EPSG:32615)
        bounds: (west, south, east, north) in EPSG:32615
        crs: "EPSG:32615"
        resolution: 30.0 (metres)
        arrays: dict of the in-memory rasters (dem, rainfall, ksat, nlcd, population)
        infrastructure_gdf, census_gdf, boundary_gdf: the vector layers in memory
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    n = int(size)
    res = RESOLUTION

    half = n * res / 2.0
    west, east = CENTER_X - half, CENTER_X + half
    south, north = CENTER_Y - half, CENTER_Y + half
    transform = from_bounds(west, south, east, north, n, n)
    profile = {
        "driver": "GTiff", "height": n, "width": n, "count": 1,
        "dtype": "float32", "crs": CRS, "transform": transform, "nodata": None,
    }

    rr, cc = np.mgrid[0:n, 0:n]
    x_n = cc / (n - 1)  # 0 west -> 1 east
    y_n = rr / (n - 1)  # 0 north -> 1 south

    # ---------------------------------------------------------------- DEM
    # coastal plain falling from the north-west (high) to the south-east (coast)
    plain = 0.75 * (1 - x_n) + 0.25 * (1 - y_n)
    dem = 12.0 + 44.0 * plain
    dem += 1.5 * _smooth_noise(rng, (n, n), sigma=max(n / 5, 4))  # broad, gentle undulation

    # main bayou: enters on the west edge, exits on the east edge further south
    main_path = _channel_path(
        rng, n, start=(0.30 * n, 0), end=(0.68 * n, n - 1), amplitude=0.07 * n, n_bends=2.5
    )
    main_cells = _path_cells(main_path)
    dem, main_bed = _carve_channel(
        dem, main_cells, depth=6.0, valley_width_cells=max(n / 10, 3), min_drop=0.008
    )

    # tributaries rise on high ground and join the main channel at ~35 % and ~70 %
    k1, k2 = int(0.35 * len(main_cells)), int(0.70 * len(main_cells))
    j1, j2 = main_cells[k1], main_cells[k2]
    trib1 = _path_cells(_channel_path(rng, n, start=(0, 0.28 * n), end=tuple(j1),
                                      amplitude=0.04 * n, n_bends=1.5, n_pts=250))
    trib2 = _path_cells(_channel_path(rng, n, start=(0.96 * n, 0.10 * n), end=tuple(j2),
                                      amplitude=0.04 * n, n_bends=1.5, n_pts=250))
    for trib, k in ((trib1, k1), (trib2, k2)):
        trib_cells = trib[:-1]  # the junction cell already belongs to the main channel
        dem, _ = _carve_channel(
            dem, trib_cells, depth=3.5, valley_width_cells=max(n / 22, 2),
            min_drop=0.006, outlet_level=main_bed[k] + 0.3,
        )

    channel_mask = np.zeros((n, n), dtype=bool)
    for cells in (main_cells, trib1, trib2):
        channel_mask[cells[:, 0], cells[:, 1]] = True
    dist_channel_cells = distance_transform_edt(~channel_mask)
    dist_channel_m = dist_channel_cells * res

    # terrain texture and a few shallow depressions, damped inside the valleys so the
    # channels keep their walls (real coastal plains have sinks; the fill step removes them)
    damping = 1.0 - np.exp(-(dist_channel_cells / max(n / 16, 2)) ** 2)
    texture = 2.5 * _smooth_noise(rng, (n, n), sigma=max(n / 25, 2))
    texture += 0.8 * _smooth_noise(rng, (n, n), sigma=max(n / 60, 1))
    for _ in range(4):
        pr, pc = rng.uniform(0.15, 0.85, 2) * (n - 1)
        rad = rng.uniform(0.03, 0.06) * n
        texture -= rng.uniform(1.0, 2.5) * np.exp(-((rr - pr) ** 2 + (cc - pc) ** 2) / (2 * rad ** 2))
    dem += texture * damping

    dem = np.clip(dem, 5.0, 60.0)
    dem_path = _write_tif(out_dir / "dem.tif", dem, profile)

    # ----------------------------------------------------------- rainfall
    # 100-year 24 h depth (mm): increases toward the coast (south-east)
    rain = 265 + 110 * (0.6 * x_n + 0.4 * y_n) + 18 * _smooth_noise(rng, (n, n), sigma=max(n / 12, 2))
    rain = np.clip(rain, 250, 400)
    rain_path = _write_tif(out_dir / "rainfall_100yr.tif", rain, profile)

    # --------------------------------------------------------------- Ksat
    # saturated hydraulic conductivity (micrometres/s): clay near the bayou, loam uplands
    upland = (dem - dem.min()) / (dem.max() - dem.min())
    ksat = 1.5 + 22 * upland * (1 - np.exp(-dist_channel_m / 500.0))
    ksat *= np.exp(0.35 * _smooth_noise(rng, (n, n), sigma=max(n / 20, 2)))
    ksat = np.clip(ksat, 0.5, 40)
    ksat_path = _write_tif(out_dir / "ksat.tif", ksat, profile)

    # --------------------------------------------------------------- NLCD
    core_r, core_c = 0.50 * n, 0.52 * n
    core_dist = np.hypot(rr - core_r, cc - core_c) * res  # metres
    urban = np.exp(-(core_dist / (0.22 * n * res)) ** 2)
    urban += 0.12 * _smooth_noise(rng, (n, n), sigma=max(n / 15, 2))

    nlcd = np.full((n, n), 81, dtype=np.int16)  # pasture/hay background
    crop = _smooth_noise(rng, (n, n), sigma=max(n / 10, 2)) > 0.2
    nlcd[crop] = 82  # cultivated crops
    forest = _smooth_noise(rng, (n, n), sigma=max(n / 18, 2)) > 0.9
    forest_type = _smooth_noise(rng, (n, n), sigma=max(n / 12, 2))
    nlcd[forest] = 41  # deciduous
    nlcd[forest & (forest_type > 0.3)] = 42  # evergreen (pine)
    nlcd[forest & (forest_type < -0.3)] = 43  # mixed
    nlcd[urban > 0.25] = 21
    nlcd[urban > 0.40] = 22
    nlcd[urban > 0.60] = 23
    nlcd[urban > 0.80] = 24
    wetland = (dist_channel_m <= 150) & (urban < 0.6)
    nlcd[wetland] = 90
    nlcd[wetland & (dist_channel_m > 90)] = 95
    nlcd[channel_mask] = 11  # open water
    nlcd_path = _write_tif(out_dir / "nlcd.tif", nlcd, profile, dtype=np.int16, nodata=0)

    # --------------------------------------------------------- population
    pop = 60 + 7500 * np.clip(urban, 0, 1) ** 1.3
    pop *= np.exp(0.25 * _smooth_noise(rng, (n, n), sigma=max(n / 30, 1)))
    pop[np.isin(nlcd, [11, 90, 95])] *= 0.15
    pop[np.isin(nlcd, [41, 42, 43])] *= 0.4
    pop = np.clip(pop, 0, 15000)
    pop_path = _write_tif(out_dir / "population_density.tif", pop, profile)

    # ------------------------------------------------ critical facilities
    n_fac = 25
    fac_rows, fac_cols, fac_types, fac_names = [], [], [], []
    counters = {t: 0 for t in FACILITY_TYPES}
    for i in range(n_fac):
        ftype = FACILITY_TYPES[i % len(FACILITY_TYPES)]
        if rng.uniform() < 0.65:  # most facilities sit in or near the urban core
            r = np.clip(rng.normal(core_r, 0.16 * n), 2, n - 3)
            c = np.clip(rng.normal(core_c, 0.16 * n), 2, n - 3)
        else:
            r, c = rng.uniform(2, n - 3, 2)
        if ftype == "water_treatment":  # treatment plants sit close to the bayou
            k = rng.integers(len(main_cells))
            r, c = np.clip(main_cells[k] + rng.normal(0, 3, 2), 2, n - 3)
        counters[ftype] += 1
        fac_rows.append(r)
        fac_cols.append(c)
        fac_types.append(ftype)
        fac_names.append(f"{ftype.replace('_', ' ').title()} {counters[ftype]}")
    xs = west + (np.array(fac_cols) + 0.5) * res
    ys = north - (np.array(fac_rows) + 0.5) * res
    infra = gpd.GeoDataFrame(
        {"name": fac_names, "type": fac_types},
        geometry=[Point(x, y) for x, y in zip(xs, ys)],
        crs=CRS,
    )
    infra_path = out_dir / "critical_infrastructure.gpkg"
    infra.to_file(infra_path, driver="GPKG")

    # --------------------------------------------------------- census SVI
    n_blocks = 10  # 10 x 10 grid of census blocks
    step = n * res / n_blocks
    low_income_r, low_income_c = 0.62 * n, 0.72 * n
    geoms, svi, ids, pops = [], [], [], []
    for i in range(n_blocks):
        for j in range(n_blocks):
            bw = west + j * step
            bs = north - (i + 1) * step
            geom = box(bw, bs, bw + step, bs + step)
            r0, r1 = int(i * n / n_blocks), int((i + 1) * n / n_blocks)
            c0, c1 = int(j * n / n_blocks), int((j + 1) * n / n_blocks)
            near_channel = np.exp(-np.mean(dist_channel_m[r0:r1, c0:c1]) / 700.0)
            cr, ccn = (r0 + r1) / 2, (c0 + c1) / 2
            low_income = np.exp(-(((cr - low_income_r) ** 2 + (ccn - low_income_c) ** 2)) / (2 * (0.14 * n) ** 2))
            value = 0.15 + 0.40 * near_channel + 0.45 * low_income + rng.normal(0, 0.06)
            geoms.append(geom)
            svi.append(float(np.clip(value, 0.02, 0.98)))
            ids.append(f"48201{i:02d}{j:02d}")
            pops.append(int(np.sum(pop[r0:r1, c0:c1]) * (res ** 2) / 1e6))
    census = gpd.GeoDataFrame(
        {"block_id": ids, "RPL_THEMES": np.round(svi, 3), "E_TOTPOP": pops},
        geometry=geoms, crs=CRS,
    )
    census_path = out_dir / "census_svi.gpkg"
    census.to_file(census_path, driver="GPKG")

    # ------------------------------------------------------------ boundary
    boundary = gpd.GeoDataFrame(
        {"name": ["Harris County demo scene"], "area_km2": [round((n * res) ** 2 / 1e6, 2)]},
        geometry=[box(west, south, east, north)], crs=CRS,
    )
    boundary_path = out_dir / "study_boundary.gpkg"
    boundary.to_file(boundary_path, driver="GPKG")

    # channel centrelines (for figures only)
    def _cells_to_line(cells):
        return LineString([(west + (c + 0.5) * res, north - (r + 0.5) * res) for r, c in cells])

    channels = gpd.GeoDataFrame(
        {"name": ["Main bayou", "Tributary 1", "Tributary 2"]},
        geometry=[_cells_to_line(main_cells), _cells_to_line(trib1), _cells_to_line(trib2)],
        crs=CRS,
    )

    return {
        "dem": dem_path,
        "rainfall": rain_path,
        "ksat": ksat_path,
        "nlcd": nlcd_path,
        "population": pop_path,
        "infrastructure": str(infra_path),
        "census_svi": str(census_path),
        "boundary": str(boundary_path),
        "profile": profile,
        "bounds": (west, south, east, north),
        "crs": CRS,
        "resolution": res,
        "arrays": {"dem": dem, "rainfall": rain, "ksat": ksat, "nlcd": nlcd, "population": pop},
        "infrastructure_gdf": infra,
        "census_gdf": census,
        "boundary_gdf": boundary,
        "channels_gdf": channels,
    }
