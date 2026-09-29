# -*- coding: utf-8 -*-
"""
AHP Weighted Overlay (Portfolio) - QGIS Processing algorithm.

Takes N criterion rasters (same grid), a comma-separated list of N weights
(for example the AHP priority vector printed by demo.py), and an optional
comma-separated list of N invert flags (1 = high input values mean LOW
susceptibility, e.g. slope, elevation, distance to river, Ksat). Each raster
is min-max normalised to 0..1 (nodata ignored, inverted when flagged), the
weighted sum is computed and rescaled to 0..1, and written as a Float32
GeoTIFF.

Install: Processing Toolbox > Scripts > Create New Script, paste this file,
save it as flood_weighted_overlay_algorithm.py, then run
"Bhargav Portfolio > AHP Weighted Overlay (Portfolio)".

Author: Bhargav Chintam, 2026, MIT License.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterString,
)
from osgeo import gdal
import numpy as np


class AhpWeightedOverlayAlgorithm(QgsProcessingAlgorithm):
    """Weighted overlay of min-max normalised criterion rasters (AHP style)."""

    INPUTS = "INPUTS"
    WEIGHTS = "WEIGHTS"
    INVERT = "INVERT"
    STRETCH = "STRETCH"
    OUTPUT = "OUTPUT"

    def tr(self, text):
        return QCoreApplication.translate("Processing", text)

    def createInstance(self):
        return AhpWeightedOverlayAlgorithm()

    def name(self):
        return "portfolio_ahp_weighted_overlay"

    def displayName(self):
        return self.tr("AHP Weighted Overlay (Portfolio)")

    def group(self):
        return self.tr("Bhargav Portfolio")

    def groupId(self):
        return "bhargav_portfolio"

    def shortHelpString(self):
        return self.tr(
            "Combines several criterion rasters into one 0..1 index with a weighted sum.\n\n"
            "Inputs: rasters on the same grid (same size and extent), in the order of the weights.\n"
            "Weights: comma-separated, one per raster (they are normalised to sum to 1), e.g. the AHP "
            "priority vector 0.313,0.193,0.158,0.115,0.095,0.070,0.056 for "
            "TWI, slope, distance to river, rainfall, elevation, Ksat, land cover score.\n"
            "Invert flags: optional comma-separated 0/1 per raster; 1 means high values reduce "
            "susceptibility (slope, elevation, distance to river, Ksat).\n"
            "Each raster is min-max normalised (nodata ignored). Output: Float32 GeoTIFF in 0..1; "
            "'Stretch result' rescales the weighted sum to use the full 0..1 range."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.INPUTS, self.tr("Criterion rasters (same grid, in weight order)"),
                layerType=QgsProcessing.TypeRaster,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.WEIGHTS, self.tr("Weights (comma-separated, one per raster)"),
                defaultValue="0.313,0.193,0.158,0.115,0.095,0.070,0.056",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.INVERT, self.tr("Invert flags (comma-separated 0/1, optional)"),
                defaultValue="0,1,1,0,1,1,0", optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(self.STRETCH, self.tr("Stretch result to full 0..1 range"),
                                          defaultValue=True)
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(self.OUTPUT, self.tr("Weighted overlay (0..1)"))
        )

    @staticmethod
    def _parse_list(text, n, name, cast):
        items = [s.strip() for s in (text or "").split(",") if s.strip() != ""]
        if not items:
            return None
        if len(items) != n:
            raise QgsProcessingException(f"{name}: expected {n} values, got {len(items)}")
        try:
            return [cast(s) for s in items]
        except ValueError as exc:
            raise QgsProcessingException(f"{name}: could not parse '{text}' ({exc})")

    @staticmethod
    def _normalise(arr, nodata, invert):
        data = arr.astype("float64")
        valid = np.isfinite(data)
        if nodata is not None:
            valid &= data != nodata
        if not valid.any():
            raise QgsProcessingException("A criterion raster has no valid cells")
        lo, hi = float(np.min(data[valid])), float(np.max(data[valid]))
        out = np.zeros_like(data) if hi - lo == 0 else (data - lo) / (hi - lo)
        if invert:
            out = 1.0 - out
        out[~valid] = np.nan
        return out

    def processAlgorithm(self, parameters, context, feedback):
        layers = self.parameterAsLayerList(parameters, self.INPUTS, context)
        if not layers:
            raise QgsProcessingException("Select at least one criterion raster")
        n = len(layers)

        weights = self._parse_list(self.parameterAsString(parameters, self.WEIGHTS, context), n, "Weights", float)
        if weights is None:
            weights = [1.0] * n
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise QgsProcessingException("Weights must be non-negative and not all zero")
        weights = [w / sum(weights) for w in weights]

        invert = self._parse_list(self.parameterAsString(parameters, self.INVERT, context), n, "Invert flags", int)
        if invert is None:
            invert = [0] * n
        stretch = self.parameterAsBool(parameters, self.STRETCH, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        ref = gdal.Open(layers[0].source())
        if ref is None:
            raise QgsProcessingException(f"Cannot open {layers[0].source()}")
        xsize, ysize = ref.RasterXSize, ref.RasterYSize
        total = np.zeros((ysize, xsize), dtype="float64")
        valid = np.ones((ysize, xsize), dtype=bool)

        for i, (layer, w, inv) in enumerate(zip(layers, weights, invert)):
            if feedback.isCanceled():
                break
            ds = gdal.Open(layer.source())
            if ds is None:
                raise QgsProcessingException(f"Cannot open {layer.source()}")
            if ds.RasterXSize != xsize or ds.RasterYSize != ysize:
                raise QgsProcessingException(
                    f"'{layer.name()}' is {ds.RasterXSize}x{ds.RasterYSize}, expected {xsize}x{ysize}. "
                    "Align the rasters first (e.g. GDAL > Warp)."
                )
            band = ds.GetRasterBand(1)
            arr = band.ReadAsArray()
            score = self._normalise(arr, band.GetNoDataValue(), bool(inv))
            valid &= ~np.isnan(score)
            total += w * np.nan_to_num(score)
            feedback.pushInfo(f"{layer.name()}: weight {w:.4f}, invert {bool(inv)}, "
                              f"mean score {np.nanmean(score):.3f}")
            feedback.setProgress(int((i + 1) / n * 90))
            ds = None

        if stretch and valid.any():
            lo, hi = float(total[valid].min()), float(total[valid].max())
            if hi - lo > 0:
                total = (total - lo) / (hi - lo)
        total = np.clip(total, 0.0, 1.0)
        nodata_value = -9999.0
        result = np.where(valid, total, nodata_value).astype("float32")

        drv = gdal.GetDriverByName("GTiff")
        out = drv.Create(out_path, xsize, ysize, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
        out.SetGeoTransform(ref.GetGeoTransform())
        out.SetProjection(ref.GetProjection())
        out_band = out.GetRasterBand(1)
        out_band.WriteArray(result)
        out_band.SetNoDataValue(nodata_value)
        out.FlushCache()
        out = None
        ref = None
        feedback.setProgress(100)
        return {self.OUTPUT: out_path}
