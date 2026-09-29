# QGIS assets for Forest Change Detection

Everything here is plain QGIS 3.x (tested layout for 3.28+). No plugin is needed.

## 1. Load the demo outputs

Run `python demo.py` first. Then in QGIS use **Layer > Add Layer > Add Raster Layer** for:

| File (results/demo/) | Content | Style to load |
|---|---|---|
| `class_t1.tif`, `class_t2.tif` | Random Forest land cover, values 1..5 (0 = no data / cloud) | `styles/landcover_classes.qml` |
| `change.tif` | 1 stable forest, 2 stable non-forest, 3 loss, 4 gain (0 = no data) | `styles/forest_change.qml` |
| `dnbr.tif` | dNBR = NBR(T1) - NBR(T2), nodata -9999 | `styles/dnbr.qml` |
| `forest_loss_patches.gpkg` | loss polygons with `patch_id`, `area_ha`, `dist_road_m` | `styles/loss_patches.qml` |
| `data/t1_stack.tif`, `data/t2_stack.tif` | 6-band reflectance (B02, B03, B04, B08, B11, B12) | Multiband colour: R = band 4, G = band 3, B = band 2 for false colour |
| `data/roads.gpkg`, `data/river.gpkg` | vector lines | any line style |

All layers are in **EPSG:32720 (WGS 84 / UTM zone 20S)**.

## 2. Apply a style (.qml)

1. Right-click the layer > **Properties**.
2. Open the **Symbology** tab.
3. Bottom-left button **Style > Load Style...**
4. Pick the matching file from `qgis/styles/` and click **OK** / **Apply**.

Notes:

* `landcover_classes.qml` and `forest_change.qml` use exact class values, so they also work on
  your own class rasters as long as the codes are the same (1..5 and 1..4).
* `dnbr.qml` uses the USGS burn-severity style breaks: -0.5 (regrowth) to 0.8 (high severity),
  with 0.27 marked as the loss threshold used in this project.
* `loss_patches.qml` is a graduated fill on the `area_ha` field with 4 classes (0-1, 1-2.5, 2.5-5, > 5 ha).
  Use **Classify** in the Symbology tab if you want different breaks.

## 3. Run the Processing script

`processing/forest_loss_algorithm.py` is a `QgsProcessingAlgorithm` called
**"Forest Loss from Two Classified Rasters (Portfolio)"**. It does the post-classification comparison
and the minimum mapping unit filter on any two class rasters that share a grid.

1. Open the **Processing Toolbox** (Ctrl+Alt+T).
2. Click the Python icon at the top of the toolbox > **Scripts > Create New Script...**
3. Paste the full content of `processing/forest_loss_algorithm.py`.
4. **Save** it (for example as `forest_loss_algorithm.py` in the default scripts folder). It appears under
   **Scripts > Bhargav Portfolio**.
5. Double-click it, set:
   * Class raster T1 (earlier date), Class raster T2 (later date), same size and grid
   * Forest class value (1 for this project)
   * Minimum mapping unit in pixels (13 = 0.5 ha at 20 m; use 50 for 0.5 ha at 10 m)
6. Run. Load `styles/forest_change.qml` on the output.

The script uses `scipy.ndimage.label` for the connected components when scipy is present in the QGIS
Python. If scipy is missing it falls back to a pure numpy/python two-pass labelling (slower on large
rasters, same result).

If your two class rasters are on different grids, align them first with
**Raster > Align Rasters...** or **GDAL > Raster projections > Warp (reproject)** with the same extent
and resolution, using nearest-neighbour resampling so class codes are not mixed.
