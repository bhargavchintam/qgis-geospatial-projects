"""Tests for the weighted overlay, classification and site extraction."""

import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

from src.suitability import (SITE_COLUMNS, classify_suitability, extract_candidate_sites, rank_sites,
                             weighted_overlay)


def _profile(n=20, res=100.0):
    return {"height": n, "width": n, "crs": CRS.from_epsg(32612),
            "transform": from_origin(200000.0, 3900000.0, res, res)}


def test_overlay_in_range_and_nan_outside_mask():
    rng = np.random.default_rng(1)
    criteria = {"a": rng.uniform(0, 1, (10, 10)), "b": rng.uniform(0, 1, (10, 10)), "c": np.ones((10, 10))}
    weights = {"a": 2.0, "b": 1.0, "c": 1.0}   # not normalised on purpose
    mask = np.ones((10, 10), dtype=bool)
    mask[0, :] = False
    index = weighted_overlay(criteria, weights, mask)
    assert np.all(np.isnan(index[0, :]))
    inside = index[1:, :]
    assert np.all((inside >= 0) & (inside <= 1))
    expected = 0.5 * criteria["a"] + 0.25 * criteria["b"] + 0.25
    np.testing.assert_allclose(inside, expected[1:, :], atol=1e-12)


def test_overlay_all_ones_gives_one_and_bad_weights_raise():
    criteria = {"a": np.ones((4, 4)), "b": np.ones((4, 4))}
    assert np.allclose(weighted_overlay(criteria, {"a": 0.3, "b": 0.7}), 1.0)
    with pytest.raises(ValueError):
        weighted_overlay(criteria, {"zzz": 1.0})


def test_classify_boundaries():
    index = np.array([[0.1, 0.5, 0.6], [0.68, 0.75, np.nan]])
    classes = classify_suitability(index, thresholds=(0.5, 0.6, 0.68, 0.75))
    np.testing.assert_array_equal(classes, [[1, 2, 3], [4, 5, 0]])
    with pytest.raises(ValueError):
        classify_suitability(index, thresholds=(0.5, 0.6))


def test_extract_sites_respects_min_area_and_capacity():
    n = 20
    profile = _profile(n, res=100.0)   # 1 ha per pixel
    index = np.full((n, n), 0.3)
    index[2:8, 2:8] = 0.9          # 36 px = 36 ha
    index[12:14, 12:14] = 0.95     # 4 px = 4 ha (too small)
    index[0, 19] = np.nan
    ghi = np.full((n, n), 6.0)
    dist = np.full((n, n), 2500.0)
    dist[5, 5] = 500.0
    sites = extract_candidate_sites(index, profile, threshold=0.7, min_area_ha=10, ghi=ghi, dist_to_grid=dist)
    assert list(sites.columns[:-1]) == SITE_COLUMNS or set(SITE_COLUMNS) <= set(sites.columns)
    assert len(sites) == 1
    site = sites.iloc[0]
    assert site["area_ha"] == pytest.approx(36.0)
    assert site["capacity_mw"] == pytest.approx(18.0)
    assert site["capacity_mw"] > 0
    assert site["mean_suitability"] == pytest.approx(0.9)
    assert site["max_suitability"] == pytest.approx(0.9)
    assert site["mean_ghi"] == pytest.approx(6.0)
    assert site["dist_to_grid_km"] == pytest.approx(0.5)
    expected_gwh = 36 * 10_000 * 6.0 * 365 * 0.20 * 0.40 * 0.85 / 1e6
    assert site["annual_gwh"] == pytest.approx(expected_gwh, rel=1e-3)
    assert site["rank"] == 1
    assert sites.crs.to_epsg() == 32612
    assert sites.geometry.iloc[0].area == pytest.approx(36 * 10_000)

    # min_area larger than both patches -> empty frame with the right columns
    empty = extract_candidate_sites(index, profile, threshold=0.7, min_area_ha=100)
    assert len(empty) == 0
    assert set(SITE_COLUMNS) <= set(empty.columns)


def test_rank_sites_prefers_suitability_with_area_bonus():
    import geopandas as gpd
    from shapely.geometry import box
    sites = gpd.GeoDataFrame({
        "site_id": [1, 2, 3],
        "area_ha": [100.0, 400.0, 400.0],
        "mean_suitability": [0.95, 0.80, 0.70],
    }, geometry=[box(0, 0, 1, 1)] * 3, crs="EPSG:32612")
    ranked = rank_sites(sites)
    # 0.80*1 = 0.80 beats 0.95*sqrt(0.25) = 0.475 beats 0.70
    assert ranked.loc[ranked["rank"] == 1, "site_id"].iloc[0] == 2
    assert ranked.loc[ranked["rank"] == 2, "site_id"].iloc[0] == 3
    assert ranked.loc[ranked["rank"] == 3, "site_id"].iloc[0] == 1
