"""Tests for the Random Forest land-cover classifier."""

import numpy as np
import pytest

from src.classifier import LandCoverClassifier
from src.synthetic_data import spectral_stack


@pytest.fixture(scope="module")
def tiny_scene():
    """40x40 truth raster with 5 class blocks and its simulated 6-band stack."""
    ref = np.ones((40, 40), dtype=np.uint8)
    ref[:, 8:16] = 2
    ref[:, 16:24] = 3
    ref[:, 24:32] = 4
    ref[:, 32:40] = 5
    rng = np.random.default_rng(7)
    stack = spectral_stack(ref, rng)
    return stack, ref


def test_build_features_shape(tiny_scene):
    stack, _ = tiny_scene
    feats = LandCoverClassifier.build_features(stack)
    assert feats.shape == (1600, 9)
    assert LandCoverClassifier.FEATURE_NAMES[6:] == ["NDVI", "NBR", "NDMI"]


def test_sample_training_is_stratified_and_split(tiny_scene):
    _, ref = tiny_scene
    s = LandCoverClassifier.sample_training(ref, n_per_class=50, seed=1)
    assert len(s["train_idx"]) == 5 * 35 and len(s["test_idx"]) == 5 * 15
    assert not set(s["train_idx"]) & set(s["test_idx"])
    assert sorted(np.unique(s["train_labels"])) == [1, 2, 3, 4, 5]
    s2 = LandCoverClassifier.sample_training(ref, n_per_class=50, seed=1)
    assert np.array_equal(s["train_idx"], s2["train_idx"])   # deterministic


def test_fit_reaches_high_test_accuracy(tiny_scene):
    stack, ref = tiny_scene
    clf = LandCoverClassifier(n_estimators=60, random_state=0).fit(stack, ref, n_per_class=80, seed=0)
    y_true, y_pred = clf.predict_test()
    assert (y_true == y_pred).mean() > 0.9
    pred = clf.predict(stack)
    assert pred.shape == ref.shape and pred.dtype == np.uint8
    assert (pred == ref).mean() > 0.9
    imp = clf.feature_importances()
    assert len(imp) == 9 and abs(imp.sum() - 1.0) < 1e-6


def test_predict_masks_clouds(tiny_scene):
    stack, ref = tiny_scene
    clf = LandCoverClassifier(n_estimators=30, random_state=0).fit(stack, ref, n_per_class=40, seed=0)
    cloud = np.zeros_like(ref, dtype=bool)
    cloud[:5, :5] = True
    pred = clf.predict(stack, cloud_mask=cloud)
    assert np.all(pred[cloud] == 0) and np.all(pred[~cloud] > 0)
