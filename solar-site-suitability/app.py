"""
Streamlit app: Utility-Scale Solar Farm Site Suitability (AHP + constraints).

    streamlit run app.py
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.criteria import CONSTRAINT_LABELS  # noqa: E402
from src.pipeline import CRITERIA_TITLES, compute_ahp, run_pipeline  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src.utils import load_config  # noqa: E402
from src.visualize import (build_web_map, fig_ahp_weights, fig_candidate_sites,  # noqa: E402
                           fig_constraints, fig_criteria_panel, fig_hero,
                           fig_site_capacity, fig_suitability, fig_terrain)

st.set_page_config(page_title="Solar Site Suitability", page_icon="☀️", layout="wide")

CONFIG = load_config(PROJECT_DIR / "config.yaml")
CRITERIA = list(CONFIG["ahp"]["criteria_names"])
AHP_WEIGHTS, AHP_CONSISTENCY, _ = compute_ahp(CONFIG)


@st.cache_data(show_spinner=False)
def cached_data(size: int, seed: int) -> dict:
    out_dir = PROJECT_DIR / "results" / "app" / f"size{size}_seed{seed}"
    return generate_demo_data(size=size, seed=seed, out_dir=out_dir / "data")


@st.cache_data(show_spinner=False)
def cached_pipeline(size: int, seed: int, weights: tuple, threshold: float, min_area_ha: float,
                    max_slope: float, residential_buffer_m: float) -> dict:
    data = cached_data(size, seed)
    overrides = {"threshold": threshold, "min_area_ha": min_area_ha, "max_slope": max_slope,
                 "residential_buffer_m": residential_buffer_m}
    return run_pipeline(data, CONFIG, weights_override=dict(zip(CRITERIA, weights)), overrides=overrides)


# ----------------------------------------------------------------- sidebar
st.sidebar.header("Scene")
size = st.sidebar.slider("Grid size (pixels per side, 18 km extent)", 100, 200, 200, step=20)
seed = st.sidebar.number_input("Random seed", min_value=0, max_value=9999, value=42, step=1)

st.sidebar.header("Criteria weights (auto-normalised)")
st.sidebar.caption("Defaults are the AHP weights from config.yaml "
                   f"(CR = {AHP_CONSISTENCY['CR']:.3f}). Move a slider to test other priorities.")
raw = []
for name in CRITERIA:
    raw.append(st.sidebar.slider(CRITERIA_TITLES[name], 0.0, 100.0, round(100 * AHP_WEIGHTS[name], 1),
                                 step=0.1, format="%.1f %%", key=f"w_{name}"))
total = sum(raw) or 1
weights = tuple(r / total for r in raw)
st.sidebar.caption("Effective weights: " + ", ".join(f"{CRITERIA_TITLES[n].split(' (')[0]} {100 * w:.0f}%"
                                                     for n, w in zip(CRITERIA, weights)))

st.sidebar.header("Sites and constraints")
threshold = st.sidebar.slider("Suitability threshold for a site", 0.50, 0.90,
                              float(CONFIG["site_extraction"]["threshold"]), step=0.01)
min_area = st.sidebar.slider("Minimum site area (ha)", 10, 200, int(CONFIG["site_extraction"]["min_area_ha"]), step=10)
max_slope = st.sidebar.slider("Maximum slope allowed (degrees)", 5, 20, int(CONFIG["constraints"]["max_slope"]), step=1)
buffer_m = st.sidebar.slider("Residential buffer (m)", 0, 2000, int(CONFIG["constraints"]["residential_buffer_m"]), step=100)

# ----------------------------------------------------------------- main
st.title("Utility-Scale Solar Farm Site Suitability")
st.markdown(
    "This app screens an 18 km x 18 km desert basin near Kingman, Arizona (synthetic scene, UTM 12N) for "
    "utility-scale photovoltaic sites. Six criteria (solar resource, slope, aspect, distance to grid, distance "
    "to roads, land use) are standardised to 0-1, weighted with the Analytic Hierarchy Process and combined "
    "in a weighted overlay; water, urban, protected land, steep slopes and a residential buffer are masked out. "
    "Contiguous high-scoring patches become ranked candidate sites with an estimated capacity and annual energy."
)

with st.spinner("Running the suitability pipeline ..."):
    results = cached_pipeline(int(size), int(seed), weights, float(threshold), float(min_area),
                              float(max_slope), float(buffer_m))
summary = results["summary"]
sites = results["sites"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Candidate sites", f"{summary['n_candidate_sites']}")
c2.metric("Total capacity", f"{summary['total_capacity_mw']:,.0f} MW")
c3.metric("Best site", f"{summary['best_site_mw']:,.0f} MW")
c4.metric("Area excluded", f"{summary['pct_area_excluded']:.1f} %")

tab_maps, tab_web, tab_stats, tab_method = st.tabs(["Maps", "Interactive map", "Statistics", "Method"])

with tab_maps:
    st.pyplot(fig_hero(results))
    col_a, col_b = st.columns(2)
    with col_a:
        st.pyplot(fig_suitability(results))
        st.pyplot(fig_constraints(results))
        st.pyplot(fig_terrain(results))
    with col_b:
        st.pyplot(fig_candidate_sites(results))
        st.pyplot(fig_site_capacity(results))
        st.pyplot(fig_ahp_weights(results))
    st.pyplot(fig_criteria_panel(results))

with tab_web:
    st.caption("Layers: suitability index, constraint mask, candidate sites (hover for rank, area, capacity, "
               "energy), transmission lines, roads and substations.")
    m = build_web_map(results)
    if hasattr(st, "iframe"):  # Streamlit >= 1.50; components.v1.html is deprecated
        st.iframe(m._repr_html_(), height=600)
    else:
        st.components.v1.html(m._repr_html_(), height=600)

with tab_stats:
    st.subheader("Candidate sites")
    if len(sites):
        st.dataframe(sites.drop(columns="geometry").set_index("rank"))
    else:
        st.info("No site meets the threshold and minimum area. Lower the threshold or the minimum area.")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Criteria weights")
        st.dataframe(pd.DataFrame({"criterion": [CRITERIA_TITLES[n] for n in CRITERIA],
                                   "weight": [round(results["weights"][n], 4) for n in CRITERIA],
                                   "AHP default": [round(AHP_WEIGHTS[n], 4) for n in CRITERIA]}),
                     hide_index=True)
        st.caption(f"AHP matrix: lambda_max {AHP_CONSISTENCY['lambda_max']:.3f}, CI {AHP_CONSISTENCY['CI']:.3f}, "
                   f"CR {AHP_CONSISTENCY['CR']:.3f}")
    with col2:
        st.subheader("Constraints (% of area)")
        rows = [{"reason": k, "pct_area": v} for k, v in summary["pct_excluded_by_reason"].items()]
        rows.append({"reason": "Total excluded", "pct_area": summary["pct_area_excluded"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    with col3:
        st.subheader("Suitability classes")
        st.dataframe(results["class_table"], hide_index=True)

with tab_method:
    st.markdown(f"""
### Method

1. **Terrain**: slope and aspect from the DEM with Horn's 3x3 kernel; hillshade for display.
2. **Distances**: Euclidean distance rasters (metres) to transmission lines, substations, roads and
   residential polygons. Grid distance = min(distance to line, distance to substation).
3. **Standardisation** (0 = unsuitable, 1 = ideal):
   - GHI: linear from {CONFIG['criteria']['ghi']['lo']} to {CONFIG['criteria']['ghi']['hi']} kWh/m²/day
   - Slope: 1 up to {CONFIG['criteria']['slope']['ideal']}°, linear to 0 at {CONFIG['criteria']['slope']['max_ok']}°
   - Aspect: (1 + cos(aspect - 180°)) / 2, flat = 1
   - Distance to grid / roads: 1 within {CONFIG['criteria']['grid_distance']['full_score_within']} m, 0 at
     {CONFIG['criteria']['grid_distance']['zero_at']} m (linear)
   - Land use: look-up table (desert scrub 1.0, agriculture 0.4, others 0)
4. **Weights**: AHP pairwise matrix (Saaty 1-9), row geometric mean, consistency ratio must be < 0.10.
   The sidebar sliders override the AHP weights after normalisation.
5. **Constraints**: water, urban and protected land, slope > {max_slope}°, and {buffer_m} m around residential
   polygons are excluded (set to NaN).
6. **Overlay**: index = sum(w_i * score_i) on the allowed pixels; classes at
   {', '.join(str(t) for t in CONFIG['classification']['thresholds'])}.
7. **Sites**: contiguous patches (8-connected) with index >= {threshold:.2f} and area >= {min_area} ha.
   capacity_mw = area_ha / {CONFIG['site_extraction']['ha_per_mw']} (about 2 ha per MW, fixed tilt);
   annual_gwh = area_m² x GHI x 365 x {CONFIG['site_extraction']['module_efficiency']} (module efficiency) x
   {CONFIG['site_extraction']['ground_cover_ratio']} (ground cover ratio) x
   {CONFIG['site_extraction']['performance_ratio']} (performance ratio) / 1e6.
   Rank = mean suitability x sqrt(area / largest area).

Constraint reason codes: {', '.join(f'{k} = {v}' for k, v in CONSTRAINT_LABELS.items())}.

Real data sources: NREL NSRDB (GHI), USGS 3DEP (DEM), HIFLD (transmission lines, substations), NLCD (land
cover), USGS PAD-US (protected areas), TIGER/Line (roads). See the README for how config.yaml points to them.
""")
