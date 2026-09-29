# QGIS assets

Run `python demo.py` first so the layers exist in `results/demo/`.

## Layers to load (Layer > Add Layer > Add Vector Layer)

| Layer | File | Style |
|---|---|---|
| Roads by class | `results/demo/data/roads.gpkg` | `styles/roads_by_class.qml` |
| Hospitals | `results/demo/data/hospitals.gpkg` | `styles/hospitals.qml` |
| Drive-time isochrones | `results/demo/isochrones.gpkg` | `styles/isochrones.qml` |
| Blocks with 2SFCA access score | `results/demo/blocks_access.gpkg` | `styles/access_score_blocks.qml` |
| Proposed sites | `results/demo/proposed_sites.gpkg` | any marker style |

All layers are in EPSG:32611 (UTM zone 11N, metres).

## Load a style

1. Right-click the layer > Properties > Symbology.
2. At the bottom, Style > Load Style.
3. Pick the `.qml` file from `qgis/styles/` and click Load Style, then OK.

* `isochrones.qml`: categorized on `max_minutes` (5, 10, 15, 20, 30) with a YlOrRd ramp.
* `access_score_blocks.qml`: graduated fill on `access_score`, five quantile classes from the demo
  run (beds per 1,000 residents), viridis colours. Click Classify in the Symbology panel to
  recompute the class breaks for your own data.
* `hospitals.qml`: red cross marker with a white halo.
* `roads_by_class.qml`: line width and colour by `highway` class.

## Run the Processing script

`processing/service_area_algorithm.py` adds the algorithm
**Service Area from Road Lines (Portfolio)** to the Processing Toolbox.

1. Open Processing Toolbox (Processing > Toolbox).
2. Click the Python icon at the top of the toolbox > Scripts > Create New Script.
3. Paste the full content of `service_area_algorithm.py`, then Save (for example as
   `service_area_algorithm.py` in the default scripts folder).
4. The tool appears under Scripts > Bhargav Portfolio. Double-click to run.

Inputs:

| Parameter | Meaning |
|---|---|
| Road lines | any line layer in a projected CRS (metres); the demo `roads.gpkg` works as-is |
| Facility points | hospitals (or any point layer); reprojected to the road CRS automatically |
| Speed field | optional numeric field in km/h (`speed_kph` in the demo) |
| Default speed | used when the field is empty or missing |
| Cutoff | travel time in minutes |
| Buffer | width around reached roads before dissolving (map units) |

The script snaps line endpoints to a 0.5 m grid to build graph nodes, runs a multi-source
Dijkstra with `heapq` (no networkx needed inside QGIS), cuts partly reached segments at the time
budget, buffers them and dissolves the result into one polygon with `cutoff_min`,
`n_facilities`, `n_segments` and `area_km2` attributes. Run it several times with different
cutoffs to build bands.

Note: the Python pipeline adds a junction delay per segment (see `config.yaml`), the QGIS script
uses free-flow speeds only, so its service areas are a little larger.
