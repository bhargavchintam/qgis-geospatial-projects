"""
Spectral indices for Sentinel-2 surface reflectance.

Band order used across the project (6-band stack, reflectance 0..1):

    index 0  B02  blue   (490 nm)
    index 1  B03  green  (560 nm)
    index 2  B04  red    (665 nm)
    index 3  B08  NIR    (842 nm)
    index 4  B11  SWIR1  (1610 nm)
    index 5  B12  SWIR2  (2190 nm)
"""

import numpy as np

BAND_NAMES = ["B02", "B03", "B04", "B08", "B11", "B12"]
BAND_INDEX = {name: i for i, name in enumerate(BAND_NAMES)}


def _normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) with NaN where the denominator is zero."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out = np.where(np.isfinite(out), out, np.nan)
    return out


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """Normalized Difference Vegetation Index = (NIR - Red) / (NIR + Red)."""
    return _normalized_difference(nir, red)


def nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
    """Normalized Burn Ratio = (NIR - SWIR2) / (NIR + SWIR2). Drops sharply when canopy is removed."""
    return _normalized_difference(nir, swir2)


def ndmi(nir: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Normalized Difference Moisture Index = (NIR - SWIR1) / (NIR + SWIR1)."""
    return _normalized_difference(nir, swir1)


def compute_all(stack: np.ndarray) -> dict:
    """Compute NDVI, NBR and NDMI from a (6, rows, cols) reflectance stack."""
    nir = stack[BAND_INDEX["B08"]]
    return {
        "ndvi": ndvi(nir, stack[BAND_INDEX["B04"]]),
        "nbr": nbr(nir, stack[BAND_INDEX["B12"]]),
        "ndmi": ndmi(nir, stack[BAND_INDEX["B11"]]),
    }


def _stretch(band: np.ndarray, low: float, high: float) -> np.ndarray:
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        return np.zeros(band.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, [low, high])
    if hi <= lo:
        hi = lo + 1e-6
    scaled = np.clip((band - lo) / (hi - lo), 0, 1)
    scaled = np.where(np.isfinite(scaled), scaled, 0)
    return (scaled * 255).astype(np.uint8)


def false_color_composite(stack: np.ndarray, bands=(3, 2, 1), low: float = 2, high: float = 98) -> np.ndarray:
    """
    Build an RGB uint8 image (rows, cols, 3) from a band stack.

    Default bands (NIR, red, green) give the classic false-colour view where
    healthy forest is bright red and cleared land is pale/cyan. Each channel is
    linearly stretched between its ``low`` and ``high`` percentiles.
    """
    channels = [_stretch(stack[b], low, high) for b in bands]
    return np.dstack(channels)
