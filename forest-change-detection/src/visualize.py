"""
Figures (matplotlib) and the interactive Folium web map.

Every ``plot_*`` function returns a matplotlib Figure. ``save_all_figures``
writes the eight portfolio figures to a folder and ``build_web_map`` returns a
``folium.Map`` with the T2 false-colour image, the change map, the loss
polygons and the road / river lines.
"""

import warnings
from pathlib import Path

import folium
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch
from rasterio.warp import transform_bounds

from .change_detection import CHANGE_CODES
from .classifier import LandCoverClassifier

matplotlib.use("Agg")

DPI = 150
CLASS_COLORS = {0: "#ffffff", 1: "#1b5e20", 2: "#e0c068", 3: "#3b7dd8", 4: "#8c6d4f", 5: "#8fd18f"}
CHANGE_COLORS = {0: "#ffffff", 1: "#1b5e20", 2: "#d2b48c", 3: "#d7191c", 4: "#a6d96a"}
DNBR_RANGE = (-0.5, 0.8)


# --------------------------------------------------------------------------- helpers
def _discrete_cmap(colors: dict):
    keys = sorted(colors)
    cmap = ListedColormap([colors[k] for k in keys])
    norm = BoundaryNorm([k - 0.5 for k in keys] + [keys[-1] + 0.5], cmap.N)
    return cmap, norm


def _extent_km(profile: dict):
    """Image extent in km relative to the scene's south-west corner."""
    t = profile["transform"]
    w = profile["width"] * t.a
    h = profile["height"] * abs(t.e)
    return [0, w / 1000.0, 0, h / 1000.0]


def _legend_patches(colors: dict, labels: dict, skip=(0,)):
    return [Patch(facecolor=colors[k], edgecolor="k", linewidth=0.3, label=labels[k])
            for k in sorted(colors) if k not in skip]


def _plot_gdf_outline(ax, gdf, profile, color="black", lw=0.6):
    """Draw polygon / line outlines in the km extent used by the rasters."""
    if gdf is None or len(gdf) == 0:
        return
    t = profile["transform"]
    x0 = t.c
    y0 = t.f + profile["height"] * t.e  # south edge
    for geom in gdf.geometry:
        parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
        for part in parts:
            if part.geom_type == "Polygon":
                xs, ys = part.exterior.xy
            else:
                xs, ys = part.xy
            ax.plot((np.asarray(xs) - x0) / 1000.0, (np.asarray(ys) - y0) / 1000.0,
                    color=color, linewidth=lw)
    ext = _extent_km(profile)
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])


def apply_layout(fig):
    """tight_layout, honouring an optional ``fig.tight_rect`` reserved area."""
    if getattr(fig, "skip_tight_layout", False):
        return fig
    rect = getattr(fig, "tight_rect", None)
    if rect is not None:
        fig.tight_layout(rect=rect)
    else:
        fig.tight_layout()
    return fig


def save_figure(fig, path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    apply_layout(fig)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


# --------------------------------------------------------------------------- panels
def _panel_false_color(ax, rgb, profile, title):
    ax.imshow(rgb, extent=_extent_km(profile), interpolation="nearest")
    ax.set_title(title)
    ax.set_xlabel("km")
    ax.set_ylabel("km")


def _panel_classes(ax, class_raster, profile, title):
    cmap, norm = _discrete_cmap(CLASS_COLORS)
    arr = np.ma.masked_equal(class_raster, 0)
    ax.imshow(arr, cmap=cmap, norm=norm, extent=_extent_km(profile), interpolation="nearest")
    ax.set_title(title)
    ax.set_xlabel("km")
    ax.set_ylabel("km")


def _panel_change(ax, change, profile, title, loss_gdf=None):
    cmap, norm = _discrete_cmap(CHANGE_COLORS)
    arr = np.ma.masked_equal(change, 0)
    ax.imshow(arr, cmap=cmap, norm=norm, extent=_extent_km(profile), interpolation="nearest")
    if loss_gdf is not None:
        _plot_gdf_outline(ax, loss_gdf, profile, color="black", lw=0.5)
    ax.set_title(title)
    ax.set_xlabel("km")
    ax.set_ylabel("km")


def _panel_confusion(ax, acc, title=None):
    cm = np.asarray(acc["confusion_matrix"])
    names = acc["class_names"]
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(names)))
    ax.set_yticks(range(len(names)))
    ax.set_xticklabels(names, rotation=35, ha="right", fontsize=8)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Reference")
    thresh = cm.max() / 2.0 if cm.max() > 0 else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=8,
                    color="white" if cm[i, j] > thresh else "black")
    ax.set_title(title or f"Confusion matrix  OA={acc['overall_accuracy']:.3f}  kappa={acc['kappa']:.3f}")
    return im


# --------------------------------------------------------------------------- figures
def plot_hero(results: dict, dates: dict = None):
    """2x2 overview: T2 false colour, change map, loss polygons over T2, confusion matrix."""
    profile = results["profile"]
    stats = results["stats"]
    d2 = (dates or {}).get("t2", "T2")
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    _panel_false_color(axes[0, 0], results["false_color_t2"], profile, f"Sentinel-2 false colour (NIR-R-G), {d2}")
    _panel_change(axes[0, 1], results["change"], profile,
                  f"Forest change: loss {stats['forest_loss_ha']:.1f} ha "
                  f"({stats['forest_loss_pct_of_t1']:.1f} % of T1 forest)")
    axes[0, 1].legend(handles=_legend_patches(CHANGE_COLORS, CHANGE_CODES), loc="lower left", fontsize=7)
    _panel_false_color(axes[1, 0], results["false_color_t2"], profile,
                       f"Loss patches ({stats['n_loss_patches']}) over {d2} image")
    _plot_gdf_outline(axes[1, 0], results["loss_gdf"], profile, color="#ffff00", lw=0.9)
    _plot_gdf_outline(axes[1, 0], results.get("roads"), profile, color="white", lw=0.8)
    _panel_confusion(axes[1, 1], results["accuracy"])
    fig.suptitle("Forest Change Detection with Sentinel-2, Rondônia, Brazil (synthetic scene)", fontsize=13)
    return fig


def plot_false_color_pair(results: dict, dates: dict = None):
    profile = results["profile"]
    d = dates or {}
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    _panel_false_color(axes[0], results["false_color_t1"], profile, f"T1 {d.get('t1', '')} false colour (NIR-R-G)")
    _panel_false_color(axes[1], results["false_color_t2"], profile, f"T2 {d.get('t2', '')} false colour (NIR-R-G)")
    fig.suptitle("Dense forest is bright red; cleared land is pale; water is dark; clouds are white")
    fig.tight_rect = [0, 0, 1, 0.95]
    return fig


def plot_dnbr(results: dict):
    profile = results["profile"]
    fig, ax = plt.subplots(figsize=(10, 7))
    arr = np.ma.masked_invalid(results["dnbr"])
    im = ax.imshow(arr, cmap="RdYlGn_r", vmin=DNBR_RANGE[0], vmax=DNBR_RANGE[1],
                   extent=_extent_km(profile), interpolation="nearest")
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("dNBR = NBR(T1) - NBR(T2)  (unitless)")
    thr = results["stats"].get("dnbr_loss_threshold", 0.27)
    cb.ax.axhline(thr, color="black", linewidth=1.2)
    cb.ax.text(-0.4, thr, f"loss >= {thr:.2f} ", va="center", ha="right", fontsize=8,
               transform=cb.ax.get_yaxis_transform())
    ax.set_title("Differenced Normalized Burn Ratio (positive = canopy removed; clouds masked)")
    ax.set_xlabel("km")
    ax.set_ylabel("km")
    return fig


def plot_classified_pair(results: dict, dates: dict = None):
    profile = results["profile"]
    d = dates or {}
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.6))
    _panel_classes(axes[0], results["class_t1"], profile, f"Random Forest land cover, T1 {d.get('t1', '')}")
    _panel_classes(axes[1], results["class_t2"], profile, f"Random Forest land cover, T2 {d.get('t2', '')} (clouds masked)")
    handles = _legend_patches(CLASS_COLORS, LandCoverClassifier.CLASSES)
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=10, frameon=False,
               bbox_to_anchor=(0.5, 0.01))
    fig.subplots_adjust(left=0.06, right=0.98, top=0.93, bottom=0.17, wspace=0.18)
    fig.skip_tight_layout = True  # manual layout leaves room for the shared legend
    return fig


def plot_change_map(results: dict):
    profile = results["profile"]
    stats = results["stats"]
    fig, ax = plt.subplots(figsize=(10, 8))
    _panel_change(ax, results["change"], profile,
                  f"Forest change map ({stats['evidence_rule']} rule, MMU {stats['mmu_ha']:.2f} ha); "
                  f"black outlines = loss patches", loss_gdf=results["loss_gdf"])
    _plot_gdf_outline(ax, results.get("roads"), profile, color="#444444", lw=1.0)
    _plot_gdf_outline(ax, results.get("river"), profile, color="#3b7dd8", lw=1.0)
    ax.legend(handles=_legend_patches(CHANGE_COLORS, CHANGE_CODES), loc="lower left", fontsize=8)
    return fig


def plot_confusion_matrix(results: dict):
    acc = results["accuracy"]
    fig, ax = plt.subplots(figsize=(8, 7))
    im = _panel_confusion(ax, acc, title=f"Held-out samples (n={acc['n_samples']}):  "
                                         f"OA = {acc['overall_accuracy']:.3f},  kappa = {acc['kappa']:.3f}")
    fig.colorbar(im, ax=ax, shrink=0.8, label="pixel count")
    return fig


def plot_patch_histogram(results: dict):
    gdf = results["loss_gdf"]
    stats = results["stats"]
    fig, ax = plt.subplots(figsize=(10, 6))
    if len(gdf) > 0:
        areas = gdf["area_ha"].to_numpy()
        bins = np.linspace(0, max(areas.max(), stats["mmu_ha"] * 2), 25)
        ax.hist(areas, bins=bins, color="#d7191c", edgecolor="black", alpha=0.85)
        ax.axvline(stats["mmu_ha"], color="black", linestyle="--", label=f"MMU {stats['mmu_ha']:.2f} ha")
        ax.axvline(areas.mean(), color="#1b5e20", linestyle="-", label=f"mean {areas.mean():.2f} ha")
        ax.legend()
    else:
        ax.text(0.5, 0.5, "No loss patches", ha="center", va="center", transform=ax.transAxes)
    ax.set_xlabel("Patch area (ha)")
    ax.set_ylabel("Number of patches")
    ax.set_title(f"Forest loss patch sizes: {stats['n_loss_patches']} patches, "
                 f"largest {stats['max_patch_ha']:.2f} ha, total {stats['forest_loss_ha']:.1f} ha")
    return fig


def plot_feature_importance(results: dict):
    imp = results["importances"].sort_values()
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = ["#2c7bb6" if not n.startswith("N") else "#1b5e20" for n in imp.index]
    ax.barh(imp.index, imp.values, color=colors, edgecolor="black", linewidth=0.4)
    for i, v in enumerate(imp.values):
        ax.text(v + 0.003, i, f"{v:.3f}", va="center", fontsize=8)
    ax.set_xlabel("Gini importance (fraction)")
    ax.set_title("Random Forest feature importance (bands in blue, indices in green)")
    ax.set_xlim(0, max(imp.values.max() * 1.2, 0.05))
    return fig


def save_all_figures(results: dict, fig_dir, dates: dict = None) -> dict:
    """Write the eight portfolio figures. Returns {name: path}."""
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    out["00_hero"] = save_figure(plot_hero(results, dates), fig_dir / "00_hero.png")
    out["01_false_color_t1_t2"] = save_figure(plot_false_color_pair(results, dates), fig_dir / "01_false_color_t1_t2.png")
    out["02_nbr_difference"] = save_figure(plot_dnbr(results), fig_dir / "02_nbr_difference.png")
    out["03_classified_t1_t2"] = save_figure(plot_classified_pair(results, dates), fig_dir / "03_classified_t1_t2.png")
    out["04_change_map"] = save_figure(plot_change_map(results), fig_dir / "04_change_map.png")
    out["05_confusion_matrix"] = save_figure(plot_confusion_matrix(results), fig_dir / "05_confusion_matrix.png")
    out["06_patch_size_histogram"] = save_figure(plot_patch_histogram(results), fig_dir / "06_patch_size_histogram.png")
    out["07_feature_importance"] = save_figure(plot_feature_importance(results), fig_dir / "07_feature_importance.png")
    return out


# --------------------------------------------------------------------------- web map
def _downsample(arr: np.ndarray, max_px: int = 600) -> np.ndarray:
    step = int(np.ceil(max(arr.shape[0], arr.shape[1]) / max_px))
    return arr[::step, ::step] if step > 1 else arr


def _rgb_to_rgba(rgb: np.ndarray, alpha_mask=None) -> np.ndarray:
    rows, cols = rgb.shape[:2]
    rgba = np.zeros((rows, cols, 4), dtype=np.uint8)
    rgba[..., :3] = rgb
    rgba[..., 3] = 255 if alpha_mask is None else np.where(alpha_mask, 255, 0).astype(np.uint8)
    return rgba


def _change_rgba(change: np.ndarray) -> np.ndarray:
    rows, cols = change.shape
    rgba = np.zeros((rows, cols, 4), dtype=np.uint8)
    rgba[change == 3] = (215, 25, 28, 230)
    rgba[change == 4] = (166, 217, 106, 230)
    return rgba


def _wgs84_bounds(profile: dict):
    t = profile["transform"]
    west, north = t.c, t.f
    east = west + profile["width"] * t.a
    south = north + profile["height"] * t.e
    w, s, e, n = transform_bounds(profile["crs"], "EPSG:4326", west, south, east, north)
    return [[s, w], [n, e]]


def build_web_map(results: dict, dates: dict = None) -> folium.Map:
    """
    Interactive Folium map: T2 false colour, change overlay (loss red, gain
    green), loss polygons with tooltip, roads and river, layer control.
    """
    profile = results["profile"]
    bounds = _wgs84_bounds(profile)
    lat = (bounds[0][0] + bounds[1][0]) / 2
    lon = (bounds[0][1] + bounds[1][1]) / 2
    d = dates or {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # folium warns about CartoDB API keys
        m = folium.Map(location=[lat, lon], zoom_start=13, tiles="CartoDB positron")
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    rgba = _downsample(_rgb_to_rgba(results["false_color_t2"]))
    folium.raster_layers.ImageOverlay(image=rgba, bounds=bounds, opacity=0.85,
                                      name=f"Sentinel-2 false colour T2 {d.get('t2', '')}").add_to(m)
    ch = _downsample(_change_rgba(results["change"]))
    folium.raster_layers.ImageOverlay(image=ch, bounds=bounds, opacity=0.75,
                                      name="Forest change (red = loss, green = gain)").add_to(m)

    gdf = results["loss_gdf"]
    if gdf is not None and len(gdf) > 0:
        g = gdf.copy()
        g["area_ha"] = g["area_ha"].round(2)
        if "dist_road_m" in g.columns:
            g["dist_road_m"] = g["dist_road_m"].round(0)
        fields = ["patch_id", "area_ha"] + (["dist_road_m"] if "dist_road_m" in g.columns else [])
        folium.GeoJson(
            g[fields + ["geometry"]].to_crs(4326),
            name="Forest loss patches",
            style_function=lambda f: {"color": "#7a0000", "weight": 1.2, "fillColor": "#d7191c", "fillOpacity": 0.15},
            tooltip=folium.GeoJsonTooltip(fields=fields, aliases=["Patch", "Area (ha)", "Dist. to road (m)"][:len(fields)]),
        ).add_to(m)

    roads = results.get("roads")
    if roads is not None and len(roads) > 0:
        folium.GeoJson(roads.to_crs(4326), name="Roads",
                       style_function=lambda f: {"color": "#333333", "weight": 3, "dashArray": "6,4"},
                       tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=["Road"])).add_to(m)
    river = results.get("river")
    if river is not None and len(river) > 0:
        folium.GeoJson(river.to_crs(4326), name="River",
                       style_function=lambda f: {"color": "#1f78b4", "weight": 3},
                       tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=["River"])).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds(bounds)
    return m
