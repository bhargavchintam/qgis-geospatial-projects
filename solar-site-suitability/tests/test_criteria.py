"""Tests for the standardisation curves and the constraint mask."""

import numpy as np

from src.criteria import (aspect_score, build_constraint_mask, constraint_reasons, distance_score,
                          ghi_score, landuse_score, slope_score)


def test_ghi_curve_endpoints():
    ghi = np.array([4.0, 5.0, 6.0, 7.0, 8.0])
    score = ghi_score(ghi, lo=5.0, hi=7.0)
    np.testing.assert_allclose(score, [0.0, 0.0, 0.5, 1.0, 1.0])


def test_slope_curve_endpoints():
    slope = np.array([0.0, 3.0, 6.5, 10.0, 25.0])
    score = slope_score(slope, ideal=3.0, max_ok=10.0)
    np.testing.assert_allclose(score, [1.0, 1.0, 0.5, 0.0, 0.0])


def test_aspect_curve_south_best_north_worst_flat_one():
    aspect = np.array([180.0, 0.0, 90.0, 270.0, -1.0, 360.0])
    score = aspect_score(aspect)
    np.testing.assert_allclose(score, [1.0, 0.0, 0.5, 0.5, 1.0, 0.0], atol=1e-9)


def test_distance_curve_endpoints():
    dist = np.array([0.0, 1000.0, 8000.0, 15000.0, 30000.0])
    score = distance_score(dist, full_score_within=1000.0, zero_at=15000.0)
    np.testing.assert_allclose(score, [1.0, 1.0, 0.5, 0.0, 0.0])


def test_landuse_lookup_and_default():
    lu = np.array([[1, 2], [3, 9]])
    score = landuse_score(lu, {1: 1.0, 2: 0.4, 3: 0.0})
    np.testing.assert_allclose(score, [[1.0, 0.4], [0.0, 0.0]])


def test_constraint_mask_excludes_water_urban_protected_steep_and_buffer():
    landuse = np.array([[1, 4, 3], [5, 1, 1], [1, 1, 1]])
    slope = np.array([[2.0, 2.0, 2.0], [2.0, 20.0, 2.0], [2.0, 2.0, 2.0]])
    res_dist = np.array([[9000.0, 9000.0, 0.0], [9000.0, 9000.0, 300.0], [9000.0, 9000.0, 9000.0]])
    mask = build_constraint_mask(landuse, slope, res_dist, max_slope=15.0, residential_buffer_m=500.0)
    reasons = constraint_reasons(landuse, slope, res_dist, max_slope=15.0, residential_buffer_m=500.0)
    assert mask.dtype == bool
    assert not mask[0, 1] and reasons[0, 1] == 1     # water
    assert not mask[0, 2] and reasons[0, 2] == 2     # urban
    assert not mask[1, 0] and reasons[1, 0] == 3     # protected
    assert not mask[1, 1] and reasons[1, 1] == 4     # steep
    assert not mask[1, 2] and reasons[1, 2] == 5     # residential buffer
    assert mask[0, 0] and mask[2, 2] and reasons[2, 2] == 0
    assert mask.sum() == 4


def test_zero_buffer_disables_residential_rule():
    landuse = np.ones((3, 3), dtype=int)
    slope = np.zeros((3, 3))
    res_dist = np.zeros((3, 3))
    assert build_constraint_mask(landuse, slope, res_dist, residential_buffer_m=0.0).all()
