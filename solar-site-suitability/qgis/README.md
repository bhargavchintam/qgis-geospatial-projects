# QGIS assets

Styles and a Processing script so the suitability workflow can be used inside QGIS 3.28 or newer.
Run `python demo.py` first; the layers referenced below are written to `results/demo/`.

## Styles (`styles/*.qml`)

| Style | Apply to | What it shows |
|---|---|---|
| `solar_suitability.qml` | `results/demo/suitability_index.tif` | Continuous 0 to 1 index, red (poor) to green (excellent), 0.75 marked as the site threshold |
| `suitability_classes.qml` | `results/demo/suitability_classes.tif` | Exact classes 1 Very Low, 2 Low, 3 Moderate, 4 High, 5 Very High (0 = excluded stays nodata) |
| `constraints.qml` | `results/demo/constraints_mask.tif` | 0 = excluded in grey, 1 = allowed transparent, so it can sit on top of any other layer |
| `candidate_sites.qml` | `results/demo/candidate_sites.gpkg` | Graduated fill on `capacity_mw` (5 classes) with the `rank` field drawn as a label |

How to load a style:

1. Add the layer to the project (drag the GeoTIFF or GeoPackage into QGIS).
2. Right click the layer, choose **Properties**, open the **Symbology** tab.
3. At the bottom click **Style**, then **Load Style...**, pick the `.qml` file and press **Load Style**, then **OK**.

The class raster has nodata 0, so excluded cells are transparent. Put `constraints.qml` on the
`constraints_mask.tif` layer above the index layer to grey them out instead.

## Processing script (`processing/solar_suitability_algorithm.py`)

The script adds **Bhargav Portfolio > Weighted Suitability Overlay with Constraints (Portfolio)** to the
Processing Toolbox. It does the core step of this project on any set of your own rasters: min-max
normalise each criterion, optionally invert cost criteria, multiply by weights, sum, and mask.

Install:

1. Open **Processing > Toolbox**.
2. Click the Python icon at the top of the toolbox and choose **Create New Script**.
3. Paste the whole content of `processing/solar_suitability_algorithm.py` into the editor.
4. **Save** it (QGIS puts it in its `processing/scripts` folder). It appears under *Scripts > Bhargav Portfolio*.

Run:

* **Criterion rasters**: pick the six `results/demo/criterion_*.tif` files (or your own rasters, all on the same grid).
* **Weights**: comma separated, same order as the layers, for example `0.37,0.18,0.06,0.20,0.09,0.10`.
  They are renormalised to sum to 1.
* **Invert flags**: optional, `1` for a layer where lower is better (raw slope or distance rasters).
  Not needed for the `criterion_*.tif` files because they are already 0 to 1 benefit scores.
* **Constraint raster**: optional, `results/demo/constraints_mask.tif` (0 = excluded).
* **Suitability index**: output GeoTIFF, float32, nodata -9999. Style it with `solar_suitability.qml`.

The script only needs GDAL and numpy, which ship with QGIS.
