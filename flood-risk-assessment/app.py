"""
Streamlit app: Multi-Criteria Flood Risk Assessment (AHP + DEM hydrology).

Run with:  streamlit run app.py
"""

import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.pipeline import run_pipeline  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src import visualize as viz  # noqa: E402

st.set_page_config(page_title="Flood Risk Assessment (AHP)", page_icon="🌊", layout="wide")

CONFIG_PATH = PROJECT_DIR / "config.yaml"
APP_RESULTS = PROJECT_DIR / "results" / "app"


# ------------------------------------------------------------------ cached steps
@st.cache_data(show_spinner="Generating synthetic Harris County scene...")
def cached_data(size: int, seed: int) -> dict:
    out_dir = APP_RESULTS / f"scene_{size}_{seed}" / "data"
    data = generate_demo_data(size=size, seed=seed, out_dir=out_dir)
    # keep only picklable, light items for the cache
    return {k: v for k, v in data.items() if k != "arrays"}


@st.cache_data(show_spinner="Running DEM hydrology, AHP overlay and risk model...")
def cached_pipeline(size: int, seed: int, stream_threshold: int, risk_method: str,
                    high_threshold: float) -> dict:
    data = cached_data(size, seed)
    results = run_pipeline(
        CONFIG_PATH, data, out_dir=None, stream_threshold=stream_threshold,
        risk_method=risk_method, high_risk_threshold=high_threshold, write_outputs=False,
    )
    results["boundary_gdf"] = data["boundary_gdf"]
    return results


# ------------------------------------------------------------------ sidebar
st.sidebar.header("Scene")
size = st.sidebar.slider("Grid size (cells per side, 30 m)", 100, 250, 200, step=10)
seed = st.sidebar.number_input("Random seed", min_value=0, max_value=9999, value=42, step=1)

st.sidebar.header("Method parameters")
stream_threshold = st.sidebar.slider("Stream accumulation threshold (cells)", 100, 1500, 400, step=50)
risk_method = st.sidebar.selectbox("Risk combination method", ["geometric_mean", "multiplicative", "matrix"])
high_threshold = st.sidebar.slider("High-risk threshold (risk index)", 0.40, 0.80, 0.60, step=0.05)
return_period = st.sidebar.selectbox("Return period for the metrics", [10, 50, 100, 500], index=2)

results = cached_pipeline(int(size), int(seed), int(stream_threshold), risk_method, float(high_threshold))
s = results["summary"]
scen = results["scenarios"][int(return_period)]

# ------------------------------------------------------------------ main
st.title("Multi-Criteria Flood Risk Assessment (AHP + DEM hydrology)")
st.markdown(
    "A synthetic Harris County (TX) scene is built at 30 m, the DEM is filled and routed (D8), and seven "
    "criteria are combined with AHP weights into a flood susceptibility map. Susceptibility is then "
    "combined with population, critical facilities and social vulnerability into a risk index, and scaled "
    "to 10 / 50 / 100 / 500-year return periods. Change the sidebar parameters to see the effect."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("AHP consistency ratio (CR)", f"{s['ahp_CR']:.4f}", "consistent" if s["ahp_consistent"] else "inconsistent")
c2.metric(f"High + Very High risk area ({return_period}-yr)", f"{scen['high_risk_percent']:.1f} %")
c3.metric(f"Population exposed ({return_period}-yr)", f"{scen['population_high_very_high']:,}",
          f"of {s['total_population']:,} total")
c4.metric("Facilities at risk (100-yr)", f"{s['facilities_high_very_high']} of {s['facilities_total']}")

tab_maps, tab_web, tab_stats, tab_method = st.tabs(["Maps", "Interactive map", "Statistics", "Method"])

with tab_maps:
    import matplotlib.pyplot as plt

    col_a, col_b = st.columns(2)
    with col_a:
        fig, ax = plt.subplots(figsize=(7, 5.5))
        viz.draw_dem_streams(ax, results, "Filled DEM, hillshade and D8 streams")
        viz.axes_labels(ax)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 5.5))
        viz.draw_index(ax, results["vulnerability"], results, "Socioeconomic vulnerability", "magma",
                        "Vulnerability index (0-1)", streams=False)
        viz.axes_labels(ax)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    with col_b:
        fig, ax = plt.subplots(figsize=(7, 5.5))
        viz.draw_index(ax, results["susceptibility"], results,
                        f"AHP flood susceptibility (CR = {s['ahp_CR']:.3f})", "YlGnBu", "Susceptibility index (0-1)")
        viz.axes_labels(ax)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 5.5))
        viz.draw_risk_classes(ax, results, f"Flood risk classes ({risk_method}), 100-yr")
        viz.axes_labels(ax)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    fig_path = Path(tempfile.gettempdir()) / f"flood_scenarios_{size}_{seed}_{risk_method}.png"
    viz.plot_scenarios(results, fig_path)
    st.image(str(fig_path), caption="High-risk share of the study area by return period")

with tab_web:
    m = viz.build_web_map(results, boundary=results.get("boundary_gdf"))
    if hasattr(st, "iframe"):  # Streamlit >= 1.50 name; components.v1.html is the older API
        st.iframe(m._repr_html_(), height=600)
    else:
        st.components.v1.html(m._repr_html_(), height=600)

with tab_stats:
    st.subheader("AHP weights")
    st.dataframe(pd.DataFrame({"criterion": list(s["ahp_weights"].keys()),
                               "weight": list(s["ahp_weights"].values())}), hide_index=True)
    st.caption(f"lambda_max = {s['ahp_lambda_max']}, CI = {s['ahp_CI']}, CR = {s['ahp_CR']} (threshold 0.10)")

    st.subheader("Risk classes (100-yr)")
    exp = results["exposure"]
    st.dataframe(pd.DataFrame([
        {"class": k, "area_km2": v["area_km2"], "area_pct": v["area_pct"],
         "estimated_population": v["estimated_population"]} for k, v in exp.items()
    ]), hide_index=True)

    st.subheader("Return-period scenarios")
    st.dataframe(pd.DataFrame([{"return_period": rp, **v} for rp, v in results["scenarios"].items()]),
                 hide_index=True)

    st.subheader("Critical facilities")
    fac = results["facilities"].drop(columns="geometry")
    st.dataframe(fac, hide_index=True)

    st.subheader("Susceptibility classes")
    st.dataframe(pd.DataFrame([{"class": k, **v} for k, v in results["susceptibility_stats"].items()]),
                 hide_index=True)

with tab_method:
    st.markdown(
        """
**1. DEM hydrology.** Sinks are filled with a priority-flood (Barnes et al. 2014). Slope uses Horn's 3x3
method. Flow direction is D8 (steepest of the 8 neighbour drops); flow accumulation is a topological
traversal. Streams are cells above the accumulation threshold; distance to streams is a Euclidean
distance transform. TWI = ln(a / tan b) with a the specific catchment area.

**2. AHP weights.** A 7x7 pairwise comparison matrix (Saaty scale) gives priority weights by the row
geometric mean method. Consistency: CI = (lambda_max - n) / (n - 1), CR = CI / RI, accepted if CR < 0.10.

**3. Flood susceptibility.** Each criterion is scored 0-1 (reclassification tables for TWI, slope,
elevation and distance to streams; percentile-clipped min-max scaling for rainfall and Ksat; NLCD
lookup for land cover) and combined as a weighted sum, stretched to 0-1.

**4. Vulnerability.** 0.40 x population density + 0.35 x critical infrastructure density (gaussian
kernel, criticality weights) + 0.25 x social vulnerability index (CDC SVI style RPL_THEMES).

**5. Risk.** geometric_mean: sqrt(H x V); multiplicative: H x V; matrix: 5x5 lookup. Classes at
0.2 / 0.4 / high threshold / very high. Exposure = population density x pixel area per class; facilities
are spatially joined onto the risk zones.

**6. Scenarios.** The hazard is scaled by 0.65 / 0.88 / 1.00 / 1.25 for the 10 / 50 / 100 / 500-year
return periods and the risk is recomputed.
        """
    )
