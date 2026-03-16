# 🌊 Multi-Criteria Flood Risk Assessment Framework

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-green.svg)](https://qgis.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A GIS-based multi-criteria decision analysis (MCDA) framework for assessing flood risk at the watershed scale. Combines hydrological modeling with socioeconomic vulnerability indicators to produce actionable flood hazard and risk maps.

## Overview

This project implements a comprehensive flood risk assessment pipeline using the **Analytical Hierarchy Process (AHP)** to combine multiple geospatial criteria into a unified risk index. The framework evaluates both the physical susceptibility to flooding (hazard) and the exposure/vulnerability of populations and infrastructure.

### Key Capabilities

1. **DEM Hydrological Preprocessing** — Fill sinks, compute flow direction & accumulation, delineate watersheds and stream networks
2. **Flood Susceptibility Mapping** — AHP-weighted overlay of elevation, slope, TWI, distance to rivers, rainfall intensity, soil permeability, and LULC
3. **Vulnerability Assessment** — Population density, critical infrastructure proximity, socioeconomic indicators
4. **Composite Risk Index** — Hazard × Exposure × Vulnerability matrix
5. **Scenario Analysis** — Model flood risk under different return periods (10yr, 50yr, 100yr, 500yr)

## Project Structure

```
flood-risk-assessment/
├── README.md
├── LICENSE
├── requirements.txt
├── config.yaml
├── data/
│   └── sample/
├── src/
│   ├── __init__.py
│   ├── dem_processor.py          # DEM hydrological processing
│   ├── flood_susceptibility.py   # AHP-based susceptibility mapping
│   ├── vulnerability.py          # Socioeconomic vulnerability analysis
│   ├── risk_calculator.py        # Composite risk index computation
│   ├── ahp.py                    # Analytical Hierarchy Process engine
│   └── utils.py                  # Shared utilities
├── qgis_sketches/
│   ├── flood_risk.qgs
│   └── styles/
│       ├── flood_susceptibility.qml
│       ├── vulnerability.qml
│       └── risk_index.qml
├── scripts/
│   ├── run_pipeline.py
│   └── generate_report.py
├── tests/
│   ├── test_ahp.py
│   └── test_dem_processor.py
├── notebooks/
│   └── sensitivity_analysis.ipynb
└── docs/
    ├── methodology.md
    └── ahp_weights.md
```

## Methodology

### AHP Criteria Hierarchy

The flood susceptibility assessment uses 7 criteria with weights derived through pairwise comparison:

| Criterion | Weight | Source |
|-----------|--------|--------|
| Topographic Wetness Index (TWI) | 0.263 | DEM-derived |
| Slope | 0.196 | DEM-derived |
| Distance to River Network | 0.165 | Stream network buffer |
| Rainfall Intensity (IDF) | 0.134 | NOAA Atlas 14 |
| Elevation | 0.098 | DEM |
| Soil Permeability (Ksat) | 0.082 | SSURGO |
| Land Use / Land Cover | 0.062 | NLCD |

**Consistency Ratio (CR) = 0.047** (acceptable; CR < 0.10)

### Risk Framework

```
Risk = f(Hazard, Exposure, Vulnerability)

Where:
  Hazard       = Flood susceptibility × Return period factor
  Exposure     = Population density × Infrastructure density
  Vulnerability = Socioeconomic index × Adaptive capacity⁻¹
```

### Topographic Wetness Index

TWI quantifies the tendency of a location to accumulate water:

```
TWI = ln(α / tan(β))

Where:
  α = upslope contributing area per unit contour length
  β = local slope gradient
```

## Installation

```bash
git clone https://github.com/bhargavchintam/qgis-geospatial-projects.git
cd qgis-geospatial-projects/flood-risk-assessment
pip install -r requirements.txt
```

### Optional: WhiteboxTools for DEM processing

```bash
pip install whitebox
```

## Configuration

```yaml
# config.yaml
study_area:
  name: "Harris County, TX"
  crs: "EPSG:32615"
  boundary: "data/harris_county.gpkg"

dem:
  source: "data/dem_10m.tif"
  resolution: 10  # meters

ahp:
  criteria_weights:
    twi: 0.263
    slope: 0.196
    river_distance: 0.165
    rainfall: 0.134
    elevation: 0.098
    soil_permeability: 0.082
    lulc: 0.062

scenarios:
  return_periods: [10, 50, 100, 500]
  rainfall_source: "NOAA Atlas 14"
```

## Usage

### Full Pipeline

```bash
python scripts/run_pipeline.py --config config.yaml --output results/
```

### Individual Modules

```python
from src.dem_processor import DEMProcessor
from src.flood_susceptibility import FloodSusceptibility
from src.vulnerability import VulnerabilityAssessor
from src.risk_calculator import RiskCalculator

# Step 1: Process DEM
dem = DEMProcessor(config_path="config.yaml")
dem.fill_sinks()
flow_dir = dem.compute_flow_direction()
flow_acc = dem.compute_flow_accumulation(flow_dir)
twi = dem.compute_twi(flow_acc)
streams = dem.extract_stream_network(flow_acc, threshold=1000)
watersheds = dem.delineate_watersheds(flow_dir, streams)

# Step 2: Flood susceptibility mapping
susceptibility = FloodSusceptibility(config_path="config.yaml")
hazard_map = susceptibility.compute(
    twi=twi,
    slope="data/slope.tif",
    river_distance="data/river_distance.tif",
    rainfall="data/rainfall_100yr.tif",
    elevation="data/dem_10m.tif",
    soil_perm="data/ksat.tif",
    lulc="data/nlcd.tif",
)

# Step 3: Vulnerability assessment
vuln = VulnerabilityAssessor(config_path="config.yaml")
vulnerability_map = vuln.compute(
    population="data/population_density.tif",
    infrastructure="data/critical_infrastructure.gpkg",
    socioeconomic="data/census_svi.gpkg",
)

# Step 4: Composite risk
risk = RiskCalculator()
risk_map = risk.compute(hazard_map, vulnerability_map)
risk.classify_and_export(risk_map, "results/flood_risk.gpkg")
```

### PyQGIS Processing

```python
# In QGIS Python Console
import processing

# Fill sinks using QGIS Processing
processing.run("saga:fillsinksxxlwangliu", {
    'ELEV': 'data/dem_10m.tif',
    'FILLED': 'results/dem_filled.tif'
})
```

## Sample Results

| Metric | Value |
|--------|-------|
| Study Area | Harris County, TX (4,604 km²) |
| DEM Resolution | 10m (3DEP) |
| Return Period | 100-year |
| High Risk Area | 18.3% of county |
| Very High Risk | 6.7% of county |
| Population in High Risk Zones | ~412,000 residents |
| Critical Facilities at Risk | 127 (hospitals, schools, fire stations) |
| AHP Consistency Ratio | 0.047 |

## Data Sources

- [USGS 3DEP](https://www.usgs.gov/3d-elevation-program) — 10m Digital Elevation Model
- [NOAA Atlas 14](https://hdsc.nws.noaa.gov/pfds/) — Precipitation Frequency Estimates
- [NRCS SSURGO](https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo) — Soil Saturated Hydraulic Conductivity
- [NLCD](https://www.mrlc.gov/) — National Land Cover Database
- [CDC/ATSDR SVI](https://www.atsdr.cdc.gov/placeandhealth/svi/) — Social Vulnerability Index
- [HIFLD](https://hifld-geoplatform.opendata.arcgis.com/) — Critical Infrastructure

## Technologies

- **QGIS 3.28+** with Processing Framework and PyQGIS
- **WhiteboxTools** for advanced hydrological DEM processing
- **GeoPandas** & **Rasterio** for geospatial I/O
- **NumPy / SciPy** for matrix operations and AHP
- **Matplotlib / Seaborn** for visualization
- **PyYAML** for configuration

## License

MIT License — see [LICENSE](LICENSE) file.

## Citation

```bibtex
@software{flood_risk_2025,
  title={Multi-Criteria Flood Risk Assessment Framework},
  author={Bhargav},
  year={2025},
  url={https://github.com/bhargavchintam/qgis-geospatial-projects/tree/main/flood-risk-assessment}
}
```

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
