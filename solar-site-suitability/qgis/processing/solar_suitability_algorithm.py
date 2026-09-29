"""
Weighted Suitability Overlay with Constraints (Portfolio)

QGIS Processing script. Paste into Processing Toolbox > Scripts >
"Create New Script", save, then run it from the toolbox.

Inputs
    RASTERS     : one or more criterion rasters on the same grid
                  (e.g. GHI, slope, distance to grid). Each one is min-max
                  normalised to 0..1 before weighting.
    WEIGHTS     : comma separated weights, same order as the layers
                  (e.g. "0.37,0.18,0.06,0.20,0.09,0.10"). They are
                  renormalised to sum to 1.
    INVERT      : optional comma separated 0/1 flags, 1 = "lower is better"
                  (e.g. slope, distance) so the layer is inverted after
                  normalisation. Defaults to all 0.
    CONSTRAINT  : optional raster where 0 = excluded; excluded cells get
                  nodata in the output.
Output
    OUTPUT      : float32 GeoTIFF suitability index (0..1, nodata -9999).

Author: Bhargav Chintam, MIT License.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingParameterMultipleLayers, QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterString, QgsProcessingParameterRasterDestination)
from osgeo import gdal
import numpy as np


class WeightedSuitabilityOverlayAlgorithm(QgsProcessingAlgorithm):
    RASTERS = "RASTERS"
    WEIGHTS = "WEIGHTS"
    INVERT = "INVERT"
    CONSTRAINT = "CONSTRAINT"
    OUTPUT = "OUTPUT"
    NODATA = -9999.0

    def tr(self, text):
        return QCoreApplication.translate("Processing", text)

    def createInstance(self):
        return WeightedSuitabilityOverlayAlgorithm()

    def name(self):
        return "portfolio_weighted_suitability_overlay"

    def displayName(self):
        return self.tr("Weighted Suitability Overlay with Constraints (Portfolio)")

    def group(self):
        return self.tr("Bhargav Portfolio")

    def groupId(self):
        return "bhargav_portfolio"

    def shortHelpString(self):
        return self.tr(
            "Min-max normalises each input raster to 0..1, optionally inverts cost criteria "
            "(1 = lower is better), multiplies by the given weights (renormalised to sum to 1) "
            "and sums them into a suitability index. Cells where the optional constraint raster "
            "is 0 become nodata. All rasters must share the same grid (rows, columns, extent)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.RASTERS, self.tr("Criterion rasters (same grid)"), layerType=QgsProcessing.TypeRaster))
        self.addParameter(QgsProcessingParameterString(
            self.WEIGHTS, self.tr("Weights, comma separated, same order as the layers"),
            defaultValue="0.37,0.18,0.06,0.20,0.09,0.10"))
        self.addParameter(QgsProcessingParameterString(
            self.INVERT, self.tr("Invert flags (0/1 per layer, 1 = lower is better), optional"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.CONSTRAINT, self.tr("Constraint raster (0 = excluded), optional"), optional=True))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Suitability index")))

    @staticmethod
    def _parse_numbers(text, n, name, default):
        text = (text or "").strip()
        if not text:
            return [default] * n
        try:
            values = [float(v) for v in text.replace(";", ",").split(",") if v.strip() != ""]
        except ValueError:
            raise QgsProcessingException(f"{name} must be a comma separated list of numbers")
        if len(values) != n:
            raise QgsProcessingException(f"{name} has {len(values)} values but {n} rasters were given")
        return values

    @staticmethod
    def _read(layer):
        ds = gdal.Open(layer.source())
        if ds is None:
            raise QgsProcessingException(f"Cannot open {layer.source()}")
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray().astype("float64")
        nodata = band.GetNoDataValue()
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr, ds

    def processAlgorithm(self, parameters, context, feedback):
        layers = self.parameterAsLayerList(parameters, self.RASTERS, context)
        if not layers:
            raise QgsProcessingException("At least one criterion raster is required")
        weights = self._parse_numbers(self.parameterAsString(parameters, self.WEIGHTS, context),
                                      len(layers), "Weights", 1.0)
        invert = self._parse_numbers(self.parameterAsString(parameters, self.INVERT, context),
                                     len(layers), "Invert flags", 0.0)
        total = float(sum(weights))
        if total <= 0:
            raise QgsProcessingException("Weights must sum to a positive number")
        weights = [w / total for w in weights]
        constraint_layer = self.parameterAsRasterLayer(parameters, self.CONSTRAINT, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        index = None
        ref_ds = None
        valid = None
        for i, (layer, w, inv) in enumerate(zip(layers, weights, invert)):
            if feedback.isCanceled():
                break
            arr, ds = self._read(layer)
            if index is None:
                ref_ds = ds
                index = np.zeros(arr.shape, dtype="float64")
                valid = np.ones(arr.shape, dtype=bool)
            elif arr.shape != index.shape:
                raise QgsProcessingException(
                    f"Raster {layer.name()} has shape {arr.shape}, expected {index.shape}")
            lo, hi = np.nanmin(arr), np.nanmax(arr)
            score = np.zeros_like(arr) if hi - lo == 0 else (arr - lo) / (hi - lo)
            if inv >= 0.5:
                score = 1.0 - score
            valid &= ~np.isnan(arr)
            index += w * np.nan_to_num(score, nan=0.0)
            feedback.pushInfo(f"{layer.name()}: weight {w:.3f}, range {lo:.3f} to {hi:.3f}, invert {int(inv)}")
            feedback.setProgress(int(100 * (i + 1) / (len(layers) + 1)))

        index = np.clip(index, 0.0, 1.0)
        if constraint_layer is not None:
            mask, _ = self._read(constraint_layer)
            if mask.shape != index.shape:
                raise QgsProcessingException("Constraint raster must be on the same grid as the criteria")
            valid &= np.nan_to_num(mask, nan=0.0) != 0
            feedback.pushInfo(f"Constraint applied: {100.0 * (~valid).mean():.1f}% of cells excluded")
        result = np.where(valid, index, self.NODATA).astype("float32")

        drv = gdal.GetDriverByName("GTiff")
        out = drv.Create(out_path, ref_ds.RasterXSize, ref_ds.RasterYSize, 1, gdal.GDT_Float32,
                         options=["COMPRESS=LZW"])
        out.SetGeoTransform(ref_ds.GetGeoTransform())
        out.SetProjection(ref_ds.GetProjection())
        band = out.GetRasterBand(1)
        band.SetNoDataValue(self.NODATA)
        band.WriteArray(result)
        out.FlushCache()
        out = None
        feedback.setProgress(100)
        return {self.OUTPUT: out_path}
