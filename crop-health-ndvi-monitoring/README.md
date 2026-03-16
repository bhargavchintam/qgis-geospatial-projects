# 🌾 Multi-Temporal Crop Health Monitoring with Sentinel-2 NDVI

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-green.svg)](https://qgis.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A precision agriculture toolkit that monitors crop health across growing seasons using multi-temporal Sentinel-2 satellite imagery. Computes vegetation indices (NDVI, EVI, SAVI), detects anomalies, and generates field-level health reports for site-specific crop management.

## Overview

This project provides an automated pipeline for monitoring agricultural fields using free Sentinel-2 multispectral data at 10m resolution. It supports the full precision agriculture workflow from satellite data acquisition to actionable field management recommendations.

### Key Capabilities

1. **Multi-Index Computation** — NDVI, EVI, SAVI, NDWI, NDRE for comprehensive crop assessment
2. **Time Series Analysis** — Track vegetation phenology across the full growing season
3. **Anomaly Detection** — Identify stressed regions deviating from field-average or historical baselines
4. **Zonal Field Statistics** — Per-parcel aggregated health metrics aligned with farm management zones
5. **Change Detection** — Quantify inter-seasonal and intra-seasonal crop vigor changes
6. **Automated Reporting** — Generate field health reports with maps and statistics

## Project Structure

```
crop-health-ndvi-monitoring/
├── README.md
├── LICENSE
├── requirements.txt
├── config.yaml
├── data/
│   └── sample/
│       └── field_boundaries.geojson
├── src/
│   ├── __init__.py
│   ├── sentinel_loader.py        # Sentinel-2 data acquisition & preprocessing
│   ├── index_calculator.py       # Vegetation index computation engine
│   ├── time_series.py            # Multi-temporal phenology analysis
│   ├── anomaly_detector.py       # Spatial anomaly detection
│   ├── zonal_stats.py            # Field-level zonal statistics
│   └── utils.py                  # Shared utilities
├── qgis_sketches/
│   ├── crop_monitoring.qgs
│   └── styles/
│       ├── ndvi_health.qml
│       ├── anomaly_map.qml
│       └── field_report.qml
├── scripts/
│   ├── run_pipeline.py
│   ├── download_sentinel.py
│   └── generate_report.py
├── tests/
│   ├── test_index_calculator.py
│   └── test_anomaly_detector.py
├── notebooks/
│   └── phenology_analysis.ipynb
└── docs/
    ├── methodology.md
    └── vegetation_indices.md
```

## Vegetation Indices

| Index | Formula | Application |
|-------|---------|-------------|
| **NDVI** | (NIR - Red) / (NIR + Red) | General vegetation vigor |
| **EVI** | 2.5 × (NIR - Red) / (NIR + 6×Red - 7.5×Blue + 1) | Enhanced vegetation, reduces atmospheric effects |
| **SAVI** | (NIR - Red) / (NIR + Red + L) × (1 + L) | Soil-adjusted vegetation, sparse canopy |
| **NDRE** | (NIR - RedEdge) / (NIR + RedEdge) | Chlorophyll content, nitrogen stress |
| **NDWI** | (Green - NIR) / (Green + NIR) | Crop water content / moisture stress |

## Installation

```bash
git clone https://github.com/bhargavchintam/qgis-geospatial-projects.git
cd qgis-geospatial-projects
cd crop-health-ndvi-monitoring
pip install -r requirements.txt
```

### Optional: Sentinel-2 data download

```bash
pip install sentinelsat
# Requires Copernicus Open Access Hub credentials
```

## Configuration

```yaml
# config.yaml
study_area:
  name: "Iowa Corn Belt Study Area"
  crs: "EPSG:32615"
  field_boundaries: "data/field_boundaries.geojson"

sentinel:
  platform: "Sentinel-2"
  product_type: "S2MSI2A"  # Level-2A (atmospherically corrected)
  cloud_cover_max: 15
  bands:
    blue: "B02"       # 10m
    green: "B03"      # 10m
    red: "B04"        # 10m
    red_edge: "B05"   # 20m
    nir: "B08"        # 10m
    swir: "B11"       # 20m

growing_season:
  start: "2024-04-01"
  end: "2024-10-31"
  phenology_stages:
    - {name: "Planting", range: ["04-01", "05-15"]}
    - {name: "Vegetative", range: ["05-15", "07-01"]}
    - {name: "Reproductive", range: ["07-01", "08-15"]}
    - {name: "Maturity", range: ["08-15", "10-01"]}
    - {name: "Harvest", range: ["10-01", "10-31"]}

anomaly:
  method: "z_score"
  threshold: -1.5        # z-score below which is anomalous
  min_cluster_ha: 0.5    # minimum anomaly cluster size (hectares)

output:
  directory: "results"
  formats: ["GeoTIFF", "GeoPackage", "PNG", "CSV"]
```

## Usage

### Full Pipeline

```bash
python scripts/run_pipeline.py --config config.yaml --output results/
```

### Individual Modules

```python
from src.sentinel_loader import SentinelLoader
from src.index_calculator import IndexCalculator
from src.time_series import TimeSeriesAnalyzer
from src.anomaly_detector import AnomalyDetector
from src.zonal_stats import ZonalFieldStats

# Step 1: Load Sentinel-2 data
loader = SentinelLoader(config_path="config.yaml")
scenes = loader.load_time_series("data/sentinel2/")

# Step 2: Compute vegetation indices
calc = IndexCalculator()
for scene in scenes:
    scene["ndvi"] = calc.ndvi(scene["nir"], scene["red"])
    scene["evi"] = calc.evi(scene["nir"], scene["red"], scene["blue"])
    scene["ndre"] = calc.ndre(scene["nir"], scene["red_edge"])

# Step 3: Time series analysis
ts = TimeSeriesAnalyzer()
phenology = ts.fit_phenology_curve(scenes, index="ndvi")
peak_ndvi = ts.get_peak_metrics(phenology)

# Step 4: Anomaly detection
detector = AnomalyDetector(config_path="config.yaml")
anomalies = detector.detect(
    current_ndvi=scenes[-1]["ndvi"],
    baseline=phenology["expected"],
    method="z_score"
)

# Step 5: Field-level statistics
zonal = ZonalFieldStats("data/field_boundaries.geojson")
report = zonal.compute(scenes, indices=["ndvi", "evi", "ndre"])
report.to_csv("results/field_health_report.csv")
```

## Sample Results

| Metric | Value |
|--------|-------|
| Study Area | Story County, Iowa |
| Crop Type | Corn (Zea mays) |
| Season | April–October 2024 |
| Sentinel-2 Scenes Analyzed | 14 (cloud-free) |
| Fields Monitored | 342 parcels (12,450 ha) |
| Peak NDVI | 0.87 (July 18) |
| Anomalous Area Detected | 8.3% of total field area |
| Dominant Stress Type | Moisture deficit (NDWI < -0.15) |

## Data Sources

- [Copernicus Open Access Hub](https://scihub.copernicus.eu/) — Sentinel-2 Level-2A MSI
- [USDA CropScape](https://nassgeodata.gmu.edu/CropScape/) — Cropland Data Layer (CDL)
- [USDA NASS](https://quickstats.nass.usda.gov/) — Agricultural statistics
- [OpenStreetMap](https://www.openstreetmap.org/) — Field boundaries (where available)
- [PRISM Climate Data](https://prism.oregonstate.edu/) — Gridded precipitation & temperature

## Technologies

- **QGIS 3.28+** with PyQGIS and Processing Framework
- **GeoPandas** for vector field boundary management
- **Rasterio** for satellite imagery I/O
- **NumPy / SciPy** for index computation and signal processing
- **scikit-learn** for anomaly detection (Isolation Forest, LOF)
- **Matplotlib / Seaborn** for phenology curve visualization
- **sentinelsat** for automated Sentinel-2 data download

## License

MIT License — see [LICENSE](LICENSE) file.

## Citation

```bibtex
@software{crop_health_2025,
  title={Multi-Temporal Crop Health Monitoring with Sentinel-2 NDVI},
  author={Bhargav},
  year={2025},
  url={https://github.com/bhargavchintam/qgis-geospatial-projects/tree/main/crop-health-ndvi-monitoring}
}
```

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
