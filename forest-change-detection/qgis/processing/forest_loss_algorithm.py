# -*- coding: utf-8 -*-
"""
Forest Loss from Two Classified Rasters (Portfolio)

QGIS Processing script by Bhargav Chintam.

Compares two land-cover class rasters (same grid) and writes a change raster:

    0  no data (nodata / 0 in either input)
    1  stable forest
    2  stable non-forest
    3  forest loss   (forest at T1, non-forest at T2)
    4  forest gain   (non-forest at T1, forest at T2)

Loss and gain patches smaller than the minimum mapping unit (in pixels) are
removed with 8-connected component labelling. scipy.ndimage.label is used
when available; otherwise a pure numpy/python two-pass labelling is used.

Install: Processing Toolbox > Scripts > Create New Script, paste this file,
save it, then run "Forest Loss from Two Classified Rasters (Portfolio)".
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterDestination)
from osgeo import gdal
import numpy as np

try:  # scipy ships with most QGIS builds but is not guaranteed
    from scipy import ndimage as _ndimage
except ImportError:  # pragma: no cover
    _ndimage = None


# --------------------------------------------------------------------------- labelling
def _label_two_pass(mask):
    """
    Two-pass 8-connected component labelling in pure numpy/python.

    Pass 1 walks the rows, assigns provisional labels to runs of True pixels
    and records equivalences with a union-find table. Pass 2 resolves the
    equivalences. Returns (labels int32 array, number of components).
    """
    rows, cols = mask.shape
    labels = np.zeros((rows, cols), dtype=np.int32)
    parent = [0]  # parent[0] unused

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    prev_runs = []  # list of (start, end_exclusive, label) for the previous row
    for r in range(rows):
        row = mask[r]
        runs = []
        c = 0
        while c < cols:
            if row[c]:
                start = c
                while c < cols and row[c]:
                    c += 1
                runs.append([start, c, 0])
            else:
                c += 1
        for run in runs:
            s, e = run[0], run[1]
            lab = 0
            for ps, pe, plab in prev_runs:
                # 8-connectivity: runs touch if they overlap when widened by one pixel
                if ps < e + 1 and pe + 1 > s:
                    if lab == 0:
                        lab = plab
                    else:
                        union(lab, plab)
            if lab == 0:
                parent.append(len(parent))
                lab = len(parent) - 1
            run[2] = lab
            labels[r, s:e] = lab
        prev_runs = [(s, e, lab) for s, e, lab in runs]

    # pass 2: resolve equivalences and renumber 1..n
    if len(parent) > 1:
        roots = np.array([find(i) for i in range(len(parent))], dtype=np.int64)
        unique_roots, renum = np.unique(roots[1:], return_inverse=True)
        lookup = np.zeros(len(parent), dtype=np.int32)
        lookup[1:] = renum + 1
        labels = lookup[labels]
        return labels, int(len(unique_roots))
    return labels, 0


def label_components(mask):
    """8-connected labelling with scipy when available, else the two-pass fallback."""
    mask = np.asarray(mask, dtype=bool)
    if _ndimage is not None:
        labels, n = _ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
        return labels.astype(np.int32), int(n)
    return _label_two_pass(mask)


def remove_small_patches(mask, min_pixels):
    """Drop connected patches with fewer than ``min_pixels`` pixels."""
    mask = np.asarray(mask, dtype=bool)
    if min_pixels <= 1 or not mask.any():
        return mask
    labels, n = label_components(mask)
    if n == 0:
        return mask
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = sizes >= int(min_pixels)
    return keep[labels]


def compute_change(class_t1, class_t2, forest_class, min_pixels):
    """Change codes 0..4 from two class arrays (0 = nodata) with MMU filtering."""
    valid = (class_t1 > 0) & (class_t2 > 0)
    f1 = class_t1 == forest_class
    f2 = class_t2 == forest_class
    change = np.zeros(class_t1.shape, dtype=np.uint8)
    change[valid & f1 & f2] = 1
    change[valid & ~f1 & ~f2] = 2
    loss = valid & f1 & ~f2
    gain = valid & ~f1 & f2
    loss_kept = remove_small_patches(loss, min_pixels)
    gain_kept = remove_small_patches(gain, min_pixels)
    change[loss & ~loss_kept] = 1  # unconfirmed loss stays forest (conservative)
    change[gain & ~gain_kept] = 2
    change[loss_kept] = 3
    change[gain_kept] = 4
    return change


# --------------------------------------------------------------------------- algorithm
class ForestLossAlgorithm(QgsProcessingAlgorithm):
    CLASS_T1 = "CLASS_T1"
    CLASS_T2 = "CLASS_T2"
    FOREST_CLASS = "FOREST_CLASS"
    MMU_PIXELS = "MMU_PIXELS"
    OUTPUT = "OUTPUT"

    def tr(self, text):
        return QCoreApplication.translate("Processing", text)

    def createInstance(self):
        return ForestLossAlgorithm()

    def name(self):
        return "portfolio_forest_loss"

    def displayName(self):
        return self.tr("Forest Loss from Two Classified Rasters (Portfolio)")

    def group(self):
        return self.tr("Bhargav Portfolio")

    def groupId(self):
        return "bhargav_portfolio"

    def shortHelpString(self):
        return self.tr(
            "Post-classification forest change from two land-cover class rasters on the same grid.\n\n"
            "Inputs: class raster T1, class raster T2, the pixel value of the forest class, and a minimum "
            "mapping unit in pixels (patches of loss or gain smaller than this are dropped, 8-connected).\n\n"
            "Output: Byte raster with 0 no data, 1 stable forest, 2 stable non-forest, 3 forest loss, "
            "4 forest gain. Load qgis/styles/forest_change.qml to style it.\n\n"
            "Pixels that are 0 or nodata in either input are written as 0."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.CLASS_T1, self.tr("Class raster T1 (earlier date)")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.CLASS_T2, self.tr("Class raster T2 (later date)")))
        self.addParameter(QgsProcessingParameterNumber(self.FOREST_CLASS, self.tr("Forest class value"),
                                                       QgsProcessingParameterNumber.Integer, 1, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.MMU_PIXELS, self.tr("Minimum mapping unit (pixels)"),
                                                       QgsProcessingParameterNumber.Integer, 13, minValue=1))
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT, self.tr("Forest change raster")))

    def processAlgorithm(self, parameters, context, feedback):
        layer_t1 = self.parameterAsRasterLayer(parameters, self.CLASS_T1, context)
        layer_t2 = self.parameterAsRasterLayer(parameters, self.CLASS_T2, context)
        forest_class = self.parameterAsInt(parameters, self.FOREST_CLASS, context)
        mmu = self.parameterAsInt(parameters, self.MMU_PIXELS, context)
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        if layer_t1 is None or layer_t2 is None:
            raise QgsProcessingException(self.tr("Both class rasters are required."))

        ds1 = gdal.Open(layer_t1.source())
        ds2 = gdal.Open(layer_t2.source())
        if ds1 is None or ds2 is None:
            raise QgsProcessingException(self.tr("Could not open an input raster with GDAL."))
        if (ds1.RasterXSize, ds1.RasterYSize) != (ds2.RasterXSize, ds2.RasterYSize):
            raise QgsProcessingException(self.tr(
                "The two rasters must have the same size. Resample one of them to the other grid first "
                "(Raster > Projections > Warp, or GDAL Align rasters)."))

        band1 = ds1.GetRasterBand(1)
        band2 = ds2.GetRasterBand(1)
        c1 = band1.ReadAsArray().astype(np.int64)
        c2 = band2.ReadAsArray().astype(np.int64)
        nd1 = band1.GetNoDataValue()
        nd2 = band2.GetNoDataValue()
        if nd1 is not None:
            c1[c1 == nd1] = 0
        if nd2 is not None:
            c2[c2 == nd2] = 0
        c1[c1 < 0] = 0
        c2[c2 < 0] = 0

        feedback.pushInfo(self.tr("Comparing classes (forest = {})...").format(forest_class))
        if _ndimage is None:
            feedback.pushInfo(self.tr("scipy not found: using the pure numpy two-pass labelling (slower)."))
        change = compute_change(c1, c2, forest_class, mmu)
        if feedback.isCanceled():
            return {}

        px_area = abs(ds1.GetGeoTransform()[1] * ds1.GetGeoTransform()[5])
        loss_ha = float((change == 3).sum()) * px_area / 10000.0
        gain_ha = float((change == 4).sum()) * px_area / 10000.0
        feedback.pushInfo(self.tr("Forest loss: {:.2f} ha, forest gain: {:.2f} ha (MMU {} px)").format(
            loss_ha, gain_ha, mmu))

        drv = gdal.GetDriverByName("GTiff")
        out = drv.Create(out_path, ds1.RasterXSize, ds1.RasterYSize, 1, gdal.GDT_Byte,
                         options=["COMPRESS=LZW"])
        out.SetGeoTransform(ds1.GetGeoTransform())
        out.SetProjection(ds1.GetProjection())
        ob = out.GetRasterBand(1)
        ob.WriteArray(change)
        ob.SetNoDataValue(0)
        ob.SetCategoryNames(["No data", "Stable forest", "Stable non-forest", "Forest loss", "Forest gain"])
        out.FlushCache()
        out = None
        ds1 = None
        ds2 = None
        return {self.OUTPUT: out_path}
