"""
Figures and the Folium web map for the flood risk pipeline.

All figure functions take the ``results`` dict returned by
``src.pipeline.run_pipeline`` and save a PNG (dpi 150). ``build_web_map``
returns a ``folium.Map`` with raster overlays and vector layers.
"""

import warnings
from pathlib import Path
from typing import Dict, Optional

import folium
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import BoundaryNorm, LightSource, ListedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402

RISK_COLORS = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]
RISK_LABELS = ["Very Low", "Low", "Moderate", "High", "Very High"]
RISK_CMAP = ListedColormap(RISK_COLORS)
RISK_NORM = BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], RISK_CMAP.N)

FACILITY_STYLE = {  # type -> (marker, colour)
    "hospital": ("P", "#d62728"),
    "fire_station": ("^", "#ff7f0e"),
    "police_station": ("s", "#1f77b4"),
    "school": ("o", "#2ca02c"),
    "emergency_shelter": ("D", "#9467bd"),
    "power_station": ("X", "#8c564b"),
    "water_treatment": ("v", "#17becf"),
}
DPI = 150


# ----------------------------------------------------------------- helpers
def _extent_km(profile: dict):
    """Raster extent in km (easting, northing) for imshow."""
    t = profile["transform"]
    w, n = t.c, t.f
    e = w + t.a * profile["width"]
    s = n + t.e * profile["height"]
    return [w / 1000, e / 1000, s / 1000, n / 1000]


def _plot_streams(ax, streams_gdf: Optional[gpd.GeoDataFrame], color="#08306b", lw=1.0):
    if streams_gdf is None or len(streams_gdf) == 0:
        return
    for geom in streams_gdf.geometry:
        lines = geom.geoms if hasattr(geom, "geoms") else [geom]
        for line in lines:
            x, y = line.xy
            ax.plot(np.asarray(x) / 1000, np.asarray(y) / 1000, color=color, lw=lw, solid_capstyle="round")


def _plot_facilities(ax, facilities: Optional[gpd.GeoDataFrame], size=45, legend=True):
    """Scatter facilities by type; returns the legend handles."""
    handles = []
    if facilities is None or len(facilities) == 0:
        return handles
    for ftype, (marker, colour) in FACILITY_STYLE.items():
        sub = facilities[facilities["type"] == ftype] if "type" in facilities.columns else facilities.iloc[0:0]
        if len(sub) == 0:
            continue
        ax.scatter(sub.geometry.x / 1000, sub.geometry.y / 1000, marker=marker, c=colour, s=size,
                   edgecolor="black", linewidth=0.6, zorder=5)
        handles.append(Line2D([0], [0], marker=marker, color="w", markerfacecolor=colour,
                              markeredgecolor="black", markersize=7, label=ftype.replace("_", " ")))
    if legend and handles:
        ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.85, title="Facilities",
                  title_fontsize=7)
    return handles


def _hillshade(dem: np.ndarray, res: float) -> np.ndarray:
    ls = LightSource(azdeg=315, altdeg=45)
    return ls.hillshade(np.nan_to_num(dem, nan=float(np.nanmean(dem))), vert_exag=8, dx=res, dy=res)


def axes_labels(ax):
    ax.set_xlabel("Easting (km, EPSG:32615)")
    ax.set_ylabel("Northing (km)")


def draw_dem_streams(ax, results: Dict, title: str, colorbar=True):
    profile, ext = results["profile"], _extent_km(results["profile"])
    dem = results["dem_filled"]
    ax.imshow(_hillshade(dem, results["resolution"]), cmap="gray", extent=ext, vmin=0, vmax=1)
    im = ax.imshow(dem, cmap="terrain", extent=ext, alpha=0.6)
    _plot_streams(ax, results.get("streams_gdf"))
    ax.set_title(title)
    if colorbar:
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label="Elevation (m)")
    return im


def draw_index(ax, arr: np.ndarray, results: Dict, title: str, cmap: str, label: str, streams=True):
    ext = _extent_km(results["profile"])
    im = ax.imshow(arr, cmap=cmap, extent=ext, vmin=0, vmax=1)
    if streams:
        _plot_streams(ax, results.get("streams_gdf"), color="black", lw=0.6)
    ax.set_title(title)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label=label)
    return im


def draw_risk_classes(ax, results: Dict, title: str, legend=True):
    ext = _extent_km(results["profile"])
    classes = results["risk_classes"].astype(float)
    classes[classes == 0] = np.nan
    ax.imshow(classes, cmap=RISK_CMAP, norm=RISK_NORM, extent=ext, interpolation="nearest")
    _plot_streams(ax, results.get("streams_gdf"), color="#08306b", lw=0.7)
    handles = _plot_facilities(ax, results.get("facilities"), legend=False)
    ax.set_title(title)
    if legend:
        patches = [plt.Rectangle((0, 0), 1, 1, fc=c) for c in RISK_COLORS]
        leg = ax.legend(patches, RISK_LABELS, loc="upper right", fontsize=7, title="Risk class",
                        title_fontsize=7, framealpha=0.85)
        ax.add_artist(leg)
        if handles:
            ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.85,
                      title="Facilities", title_fontsize=7)


# ----------------------------------------------------------------- figures
def plot_hero(results: Dict, out_path: Path) -> Path:
    """2 x 2 overview: hillshade + streams, susceptibility, vulnerability, risk classes."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 11))
    draw_dem_streams(axes[0, 0], results, "Filled DEM, hillshade and D8 stream network")
    draw_index(axes[0, 1], results["susceptibility"], results,
                f"AHP flood susceptibility (CR = {results['ahp']['CR']:.3f})", "YlGnBu", "Susceptibility index (0-1)")
    draw_index(axes[1, 0], results["vulnerability"], results, "Socioeconomic vulnerability", "magma",
                "Vulnerability index (0-1)", streams=False)
    s = results["summary"]
    draw_risk_classes(axes[1, 1], results,
                       f"Flood risk classes ({s['risk_method']}), High+Very High = {s['high_very_high_pct']:.1f}%")
    for ax in axes.ravel():
        axes_labels(ax)
    fig.suptitle("Multi-criteria flood risk assessment, synthetic Harris County (TX) scene, EPSG:32615",
                 fontsize=13)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_dem_streams(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    s = results["summary"]
    draw_dem_streams(ax, results, f"Filled DEM with hillshade and streams (threshold {s['stream_threshold_cells']} cells, "
                                   f"{s['stream_length_km']:.1f} km)")
    axes_labels(ax)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_twi(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    ext = _extent_km(results["profile"])
    twi = results["twi"]
    im = ax.imshow(twi, cmap="viridis", extent=ext, vmin=np.nanpercentile(twi, 1), vmax=np.nanpercentile(twi, 99))
    _plot_streams(ax, results.get("streams_gdf"), color="white", lw=0.6)
    ax.set_title("Topographic Wetness Index, TWI = ln(a / tan b)")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03, label="TWI (dimensionless)")
    axes_labels(ax)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_susceptibility(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    w = results["ahp"]["weights"]
    top = ", ".join(f"{k} {v:.2f}" for k, v in list(w.items())[:3])
    draw_index(ax, results["susceptibility"], results,
                f"AHP flood susceptibility (weights: {top}, ...; CR = {results['ahp']['CR']:.3f})",
                "YlGnBu", "Susceptibility index (0-1)")
    axes_labels(ax)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_vulnerability(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    draw_index(ax, results["vulnerability"], results,
                "Vulnerability = 0.40 population + 0.35 infrastructure + 0.25 SVI", "magma",
                "Vulnerability index (0-1)", streams=False)
    _plot_facilities(ax, results.get("facilities"), size=35)
    axes_labels(ax)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_risk_map(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7.5))
    s = results["summary"]
    draw_risk_classes(ax, results,
                       f"Flood risk classes ({s['risk_method']}): {s['population_high_very_high']:,} people and "
                       f"{s['facilities_high_very_high']} facilities in High / Very High")
    axes_labels(ax)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_scenarios(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    sc = results["scenarios"]
    rps = list(sc.keys())
    high = [sc[rp]["high_risk_percent"] for rp in rps]
    vhigh = [sc[rp]["very_high_risk_percent"] for rp in rps]
    x = np.arange(len(rps))
    b1 = ax.bar(x - 0.18, high, 0.36, color="#fdae61", edgecolor="black", label="High + Very High")
    b2 = ax.bar(x + 0.18, vhigh, 0.36, color="#d7191c", edgecolor="black", label="Very High only")
    ax.bar_label(b1, fmt="%.1f%%", fontsize=8)
    ax.bar_label(b2, fmt="%.1f%%", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{rp}-yr\n(x{sc[rp]['factor']:.2f})" for rp in rps])
    ax.set_ylabel("Share of study area (%)")
    ax.set_xlabel("Return period (hazard scale factor)")
    ax.set_title("High-risk area by return period")
    ax2 = ax.twinx()
    pop = [sc[rp]["population_high_very_high"] for rp in rps]
    ax2.plot(x, pop, "o-", color="#08306b", label="People in High + Very High")
    ax2.set_ylabel("Estimated people in High + Very High")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def plot_ahp_weights(results: Dict, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    w = results["ahp"]["weights"]
    names = list(w.keys())[::-1]
    vals = [w[n] for n in names]
    bars = ax.barh(names, vals, color=plt.cm.viridis(np.linspace(0.15, 0.9, len(names))), edgecolor="black")
    ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
    ax.set_xlim(0, max(vals) * 1.25)
    ax.set_xlabel("AHP priority weight (row geometric mean)")
    a = results["ahp"]
    ax.set_title(f"AHP criteria weights: lambda_max = {a['lambda_max']:.3f}, CI = {a['CI']:.4f}, "
                 f"CR = {a['CR']:.4f} ({'consistent' if a['is_consistent'] else 'inconsistent'})")
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def make_all_figures(results: Dict, fig_dir: Path) -> Dict[str, Path]:
    """Write every figure into fig_dir and return {name: path}."""
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    return {
        "hero": plot_hero(results, fig_dir / "00_hero.png"),
        "dem_streams": plot_dem_streams(results, fig_dir / "01_dem_streams.png"),
        "twi": plot_twi(results, fig_dir / "02_twi.png"),
        "susceptibility": plot_susceptibility(results, fig_dir / "03_susceptibility.png"),
        "vulnerability": plot_vulnerability(results, fig_dir / "04_vulnerability.png"),
        "risk_map": plot_risk_map(results, fig_dir / "05_risk_map.png"),
        "scenarios": plot_scenarios(results, fig_dir / "06_scenarios.png"),
        "ahp_weights": plot_ahp_weights(results, fig_dir / "07_ahp_weights.png"),
    }


# ----------------------------------------------------------------- web map
def _array_to_rgba(arr: np.ndarray, cmap: str, vmin=0.0, vmax=1.0, max_px: int = 600) -> np.ndarray:
    """Render an array to an RGBA uint8 image (NaN transparent), downsampled to max_px."""
    arr = np.asarray(arr, dtype=np.float64)
    step = max(1, int(np.ceil(max(arr.shape) / max_px)))
    arr = arr[::step, ::step]
    norm = np.clip((arr - vmin) / (vmax - vmin + 1e-12), 0, 1)
    rgba = plt.get_cmap(cmap)(norm)
    rgba[..., 3] = np.where(np.isnan(arr), 0.0, 1.0)
    return (rgba * 255).astype(np.uint8)


def build_web_map(results: Dict, boundary: Optional[gpd.GeoDataFrame] = None) -> folium.Map:
    """
    Folium map with risk and susceptibility overlays, the stream network,
    risk zone polygons and facility markers (tooltip shows type and risk).
    """
    profile = results["profile"]
    t = profile["transform"]
    west, north = t.c, t.f
    east = west + t.a * profile["width"]
    south = north + t.e * profile["height"]
    w, s, e, n = transform_bounds(profile["crs"], "EPSG:4326", west, south, east, north)
    bounds = [[s, w], [n, e]]
    center = [(s + n) / 2, (w + e) / 2]

    with warnings.catch_warnings():  # folium >= 0.20 warns about CartoDB keys; tiles still serve
        warnings.simplefilter("ignore", UserWarning)
        m = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron")
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)

    folium.raster_layers.ImageOverlay(
        image=_array_to_rgba(results["susceptibility"], "YlGnBu"), bounds=bounds, opacity=0.75,
        name="Flood susceptibility (AHP)", show=False,
    ).add_to(m)
    folium.raster_layers.ImageOverlay(
        image=_array_to_rgba(results["vulnerability"], "magma"), bounds=bounds, opacity=0.75,
        name="Vulnerability", show=False,
    ).add_to(m)
    folium.raster_layers.ImageOverlay(
        image=_array_to_rgba(results["risk"], "YlOrRd"), bounds=bounds, opacity=0.75, name="Flood risk index",
    ).add_to(m)

    zones = results["risk_zones"]
    if zones is not None and len(zones):
        zones_wgs = zones.to_crs(4326)
        zones_wgs["geometry"] = zones_wgs.geometry.simplify(0.0002)
        folium.GeoJson(
            zones_wgs,
            name="Risk zones (classes)",
            style_function=lambda f: {
                "fillColor": RISK_COLORS[int(f["properties"]["risk_class"]) - 1],
                "color": "#555555", "weight": 0.4, "fillOpacity": 0.45,
            },
            tooltip=folium.GeoJsonTooltip(fields=["risk_label", "area_km2", "area_pct"],
                                          aliases=["Risk class", "Area (km2)", "Area (%)"]),
            show=False,
        ).add_to(m)

    streams = results.get("streams_gdf")
    if streams is not None and len(streams):
        folium.GeoJson(
            streams.to_crs(4326), name="Stream network (D8)",
            style_function=lambda f: {"color": "#08306b", "weight": 2.2, "opacity": 0.9},
            tooltip=folium.GeoJsonTooltip(fields=["upstream_km2", "length_m"],
                                          aliases=["Upstream area (km2)", "Length (m)"]),
        ).add_to(m)

    if boundary is not None and len(boundary):
        folium.GeoJson(
            boundary.to_crs(4326), name="Study boundary",
            style_function=lambda f: {"color": "#333333", "weight": 1.5, "fill": False, "dashArray": "6 4"},
        ).add_to(m)

    fac = results.get("facilities")
    if fac is not None and len(fac):
        fg = folium.FeatureGroup(name="Critical infrastructure")
        for _, row in fac.to_crs(4326).iterrows():
            ftype = str(row.get("type", "facility"))
            colour = FACILITY_STYLE.get(ftype, ("o", "#333333"))[1]
            risk_label = str(row.get("risk_label", ""))
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x], radius=6, color="black", weight=1,
                fill=True, fill_color=colour, fill_opacity=0.95,
                tooltip=f"{row.get('name', ftype)}<br>type: {ftype}<br>risk: {risk_label}",
            ).add_to(fg)
        fg.add_to(m)

    m.fit_bounds(bounds)
    folium.LayerControl(collapsed=False).add_to(m)
    return m
