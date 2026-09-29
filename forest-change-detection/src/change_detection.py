"""
Forest change detection: post-classification comparison, dNBR, evidence
combination, minimum mapping unit filtering and vectorisation of loss patches.

Change raster codes
-------------------
    0  no data (either date masked)
    1  stable forest
    2  stable non-forest
    3  forest loss   (forest at T1, non-forest at T2)
    4  forest gain   (non-forest at T1, forest at T2)
"""

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape

CHANGE_CODES = {0: "No data", 1: "Stable forest", 2: "Stable non-forest", 3: "Forest loss", 4: "Forest gain"}
EIGHT_CONNECTED = np.ones((3, 3), dtype=int)


def post_classification_change(class_t1: np.ndarray, class_t2: np.ndarray, forest_class: int = 1) -> np.ndarray:
    """
    Compare two class rasters pixel by pixel.

    Returns a uint8 raster with codes 0..4 (see module docstring). Pixels that
    are 0 (no data) in either date become 0.
    """
    c1 = np.asarray(class_t1)
    c2 = np.asarray(class_t2)
    if c1.shape != c2.shape:
        raise ValueError(f"Class rasters differ in shape: {c1.shape} vs {c2.shape}")
    valid = (c1 > 0) & (c2 > 0)
    f1 = c1 == forest_class
    f2 = c2 == forest_class
    out = np.zeros(c1.shape, dtype=np.uint8)
    out[valid & f1 & f2] = 1
    out[valid & ~f1 & ~f2] = 2
    out[valid & f1 & ~f2] = 3
    out[valid & ~f1 & f2] = 4
    return out


def dnbr(nbr_t1: np.ndarray, nbr_t2: np.ndarray) -> np.ndarray:
    """
    Differenced NBR = NBR(T1) - NBR(T2), following the USGS "pre minus post"
    convention: positive values mean vegetation was removed between the dates.
    """
    return np.asarray(nbr_t1, dtype=np.float64) - np.asarray(nbr_t2, dtype=np.float64)


def threshold_dnbr(dnbr_arr: np.ndarray, loss_thresh: float = 0.27) -> np.ndarray:
    """
    Boolean loss mask where dNBR >= ``loss_thresh``.

    0.27 is the USGS burn-severity break between "low" and "moderate-low"
    severity. It is used here as a change/no-change cut for canopy removal.
    NaN values are never flagged.
    """
    arr = np.asarray(dnbr_arr, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        return np.isfinite(arr) & (arr >= loss_thresh)


def combine_evidence(post_class_loss: np.ndarray, dnbr_loss: np.ndarray) -> np.ndarray:
    """
    Conservative rule: a pixel is forest loss only when BOTH the
    post-classification comparison AND the dNBR threshold flag it.

    Classification errors (a forest pixel mislabelled at one date) and
    radiometric noise (dNBR spikes from illumination or moisture changes) are
    largely independent, so requiring agreement suppresses both kinds of false
    alarms at the cost of a slightly lower detection rate.
    """
    return np.asarray(post_class_loss, dtype=bool) & np.asarray(dnbr_loss, dtype=bool)


def label_patches(mask: np.ndarray, connectivity: int = 8) -> tuple:
    """Connected-component labelling of a boolean mask. Returns (labels, n)."""
    structure = EIGHT_CONNECTED if connectivity == 8 else None
    labels, n = ndimage.label(np.asarray(mask, dtype=bool), structure=structure)
    return labels, int(n)


def filter_mmu(loss_bool: np.ndarray, min_pixels: int, connectivity: int = 8) -> np.ndarray:
    """
    Remove connected patches smaller than ``min_pixels`` (minimum mapping unit).

    Uses ``scipy.ndimage.label`` with 8-connectivity by default so that thin
    diagonal clearing strips stay as one patch.
    """
    mask = np.asarray(loss_bool, dtype=bool)
    if min_pixels <= 1 or not mask.any():
        return mask.copy()
    labels, n = label_patches(mask, connectivity)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = sizes >= int(min_pixels)
    return keep[labels]


def vectorize_loss(loss_bool: np.ndarray, profile: dict, connectivity: int = 8) -> gpd.GeoDataFrame:
    """
    Convert a boolean loss mask into one polygon per connected patch.

    Columns: ``patch_id``, ``n_pixels``, ``area_ha``, ``centroid_x``,
    ``centroid_y`` (in the raster CRS) and ``geometry``.
    """
    mask = np.asarray(loss_bool, dtype=bool)
    crs = profile.get("crs")
    transform = profile["transform"]
    columns = ["patch_id", "n_pixels", "area_ha", "centroid_x", "centroid_y"]
    if not mask.any():
        return gpd.GeoDataFrame({c: pd.Series(dtype="float64") for c in columns},
                                geometry=gpd.GeoSeries([], crs=crs), crs=crs)

    labels, n = label_patches(mask, connectivity)
    counts = np.bincount(labels.ravel())
    geoms = {}
    for geom, value in features.shapes(labels.astype(np.int32), mask=mask, transform=transform,
                                       connectivity=connectivity):
        pid = int(value)
        geoms.setdefault(pid, []).append(shape(geom))
    records = []
    for pid in sorted(geoms):
        parts = geoms[pid]
        geometry = parts[0] if len(parts) == 1 else shapely.union_all(parts)
        centroid = geometry.centroid
        records.append({
            "patch_id": pid,
            "n_pixels": int(counts[pid]),
            "area_ha": float(geometry.area / 10000.0),
            "centroid_x": float(centroid.x),
            "centroid_y": float(centroid.y),
            "geometry": geometry,
        })
    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=crs)
    return gdf.reset_index(drop=True)


def distance_to_nearest_road(loss_gdf: gpd.GeoDataFrame, roads_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Add a ``dist_road_m`` column: planar distance from each loss patch polygon
    to the nearest road line (0 when the patch touches a road). Both layers
    must share a projected CRS (metres).
    """
    out = loss_gdf.copy()
    if len(out) == 0:
        out["dist_road_m"] = pd.Series(dtype="float64")
        return out
    if roads_gdf is None or len(roads_gdf) == 0:
        out["dist_road_m"] = np.nan
        return out
    roads = roads_gdf
    if roads.crs is not None and out.crs is not None and roads.crs != out.crs:
        roads = roads.to_crs(out.crs)
    road_union = shapely.union_all(list(roads.geometry.values))
    out["dist_road_m"] = out.geometry.distance(road_union).astype(float)
    return out
