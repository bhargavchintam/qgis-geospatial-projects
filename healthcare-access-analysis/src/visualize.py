"""
Figures (matplotlib) and the interactive Folium map.

Every ``plot_*`` function returns the matplotlib Figure and saves it when
``out_path`` is given. ``build_web_map`` returns a folium.Map.
"""

import warnings
from pathlib import Path

import folium
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from branca.colormap import LinearColormap
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

matplotlib.use("Agg")

DPI = 150
FIGSIZE = (10, 7)

# colour, line width, z-order per road class
ROAD_STYLE = {
    "residential": ("#b8b8b8", 0.45, 1),
    "secondary": ("#f4a261", 1.1, 2),
    "primary": ("#d62828", 1.6, 3),
    "motorway": ("#5a189a", 2.4, 4),
}
ROAD_LABEL = {
    "residential": "Residential (30 km/h)",
    "secondary": "Secondary (50 km/h)",
    "primary": "Primary arterial (65 km/h)",
    "motorway": "Motorway (100 km/h)",
}
ISO_COLOURS = {5: "#ffffb2", 10: "#fecc5c", 15: "#fd8d3c", 20: "#f03b20", 30: "#bd0026"}
RIVER_COLOUR = "#7fb3d5"
HOSPITAL_COLOUR = "#c1121f"
SITE_COLOUR = "#2a9d8f"


def _save(fig, out_path):
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=DPI)
    return fig


def _finish_axes(ax, title, bounds=None):
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_aspect("equal")
    ax.set_xlabel("Easting (m, EPSG:32611)", fontsize=8)
    ax.set_ylabel("Northing (m)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.ticklabel_format(style="plain", useOffset=False)
    if bounds is not None:
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])


def _draw_river(ax, river):
    if river is not None and len(river):
        river.plot(ax=ax, color=RIVER_COLOUR, alpha=0.85, edgecolor="none", zorder=0.5)


def _draw_roads(ax, edges, faint=False):
    for cls, (colour, lw, z) in ROAD_STYLE.items():
        sub = edges[edges["highway"] == cls]
        if len(sub):
            sub.plot(ax=ax, color=colour, linewidth=lw * (0.6 if faint else 1.0),
                     alpha=0.5 if faint else 1.0, zorder=z)


def _draw_hospitals(ax, hospitals, label="Existing hospital"):
    if hospitals is None or not len(hospitals):
        return
    ax.scatter(hospitals.geometry.x, hospitals.geometry.y, marker="P", s=140,
               c=HOSPITAL_COLOUR, edgecolors="white", linewidths=0.8, zorder=10, label=label)


def _draw_sites(ax, sites, annotate=True):
    if sites is None or not len(sites):
        return
    ax.scatter(sites.geometry.x, sites.geometry.y, marker="*", s=320, c=SITE_COLOUR,
               edgecolors="black", linewidths=0.8, zorder=11, label="Proposed site")
    if annotate:
        for _, row in sites.iterrows():
            txt = f"Site {int(row['step'])}"
            if "new_population" in row:
                txt += f"\n+{int(round(row['new_population'])):,} people"
            ax.annotate(txt, (row.geometry.x, row.geometry.y), xytext=(8, 8),
                        textcoords="offset points", fontsize=7.5, fontweight="bold",
                        color="black", zorder=12,
                        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=SITE_COLOUR, alpha=0.9))


def _bounds(*gdfs):
    b = None
    for g in gdfs:
        if g is None or not len(g):
            continue
        tb = g.total_bounds
        b = tb if b is None else [min(b[0], tb[0]), min(b[1], tb[1]), max(b[2], tb[2]), max(b[3], tb[3])]
    return b


# ---------------------------------------------------------------- panels --

def draw_road_network(ax, edges, hospitals=None, river=None, title="Road network by class"):
    _draw_river(ax, river)
    _draw_roads(ax, edges)
    bridges = edges[edges["bridge"]] if "bridge" in edges else edges.iloc[0:0]
    if len(bridges):
        bridges.plot(ax=ax, color="black", linewidth=3.2, zorder=5)
    _draw_hospitals(ax, hospitals)
    handles = [Line2D([0], [0], color=c, lw=max(lw * 1.6, 1.2), label=ROAD_LABEL[k])
               for k, (c, lw, _) in ROAD_STYLE.items()]
    if len(bridges):
        handles.append(Line2D([0], [0], color="black", lw=3, label=f"Bridge ({len(bridges)})"))
    if river is not None and len(river):
        handles.append(Patch(facecolor=RIVER_COLOUR, label="River"))
    if hospitals is not None and len(hospitals):
        handles.append(Line2D([0], [0], marker="P", color="w", markerfacecolor=HOSPITAL_COLOUR,
                              markersize=11, label="Hospital"))
    ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.9).set_zorder(20)
    _finish_axes(ax, title, _bounds(edges))


def draw_isochrones(ax, iso, edges=None, hospitals=None, river=None,
                    title="Drive-time isochrones from the nearest hospital"):
    _draw_river(ax, river)
    if edges is not None:
        _draw_roads(ax, edges, faint=True)
    iso_sorted = iso.sort_values("max_minutes", ascending=False)
    handles = []
    for _, row in iso_sorted.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        colour = ISO_COLOURS.get(int(row["max_minutes"]), "#800026")
        iso_sorted[iso_sorted["max_minutes"] == row["max_minutes"]].plot(
            ax=ax, color=colour, alpha=0.75, edgecolor="none", zorder=6)
    for _, row in iso_sorted.sort_values("max_minutes").iterrows():
        colour = ISO_COLOURS.get(int(row["max_minutes"]), "#800026")
        handles.append(Patch(facecolor=colour, alpha=0.85,
                             label=f"{int(row['min_minutes'])} to {int(row['max_minutes'])} min"))
    if river is not None and len(river):
        river.plot(ax=ax, color=RIVER_COLOUR, alpha=0.9, edgecolor="none", zorder=7)
        handles.append(Patch(facecolor=RIVER_COLOUR, label="River"))
    _draw_hospitals(ax, hospitals)
    if hospitals is not None and len(hospitals):
        handles.append(Line2D([0], [0], marker="P", color="w", markerfacecolor=HOSPITAL_COLOUR,
                              markersize=11, label="Hospital"))
    ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.9, title="Travel time",
              title_fontsize=7).set_zorder(20)
    _finish_axes(ax, title, _bounds(edges if edges is not None else iso))


def draw_choropleth(ax, blocks, column, cmap, label, hospitals=None, sites=None, title="",
                    vmin=None, vmax=None):
    blocks.plot(ax=ax, column=column, cmap=cmap, edgecolor="white", linewidth=0.15,
                legend=True, vmin=vmin, vmax=vmax,
                legend_kwds={"label": label, "shrink": 0.75, "pad": 0.02}, zorder=1)
    _draw_hospitals(ax, hospitals)
    _draw_sites(ax, sites, annotate=False)
    handles = []
    if hospitals is not None and len(hospitals):
        handles.append(Line2D([0], [0], marker="P", color="w", markerfacecolor=HOSPITAL_COLOUR,
                              markersize=11, label="Existing hospital"))
    if sites is not None and len(sites):
        handles.append(Line2D([0], [0], marker="*", color="w", markerfacecolor=SITE_COLOUR,
                              markeredgecolor="black", markersize=14, label="Proposed site"))
    if handles:
        ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.9).set_zorder(20)
    _finish_axes(ax, title, _bounds(blocks))


def draw_underserved(ax, blocks, hospitals=None, sites=None, river=None, edges=None,
                     title="Underserved blocks and proposed sites"):
    blocks.plot(ax=ax, color="#ececec", edgecolor="white", linewidth=0.2, zorder=1)
    und = blocks[blocks["underserved"].astype(bool)]
    if len(und):
        und.plot(ax=ax, color="#e63946", alpha=0.55, edgecolor="#9d0208", linewidth=0.3,
                 hatch="///", zorder=2)
    if edges is not None:
        _draw_roads(ax, edges, faint=True)
    if river is not None and len(river):
        river.plot(ax=ax, color=RIVER_COLOUR, alpha=0.9, edgecolor="none", zorder=5)
    _draw_hospitals(ax, hospitals)
    _draw_sites(ax, sites, annotate=True)
    pop = int(und["population"].sum()) if len(und) else 0
    handles = [Patch(facecolor="#e63946", alpha=0.55, hatch="///", edgecolor="#9d0208",
                     label=f"Underserved ({len(und)} blocks, {pop:,} people)"),
               Line2D([0], [0], marker="P", color="w", markerfacecolor=HOSPITAL_COLOUR,
                      markersize=11, label="Existing hospital")]
    if sites is not None and len(sites):
        handles.append(Line2D([0], [0], marker="*", color="w", markerfacecolor=SITE_COLOUR,
                              markeredgecolor="black", markersize=14, label="Proposed site"))
    ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.9).set_zorder(20)
    _finish_axes(ax, title, _bounds(blocks))


# --------------------------------------------------------------- figures --

def plot_road_network(edges, hospitals=None, river=None, out_path=None):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    draw_road_network(ax, edges, hospitals, river,
                      title=f"Synthetic road network: {len(edges):,} segments by class")
    plt.tight_layout()
    _save(fig, out_path)
    return fig


def plot_isochrones(iso, edges=None, hospitals=None, river=None, out_path=None):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    draw_isochrones(ax, iso, edges, hospitals, river)
    plt.tight_layout()
    _save(fig, out_path)
    return fig


def plot_travel_time_choropleth(blocks, hospitals=None, out_path=None):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    draw_choropleth(ax, blocks, "tt_nearest_min", "YlOrRd",
                    "Drive time to nearest hospital (minutes)", hospitals=hospitals,
                    title="Block travel time to the nearest hospital")
    plt.tight_layout()
    _save(fig, out_path)
    return fig


def plot_access_score(blocks, hospitals=None, out_path=None, threshold_min=15):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    draw_choropleth(ax, blocks, "access_score", "viridis",
                    "2SFCA access score (beds per 1,000 residents)", hospitals=hospitals,
                    title=f"Two-step floating catchment access score ({threshold_min:g} min catchment)")
    plt.tight_layout()
    _save(fig, out_path)
    return fig


def plot_underserved_and_sites(blocks, hospitals=None, sites=None, river=None, edges=None,
                               out_path=None):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    draw_underserved(ax, blocks, hospitals, sites, river, edges)
    plt.tight_layout()
    _save(fig, out_path)
    return fig


def plot_coverage_before_after(steps, threshold_min=15, out_path=None):
    """
    Bar chart of % population within the threshold. ``steps`` is a list of
    (label, pct) pairs, e.g. [("Existing", 89.3), ("+ Site 1", 99.7), ...].
    """
    labels = [s[0] for s in steps]
    vals = [s[1] for s in steps]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    colours = [HOSPITAL_COLOUR] + [SITE_COLOUR] * (len(vals) - 1)
    bars = ax.bar(labels, vals, color=colours, edgecolor="black", linewidth=0.6, width=0.6)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:.1f} %", (b.get_x() + b.get_width() / 2, v), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=10, fontweight="bold")
    ax.set_ylim(0, 105)
    ax.set_ylabel(f"Population within {threshold_min:g} min drive of a hospital (%)")
    ax.set_title("Coverage before and after each proposed site", fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    plt.tight_layout()
    _save(fig, out_path)
    return fig


def plot_hero(edges, iso, blocks, hospitals, sites=None, river=None, out_path=None, threshold_min=15):
    """2 x 2 overview: network, isochrones, access score, underserved + sites."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    draw_road_network(axes[0, 0], edges, hospitals, river, title="(a) Road network and hospitals")
    draw_isochrones(axes[0, 1], iso, edges, hospitals, river, title="(b) Drive-time isochrones")
    draw_choropleth(axes[1, 0], blocks, "access_score", "viridis",
                    "beds per 1,000 residents", hospitals=hospitals,
                    title=f"(c) 2SFCA access score ({threshold_min:g} min)")
    draw_underserved(axes[1, 1], blocks, hospitals, sites, river, edges,
                     title="(d) Underserved blocks and proposed sites")
    fig.suptitle("Healthcare accessibility and site selection, synthetic Fresno (EPSG:32611)",
                 fontsize=14, fontweight="bold")
    plt.tight_layout()
    _save(fig, out_path)
    return fig


# ---------------------------------------------------------------- folium --

def build_web_map(edges, iso, blocks, hospitals, sites=None, river=None, threshold_min=15,
                  centre_lonlat=None) -> folium.Map:
    """
    Interactive Folium map: roads by class, isochrone bands, block choropleth
    on access_score with tooltips, hospital markers (plus-sign icon),
    proposed-site markers and a layer control.
    """
    blocks_ll = blocks.to_crs(4326)
    if centre_lonlat is None:
        b = blocks_ll.total_bounds
        centre_lonlat = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    with warnings.catch_warnings():
        # folium >= 0.20 warns that CartoDB may require an API key; the public
        # positron tiles still load, so keep the demo output clean.
        warnings.filterwarnings("ignore", message=".*CartoDB tiles.*")
        m = folium.Map(location=[centre_lonlat[1], centre_lonlat[0]], zoom_start=12,
                       tiles="CartoDB positron")

    if river is not None and len(river):
        folium.GeoJson(
            river.to_crs(4326),
            name="River",
            style_function=lambda f: {"fillColor": RIVER_COLOUR, "color": RIVER_COLOUR,
                                      "weight": 0.5, "fillOpacity": 0.7},
        ).add_to(m)

    # blocks choropleth on access score
    score = blocks_ll["access_score"].astype(float)
    vmin, vmax = float(score.min()), float(max(score.max(), score.min() + 1e-6))
    cm = LinearColormap(["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"], vmin=vmin, vmax=vmax)
    cm.caption = "2SFCA access score (beds per 1,000 residents)"
    show = blocks_ll.copy()
    show["tt_nearest_min"] = show["tt_nearest_min"].round(1)
    show["access_score"] = show["access_score"].round(2)
    fields = [c for c in ["block_id", "population", "median_income", "svi", "tt_nearest_min",
                          "access_score", "underserved"] if c in show]
    aliases = {"block_id": "Block", "population": "Population", "median_income": "Median income ($)",
               "svi": "SVI", "tt_nearest_min": "Drive time (min)",
               "access_score": "Access score", "underserved": "Underserved"}
    if "underserved" in show:
        show["underserved"] = show["underserved"].map(lambda v: "yes" if bool(v) else "no")
    folium.GeoJson(
        show[fields + ["geometry"]],
        name="Blocks: 2SFCA access score",
        style_function=lambda f: {"fillColor": cm(f["properties"]["access_score"]),
                                  "color": "white", "weight": 0.3, "fillOpacity": 0.65},
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=[aliases[f] for f in fields]),
    ).add_to(m)
    m.add_child(cm)

    # isochrone bands (largest first so small bands sit on top)
    iso_ll = iso.copy()
    iso_ll["geometry"] = iso_ll.geometry.simplify(5.0)
    iso_ll = iso_ll[~iso_ll.geometry.is_empty].to_crs(4326).sort_values("max_minutes", ascending=False)
    iso_ll["label"] = iso_ll.apply(lambda r: f"{int(r['min_minutes'])} to {int(r['max_minutes'])} min", axis=1)
    folium.GeoJson(
        iso_ll[["min_minutes", "max_minutes", "label", "geometry"]],
        name="Drive-time isochrones",
        style_function=lambda f: {"fillColor": ISO_COLOURS.get(int(f["properties"]["max_minutes"]), "#800026"),
                                  "color": "#444", "weight": 0.4, "fillOpacity": 0.35},
        tooltip=folium.GeoJsonTooltip(fields=["label"], aliases=["Drive time"]),
        show=True,
    ).add_to(m)

    # roads by class
    roads_ll = edges[["highway", "speed_kph", "geometry"]].to_crs(4326)
    folium.GeoJson(
        roads_ll,
        name="Roads by class",
        style_function=lambda f: {"color": ROAD_STYLE.get(f["properties"]["highway"], ("#999",))[0],
                                  "weight": {"residential": 0.8, "secondary": 1.6, "primary": 2.2,
                                             "motorway": 3.0}.get(f["properties"]["highway"], 1),
                                  "opacity": 0.8},
        tooltip=folium.GeoJsonTooltip(fields=["highway", "speed_kph"], aliases=["Class", "Speed (km/h)"]),
    ).add_to(m)

    hosp_group = folium.FeatureGroup(name="Existing hospitals")
    for _, r in hospitals.to_crs(4326).iterrows():
        folium.Marker(
            location=[r.geometry.y, r.geometry.x],
            popup=folium.Popup(f"<b>{r.get('name', 'Hospital')}</b><br>{int(r.get('beds', 0))} beds", max_width=220),
            tooltip=str(r.get("name", "Hospital")),
            icon=folium.Icon(color="red", icon="plus-sign"),
        ).add_to(hosp_group)
    hosp_group.add_to(m)

    if sites is not None and len(sites):
        site_group = folium.FeatureGroup(name="Proposed new sites")
        for _, r in sites.to_crs(4326).iterrows():
            folium.Marker(
                location=[r.geometry.y, r.geometry.x],
                popup=folium.Popup(
                    f"<b>{r.get('name', 'Proposed site')}</b><br>"
                    f"Newly covered: {int(round(r.get('new_population', 0))):,} people<br>"
                    f"Coverage after: {float(r.get('pct_covered_after', 0)):.1f} %", max_width=240),
                tooltip=str(r.get("name", "Proposed site")),
                icon=folium.Icon(color="green", icon="star"),
            ).add_to(site_group)
        site_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m
