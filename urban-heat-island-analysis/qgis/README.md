# QGIS assets for the Urban Heat Island project

This folder holds hand-written QGIS 3.x layer styles and one Processing
script, so the pipeline outputs (or your own Landsat scene) can be used
straight inside QGIS.

## Styles (`styles/`)

| File | Apply to | What it shows |
|------|----------|---------------|
| `lst_celsius.qml` | `results/demo/rasters/lst_celsius.tif` (or any LST raster in deg C) | Single-band pseudocolor, blue to red, 20 to 60 deg C, labels every 5 deg C |
| `uhi_classified.qml` | `results/demo/rasters/uhi_classified.tif` | Exact classes 0 to 5: Cool Island, Neutral, Mild, Moderate, Strong, Extreme (nodata -1 transparent) |
| `mitigation_priority_zones.qml` | `results/demo/vectors/mitigation_priority_zones.gpkg` | Categorized fill on `priority_label`: High (red), Medium (orange), Low (pale yellow) |

To load a style:

1. Add the raster or vector layer to the map (drag the file into QGIS).
2. Right click the layer, choose **Properties**, then **Symbology**.
3. At the bottom click **Style**, then **Load Style...**.
4. Pick the matching `.qml` file from `qgis/styles/` and click **Load Style**, then **OK**.

The same colours are used by the figures in `docs/figures/` and by the
Folium map in `docs/map.html`, so QGIS output matches the report.

## Processing script (`processing/uhi_lst_algorithm.py`)

Algorithm name: **Land Surface Temperature from Landsat 8/9 L2 (Portfolio)**,
group **Bhargav Portfolio**. It is the same single-channel LST method as
`src/lst_processor.py`, written against GDAL and numpy so it runs inside
the QGIS Python environment without extra packages.

Inputs:

* Thermal band `ST_B10` (Collection 2 Level-2, scaled DN)
* Red band `SR_B4` and NIR band `SR_B5` (reflectance 0 to 1)
* Thermal scale (0.00341802) and offset (149.0)
* NDVI soil (0.2) and vegetation (0.5) thresholds
* Emissivity constants: soil 0.966, vegetation 0.973, mixed pixel slope 0.004 and offset 0.986
* Band wavelength 10.895 micrometres

Output: a float32 GeoTIFF of land surface temperature in degrees Celsius
(NaN where the thermal band is nodata). Load `styles/lst_celsius.qml` on it.

To install and run it:

1. Open the **Processing Toolbox** (menu Processing > Toolbox).
2. Click the Python icon at the top of the toolbox, choose **Scripts > Create New Script...**.
3. Paste the whole content of `processing/uhi_lst_algorithm.py` into the editor.
4. Save it (for example as `uhi_lst_algorithm.py` in the default scripts folder). It appears
   under **Scripts > Bhargav Portfolio**.
5. Double click the algorithm, choose the three bands, keep the defaults, set an output
   file and click **Run**.

All three input rasters must share the same grid. If they do not, run
**Raster > Align Rasters** (or GDAL Warp) first. The synthetic bands written
by `python demo.py` into `results/demo/data/` are ready to use for a test.

## Tested with

Hand-validated as XML and compiled with `python -m py_compile`; the styles
follow the QGIS 3.28 QML schema. The Processing script could not be executed
outside QGIS, so please report any issue you meet in QGIS itself.
