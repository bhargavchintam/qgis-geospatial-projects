"""
Streamlit app: Healthcare Accessibility and Facility Site Selection.

    streamlit run app.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.pipeline import run_pipeline
from src.synthetic_data import generate_demo_data
from src.utils import load_config
from src.visualize import (build_web_map, plot_access_score, plot_coverage_before_after,
                           plot_isochrones, plot_road_network, plot_travel_time_choropleth,
                           plot_underserved_and_sites)

ROOT = Path(__file__).parent
CFG = load_config(ROOT / "config.yaml")

st.set_page_config(page_title="Healthcare Accessibility (2SFCA)", page_icon="🏥", layout="wide")


@st.cache_data(show_spinner="Building the network and running the analysis...")
def run(n: int, seed: int, threshold_min: float, k_new: int, decay: str):
    out_dir = ROOT / "results" / "app" / f"n{n}_seed{seed}"
    data = generate_demo_data(
        size=n, seed=seed, out_dir=out_dir,
        spacing_m=float(CFG["network"]["spacing_m"]),
        block_size_m=float(CFG["demand"]["block_size_m"]),
        density_per_km2=float(CFG["demand"]["density_per_km2"]),
        removal_fraction=float(CFG["network"]["removal_fraction"]),
    )
    res = run_pipeline(
        data,
        threshold_min=threshold_min,
        decay=decay,
        k_new_sites=k_new,
        breaks_min=CFG["analysis"]["isochrone_breaks_min"],
        bottom_quantile=float(CFG["analysis"]["underserved_bottom_quantile"]),
        new_site_beds=float(CFG["facilities"]["new_site_beds"]),
        candidate_every=int(CFG["analysis"]["candidate_every_nth_node"]),
        candidate_min_dist_m=float(CFG["analysis"]["candidate_min_dist_m"]),
    )
    res["centre_lonlat"] = data["centre_lonlat"]
    return res


# ------------------------------------------------------------- sidebar --
st.sidebar.header("Parameters")
n = st.sidebar.slider("Grid size (nodes per side)", 25, 45, int(CFG["network"]["grid_nodes"]), step=1,
                      help="40 nodes at 250 m spacing = a 10 km x 10 km city")
seed = st.sidebar.number_input("Random seed", min_value=0, max_value=9999, value=int(CFG["network"]["seed"]), step=1)
threshold = st.sidebar.slider("Catchment threshold (minutes)", 10, 30, int(CFG["analysis"]["threshold_min"]), step=1)
k_new = st.sidebar.slider("Number of new facilities", 0, 4, int(CFG["analysis"]["k_new_sites"]), step=1)
decay = st.sidebar.selectbox("Distance decay", ["gaussian", "none"],
                             index=0 if CFG["analysis"]["decay"] == "gaussian" else 1)
st.sidebar.caption("Synthetic Fresno-like city, EPSG:32611. Everything runs offline.")

res = run(int(n), int(seed), float(threshold), int(k_new), decay)
G = res["graph"]
cb, ca = res["coverage_before"], res["coverage_after"]
und = res["blocks_before"][res["blocks_before"]["underserved"]]

# ---------------------------------------------------------------- main --
st.title("Healthcare Accessibility and Facility Site Selection")
st.markdown(
    "This app measures how easily residents can reach a hospital by road. It computes drive times "
    "on a street network with multi-source Dijkstra, builds isochrones, scores every census block with "
    "the two-step floating catchment area (2SFCA) method, flags underserved blocks, and then picks new "
    "facility sites with a greedy maximal-covering heuristic."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Population within {threshold} min (before)", f"{cb['pct_population_covered']:.1f} %")
c2.metric(f"Population within {threshold} min (after)", f"{ca['pct_population_covered']:.1f} %",
          delta=f"{ca['pct_population_covered'] - cb['pct_population_covered']:+.1f} pts")
c3.metric("Underserved population (before)", f"{int(und['population'].sum()):,}",
          help=f"{len(und)} blocks in the bottom 20 % of access score or beyond {threshold} min")
c4.metric("Mean access score (beds / 1,000)", f"{cb['mean_access_score']:.2f}",
          delta=f"{ca['mean_access_score'] - cb['mean_access_score']:+.2f} after new sites")

tab_maps, tab_web, tab_stats, tab_method = st.tabs(["Maps", "Interactive map", "Statistics", "Method"])

with tab_maps:
    roads, iso, hosp, sites, river = res["roads"], res["isochrones"], res["hospitals"], res["sites"], res["river"]
    blocks_b = res["blocks_before"]
    left, right = st.columns(2)
    with left:
        fig = plot_road_network(roads, hosp, river); st.pyplot(fig); plt.close(fig)
        fig = plot_travel_time_choropleth(blocks_b, hosp); st.pyplot(fig); plt.close(fig)
        fig = plot_underserved_and_sites(blocks_b, hosp, sites, river, roads); st.pyplot(fig); plt.close(fig)
    with right:
        fig = plot_isochrones(iso, roads, hosp, river); st.pyplot(fig); plt.close(fig)
        fig = plot_access_score(blocks_b, hosp, threshold_min=threshold); st.pyplot(fig); plt.close(fig)
        fig = plot_coverage_before_after(res["coverage_steps"], threshold); st.pyplot(fig); plt.close(fig)

with tab_web:
    m = build_web_map(res["roads"], res["isochrones"], res["blocks_before"], res["hospitals"],
                      res["sites"], res["river"], threshold, centre_lonlat=res["centre_lonlat"])
    components.html(m._repr_html_(), height=600)

with tab_stats:
    st.subheader("Network")
    st.dataframe(pd.DataFrame({
        "metric": ["nodes", "edges", "bridges", "road length (km)", "blocks", "residents", "hospitals", "beds"],
        "value": [G.number_of_nodes(), G.number_of_edges(), int(res["roads"]["bridge"].sum()),
                  round(res["roads"]["length_m"].sum() / 1000, 1), len(blocks_b),
                  int(cb["population_total"]), len(hosp), int(hosp["beds"].sum())],
    }), hide_index=True)
    st.subheader("Coverage after each proposed site")
    st.dataframe(pd.DataFrame(res["coverage_steps"], columns=["step", f"% population within {threshold} min"]),
                 hide_index=True)
    if len(sites):
        st.subheader("Proposed sites")
        st.dataframe(sites.drop(columns="geometry").assign(x=sites.geometry.x.round(0), y=sites.geometry.y.round(0)),
                     hide_index=True)
    st.subheader("Hospitals")
    st.dataframe(hosp[["hospital_id", "name", "type", "beds", "node", "snap_dist_m"]].round(1),
                 hide_index=True)
    st.subheader("Block statistics (before)")
    st.dataframe(blocks_b[["population", "median_income", "svi", "tt_nearest_min", "access_score"]].describe().round(2))
    st.subheader("Isochrone band areas (km²)")
    st.dataframe(iso[["min_minutes", "max_minutes", "area_km2"]].round(2), hide_index=True)

with tab_method:
    st.markdown(
        r"""
### Method

1. **Travel-time graph.** Every road segment gets `travel_time_s = length / speed + junction delay`
   (30 / 50 / 65 / 100 km/h for residential / secondary / primary / motorway).
2. **Multi-source Dijkstra.** All hospitals are seeded at time 0 and one Dijkstra pass gives the
   drive time from the *nearest* hospital to every node (`networkx.multi_source_dijkstra`).
3. **Isochrones.** Road segments reached within 5, 10, 15, 20 and 30 minutes (partially reached
   segments are cut at the time budget) are buffered and unioned; bands are differenced so they do not overlap.
4. **2SFCA access score.** With catchment size $d_0$ and decay weight $f(d)$:

   Step 1, supply-to-demand ratio of every hospital $j$ with $S_j$ beds:
   $R_j = \dfrac{S_j}{\sum_{k:\, d_{kj} \le d_0} P_k\, f(d_{kj})}$

   Step 2, access of every block $i$:
   $A_i = \sum_{j:\, d_{ij} \le d_0} R_j\, f(d_{ij})$ (reported as beds per 1,000 residents).

   $f(d) = 1$ for `none`; Gaussian decay
   $f(d) = \dfrac{e^{-\frac{1}{2}(d/d_0)^2} - e^{-1/2}}{1 - e^{-1/2}}$ for `gaussian`.
5. **Underserved blocks.** Bottom 20 % of population by access score, or nearest hospital beyond the threshold.
6. **Greedy maximal covering.** Candidate nodes are every 4th grid node at least 1 km from an existing
   hospital. At each step the candidate that brings the largest *newly* covered population within the
   threshold is chosen (greedy MCLP, within 1 - 1/e of optimal).
"""
    )
