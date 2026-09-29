"""
Shared utilities for the Healthcare Accessibility pipeline.
"""

from pathlib import Path

import geopandas as gpd
import yaml


def load_config(config_path: str) -> dict:
    """Load and return the YAML configuration file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config


def ensure_directory(path) -> Path:
    """Create directory (and parents) if it does not exist. Returns the Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_gdf(gdf: gpd.GeoDataFrame, output_path, layer: str = None) -> str:
    """
    Write a GeoDataFrame to disk (GeoPackage by default).

    The parent directory is created if needed. Boolean columns are cast to
    integers because GeoPackage has no native boolean type. Returns the path
    as a string.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out = gdf.copy()
    for col in out.columns:
        if col != out.geometry.name and out[col].dtype == bool:
            out[col] = out[col].astype(int)
    if layer is None:
        layer = output_path.stem
    driver = "GPKG" if output_path.suffix.lower() == ".gpkg" else None
    if driver == "GPKG":
        out.to_file(output_path, layer=layer, driver=driver)
    else:
        out.to_file(output_path)
    return str(output_path)


def read_gdf(path, layer: str = None) -> gpd.GeoDataFrame:
    """Read a vector file into a GeoDataFrame."""
    if layer is None:
        return gpd.read_file(path)
    return gpd.read_file(path, layer=layer)
