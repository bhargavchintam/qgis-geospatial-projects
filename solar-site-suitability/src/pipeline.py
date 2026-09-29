"""
End-to-end suitability pipeline.

``run_pipeline`` chains the src modules: terrain -> distance rasters ->
criteria -> AHP weights -> constraints -> weighted overlay -> classes ->
candidate sites -> summary. demo.py, app.py and the tests all call it so
the logic lives in one place.
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from .ahp import AHPEngine
from .criteria import (CONSTRAINT_LABELS, aspect_score, build_constraint_mask,
                       constraint_reasons, distance_score, ghi_score,
                       landuse_score, slope_score)
from .suitability import (class_area_table, classify_suitability,
                          extract_candidate_sites, weighted_overlay)
from .terrain import aspect_degrees, hillshade, slope_degrees
from .utils import (distance_raster, ensure_directory, pixel_area_ha, pixel_size,
                    read_raster, write_raster, write_vector)

CRITERIA_TITLES = {
    "ghi": "Solar resource (GHI)",
    "slope": "Slope",
    "aspect": "Aspect",
    "grid_distance": "Distance to grid",
    "road_distance": "Distance to roads",
    "landuse": "Land use",
}


def _load_raster(data: dict, key: str):
    arrays = data.get("arrays") or {}
    if key in arrays and "profile" in data:
        return np.asarray(arrays[key], dtype=np.float64), dict(data["profile"])
    return read_raster(data[key])


def _load_vector(data: dict, key: str, crs) -> gpd.GeoDataFrame:
    value = data.get(key)
    if isinstance(value, gpd.GeoDataFrame):
        gdf = value
    else:
        gdf = gpd.read_file(value)
    if gdf.crs is not None and crs is not None and gdf.crs != crs:
        gdf = gdf.to_crs(crs)
    return gdf


def compute_ahp(config: dict, weights_override: dict = None) -> tuple:
    """Return (weights dict, consistency dict, AHPEngine).

    ``weights_override`` (e.g. Streamlit sliders) replaces the AHP weights
    after normalisation but the consistency report still describes the
    configured pairwise matrix.
    """
    ahp_cfg = config["ahp"]
    names = list(ahp_cfg["criteria_names"])
    engine = AHPEngine(ahp_cfg["pairwise_matrix"], criteria_names=names,
                       consistency_threshold=float(ahp_cfg.get("consistency_threshold", 0.10)))
    engine.compute_weights()
    consistency = engine.compute_consistency()
    weights = engine.get_weight_dict()
    if weights_override:
        total = float(sum(weights_override.values()))
        if total > 0:
            weights = {k: float(v) / total for k, v in weights_override.items()}
    return weights, consistency, engine


def run_pipeline(data: dict, config: dict, out_dir=None, weights_override: dict = None,
                 overrides: dict = None) -> dict:
    """Run the full suitability workflow.

    Args:
        data: dict from ``generate_demo_data`` (paths and/or arrays + profile)
            or a dict of file paths with the same keys.
        config: parsed config.yaml.
        out_dir: if given, rasters / vectors / CSV / JSON are written here.
        weights_override: optional {criterion: weight} replacing AHP weights.
        overrides: optional dict to override config values without editing
            it, keys: ``threshold``, ``min_area_ha``, ``max_slope``,
            ``residential_buffer_m``.

    Returns:
        dict with arrays (dem, slope, aspect, hillshade, ghi, landuse,
        distances, criteria, mask, reasons, index, classes), ``sites``
        GeoDataFrame, vector layers, ``weights``, ``consistency``,
        ``profile``, ``summary`` and ``outputs`` (written file paths).
    """
    overrides = overrides or {}
    dem, profile = _load_raster(data, "dem")
    ghi, _ = _load_raster(data, "ghi")
    landuse, _ = _load_raster(data, "landuse")
    crs = profile.get("crs")
    res = pixel_size(profile)

    # 1. Terrain
    slope = slope_degrees(dem, res)
    aspect = aspect_degrees(dem, res)
    shade = hillshade(dem, res)

    # 2. Vectors and distance rasters
    vectors = {k: _load_vector(data, k, crs)
               for k in ["transmission_lines", "roads", "substations", "residential", "protected_areas"]}
    dist = {
        "transmission": distance_raster(vectors["transmission_lines"], profile),
        "substations": distance_raster(vectors["substations"], profile),
        "roads": distance_raster(vectors["roads"], profile),
        "residential": distance_raster(vectors["residential"], profile),
    }
    # Substations are folded into the grid criterion: a site can connect to
    # either a line or a substation, so use whichever is nearer.
    dist["grid"] = np.minimum(dist["transmission"], dist["substations"])

    # 3. Criteria (0..1)
    ccfg = config["criteria"]
    criteria = {
        "ghi": ghi_score(ghi, **ccfg["ghi"]),
        "slope": slope_score(slope, **ccfg["slope"]),
        "aspect": aspect_score(aspect),
        "grid_distance": distance_score(dist["grid"], **ccfg["grid_distance"]),
        "road_distance": distance_score(dist["roads"], **ccfg["road_distance"]),
        "landuse": landuse_score(landuse, {int(k): float(v) for k, v in ccfg["landuse"]["mapping"].items()}),
    }

    # 4. AHP weights
    weights, consistency, engine = compute_ahp(config, weights_override)

    # 5. Constraints
    kcfg = config["constraints"]
    max_slope = float(overrides.get("max_slope", kcfg["max_slope"]))
    buffer_m = float(overrides.get("residential_buffer_m", kcfg["residential_buffer_m"]))
    reasons = constraint_reasons(landuse, slope, dist["residential"],
                                 water_codes=tuple(kcfg["water_codes"]),
                                 urban_codes=tuple(kcfg["urban_codes"]),
                                 protected_codes=tuple(kcfg["protected_codes"]),
                                 max_slope=max_slope, residential_buffer_m=buffer_m)
    mask = build_constraint_mask(landuse, slope, dist["residential"],
                                 water_codes=tuple(kcfg["water_codes"]),
                                 urban_codes=tuple(kcfg["urban_codes"]),
                                 protected_codes=tuple(kcfg["protected_codes"]),
                                 max_slope=max_slope, residential_buffer_m=buffer_m)

    # 6. Overlay and classes
    index = weighted_overlay(criteria, weights, mask)
    thresholds = tuple(config["classification"]["thresholds"])
    classes = classify_suitability(index, thresholds)

    # 7. Candidate sites
    scfg = config["site_extraction"]
    threshold = float(overrides.get("threshold", scfg["threshold"]))
    min_area_ha = float(overrides.get("min_area_ha", scfg["min_area_ha"]))
    sites = extract_candidate_sites(
        index, profile, threshold=threshold, min_area_ha=min_area_ha, ghi=ghi,
        dist_to_grid=dist["grid"], ha_per_mw=float(scfg["ha_per_mw"]),
        module_efficiency=float(scfg["module_efficiency"]),
        ground_cover_ratio=float(scfg["ground_cover_ratio"]),
        performance_ratio=float(scfg["performance_ratio"]))

    # 8. Summary
    n_pix = mask.size
    pix_ha = pixel_area_ha(profile)
    excluded_by_reason = {}
    for code, label in CONSTRAINT_LABELS.items():
        if code == 0:
            continue
        excluded_by_reason[label] = round(100.0 * float((reasons == code).sum()) / n_pix, 2)
    class_table = class_area_table(classes, profile)
    summary = {
        "study_area": config["study_area"]["name"],
        "grid_size": [int(profile["height"]), int(profile["width"])],
        "resolution_m": round(res, 2),
        "total_area_km2": round(n_pix * pix_ha / 100.0, 2),
        "ahp_weights": {k: round(float(v), 4) for k, v in weights.items()},
        "ahp_consistency": consistency,
        "pct_area_excluded": round(100.0 * float((~mask).sum()) / n_pix, 2),
        "pct_excluded_by_reason": excluded_by_reason,
        "class_area_pct_of_allowed": {row["label"]: row["pct_of_allowed"] for _, row in class_table.iterrows()},
        "site_threshold": threshold,
        "min_site_area_ha": min_area_ha,
        "n_candidate_sites": int(len(sites)),
        "total_capacity_mw": round(float(sites["capacity_mw"].sum()), 1) if len(sites) else 0.0,
        "total_annual_gwh": round(float(sites["annual_gwh"].sum()), 1) if len(sites) else 0.0,
        "best_site_mw": round(float(sites["capacity_mw"].iloc[0]), 1) if len(sites) else 0.0,
        "top_sites": sites.drop(columns="geometry").head(5).to_dict(orient="records") if len(sites) else [],
    }

    results = {
        "profile": profile, "dem": dem, "slope": slope, "aspect": aspect, "hillshade": shade,
        "ghi": ghi, "landuse": landuse, "distances": dist, "criteria": criteria,
        "weights": weights, "consistency": consistency, "pairwise_matrix": np.asarray(engine.matrix),
        "criteria_names": list(engine.criteria_names), "criteria_params": ccfg,
        "mask": mask, "reasons": reasons, "index": index, "classes": classes,
        "thresholds": thresholds, "sites": sites, "vectors": vectors,
        "class_table": class_table, "summary": summary, "outputs": {},
    }

    if out_dir is not None:
        results["outputs"] = write_outputs(results, out_dir)
    return results


def write_outputs(results: dict, out_dir) -> dict:
    """Write rasters, vectors, CSVs and summary.json to ``out_dir``."""
    out_dir = ensure_directory(out_dir)
    profile = results["profile"]
    outputs = {}
    rasters = {
        "slope_degrees": results["slope"],
        "aspect_degrees": results["aspect"],
        "hillshade": results["hillshade"],
        "distance_to_grid_m": results["distances"]["grid"],
        "distance_to_roads_m": results["distances"]["roads"],
        "suitability_index": results["index"],
    }
    for name, arr in rasters.items():
        outputs[name] = write_raster(arr, profile, out_dir / f"{name}.tif")
    for name, arr in results["criteria"].items():
        outputs[f"criterion_{name}"] = write_raster(arr, profile, out_dir / f"criterion_{name}.tif")
    outputs["suitability_classes"] = write_raster(results["classes"], profile,
                                                  out_dir / "suitability_classes.tif", nodata=0)
    outputs["constraints_mask"] = write_raster(results["mask"].astype(np.int32), profile,
                                               out_dir / "constraints_mask.tif")
    outputs["constraint_reasons"] = write_raster(results["reasons"], profile,
                                                 out_dir / "constraint_reasons.tif")

    sites = results["sites"]
    if len(sites):
        outputs["candidate_sites"] = write_vector(sites, out_dir / "candidate_sites.gpkg")
    sites.drop(columns="geometry").to_csv(out_dir / "candidate_sites.csv", index=False)
    outputs["candidate_sites_csv"] = str(out_dir / "candidate_sites.csv")

    weights_df = pd.DataFrame({
        "criterion": list(results["weights"].keys()),
        "weight": [round(v, 4) for v in results["weights"].values()],
    })
    weights_df.to_csv(out_dir / "ahp_weights.csv", index=False)
    outputs["ahp_weights_csv"] = str(out_dir / "ahp_weights.csv")
    results["class_table"].to_csv(out_dir / "class_areas.csv", index=False)
    outputs["class_areas_csv"] = str(out_dir / "class_areas.csv")

    with open(out_dir / "summary.json", "w") as f:
        json.dump(results["summary"], f, indent=2, default=_json_default)
    outputs["summary_json"] = str(out_dir / "summary.json")
    return outputs


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)
