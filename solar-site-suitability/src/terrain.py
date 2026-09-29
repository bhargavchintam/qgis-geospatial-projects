"""
Terrain derivatives from a DEM: slope, aspect and hillshade.

All functions take a 2-D elevation array (row 0 = north, columns increase
eastward) and the pixel size ``res`` in the same units as the elevation
(metres). Gradients use Horn's (1981) 3x3 finite-difference kernel, the
same method as ArcGIS, GDAL and QGIS "Slope"/"Aspect".
"""

import numpy as np


def _horn_gradients(dem: np.ndarray, res: float):
    """Return (dz/dx, dz/dy_array) using Horn's kernel.

    dz/dx is the change in elevation per metre going east.
    dz/dy_array is the change per metre going down the array (south).
    Edges are handled by replicating the border pixels.
    """
    z = np.asarray(dem, dtype=np.float64)
    p = np.pad(z, 1, mode="edge")
    z1, z2, z3 = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    z4, z6 = p[1:-1, :-2], p[1:-1, 2:]
    z7, z8, z9 = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    dzdx = ((z3 + 2.0 * z6 + z9) - (z1 + 2.0 * z4 + z7)) / (8.0 * res)
    dzdy = ((z7 + 2.0 * z8 + z9) - (z1 + 2.0 * z2 + z3)) / (8.0 * res)
    return dzdx, dzdy


def slope_degrees(dem: np.ndarray, res: float) -> np.ndarray:
    """Slope in degrees (0 = flat, 90 = vertical) using Horn's method."""
    dzdx, dzdy = _horn_gradients(dem, res)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))


def aspect_degrees(dem: np.ndarray, res: float, flat_value: float = -1.0) -> np.ndarray:
    """Downslope aspect in compass degrees.

    0 = north, 90 = east, 180 = south, 270 = west (clockwise). Flat pixels
    (zero gradient) get ``flat_value`` (default -1), matching GDAL/ArcGIS.
    """
    dzdx, dzdy = _horn_gradients(dem, res)
    # Downslope vector: east component = -dzdx, north component = -(-dzdy) = dzdy
    aspect = np.degrees(np.arctan2(-dzdx, dzdy))
    aspect = np.mod(aspect, 360.0)
    flat = (dzdx == 0) & (dzdy == 0)
    aspect[flat] = flat_value
    return aspect


def hillshade(dem: np.ndarray, res: float, azimuth: float = 315.0,
              altitude: float = 45.0, z_factor: float = 1.0) -> np.ndarray:
    """Shaded relief in [0, 1] for a light at ``azimuth``/``altitude`` degrees.

    Standard formula (Burrough & McDonnell, 1998):
        shade = cos(zenith) cos(slope) + sin(zenith) sin(slope) cos(az - aspect)
    """
    dzdx, dzdy = _horn_gradients(dem, res)
    dzdx = dzdx * z_factor
    dzdy = dzdy * z_factor
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    # Aspect in the maths convention used by the ESRI hillshade formula
    aspect_rad = np.arctan2(dzdy, -dzdx)
    aspect_rad = np.where(aspect_rad < 0, aspect_rad + 2.0 * np.pi, aspect_rad)
    zenith_rad = np.radians(90.0 - altitude)
    azimuth_rad = np.radians(np.mod(360.0 - azimuth + 90.0, 360.0))
    shade = (np.cos(zenith_rad) * np.cos(slope_rad)
             + np.sin(zenith_rad) * np.sin(slope_rad) * np.cos(azimuth_rad - aspect_rad))
    return np.clip(shade, 0.0, 1.0)
