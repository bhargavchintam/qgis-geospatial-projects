"""
Tests for the DEM hydrology core: priority-flood sink filling, D8 flow
direction and flow accumulation.
"""

import numpy as np

from src.dem_processor import D8_DIRECTIONS, DEMProcessor

CFG = {"dem": {"resolution": 30}}


OUTLET = 15.0


def _bowl(n=41, rim=20.0, depth=10.0):
    """
    Square bowl: lowest at the centre (10 m), rim 20 m at the edges, and a
    flat outlet channel at 15 m from the centre to the east edge. The spill
    level of the bowl is therefore exactly OUTLET.
    """
    y, x = np.mgrid[0:n, 0:n]
    r = np.hypot(x - n // 2, y - n // 2) / (n // 2)
    dem = rim - depth * (1 - np.clip(r, 0, 1) ** 2)
    dem[n // 2, n // 2:] = np.minimum(dem[n // 2, n // 2:], OUTLET)
    return dem


class TestPriorityFlood:
    def test_bowl_is_filled_to_outlet_level(self):
        dem = _bowl()
        filled = DEMProcessor.priority_flood(dem, epsilon=1e-5)
        assert dem[dem.shape[0] // 2, -1] == OUTLET
        # Nothing is ever lowered and edge cells are untouched
        assert np.all(filled >= dem - 1e-12)
        assert np.allclose(filled[0, :], dem[0, :]) and np.allclose(filled[:, 0], dem[:, 0])
        # No cell is lower than the outlet: the bowl (originally down to 10 m) is now
        # flat at the outlet level, apart from the tiny epsilon drainage gradient
        assert np.all(filled >= OUTLET)
        bowl_cells = dem < OUTLET
        assert bowl_cells.sum() > 100
        assert filled[bowl_cells].min() >= OUTLET
        assert filled[bowl_cells].max() - OUTLET < 1e-2
        # cells clearly above the spill level are unchanged (flat rim cells may get
        # the epsilon gradient, which is far below 1 mm)
        above = dem > OUTLET + 0.01
        np.testing.assert_allclose(filled[above], dem[above], atol=1e-3)

    def test_no_cell_lower_than_its_downstream_path(self):
        dem = _bowl()
        proc = DEMProcessor(CFG, dem_array=dem)
        proc.fill_sinks()
        flow_dir = proc.compute_flow_direction()
        # every interior cell drains somewhere (no pits, no flats left)
        assert np.all(flow_dir[1:-1, 1:-1] != 0)
        # walking downstream never goes uphill and ends on the edge
        filled = proc.dem
        rows, cols = filled.shape
        r, c = rows // 2, cols // 2
        steps = 0
        while flow_dir[r, c] != 0 and steps < rows * cols:
            dr, dc = D8_DIRECTIONS[int(flow_dir[r, c])]
            nr, nc = r + dr, c + dc
            assert filled[nr, nc] < filled[r, c]
            r, c = nr, nc
            steps += 1
        assert r in (0, rows - 1) or c in (0, cols - 1)

    def test_nodata_preserved_and_ignored(self):
        dem = _bowl()
        dem[5:8, 5:8] = np.nan
        filled = DEMProcessor.priority_flood(dem)
        assert np.isnan(filled[5:8, 5:8]).all()
        assert np.isfinite(filled[~np.isnan(dem)]).all()

    def test_plane_is_unchanged(self):
        dem = np.linspace(50, 10, 30)[None, :] * np.ones((25, 1))
        filled = DEMProcessor.priority_flood(dem)
        np.testing.assert_allclose(filled, dem)


class TestFlowRouting:
    def test_accumulation_mass_balance(self):
        rng = np.random.default_rng(3)
        from scipy.ndimage import gaussian_filter

        dem = np.linspace(60, 5, 60)[None, :] + gaussian_filter(rng.normal(size=(60, 60)), 3) * 4
        proc = DEMProcessor(CFG, dem_array=dem)
        proc.fill_sinks()
        fd = proc.compute_flow_direction()
        acc = proc.compute_flow_accumulation(fd)
        assert acc.min() == 1.0
        # all water leaves through outlet cells (flow_dir == 0)
        assert np.isclose(acc[fd == 0].sum(), dem.size)

    def test_plane_drains_east(self):
        dem = np.linspace(50, 10, 20)[None, :] * np.ones((10, 1))
        proc = DEMProcessor(CFG, dem_array=dem)
        fd = proc.compute_flow_direction()
        assert np.all(fd[:, :-1] == 1)  # code 1 = East
        assert np.all(fd[:, -1] == 0)   # east edge cells are outlets
        acc = proc.compute_flow_accumulation(fd)
        assert np.all(acc[:, -1] == 20)

    def test_twi_increases_with_accumulation(self):
        dem = np.linspace(50, 10, 20)[None, :] * np.ones((10, 1))
        proc = DEMProcessor(CFG, dem_array=dem)
        fd = proc.compute_flow_direction()
        acc = proc.compute_flow_accumulation(fd)
        twi = proc.compute_twi(acc, proc.compute_slope())
        assert twi[5, -2] > twi[5, 1]
