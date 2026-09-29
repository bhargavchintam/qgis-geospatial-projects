"""
Criterion standardisation curves and constraint mapping.

Every ``*_score`` function turns a physical raster into a 0..1 suitability
raster (1 = best for a utility-scale PV plant). The curve for each one is
documented in its docstring and repeated in the README. NaN inputs stay NaN.

Constraint codes used by ``constraint_reasons``:
    0 allowed, 1 water body, 2 urban / built-up, 3 protected area,
    4 slope above the maximum, 5 inside the residential buffer.
"""

import numpy as np

CONSTRAINT_LABELS = {
    0: "Allowed",
    1: "Water body",
    2: "Urban / built-up",
    3: "Protected area",
    4: "Slope too steep",
    5: "Residential buffer",
}


def ghi_score(ghi: np.ndarray, lo: float = 5.0, hi: float = 7.0) -> np.ndarray:
    """Linear: 0 at ``lo`` kWh/m2/day or below, 1 at ``hi`` or above.

    Global horizontal irradiance drives energy yield almost linearly, so a
    straight ramp between a poor (5.0) and an excellent (7.0) resource is
    used. Values are clipped to [0, 1].
    """
    ghi = np.asarray(ghi, dtype=np.float64)
    return np.clip((ghi - lo) / (hi - lo), 0.0, 1.0)


def slope_score(slope: np.ndarray, ideal: float = 3.0, max_ok: float = 10.0) -> np.ndarray:
    """Flat is best: 1 up to ``ideal`` degrees, then linear to 0 at ``max_ok``.

    Fixed-tilt racking is cheapest on near-flat ground; grading cost rises
    quickly beyond a few degrees and above about 10 degrees most developers
    walk away. Slopes above ``max_ok`` score 0.
    """
    slope = np.asarray(slope, dtype=np.float64)
    score = 1.0 - (slope - ideal) / (max_ok - ideal)
    score = np.where(slope <= ideal, 1.0, score)
    return np.clip(score, 0.0, 1.0)


def aspect_score(aspect: np.ndarray, flat_value: float = -1.0) -> np.ndarray:
    """Cosine falloff from south: 1 at 180 degrees, 0.5 east/west, 0 north.

    score = (1 + cos(aspect - 180 deg)) / 2. Flat pixels (``flat_value``)
    score 1 because panels can be tilted freely on flat ground. In the
    northern hemisphere south-facing slopes receive the most irradiance.
    """
    aspect = np.asarray(aspect, dtype=np.float64)
    score = (1.0 + np.cos(np.radians(aspect - 180.0))) / 2.0
    score = np.where(aspect == flat_value, 1.0, score)
    score = np.where(np.isnan(aspect), np.nan, score)
    return np.clip(score, 0.0, 1.0)


def distance_score(dist_m: np.ndarray, full_score_within: float = 1000.0,
                   zero_at: float = 15000.0) -> np.ndarray:
    """Linear decay: 1 within ``full_score_within`` m, 0 at ``zero_at`` m.

    Used for distance to transmission lines / substations (interconnection
    cost) and to roads (construction access). Anything closer than the
    first threshold is equally good; beyond ``zero_at`` the criterion
    contributes nothing.
    """
    dist_m = np.asarray(dist_m, dtype=np.float64)
    score = 1.0 - (dist_m - full_score_within) / (zero_at - full_score_within)
    score = np.where(dist_m <= full_score_within, 1.0, score)
    return np.clip(score, 0.0, 1.0)


def landuse_score(landuse: np.ndarray, mapping: dict, default: float = 0.0) -> np.ndarray:
    """Look-up table: each land-use code maps to a 0..1 preference.

    Example mapping: {1: 1.0 (desert scrub), 2: 0.4 (agriculture),
    3: 0.0 (urban), 4: 0.0 (water), 5: 0.0 (protected)}. Codes not in the
    mapping get ``default``. NaN inputs stay NaN.
    """
    landuse = np.asarray(landuse, dtype=np.float64)
    score = np.full(landuse.shape, default, dtype=np.float64)
    for code, value in mapping.items():
        score[landuse == float(code)] = float(value)
    score[np.isnan(landuse)] = np.nan
    return score


def constraint_reasons(landuse: np.ndarray, slope: np.ndarray, residential_dist: np.ndarray,
                       water_codes=(4,), urban_codes=(3,), protected_codes=(5,),
                       max_slope: float = 15.0, residential_buffer_m: float = 500.0) -> np.ndarray:
    """Integer raster of why a pixel is excluded (0 = allowed).

    Rules are applied in the order steep slope (4), residential buffer (5),
    protected (3), urban (2), water (1), so when a pixel fails several rules
    the label shows the hard land-cover exclusion first. Note the buffer
    rule fires only outside the urban pixels themselves, so "residential
    buffer" counts the ring around the town, not the town.
    """
    landuse = np.asarray(landuse)
    slope = np.asarray(slope, dtype=np.float64)
    residential_dist = np.asarray(residential_dist, dtype=np.float64)
    reasons = np.zeros(landuse.shape, dtype=np.int32)

    reasons[slope > max_slope] = 4
    if residential_buffer_m > 0:
        reasons[residential_dist <= residential_buffer_m] = 5
    for code in protected_codes:
        reasons[landuse == code] = 3
    for code in urban_codes:
        reasons[landuse == code] = 2
    for code in water_codes:
        reasons[landuse == code] = 1
    return reasons


def build_constraint_mask(landuse: np.ndarray, slope: np.ndarray, residential_dist: np.ndarray,
                          water_codes=(4,), urban_codes=(3,), protected_codes=(5,),
                          max_slope: float = 15.0, residential_buffer_m: float = 500.0) -> np.ndarray:
    """Boolean mask: True where development is allowed.

    A pixel is excluded if it is water, urban or protected land, steeper
    than ``max_slope`` degrees, or within ``residential_buffer_m`` metres of
    residential polygons. See ``constraint_reasons`` for the coded version.
    """
    reasons = constraint_reasons(landuse, slope, residential_dist, water_codes,
                                 urban_codes, protected_codes, max_slope,
                                 residential_buffer_m)
    return reasons == 0
