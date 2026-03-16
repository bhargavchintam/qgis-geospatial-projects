"""
Multi-Temporal Phenology Analysis

Analyzes vegetation index time series to track crop growth stages,
fit phenology curves, and extract key metrics (green-up, peak, senescence).
"""

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TimeSeriesAnalyzer:
    """
    Analyzes vegetation index time series for phenology extraction.

    Fits smooth curves to temporal NDVI profiles and extracts
    key phenological metrics per pixel.
    """

    def __init__(self):
        pass

    def extract_pixel_time_series(
        self,
        scenes: List[Dict],
        index_name: str = "ndvi",
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Extract a 3D time series stack from multiple scenes.

        Args:
            scenes: list of scene dicts with computed indices
            index_name: name of the index to stack

        Returns:
            tuple: (dates array, values 3D array [time, rows, cols], doy array)
        """
        dates = []
        arrays = []

        for scene in scenes:
            if index_name in scene:
                dates.append(scene["date"])
                arrays.append(scene[index_name])

        dates = np.array(dates)
        sort_idx = np.argsort(dates)
        dates = dates[sort_idx]
        values = np.array([arrays[i] for i in sort_idx])

        # Day of year
        doy = np.array([d.timetuple().tm_yday for d in dates])

        logger.info(
            f"Extracted time series: {len(dates)} dates, "
            f"shape {values.shape}, DOY range [{doy.min()}, {doy.max()}]"
        )

        return dates, values, doy

    def smooth_time_series(
        self,
        values: np.ndarray,
        method: str = "savgol",
        window_length: int = 5,
        polyorder: int = 2,
    ) -> np.ndarray:
        """
        Smooth noisy time series using Savitzky-Golay filter.

        Applied per-pixel along the temporal axis.

        Args:
            values: 3D array [time, rows, cols]
            method: smoothing method ("savgol", "moving_average")
            window_length: filter window (must be odd, ≤ time steps)
            polyorder: polynomial order for Savitzky-Golay

        Returns:
            Smoothed 3D array
        """
        n_times, rows, cols = values.shape

        # Ensure window_length is valid
        window_length = min(window_length, n_times)
        if window_length % 2 == 0:
            window_length -= 1
        window_length = max(window_length, 3)
        polyorder = min(polyorder, window_length - 1)

        smoothed = np.full_like(values, np.nan)

        if method == "savgol":
            for r in range(rows):
                for c in range(cols):
                    pixel_ts = values[:, r, c]
                    valid = ~np.isnan(pixel_ts)

                    if np.sum(valid) >= window_length:
                        # Interpolate gaps for smoothing
                        interp = np.interp(
                            np.arange(n_times),
                            np.where(valid)[0],
                            pixel_ts[valid],
                        )
                        smoothed[:, r, c] = savgol_filter(
                            interp, window_length, polyorder
                        )
        elif method == "moving_average":
            kernel = np.ones(window_length) / window_length
            for r in range(rows):
                for c in range(cols):
                    pixel_ts = values[:, r, c]
                    valid = ~np.isnan(pixel_ts)
                    if np.sum(valid) >= window_length:
                        interp = np.interp(
                            np.arange(n_times),
                            np.where(valid)[0],
                            pixel_ts[valid],
                        )
                        smoothed[:, r, c] = np.convolve(interp, kernel, mode="same")

        logger.info(f"Time series smoothed using {method} (window={window_length})")
        return smoothed

    @staticmethod
    def _double_logistic(doy, a1, a2, a3, a4, a5, a6):
        """
        Double logistic function for phenology curve fitting.

        Models the green-up and senescence of vegetation:
        f(t) = a1 + a2 × (1/(1+exp(-a3(t-a4))) - 1/(1+exp(-a5(t-a6))))

        Parameters:
            a1: minimum NDVI (winter baseline)
            a2: amplitude (peak - baseline)
            a3: green-up rate
            a4: green-up midpoint (DOY)
            a5: senescence rate
            a6: senescence midpoint (DOY)
        """
        return a1 + a2 * (
            1 / (1 + np.exp(-a3 * (doy - a4)))
            - 1 / (1 + np.exp(-a5 * (doy - a6)))
        )

    def fit_phenology_curve(
        self,
        doy: np.ndarray,
        values: np.ndarray,
    ) -> Dict:
        """
        Fit double-logistic phenology curves per pixel.

        Args:
            doy: day-of-year array (1D)
            values: 3D index array [time, rows, cols]

        Returns:
            dict with fitted curve parameters, expected values, residuals
        """
        logger.info("Fitting double-logistic phenology curves")

        n_times, rows, cols = values.shape
        params_map = np.full((6, rows, cols), np.nan)
        expected = np.full_like(values, np.nan)
        r_squared = np.full((rows, cols), np.nan)

        # Initial parameter guesses
        p0 = [0.15, 0.7, 0.05, 140, 0.05, 260]
        bounds = (
            [0, 0, 0.001, 90, 0.001, 200],
            [0.5, 1.0, 0.5, 200, 0.5, 330],
        )

        fitted_count = 0

        for r in range(rows):
            for c in range(cols):
                pixel_ts = values[:, r, c]
                valid = ~np.isnan(pixel_ts)

                if np.sum(valid) < 6:  # Need minimum observations
                    continue

                try:
                    popt, _ = curve_fit(
                        self._double_logistic,
                        doy[valid],
                        pixel_ts[valid],
                        p0=p0,
                        bounds=bounds,
                        maxfev=1000,
                    )

                    params_map[:, r, c] = popt
                    fitted = self._double_logistic(doy, *popt)
                    expected[:, r, c] = fitted

                    # R-squared
                    ss_res = np.sum((pixel_ts[valid] - fitted[valid]) ** 2)
                    ss_tot = np.sum((pixel_ts[valid] - np.mean(pixel_ts[valid])) ** 2)
                    r_squared[r, c] = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

                    fitted_count += 1

                except (RuntimeError, ValueError):
                    continue

        logger.info(
            f"Phenology curves fitted: {fitted_count}/{rows*cols} pixels "
            f"({fitted_count/(rows*cols)*100:.1f}%)"
        )

        return {
            "parameters": params_map,
            "expected": expected,
            "r_squared": r_squared,
            "doy": doy,
        }

    def get_peak_metrics(
        self, phenology: Dict
    ) -> Dict[str, np.ndarray]:
        """
        Extract peak phenology metrics from fitted curves.

        Returns:
            dict with:
                peak_doy: day of year of maximum NDVI
                peak_value: maximum NDVI value
                greenup_doy: start of growing season
                senescence_doy: start of senescence
                growing_season_length: days between greenup and senescence
        """
        params = phenology["parameters"]
        expected = phenology["expected"]
        doy = phenology["doy"]

        rows, cols = params.shape[1], params.shape[2]

        peak_doy = np.full((rows, cols), np.nan)
        peak_value = np.full((rows, cols), np.nan)

        for r in range(rows):
            for c in range(cols):
                if np.isnan(params[0, r, c]):
                    continue

                pixel_curve = expected[:, r, c]
                if np.all(np.isnan(pixel_curve)):
                    continue

                peak_idx = np.nanargmax(pixel_curve)
                peak_doy[r, c] = doy[peak_idx]
                peak_value[r, c] = pixel_curve[peak_idx]

        # Green-up and senescence from logistic parameters
        greenup_doy = params[3]  # a4 parameter
        senescence_doy = params[5]  # a6 parameter
        season_length = senescence_doy - greenup_doy

        metrics = {
            "peak_doy": peak_doy,
            "peak_value": peak_value,
            "greenup_doy": greenup_doy,
            "senescence_doy": senescence_doy,
            "growing_season_length": season_length,
        }

        logger.info(
            f"Peak metrics — Mean peak DOY: {np.nanmean(peak_doy):.0f}, "
            f"Mean peak NDVI: {np.nanmean(peak_value):.3f}, "
            f"Mean season length: {np.nanmean(season_length):.0f} days"
        )

        return metrics
