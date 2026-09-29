"""
Figures and the Folium web map for the crop health pipeline.

Every ``plot_*`` function takes the results dict returned by
``src.pipeline.run_pipeline`` and a destination path, and returns the path.
``build_web_map`` returns a ``folium.Map``.
"""

import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import folium
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import cm, colors  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402

HEALTH_ORDER = ["Excellent", "Good", "Moderate", "Poor", "Very Poor", "No Data"]
DEFAULT_HEALTH_COLORS = {
    "Excellent": "#006400", "Good": "#32CD32", "Moderate": "#FFD700",
    "Poor": "#FF8C00", "Very Poor": "#DC143C", "No Data": "#BBBBBB",
}
STAGE_COLORS = ["#f1eef6", "#d0d1e6", "#a6bddb", "#74a9cf", "#2b8cbe"]
DPI = 150


# ---------------------------------------------------------------- helpers
def health_colors(config: Optional[dict] = None) -> Dict[str, str]:
    cols = dict(DEFAULT_HEALTH_COLORS)
    if config:
        hc = config.get("classification", {}).get("health_classes", {})
        key = {"excellent": "Excellent", "good": "Good", "moderate": "Moderate",
               "poor": "Poor", "very_poor": "Very Poor"}
        for k, name in key.items():
            if k in hc and "color" in hc[k]:
                cols[name] = hc[k]["color"]
    return cols


def raster_extent(profile: dict) -> List[float]:
    """[west, east, south, north] in the raster CRS for imshow(extent=...)."""
    tr = profile["transform"]
    west, north = tr.c, tr.f
    east = west + profile["width"] * tr.a
    south = north + profile["height"] * tr.e
    return [west, east, south, north]


def _outlines(ax, fields, profile, color="black", lw=0.6):
    fields.to_crs(profile["crs"]).boundary.plot(ax=ax, color=color, linewidth=lw)


def _map_axes(ax, title):
    ax.set_title(title)
    ax.set_xlabel("Easting (m, EPSG:32615)")
    ax.set_ylabel("Northing (m)")
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(labelsize=7)


def _stage_bands(ax, config, year=2024):
    """Shade the phenology stages from config.yaml as vertical bands."""
    stages = config.get("growing_season", {}).get("phenology_stages", [])
    ymin, ymax = ax.get_ylim()
    for i, st in enumerate(stages):
        s = datetime.strptime(f"{year}-{st['start']}", "%Y-%m-%d").timetuple().tm_yday
        e = datetime.strptime(f"{year}-{st['end']}", "%Y-%m-%d").timetuple().tm_yday
        ax.axvspan(s, e, color=STAGE_COLORS[i % len(STAGE_COLORS)], alpha=0.35, lw=0)
        ax.text((s + e) / 2, ymin + 0.02 * (ymax - ymin), st["name"], ha="center", va="bottom",
                fontsize=7, color="#333333")


def _pick_curve_fields(res, n_max=7) -> List[int]:
    """Row indices of a varied set of fields for the phenology plot."""
    t = res["field_table"]
    if "peak_value" not in t.columns:
        return list(range(min(n_max, len(t))))
    chosen = []

    def add(idx_list):
        for i in idx_list:
            if i not in chosen and len(chosen) < n_max:
                chosen.append(int(i))

    for crop in ("corn", "soybean"):
        sub = t[t.get("crop", "") == crop] if "crop" in t.columns else t
        if len(sub):
            add(sub.sort_values("peak_value", ascending=False).index[:1])
    if "ndre_stress" in t.columns:
        add(t[t["ndre_stress"] == True].index[:1])
    add(t.sort_values("anomaly_pct", ascending=False).index[:2])
    add(t.sort_values("mean_ndvi").index[:2])
    add(t.index)
    return chosen[:n_max]


# ---------------------------------------------------------------- panels
def _panel_peak_ndvi(ax, res, cbar=True):
    pv = res["peak_metrics"]["peak_value"]
    im = ax.imshow(pv, cmap="RdYlGn", vmin=0.2, vmax=0.9, extent=raster_extent(res["profile"]))
    _outlines(ax, res["fields"], res["profile"])
    _map_axes(ax, "Peak NDVI from fitted phenology (block fit)")
    if cbar:
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Peak NDVI (-)")
    return im


def _panel_curves(ax, res, config, n_max=7):
    ff = res["field_fit"]
    t = res["field_table"]
    rows = _pick_curve_fields(res, n_max)
    cmap = plt.get_cmap("tab10")
    for j, k in enumerate(rows):
        fid = t.loc[k, "field_id"]
        crop = t.loc[k, "crop"] if "crop" in t.columns else ""
        label = f"{fid} {crop}".strip()
        if "ndre_stress" in t.columns and bool(t.loc[k, "ndre_stress"]):
            label += " (N-stress flag)"
        ax.plot(ff["doy"], ff["observed"][k], "o", ms=4, color=cmap(j % 10))
        ax.plot(ff["doy_dense"], ff["expected_dense"][k], "-", lw=1.5, color=cmap(j % 10), label=label)
    ax.set_ylim(0, 1.0)
    _stage_bands(ax, config)
    a_doy = res["doy"][res["assessment_idx"]]
    ax.axvline(a_doy, color="k", ls="--", lw=0.8)
    ax.text(a_doy + 1, 0.98, f"assessment {res['assessment_date']}", fontsize=7, rotation=90, va="top")
    ax.set_xlabel("Day of year 2024 (stage bands from config.yaml)")
    ax.set_ylabel("Field mean NDVI (-)")
    ax.set_title("Field NDVI: observed (points) and fitted double logistic (lines)")
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    ax.grid(alpha=0.3)


def _panel_anomaly(ax, res, cbar=True):
    ndvi = res["scenes"][res["assessment_idx"]]["ndvi"]
    ext = raster_extent(res["profile"])
    im = ax.imshow(ndvi, cmap="RdYlGn", vmin=-0.1, vmax=0.9, extent=ext)
    mask = res["anomaly_mask"]
    overlay = np.zeros(mask.shape + (4,))
    overlay[mask] = colors.to_rgba("#d7191c", 0.95)
    ax.imshow(overlay, extent=ext, interpolation="nearest")
    _outlines(ax, res["fields"], res["profile"])
    st = res["anomaly_stats"]
    _map_axes(ax, f"Anomalies ({st['method']}) on {res['assessment_date']}: "
                  f"{st['anomalous_percent']:.1f}% of crop area, {st['n_clusters']} clusters")
    if cbar:
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="NDVI (-)")
    ax.legend(handles=[Patch(color="#d7191c", label="anomalous (stressed)")], loc="lower right", fontsize=7)


def _panel_health(ax, res, config=None):
    t = res["field_table"].to_crs(res["profile"]["crs"])
    cols = health_colors(config)
    t.plot(ax=ax, color=[cols.get(c, cols["No Data"]) for c in t["health_class"]],
           edgecolor="black", linewidth=0.5)
    ax.set_xlim(raster_extent(res["profile"])[:2])
    ax.set_ylim(raster_extent(res["profile"])[2:])
    counts = t["health_class"].value_counts()
    handles = [Patch(color=cols[c], label=f"{c} ({counts.get(c, 0)})") for c in HEALTH_ORDER[:5]]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=7,
              title="Field health\n(mean NDVI)", title_fontsize=7, frameon=False)
    _map_axes(ax, f"Field health classes on {res['assessment_date']}")


# ---------------------------------------------------------------- figures
def plot_hero(res, config, path) -> str:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    _panel_peak_ndvi(axes[0, 0], res)
    _panel_curves(axes[0, 1], res, config, n_max=6)
    _panel_anomaly(axes[1, 0], res)
    _panel_health(axes[1, 1], res, config)
    fig.suptitle("Multi-temporal crop health monitoring, Sentinel-2 style synthetic season, Story County, Iowa",
                 fontsize=13)
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_peak_ndvi_map(res, path) -> str:
    fig, ax = plt.subplots(figsize=(10, 7))
    _panel_peak_ndvi(ax, res)
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_phenology_curves(res, config, path, n_max=7) -> str:
    fig, ax = plt.subplots(figsize=(10, 7))
    _panel_curves(ax, res, config, n_max=n_max)
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_anomaly_map(res, path) -> str:
    fig, ax = plt.subplots(figsize=(10, 7))
    _panel_anomaly(ax, res)
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_field_health_map(res, config, path) -> str:
    fig, ax = plt.subplots(figsize=(10, 7))
    _panel_health(ax, res, config)
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_peak_doy_map(res, path) -> str:
    fig, ax = plt.subplots(figsize=(10, 7))
    pdoy = res["peak_metrics"]["peak_doy"]
    vmin, vmax = np.nanpercentile(pdoy, [2, 98]) if np.isfinite(pdoy).any() else (150, 250)
    im = ax.imshow(pdoy, cmap="viridis", vmin=vmin, vmax=vmax, extent=raster_extent(res["profile"]))
    _outlines(ax, res["fields"], res["profile"], color="white", lw=0.6)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="Day of year of peak NDVI")
    _map_axes(ax, "Timing of peak NDVI (corn earlier, soybean later)")
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_ndre_vs_ndvi(res, path) -> str:
    t = res["field_table"]
    fig, ax = plt.subplots(figsize=(10, 7))
    if "mean_ndre" not in t.columns:
        ax.text(0.5, 0.5, "NDRE not computed", ha="center")
    else:
        ok = t[["mean_ndvi", "mean_ndre"]].notna().all(axis=1)
        flag = t.get("ndre_stress", np.zeros(len(t), dtype=bool)).astype(bool)
        for crop, marker in (("corn", "o"), ("soybean", "s")):
            sub = ok & (t.get("crop", "") == crop) if "crop" in t.columns else ok
            for is_flag, color, lab in ((False, "#1a9641", "normal"), (True, "#d7191c", "red-edge stress flag")):
                sel = sub & (flag == is_flag)
                if sel.any():
                    ax.scatter(t.loc[sel, "mean_ndvi"], t.loc[sel, "mean_ndre"], marker=marker, s=60,
                               c=color, edgecolor="k", linewidth=0.5, label=f"{crop}, {lab}")
        x = t.loc[ok, "mean_ndvi"].values
        y = t.loc[ok, "mean_ndre"].values
        if len(x) >= 3:
            a, b = np.polyfit(x, y, 1)
            xs = np.linspace(x.min(), x.max(), 50)
            ax.plot(xs, a * xs + b, "k--", lw=1, label=f"fit NDRE = {a:.2f} NDVI + {b:.2f}")
        for _, r in t[ok & flag].iterrows():
            ax.annotate(r["field_id"], (r["mean_ndvi"], r["mean_ndre"]), fontsize=7,
                        xytext=(4, -9), textcoords="offset points")
        ax.legend(fontsize=8)
    ax.set_xlabel("Field mean NDVI (-)")
    ax.set_ylabel("Field mean NDRE (-)")
    ax.set_title(f"NDRE vs NDVI per field on {res['assessment_date']}: low NDRE for the NDVI suggests nitrogen stress")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def plot_ndvi_timeline(res, path) -> str:
    df = res["stats_df"]
    ndvi = df[df["index"] == "ndvi"]
    daily = ndvi.groupby("date")["mean"].agg(["mean", "std"]).reset_index()
    daily["dt"] = daily["date"].apply(lambda s: datetime.strptime(s, "%Y-%m-%d"))
    cloud = {s["date"]: s["cloud_percent"] for s in res["summary"]["scenes"]}
    daily["cloud"] = daily["date"].map(cloud)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax2 = ax.twinx()
    ax2.bar(daily["dt"], daily["cloud"], width=6, color="#9ecae1", alpha=0.7, label="cloud + shadow cover (%)")
    ax2.set_ylabel("Masked cover per scene (%)")
    ax2.set_ylim(0, 100)
    ax.errorbar(daily["dt"], daily["mean"], yerr=daily["std"], fmt="-o", color="#1a9641", ecolor="#a6d96a",
                capsize=3, label="all-field mean NDVI (+/- 1 std across fields)")
    a_dt = datetime.strptime(res["assessment_date"], "%Y-%m-%d")
    ax.axvline(a_dt, color="k", ls="--", lw=0.8)
    ax.text(a_dt, 0.97, " assessment scene", fontsize=8, va="top")
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Field mean NDVI (-)")
    ax.set_xlabel("Acquisition date (2024)")
    ax.set_title("Season NDVI timeline across all fields, with masked cloud/shadow share per scene")
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    plt.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return str(path)


def make_all_figures(res, config, fig_dir) -> List[str]:
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    return [
        plot_hero(res, config, fig_dir / "00_hero.png"),
        plot_peak_ndvi_map(res, fig_dir / "01_ndvi_peak_map.png"),
        plot_phenology_curves(res, config, fig_dir / "02_phenology_curves.png"),
        plot_anomaly_map(res, fig_dir / "03_anomaly_map.png"),
        plot_field_health_map(res, config, fig_dir / "04_field_health_map.png"),
        plot_peak_doy_map(res, fig_dir / "05_peak_doy_map.png"),
        plot_ndre_vs_ndvi(res, fig_dir / "06_ndre_vs_ndvi.png"),
        plot_ndvi_timeline(res, fig_dir / "07_ndvi_timeline.png"),
    ]


# ---------------------------------------------------------------- web map
def _to_rgba(arr, cmap, vmin, vmax, max_px=600, alpha=0.75):
    step = max(1, int(np.ceil(max(arr.shape) / max_px)))
    a = arr[::step, ::step].astype(float)
    norm = colors.Normalize(vmin=vmin, vmax=vmax)
    rgba = plt.get_cmap(cmap)(norm(np.nan_to_num(a, nan=vmin)))
    rgba[..., 3] = np.where(np.isnan(a), 0.0, alpha)
    return (rgba * 255).astype(np.uint8)


def build_web_map(res, config: Optional[dict] = None) -> folium.Map:
    """Folium map: NDVI (assessment scene), anomaly overlay, field polygons with tooltips."""
    profile = res["profile"]
    w, e, s, n = raster_extent(profile)
    west, south, east, north = transform_bounds(profile["crs"], "EPSG:4326", w, s, e, n)
    bounds = [[south, west], [north, east]]
    with warnings.catch_warnings():
        # folium >= 0.20 warns that CartoDB basemaps may need an API key; the public
        # cartocdn tiles still load, so keep the portfolio-standard basemap.
        warnings.simplefilter("ignore", UserWarning)
        m = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=14, tiles="CartoDB positron")

    ndvi = res["scenes"][res["assessment_idx"]]["ndvi"]
    folium.raster_layers.ImageOverlay(
        image=_to_rgba(ndvi, "RdYlGn", -0.1, 0.9), bounds=bounds, opacity=0.75,
        name=f"NDVI {res['assessment_date']}",
    ).add_to(m)

    mask = res["anomaly_mask"].astype(float)
    mask[mask == 0] = np.nan
    folium.raster_layers.ImageOverlay(
        image=_to_rgba(mask, "Reds", 0.0, 1.0, alpha=0.9), bounds=bounds, opacity=0.9,
        name="Anomalies (stressed crop)",
    ).add_to(m)

    cols = health_colors(config)
    t = res["field_table"].copy()
    fields = ["field_id", "crop", "mean_ndvi", "health_class", "anomaly_pct"]
    aliases = ["Field", "Crop", "Mean NDVI", "Health class", "Anomalous area (%)"]
    if "peak_value" in t.columns:
        t["peak_value"] = t["peak_value"].round(3)
        fields += ["peak_value", "peak_doy"]
        aliases += ["Peak NDVI", "Peak DOY"]
    if "ndre_stress" in t.columns:
        t["ndre_stress"] = t["ndre_stress"].map({True: "yes", False: "no"})
        fields.append("ndre_stress")
        aliases.append("Red-edge stress flag")
    fields = [f for f in fields if f in t.columns]
    aliases = aliases[: len(fields)]
    keep = fields + ["geometry"]
    folium.GeoJson(
        t[keep].to_crs(4326).to_json(),
        name="Fields (health class)",
        style_function=lambda f: {
            "fillColor": cols.get(f["properties"].get("health_class"), cols["No Data"]),
            "color": "#333333", "weight": 1, "fillOpacity": 0.35,
        },
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases),
    ).add_to(m)

    folium.LayerControl().add_to(m)
    m.fit_bounds(bounds)
    return m
