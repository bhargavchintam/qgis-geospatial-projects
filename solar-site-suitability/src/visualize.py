"""
Figures and the Folium web map for the solar site suitability project.

Every ``fig_*`` function returns a matplotlib Figure (used by app.py);
``make_all_figures`` saves the numbered PNGs to docs/figures/ and
``build_web_map`` returns a folium.Map for docs/map.html.
"""

from pathlib import Path

import folium
import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402
from scipy import ndimage  # noqa: E402

from .criteria import CONSTRAINT_LABELS  # noqa: E402
from .pipeline import CRITERIA_TITLES  # noqa: E402
from .suitability import CLASS_LABELS  # noqa: E402
from .utils import raster_bounds  # noqa: E402

DPI = 150
# "CartoDB positron" basemap; the explicit URL avoids the folium API-key warning
CARTO_POSITRON_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
CARTO_ATTR = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
              '&copy; <a href="https://carto.com/attributions">CARTO</a>')
CLASS_COLORS = ["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"]  # RdYlGn 5 classes
CONSTRAINT_COLORS = {
    0: "#f5f5f5",  # allowed
    1: "#3182bd",  # water
    2: "#de2d26",  # urban
    3: "#31a354",  # protected
    4: "#8c6d31",  # steep
    5: "#fd8d3c",  # residential buffer
}


def criteria_curve_labels(params: dict) -> dict:
    """Short text of each standardisation curve from the config parameters."""
    p = params or {}
    ghi = p.get("ghi", {})
    slope = p.get("slope", {})
    grid = p.get("grid_distance", {})
    road = p.get("road_distance", {})
    mapping = p.get("landuse", {}).get("mapping", {})
    return {
        "ghi": f"linear {ghi.get('lo', 5.0):.1f} -> {ghi.get('hi', 7.0):.1f} kWh/m²/day",
        "slope": f"1 up to {slope.get('ideal', 3.0):.0f}°, 0 at {slope.get('max_ok', 10.0):.0f}°",
        "aspect": "cosine, south = 1, flat = 1",
        "grid_distance": f"1 within {grid.get('full_score_within', 1000) / 1000:.0f} km, 0 at {grid.get('zero_at', 15000) / 1000:.0f} km",
        "road_distance": f"1 within {road.get('full_score_within', 1000) / 1000:.0f} km, 0 at {road.get('zero_at', 15000) / 1000:.0f} km",
        "landuse": "look-up: " + ", ".join(f"{k}={v}" for k, v in list(mapping.items())[:3]) if mapping else "look-up table",
    }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _extent(profile):
    west, south, east, north = raster_bounds(profile)
    return [west, east, south, north]


def _km_axes(ax):
    fmt = FuncFormatter(lambda v, _: f"{v / 1000:.0f}")
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)
    ax.set_xlabel("Easting (km, UTM 12N)")
    ax.set_ylabel("Northing (km)")


def _nan_transparent(cmap_name):
    cmap = matplotlib.colormaps[cmap_name].copy()
    cmap.set_bad(alpha=0.0)
    return cmap


def _draw_hillshade(ax, results, alpha=1.0):
    ax.imshow(results["hillshade"], cmap="gray", extent=_extent(results["profile"]),
              vmin=0, vmax=1, alpha=alpha, interpolation="nearest")


def _draw_vectors(ax, results, lines=True, substations=True, roads=False):
    vec = results["vectors"]
    if lines and len(vec["transmission_lines"]):
        vec["transmission_lines"].plot(ax=ax, color="#7b3294", linewidth=1.6, linestyle="-", zorder=5)
    if roads and len(vec["roads"]):
        vec["roads"].plot(ax=ax, color="#252525", linewidth=0.9, linestyle="--", zorder=5)
    if substations and len(vec["substations"]):
        vec["substations"].plot(ax=ax, color="#7b3294", marker="s", markersize=40,
                                edgecolor="white", linewidth=0.8, zorder=6)


def _draw_sites(ax, results, top_n=10, label=True, color="#e41a1c"):
    sites = results["sites"]
    if len(sites) == 0:
        return
    top = sites[sites["rank"] <= top_n]
    top.plot(ax=ax, facecolor="none", edgecolor=color, linewidth=1.5, zorder=7)
    if label:
        for _, row in top.iterrows():
            p = row.geometry.representative_point()
            ax.annotate(str(int(row["rank"])), (p.x, p.y), ha="center", va="center", fontsize=8,
                        fontweight="bold", color="white", zorder=8,
                        bbox=dict(boxstyle="circle,pad=0.25", fc=color, ec="white", lw=0.8))


def _masked(arr, mask=None):
    a = np.ma.masked_invalid(np.asarray(arr, dtype=float))
    if mask is not None:
        a = np.ma.masked_where(~np.asarray(mask, dtype=bool), a)
    return a


def save_fig(fig, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return str(path)


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------
def fig_hero(results, top_n=10):
    """2x2 overview: terrain, GHI, constrained suitability, top sites."""
    profile = results["profile"]
    ext = _extent(profile)
    fig, axes = plt.subplots(2, 2, figsize=(12, 10.5))

    ax = axes[0, 0]
    _draw_hillshade(ax, results)
    im = ax.imshow(results["dem"], cmap="terrain", extent=ext, alpha=0.55, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Elevation (m)")
    _draw_vectors(ax, results, roads=True)
    ax.set_title("Terrain (hillshade + DEM), roads and transmission lines")
    _km_axes(ax)

    ax = axes[0, 1]
    im = ax.imshow(results["ghi"], cmap="YlOrRd", extent=ext, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="GHI (kWh/m²/day)")
    ax.set_title("Solar resource (global horizontal irradiance)")
    _km_axes(ax)

    ax = axes[1, 0]
    im = ax.imshow(_masked(results["index"]), cmap=_nan_transparent("viridis"), extent=ext,
                   vmin=0, vmax=1, interpolation="nearest")
    ax.imshow(np.ma.masked_where(results["mask"], np.ones_like(results["mask"], dtype=float)),
              cmap=ListedColormap(["#9e9e9e"]), extent=ext, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Suitability index (0-1)")
    ax.set_title(f"AHP suitability (grey = excluded, {results['summary']['pct_area_excluded']:.0f}% of area)")
    _km_axes(ax)

    ax = axes[1, 1]
    _draw_hillshade(ax, results)
    ax.imshow(_masked(results["index"]), cmap=_nan_transparent("viridis"), extent=ext,
              vmin=0, vmax=1, alpha=0.45, interpolation="nearest")
    _draw_vectors(ax, results)
    _draw_sites(ax, results, top_n=top_n)
    n = min(top_n, len(results["sites"]))
    ax.set_title(f"Top {n} candidate sites (rank), {results['summary']['total_capacity_mw']:.0f} MW total")
    _km_axes(ax)

    fig.suptitle("Utility-scale solar site suitability, Hualapai Valley near Kingman, AZ (synthetic scene)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    return fig


def fig_terrain(results):
    """Hillshade and slope side by side."""
    ext = _extent(results["profile"])
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
    ax = axes[0]
    im = ax.imshow(results["hillshade"], cmap="gray", extent=ext, vmin=0, vmax=1, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Hillshade (0-1), azimuth 315°, altitude 45°")
    ax.set_title("Hillshade")
    _km_axes(ax)
    ax = axes[1]
    im = ax.imshow(results["slope"], cmap="magma", extent=ext, vmin=0, vmax=30, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Slope (degrees)")
    ax.contour(np.flipud(results["slope"]), levels=[15], colors="cyan", linewidths=0.6,
               extent=ext, origin="lower")
    ax.set_title("Slope (Horn 3x3), cyan line = 15° exclusion")
    _km_axes(ax)
    plt.tight_layout()
    return fig


def fig_criteria_panel(results):
    """2x3 grid of the six standardised criteria (0-1)."""
    ext = _extent(results["profile"])
    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    weights = results["weights"]
    curves = criteria_curve_labels(results.get("criteria_params"))
    for ax, (name, arr) in zip(axes.ravel(), results["criteria"].items()):
        im = ax.imshow(_masked(arr), cmap=_nan_transparent("viridis"), extent=ext, vmin=0, vmax=1,
                       interpolation="nearest")
        ax.set_title(f"{CRITERIA_TITLES[name]}  (w = {weights.get(name, 0):.3f})\n{curves[name]}",
                     fontsize=10)
        _km_axes(ax)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Score (0-1)")
    plt.tight_layout()
    return fig


def fig_constraints(results):
    """Excluded areas coloured by reason."""
    ext = _extent(results["profile"])
    reasons = results["reasons"]
    fig, ax = plt.subplots(figsize=(10, 8))
    _draw_hillshade(ax, results, alpha=0.6)
    codes = sorted(CONSTRAINT_LABELS)
    cmap = ListedColormap([CONSTRAINT_COLORS[c] for c in codes])
    norm = BoundaryNorm(np.array(codes + [codes[-1] + 1]) - 0.5, cmap.N)
    ax.imshow(np.ma.masked_where(reasons == 0, reasons), cmap=cmap, norm=norm, extent=ext,
              alpha=0.85, interpolation="nearest")
    _draw_vectors(ax, results, roads=True)
    pct = results["summary"]["pct_excluded_by_reason"]
    n_pix = reasons.size
    handles = [Patch(facecolor=CONSTRAINT_COLORS[0], edgecolor="grey",
                     label=f"Allowed ({100 * (reasons == 0).sum() / n_pix:.1f}%)")]
    for c in codes[1:]:
        handles.append(Patch(facecolor=CONSTRAINT_COLORS[c], label=f"{CONSTRAINT_LABELS[c]} ({pct[CONSTRAINT_LABELS[c]]:.1f}%)"))
    ax.legend(handles=handles, loc="lower left", fontsize=9, framealpha=0.9, title="Constraint (share of area)")
    ax.set_title(f"Constraint mapping: {results['summary']['pct_area_excluded']:.1f}% of the study area excluded")
    _km_axes(ax)
    plt.tight_layout()
    return fig


def fig_suitability(results):
    """Continuous index with class contours, and the 5-class map."""
    ext = _extent(results["profile"])
    index = results["index"]
    classes = results["classes"]
    thresholds = list(results["thresholds"])
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax = axes[0]
    _draw_hillshade(ax, results, alpha=0.5)
    im = ax.imshow(_masked(index), cmap=_nan_transparent("viridis"), extent=ext, vmin=0, vmax=1,
                   alpha=0.9, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Suitability index (0-1)")
    # Contours of a lightly smoothed index so the class boundaries read as
    # lines instead of pixel noise; the site threshold is drawn heavier.
    filled = ndimage.gaussian_filter(np.nan_to_num(index, nan=0.0), sigma=1.5)
    widths = [0.4] * (len(thresholds) - 1) + [1.0]
    cs = ax.contour(np.flipud(filled), levels=thresholds, colors="white", linewidths=widths, extent=ext,
                    origin="lower", alpha=0.9)
    ax.clabel(cs, levels=[thresholds[-1]], fmt="%.2f", fontsize=7)
    ax.set_title("Continuous suitability index with class contours (smoothed)")
    _km_axes(ax)

    ax = axes[1]
    _draw_hillshade(ax, results, alpha=0.5)
    cmap = ListedColormap(CLASS_COLORS)
    norm = BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], cmap.N)
    ax.imshow(np.ma.masked_where(classes == 0, classes), cmap=cmap, norm=norm, extent=ext,
              alpha=0.9, interpolation="nearest")
    table = results["class_table"]
    handles = [Patch(facecolor=CLASS_COLORS[k - 1],
                     label=f"{k} {CLASS_LABELS[k]} ({table.loc[table['class'] == k, 'pct_of_allowed'].iloc[0]:.1f}%)")
               for k in range(1, 6)]
    handles.append(Patch(facecolor="#bdbdbd", label="Excluded"))
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9, title="Class (% of allowed area)")
    ax.set_title(f"Suitability classes (boundaries {', '.join(f'{t:.2f}' for t in thresholds)})")
    _km_axes(ax)
    plt.tight_layout()
    return fig


def fig_candidate_sites(results, top_n=10):
    """Top-N candidate sites with rank labels, lines and substations."""
    ext = _extent(results["profile"])
    fig, ax = plt.subplots(figsize=(10, 8.5))
    _draw_hillshade(ax, results, alpha=0.8)
    ax.imshow(np.ma.masked_where(results["mask"], np.ones_like(results["mask"], dtype=float)),
              cmap=ListedColormap(["#bdbdbd"]), extent=ext, alpha=0.6, interpolation="nearest")
    ax.imshow(_masked(results["index"]), cmap=_nan_transparent("viridis"), extent=ext, vmin=0, vmax=1,
              alpha=0.35, interpolation="nearest")
    sites = results["sites"]
    if len(sites):
        sites.plot(ax=ax, facecolor="#fee08b", edgecolor="none", alpha=0.6, zorder=4)
    _draw_vectors(ax, results, roads=True)
    _draw_sites(ax, results, top_n=top_n)
    handles = [
        Patch(facecolor="#fee08b", edgecolor="#e41a1c", label=f"Candidate site (index >= {results['summary']['site_threshold']:.2f}, >= {results['summary']['min_site_area_ha']:.0f} ha)"),
        plt.Line2D([], [], color="#7b3294", linewidth=1.6, label="Transmission line"),
        plt.Line2D([], [], color="#7b3294", marker="s", linestyle="", markersize=7, label="Substation"),
        plt.Line2D([], [], color="#252525", linestyle="--", linewidth=0.9, label="Road"),
        Patch(facecolor="#bdbdbd", label="Excluded by constraints"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.92)
    n = min(top_n, len(sites))
    total = sites.head(n)["capacity_mw"].sum() if n else 0.0
    ax.set_title(f"Top {n} candidate sites ranked by suitability x sqrt(area): {total:.0f} MW")
    _km_axes(ax)
    plt.tight_layout()
    return fig


def fig_ahp_weights(results):
    """AHP weights bar chart and the pairwise matrix heat map."""
    weights = results["weights"]
    names = results["criteria_names"]
    matrix = np.asarray(results["pairwise_matrix"])
    cons = results["consistency"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1.1, 1]})

    ax = axes[0]
    order = sorted(names, key=lambda n: weights[n], reverse=True)
    vals = [weights[n] for n in order]
    colors = matplotlib.colormaps["viridis"](np.linspace(0.15, 0.9, len(order)))[::-1]
    bars = ax.barh([CRITERIA_TITLES[n] for n in order], vals, color=colors)
    ax.invert_yaxis()
    for b, v in zip(bars, vals):
        ax.text(v + 0.005, b.get_y() + b.get_height() / 2, f"{v:.3f} ({100 * v:.1f}%)", va="center", fontsize=9)
    ax.set_xlim(0, max(vals) * 1.35)
    ax.set_xlabel("AHP priority weight (row geometric mean)")
    ax.set_title(f"Criteria weights, CR = {cons['CR']:.3f} ({'consistent' if cons['is_consistent'] else 'NOT consistent'}, < 0.10)")
    ax.grid(axis="x", alpha=0.3)

    ax = axes[1]
    im = ax.imshow(np.log(matrix), cmap="RdBu_r", vmin=-np.log(9), vmax=np.log(9))
    ax.set_xticks(range(len(names)))
    ax.set_yticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(names, fontsize=8)
    for i in range(len(names)):
        for j in range(len(names)):
            v = matrix[i, j]
            ax.text(j, i, f"{v:.2f}" if v < 1 else f"{v:.0f}", ha="center", va="center", fontsize=8,
                    color="black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="log(pairwise ratio), Saaty 1-9 scale")
    ax.set_title(f"Pairwise comparison matrix (lambda_max = {cons['lambda_max']:.3f}, CI = {cons['CI']:.3f})")
    plt.tight_layout()
    return fig


def fig_site_capacity(results, top_n=10):
    """Capacity (MW) per ranked site with annual energy (GWh) on a second axis."""
    sites = results["sites"].head(top_n)
    fig, ax = plt.subplots(figsize=(10, 6))
    if len(sites) == 0:
        ax.text(0.5, 0.5, "No candidate sites found", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Site capacity")
        return fig
    x = np.arange(len(sites))
    bars = ax.bar(x, sites["capacity_mw"], color="#fdb863", edgecolor="#e66101", label="Capacity (MW-dc)")
    for b, (_, row) in zip(bars, sites.iterrows()):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{row['area_ha']:.0f} ha", ha="center",
                va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"#{int(r)}" for r in sites["rank"]])
    ax.set_xlabel("Site rank")
    ax.set_ylabel("Capacity (MW) at 2 ha per MW")
    ax.grid(axis="y", alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(x, sites["annual_gwh"], color="#5e3c99", marker="o", linewidth=1.8, label="Annual energy (GWh/yr)")
    ax2.set_ylabel("Annual energy (GWh/yr)")
    ax2.set_ylim(0, sites["annual_gwh"].max() * 1.25)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=9)
    ax.set_title(f"Developable capacity of the top {len(sites)} sites: {sites['capacity_mw'].sum():.0f} MW, "
                 f"{sites['annual_gwh'].sum():.0f} GWh/yr")
    plt.tight_layout()
    return fig


def make_all_figures(results, fig_dir, top_n=10) -> dict:
    """Save every figure to ``fig_dir`` and return {name: path}."""
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    builders = {
        "00_hero.png": lambda: fig_hero(results, top_n),
        "01_terrain.png": lambda: fig_terrain(results),
        "02_criteria_panel.png": lambda: fig_criteria_panel(results),
        "03_constraints.png": lambda: fig_constraints(results),
        "04_suitability.png": lambda: fig_suitability(results),
        "05_candidate_sites.png": lambda: fig_candidate_sites(results, top_n),
        "06_ahp_weights.png": lambda: fig_ahp_weights(results),
        "07_site_capacity.png": lambda: fig_site_capacity(results, top_n),
    }
    paths = {}
    for name, build in builders.items():
        paths[name] = save_fig(build(), fig_dir / name)
    return paths


# --------------------------------------------------------------------------
# web map
# --------------------------------------------------------------------------
def _downsample(arr, max_px=600):
    arr = np.asarray(arr)
    step = int(np.ceil(max(arr.shape) / max_px))
    return arr[::step, ::step] if step > 1 else arr


def array_to_rgba(arr, cmap_name="viridis", vmin=None, vmax=None, alpha=1.0, max_px=600):
    """Render a 2-D array to an RGBA uint8 image; NaN pixels are transparent."""
    a = _downsample(np.asarray(arr, dtype=float), max_px)
    vmin = np.nanmin(a) if vmin is None else vmin
    vmax = np.nanmax(a) if vmax is None else vmax
    norm = Normalize(vmin=vmin, vmax=vmax)
    rgba = matplotlib.colormaps[cmap_name](norm(np.nan_to_num(a, nan=vmin)))
    rgba[..., 3] = np.where(np.isnan(a), 0.0, alpha)
    return (rgba * 255).astype(np.uint8)


def build_web_map(results, top_n=10) -> folium.Map:
    """Folium map with suitability, constraints, sites and infrastructure."""
    profile = results["profile"]
    west, south, east, north = raster_bounds(profile)
    w, s, e, n = transform_bounds(profile["crs"], "EPSG:4326", west, south, east, north)
    bounds = [[s, w], [n, e]]
    center = [(s + n) / 2.0, (w + e) / 2.0]
    m = folium.Map(location=center, zoom_start=11, tiles=CARTO_POSITRON_URL, attr=CARTO_ATTR,
                   name="CartoDB positron")

    folium.raster_layers.ImageOverlay(
        image=array_to_rgba(results["hillshade"], "gray", 0, 1), bounds=bounds, opacity=0.5,
        name="Hillshade", show=False).add_to(m)
    folium.raster_layers.ImageOverlay(
        image=array_to_rgba(results["ghi"], "YlOrRd"), bounds=bounds, opacity=0.7,
        name="GHI (kWh/m²/day)", show=False).add_to(m)
    folium.raster_layers.ImageOverlay(
        image=array_to_rgba(results["index"], "viridis", 0, 1), bounds=bounds, opacity=0.75,
        name="Suitability index (0-1)").add_to(m)
    excluded = np.where(results["mask"], np.nan, 1.0)
    folium.raster_layers.ImageOverlay(
        image=array_to_rgba(excluded, "Greys", 0, 1.2), bounds=bounds, opacity=0.6,
        name="Constraint mask (grey = excluded)").add_to(m)

    vec = results["vectors"]
    if len(vec["protected_areas"]):
        folium.GeoJson(vec["protected_areas"].to_crs(4326), name="Protected areas",
                       style_function=lambda f: {"color": "#31a354", "weight": 1.5, "fillOpacity": 0.08},
                       tooltip=folium.GeoJsonTooltip(fields=["name", "area_ha"])).add_to(m)
    if len(vec["residential"]):
        folium.GeoJson(vec["residential"].to_crs(4326), name="Residential",
                       style_function=lambda f: {"color": "#de2d26", "weight": 1, "fillOpacity": 0.25},
                       tooltip=folium.GeoJsonTooltip(fields=["name", "area_ha"])).add_to(m)
    if len(vec["roads"]):
        folium.GeoJson(vec["roads"].to_crs(4326), name="Roads",
                       style_function=lambda f: {"color": "#252525", "weight": 3 if f["properties"]["road_type"] == "highway" else 2, "dashArray": "6 4"},
                       tooltip=folium.GeoJsonTooltip(fields=["name", "road_type"])).add_to(m)
    if len(vec["transmission_lines"]):
        folium.GeoJson(vec["transmission_lines"].to_crs(4326), name="Transmission lines",
                       style_function=lambda f: {"color": "#7b3294", "weight": 3},
                       tooltip=folium.GeoJsonTooltip(fields=["name", "voltage_kv", "length_km"])).add_to(m)
    sites = results["sites"]
    if len(sites):
        top = sites[sites["rank"] <= top_n].to_crs(4326)
        folium.GeoJson(
            top, name=f"Candidate sites (top {min(top_n, len(sites))})",
            style_function=lambda f: {"color": "#e41a1c", "weight": 2, "fillColor": "#fee08b", "fillOpacity": 0.5},
            tooltip=folium.GeoJsonTooltip(
                fields=["rank", "area_ha", "capacity_mw", "annual_gwh", "mean_suitability", "dist_to_grid_km"],
                aliases=["Rank", "Area (ha)", "Capacity (MW)", "Energy (GWh/yr)", "Mean suitability", "Distance to grid (km)"]),
        ).add_to(m)
        for _, row in top.iterrows():
            p = row.geometry.representative_point()
            folium.map.Marker(
                [p.y, p.x],
                icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:bold;color:white;background:#e41a1c;"
                                         f"border-radius:10px;width:20px;height:20px;line-height:20px;text-align:center;'>"
                                         f"{int(row['rank'])}</div>", icon_size=(20, 20), icon_anchor=(10, 10)),
            ).add_to(m)
    if len(vec["substations"]):
        sub_group = folium.FeatureGroup(name="Substations")
        for _, row in vec["substations"].to_crs(4326).iterrows():
            folium.CircleMarker([row.geometry.y, row.geometry.x], radius=6, color="white", weight=1.5,
                                fill=True, fill_color="#7b3294", fill_opacity=1.0,
                                tooltip=f"{row['name']} ({row['voltage_kv']} kV)").add_to(sub_group)
        sub_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds(bounds)
    return m
