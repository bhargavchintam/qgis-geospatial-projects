# 🌡️ Urban Heat Island Analysis & Mitigation Mapping

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-green.svg)](https://qgis.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A comprehensive geospatial analysis pipeline that identifies Urban Heat Islands (UHI) using Landsat 8/9 thermal imagery, correlates them with land use/land cover (LULC) data, and generates actionable mitigation priority maps for urban planners.

## Overview

Urban Heat Islands are metropolitan areas that experience significantly higher temperatures than surrounding rural regions due to human activities and built infrastructure. This project provides an end-to-end workflow for:

1. **Land Surface Temperature (LST) derivation** from Landsat 8/9 Band 10 thermal data
2. **NDVI-based emissivity correction** for accurate temperature estimation
3. **UHI intensity classification** using statistical thresholds
4. **Spatial correlation analysis** between UHI zones and LULC categories
5. **Mitigation priority mapping** combining temperature anomaly, population density, and green space deficit

## Project Structure

```
urban-heat-island-analysis/
├── README.md
├── LICENSE
├── requirements.txt
├── config.yaml
├── data/
│   └── sample/                  # Sample data for testing
├── src/
│   ├── __init__.py
│   ├── lst_processor.py         # Land Surface Temperature derivation
│   ├── uhi_classifier.py        # UHI zone identification & classification
│   ├── lulc_correlator.py       # LULC spatial correlation analysis
│   ├── mitigation_mapper.py     # Priority mitigation zone mapping
│   └── utils.py                 # Shared utilities and helpers
├── qgis_sketches/
│   ├── uhi_analysis.qgs         # QGIS project file
│   └── styles/                  # QGIS .qml style files
│       ├── lst_gradient.qml
│       ├── uhi_zones.qml
│       └── mitigation_priority.qml
├── notebooks/
│   └── exploration.ipynb        # Data exploration notebook
├── scripts/
│   ├── run_pipeline.py          # Full pipeline execution script
│   └── download_data.py         # Automated Landsat data download
├── tests/
│   └── test_lst_processor.py
└── docs/
    └── methodology.md
```

## Key Features

- **Automated LST Derivation**: Converts Landsat 8/9 Band 10 DN values → radiance → brightness temperature → LST with emissivity correction
- **Multi-Temporal Analysis**: Compare UHI patterns across seasons and years
- **Statistical UHI Classification**: Uses mean + σ thresholds to classify UHI intensity (Extreme, Strong, Moderate, Mild)
- **LULC Correlation Engine**: Zonal statistics linking UHI intensity to impervious surface %, vegetation cover, and water bodies
- **Mitigation Priority Index (MPI)**: Weighted composite score combining thermal anomaly, population exposure, and green infrastructure deficit
- **QGIS Integration**: Full PyQGIS scripting with styled layer outputs ready for cartographic production

## Installation

### Prerequisites

- Python 3.9+
- QGIS 3.28+ (with PyQGIS)
- GDAL 3.4+

### Setup

```bash
git clone https://github.com/bhargavchintam/qgis-geospatial-projects.git
cd qgis-geospatial-projects/urban-heat-island-analysis
pip install -r requirements.txt
```

### Configuration

Edit `config.yaml` to set your study area and data paths:

```yaml
study_area:
  name: "Phoenix Metropolitan Area"
  bbox: [-112.45, 33.20, -111.60, 33.85]
  crs: "EPSG:32612"

landsat:
  collection: 2
  level: "L2SP"
  bands: ["B4", "B5", "B10"]
  cloud_cover_max: 10

classification:
  uhi_thresholds:
    extreme: 2.0    # mean + 2σ
    strong: 1.5     # mean + 1.5σ
    moderate: 1.0   # mean + 1σ
    mild: 0.5       # mean + 0.5σ

mitigation:
  weights:
    thermal_anomaly: 0.40
    population_density: 0.35
    green_space_deficit: 0.25
```

## Usage

### Full Pipeline

```bash
python scripts/run_pipeline.py --config config.yaml --output results/
```

### Individual Modules

```python
from src.lst_processor import LSTProcessor
from src.uhi_classifier import UHIClassifier
from src.mitigation_mapper import MitigationMapper

# Step 1: Derive Land Surface Temperature
processor = LSTProcessor(config_path="config.yaml")
lst_raster = processor.compute_lst(
    thermal_band="data/LC09_B10.TIF",
    red_band="data/LC09_B4.TIF",
    nir_band="data/LC09_B5.TIF"
)

# Step 2: Classify UHI zones
classifier = UHIClassifier(config_path="config.yaml")
uhi_zones = classifier.classify(lst_raster)
stats = classifier.compute_statistics(uhi_zones)

# Step 3: Generate mitigation priority map
mapper = MitigationMapper(config_path="config.yaml")
priority_map = mapper.generate(
    uhi_zones=uhi_zones,
    population_raster="data/population_density.tif",
    greenspace_vector="data/parks_greenspace.gpkg"
)
```

### PyQGIS Integration

```python
# Run inside QGIS Python Console
exec(open('scripts/run_pipeline.py').read())
```

## Methodology

### Land Surface Temperature Derivation

The LST computation follows the **single-channel algorithm** with NDVI-based emissivity correction:

1. **Top-of-Atmosphere Radiance**: `Lλ = ML × Qcal + AL`
2. **Brightness Temperature**: `BT = K2 / ln(K1/Lλ + 1)`
3. **NDVI Calculation**: `NDVI = (NIR - Red) / (NIR + Red)`
4. **Proportion of Vegetation**: `Pv = ((NDVI - NDVImin) / (NDVImax - NDVImin))²`
5. **Land Surface Emissivity**: `ε = 0.004 × Pv + 0.986`
6. **Land Surface Temperature**: `LST = BT / (1 + (λ × BT / ρ) × ln(ε))`

### UHI Classification

UHI intensity is classified using standard deviation thresholds relative to the study area mean LST:

| Class | Threshold | Description |
|-------|-----------|-------------|
| Extreme | μ + 2σ | Critical heat zones requiring immediate intervention |
| Strong | μ + 1.5σ | Significant heat accumulation areas |
| Moderate | μ + 1σ | Notable temperature elevation |
| Mild | μ + 0.5σ | Slight temperature increase |
| Neutral | ≤ μ | At or below average temperature |

### Mitigation Priority Index

```
MPI = w₁ × Normalized_Thermal_Anomaly + w₂ × Normalized_Pop_Density + w₃ × Green_Space_Deficit
```

## Sample Results

| Metric | Value |
|--------|-------|
| Study Area | Phoenix Metro, AZ |
| Acquisition Date | July 2024 |
| Mean LST | 45.3°C |
| Max LST | 58.7°C |
| UHI Intensity Range | 2.1–13.4°C above rural baseline |
| Extreme UHI Coverage | 12.8% of urban area |
| Top Mitigation Priority Zones | 47 census blocks identified |

## Data Sources

- [USGS EarthExplorer](https://earthexplorer.usgs.gov/) — Landsat 8/9 Collection 2 Level-2
- [NLCD](https://www.mrlc.gov/) — National Land Cover Database
- [US Census TIGER](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) — Population and boundary data
- [OpenStreetMap](https://www.openstreetmap.org/) — Green space and infrastructure layers

## Technologies

- **QGIS 3.28+** with PyQGIS for spatial analysis and cartographic output
- **GeoPandas** for vector data manipulation
- **Rasterio** for raster I/O and processing
- **NumPy / SciPy** for numerical computation and statistical analysis
- **Matplotlib** for visualization and figure generation
- **PyYAML** for configuration management

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Citation

If you use this project in your research, please cite:

```bibtex
@software{uhi_analysis_2025,
  title={Urban Heat Island Analysis & Mitigation Mapping},
  author={Bhargav},
  year={2025},
  url={https://github.com/bhargavchintam/qgis-geospatial-projects/tree/main/urban-heat-island-analysis}
}
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
