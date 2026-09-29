"""
Area statistics and text summary for the forest change results.
"""

import numpy as np
import pandas as pd


def area_statistics(class_t1: np.ndarray, class_t2: np.ndarray, change: np.ndarray,
                    pixel_area_ha: float, years: float, loss_gdf=None,
                    forest_class: int = 1, road_distance_m: float = 500.0,
                    class_names=None) -> dict:
    """
    Summarise forest area and change.

    Forest area at each date is counted on pixels that are valid (non-zero) on
    BOTH dates so the two totals are comparable. Loss / gain come from the
    final change raster (codes 3 and 4). Patch statistics come from
    ``loss_gdf`` when given (needs ``area_ha`` and, for the road share,
    ``dist_road_m``).

    Returns a flat dict of numbers (ha, %, counts) plus ``class_area_t1_ha``
    and ``class_area_t2_ha`` sub-dicts.
    """
    c1 = np.asarray(class_t1)
    c2 = np.asarray(class_t2)
    ch = np.asarray(change)
    valid = (c1 > 0) & (c2 > 0)

    forest_t1_ha = float(np.count_nonzero(valid & (c1 == forest_class)) * pixel_area_ha)
    forest_t2_ha = float(np.count_nonzero(valid & (c2 == forest_class)) * pixel_area_ha)
    loss_ha = float(np.count_nonzero(ch == 3) * pixel_area_ha)
    gain_ha = float(np.count_nonzero(ch == 4) * pixel_area_ha)
    loss_pct = 100.0 * loss_ha / forest_t1_ha if forest_t1_ha > 0 else float("nan")
    annual_rate = loss_pct / years if years > 0 else float("nan")

    stats = {
        "valid_area_ha": float(np.count_nonzero(valid) * pixel_area_ha),
        "masked_area_ha": float(np.count_nonzero(~valid) * pixel_area_ha),
        "forest_area_t1_ha": forest_t1_ha,
        "forest_area_t2_ha": forest_t2_ha,
        "forest_loss_ha": loss_ha,
        "forest_loss_pct_of_t1": loss_pct,
        "annual_loss_rate_pct": annual_rate,
        "forest_gain_ha": gain_ha,
        "years_between": float(years),
        "n_loss_patches": 0,
        "mean_patch_ha": float("nan"),
        "max_patch_ha": float("nan"),
        "median_patch_ha": float("nan"),
        "loss_share_near_roads_pct": float("nan"),
        "road_distance_m": float(road_distance_m),
    }

    if loss_gdf is not None and len(loss_gdf) > 0:
        areas = loss_gdf["area_ha"].to_numpy(dtype=float)
        stats["n_loss_patches"] = int(len(loss_gdf))
        stats["mean_patch_ha"] = float(areas.mean())
        stats["max_patch_ha"] = float(areas.max())
        stats["median_patch_ha"] = float(np.median(areas))
        if "dist_road_m" in loss_gdf.columns and areas.sum() > 0:
            near = loss_gdf["dist_road_m"].to_numpy(dtype=float) <= road_distance_m
            stats["loss_share_near_roads_pct"] = float(100.0 * areas[near].sum() / areas.sum())

    names = class_names or {}
    classes = sorted(set(np.unique(c1[valid]).tolist()) | set(np.unique(c2[valid]).tolist()))
    stats["class_area_t1_ha"] = {
        names.get(int(k), str(k)): float(np.count_nonzero(valid & (c1 == k)) * pixel_area_ha) for k in classes
    }
    stats["class_area_t2_ha"] = {
        names.get(int(k), str(k)): float(np.count_nonzero(valid & (c2 == k)) * pixel_area_ha) for k in classes
    }
    return stats


def class_area_table(stats: dict) -> pd.DataFrame:
    """Class area at T1 and T2 as a DataFrame."""
    t1 = stats.get("class_area_t1_ha", {})
    t2 = stats.get("class_area_t2_ha", {})
    rows = []
    for name in t1:
        rows.append({"class": name, "area_t1_ha": t1[name], "area_t2_ha": t2.get(name, 0.0),
                     "difference_ha": t2.get(name, 0.0) - t1[name]})
    return pd.DataFrame(rows)


def summary_lines(stats: dict, acc: dict, importances=None, header: str = "Forest change summary") -> list:
    """Plain-text summary lines for the console and the README."""
    lines = []
    bar = "=" * 62
    lines.append(bar)
    lines.append(f" {header}")
    lines.append(bar)
    lines.append(f" Overall accuracy (held-out)      : {acc['overall_accuracy']:.3f}")
    lines.append(f" Kappa                            : {acc['kappa']:.3f}")
    lines.append(f" Held-out test samples            : {acc['n_samples']}")
    lines.append(" Per-class accuracy (producer's / user's):")
    for _, r in acc["per_class"].iterrows():
        lines.append(f"   {int(r['class'])} {r['name']:<16s} PA {r['producers_accuracy']:.3f}   UA {r['users_accuracy']:.3f}")
    lines.append("-" * 62)
    lines.append(f" Forest area T1                   : {stats['forest_area_t1_ha']:.1f} ha")
    lines.append(f" Forest area T2                   : {stats['forest_area_t2_ha']:.1f} ha")
    lines.append(f" Forest loss                      : {stats['forest_loss_ha']:.1f} ha "
                 f"({stats['forest_loss_pct_of_t1']:.2f} % of T1 forest)")
    lines.append(f" Annual loss rate                 : {stats['annual_loss_rate_pct']:.2f} %/yr "
                 f"over {stats['years_between']:.1f} yr")
    lines.append(f" Forest gain                      : {stats['forest_gain_ha']:.1f} ha")
    lines.append(f" Loss patches (after MMU)         : {stats['n_loss_patches']}")
    lines.append(f" Mean / max patch                 : {stats['mean_patch_ha']:.2f} / {stats['max_patch_ha']:.2f} ha")
    lines.append(f" Loss within {int(stats['road_distance_m'])} m of roads       : "
                 f"{stats['loss_share_near_roads_pct']:.1f} %")
    if "truth_loss_ha" in stats:
        lines.append(f" Synthetic truth loss             : {stats['truth_loss_ha']:.1f} ha "
                     f"(detected {stats['truth_loss_detected_pct']:.1f} %)")
    if importances is not None:
        top = importances.head(3)
        top_txt = ", ".join(f"{k} {v:.2f}" for k, v in top.items())
        lines.append(f" Top 3 features                   : {top_txt}")
    lines.append(bar)
    return lines
