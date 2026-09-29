"""
Land Surface Temperature (LST) Processor

Derives Land Surface Temperature from Landsat 8/9 thermal infrared data
using the single-channel algorithm with NDVI-based emissivity correction.

Workflow:
    1. DN → Top-of-Atmosphere (TOA) Spectral Radiance
    2. TOA Radiance → Brightness Temperature
    3. NDVI computation from Red + NIR bands
    4. NDVI → Proportion of Vegetation (Pv)
    5. Pv → Land Surface Emissivity (ε)
    6. Brightness Temperature + ε → Land Surface Temperature (LST)
"""

import numpy as np
import rasterio
import logging
from pathlib import Path
from typing import Optional, Tuple

from .utils import load_config, read_raster, write_raster, normalize_array

logger = logging.getLogger(__name__)


class LSTProcessor:
    """
    Computes Land Surface Temperature from Landsat 8/9 thermal data.

    The processor implements the mono-window algorithm with emissivity
    correction based on NDVI-derived proportion of vegetation.
    """

    # Physical constant: h*c / (σ * λ) - Planck's radiation constant
    RHO = 1.438e-2  # m·K

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize LSTProcessor with configuration.

        Args:
            config_path: path to YAML configuration file
        """
        self.config = load_config(config_path)
        self.landsat_cfg = self.config["landsat"]
        self.emissivity_cfg = self.config["emissivity"]
        self.ndvi_cfg = self.config["ndvi"]

        # Landsat calibration constants
        self.K1 = self.landsat_cfg["constants"]["K1"]
        self.K2 = self.landsat_cfg["constants"]["K2"]
        self.wavelength = self.landsat_cfg["constants"]["wavelength"] * 1e-6  # μm → m

    def compute_lst(
        self,
        thermal_band: str,
        red_band: str,
        nir_band: str,
        output_path: Optional[str] = None,
    ) -> Tuple[np.ndarray, dict]:
        """
        Full LST computation pipeline.

        Args:
            thermal_band: path to Landsat Band 10 (thermal infrared)
            red_band: path to Landsat Band 4 (red)
            nir_band: path to Landsat Band 5 (NIR)
            output_path: optional path to save output GeoTIFF

        Returns:
            tuple: (LST array in Celsius, rasterio profile)
        """
        logger.info("Starting LST computation pipeline")

        # Read input bands
        thermal, profile = read_raster(thermal_band)
        red, _ = read_raster(red_band)
        nir, _ = read_raster(nir_band)

        # Step 1: Convert DN to brightness temperature
        # For Collection 2 Level-2, thermal band is already in Kelvin × 10
        logger.info("Computing brightness temperature")
        bt = self._dn_to_brightness_temperature(thermal)

        # Step 2: Compute NDVI
        logger.info("Computing NDVI")
        ndvi = self._compute_ndvi(red, nir)

        # Step 3: Derive proportion of vegetation
        logger.info("Computing proportion of vegetation")
        pv = self._compute_proportion_vegetation(ndvi)

        # Step 4: Estimate land surface emissivity
        logger.info("Estimating land surface emissivity")
        emissivity = self._compute_emissivity(ndvi, pv)

        # Step 5: Calculate Land Surface Temperature
        logger.info("Deriving Land Surface Temperature")
        lst = self._compute_lst(bt, emissivity)

        # Convert Kelvin to Celsius
        lst_celsius = lst - 273.15

        # Mask invalid values
        lst_celsius = np.where(
            (lst_celsius > -50) & (lst_celsius < 80), lst_celsius, np.nan
        )

        # Return a clean float profile. The thermal band is usually uint16
        # with nodata=0; downstream rasters are float with NaN nodata.
        profile = dict(profile)
        profile.update(dtype="float32", nodata=np.nan, count=1)
        for key in ("blockxsize", "blockysize", "tiled", "interleave"):
            profile.pop(key, None)

        if output_path:
            write_raster(lst_celsius, profile, output_path)
            logger.info(f"LST raster saved to: {output_path}")

        # Log summary statistics
        logger.info(
            f"LST Statistics - "
            f"Mean: {np.nanmean(lst_celsius):.1f}°C, "
            f"Max: {np.nanmax(lst_celsius):.1f}°C, "
            f"Min: {np.nanmin(lst_celsius):.1f}°C, "
            f"Std: {np.nanstd(lst_celsius):.1f}°C"
        )

        return lst_celsius, profile

    def _dn_to_brightness_temperature(self, thermal: np.ndarray) -> np.ndarray:
        """
        Convert thermal band DN values to brightness temperature (Kelvin).

        For Landsat Collection 2 Level-2 Science Products, the thermal
        band values are already scaled surface temperature (Kelvin × 0.00341802 + 149.0).
        For Level-1 products, conversion uses radiance calibration constants.

        Args:
            thermal: thermal band array (Band 10)

        Returns:
            Brightness temperature array in Kelvin
        """
        if self.landsat_cfg["level"] == "L2SP":
            # Collection 2 Level-2: apply scale factor and offset
            bt = thermal * 0.00341802 + 149.0
        else:
            # Level-1: DN → Radiance → BT using Planck equation
            # Lλ = ML * Qcal + AL (using metadata values)
            radiance = thermal * 0.0003342 + 0.1
            with np.errstate(divide="ignore", invalid="ignore"):
                bt = self.K2 / np.log((self.K1 / radiance) + 1)

        # DN fill value 0 gives 149 K which is not a real surface temperature
        bt = np.where(bt > 150.0, bt, np.nan)
        return bt

    def _compute_ndvi(self, red: np.ndarray, nir: np.ndarray) -> np.ndarray:
        """
        Compute Normalized Difference Vegetation Index.

        NDVI = (NIR - Red) / (NIR + Red)

        Args:
            red: Red band array (Band 4)
            nir: NIR band array (Band 5)

        Returns:
            NDVI array with values in [-1, 1]
        """
        # Avoid division by zero
        denominator = nir + red
        denominator = np.where(denominator == 0, np.nan, denominator)

        ndvi = (nir - red) / denominator
        ndvi = np.clip(ndvi, -1.0, 1.0)

        return ndvi

    def _compute_proportion_vegetation(self, ndvi: np.ndarray) -> np.ndarray:
        """
        Compute Proportion of Vegetation (Pv) from NDVI.

        Pv = ((NDVI - NDVImin) / (NDVImax - NDVImin))²

        where NDVImin = soil threshold and NDVImax = vegetation threshold.

        Args:
            ndvi: NDVI array

        Returns:
            Proportion of vegetation array [0, 1]
        """
        ndvi_min = self.ndvi_cfg["soil_threshold"]
        ndvi_max = self.ndvi_cfg["vegetation_threshold"]

        pv = ((ndvi - ndvi_min) / (ndvi_max - ndvi_min)) ** 2
        pv = np.clip(pv, 0.0, 1.0)

        # Bare soil: Pv = 0
        pv = np.where(ndvi < ndvi_min, 0.0, pv)
        # Full vegetation: Pv = 1
        pv = np.where(ndvi > ndvi_max, 1.0, pv)

        return pv

    def _compute_emissivity(
        self, ndvi: np.ndarray, pv: np.ndarray
    ) -> np.ndarray:
        """
        Estimate Land Surface Emissivity using NDVI thresholds.

        Three-class approach:
        - Water/bare soil (NDVI < 0.2): ε = 0.966
        - Mixed pixels (0.2 ≤ NDVI ≤ 0.5): ε = 0.004 × Pv + 0.986
        - Dense vegetation (NDVI > 0.5): ε = 0.973

        Args:
            ndvi: NDVI array
            pv: proportion of vegetation array

        Returns:
            Emissivity array
        """
        soil_thresh = self.ndvi_cfg["soil_threshold"]
        veg_thresh = self.ndvi_cfg["vegetation_threshold"]

        emissivity = np.full_like(ndvi, np.nan)

        # Water and bare soil
        emissivity = np.where(ndvi < soil_thresh, self.emissivity_cfg["soil"], emissivity)

        # Mixed pixels - linear model
        mixed_mask = (ndvi >= soil_thresh) & (ndvi <= veg_thresh)
        emissivity = np.where(
            mixed_mask,
            self.emissivity_cfg["slope"] * pv + self.emissivity_cfg["offset"],
            emissivity,
        )

        # Dense vegetation
        emissivity = np.where(ndvi > veg_thresh, self.emissivity_cfg["vegetation"], emissivity)

        return emissivity

    def _compute_lst(
        self, bt: np.ndarray, emissivity: np.ndarray
    ) -> np.ndarray:
        """
        Compute Land Surface Temperature from brightness temperature
        and emissivity.

        LST = BT / (1 + (λ × BT / ρ) × ln(ε))

        where:
            BT  = brightness temperature (K)
            λ   = wavelength of emitted radiance (m)
            ρ   = h × c / σ = 1.438 × 10⁻² m·K
            ε   = land surface emissivity

        Args:
            bt: brightness temperature array (Kelvin)
            emissivity: land surface emissivity array

        Returns:
            Land Surface Temperature array (Kelvin)
        """
        log_emissivity = np.log(emissivity)
        correction_factor = (self.wavelength * bt) / self.RHO

        lst = bt / (1 + correction_factor * log_emissivity)

        return lst

    def compute_lst_anomaly(
        self,
        lst: np.ndarray,
        rural_mask_path: Optional[str] = None,
        rural_mask: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Compute LST anomaly relative to a rural baseline.

        The UHI effect is measured as the difference between local LST
        and the mean rural LST (or the study area mean if no mask is given).

        Args:
            lst: LST array in Celsius
            rural_mask_path: optional path to a rural area mask raster (>0 = rural)
            rural_mask: optional boolean/int array with the same shape as ``lst``
                (>0 = rural). Takes precedence over ``rural_mask_path``.

        Returns:
            LST anomaly array (positive = warmer than baseline)
        """
        baseline = None
        if rural_mask is None and rural_mask_path:
            rural_mask, _ = read_raster(rural_mask_path)

        if rural_mask is not None:
            rural_lst = lst[(rural_mask > 0) & ~np.isnan(lst)]
            if rural_lst.size > 0:
                baseline = float(np.mean(rural_lst))
        if baseline is None:
            baseline = float(np.nanmean(lst))

        anomaly = lst - baseline
        self.last_baseline = baseline
        logger.info(f"LST Anomaly - Baseline: {baseline:.1f}°C, Max anomaly: {np.nanmax(anomaly):.1f}°C")

        return anomaly
