"""
Multi-Temporal Phenology Analysis

Analyzes vegetation index time series to track crop growth stages,
fit phenology curves, and extract key metrics (green-up, peak, senescence).
"""

import logging
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

from .utils import rasterize_fields

logger = logging.getLogger(__name__)


def interpolate_nan_along_axis0(values: np.ndarray) -> np.ndarray:
    """
    Vectorised linear interpolation of NaN gaps along axis 0 (time).

    Behaves like ``np.interp`` per pixel: interior gaps are linearly
    interpolated, leading/trailing gaps take the nearest valid value.
    Pixels with no valid observation stay NaN.
    """
    n = values.shape[0]
    flat = values.reshape(n, -1).astype(np.float64)
    valid = ~np.isnan(flat)
    t = np.arange(n)[:, None]

    # index of the last valid step at or before t, and the next at or after t
    prev_idx = np.where(valid, t, -1)
    prev_idx = np.maximum.accumulate(prev_idx, axis=0)
    next_idx = np.where(valid, t, n)
    next_idx = np.minimum.accumulate(next_idx[::-1], axis=0)[::-1]

    has_prev = prev_idx >= 0
    has_next = next_idx < n
    cols = np.arange(flat.shape[1])[None, :]
    prev_val = np.where(has_prev, flat[np.clip(prev_idx, 0, n - 1), cols], np.nan)
    next_val = np.where(has_next, flat[np.clip(next_idx, 0, n - 1), cols], np.nan)

    span = np.where(has_prev & has_next, next_idx - prev_idx, 1)
    weight = np.where(has_prev & has_next, (t - prev_idx) / np.maximum(span, 1), 0.0)
    out = np.where(
        has_prev & has_next,
        prev_val + weight * (next_val - prev_val),
        np.where(has_prev, prev_val, next_val),
    )
    return out.reshape(values.shape)


def double_logistic(doy, a1, a2, a3, a4, a5, a6):
    """
    Double logistic phenology model.

    f(t) = a1 + a2 * (1/(1+exp(-a3 (t-a4))) - 1/(1+exp(-a5 (t-a6))))

    a1 baseline, a2 amplitude, a3/a4 green-up rate and midpoint (DOY),
    a5/a6 senescence rate and midpoint (DOY).
    """
    return a1 + a2 * (
        1.0 / (1.0 + np.exp(-a3 * (doy - a4))) - 1.0 / (1.0 + np.exp(-a5 * (doy - a6)))
    )


class TimeSeriesAnalyzer:
    """
    Analyzes vegetation index time series for phenology extraction.

    Fits smooth curves to temporal NDVI profiles and extracts
    key phenological metrics per pixel block and per field.
    """

    PARAM_NAMES = ["a1_base", "a2_amp", "a3_rise_rate", "a4_greenup_doy",
                   "a5_fall_rate", "a6_senescence_doy"]

    def __init__(self):
        self.dates = None
        self.doy = None

    # ------------------------------------------------------------------ stack
    def extract_pixel_time_series(
        self,
        scenes: List[Dict],
        index_name: str = "ndvi",
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Extract a 3D time series stack from multiple scenes.

        Returns:
            tuple: (dates array, values 3D array [time, rows, cols], doy array)
        """
        dates, arrays = [], []
        for scene in scenes:
            if index_name in scene:
                dates.append(scene["date"])
                arrays.append(scene[index_name])
        if not dates:
            raise ValueError(f"No scene contains index '{index_name}'")

        dates = np.array(dates)
        sort_idx = np.argsort(dates)
        dates = dates[sort_idx]
        values = np.array([arrays[i] for i in sort_idx], dtype=np.float64)
        doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)

        self.dates, self.doy = dates, doy
        logger.info(
            f"Extracted time series: {len(dates)} dates, shape {values.shape}, "
            f"DOY range [{doy.min():.0f}, {doy.max():.0f}]"
        )
        return dates, values, doy

    # -------------------------------------------------------------- smoothing
    def smooth_time_series(
        self,
        values: np.ndarray,
        method: str = "savgol",
        window_length: int = 5,
        polyorder: int = 2,
        min_valid: Optional[int] = None,
    ) -> np.ndarray:
        """
        Smooth noisy time series along the temporal axis (vectorised).

        NaN gaps (clouds) are linearly interpolated first, then a
        Savitzky-Golay (or moving average) filter runs along axis 0.
        Pixels with fewer than ``min_valid`` observations (default: the
        window length) are left NaN.

        Args:
            values: 3D array [time, rows, cols]
            method: "savgol" or "moving_average"
            window_length: filter window (odd, <= time steps)
            polyorder: polynomial order for Savitzky-Golay
        """
        n_times = values.shape[0]
        window_length = min(window_length, n_times)
        if window_length % 2 == 0:
            window_length -= 1
        window_length = max(window_length, 3)
        polyorder = min(polyorder, window_length - 1)
        min_valid = window_length if min_valid is None else min_valid

        n_valid = np.sum(~np.isnan(values), axis=0)
        interp = interpolate_nan_along_axis0(values)
        interp = np.nan_to_num(interp, nan=0.0)

        if method == "savgol":
            smoothed = savgol_filter(interp, window_length, polyorder, axis=0)
        elif method == "moving_average":
            smoothed = ndimage.uniform_filter1d(interp, size=window_length, axis=0, mode="nearest")
        else:
            raise ValueError(f"Unknown smoothing method: {method}")

        smoothed = np.where((n_valid >= min_valid)[None, ...], smoothed, np.nan)
        logger.info(f"Time series smoothed using {method} (window={window_length})")
        return smoothed

    # ------------------------------------------------------------ curve fits
    @staticmethod
    def _double_logistic(doy, a1, a2, a3, a4, a5, a6):
        return double_logistic(doy, a1, a2, a3, a4, a5, a6)

    @staticmethod
    def _initial_guess(doy: np.ndarray, y: np.ndarray) -> List[float]:
        """Data-driven starting values: baseline, amplitude, half-rise/half-fall DOYs."""
        a1 = float(max(np.min(y), 0.0))
        a2 = float(max(np.max(y) - a1, 0.05))
        half = a1 + a2 / 2.0
        peak = int(np.argmax(y))
        rise = np.where(y[: peak + 1] >= half)[0]
        a4 = float(doy[rise[0]]) if len(rise) else float(doy[max(peak - 1, 0)])
        fall = np.where(y[peak:] <= half)[0]
        a6 = float(doy[peak + fall[0]]) if len(fall) else float(doy[-1])
        return [a1, a2, 0.08, a4, 0.08, max(a6, a4 + 20.0)]

    def _fit_one(self, doy: np.ndarray, y: np.ndarray, bounds) -> Optional[np.ndarray]:
        p0 = self._initial_guess(doy, y)
        p0 = [min(max(p, lo + 1e-6), hi - 1e-6) for p, lo, hi in zip(p0, bounds[0], bounds[1])]
        try:
            popt, _ = curve_fit(self._double_logistic, doy, y, p0=p0, bounds=bounds,
                                method="trf", max_nfev=400)
            return popt
        except (RuntimeError, ValueError):
            return None

    def _bounds(self, doy: np.ndarray):
        lo, hi = float(doy.min()), float(doy.max())
        return (
            [0.0, 0.05, 0.01, lo - 30.0, 0.01, lo],
            [0.6, 1.0, 0.5, hi, 0.5, hi + 30.0],
        )

    def fit_phenology_curve(
        self,
        doy: np.ndarray,
        values: np.ndarray,
        block_size: int = 5,
        min_valid: int = 6,
    ) -> Dict:
        """
        Fit double-logistic phenology curves on ``block_size`` x ``block_size``
        pixel blocks and upsample the result back to full resolution.

        The stack is aggregated by block mean (NaN-aware), one curve is fitted
        per block, and the parameters / expected values / R2 are repeated back
        to the original shape with ``np.repeat``. ``block_size=1`` gives the
        classic per-pixel fit.

        Returns dict with:
            parameters   [6, rows, cols]   a1..a6 (see PARAM_NAMES)
            expected     [time, rows, cols] fitted curve at the observation DOYs
            r_squared    [rows, cols]
            doy          the input DOY array
            block_size, fitted_fraction
        """
        block_size = max(int(block_size), 1)
        n_times, rows, cols = values.shape
        logger.info(f"Fitting double-logistic phenology curves (block_size={block_size})")

        pad_r = (-rows) % block_size
        pad_c = (-cols) % block_size
        padded = np.pad(values, ((0, 0), (0, pad_r), (0, pad_c)), constant_values=np.nan)
        nb_r, nb_c = padded.shape[1] // block_size, padded.shape[2] // block_size
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks (roads) are expected
            blocks = np.nanmean(
                padded.reshape(n_times, nb_r, block_size, nb_c, block_size), axis=(2, 4)
            )  # [time, nb_r, nb_c]

        params_b = np.full((6, nb_r, nb_c), np.nan)
        expected_b = np.full((n_times, nb_r, nb_c), np.nan)
        r2_b = np.full((nb_r, nb_c), np.nan)
        bounds = self._bounds(doy)
        fitted = 0
        for r in range(nb_r):
            for c in range(nb_c):
                y = blocks[:, r, c]
                valid = ~np.isnan(y)
                if valid.sum() < min_valid:
                    continue
                popt = self._fit_one(doy[valid], y[valid], bounds)
                if popt is None:
                    continue
                params_b[:, r, c] = popt
                curve = self._double_logistic(doy, *popt)
                expected_b[:, r, c] = curve
                ss_res = np.sum((y[valid] - curve[valid]) ** 2)
                ss_tot = np.sum((y[valid] - y[valid].mean()) ** 2)
                r2_b[r, c] = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
                fitted += 1

        def up(a):
            a = np.repeat(np.repeat(a, block_size, axis=-2), block_size, axis=-1)
            return a[..., :rows, :cols]

        n_blocks = nb_r * nb_c
        logger.info(f"Phenology curves fitted: {fitted}/{n_blocks} blocks ({fitted / n_blocks * 100:.1f}%)")
        return {
            "parameters": up(params_b),
            "expected": up(expected_b),
            "r_squared": up(r2_b),
            "doy": doy,
            "block_size": block_size,
            "fitted_fraction": fitted / n_blocks,
        }

    def fit_field_curves(
        self,
        field_gdf,
        stack: np.ndarray,
        profile: dict,
        doy: Optional[np.ndarray] = None,
        id_column: str = "field_id",
        min_valid: int = 6,
    ) -> Dict:
        """
        Fit one double-logistic curve per field on the field-mean series.

        Fields are rasterised (``rasterio.features.rasterize``) onto the stack
        grid; the per-date mean over each field's valid pixels is fitted.

        Returns dict with:
            table            DataFrame: field_id, n_pixels, n_valid_dates, a1..a6,
                             peak_doy, peak_value, greenup_doy, senescence_doy,
                             season_length_days, r_squared
            observed         [n_fields, time] field-mean index values
            expected         [n_fields, time] fitted values at observation DOYs
            doy_dense        daily DOY grid spanning the observations
            expected_dense   [n_fields, len(doy_dense)] fitted curve on that grid
            expected_raster  [time, rows, cols] field-expected value per pixel
            field_id_raster  [rows, cols] int32, 0 = no field, k+1 = row k of field_gdf
        """
        doy = self.doy if doy is None else np.asarray(doy, dtype=float)
        if doy is None:
            raise ValueError("doy is required (or call extract_pixel_time_series first)")

        n_times = stack.shape[0]
        id_raster, ids = rasterize_fields(field_gdf, profile, id_column)
        n_fields = len(ids)
        flat_ids = id_raster.ravel()

        # field-mean per date; a field counts as observed on a date only when
        # at least half of its pixels are cloud-free
        n_pix = np.bincount(flat_ids[flat_ids > 0], minlength=n_fields + 1)[1:]
        observed = np.full((n_fields, n_times), np.nan)
        for t in range(n_times):
            vals = stack[t].ravel()
            ok = (flat_ids > 0) & ~np.isnan(vals)
            sums = np.bincount(flat_ids[ok], weights=vals[ok], minlength=n_fields + 1)[1:]
            cnts = np.bincount(flat_ids[ok], minlength=n_fields + 1)[1:]
            with np.errstate(invalid="ignore", divide="ignore"):
                means = sums / cnts
            means[cnts < 0.5 * np.maximum(n_pix, 1)] = np.nan
            observed[:, t] = means

        doy_dense = np.arange(doy.min(), doy.max() + 1.0)
        expected = np.full((n_fields, n_times), np.nan)
        expected_dense = np.full((n_fields, len(doy_dense)), np.nan)
        bounds = self._bounds(doy)
        rows = []
        for k in range(n_fields):
            y = observed[k]
            valid = ~np.isnan(y)
            rec = {"field_id": ids[k], "n_pixels": int(n_pix[k]), "n_valid_dates": int(valid.sum())}
            popt = self._fit_one(doy[valid], y[valid], bounds) if valid.sum() >= min_valid else None
            if popt is not None:
                expected[k] = self._double_logistic(doy, *popt)
                dense = self._double_logistic(doy_dense, *popt)
                expected_dense[k] = dense
                peak = int(np.argmax(dense))
                ss_res = np.sum((y[valid] - expected[k][valid]) ** 2)
                ss_tot = np.sum((y[valid] - y[valid].mean()) ** 2)
                rec.update({name: float(v) for name, v in zip(self.PARAM_NAMES, popt)})
                rec.update({
                    "peak_doy": float(doy_dense[peak]),
                    "peak_value": float(dense[peak]),
                    "greenup_doy": float(popt[3]),
                    "senescence_doy": float(popt[5]),
                    "season_length_days": float(popt[5] - popt[3]),
                    "r_squared": float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
                })
            rows.append(rec)
        table = pd.DataFrame(rows)

        # expected value per pixel from its field curve (roads -> NaN)
        lookup = np.vstack([np.full((1, n_times), np.nan), expected])  # index 0 = no field
        expected_raster = np.moveaxis(lookup[id_raster], -1, 0)

        n_ok = int(table["peak_doy"].notna().sum()) if "peak_doy" in table else 0
        logger.info(f"Field curves fitted: {n_ok}/{n_fields} fields")
        return {
            "table": table,
            "observed": observed,
            "expected": expected,
            "doy": doy,
            "doy_dense": doy_dense,
            "expected_dense": expected_dense,
            "expected_raster": expected_raster,
            "field_id_raster": id_raster,
        }

    # ------------------------------------------------------------- metrics
    def get_peak_metrics(self, phenology: Dict) -> Dict[str, np.ndarray]:
        """
        Extract peak phenology metrics from fitted curves.

        The fitted curve is evaluated on a daily DOY grid (vectorised over
        pixels) so the peak is not limited to the acquisition dates.

        Returns dict with:
            peak_doy, peak_value, greenup_doy (a4), senescence_doy (a6),
            growing_season_length (a6 - a4, days)
        """
        params = phenology["parameters"]
        doy = phenology["doy"]
        rows, cols = params.shape[1], params.shape[2]
        ok = ~np.isnan(params[0])

        peak_value = np.full((rows, cols), -np.inf)
        peak_doy = np.full((rows, cols), np.nan)
        for d in np.arange(doy.min(), doy.max() + 1.0):
            v = self._double_logistic(d, *params)
            better = ok & (v > peak_value)
            peak_value[better] = v[better]
            peak_doy[better] = d
        peak_value[~ok] = np.nan

        greenup_doy = params[3]
        senescence_doy = params[5]
        season_length = senescence_doy - greenup_doy

        metrics = {
            "peak_doy": peak_doy,
            "peak_value": peak_value,
            "greenup_doy": greenup_doy,
            "senescence_doy": senescence_doy,
            "growing_season_length": season_length,
        }
        if ok.any():
            logger.info(
                f"Peak metrics: mean peak DOY {np.nanmean(peak_doy):.0f}, "
                f"mean peak NDVI {np.nanmean(peak_value):.3f}, "
                f"mean season length {np.nanmean(season_length):.0f} days"
            )
        return metrics
