"""
QGIS Processing algorithm: Land Surface Temperature from Landsat 8/9 L2.

Implements the same single-channel method as ``src/lst_processor.py``:

    BT  = DN * 0.00341802 + 149.0                (Collection 2 Level-2 ST_B10)
    NDVI = (NIR - Red) / (NIR + Red)
    Pv  = ((NDVI - NDVI_soil) / (NDVI_veg - NDVI_soil)) ** 2
    eps = soil emissivity        where NDVI <  NDVI_soil
        = slope * Pv + offset    where NDVI_soil <= NDVI <= NDVI_veg
        = vegetation emissivity  where NDVI >  NDVI_veg
    LST = BT / (1 + (lambda * BT / rho) * ln(eps)) - 273.15   (deg C)

Install: Processing Toolbox > Scripts > Create New Script, paste this file,
save it, then run "Land Surface Temperature from Landsat 8/9 L2 (Portfolio)"
from the "Bhargav Portfolio" group.

Author: Bhargav Chintam, 2026, MIT License.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)
from osgeo import gdal
import numpy as np


class LandSurfaceTemperatureAlgorithm(QgsProcessingAlgorithm):
    THERMAL = "THERMAL"
    RED = "RED"
    NIR = "NIR"
    SCALE = "SCALE"
    OFFSET = "OFFSET"
    NDVI_SOIL = "NDVI_SOIL"
    NDVI_VEG = "NDVI_VEG"
    EMIS_SOIL = "EMIS_SOIL"
    EMIS_VEG = "EMIS_VEG"
    EMIS_SLOPE = "EMIS_SLOPE"
    EMIS_OFFSET = "EMIS_OFFSET"
    WAVELENGTH = "WAVELENGTH"
    OUTPUT = "OUTPUT"

    RHO = 1.438e-2  # h * c / sigma in m K

    def tr(self, text):
        return QCoreApplication.translate("Processing", text)

    def createInstance(self):
        return LandSurfaceTemperatureAlgorithm()

    def name(self):
        return "portfolio_uhi_lst"

    def displayName(self):
        return self.tr("Land Surface Temperature from Landsat 8/9 L2 (Portfolio)")

    def group(self):
        return self.tr("Bhargav Portfolio")

    def groupId(self):
        return "bhargav_portfolio"

    def shortHelpString(self):
        return self.tr(
            "Derives land surface temperature in degrees Celsius from a Landsat 8/9 "
            "Collection 2 Level-2 scene with the single-channel method and an NDVI based "
            "emissivity correction.\n\n"
            "Inputs: thermal band ST_B10 (scaled DN), red band SR_B4 and NIR band SR_B5 "
            "as reflectance (0 to 1, or scaled DN that give the same ratio). All three "
            "rasters must share the same grid.\n\n"
            "Emissivity constants follow Sobrino et al. (2004): 0.966 for bare soil and "
            "water (NDVI below the soil threshold), 0.973 for dense vegetation (NDVI above "
            "the vegetation threshold) and 0.004 * Pv + 0.986 for mixed pixels.\n\n"
            "Output: single band float32 GeoTIFF of LST in degrees Celsius, NaN where the "
            "thermal band is nodata or the result is outside -50 to 80 degrees C."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.THERMAL, self.tr("Thermal band (ST_B10)")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.RED, self.tr("Red band (SR_B4)")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.NIR, self.tr("NIR band (SR_B5)")))
        self.addParameter(QgsProcessingParameterNumber(
            self.SCALE, self.tr("Thermal scale factor (Kelvin per DN)"),
            QgsProcessingParameterNumber.Double, 0.00341802, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.OFFSET, self.tr("Thermal offset (Kelvin)"),
            QgsProcessingParameterNumber.Double, 149.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.NDVI_SOIL, self.tr("NDVI soil threshold"),
            QgsProcessingParameterNumber.Double, 0.2, minValue=-1.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.NDVI_VEG, self.tr("NDVI vegetation threshold"),
            QgsProcessingParameterNumber.Double, 0.5, minValue=-1.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EMIS_SOIL, self.tr("Emissivity of bare soil / water"),
            QgsProcessingParameterNumber.Double, 0.966, minValue=0.8, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EMIS_VEG, self.tr("Emissivity of dense vegetation"),
            QgsProcessingParameterNumber.Double, 0.973, minValue=0.8, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.EMIS_SLOPE, self.tr("Mixed pixel emissivity slope (per Pv)"),
            QgsProcessingParameterNumber.Double, 0.004))
        self.addParameter(QgsProcessingParameterNumber(
            self.EMIS_OFFSET, self.tr("Mixed pixel emissivity offset"),
            QgsProcessingParameterNumber.Double, 0.986, minValue=0.8, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.WAVELENGTH, self.tr("Thermal band wavelength (micrometres)"),
            QgsProcessingParameterNumber.Double, 10.895, minValue=8.0, maxValue=14.0))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, self.tr("Land surface temperature (deg C)")))

    def processAlgorithm(self, parameters, context, feedback):
        thermal_layer = self.parameterAsRasterLayer(parameters, self.THERMAL, context)
        red_layer = self.parameterAsRasterLayer(parameters, self.RED, context)
        nir_layer = self.parameterAsRasterLayer(parameters, self.NIR, context)
        if thermal_layer is None or red_layer is None or nir_layer is None:
            raise QgsProcessingException(self.tr("All three input rasters are required"))

        scale = self.parameterAsDouble(parameters, self.SCALE, context)
        offset = self.parameterAsDouble(parameters, self.OFFSET, context)
        ndvi_soil = self.parameterAsDouble(parameters, self.NDVI_SOIL, context)
        ndvi_veg = self.parameterAsDouble(parameters, self.NDVI_VEG, context)
        emis_soil = self.parameterAsDouble(parameters, self.EMIS_SOIL, context)
        emis_veg = self.parameterAsDouble(parameters, self.EMIS_VEG, context)
        emis_slope = self.parameterAsDouble(parameters, self.EMIS_SLOPE, context)
        emis_offset = self.parameterAsDouble(parameters, self.EMIS_OFFSET, context)
        wavelength_m = self.parameterAsDouble(parameters, self.WAVELENGTH, context) * 1e-6
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        if ndvi_veg <= ndvi_soil:
            raise QgsProcessingException(self.tr("NDVI vegetation threshold must be above the soil threshold"))

        feedback.pushInfo(self.tr("Reading input bands"))
        thermal, thermal_ds = self._read_band(thermal_layer)
        red, _ = self._read_band(red_layer)
        nir, _ = self._read_band(nir_layer)
        if thermal.shape != red.shape or thermal.shape != nir.shape:
            raise QgsProcessingException(self.tr(
                "Input rasters must have the same size. Resample them to a common grid first."))

        # Step 1: brightness temperature (K)
        feedback.setProgress(20)
        bt = thermal * scale + offset
        bt = np.where(np.isfinite(bt) & (bt > 150.0), bt, np.nan)

        # Step 2: NDVI
        feedback.setProgress(40)
        with np.errstate(divide="ignore", invalid="ignore"):
            denom = nir + red
            ndvi = np.where(denom == 0, np.nan, (nir - red) / denom)
        ndvi = np.clip(ndvi, -1.0, 1.0)

        # Step 3: proportion of vegetation and emissivity
        feedback.setProgress(60)
        pv = np.clip(((ndvi - ndvi_soil) / (ndvi_veg - ndvi_soil)) ** 2, 0.0, 1.0)
        pv = np.where(ndvi < ndvi_soil, 0.0, pv)
        pv = np.where(ndvi > ndvi_veg, 1.0, pv)

        emissivity = np.full(ndvi.shape, np.nan, dtype="float64")
        emissivity = np.where(ndvi < ndvi_soil, emis_soil, emissivity)
        mixed = (ndvi >= ndvi_soil) & (ndvi <= ndvi_veg)
        emissivity = np.where(mixed, emis_slope * pv + emis_offset, emissivity)
        emissivity = np.where(ndvi > ndvi_veg, emis_veg, emissivity)

        # Step 4: land surface temperature
        feedback.setProgress(80)
        with np.errstate(divide="ignore", invalid="ignore"):
            lst = bt / (1.0 + (wavelength_m * bt / self.RHO) * np.log(emissivity)) - 273.15
        lst = np.where((lst > -50.0) & (lst < 80.0), lst, np.nan).astype("float32")

        feedback.pushInfo(self.tr("Writing %s") % out_path)
        drv = gdal.GetDriverByName("GTiff")
        out = drv.Create(out_path, thermal_ds.RasterXSize, thermal_ds.RasterYSize, 1, gdal.GDT_Float32,
                         options=["COMPRESS=LZW"])
        out.SetGeoTransform(thermal_ds.GetGeoTransform())
        out.SetProjection(thermal_ds.GetProjection())
        band = out.GetRasterBand(1)
        band.WriteArray(lst)
        band.SetNoDataValue(float("nan"))
        out.FlushCache()
        out = None
        thermal_ds = None

        valid = lst[np.isfinite(lst)]
        if valid.size:
            feedback.pushInfo(self.tr("LST mean %.1f, min %.1f, max %.1f deg C")
                              % (float(valid.mean()), float(valid.min()), float(valid.max())))
        feedback.setProgress(100)
        return {self.OUTPUT: out_path}

    @staticmethod
    def _read_band(layer):
        """Read band 1 as float64 with nodata converted to NaN."""
        ds = gdal.Open(layer.source())
        if ds is None:
            raise QgsProcessingException("Could not open %s with GDAL" % layer.source())
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray().astype("float64")
        nodata = band.GetNoDataValue()
        if nodata is not None and not np.isnan(nodata):
            arr[arr == nodata] = np.nan
        return arr, ds
