"""
Streamlit app: multi-temporal crop health monitoring on a synthetic
Sentinel-2 season (Story County, Iowa).

    python -m streamlit run app.py
"""

import sys
import tempfile
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import streamlit as st

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.pipeline import run_pipeline  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src.utils import load_config  # noqa: E402
from src import visualize as viz  # noqa: E402

st.set_page_config(page_title="Crop Health Monitoring (Sentinel-2)", page_icon="🌽", layout="wide")


@st.cache_data(show_spinner="Generating synthetic Sentinel-2 season...")
def make_data(size: int, seed: int) -> str:
    """Write the synthetic season to a temp folder and return its path."""
    out = Path(tempfile.mkdtemp(prefix=f"crop_{size}_{seed}_"))
    generate_demo_data(size=size, seed=seed, out_dir=out)
    return str(out)


@st.cache_data(show_spinner="Running pipeline (indices, phenology, anomalies, field stats)...")
def run(size: int, seed: int, method: str, z_thr: float, min_ha: float):
    data_dir = Path(make_data(size, seed))
    config = load_config(PROJECT_DIR / "config.yaml")
    res = run_pipeline(
        config, data_dir / "sentinel2", fields_path=data_dir / "fields.geojson",
        block_size=5, anomaly_method=method, z_threshold=z_thr, min_cluster_ha=min_ha,
        run_comparison=False, write_outputs=False,
    )
    # keep only what the UI needs (small, picklable)
    ndvi_stack = np.stack([s["ndvi"] for s in res["scenes"]]).astype(np.float32)
    slim = {
        "profile": res["profile"], "fields": res["fields"], "field_table": res["field_table"],
        "peak_metrics": res["peak_metrics"], "anomaly_mask": res["anomaly_mask"],
        "anomaly_stats": res["anomaly_stats"], "assessment_idx": res["assessment_idx"],
        "assessment_date": res["assessment_date"], "summary": res["summary"], "doy": res["doy"],
        "field_fit": {k: v for k, v in res["field_fit"].items() if k != "expected_raster"},
        "stats_df": res["stats_df"], "change_df": res["change_df"], "ndvi_stack": ndvi_stack,
        "dates": [s["date"].strftime("%Y-%m-%d") for s in res["scenes"]],
        "cloud": [float(s.get("cloud_percent", 0.0)) for s in res["scenes"]],
        "scenes": [{"ndvi": ndvi_stack[i]} for i in range(len(res["scenes"]))],
    }
    return slim, config


# ----------------------------------------------------------------- sidebar
st.sidebar.header("Scene and method")
size = st.sidebar.slider("Grid size (10 m pixels)", 100, 200, 160, step=20)
seed = st.sidebar.number_input("Random seed", 0, 9999, 42)
method = st.sidebar.selectbox("Anomaly method", ["z_score", "isolation_forest"])
z_thr = st.sidebar.slider("Z-score threshold (flag below)", -3.0, -0.5, -1.5, step=0.1)
min_ha = st.sidebar.slider("Minimum anomaly cluster (ha)", 0.1, 2.0, 0.5, step=0.1)

res, config = run(int(size), int(seed), method, float(z_thr), float(min_ha))

# ----------------------------------------------------------------- header
st.title("Multi-temporal crop health monitoring with Sentinel-2")
st.write(
    "Fourteen synthetic Sentinel-2 style scenes (April to October 2024) over corn and soybean fields "
    "in Story County, Iowa. The app computes NDVI, EVI, SAVI, NDRE and NDWI per scene, fits a double "
    "logistic phenology curve per field and per pixel block, flags stressed areas on the latest cloud-free "
    "scene against the phenology-expected NDVI, and summarises health per field."
)

t = res["field_table"]
hd = res["summary"]["assessment"]["health_distribution"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Mean peak NDVI (crop pixels)", f"{res['summary']['phenology']['mean_peak_ndvi']:.3f}")
c2.metric(f"Anomalous crop area ({res['assessment_date']})", f"{res['anomaly_stats']['anomalous_percent']:.2f} %",
          help=f"{res['anomaly_stats']['n_clusters']} clusters, method {method}")
c3.metric("Fields Excellent + Good", int(hd.get("Excellent", 0) + hd.get("Good", 0)))
c4.metric("Fields Poor + Very Poor", int(hd.get("Poor", 0) + hd.get("Very Poor", 0)))

tab_maps, tab_web, tab_stats, tab_method = st.tabs(["Maps", "Interactive map", "Statistics", "Method"])

# ----------------------------------------------------------------- maps
with tab_maps:
    st.subheader("NDVI by acquisition date")
    labels = [f"{d} ({c:.0f}% masked)" for d, c in zip(res["dates"], res["cloud"])]
    pick = st.select_slider("Scene date", options=list(range(len(labels))), value=res["assessment_idx"],
                            format_func=lambda i: labels[i])
    fig, ax = plt.subplots(figsize=(9, 6.5))
    im = ax.imshow(res["ndvi_stack"][pick], cmap="RdYlGn", vmin=-0.1, vmax=0.9,
                   extent=viz.raster_extent(res["profile"]))
    res["fields"].to_crs(res["profile"]["crs"]).boundary.plot(ax=ax, color="black", linewidth=0.5)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="NDVI (-)")
    ax.set_title(f"NDVI on {res['dates'][pick]} (white = cloud / shadow masked)")
    ax.set_xlabel("Easting (m, EPSG:32615)")
    ax.set_ylabel("Northing (m)")
    ax.ticklabel_format(style="plain", useOffset=False)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    col_a, col_b = st.columns(2)
    with col_a:
        fig, ax = plt.subplots(figsize=(8, 6))
        viz._panel_anomaly(ax, res)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(8, 6))
        viz._panel_peak_ndvi(ax, res)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    with col_b:
        fig, ax = plt.subplots(figsize=(8, 6))
        viz._panel_health(ax, res, config)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(8, 6))
        viz._panel_curves(ax, res, config, n_max=6)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

# ----------------------------------------------------------------- web map
with tab_web:
    m = viz.build_web_map(res, config)
    html = m._repr_html_()
    if hasattr(st, "iframe"):  # Streamlit >= 1.50; components.v1.html is deprecated after mid-2026
        st.iframe(html, height=600)
    else:
        st.components.v1.html(html, height=600)

# ----------------------------------------------------------------- stats
with tab_stats:
    st.subheader(f"Fields on the assessment scene ({res['assessment_date']})")
    cols = [c for c in ["field_id", "crop", "area_ha", "mean_ndvi", "mean_ndre", "mean_evi", "health_class",
                        "anomaly_pct", "ndre_stress", "peak_value", "peak_doy", "season_length_days", "r_squared"]
            if c in t.columns]
    st.dataframe(pd.DataFrame(t[cols]).sort_values("mean_ndvi"), hide_index=True)

    st.subheader("Scenes")
    st.dataframe(pd.DataFrame(res["summary"]["scenes"]), hide_index=True)

    st.subheader("Anomaly statistics")
    st.json(res["anomaly_stats"])

    if not res["change_df"].empty:
        st.subheader("Field change between consecutive scenes")
        st.dataframe(res["change_df"], hide_index=True)

# ----------------------------------------------------------------- method
with tab_method:
    st.markdown(
        """
**1. Load scenes.** Each scene folder holds Sentinel-2 L2A bands as uint16 DN (reflectance x 10000) and an
SCL layer. DN are scaled to reflectance, 20 m bands are resampled to 10 m, and SCL classes 3, 8, 9, 10
(shadow, cloud, cirrus) are masked to NaN.

**2. Indices.** NDVI = (NIR - Red)/(NIR + Red); EVI = 2.5 (NIR - Red)/(NIR + 6 Red - 7.5 Blue + 1);
SAVI = 1.5 (NIR - Red)/(NIR + Red + 0.5); NDRE = (NIR - RedEdge)/(NIR + RedEdge); NDWI = (Green - NIR)/(Green + NIR).

**3. Phenology.** Cloud gaps are linearly interpolated in time, a Savitzky-Golay filter smooths the NDVI series,
and a double logistic `a1 + a2 (1/(1+e^{-a3(t-a4)}) - 1/(1+e^{-a5(t-a6)}))` is fitted per 5 x 5 pixel block and
per field. Peak NDVI, peak day of year and season length (a6 - a4) come from the fitted curve.

**4. Anomalies.** On the latest scene under the cloud limit, the residual between observed NDVI and the field's
expected NDVI is z-scored; pixels below the threshold are stressed. Clusters smaller than the minimum area are
dropped. Isolation Forest on local NDVI features is the alternative method.

**5. Field statistics.** Zonal mean/median/std/percentiles per field and date, health classes from mean NDVI
(Excellent >= 0.75, Good >= 0.55, Moderate >= 0.35, Poor >= 0.20), change between consecutive scenes, and a
red-edge (NDRE vs NDVI) residual flag for likely nitrogen stress.

All data here are synthetic and generated with the seed in the sidebar; the same code runs on real Sentinel-2
scenes placed in the folder layout described in the README.
        """
    )
