"""End-to-end test at a tiny size (must finish in < 10 s)."""

import time
from pathlib import Path

import numpy as np

from src.pipeline import run_pipeline
from src.synthetic_data import generate_demo_data


def test_end_to_end_small(tmp_path):
    t0 = time.perf_counter()
    data = generate_demo_data(size=40, seed=1, out_dir=tmp_path / "data")
    assert data["t1_stack"].shape == (6, 40, 40) and data["t2_stack"].dtype == np.float32
    assert 0.0 <= float(data["t1_stack"].min()) and float(data["t2_stack"].max()) <= 1.0
    assert set(np.unique(data["reference_t1"])) <= {1, 2, 3, 4, 5}
    assert 5 in np.unique(data["reference_t2"])          # regrowth appears at T2
    assert data["cloud_mask_t2"].any()
    for key in ("t1_stack", "t2_stack", "reference_t1", "reference_t2", "cloud_mask_t2", "roads", "river"):
        assert Path(data["paths"][key]).exists(), key

    res = run_pipeline(data, out_dir=tmp_path / "out", n_per_class=60, n_estimators=40, seed=1)
    assert res["class_t1"].shape == (40, 40) and res["class_t2"].dtype == np.uint8
    assert np.all(res["class_t2"][data["cloud_mask_t2"]] == 0)
    assert set(np.unique(res["change"])) <= {0, 1, 2, 3, 4}
    assert 0.0 <= res["accuracy"]["overall_accuracy"] <= 1.0
    assert res["accuracy"]["overall_accuracy"] > 0.8
    assert res["mmu_pixels"] == 13                        # 0.5 ha at 20 m
    stats = res["stats"]
    assert stats["forest_area_t1_ha"] > 0
    assert stats["forest_loss_ha"] == (res["change"] == 3).sum() * 0.04
    assert abs(res["loss_gdf"]["area_ha"].sum() - stats["forest_loss_ha"]) < 1e-6
    for key in ("class_t1", "class_t2", "change", "dnbr", "confusion_matrix", "accuracy_per_class",
                "feature_importance", "area_statistics"):
        assert Path(res["paths"][key]).exists(), key
    assert time.perf_counter() - t0 < 10.0


def test_generation_is_deterministic():
    a = generate_demo_data(size=30, seed=5, out_dir=None)
    b = generate_demo_data(size=30, seed=5, out_dir=None)
    assert np.array_equal(a["t2_stack"], b["t2_stack"])
    assert np.array_equal(a["reference_t2"], b["reference_t2"])
    c = generate_demo_data(size=30, seed=6, out_dir=None)
    assert not np.array_equal(a["t2_stack"], c["t2_stack"])
