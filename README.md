# Geospatial Analysis Portfolio (QGIS + Python)

[![CI](https://github.com/bhargavchintam/qgis-geospatial-projects/actions/workflows/ci.yml/badge.svg)](https://github.com/bhargavchintam/qgis-geospatial-projects/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-green.svg)](https://qgis.org/)
[![Portfolio site](https://img.shields.io/badge/Portfolio-site-orange.svg)](https://bhargavchintam.github.io/qgis-geospatial-projects/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Six end-to-end geospatial projects covering urban planning, hydrology, agriculture, public health, forestry and energy. Every project runs with one command on built-in synthetic data, ships a Streamlit app and an interactive web map, and includes QGIS style files plus a Processing Toolbox script so the same method can be run inside QGIS on real layers.

**Portfolio site:** https://bhargavchintam.github.io/qgis-geospatial-projects/

## Projects at a glance

| Project | Domain | Core methods | Demo result (seed 42) |
|---|---|---|---|
| [Urban Heat Island Analysis](urban-heat-island-analysis/) | Urban planning | Landsat 8/9 LST (single-channel), NDVI emissivity, UHI classes, LULC correlation, Mitigation Priority Index | Mean LST 43.2 C, max 55.4 C, LST vs impervious r = 0.82, 378 ha high-priority zones |
| [Flood Risk Assessment](flood-risk-assessment/) | Hydrology, emergency planning | Priority-flood DEM fill, D8 flow, TWI, 7-criteria AHP (CR 0.011), vulnerability, risk matrix, return-period scenarios | 7.0 % of area High or Very High risk, 10,202 people exposed, 3 of 25 facilities at risk |
| [Crop Health Monitoring](crop-health-ndvi-monitoring/) | Precision agriculture | Sentinel-2 time series, NDVI/EVI/SAVI/NDRE/NDWI, double-logistic phenology, z-score and Isolation Forest anomalies, field zonal stats | 14 scenes, peak NDVI 0.81 at DOY 207, 2.7 % stressed area in 7 clusters, all 4 N-stressed fields flagged by NDRE |
| [Healthcare Access Analysis](healthcare-access-analysis/) | Public health, network analysis | Road graph, multi-source Dijkstra, isochrones, two-step floating catchment (2SFCA), greedy maximal coverage siting | 89.3 % of residents within 15 min, 100 % after two proposed sites, 101,714 underserved people located |
| [Forest Change Detection](forest-change-detection/) | Forestry, environment | Random Forest land cover (OA 0.98, kappa 0.97), post-classification change, dNBR, MMU filtering, accuracy assessment | 44.8 ha loss (3.2 % of forest, 0.63 %/yr), 29 patches, 87 % within 500 m of roads |
| [Solar Site Suitability](solar-site-suitability/) | Energy, infrastructure | Terrain (slope, aspect, hillshade), criterion curves, AHP (CR 0.013), constraint masks, weighted overlay, site extraction and capacity | 10 candidate sites, 1,911 MW developable, best site 549 MW, 35 % of area excluded |

All numbers come straight from `python demo.py` in each folder. They are reproducible with the default seed.

## What each project looks like

<table>
<tr>
<td width="50%"><a href="urban-heat-island-analysis/"><img src="urban-heat-island-analysis/docs/figures/00_hero.png" alt="Urban heat island"></a><br><b>Urban Heat Island Analysis</b><br>Landsat thermal to land surface temperature, UHI intensity zones and a mitigation priority map for planners. <a href="https://bhargavchintam.github.io/qgis-geospatial-projects/urban-heat-island-analysis/docs/map.html">Interactive map</a></td>
<td width="50%"><a href="flood-risk-assessment/"><img src="flood-risk-assessment/docs/figures/00_hero.png" alt="Flood risk"></a><br><b>Flood Risk Assessment</b><br>DEM hydrology plus AHP multi-criteria hazard, socio-economic vulnerability and a composite risk index with 10 to 500 year scenarios. <a href="https://bhargavchintam.github.io/qgis-geospatial-projects/flood-risk-assessment/docs/map.html">Interactive map</a></td>
</tr>
<tr>
<td><a href="crop-health-ndvi-monitoring/"><img src="crop-health-ndvi-monitoring/docs/figures/00_hero.png" alt="Crop health"></a><br><b>Crop Health Monitoring</b><br>A full Sentinel-2 growing season: phenology curves, stress anomalies and per-field health reports. <a href="https://bhargavchintam.github.io/qgis-geospatial-projects/crop-health-ndvi-monitoring/docs/map.html">Interactive map</a></td>
<td><a href="healthcare-access-analysis/"><img src="healthcare-access-analysis/docs/figures/00_hero.png" alt="Healthcare access"></a><br><b>Healthcare Access Analysis</b><br>Drive-time isochrones, 2SFCA accessibility scores, underserved blocks and where to put the next hospital. <a href="https://bhargavchintam.github.io/qgis-geospatial-projects/healthcare-access-analysis/docs/map.html">Interactive map</a></td>
</tr>
<tr>
<td><a href="forest-change-detection/"><img src="forest-change-detection/docs/figures/00_hero.png" alt="Forest change"></a><br><b>Forest Change Detection</b><br>Two-date Sentinel-2 classification, forest loss mapping and a proper accuracy assessment. <a href="https://bhargavchintam.github.io/qgis-geospatial-projects/forest-change-detection/docs/map.html">Interactive map</a></td>
<td><a href="solar-site-suitability/"><img src="solar-site-suitability/docs/figures/00_hero.png" alt="Solar suitability"></a><br><b>Solar Site Suitability</b><br>AHP weighted overlay with hard constraints, ranked candidate parcels and MW / GWh estimates. <a href="https://bhargavchintam.github.io/qgis-geospatial-projects/solar-site-suitability/docs/map.html">Interactive map</a></td>
</tr>
</table>

## Run any project in under a minute

```bash
git clone https://github.com/bhargavchintam/qgis-geospatial-projects.git
cd qgis-geospatial-projects/flood-risk-assessment      # or any other project folder
pip install -r requirements.txt
python demo.py               # synthetic data -> full pipeline -> figures + web map, 2 to 10 s
streamlit run app.py         # interactive dashboard with sliders
python -m pytest tests -q    # unit and end-to-end tests
```

No downloads or accounts are needed. Each `demo.py` generates a realistic, georeferenced synthetic scene, runs the real pipeline code, and writes rasters, vectors, CSVs, figures and a Folium map. To use real data, edit the paths in that project's `config.yaml` (each README lists the public data sources).

## Use it inside QGIS

Every project has a `qgis/` folder with:

- `.qml` style files for the output layers (load via Layer Properties > Symbology > Style > Load Style)
- a `QgsProcessingAlgorithm` script that exposes the core method in the Processing Toolbox (Scripts > Create New Script > paste > Save)

So a QGIS user can run, for example, the AHP weighted overlay, the service-area isochrones or the Landsat LST formula on their own layers without leaving QGIS.

## Skills demonstrated

| Area | Where |
|---|---|
| Raster analysis | LST derivation, TWI, terrain derivatives, weighted overlays, zonal statistics, MMU filtering |
| Vector and network analysis | Road graphs, Dijkstra travel times, isochrone construction, 2SFCA, spatial joins, site selection |
| Remote sensing | Landsat 8/9 Collection 2, Sentinel-2 L2A, cloud masking (SCL), 10 m / 20 m resampling, vegetation and burn indices, phenology fitting |
| Machine learning | Random Forest classification, Isolation Forest and LOF anomaly detection, accuracy assessment (OA, kappa, producer's and user's accuracy) |
| Multi-criteria decision analysis | AHP pairwise matrices, consistency ratio, sensitivity analysis, constraint mapping |
| Engineering practice | Config-driven pipelines, synthetic data generators, pytest suites (158 tests), CI, Streamlit apps, Folium web maps, QGIS Processing scripts |

Stack: QGIS 3.28+ and PyQGIS, Python 3.10, GeoPandas, Rasterio, Shapely, NumPy, SciPy, scikit-learn, NetworkX, OSMnx, Matplotlib, Folium, Streamlit.

## Repository layout

```
qgis-geospatial-projects/
├── README.md                     this file
├── index.html                    portfolio landing page (GitHub Pages)
├── DEPLOYMENT.md                 how to publish Pages and the Streamlit apps
├── .github/workflows/ci.yml      runs every project's tests and demo
├── urban-heat-island-analysis/
├── flood-risk-assessment/
├── crop-health-ndvi-monitoring/
├── healthcare-access-analysis/
├── forest-change-detection/
└── solar-site-suitability/
    ├── README.md                 what it does, results, figures, method, real data
    ├── demo.py                   one-command runnable demo
    ├── app.py                    Streamlit dashboard
    ├── config.yaml               all parameters and data paths
    ├── src/                      pipeline modules + synthetic_data.py + visualize.py
    ├── qgis/                     .qml styles and a Processing algorithm
    ├── tests/                    pytest suite incl. end-to-end test
    └── docs/                     figures/*.png and map.html
```

## About me

Bhargav Chintam. Applied machine learning and data engineering background (about six years across genomics, clinical analytics, telecom and enterprise data), M.S. in Computer Science. I build these projects to apply that experience to spatial problems with open data and open tools.

GitHub: https://github.com/bhargavchintam

## License

MIT. See [LICENSE](LICENSE) and each project's own LICENSE file.
