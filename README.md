# 🌍 QGIS Geospatial Projects

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-green.svg)](https://qgis.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A collection of three geospatial analysis projects built with **QGIS**, **Python**, and open-source remote sensing data. Each project tackles a real-world environmental or urban planning problem using satellite imagery, GIS processing pipelines, and multi-criteria decision analysis.

## Projects

### 🌾 [Crop Health NDVI Monitoring](crop-health-ndvi-monitoring/)

Precision agriculture toolkit that monitors crop health across growing seasons using **Sentinel-2** satellite imagery at 10m resolution.

| | |
|---|---|
| **Satellite Data** | Sentinel-2 Level-2A (multispectral) |
| **Indices** | NDVI, EVI, SAVI, NDRE, NDWI |
| **Techniques** | Time series phenology analysis, anomaly detection (Z-score, Isolation Forest, LOF), zonal statistics |
| **Study Area** | Iowa Corn Belt — 342 parcels, 12,450 ha |
| **Key Result** | 8.3% anomalous area detected; dominant stress: moisture deficit |

---

### 🌊 [Flood Risk Assessment](flood-risk-assessment/)

Multi-criteria flood risk mapping framework using **AHP** (Analytical Hierarchy Process) and DEM-based hydrological analysis.

| | |
|---|---|
| **Data Sources** | USGS 3DEP DEM (10m), NOAA Atlas 14, SSURGO soils, NLCD |
| **Criteria** | TWI, slope, river distance, rainfall, elevation, soil permeability, LULC |
| **Techniques** | AHP-weighted overlay, vulnerability assessment, scenario analysis (10yr–500yr return periods) |
| **Study Area** | Harris County, TX — 4,604 km² |
| **Key Result** | 18.3% high risk area; ~412,000 residents in flood-prone zones |

---

### 🌡️ [Urban Heat Island Analysis](urban-heat-island-analysis/)

Urban Heat Island (UHI) identification and mitigation priority mapping using **Landsat 8/9** thermal imagery.

| | |
|---|---|
| **Satellite Data** | Landsat 8/9 Collection 2 Level-2 (thermal + multispectral) |
| **Techniques** | LST derivation (single-channel algorithm), NDVI-based emissivity correction, UHI classification, LULC correlation |
| **Mitigation Index** | Thermal anomaly (40%) + population density (35%) + green space deficit (25%) |
| **Study Area** | Phoenix Metropolitan Area, AZ |
| **Key Result** | 12.8% extreme UHI coverage; 47 priority census blocks identified |

---

## Tech Stack

| Category | Tools |
|----------|-------|
| **GIS Platform** | QGIS 3.28+ with PyQGIS & Processing Framework |
| **Languages** | Python 3.9+ |
| **Geospatial** | GeoPandas, Rasterio, Shapely, GDAL |
| **Scientific** | NumPy, SciPy, scikit-learn |
| **Visualization** | Matplotlib, Seaborn |
| **DEM Processing** | WhiteboxTools |
| **Data Download** | Sentinelsat, USGS M2M API |

## Getting Started

```bash
git clone https://github.com/bhargavchintam/qgis-geospatial-projects.git
cd qgis-geospatial-projects
```

Each project has its own `requirements.txt` and `config.yaml`. Navigate into any project directory and follow its README:

```bash
cd crop-health-ndvi-monitoring   # or flood-risk-assessment / urban-heat-island-analysis
pip install -r requirements.txt
python scripts/run_pipeline.py --config config.yaml --output results/
```

## Repository Structure

```
qgis-geospatial-projects/
├── README.md
├── .gitignore
├── crop-health-ndvi-monitoring/
│   ├── src/           # 7 Python modules (sentinel loader, index calculator, anomaly detection, etc.)
│   ├── scripts/       # Pipeline runner
│   ├── tests/         # Pytest test suite
│   ├── qgis_sketches/ # QGIS project files & styles
│   ├── config.yaml
│   └── README.md
├── flood-risk-assessment/
│   ├── src/           # 7 Python modules (DEM processor, AHP engine, risk calculator, etc.)
│   ├── scripts/       # Pipeline runner
│   ├── tests/         # Pytest test suite
│   ├── qgis_sketches/ # QGIS project files & styles
│   ├── config.yaml
│   └── README.md
└── urban-heat-island-analysis/
    ├── src/           # 5 Python modules (LST processor, UHI classifier, mitigation mapper, etc.)
    ├── scripts/       # Pipeline runner & data downloader
    ├── tests/         # Pytest test suite
    ├── qgis_sketches/ # QGIS project files & styles
    ├── config.yaml
    └── README.md
```

## Author

**Bhargav** — [GitHub](https://github.com/bhargavchintam)

## License

All projects are licensed under the MIT License. See individual project `LICENSE` files for details.
