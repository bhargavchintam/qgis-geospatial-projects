"""
QGIS Processing algorithm: NDVI and crop health classes from a red and a NIR band.

Install: Processing Toolbox > Scripts > Create New Script, paste this file,
save as crop_ndvi_health_algorithm.py. It then appears under
"Bhargav Portfolio > NDVI and Crop Health Classes (Portfolio)".

Inputs
    RED, NIR       single-band rasters on the same grid (Sentinel-2 B04 and B08,
                   uint16 DN or reflectance)
    SCALE          divide DN by this to get reflectance (10000 for Sentinel-2 L2A,
                   1 if the bands are already reflectance)
    T_EXCELLENT..T_POOR  NDVI thresholds for the classes
Outputs
    NDVI           float32 raster, NaN where the denominator is zero or nodata
    CLASSES        uint8 raster: 5 Excellent, 4 Good, 3 Moderate, 2 Poor,
                   1 Very Poor, 0 nodata (matches styles/field_health.qml labels)
"""

import numpy as np
from osgeo import gdal
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)
from qgis.PyQt.QtCore import QCoreApplication


class CropNdviHealthAlgorithm(QgsProcessingAlgorithm):
    RED = "RED"
    NIR = "NIR"
    SCALE = "SCALE"
    T_EXCELLENT = "T_EXCELLENT"
    T_GOOD = "T_GOOD"
    T_MODERATE = "T_MODERATE"
    T_POOR = "T_POOR"
    NDVI = "NDVI"
    CLASSES = "CLASSES"

    def tr(self, text):
        return QCoreApplication.translate("Processing", text)

    def createInstance(self):
        return CropNdviHealthAlgorithm()

    def name(self):
        return "portfolio_crop_ndvi_health"

    def displayName(self):
        return self.tr("NDVI and Crop Health Classes (Portfolio)")

    def group(self):
        return self.tr("Bhargav Portfolio")

    def groupId(self):
        return "bhargav_portfolio"

    def shortHelpString(self):
        return self.tr(
            "Computes NDVI = (NIR - Red) / (NIR + Red) from two single-band rasters on the "
            "same grid and classifies it into five crop health classes using NDVI thresholds. "
            "Inputs: red and NIR rasters (Sentinel-2 B04 and B08), a DN scale factor "
            "(10000 for L2A, 1 for reflectance) and four class thresholds. Outputs: an NDVI "
            "raster (float32) and a class raster (5 Excellent ... 1 Very Poor, 0 nodata). "
            "Style the class raster with styles/crop_anomaly.qml or a paletted renderer."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.RED, self.tr("Red band (B04)")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.NIR, self.tr("NIR band (B08)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.SCALE, self.tr("DN scale factor (10000 for Sentinel-2 L2A, 1 for reflectance)"),
            QgsProcessingParameterNumber.Double, 10000.0, minValue=1e-6))
        self.addParameter(QgsProcessingParameterNumber(
            self.T_EXCELLENT, self.tr("Excellent if NDVI >="), QgsProcessingParameterNumber.Double, 0.75))
        self.addParameter(QgsProcessingParameterNumber(
            self.T_GOOD, self.tr("Good if NDVI >="), QgsProcessingParameterNumber.Double, 0.55))
        self.addParameter(QgsProcessingParameterNumber(
            self.T_MODERATE, self.tr("Moderate if NDVI >="), QgsProcessingParameterNumber.Double, 0.35))
        self.addParameter(QgsProcessingParameterNumber(
            self.T_POOR, self.tr("Poor if NDVI >= (below is Very Poor)"), QgsProcessingParameterNumber.Double, 0.20))
        self.addParameter(QgsProcessingParameterRasterDestination(self.NDVI, self.tr("NDVI")))
        self.addParameter(QgsProcessingParameterRasterDestination(self.CLASSES, self.tr("Health classes")))

    def processAlgorithm(self, parameters, context, feedback):
        red_layer = self.parameterAsRasterLayer(parameters, self.RED, context)
        nir_layer = self.parameterAsRasterLayer(parameters, self.NIR, context)
        scale = self.parameterAsDouble(parameters, self.SCALE, context)
        thresholds = [
            self.parameterAsDouble(parameters, self.T_EXCELLENT, context),
            self.parameterAsDouble(parameters, self.T_GOOD, context),
            self.parameterAsDouble(parameters, self.T_MODERATE, context),
            self.parameterAsDouble(parameters, self.T_POOR, context),
        ]
        ndvi_path = self.parameterAsOutputLayer(parameters, self.NDVI, context)
        class_path = self.parameterAsOutputLayer(parameters, self.CLASSES, context)

        red_ds = gdal.Open(red_layer.source())
        nir_ds = gdal.Open(nir_layer.source())
        if red_ds is None or nir_ds is None:
            raise QgsProcessingException(self.tr("Could not open the input rasters with GDAL"))
        if (red_ds.RasterXSize, red_ds.RasterYSize) != (nir_ds.RasterXSize, nir_ds.RasterYSize):
            raise QgsProcessingException(self.tr("Red and NIR rasters must have the same size (resample first)"))

        red_band = red_ds.GetRasterBand(1)
        nir_band = nir_ds.GetRasterBand(1)
        red = red_band.ReadAsArray().astype("float64")
        nir = nir_band.ReadAsArray().astype("float64")
        nodata = np.zeros(red.shape, dtype=bool)
        for band, arr in ((red_band, red), (nir_band, nir)):
            nd = band.GetNoDataValue()
            if nd is not None:
                nodata |= arr == nd
        feedback.pushInfo(f"Read {red.shape[1]} x {red.shape[0]} pixels; scale factor {scale}")

        red = red / scale
        nir = nir / scale
        denom = nir + red
        with np.errstate(divide="ignore", invalid="ignore"):
            ndvi = np.where(np.abs(denom) > 1e-10, (nir - red) / denom, np.nan)
        ndvi = np.clip(ndvi, -1.0, 1.0)
        ndvi[nodata] = np.nan

        classes = np.zeros(ndvi.shape, dtype="uint8")
        valid = ~np.isnan(ndvi)
        classes[valid] = 1  # Very Poor
        classes[valid & (ndvi >= thresholds[3])] = 2  # Poor
        classes[valid & (ndvi >= thresholds[2])] = 3  # Moderate
        classes[valid & (ndvi >= thresholds[1])] = 4  # Good
        classes[valid & (ndvi >= thresholds[0])] = 5  # Excellent

        drv = gdal.GetDriverByName("GTiff")
        opts = ["COMPRESS=LZW"]
        out = drv.Create(ndvi_path, red_ds.RasterXSize, red_ds.RasterYSize, 1, gdal.GDT_Float32, opts)
        out.SetGeoTransform(red_ds.GetGeoTransform())
        out.SetProjection(red_ds.GetProjection())
        out.GetRasterBand(1).WriteArray(ndvi.astype("float32"))
        out.GetRasterBand(1).SetNoDataValue(float("nan"))
        out.FlushCache()
        out = None

        out = drv.Create(class_path, red_ds.RasterXSize, red_ds.RasterYSize, 1, gdal.GDT_Byte, opts)
        out.SetGeoTransform(red_ds.GetGeoTransform())
        out.SetProjection(red_ds.GetProjection())
        out.GetRasterBand(1).WriteArray(classes)
        out.GetRasterBand(1).SetNoDataValue(0)
        out.FlushCache()
        out = None

        counts = {name: int((classes == v).sum()) for name, v in
                  (("Excellent", 5), ("Good", 4), ("Moderate", 3), ("Poor", 2), ("Very Poor", 1))}
        feedback.pushInfo(f"Mean NDVI {np.nanmean(ndvi):.3f}; class pixel counts {counts}")
        return {self.NDVI: ndvi_path, self.CLASSES: class_path}
