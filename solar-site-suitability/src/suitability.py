"""
Weighted overlay, classification and candidate site extraction.

Capacity and energy assumptions (all in config.yaml, defaults here):
    * 2 ha per MW of fixed-tilt utility PV, so capacity_mw = area_ha * 0.5.
      NREL (Ong et al., 2013, "Land-Use Requirements for Solar Power Plants
      in the United States") reports a direct-area footprint of about
      5.5 acres/MWac (~2.2 ha/MW) for fixed-tilt plants.
    * annual_gwh = area_m2 * GHI (kWh/m2/day) * 365 * module efficiency (0.20)
      * ground cover ratio (0.40) * performance ratio (0.85) / 1e6.
"""

import numpy as np
import pandas as pd
import geopandas as gpd
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

SITE_COLUMNS = [
    "site_id", "area_ha", "mean_suitability", "max_suitability", "mean_ghi",
    "capacity_mw", "annual_gwh", "dist_to_grid_km", "rank_score", "rank",
]

CLASS_LABELS = {1: "Very Low", 2: "Low", 3: "Moderate", 4: "High", 5: "Very High"}


def weighted_overlay(criteria: dict, weights: dict, mask: np.ndarray = None) -> np.ndarray:
    """Weighted linear combination of 0..1 criterion rasters.

    index = sum_i w_i * c_i with the weights renormalised to sum to 1.
    Criteria missing from ``weights`` are ignored. NaN pixels in a criterion
    are treated as 0 for that criterion. Pixels where ``mask`` is False are
    set to NaN (excluded by constraints).
    """
    names = [n for n in weights if n in criteria]
    if not names:
        raise ValueError("No criteria matched the weights dictionary")
    total = float(sum(weights[n] for n in names))
    if total <= 0:
        raise ValueError("Weights must sum to a positive number")
    first = np.asarray(criteria[names[0]], dtype=np.float64)
    index = np.zeros(first.shape, dtype=np.float64)
    for n in names:
        c = np.asarray(criteria[n], dtype=np.float64)
        c = np.clip(np.nan_to_num(c, nan=0.0), 0.0, 1.0)
        index += (weights[n] / total) * c
    index = np.clip(index, 0.0, 1.0)
    if mask is not None:
        index = np.where(np.asarray(mask, dtype=bool), index, np.nan)
    return index


def classify_suitability(index: np.ndarray, thresholds=(0.2, 0.4, 0.6, 0.8)) -> np.ndarray:
    """Classify a 0..1 index into 1..5 (Very Low .. Very High).

    ``thresholds`` are the four class boundaries; a value >= thresholds[k]
    belongs to class k+2. NaN (excluded) pixels get 0.
    """
    thr = np.asarray(sorted(thresholds), dtype=np.float64)
    if thr.size != 4:
        raise ValueError("Exactly four thresholds are needed for five classes")
    idx = np.asarray(index, dtype=np.float64)
    classes = (np.digitize(np.nan_to_num(idx, nan=-1.0), thr) + 1).astype(np.int32)
    classes[np.isnan(idx)] = 0
    return classes


def rank_sites(sites: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rank candidate sites (1 = best) by suitability with an area bonus.

    rank_score = mean_suitability * sqrt(area_ha / max_area_ha)

    The square root damps the area term so a very large but mediocre patch
    does not outrank a smaller excellent one, while still rewarding size
    (bigger plants have lower cost per MW). rank_score is 0..1 relative to
    the largest site.
    """
    sites = sites.copy()
    if len(sites) == 0:
        sites["rank_score"] = pd.Series(dtype=float)
        sites["rank"] = pd.Series(dtype=int)
        return sites
    max_area = float(sites["area_ha"].max())
    sites["rank_score"] = (sites["mean_suitability"] * np.sqrt(sites["area_ha"] / max_area)).round(4)
    sites = sites.sort_values(["rank_score", "area_ha"], ascending=[False, False])
    sites["rank"] = np.arange(1, len(sites) + 1, dtype=int)
    return sites.reset_index(drop=True)


def _empty_sites(crs) -> gpd.GeoDataFrame:
    data = {c: pd.Series(dtype=float) for c in SITE_COLUMNS}
    data["site_id"] = pd.Series(dtype=int)
    data["rank"] = pd.Series(dtype=int)
    return gpd.GeoDataFrame(data, geometry=gpd.GeoSeries([], crs=crs), crs=crs)


def extract_candidate_sites(index: np.ndarray, profile: dict, threshold: float = 0.7,
                            min_area_ha: float = 50.0, ghi: np.ndarray = None,
                            dist_to_grid: np.ndarray = None, ha_per_mw: float = 2.0,
                            module_efficiency: float = 0.20, ground_cover_ratio: float = 0.40,
                            performance_ratio: float = 0.85) -> gpd.GeoDataFrame:
    """Vectorise contiguous patches with index >= threshold into sites.

    Patches are found with 8-connectivity, patches smaller than
    ``min_area_ha`` are dropped, and each remaining patch becomes one
    (multi)polygon with these attributes:

        site_id, area_ha, mean_suitability, max_suitability, mean_ghi
        (kWh/m2/day), capacity_mw (= area_ha / ha_per_mw), annual_gwh,
        dist_to_grid_km (nearest grid distance inside the patch, km),
        rank_score, rank (see ``rank_sites``).

    ``ghi`` and ``dist_to_grid`` are optional rasters on the same grid; if
    missing, mean_ghi and dist_to_grid_km are NaN and annual_gwh is NaN.
    """
    idx = np.asarray(index, dtype=np.float64)
    binary = np.nan_to_num(idx, nan=-1.0) >= threshold
    crs = profile.get("crs")
    if not binary.any():
        return _empty_sites(crs)

    transform = profile["transform"]
    pix_ha = abs(transform.a * transform.e) / 10_000.0
    labels, n_patches = ndimage.label(binary, structure=np.ones((3, 3), dtype=int))
    ids = np.arange(1, n_patches + 1)
    counts = ndimage.sum(binary, labels, index=ids)
    areas_ha = np.asarray(counts, dtype=np.float64) * pix_ha
    keep = areas_ha >= min_area_ha
    if not keep.any():
        return _empty_sites(crs)

    kept_ids = ids[keep]
    mean_suit = ndimage.mean(np.nan_to_num(idx, nan=0.0), labels, index=kept_ids)
    max_suit = ndimage.maximum(np.nan_to_num(idx, nan=0.0), labels, index=kept_ids)
    if ghi is not None:
        mean_ghi = ndimage.mean(np.nan_to_num(np.asarray(ghi, dtype=np.float64), nan=0.0),
                                labels, index=kept_ids)
    else:
        mean_ghi = np.full(len(kept_ids), np.nan)
    if dist_to_grid is not None:
        d = np.asarray(dist_to_grid, dtype=np.float64)
        min_grid = ndimage.minimum(np.nan_to_num(d, nan=np.inf), labels, index=kept_ids)
        dist_grid_km = np.asarray(min_grid, dtype=np.float64) / 1000.0
    else:
        dist_grid_km = np.full(len(kept_ids), np.nan)

    # Polygonise only the kept labels
    keep_mask = np.isin(labels, kept_ids)
    geoms = {}
    for geom, value in features.shapes(labels.astype(np.int32), mask=keep_mask,
                                       transform=transform, connectivity=8):
        geoms.setdefault(int(value), []).append(shape(geom))

    records = []
    for k, lab in enumerate(kept_ids):
        parts = geoms.get(int(lab), [])
        if not parts:
            continue
        geom = unary_union(parts) if len(parts) > 1 else parts[0]
        area_ha = float(areas_ha[keep][k])
        g = float(mean_ghi[k])
        capacity_mw = area_ha / ha_per_mw
        annual_gwh = (area_ha * 10_000.0 * g * 365.0 * module_efficiency
                      * ground_cover_ratio * performance_ratio / 1e6)
        records.append({
            "site_id": int(lab),
            "area_ha": round(area_ha, 2),
            "mean_suitability": round(float(mean_suit[k]), 4),
            "max_suitability": round(float(max_suit[k]), 4),
            "mean_ghi": round(g, 3) if np.isfinite(g) else np.nan,
            "capacity_mw": round(capacity_mw, 2),
            "annual_gwh": round(float(annual_gwh), 2) if np.isfinite(annual_gwh) else np.nan,
            "dist_to_grid_km": round(float(dist_grid_km[k]), 2) if np.isfinite(dist_grid_km[k]) else np.nan,
            "geometry": geom,
        })
    sites = gpd.GeoDataFrame(records, geometry="geometry", crs=crs)
    return rank_sites(sites)


def class_area_table(classes: np.ndarray, profile: dict) -> pd.DataFrame:
    """Area (ha) and share (% of allowed area) of each suitability class."""
    t = profile["transform"]
    pix_ha = abs(t.a * t.e) / 10_000.0
    allowed = int((classes > 0).sum())
    rows = []
    for k, label in CLASS_LABELS.items():
        n = int((classes == k).sum())
        rows.append({
            "class": k,
            "label": label,
            "area_ha": round(n * pix_ha, 1),
            "pct_of_allowed": round(100.0 * n / allowed, 2) if allowed else 0.0,
        })
    return pd.DataFrame(rows)
