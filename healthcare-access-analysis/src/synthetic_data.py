"""
Synthetic demo data for the Healthcare Accessibility project.

Study area: a square synthetic city centred on Fresno, California
(lon -119.79, lat 36.74), projected in UTM zone 11N (EPSG:32611). With the
default ``size=40`` and 250 m spacing the box is 10 km x 10 km.

Everything is deterministic for a given seed and works offline.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from scipy.ndimage import gaussian_filter
from shapely.geometry import Point, box

from .network_builder import (DEFAULT_CRS, build_synthetic_network, network_to_gdf,
                              river_to_gdf)
from .utils import ensure_directory, save_gdf

STUDY_CENTRE_LONLAT = (-119.79, 36.74)
STUDY_CRS = DEFAULT_CRS

HOSPITAL_SPECS = [
    # (name, x fraction, y fraction, type) - clustered north-west and centre,
    # all on the west bank of the river (which runs at about x = 0.62).
    ("Northwest Medical Center", 0.20, 0.82, "General acute care"),
    ("Riverbend Community Hospital", 0.33, 0.72, "Community"),
    ("Sierra View Hospital", 0.14, 0.62, "Community"),
    ("Central Valley Regional Medical Center", 0.40, 0.55, "Regional referral"),
    ("University Health Campus", 0.47, 0.66, "Teaching"),
]

# Secondary population centre: a growing suburb on the east bank, south of
# the last bridge. (x fraction, y fraction, relative peak, sigma fraction)
EAST_BANK_SUBURB = (0.80, 0.22, 0.35, 0.15)


def study_origin(extent_m: float, centre_lonlat=STUDY_CENTRE_LONLAT, crs: str = STUDY_CRS) -> tuple:
    """South-west corner (x, y) of a square box of ``extent_m`` centred on the study centre."""
    t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    cx, cy = t.transform(centre_lonlat[0], centre_lonlat[1])
    return (float(round(cx - extent_m / 2.0)), float(round(cy - extent_m / 2.0)))


def _smooth_noise(rng, shape, sigma):
    field = gaussian_filter(rng.random(shape), sigma=sigma, mode="reflect")
    lo, hi = field.min(), field.max()
    return (field - lo) / (hi - lo) if hi > lo else np.zeros(shape)


def make_blocks(
    origin_xy: tuple,
    extent_m: float,
    seed: int,
    block_size_m: float = 500.0,
    density_per_km2: float = 5000.0,
    river_geom=None,
    crs: str = STUDY_CRS,
) -> gpd.GeoDataFrame:
    """
    Census-block-like square polygons with population, income and SVI.

    Population = smoothed noise x centre-weighted density (a Gaussian bump on
    the city centre plus a smaller bump for the east-bank suburb), scaled so
    the average density equals ``density_per_km2`` (about 500 k people for
    the default 10 km box). Blocks on the river keep 60 % of their density.
    Median income is higher in the north-west, lower in the south-east; the
    social vulnerability index (0..1) runs the other way.
    """
    rng = np.random.default_rng(seed + 101)
    nb = max(4, int(round(extent_m / block_size_m)))
    bs = extent_m / nb
    x0, y0 = origin_xy
    cx, cy = x0 + extent_m / 2.0, y0 + extent_m / 2.0
    sx, sy, s_amp, s_sig = EAST_BANK_SUBURB
    sub_x, sub_y = x0 + sx * extent_m, y0 + sy * extent_m

    noise_pop = _smooth_noise(rng, (nb, nb), sigma=1.5)
    noise_inc = _smooth_noise(rng, (nb, nb), sigma=2.0)
    noise_svi = _smooth_noise(rng, (nb, nb), sigma=1.0)

    rows = []
    for r in range(nb):          # r = 0 is the southern row
        for c in range(nb):
            minx, miny = x0 + c * bs, y0 + r * bs
            geom = box(minx, miny, minx + bs, miny + bs)
            xc, yc = minx + bs / 2.0, miny + bs / 2.0
            d2 = (xc - cx) ** 2 + (yc - cy) ** 2
            bump = np.exp(-d2 / (2.0 * (0.35 * extent_m) ** 2))
            d2s = (xc - sub_x) ** 2 + (yc - sub_y) ** 2
            suburb = s_amp * np.exp(-d2s / (2.0 * (s_sig * extent_m) ** 2))
            density = (0.35 + 0.65 * bump + suburb) * (0.5 + noise_pop[r, c])
            if river_geom is not None and geom.intersects(river_geom):
                density *= 0.6
            fx, fy = (xc - x0) / extent_m, (yc - y0) / extent_m
            grad = (1.0 - fx + fy) / 2.0                     # 1 = NW corner, 0 = SE
            income = 28000.0 + 90000.0 * (0.55 * grad + 0.45 * noise_inc[r, c])
            rows.append({
                "block_id": r * nb + c, "row": r, "col": c,
                "area_km2": (bs * bs) / 1e6,
                "_density": density,
                "median_income": float(np.clip(round(income / 100.0) * 100.0, 22000, 160000)),
                "_svi_noise": noise_svi[r, c],
                "geometry": geom,
            })
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    area_km2 = (extent_m / 1000.0) ** 2
    target_total = density_per_km2 * area_km2
    weights = gdf["_density"].values
    gdf["population"] = np.round(weights / weights.sum() * target_total).astype(int)
    gdf["pop_density"] = (gdf["population"] / gdf["area_km2"]).round(1)
    inc = gdf["median_income"].values
    inc_norm = (inc - inc.min()) / (inc.max() - inc.min() + 1e-9)
    svi = 0.9 - 0.75 * inc_norm + 0.25 * (gdf["_svi_noise"].values - 0.5)
    gdf["svi"] = np.clip(svi, 0.02, 0.98).round(3)
    gdf = gdf.drop(columns=["_density", "_svi_noise"])
    return gdf[["block_id", "row", "col", "area_km2", "population", "pop_density",
                "median_income", "svi", "geometry"]]


def make_hospitals(origin_xy: tuple, extent_m: float, seed: int, crs: str = STUDY_CRS) -> gpd.GeoDataFrame:
    """Five hospitals (points with name, beds, type) clustered north-west and centre."""
    rng = np.random.default_rng(seed + 202)
    x0, y0 = origin_xy
    rows = []
    for i, (name, fx, fy, htype) in enumerate(HOSPITAL_SPECS):
        jx, jy = rng.uniform(-0.015, 0.015, size=2)
        x = x0 + (fx + jx) * extent_m
        y = y0 + (fy + jy) * extent_m
        beds = int(rng.integers(120, 601))
        rows.append({"hospital_id": i + 1, "name": name, "beds": beds, "type": htype,
                     "geometry": Point(x, y)})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def generate_demo_data(
    size: int = 40,
    seed: int = 42,
    out_dir="results/demo/data",
    spacing_m: float = 250.0,
    block_size_m: float = 500.0,
    density_per_km2: float = 5000.0,
    removal_fraction: float = 0.08,
) -> dict:
    """
    Generate the synthetic city and write it to ``out_dir``.

    Parameters
    ----------
    size : network grid nodes per side (40 -> 10 km with 250 m spacing).
    seed : random seed (deterministic output).
    out_dir : folder for the GeoPackages (created if missing).

    Returns
    -------
    dict with keys
      graph          networkx.Graph road network (see network_builder)
      crs            "EPSG:32611"
      origin_xy      (x, y) south-west corner of the box in metres
      extent_m       box side length in metres
      spacing_m      grid spacing
      bounds         (minx, miny, maxx, maxy) of the box
      centre_lonlat  (lon, lat) of the study centre
      roads_path, nodes_path, blocks_path, hospitals_path, river_path
                     written GeoPackage paths (str)
      roads_gdf, nodes_gdf, blocks_gdf, hospitals_gdf, river_gdf
                     the same layers in memory
    """
    out_dir = ensure_directory(out_dir)
    extent = float(size) * float(spacing_m)
    origin = study_origin(extent)

    G = build_synthetic_network(n=size, spacing_m=spacing_m, seed=seed, origin_xy=origin,
                                removal_fraction=removal_fraction, crs=STUDY_CRS)
    roads, nodes = network_to_gdf(G)
    river = river_to_gdf(G)
    river_geom = G.graph.get("river")
    if river_geom is not None:
        river_geom = river_geom.intersection(box(origin[0], origin[1], origin[0] + extent, origin[1] + extent))
        river = gpd.GeoDataFrame({"name": ["river"]}, geometry=[river_geom], crs=STUDY_CRS)

    blocks = make_blocks(origin, extent, seed, block_size_m=block_size_m,
                         density_per_km2=density_per_km2, river_geom=river_geom)
    hospitals = make_hospitals(origin, extent, seed)

    paths = {
        "roads_path": save_gdf(roads, out_dir / "roads.gpkg"),
        "nodes_path": save_gdf(nodes, out_dir / "nodes.gpkg"),
        "blocks_path": save_gdf(blocks, out_dir / "blocks.gpkg"),
        "hospitals_path": save_gdf(hospitals, out_dir / "hospitals.gpkg"),
        "river_path": save_gdf(river, out_dir / "river.gpkg"),
    }
    return {
        "graph": G,
        "crs": STUDY_CRS,
        "origin_xy": origin,
        "extent_m": extent,
        "spacing_m": float(spacing_m),
        "bounds": (origin[0], origin[1], origin[0] + extent, origin[1] + extent),
        "centre_lonlat": STUDY_CENTRE_LONLAT,
        **paths,
        "roads_gdf": roads,
        "nodes_gdf": nodes,
        "blocks_gdf": blocks,
        "hospitals_gdf": hospitals,
        "river_gdf": river,
    }
