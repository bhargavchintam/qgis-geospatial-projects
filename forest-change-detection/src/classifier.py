"""
Supervised land-cover classification with a Random Forest.

The feature stack per pixel is the six Sentinel-2 reflectance bands plus three
spectral indices (NDVI, NBR, NDMI). Training samples are drawn from a reference
(truth) raster with stratified random sampling and split 70/30 into train and
held-out test pixels. The held-out pixels are used for the accuracy assessment.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from .indices import BAND_NAMES, compute_all


class LandCoverClassifier:
    """Random Forest land-cover classifier for 6-band Sentinel-2 stacks."""

    CLASSES = {1: "Forest", 2: "Pasture/Cleared", 3: "Water", 4: "Bare/Road", 5: "Regrowth"}
    FEATURE_NAMES = BAND_NAMES + ["NDVI", "NBR", "NDMI"]

    def __init__(self, n_estimators: int = 100, random_state: int = 42, n_jobs: int = -1):
        self.n_estimators = int(n_estimators)
        self.random_state = int(random_state)
        self.model = RandomForestClassifier(
            n_estimators=self.n_estimators, n_jobs=n_jobs, random_state=self.random_state
        )
        self.train_features = None
        self.train_labels = None
        self.test_features = None
        self.test_labels = None
        self.test_samples = []  # one dict per input date: {"test_idx", "train_idx"}
        self.fitted = False

    # ------------------------------------------------------------------ features
    @staticmethod
    def build_features(stack: np.ndarray) -> np.ndarray:
        """
        Turn a (6, rows, cols) stack into an (n_pixels, 9) feature matrix.

        Columns: B02, B03, B04, B08, B11, B12, NDVI, NBR, NDMI.
        """
        if stack.ndim != 3 or stack.shape[0] != 6:
            raise ValueError(f"Expected a (6, rows, cols) stack, got {stack.shape}")
        idx = compute_all(stack)
        bands = [stack[i].ravel() for i in range(6)]
        extra = [idx["ndvi"].ravel(), idx["nbr"].ravel(), idx["ndmi"].ravel()]
        return np.column_stack(bands + extra).astype(np.float32)

    # ------------------------------------------------------------------ sampling
    @staticmethod
    def sample_training(reference: np.ndarray, n_per_class: int, seed: int,
                        train_fraction: float = 0.7, valid_mask=None) -> dict:
        """
        Stratified random pixel sampling from a reference raster.

        For each class value > 0 up to ``n_per_class`` pixels are drawn without
        replacement (fewer if the class is rare). The sample is then split into
        train / test by ``train_fraction`` (default 70/30).

        Returns
        -------
        dict with flat pixel indices: ``train_idx``, ``test_idx`` and the matching
        ``train_labels``, ``test_labels``.
        """
        rng = np.random.default_rng(seed)
        ref = np.asarray(reference).ravel()
        usable = ref > 0
        if valid_mask is not None:
            usable &= np.asarray(valid_mask, dtype=bool).ravel()
        train_idx, test_idx = [], []
        for cls in np.unique(ref[usable]):
            candidates = np.flatnonzero(usable & (ref == cls))
            n_take = min(int(n_per_class), candidates.size)
            chosen = rng.choice(candidates, size=n_take, replace=False)
            n_train = int(round(n_take * train_fraction))
            if n_take >= 2:
                n_train = min(max(n_train, 1), n_take - 1)
            train_idx.append(chosen[:n_train])
            test_idx.append(chosen[n_train:])
        train_idx = np.concatenate(train_idx) if train_idx else np.array([], dtype=int)
        test_idx = np.concatenate(test_idx) if test_idx else np.array([], dtype=int)
        return {
            "train_idx": train_idx,
            "test_idx": test_idx,
            "train_labels": ref[train_idx].astype(np.uint8),
            "test_labels": ref[test_idx].astype(np.uint8),
        }

    # ------------------------------------------------------------------ fit / predict
    def fit(self, stacks, references, n_per_class: int = 400, seed: int = 42, valid_masks=None):
        """
        Train the Random Forest.

        ``stacks`` / ``references`` may be a single array or a list of arrays
        (one per acquisition date). Samples from every date are pooled so the
        model sees both dates. ``valid_masks`` (optional, same length) exclude
        pixels such as clouds from sampling.
        """
        if isinstance(stacks, np.ndarray):
            stacks = [stacks]
            references = [references]
            valid_masks = [valid_masks]
        if valid_masks is None:
            valid_masks = [None] * len(stacks)

        X_train, y_train, X_test, y_test = [], [], [], []
        self.test_samples = []
        for i, (stack, ref, vmask) in enumerate(zip(stacks, references, valid_masks)):
            feats = self.build_features(stack)
            finite = np.isfinite(feats).all(axis=1)
            vm = finite if vmask is None else (finite & np.asarray(vmask, dtype=bool).ravel())
            sample = self.sample_training(ref, n_per_class, seed + i, valid_mask=vm)
            X_train.append(feats[sample["train_idx"]])
            y_train.append(sample["train_labels"])
            X_test.append(feats[sample["test_idx"]])
            y_test.append(sample["test_labels"])
            self.test_samples.append({"date_index": i, "train_idx": sample["train_idx"],
                                      "test_idx": sample["test_idx"]})

        self.train_features = np.vstack(X_train)
        self.train_labels = np.concatenate(y_train)
        self.test_features = np.vstack(X_test)
        self.test_labels = np.concatenate(y_test)
        self.model.fit(self.train_features, self.train_labels)
        self.fitted = True
        return self

    def predict(self, stack: np.ndarray, cloud_mask=None) -> np.ndarray:
        """
        Classify a stack. Returns a uint8 class raster (rows, cols).

        Pixels under ``cloud_mask`` (True = cloud) or with non-finite features
        are set to 0 (no data).
        """
        if not self.fitted:
            raise RuntimeError("Call fit() before predict().")
        rows, cols = stack.shape[1], stack.shape[2]
        feats = self.build_features(stack)
        valid = np.isfinite(feats).all(axis=1)
        if cloud_mask is not None:
            valid &= ~np.asarray(cloud_mask, dtype=bool).ravel()
        out = np.zeros(rows * cols, dtype=np.uint8)
        if valid.any():
            out[valid] = self.model.predict(feats[valid]).astype(np.uint8)
        return out.reshape(rows, cols)

    def predict_test(self) -> tuple:
        """Predict the held-out samples. Returns (y_true, y_pred)."""
        if not self.fitted:
            raise RuntimeError("Call fit() before predict_test().")
        y_pred = self.model.predict(self.test_features).astype(np.uint8)
        return self.test_labels.copy(), y_pred

    def feature_importances(self) -> pd.Series:
        """Gini importances as a Series indexed by feature name, largest first."""
        if not self.fitted:
            raise RuntimeError("Call fit() before feature_importances().")
        s = pd.Series(self.model.feature_importances_, index=self.FEATURE_NAMES, name="importance")
        return s.sort_values(ascending=False)
