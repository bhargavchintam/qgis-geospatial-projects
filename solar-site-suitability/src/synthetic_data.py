"""
Synthetic demo scene: a desert basin near Kingman, Mohave County, Arizona.

The scene is an 18 km x 18 km square in EPSG:32612 (UTM zone 12N) centred
near lon -114.05, lat 35.19 (UTM 222300 E, 3898400 N). At the default
size of 200 pixels the resolution is 90 m; the extent stays fixed for any
size so all outputs line up on the same web map.

Layers written by ``generate_demo_data``:
    dem.tif                 elevation (m): basin floor ~900 m rising to
                            mountain ranges ~1800 m on the west and east
    ghi.tif                 global horizontal irradiance (kWh/m2/day, 5.6-6.8)
    landuse.tif             1 desert scrub, 2 agriculture, 3 urban,
                            4 water, 5 protected area
    transmission_lines.gpkg three polylines crossing the basin
    roads.gpkg              one highway and two secondary roads
    substations.gpkg        three points on the transmission lines
    residential.gpkg        polygons of the urban cluster
    protected_areas.gpkg    one large protected polygon
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from scipy import ndimage
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

from .utils import ensure_directory, write_raster, write_vector

STUDY_AREA = {
    "name": "Hualapai Valley near Kingman, Mohave County, Arizona",
    "crs": "EPSG:32612",
    "center_lon": -114.05,
    "center_lat": 35.19,
    "center_x": 222300.0,   # UTM 12N easting of the centre (m)
    "center_y": 3898400.0,  # UTM 12N northing of the centre (m)
    "extent_m": 18000.0,
}

LANDUSE_CODES = {1: "Desert scrub", 2: "Agriculture", 3: "Urban", 4: "Water", 5: "Protected area"}


def _smooth_noise(rng, size, sigma):
    """Unit-variance smooth random field."""
    field = ndimage.gaussian_filter(rng.normal(0.0, 1.0, (size, size)), sigma=sigma)
    std = field.std()
    return field / std if std > 0 else field


def _wash_x(fy):
    """Normalised easting of the dry wash as a function of normalised northing."""
    return 0.50 + 0.07 * np.sin(2.0 * np.pi * 1.3 * fy + 0.5)


def _tributary_channels(rng, size, res, n_west=6, n_east=4, depth=22.0, sigma_m=100.0):
    """Carve depth (m) for a dendritic network of tributaries joining the wash.

    Each tributary starts on a bajada and runs down-basin to the main wash.
    Returns an array of channel depths (Gaussian cross-section, ``sigma_m``
    metres wide, ``depth`` metres deep).
    """
    lines = []
    for side, count in (("west", n_west), ("east", n_east)):
        starts_y = np.sort(rng.uniform(0.05, 0.85, count))
        for y0 in starts_y:
            x0 = rng.uniform(0.10, 0.24) if side == "west" else rng.uniform(0.74, 0.88)
            y_end = min(y0 + rng.uniform(0.04, 0.12), 0.98)
            x_end = _wash_x(y_end)
            pts = []
            for t in np.linspace(0.0, 1.0, 6):
                x = x0 + (x_end - x0) * t
                y = y0 + (y_end - y0) * t + 0.02 * np.sin(np.pi * t * rng.uniform(1.0, 2.0))
                pts.append((x * size, (1.0 - y) * size))  # pixel coords (col, row)
            lines.append(LineString(pts))
    burned = features.rasterize(((g, 1) for g in lines), out_shape=(size, size), fill=0,
                                all_touched=True, dtype="uint8")
    if burned.sum() == 0:
        return np.zeros((size, size))
    dist_m = ndimage.distance_transform_edt(burned == 0) * res
    return depth * np.exp(-(dist_m / sigma_m) ** 2)


def _to_utm(coords, west, south, extent):
    """Convert normalised (fx, fy) pairs to UTM (x, y)."""
    return [(west + fx * extent, south + fy * extent) for fx, fy in coords]


def _polygons_from_mask(mask, transform, crs, name_prefix):
    """Polygonise a boolean raster mask into a GeoDataFrame."""
    geoms = []
    for geom, value in features.shapes(mask.astype(np.uint8), mask=mask, transform=transform, connectivity=8):
        if value == 1:
            geoms.append(shape(geom))
    if not geoms:
        return gpd.GeoDataFrame({"name": [], "area_ha": []}, geometry=gpd.GeoSeries([], crs=crs), crs=crs)
    gdf = gpd.GeoDataFrame({"geometry": geoms}, crs=crs)
    gdf["area_ha"] = (gdf.geometry.area / 10_000.0).round(2)
    gdf = gdf.sort_values("area_ha", ascending=False).reset_index(drop=True)
    gdf["name"] = [f"{name_prefix} {i + 1}" for i in range(len(gdf))]
    return gdf[["name", "area_ha", "geometry"]]


def generate_demo_data(size: int = 200, seed: int = 42, out_dir: Path = "results/demo/data",
                       extent_m: float = None) -> dict:
    """Generate the synthetic Kingman scene and write it to ``out_dir``.

    Args:
        size: raster width and height in pixels (extent stays 18 km).
        seed: numpy random seed (fully deterministic).
        out_dir: directory for the GeoTIFFs and GeoPackages.
        extent_m: optional override of the square extent in metres.

    Returns:
        dict with keys
            ``dem``, ``ghi``, ``landuse`` (GeoTIFF paths),
            ``transmission_lines``, ``roads``, ``substations``,
            ``residential``, ``protected_areas`` (GeoPackage paths),
            ``profile`` (rasterio profile shared by every raster),
            ``bounds`` (west, south, east, north in UTM metres),
            ``resolution`` (pixel size in metres),
            ``arrays`` (dict of the in-memory dem / ghi / landuse arrays),
            ``study_area`` (copy of STUDY_AREA).
    """
    out_dir = ensure_directory(out_dir)
    rng = np.random.default_rng(seed)
    extent = float(extent_m or STUDY_AREA["extent_m"])
    cx, cy = STUDY_AREA["center_x"], STUDY_AREA["center_y"]
    west, east = cx - extent / 2.0, cx + extent / 2.0
    south, north = cy - extent / 2.0, cy + extent / 2.0
    res = extent / size
    crs = CRS.from_string(STUDY_AREA["crs"])
    transform = from_bounds(west, south, east, north, size, size)
    profile = {
        "driver": "GTiff", "height": size, "width": size, "count": 1,
        "dtype": "float32", "crs": crs, "transform": transform,
        "nodata": np.nan, "compress": "lzw",
    }

    # Normalised coordinates of pixel centres: fx east 0..1, fy north 0..1
    jj, ii = np.meshgrid(np.arange(size), np.arange(size))
    fx = (jj + 0.5) / size
    fy = 1.0 - (ii + 0.5) / size

    # ------------------------------------------------------------------ DEM
    floor = 900.0 + 90.0 * (1.0 - fy) + 15.0 * np.abs(fx - 0.5)
    # Two meandering ranges (west and east) with peaks and saddles along strike
    west_axis = 0.05 + 0.04 * np.sin(2.0 * np.pi * 1.1 * fy + 0.3)
    east_axis = 0.96 + 0.03 * np.sin(2.0 * np.pi * 0.9 * fy + 2.0)
    west_peaks = 0.80 + 0.20 * np.sin(2.0 * np.pi * 2.3 * fy + 1.0)
    east_peaks = 0.80 + 0.20 * np.sin(2.0 * np.pi * 1.9 * fy + 2.4)
    west_range = west_peaks * 720.0 * np.exp(-((fx - west_axis) / 0.13) ** 2) \
        + 160.0 * np.exp(-((fx - west_axis) / 0.30) ** 2)
    east_range = east_peaks * 700.0 * np.exp(-((fx - east_axis) / 0.12) ** 2) \
        + 150.0 * np.exp(-((fx - east_axis) / 0.28) ** 2)
    mountains = west_range + east_range
    coarse = _smooth_noise(rng, size, sigma=max(size / 25.0, 1.0))
    fine = _smooth_noise(rng, size, sigma=max(size / 80.0, 0.6))
    roughness = coarse * (15.0 + 0.12 * mountains) + fine * (4.0 + 0.03 * mountains)
    # Dissected alluvial fans: short-wavelength relief that fades away from
    # the mountain fronts, plus a few low hills (inselbergs) on the basin floor
    fan_zone = np.clip((mountains - 40.0) / 250.0, 0.0, 1.0) * np.clip((450.0 - mountains) / 250.0, 0.0, 1.0)
    dissection = _smooth_noise(rng, size, sigma=max(size / 120.0, 0.5)) * 14.0 * fan_zone
    # Patchy gullying on the basin floor (intensity is itself a smooth random
    # field so some areas stay flat and others are dissected)
    gully_intensity = np.clip(0.5 + 0.5 * _smooth_noise(rng, size, sigma=max(size / 12.0, 1.0)), 0.0, 1.0)
    gullies = _smooth_noise(rng, size, sigma=max(size / 150.0, 0.5)) * 24.0 * gully_intensity * (mountains < 450.0)
    hills = np.zeros_like(fx)
    for _ in range(6):
        hx, hy = rng.uniform(0.22, 0.78), rng.uniform(0.08, 0.92)
        height = rng.uniform(40.0, 110.0)
        width = rng.uniform(0.018, 0.035)
        hills += height * np.exp(-(((fx - hx) ** 2 + (fy - hy) ** 2) / width ** 2))
    # Entrenched dry wash (about 350 m wide, 30 m deep) draining north, fed
    # by a dendritic set of tributaries that cut the bajadas into inter-wash
    # benches (the classic Basin and Range pattern)
    wash = 30.0 * np.exp(-((fx - _wash_x(fy)) / 0.010) ** 2)
    tributaries = _tributary_channels(rng, size, res)
    dem = floor + mountains + roughness + dissection + gullies + hills - wash - tributaries
    dem = dem.astype(np.float64)

    # ------------------------------------------------------------------ GHI
    gradient = 0.5 * (1.0 - fy) + 0.5 * (1.0 - fx)  # highest in the south-west
    ghi_noise = _smooth_noise(rng, size, sigma=max(size / 15.0, 1.0))
    ghi = 5.75 + 0.6 * gradient + 0.00025 * (dem - 900.0) + 0.08 * ghi_noise
    ghi = np.clip(ghi, 5.6, 6.8)

    # ------------------------------------------------------------- Land use
    landuse = np.ones((size, size), dtype=np.int32)

    # Agriculture patches along the wash on the basin floor
    for k in range(9):
        py = 0.08 + 0.10 * k + rng.uniform(-0.03, 0.03)
        side = rng.choice([-1.0, 1.0])
        px = _wash_x(py) + side * rng.uniform(0.03, 0.06)
        a = rng.uniform(0.035, 0.06)
        b = rng.uniform(0.02, 0.04)
        ellipse = ((fx - px) / a) ** 2 + ((fy - py) / b) ** 2 <= 1.0
        landuse[ellipse & (mountains < 120.0)] = 2

    # Protected area: one large irregular polygon on the eastern foothills
    protected_norm = [(0.66, 0.10), (0.80, 0.06), (0.99, 0.14), (0.99, 0.60),
                      (0.90, 0.70), (0.78, 0.66), (0.70, 0.50), (0.64, 0.30)]
    protected_poly = Polygon(_to_utm(protected_norm, west, south, extent))
    protected_gdf = gpd.GeoDataFrame(
        {"name": ["Synthetic Wilderness Study Area"], "designation": ["Wilderness Study Area"],
         "area_ha": [round(protected_poly.area / 10_000.0, 1)]},
        geometry=[protected_poly], crs=crs)
    protected_mask = features.rasterize([(protected_poly, 1)], out_shape=(size, size),
                                        transform=transform, fill=0, dtype="uint8") == 1
    landuse[protected_mask] = 5

    # Urban town cluster with an irregular edge plus two satellite blobs
    town_noise = _smooth_noise(rng, size, sigma=max(size / 30.0, 1.0))
    town_dist = np.hypot(fx - 0.36, fy - 0.47)
    urban = town_dist < 0.065 * (1.0 + 0.30 * town_noise)
    urban |= np.hypot(fx - 0.45, fy - 0.41) < 0.02
    urban |= np.hypot(fx - 0.29, fy - 0.56) < 0.018
    urban = ndimage.binary_opening(urban, iterations=1) | (town_dist < 0.03)
    # Scattered rural subdivisions on the basin floor (typical of Mohave County)
    for _ in range(6):
        hx, hy = rng.uniform(0.18, 0.72), rng.uniform(0.08, 0.92)
        radius = rng.uniform(0.010, 0.020)
        blob = np.hypot(fx - hx, fy - hy) < radius
        if (mountains[blob] < 200.0).all() and not (landuse[blob] == 5).any():
            urban |= blob
    landuse[urban] = 3

    # Water: a small reservoir on the wash in the north of the basin
    ry = 0.78
    rx = _wash_x(ry)
    reservoir = ((fx - rx) / 0.035) ** 2 + ((fy - ry) / 0.022) ** 2 <= 1.0
    landuse[reservoir] = 4

    # ------------------------------------------------------------- Vectors
    lines_norm = {
        "Line A 345 kV": [(0.0, 0.16), (0.18, 0.22), (0.36, 0.30), (0.52, 0.36),
                          (0.68, 0.44), (0.84, 0.50), (1.0, 0.54)],
        "Line B 230 kV": [(0.74, 0.0), (0.72, 0.20), (0.70, 0.44), (0.66, 0.62),
                          (0.68, 0.82), (0.64, 1.0)],
        "Line C 69 kV": [(0.36, 0.30), (0.34, 0.44), (0.27, 0.62), (0.22, 0.80), (0.20, 1.0)],
    }
    line_kv = {"Line A 345 kV": 345, "Line B 230 kV": 230, "Line C 69 kV": 69}
    line_geoms = {name: LineString(_to_utm(pts, west, south, extent)) for name, pts in lines_norm.items()}
    transmission_gdf = gpd.GeoDataFrame(
        {"name": list(line_geoms), "voltage_kv": [line_kv[n] for n in line_geoms],
         "length_km": [round(g.length / 1000.0, 2) for g in line_geoms.values()]},
        geometry=list(line_geoms.values()), crs=crs)

    substation_geoms = [
        line_geoms["Line A 345 kV"].interpolate(0.36, normalized=True),   # junction with Line C
        line_geoms["Line A 345 kV"].interpolate(0.68, normalized=True),   # near Line B crossing
        line_geoms["Line B 230 kV"].interpolate(0.82, normalized=True),   # north basin
    ]
    substations_gdf = gpd.GeoDataFrame(
        {"name": ["Town Substation", "Basin East Substation", "North Basin Substation"],
         "voltage_kv": [345, 345, 230]},
        geometry=substation_geoms, crs=crs)

    roads_norm = {
        "Interstate highway": ([(0.0, 0.42), (0.15, 0.44), (0.30, 0.47), (0.40, 0.46), (0.55, 0.43),
                                (0.72, 0.40), (0.88, 0.36), (1.0, 0.33)], "highway", 4),
        "State route north": ([(0.38, 0.47), (0.44, 0.62), (0.50, 0.80), (0.54, 1.0)], "secondary", 2),
        "County road south": ([(0.36, 0.47), (0.30, 0.30), (0.25, 0.14), (0.22, 0.0)], "secondary", 2),
    }
    roads_gdf = gpd.GeoDataFrame(
        {"name": list(roads_norm),
         "road_type": [v[1] for v in roads_norm.values()],
         "lanes": [v[2] for v in roads_norm.values()]},
        geometry=[LineString(_to_utm(v[0], west, south, extent)) for v in roads_norm.values()], crs=crs)

    residential_gdf = _polygons_from_mask(landuse == 3, transform, crs, "Town cluster")

    # -------------------------------------------------------------- Output
    paths = {
        "dem": write_raster(dem, profile, out_dir / "dem.tif"),
        "ghi": write_raster(ghi, profile, out_dir / "ghi.tif"),
        "landuse": write_raster(landuse, profile, out_dir / "landuse.tif", nodata=0),
    }
    vectors = {
        "transmission_lines": transmission_gdf,
        "roads": roads_gdf,
        "substations": substations_gdf,
        "residential": residential_gdf,
        "protected_areas": protected_gdf,
    }
    for key, gdf in vectors.items():
        paths[key] = write_vector(gdf, out_dir / f"{key}.gpkg")

    paths.update({
        "profile": profile,
        "bounds": (west, south, east, north),
        "resolution": res,
        "arrays": {"dem": dem, "ghi": ghi, "landuse": landuse},
        "study_area": dict(STUDY_AREA),
    })
    return paths
