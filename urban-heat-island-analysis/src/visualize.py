"""
Figures and the interactive Folium map for the UHI pipeline.

All figure functions take the ``results`` dict from ``pipeline.run_pipeline``
and write a PNG at dpi=150. ``build_web_map`` returns a ``folium.Map``.
"""

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm, Normalize
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
from rasterio.transform import array_bounds
import folium
import branca.colormap as bcm

from .uhi_classifier import UHI_CLASSES, UHI_COLORS
from .lulc_correlator import NLCD_CLASSES, NLCD_COLORS
from .utils import raster_bounds_wgs84

LST_CMAP = "RdYlBu_r"
MPI_CMAP = "magma"
PRIORITY_COLORS = {"High": "#d7191c", "Medium": "#fdae61", "Low": "#ffffbf"}
_KM = FuncFormatter(lambda v, _pos: f"{v / 1000:.1f}")


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def uhi_cmap_norm():
    """Discrete colormap + norm for the six UHI classes (0..5)."""
    cmap = ListedColormap([UHI_COLORS[i] for i in range(6)])
    norm = BoundaryNorm(np.arange(-0.5, 6.5, 1.0), cmap.N)
    return cmap, norm


def _extent(results: Dict):
    """(left, right, bottom, top) in map units for imshow."""
    p = results["profile"]
    h, w = results["lst"].shape
    west, south, east, north = array_bounds(h, w, p["transform"])
    return (west, east, south, north)


def _axes_km(ax, extent):
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.xaxis.set_major_formatter(_KM)
    ax.yaxis.set_major_formatter(_KM)
    ax.set_xlabel("UTM easting (km)")
    ax.set_ylabel("UTM northing (km)")
    ax.set_aspect("equal")


def _lst_limits(lst: np.ndarray):
    return float(np.nanpercentile(lst, 1)), float(np.nanpercentile(lst, 99))


def _draw_parks(ax, parks_gdf, color="#00e676", lw=1.2, label="Parks / green space"):
    if parks_gdf is not None and not parks_gdf.empty:
        parks_gdf.boundary.plot(ax=ax, color=color, linewidth=lw, label=label)


def _draw_lst(ax, results, cbar=True):
    lst = results["lst"]
    vmin, vmax = _lst_limits(lst)
    im = ax.imshow(lst, cmap=LST_CMAP, vmin=vmin, vmax=vmax, extent=_extent(results))
    if cbar:
        cb = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.set_label("Land surface temperature (°C)")
    return im


def _draw_uhi(ax, results, legend=True):
    cmap, norm = uhi_cmap_norm()
    uhi = results["uhi"].astype(float)
    uhi[uhi < 0] = np.nan
    im = ax.imshow(uhi, cmap=cmap, norm=norm, extent=_extent(results), interpolation="nearest")
    if legend:
        handles = [Patch(facecolor=UHI_COLORS[i], edgecolor="k", linewidth=0.3, label=UHI_CLASSES[i]) for i in range(6)]
        ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9, title="UHI class", title_fontsize=8)
    return im


def _draw_mpi(ax, results, cbar=True, parks=True):
    # MPI is 0 outside UHI zones (Neutral / Cool Island); show that as grey
    mpi = np.where(results["mpi"] > 0, results["mpi"], np.nan)
    ax.set_facecolor("#e6e6e6")
    im = ax.imshow(mpi, cmap=MPI_CMAP, vmin=0, vmax=1, extent=_extent(results))
    if parks:
        _draw_parks(ax, results.get("parks_gdf"))
    if cbar:
        cb = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.set_label("Mitigation Priority Index (0 to 1); grey = outside UHI zones")
    return im


def _draw_lst_by_lulc(ax, results, horizontal=True):
    df = results["lst_by_lulc"].sort_values("mean_lst", ascending=horizontal)
    colors = [NLCD_COLORS.get(int(c), "#888888") for c in df["lulc_code"]]
    if horizontal:
        ax.barh(df["lulc_name"], df["mean_lst"], xerr=df["std_lst"], color=colors, edgecolor="k", linewidth=0.4, capsize=2)
        ax.set_xlabel("Mean land surface temperature (°C)")
        lo = float(df["mean_lst"].min() - df["std_lst"].max() - 2)
        ax.set_xlim(max(lo, 0), float(df["mean_lst"].max() + df["std_lst"].max() + 2))
        ax.grid(axis="x", alpha=0.3)
    else:
        ax.bar(df["lulc_name"], df["mean_lst"], color=colors, edgecolor="k", linewidth=0.4)
        ax.set_ylabel("Mean LST (°C)")
        ax.tick_params(axis="x", rotation=60)
        ax.grid(axis="y", alpha=0.3)


# ----------------------------------------------------------------------
# individual figures
# ----------------------------------------------------------------------
def plot_hero(results: Dict, path: Path) -> Path:
    """2x2 overview: LST, UHI classes, mitigation priority, LST by land cover."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    ext = _extent(results)

    ax = axes[0, 0]
    _draw_lst(ax, results)
    _axes_km(ax, ext)
    ax.set_title("Land surface temperature (Landsat 8/9 B10, single-channel)")

    ax = axes[0, 1]
    _draw_uhi(ax, results)
    _axes_km(ax, ext)
    ax.set_title("UHI intensity classes (mean + k·std)")

    ax = axes[1, 0]
    _draw_mpi(ax, results)
    _axes_km(ax, ext)
    ax.set_title("Mitigation Priority Index (parks outlined)")

    ax = axes[1, 1]
    _draw_lst_by_lulc(ax, results, horizontal=True)
    ax.set_title("Mean LST by NLCD land cover class")

    s = results["summary"]
    fig.suptitle(
        f"Urban Heat Island Analysis, {s['study_area']}: mean LST {s['lst']['mean_c']:.1f} °C, "
        f"max {s['lst']['max_c']:.1f} °C, LST vs impervious r = {s['lst_vs_impervious']['pearson_r']:.2f}",
        fontsize=13,
    )
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def plot_lst_map(results: Dict, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    _draw_lst(ax, results)
    _draw_parks(ax, results.get("parks_gdf"), color="k", lw=0.8)
    _axes_km(ax, _extent(results))
    ax.set_title("Land surface temperature (°C), parks outlined in black")
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def plot_uhi_zones(results: Dict, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    _draw_uhi(ax, results)
    _axes_km(ax, _extent(results))
    s = results["summary"]
    ax.set_title(
        f"UHI intensity classes (Strong + Extreme = {s['uhi_strong_plus_extreme_percent']:.1f} % of area)"
    )
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def plot_mitigation_priority(results: Dict, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    _draw_mpi(ax, results, parks=True)
    pz = results.get("priority_gdf")
    if pz is not None and not pz.empty:
        high = pz[pz["priority_label"] == "High"]
        if not high.empty:
            high.boundary.plot(ax=ax, color="#00e5ff", linewidth=0.8, label="High priority zone")
    _axes_km(ax, _extent(results))
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
    s = results["summary"]
    ax.set_title(
        f"Mitigation Priority Index (high priority = {s['priority_area_ha']['high']:.0f} ha)"
    )
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def plot_lst_vs_impervious(results: Dict, path: Path, max_points: int = 8000, seed: int = 0) -> Path:
    lst = results["lst"].ravel()
    imp = results["impervious"].ravel()
    ok = ~np.isnan(lst) & ~np.isnan(imp)
    lst, imp = lst[ok], imp[ok]
    if lst.size > max_points:
        rng = np.random.default_rng(seed)
        idx = rng.choice(lst.size, max_points, replace=False)
        lst, imp = lst[idx], imp[idx]

    c = results["impervious_corr"]
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(imp, lst, s=6, alpha=0.35, c=lst, cmap=LST_CMAP, edgecolors="none")
    xs = np.array([0, 100])
    ax.plot(xs, c["intercept"] + c["slope"] * xs, color="k", lw=2,
            label=f"LST = {c['intercept']:.1f} + {c['slope']:.3f} × impervious")
    ax.text(0.03, 0.95, f"Pearson r = {c['pearson_r']:.3f}\n{c['interpretation']}\nn = {c['n_samples']:,}",
            transform=ax.transAxes, va="top", fontsize=10,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.9))
    ax.set_xlabel("Impervious surface (%)")
    ax.set_ylabel("Land surface temperature (°C)")
    ax.set_title("LST rises with impervious surface fraction")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def plot_lst_by_lulc(results: Dict, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    _draw_lst_by_lulc(ax, results, horizontal=True)
    ax.set_title("Mean LST by NLCD land cover class (bars sorted, whiskers = 1 std)")
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def plot_lulc_map(results: Dict, path: Path) -> Path:
    lulc = results["lulc"]
    codes = [c for c in sorted(NLCD_CLASSES) if np.any(lulc == c)]
    cmap = ListedColormap([NLCD_COLORS[c] for c in codes])
    index = np.full(lulc.shape, np.nan)
    for i, c in enumerate(codes):
        index[lulc == c] = i
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(index, cmap=cmap, vmin=-0.5, vmax=len(codes) - 0.5, extent=_extent(results), interpolation="nearest")
    _draw_parks(ax, results.get("parks_gdf"), color="k", lw=0.8)
    handles = [Patch(facecolor=NLCD_COLORS[c], edgecolor="k", linewidth=0.3, label=f"{c} {NLCD_CLASSES[c]}") for c in codes]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8, title="NLCD class")
    _axes_km(ax, _extent(results))
    ax.set_title("Land use / land cover input (NLCD codes)")
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)


def make_all_figures(results: Dict, fig_dir: Path) -> List[Path]:
    """Write every figure into ``fig_dir`` and return the paths."""
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    return [
        plot_hero(results, fig_dir / "00_hero.png"),
        plot_lst_map(results, fig_dir / "01_lst_map.png"),
        plot_uhi_zones(results, fig_dir / "02_uhi_zones.png"),
        plot_mitigation_priority(results, fig_dir / "03_mitigation_priority.png"),
        plot_lst_vs_impervious(results, fig_dir / "04_lst_vs_impervious.png"),
        plot_lst_by_lulc(results, fig_dir / "05_lst_by_lulc.png"),
        plot_lulc_map(results, fig_dir / "06_lulc_map.png"),
    ]


# ----------------------------------------------------------------------
# Folium map
# ----------------------------------------------------------------------
def array_to_rgba(arr: np.ndarray, cmap, vmin=None, vmax=None, norm=None, max_px: int = 600) -> np.ndarray:
    """Render an array to an RGBA uint8 image (NaN -> transparent), downsampled to ``max_px``."""
    arr = np.asarray(arr, dtype=float)
    step = int(np.ceil(max(arr.shape) / max_px))
    if step > 1:
        arr = arr[::step, ::step]
    if norm is None:
        norm = Normalize(vmin=np.nanmin(arr) if vmin is None else vmin,
                         vmax=np.nanmax(arr) if vmax is None else vmax)
    mappable = plt.get_cmap(cmap) if isinstance(cmap, str) else cmap
    rgba = mappable(norm(np.ma.masked_invalid(arr)))
    rgba[..., 3] = np.where(np.isnan(arr), 0.0, rgba[..., 3])
    return (rgba * 255).astype(np.uint8)


def build_web_map(results: Dict, zoom_start: int = 13) -> folium.Map:
    """
    Interactive map with LST and UHI-class raster overlays, the mitigation
    priority zones and the park polygons, plus a layer control.
    """
    import warnings

    profile = results["profile"]
    west, south, east, north = raster_bounds_wgs84(profile)
    bounds = [[south, west], [north, east]]
    with warnings.catch_warnings():
        # folium 0.20 warns that Carto may ask for an API key; the public
        # light_all tiles it emits still load without one
        warnings.filterwarnings("ignore", message=".*CartoDB tiles.*")
        m = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=zoom_start, tiles="CartoDB positron")

    lst = results["lst"]
    vmin, vmax = _lst_limits(lst)
    folium.raster_layers.ImageOverlay(
        image=array_to_rgba(lst, LST_CMAP, vmin=vmin, vmax=vmax),
        bounds=bounds, opacity=0.75, name="Land surface temperature (°C)", interactive=False,
    ).add_to(m)

    cmap, norm = uhi_cmap_norm()
    uhi = results["uhi"].astype(float)
    uhi[uhi < 0] = np.nan
    folium.raster_layers.ImageOverlay(
        image=array_to_rgba(uhi, cmap, norm=norm),
        bounds=bounds, opacity=0.75, name="UHI intensity class", show=False, interactive=False,
    ).add_to(m)

    pz = results.get("priority_gdf")
    if pz is not None and not pz.empty:
        folium.GeoJson(
            pz.to_crs(4326),
            name="Mitigation priority zones",
            style_function=lambda f: {
                "fillColor": PRIORITY_COLORS.get(f["properties"]["priority_label"], "#999999"),
                "color": "#333333", "weight": 0.8, "fillOpacity": 0.55,
            },
            tooltip=folium.GeoJsonTooltip(fields=["priority_label", "area_ha"], aliases=["Priority", "Area (ha)"]),
        ).add_to(m)

    parks = results.get("parks_gdf")
    if parks is not None and not parks.empty:
        fields = [c for c in ["name", "park_type", "area_ha"] if c in parks.columns]
        folium.GeoJson(
            parks.to_crs(4326),
            name="Parks and green space",
            style_function=lambda f: {"fillColor": "#2e7d32", "color": "#1b5e20", "weight": 1.2, "fillOpacity": 0.35},
            tooltip=folium.GeoJsonTooltip(fields=fields) if fields else None,
        ).add_to(m)

    legend = bcm.LinearColormap(
        colors=[matplotlib.colors.to_hex(plt.get_cmap(LST_CMAP)(x)) for x in np.linspace(0, 1, 9)],
        vmin=round(vmin, 1), vmax=round(vmax, 1), caption="Land surface temperature (°C)",
    )
    legend.add_to(m)

    class_legend = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;background:{UHI_COLORS[i]};'
        f'border:1px solid #444;margin-right:6px"></span>{UHI_CLASSES[i]}</div>' for i in range(6)
    )
    m.get_root().html.add_child(folium.Element(
        '<div style="position:fixed;bottom:30px;left:10px;z-index:9999;background:white;'
        'padding:8px 10px;border:1px solid #999;border-radius:4px;font-size:12px">'
        f'<b>UHI class</b>{class_legend}</div>'
    ))
    m.fit_bounds(bounds)
    folium.LayerControl(collapsed=False).add_to(m)
    return m
