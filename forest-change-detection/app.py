"""
Streamlit app: Forest Change Detection with Sentinel-2 (synthetic Rondônia scene).

    streamlit run app.py
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.pipeline import run_pipeline  # noqa: E402
from src.report import class_area_table  # noqa: E402
from src.synthetic_data import generate_demo_data  # noqa: E402
from src.utils import load_config  # noqa: E402
from src.visualize import (build_web_map, plot_change_map, plot_classified_pair,  # noqa: E402
                           plot_confusion_matrix, plot_dnbr, plot_false_color_pair,
                           plot_feature_importance, plot_hero, plot_patch_histogram)

st.set_page_config(page_title="Forest Change Detection", page_icon="🌳", layout="wide")

CFG = load_config(ROOT / "config.yaml")
DATES = CFG["dates"]
RULES = {
    "Both agree (conservative)": "both",
    "Post-classification only": "post_classification",
    "dNBR only": "dnbr",
}


@st.cache_data(show_spinner="Generating scene and running the pipeline...")
def run(size: int, seed: int, intensity: float, mmu_ha: float, dnbr_thresh: float,
        n_trees: int, rule: str) -> dict:
    data = generate_demo_data(size=size, seed=seed, out_dir=None, clearing_intensity=intensity,
                              pixel_size=float(CFG["study_area"]["pixel_size_m"]))
    res = run_pipeline(
        data, out_dir=None,
        forest_class=int(CFG["classes"]["forest_class"]),
        n_per_class=int(CFG["classification"]["n_samples_per_class"]),
        n_estimators=n_trees, seed=seed,
        dnbr_loss_threshold=dnbr_thresh, evidence_rule=rule, mmu_ha=mmu_ha,
        road_distance_m=float(CFG["change_detection"]["road_distance_m"]),
        years=float(DATES["years_between"]),
    )
    res.pop("classifier", None)  # keep the cached object small and picklable
    return res


# ----------------------------------------------------------------------------- sidebar
st.sidebar.header("Scene")
size = st.sidebar.slider("Grid size (pixels, 20 m each)", 100, 200, 160, step=10)
seed = st.sidebar.number_input("Random seed", min_value=0, max_value=9999, value=42, step=1)
intensity = st.sidebar.slider("Clearing intensity (x number / size of clearings)", 0.5, 2.0, 1.0, step=0.1)

st.sidebar.header("Method")
mmu_ha = st.sidebar.slider("Minimum mapping unit (ha)", 0.1, 2.0, 0.5, step=0.1)
dnbr_thresh = st.sidebar.slider("dNBR loss threshold", 0.10, 0.50, 0.27, step=0.01)
n_trees = st.sidebar.slider("Random Forest trees", 50, 300, 100, step=10)
rule_label = st.sidebar.selectbox("Evidence rule", list(RULES.keys()), index=0)

results = run(int(size), int(seed), float(intensity), float(mmu_ha), float(dnbr_thresh),
              int(n_trees), RULES[rule_label])
stats = results["stats"]
acc = results["accuracy"]

# ----------------------------------------------------------------------------- main
st.title("Forest Change Detection with Sentinel-2")
st.markdown(
    f"A synthetic {size * 20 / 1000:.1f} km x {size * 20 / 1000:.1f} km scene in Rondônia, Brazil "
    f"({DATES['t1']} to {DATES['t2']}) is classified with a Random Forest into five land-cover classes. "
    "Forest loss is mapped where the post-classification comparison and the dNBR spectral change agree, "
    "small patches below the minimum mapping unit are dropped, and the remaining patches are vectorised "
    "and related to the road network."
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Overall accuracy", f"{acc['overall_accuracy']:.3f}")
c2.metric("Kappa", f"{acc['kappa']:.3f}")
c3.metric("Forest loss", f"{stats['forest_loss_ha']:.1f} ha", f"{stats['forest_loss_pct_of_t1']:.2f} % of T1 forest",
          delta_color="inverse")
c4.metric("Annual loss rate", f"{stats['annual_loss_rate_pct']:.2f} %/yr")
c5.metric("Loss patches", f"{stats['n_loss_patches']}", f"largest {stats['max_patch_ha']:.2f} ha", delta_color="off")

tab_maps, tab_web, tab_stats, tab_method = st.tabs(["Maps", "Interactive map", "Statistics", "Method"])

with tab_maps:
    for fn, args in [(plot_hero, (results, DATES)), (plot_false_color_pair, (results, DATES)),
                     (plot_classified_pair, (results, DATES)), (plot_change_map, (results,)),
                     (plot_dnbr, (results,)), (plot_confusion_matrix, (results,)),
                     (plot_patch_histogram, (results,)), (plot_feature_importance, (results,))]:
        fig = fn(*args)
        st.pyplot(fig)
        plt.close(fig)

with tab_web:
    m = build_web_map(results, DATES)
    components.html(m._repr_html_(), height=600)

with tab_stats:
    st.subheader("Accuracy on held-out samples")
    st.dataframe(acc["per_class"].round({"producers_accuracy": 3, "users_accuracy": 3}), hide_index=True)
    cm = pd.DataFrame(acc["confusion_matrix"],
                      index=[f"ref: {n}" for n in acc["class_names"]],
                      columns=[f"pred: {n}" for n in acc["class_names"]])
    st.dataframe(cm)

    st.subheader("Area statistics")
    flat = {k: v for k, v in stats.items() if not isinstance(v, dict)}
    st.dataframe(pd.DataFrame({"metric": list(flat.keys()), "value": [str(v) for v in flat.values()]}),
                 hide_index=True)
    st.dataframe(class_area_table(stats).round(1), hide_index=True)

    st.subheader("Loss patches")
    gdf = results["loss_gdf"]
    if len(gdf) > 0:
        st.dataframe(gdf.drop(columns="geometry").sort_values("area_ha", ascending=False)
                     .round({"area_ha": 2, "dist_road_m": 0, "centroid_x": 0, "centroid_y": 0}),
                     hide_index=True)
    else:
        st.info("No loss patches above the minimum mapping unit.")

    st.subheader("Feature importance")
    st.dataframe(results["importances"].round(4).rename_axis("feature").reset_index(), hide_index=True)

with tab_method:
    st.markdown(
        f"""
### How the pipeline works

1. **Synthetic scene.** Six Sentinel-2 bands (B02, B03, B04, B08, B11, B12) are simulated at 20 m for two
   dates from a truth map with forest, pasture, water, roads and regrowth. At T2 fishbone strips and
   blob clearings are added along the roads and two cloud blobs mask part of the image.
2. **Features.** The six bands plus NDVI, NBR and NDMI give nine features per pixel.
3. **Sampling.** Up to {CFG['classification']['n_samples_per_class']} pixels per class and date are drawn
   at random (stratified) and split 70 / 30 into training and held-out test pixels. Cloud pixels are excluded.
4. **Random Forest.** `RandomForestClassifier(n_estimators={n_trees})` trained on both dates so that the
   model is not tuned to one date's illumination.
5. **Accuracy.** Error matrix on the held-out pixels: overall accuracy, kappa, producer's and user's accuracy.
6. **Post-classification change.** Forest at T1 and non-forest at T2 is candidate loss; the reverse is gain.
7. **dNBR.** `dNBR = NBR(T1) - NBR(T2)`; pixels with dNBR >= {dnbr_thresh:.2f} show spectral canopy removal
   (0.27 is the USGS burn-severity break between low and moderate-low severity).
8. **Evidence rule.** *{rule_label}*: with "both agree" a pixel is loss only if the classifier AND dNBR flag it.
   That is deliberately conservative: it trades some missed loss for far fewer false alarms.
9. **Minimum mapping unit.** Patches smaller than {mmu_ha:.1f} ha ({results['mmu_pixels']} pixels) are
   removed with 8-connected component labelling.
10. **Vectorise and report.** Remaining loss pixels become polygons with area and distance to the nearest
    road; forest area, loss, annual rate and patch statistics are summarised.

Detected {stats['truth_loss_detected_pct']:.1f} % of the synthetic truth loss ({stats['truth_loss_ha']:.1f} ha)
with {stats['false_alarm_ha']:.1f} ha of false alarms under the current settings.
"""
    )
