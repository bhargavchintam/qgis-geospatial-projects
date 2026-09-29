"""
Streamlit app for the Urban Heat Island Analysis project.

    streamlit run app.py

Sidebar: grid size, seed, the four UHI threshold multipliers and the
three Mitigation Priority Index weights (auto-normalised to sum to 1).
Everything is computed by the ``src`` modules on a synthetic Phoenix
scene, so it runs offline and needs no data download.
"""

import copy
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.synthetic_data import generate_demo_data  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402
from src.utils import load_config  # noqa: E402
from src import visualize as viz  # noqa: E402

st.set_page_config(page_title="Urban Heat Island Analysis", page_icon="🌡️", layout="wide")


@st.cache_data(show_spinner="Building the scene and running the pipeline ...")
def run(size: int, seed: int, mild: float, moderate: float, strong: float, extreme: float,
        w_thermal: float, w_pop: float, w_green: float) -> dict:
    """Generate the synthetic scene and run the full pipeline (cached on the inputs)."""
    config = load_config(PROJECT_DIR / "config.yaml")
    config = copy.deepcopy(config)
    config["classification"]["uhi_thresholds"] = {
        "mild": mild, "moderate": moderate, "strong": strong, "extreme": extreme,
    }
    total = w_thermal + w_pop + w_green
    config["mitigation"]["weights"] = {
        "thermal_anomaly": w_thermal / total,
        "population_density": w_pop / total,
        "green_space_deficit": w_green / total,
    }
    with tempfile.TemporaryDirectory() as tmp:
        data = generate_demo_data(size=size, seed=seed, out_dir=Path(tmp) / "data")
        results = run_pipeline(data, config, Path(tmp) / "out")
    # drop file paths that no longer exist after the temp folder is removed
    results.pop("paths", None)
    results["summary"].pop("outputs", None)
    results["weights"] = config["mitigation"]["weights"]
    return results


# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
st.sidebar.header("Scene")
size = st.sidebar.slider("Grid size (pixels, 30 m each)", 100, 250, 200, step=10)
seed = st.sidebar.number_input("Random seed", min_value=0, max_value=9999, value=42, step=1)

st.sidebar.header("UHI class thresholds (k in mean + k * std)")
mild = st.sidebar.slider("Mild", 0.1, 1.5, 0.5, 0.1)
moderate = st.sidebar.slider("Moderate", 0.2, 2.5, 1.0, 0.1)
strong = st.sidebar.slider("Strong", 0.3, 3.0, 1.5, 0.1)
extreme = st.sidebar.slider("Extreme", 0.5, 3.5, 2.0, 0.1)
if not (mild < moderate < strong < extreme):
    st.sidebar.warning("Thresholds should increase: Mild < Moderate < Strong < Extreme.")

st.sidebar.header("Mitigation Priority Index weights")
w_thermal = st.sidebar.slider("Thermal anomaly", 0.0, 1.0, 0.40, 0.05)
w_pop = st.sidebar.slider("Population density", 0.0, 1.0, 0.35, 0.05)
w_green = st.sidebar.slider("Green space deficit", 0.0, 1.0, 0.25, 0.05)
w_sum = w_thermal + w_pop + w_green
if w_sum <= 0:
    st.sidebar.error("At least one weight must be above zero.")
    st.stop()
st.sidebar.caption(
    f"Normalised: thermal {w_thermal / w_sum:.2f}, population {w_pop / w_sum:.2f}, "
    f"green deficit {w_green / w_sum:.2f}"
)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
st.title("Urban Heat Island Analysis (Landsat 8/9 thermal)")
st.markdown(
    "This app derives land surface temperature from Landsat 8/9 Band 10 with the single-channel "
    "method, classifies urban heat island intensity from the mean and standard deviation, and "
    "combines heat, population and green-space deficit into a Mitigation Priority Index. "
    "The scene is a synthetic Phoenix, Arizona summer afternoon, so it works without any download."
)

results = run(int(size), int(seed), mild, moderate, strong, extreme, w_thermal, w_pop, w_green)
summary = results["summary"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Mean LST", f"{summary['lst']['mean_c']:.1f} °C")
c2.metric("Max LST", f"{summary['lst']['max_c']:.1f} °C")
c3.metric("Extreme + Strong UHI", f"{summary['uhi_strong_plus_extreme_percent']:.1f} % of area")
c4.metric("High priority", f"{summary['mpi']['high_percent']:.1f} % of area")

tab_maps, tab_web, tab_stats, tab_method = st.tabs(["Maps", "Interactive map", "Statistics", "Method"])

with tab_maps:
    fig_dir = Path(tempfile.mkdtemp(prefix="uhi_figs_"))
    left, right = st.columns(2)
    with left:
        st.image(str(viz.plot_lst_map(results, fig_dir / "01_lst_map.png")), caption="Land surface temperature")
        st.image(str(viz.plot_mitigation_priority(results, fig_dir / "03_mitigation_priority.png")),
                 caption="Mitigation Priority Index with parks and high-priority zones")
        st.image(str(viz.plot_lst_by_lulc(results, fig_dir / "05_lst_by_lulc.png")), caption="Mean LST by land cover")
    with right:
        st.image(str(viz.plot_uhi_zones(results, fig_dir / "02_uhi_zones.png")), caption="UHI intensity classes")
        st.image(str(viz.plot_lst_vs_impervious(results, fig_dir / "04_lst_vs_impervious.png")),
                 caption="LST against impervious surface percent")
        st.image(str(viz.plot_lulc_map(results, fig_dir / "06_lulc_map.png")), caption="Land cover input (NLCD codes)")

with tab_web:
    m = viz.build_web_map(results)
    if hasattr(st, "iframe"):  # Streamlit >= 1.64 retires components.v1.html
        st.iframe(m._repr_html_(), height=600)
    else:
        components.html(m._repr_html_(), height=600)

with tab_stats:
    st.subheader("UHI class areas")
    uhi_df = pd.DataFrame(
        [
            {"class_id": v["class_id"], "class": k, "area_percent": v["area_percent"],
             "pixel_count": v["pixel_count"], "mean_lst_c": v["mean_lst"], "max_lst_c": v["max_lst"]}
            for k, v in results["uhi_stats"].items()
        ]
    ).sort_values("class_id")
    st.dataframe(uhi_df, width="stretch", hide_index=True)

    st.subheader("LST by land cover class")
    st.dataframe(results["lst_by_lulc"], width="stretch", hide_index=True)

    st.subheader("UHI class x land cover cross-tabulation (pixel counts)")
    st.dataframe(results["crosstab"], width="stretch", hide_index=True)

    st.subheader("LST vs impervious surface")
    st.json(summary["lst_vs_impervious"])

    st.subheader("Mitigation priority zones")
    pz = results["priority_gdf"].drop(columns="geometry")
    st.dataframe(pz, width="stretch", hide_index=True)
    st.caption(f"Weights used: {results['weights']}")

with tab_method:
    st.markdown(
        """
### 1. Land surface temperature (single-channel method)
* Collection 2 Level-2 thermal band: `BT (K) = DN * 0.00341802 + 149.0`
* `NDVI = (NIR - Red) / (NIR + Red)`
* Proportion of vegetation: `Pv = ((NDVI - NDVI_soil) / (NDVI_veg - NDVI_soil))^2`
* Emissivity: `0.966` for NDVI below 0.2, `0.004 * Pv + 0.986` for mixed pixels, `0.973` above 0.5
* `LST = BT / (1 + (lambda * BT / rho) * ln(emissivity))` with `lambda = 10.895 um`, `rho = 1.438e-2 m K`

### 2. UHI intensity classes
The study-area mean and standard deviation of LST set the class edges. With the sidebar
multipliers `k`: Extreme `>= mean + k_extreme * std`, Strong, Moderate, Mild, Neutral within
`+/- k_mild * std` of the mean, Cool Island below `mean - k_mild * std`. The UHI anomaly is
LST minus the mean LST of the rural classes (forest, shrub, grassland, crops).

### 3. Land cover relationships
Cross-tabulation of UHI classes against NLCD codes, mean LST per class, and a Pearson
correlation plus linear regression of LST against impervious surface percent.

### 4. Mitigation Priority Index
`MPI = w1 * norm(thermal anomaly) + w2 * norm(population density) + w3 * green-space deficit`
where the deficit is 1 outside a 400 m buffer around parks. MPI is computed only inside
Mild or stronger UHI zones, rescaled to 0..1, and split into High (>= 0.7), Medium (0.4 to 0.7)
and Low priority zones.
        """
    )
