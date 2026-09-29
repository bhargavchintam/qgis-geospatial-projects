"""
End-to-end forest change pipeline used by demo.py, app.py and the tests.

    indices -> Random Forest (both dates) -> predict T1 / T2 (cloud masked)
    -> accuracy on held-out samples -> post-classification change + dNBR
    -> evidence rule -> minimum mapping unit -> vectorise -> statistics
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .accuracy import accuracy_summary
from .change_detection import (combine_evidence, distance_to_nearest_road, dnbr,
                               filter_mmu, post_classification_change, threshold_dnbr,
                               vectorize_loss)
from .classifier import LandCoverClassifier
from .indices import compute_all, false_color_composite
from .report import area_statistics
from .utils import ensure_directory, write_raster, write_vector

EVIDENCE_RULES = ("both", "post_classification", "dnbr")


def mmu_pixels_from_ha(mmu_ha: float, pixel_area_m2: float) -> int:
    """Minimum mapping unit in pixels (rounded up): 0.5 ha at 20 m -> 13 pixels."""
    if mmu_ha <= 0:
        return 1
    return int(np.ceil(mmu_ha * 10000.0 / pixel_area_m2))


def run_pipeline(data: dict, out_dir=None, *, forest_class: int = 1, n_per_class: int = 400,
                 n_estimators: int = 100, seed: int = 42, dnbr_loss_threshold: float = 0.27,
                 evidence_rule: str = "both", mmu_ha: float = 0.5, road_distance_m: float = 500.0,
                 years: float = None) -> dict:
    """
    Run the full pipeline on the dict returned by ``generate_demo_data``.

    Parameters
    ----------
    data : output of ``synthetic_data.generate_demo_data`` (arrays in memory).
    out_dir : optional folder for rasters / vectors / CSVs.
    evidence_rule : "both" (post-classification AND dNBR agree, conservative),
                    "post_classification" or "dnbr".
    mmu_ha : minimum mapping unit in hectares.

    Returns
    -------
    dict with class rasters, indices, change rasters, loss GeoDataFrame,
    accuracy summary, area statistics, feature importances and the classifier.
    """
    if evidence_rule not in EVIDENCE_RULES:
        raise ValueError(f"evidence_rule must be one of {EVIDENCE_RULES}")

    t1, t2 = data["t1_stack"], data["t2_stack"]
    ref_t1, ref_t2 = data["reference_t1"], data["reference_t2"]
    cloud = np.asarray(data["cloud_mask_t2"], dtype=bool)
    profile = data["class_profile"]
    pixel_area_ha = data["pixel_area_ha"]
    pixel_area_m2 = pixel_area_ha * 10000.0
    years = float(years if years is not None else data["dates"]["years"])
    class_names = LandCoverClassifier.CLASSES

    # 1. indices
    idx_t1 = compute_all(t1)
    idx_t2 = compute_all(t2)
    for arr in idx_t2.values():
        arr[cloud] = np.nan

    # 2. classifier trained on samples from both dates (cloud pixels excluded at T2)
    clf = LandCoverClassifier(n_estimators=n_estimators, random_state=seed)
    clf.fit([t1, t2], [ref_t1, ref_t2], n_per_class=n_per_class, seed=seed,
            valid_masks=[None, ~cloud])
    class_t1 = clf.predict(t1)
    class_t2 = clf.predict(t2, cloud_mask=cloud)

    # 3. accuracy on the held-out 30 %
    y_true, y_pred = clf.predict_test()
    acc = accuracy_summary(y_true, y_pred, labels=sorted(class_names), class_names=class_names)

    # 4. change evidence
    change_pc = post_classification_change(class_t1, class_t2, forest_class)
    dnbr_arr = dnbr(idx_t1["nbr"], idx_t2["nbr"])
    dnbr_loss = threshold_dnbr(dnbr_arr, dnbr_loss_threshold)
    post_loss = change_pc == 3
    valid = (class_t1 > 0) & (class_t2 > 0)
    if evidence_rule == "both":
        loss_raw = combine_evidence(post_loss, dnbr_loss)
    elif evidence_rule == "post_classification":
        loss_raw = post_loss.copy()
    else:
        loss_raw = dnbr_loss & valid

    # 5. minimum mapping unit (applied to loss and to gain speckles)
    mmu_px = mmu_pixels_from_ha(mmu_ha, pixel_area_m2)
    loss_final = filter_mmu(loss_raw, mmu_px)
    gain_final = filter_mmu(change_pc == 4, mmu_px)

    # final change raster: unconfirmed loss falls back to stable forest and
    # gain speckle below the MMU falls back to stable non-forest (conservative)
    change = change_pc.copy()
    change[change == 3] = 1
    change[(change == 4) & ~gain_final] = 2
    change[loss_final & valid] = 3

    # 6. vectorise and relate to roads
    loss_gdf = vectorize_loss(loss_final, profile)
    loss_gdf = distance_to_nearest_road(loss_gdf, data.get("roads"))

    # 7. statistics
    stats = area_statistics(class_t1, class_t2, change, pixel_area_ha, years, loss_gdf,
                            forest_class, road_distance_m, class_names)
    truth_loss = (ref_t1 == forest_class) & (ref_t2 != forest_class) & valid
    stats["truth_loss_ha"] = float(truth_loss.sum() * pixel_area_ha)
    stats["truth_loss_detected_pct"] = float(100.0 * (loss_final & truth_loss).sum() / truth_loss.sum()) \
        if truth_loss.any() else float("nan")
    stats["false_alarm_ha"] = float((loss_final & ~truth_loss).sum() * pixel_area_ha)
    stats["mmu_pixels"] = mmu_px
    stats["mmu_ha"] = float(mmu_ha)
    stats["dnbr_loss_threshold"] = float(dnbr_loss_threshold)
    stats["evidence_rule"] = evidence_rule
    stats["loss_raw_ha"] = float(loss_raw.sum() * pixel_area_ha)
    stats["post_classification_loss_ha"] = float(post_loss.sum() * pixel_area_ha)
    stats["dnbr_loss_ha"] = float((dnbr_loss & valid).sum() * pixel_area_ha)

    importances = clf.feature_importances()

    results = {
        "class_t1": class_t1,
        "class_t2": class_t2,
        "ndvi_t1": idx_t1["ndvi"], "ndvi_t2": idx_t2["ndvi"],
        "nbr_t1": idx_t1["nbr"], "nbr_t2": idx_t2["nbr"],
        "ndmi_t1": idx_t1["ndmi"], "ndmi_t2": idx_t2["ndmi"],
        "dnbr": dnbr_arr,
        "dnbr_loss": dnbr_loss,
        "change_post_classification": change_pc,
        "loss_raw": loss_raw,
        "loss_final": loss_final,
        "change": change,
        "loss_gdf": loss_gdf,
        "accuracy": acc,
        "stats": stats,
        "importances": importances,
        "classifier": clf,
        "false_color_t1": false_color_composite(t1),
        "false_color_t2": false_color_composite(t2),
        "profile": profile,
        "roads": data.get("roads"),
        "river": data.get("river"),
        "cloud_mask_t2": cloud,
        "mmu_pixels": mmu_px,
    }

    if out_dir is not None:
        results["paths"] = write_outputs(results, out_dir)
    return results


def write_outputs(results: dict, out_dir) -> dict:
    """Write rasters, the loss polygons and CSV tables to ``out_dir``."""
    out_dir = ensure_directory(out_dir)
    profile = results["profile"]
    paths = {}
    for key in ("class_t1", "class_t2", "change"):
        paths[key] = write_raster(results[key], profile, out_dir / f"{key}.tif", nodata=0, dtype="uint8")
    paths["loss_final"] = write_raster(results["loss_final"].astype(np.uint8), profile,
                                       out_dir / "forest_loss_mask.tif", nodata=None, dtype="uint8")
    for key in ("ndvi_t1", "ndvi_t2", "nbr_t1", "nbr_t2", "dnbr"):
        arr = np.where(np.isfinite(results[key]), results[key], -9999.0).astype(np.float32)
        paths[key] = write_raster(arr, profile, out_dir / f"{key}.tif", nodata=-9999.0, dtype="float32")

    gdf = results["loss_gdf"]
    if len(gdf) > 0:
        paths["loss_patches"] = write_vector(gdf, out_dir / "forest_loss_patches.gpkg", layer="forest_loss_patches")
    else:
        paths["loss_patches"] = None

    acc = results["accuracy"]
    cm = pd.DataFrame(acc["confusion_matrix"],
                      index=[f"ref_{n}" for n in acc["class_names"]],
                      columns=[f"pred_{n}" for n in acc["class_names"]])
    paths["confusion_matrix"] = str(out_dir / "confusion_matrix.csv")
    cm.to_csv(paths["confusion_matrix"])
    paths["accuracy_per_class"] = str(out_dir / "accuracy_per_class.csv")
    acc["per_class"].to_csv(paths["accuracy_per_class"], index=False)
    paths["feature_importance"] = str(out_dir / "feature_importance.csv")
    results["importances"].rename_axis("feature").reset_index().to_csv(paths["feature_importance"], index=False)

    flat = {k: v for k, v in results["stats"].items() if not isinstance(v, dict)}
    paths["area_statistics"] = str(out_dir / "area_statistics.csv")
    pd.DataFrame([flat]).T.rename(columns={0: "value"}).to_csv(paths["area_statistics"])
    return paths
