"""Tests for slope, aspect and hillshade."""

import numpy as np

from src.terrain import aspect_degrees, hillshade, slope_degrees


def test_flat_dem_has_zero_slope_and_flat_aspect():
    dem = np.full((20, 20), 1000.0)
    slope = slope_degrees(dem, 30.0)
    aspect = aspect_degrees(dem, 30.0)
    assert np.allclose(slope, 0.0)
    assert np.all(aspect == -1.0)


def test_tilted_plane_known_slope_and_aspect_south():
    # Elevation drops 0.1 m per metre going south (rows increase southward)
    res = 30.0
    rows = np.arange(30)[:, None] * np.ones((1, 30))
    dem = 1000.0 - 0.1 * rows * res
    slope = slope_degrees(dem, res)
    aspect = aspect_degrees(dem, res)
    expected = np.degrees(np.arctan(0.1))
    assert np.allclose(slope[2:-2, 2:-2], expected, atol=1e-6)
    assert np.allclose(aspect[2:-2, 2:-2], 180.0, atol=1e-6)


def test_tilted_plane_aspect_east_and_west():
    res = 10.0
    cols = np.ones((30, 1)) * np.arange(30)[None, :]
    dem_east = 500.0 - 0.05 * cols * res   # drops toward the east
    dem_west = 500.0 + 0.05 * cols * res   # drops toward the west
    assert np.allclose(aspect_degrees(dem_east, res)[2:-2, 2:-2], 90.0, atol=1e-6)
    assert np.allclose(aspect_degrees(dem_west, res)[2:-2, 2:-2], 270.0, atol=1e-6)
    assert np.allclose(slope_degrees(dem_east, res)[2:-2, 2:-2], np.degrees(np.arctan(0.05)))


def test_hillshade_range_and_lighting_direction():
    rng = np.random.default_rng(0)
    dem = rng.normal(1000, 50, (40, 40))
    shade = hillshade(dem, 30.0)
    assert shade.shape == dem.shape
    assert shade.min() >= 0.0 and shade.max() <= 1.0
    # A slope facing the light (north-west, azimuth 315) is brighter than one facing away
    rows = np.arange(30)[:, None] * np.ones((1, 30))
    cols = np.ones((30, 1)) * np.arange(30)[None, :]
    facing_nw = 1000.0 + 0.3 * 30.0 * (rows + cols)   # rises to the south-east, so it faces north-west
    facing_se = 1000.0 - 0.3 * 30.0 * (rows + cols)
    assert hillshade(facing_nw, 30.0)[5, 5] > hillshade(facing_se, 30.0)[5, 5]
