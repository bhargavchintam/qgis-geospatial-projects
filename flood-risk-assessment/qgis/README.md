# QGIS assets for the flood risk project

This folder has ready-to-use layer styles and one Processing script so the
core step (AHP weighted overlay) can run inside QGIS on your own layers.

## 1. Load the demo outputs

Run `python demo.py` first. Then in QGIS use Layer > Add Layer:

| Output file | Type | Style to load |
|---|---|---|
| `results/demo/rasters/flood_risk.tif` | raster (0..1) | `styles/flood_risk_index.qml` |
| `results/demo/rasters/twi.tif` | raster | `styles/twi.qml` |
| `results/demo/vectors/flood_risk_zones.gpkg` | polygons | `styles/flood_risk_zones.qml` |
| `results/demo/data/critical_infrastructure.gpkg` | points | `styles/critical_infrastructure.qml` |
| `results/demo/vectors/streams.gpkg` | lines | default line style (set blue) |

## 2. Load a style (.qml)

1. Right-click the layer > Properties > Symbology.
2. At the bottom click Style > Load Style.
3. Pick the `.qml` file from `qgis/styles/` and press Load Style, then OK.

`flood_risk_index.qml` is a single-band pseudocolor ramp from blue (0, very
low) to red (1, very high). `twi.qml` is a viridis ramp for TWI 6 to 18.
`flood_risk_zones.qml` is categorized on `risk_label` (Very Low to Very
High, blue to red). `critical_infrastructure.qml` is categorized on `type`
with one marker per facility type.

## 3. Install and run the Processing script

1. Open Processing > Toolbox.
2. Click the Python icon at the top of the toolbox > Scripts > Create New Script.
3. Paste the content of `processing/flood_weighted_overlay_algorithm.py`.
4. Save it (File > Save As) as `flood_weighted_overlay_algorithm.py` in the
   folder QGIS suggests (its `processing/scripts` profile folder).
5. The tool appears under Scripts > Bhargav Portfolio > AHP Weighted Overlay (Portfolio).

Inputs:

- Criterion rasters: pick the layers in the same order as the weights. They
  must share one grid (same size and extent). Use GDAL > Warp (reproject)
  or Raster > Align Rasters first if they do not.
- Weights: comma-separated, one per raster. The default is the AHP vector
  from `config.yaml` (TWI 0.313, slope 0.193, distance to river 0.158,
  rainfall 0.115, elevation 0.095, Ksat 0.070, land cover 0.056).
- Invert flags: `1` where a high input value means low susceptibility
  (slope, elevation, distance to river, Ksat). Default `0,1,1,0,1,1,0`.
- Stretch result: rescale the weighted sum to use the full 0..1 range.

Output: a Float32 GeoTIFF in 0..1. Load `styles/flood_risk_index.qml` on
it to see the same colour ramp as the Python figures.

## 4. Reproduce the full chain in QGIS (optional)

The Python pipeline can be mirrored with core tools: SAGA "Fill Sinks
(Wang & Liu)" or GRASS `r.fill.dir`, GRASS `r.watershed` for flow
accumulation and TWI, `r.stream.extract` or Raster Calculator for streams,
GDAL Proximity for distance to streams, Reclassify by Table for the score
tables in `config.yaml`, then this weighted overlay script.
