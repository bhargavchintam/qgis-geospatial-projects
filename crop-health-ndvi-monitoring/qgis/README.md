# QGIS assets for the crop health project

Everything here is plain QGIS 3.x (tested layout: 3.28). No plugin needed.

## Styles (`styles/`)

| File | Apply to | What it shows |
|------|----------|---------------|
| `ndvi.qml` | any NDVI raster, e.g. `results/demo/rasters/ndvi_20240920.tif` or `peak_ndvi.tif` | single-band pseudocolor, RdYlGn ramp from -0.2 (water, shadow) to 0.9 (peak canopy) |
| `crop_anomaly.qml` | `results/demo/rasters/anomaly_map.tif` | exact classes: 0 normal (almost transparent), 1 anomaly (red); 255 is nodata |
| `field_health.qml` | `results/demo/fields_assessment.geojson` (or any polygon layer with a `health_class` field) | categorized fill: Excellent, Good, Moderate, Poor, Very Poor, No Data |

How to load a style:

1. Add the layer to QGIS (drag the file into the map, or Layer > Add Layer).
2. Right-click the layer > Properties > Symbology.
3. At the bottom click Style > Load Style, pick the `.qml` file, click Load Style, then OK.

The NDVI ramp is fixed to -0.2 to 0.9 so every date looks the same. If your raster is DN scaled
(0 to 10000) run the Processing script below first, or set a scale in the raster properties.

## Processing script (`processing/crop_ndvi_health_algorithm.py`)

The script exposes the core step of the pipeline (NDVI plus five health classes) so it can run on
your own Sentinel-2 bands from the Processing Toolbox.

Install once:

1. Open Processing > Toolbox (Ctrl+Alt+T).
2. Click the Python icon at the top of the toolbox > Scripts > Create New Script.
3. Paste the whole content of `crop_ndvi_health_algorithm.py` into the editor.
4. Save it as `crop_ndvi_health_algorithm.py` in the folder QGIS proposes (its `processing/scripts` folder).
5. It now shows up in the toolbox under Scripts > Bhargav Portfolio > NDVI and Crop Health Classes (Portfolio).

Run it:

- Red band: Sentinel-2 `B04` (10 m). NIR band: `B08` (10 m). Both must share the same grid.
- DN scale factor: 10000 for Level-2A DN files, 1 if your bands are already reflectance.
- Class thresholds default to the values in `config.yaml` (0.75 / 0.55 / 0.35 / 0.20).
- Outputs: an NDVI raster (float32, load `styles/ndvi.qml`) and a class raster
  (uint8: 5 Excellent, 4 Good, 3 Moderate, 2 Poor, 1 Very Poor, 0 nodata).

For the class raster, Symbology > Paletted/Unique values > Classify gives a quick legend; the colours
used in the project are dark green, lime, gold, dark orange and crimson (see `field_health.qml`).

## Loading the demo outputs

After `python demo.py` the folder `results/demo/` contains:

- `data/sentinel2/S2A_MSIL2A_<date>T170000_demo/B02.tif ... B12.tif, SCL.tif` (uint16 DN, 10 m and 20 m)
- `rasters/ndvi_<date>.tif`, `peak_ndvi.tif`, `peak_doy.tif`, `season_length_days.tif`,
  `ndvi_expected_baseline.tif`, `anomaly_map.tif`
- `fields_assessment.geojson` with per-field NDVI, NDRE, health class, anomaly percent and phenology metrics

All layers are in EPSG:32615 (UTM zone 15N) and line up directly.
