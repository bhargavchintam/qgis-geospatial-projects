"""Tests for change detection, MMU filtering and vectorisation."""

import numpy as np
from rasterio.crs import CRS
from rasterio.transform import from_origin

from src.change_detection import (combine_evidence, dnbr, filter_mmu, post_classification_change,
                                  threshold_dnbr, vectorize_loss)


def _profile(size=20, px=20.0):
    return {"crs": CRS.from_epsg(32720), "transform": from_origin(500000, 8800000, px, px),
            "width": size, "height": size}


def test_post_classification_codes():
    c1 = np.array([[1, 1, 2, 0], [1, 2, 3, 1]], dtype=np.uint8)
    c2 = np.array([[1, 2, 2, 1], [0, 1, 3, 4]], dtype=np.uint8)
    ch = post_classification_change(c1, c2, forest_class=1)
    expected = np.array([[1, 3, 2, 0], [0, 4, 2, 3]], dtype=np.uint8)
    assert np.array_equal(ch, expected)


def test_dnbr_threshold_and_combination():
    nbr1 = np.array([[0.6, 0.6, 0.6, np.nan]])
    nbr2 = np.array([[0.2, 0.5, 0.1, 0.1]])
    d = dnbr(nbr1, nbr2)
    loss = threshold_dnbr(d, 0.27)
    assert loss.tolist() == [[True, False, True, False]]   # NaN never flagged
    post = np.array([[True, True, False, True]])
    both = combine_evidence(post, loss)
    assert both.tolist() == [[True, False, False, False]]


def test_mmu_removes_single_pixels_and_keeps_blocks():
    m = np.zeros((20, 20), dtype=bool)
    m[2, 2] = True                 # single pixel
    m[5:9, 5:9] = True             # 16-pixel block
    m[12, 12] = m[13, 13] = True   # 2-pixel diagonal pair (8-connected)
    out = filter_mmu(m, min_pixels=13)
    assert out.sum() == 16 and not out[2, 2] and not out[12, 12]
    assert filter_mmu(m, min_pixels=2).sum() == 18   # diagonal pair survives with 8-connectivity
    assert np.array_equal(filter_mmu(m, min_pixels=1), m)


def test_vectorize_areas_match_raster_area():
    rng = np.random.default_rng(3)
    m = rng.random((20, 20)) < 0.3
    m = filter_mmu(m, 3)
    prof = _profile()
    gdf = vectorize_loss(m, prof)
    assert set(["patch_id", "area_ha", "centroid_x", "centroid_y", "geometry"]) <= set(gdf.columns)
    raster_ha = m.sum() * 20 * 20 / 10000.0
    assert abs(gdf["area_ha"].sum() - raster_ha) / raster_ha < 0.01
    assert gdf["n_pixels"].sum() == m.sum()
    assert gdf.crs.to_epsg() == 32720


def test_vectorize_empty_mask():
    gdf = vectorize_loss(np.zeros((5, 5), dtype=bool), _profile(5))
    assert len(gdf) == 0 and "area_ha" in gdf.columns
