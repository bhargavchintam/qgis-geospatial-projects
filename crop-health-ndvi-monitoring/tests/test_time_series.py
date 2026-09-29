"""Tests for the vectorised smoothing and the block-wise phenology fit."""

import numpy as np
import pytest

from src.time_series import TimeSeriesAnalyzer, double_logistic, interpolate_nan_along_axis0

DOY = np.array([96, 111, 126, 142, 157, 172, 187, 203, 218, 233, 248, 264, 279, 294], dtype=float)


def _synthetic_stack(rows=20, cols=20, seed=0, noise=0.02):
    """Double-logistic NDVI stack with a small spatial gradient in the peak and a few cloud gaps."""
    rng = np.random.default_rng(seed)
    rr, cc = np.mgrid[0:rows, 0:cols]
    a2 = 0.6 + 0.1 * cc / max(cols - 1, 1)
    stack = np.empty((len(DOY), rows, cols))
    for i, d in enumerate(DOY):
        stack[i] = double_logistic(d, 0.15, a2, 0.10, 155.0, 0.08, 270.0)
    stack += rng.normal(0, noise, stack.shape)
    stack[7, :8, :8] = np.nan  # a cloud on one date
    stack[12, 10:, :] = np.nan
    return stack


def test_interpolation_matches_np_interp_per_pixel():
    stack = _synthetic_stack(rows=6, cols=5)
    out = interpolate_nan_along_axis0(stack)
    n = stack.shape[0]
    for r in range(6):
        for c in range(5):
            ts = stack[:, r, c]
            valid = ~np.isnan(ts)
            ref = np.interp(np.arange(n), np.where(valid)[0], ts[valid])
            np.testing.assert_allclose(out[:, r, c], ref, atol=1e-12)
    assert not np.isnan(out).any()


def test_interpolation_keeps_all_nan_pixels():
    stack = _synthetic_stack(rows=4, cols=4)
    stack[:, 0, 0] = np.nan
    out = interpolate_nan_along_axis0(stack)
    assert np.isnan(out[:, 0, 0]).all()
    assert not np.isnan(out[:, 1, 1]).any()


def test_smooth_is_vectorised_and_fills_gaps():
    ts = TimeSeriesAnalyzer()
    stack = _synthetic_stack()
    sm = ts.smooth_time_series(stack, window_length=5, polyorder=2)
    assert sm.shape == stack.shape
    assert not np.isnan(sm).any()  # every pixel has >= 12 valid dates
    assert np.nanmax(np.abs(sm - np.nan_to_num(stack, nan=0.5))[~np.isnan(stack)]) < 0.15


@pytest.mark.parametrize("block_size", [1, 4, 6])
def test_fit_phenology_curve_block_shapes_and_peak(block_size):
    ts = TimeSeriesAnalyzer()
    rows, cols = 12, 16
    stack = _synthetic_stack(rows, cols)
    ph = ts.fit_phenology_curve(DOY, stack, block_size=block_size)
    assert ph["parameters"].shape == (6, rows, cols)
    assert ph["expected"].shape == (len(DOY), rows, cols)
    assert ph["r_squared"].shape == (rows, cols)
    assert ph["block_size"] == block_size
    assert ph["fitted_fraction"] > 0.95
    assert np.nanmean(ph["r_squared"]) > 0.95

    metrics = ts.get_peak_metrics(ph)
    peak_doy = metrics["peak_doy"]
    assert peak_doy.shape == (rows, cols)
    assert np.all((peak_doy[~np.isnan(peak_doy)] >= DOY.min()) & (peak_doy[~np.isnan(peak_doy)] <= DOY.max()))
    # true curve peaks around DOY 212 (midway between a4=155 and a6=270)
    assert abs(np.nanmean(peak_doy) - 212) < 12
    assert 0.6 < np.nanmean(metrics["peak_value"]) < 0.9
    assert np.nanmean(metrics["growing_season_length"]) > 60


def test_block_fit_is_piecewise_constant_within_blocks():
    ts = TimeSeriesAnalyzer()
    stack = _synthetic_stack(10, 10)
    ph = ts.fit_phenology_curve(DOY, stack, block_size=5)
    params = ph["parameters"]
    # every pixel in the top-left 5x5 block carries the same parameters
    block = params[:, :5, :5].reshape(6, -1)
    assert np.allclose(block, block[:, :1])
    # and the two horizontal blocks differ (the peak amplitude grows with column)
    assert params[1, 0, 0] < params[1, 0, 9]
