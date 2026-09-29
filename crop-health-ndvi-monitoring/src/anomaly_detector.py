"""
Spatial Anomaly Detection for Crop Health

Detects areas of crop stress by identifying pixels that deviate
significantly from expected values (field average or phenology baseline).

Methods:
    - Z-score thresholding
    - Isolation Forest (unsupervised ML)
    - Local Outlier Factor (LOF)
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np
from scipy import ndimage

from .utils import load_config, write_raster

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Detects spatial anomalies in vegetation index maps.

    Identifies areas where crop health deviates significantly from
    expected patterns, indicating potential stress, disease, or damage.
    """

    def __init__(self, config_path: str = "config.yaml", config: Optional[dict] = None):
        self.config = config if config is not None else load_config(config_path)
        self.anomaly_cfg = dict(self.config["anomaly"])

    def detect(
        self,
        current: np.ndarray,
        baseline: Optional[np.ndarray] = None,
        method: Optional[str] = None,
        profile: Optional[dict] = None,
        output_path: Optional[str] = None,
        threshold: Optional[float] = None,
        min_cluster_ha: Optional[float] = None,
    ) -> Tuple[np.ndarray, Dict]:
        """
        Detect anomalous (stressed) areas in a vegetation index map.

        Args:
            current: current observation array (e.g., NDVI)
            baseline: expected baseline array (from phenology or historical)
            method: detection method (z_score, isolation_forest, lof)
            profile: rasterio profile for output / pixel size
            output_path: optional path to save the anomaly map (uint8 0/1)
            threshold: override of the configured z-score threshold
            min_cluster_ha: override of the configured minimum cluster size

        Returns:
            tuple: (anomaly boolean mask, statistics dict)
        """
        method = method or self.anomaly_cfg["method"]
        logger.info(f"Detecting anomalies using method: {method}")

        if method == "z_score":
            anomaly_map, scores = self._z_score_detection(current, baseline, threshold)
        elif method == "isolation_forest":
            anomaly_map, scores = self._isolation_forest_detection(current)
        elif method == "lof":
            anomaly_map, scores = self._lof_detection(current)
        else:
            raise ValueError(f"Unknown anomaly detection method: {method}")

        min_area_ha = self.anomaly_cfg.get("min_cluster_ha", 0.5) if min_cluster_ha is None else min_cluster_ha
        anomaly_map, n_removed = self._filter_small_clusters(anomaly_map, min_area_ha, profile)

        stats = self._compute_anomaly_statistics(anomaly_map, current, scores)
        stats["method"] = method
        stats["min_cluster_ha"] = float(min_area_ha)
        stats["clusters_removed_small"] = int(n_removed)
        if method == "z_score":
            stats["z_threshold"] = float(self.anomaly_cfg.get("z_score_threshold", -1.5) if threshold is None else threshold)

        if output_path and profile:
            out = np.where(np.isnan(current), 255, anomaly_map.astype(np.uint8)).astype(np.uint8)
            write_raster(out, profile, output_path, dtype="uint8", nodata=255)
            logger.info(f"Anomaly map saved to: {output_path}")

        return anomaly_map, stats

    def z_scores(self, current: np.ndarray, baseline: Optional[np.ndarray] = None) -> np.ndarray:
        """Per-pixel z-score of the residual (current - baseline), or of current alone."""
        residuals = current - baseline if baseline is not None else current.copy()
        mean_residual = np.nanmean(residuals)
        std_residual = np.nanstd(residuals)
        if not np.isfinite(std_residual) or std_residual == 0:
            std_residual = 1e-10
        return (residuals - mean_residual) / std_residual

    def _z_score_detection(
        self,
        current: np.ndarray,
        baseline: Optional[np.ndarray] = None,
        threshold: Optional[float] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Z-score based anomaly detection.

        Computes per-pixel z-scores of the residual against the baseline
        (phenology-expected) if provided, else of the raw values against
        the scene mean/std. Pixels below the threshold are anomalous.
        """
        if threshold is None:
            threshold = self.anomaly_cfg.get("z_score_threshold", -1.5)
        z = self.z_scores(current, baseline)
        with np.errstate(invalid="ignore"):
            anomaly_mask = z < threshold
        anomaly_mask = np.where(np.isnan(current) | np.isnan(z), False, anomaly_mask)

        n_valid = int(np.sum(~np.isnan(current)))
        logger.info(
            f"Z-score detection: threshold={threshold}, anomalous={int(anomaly_mask.sum())}/{n_valid} pixels"
        )
        return anomaly_mask, z

    def _isolation_forest_detection(self, current: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Isolation Forest anomaly detection.

        Uses spatial context (local window statistics) as features
        for unsupervised outlier detection.
        """
        from sklearn.ensemble import IsolationForest

        iso_cfg = self.anomaly_cfg.get("isolation_forest", {})
        contamination = iso_cfg.get("contamination", 0.05)
        n_estimators = iso_cfg.get("n_estimators", 100)

        features = self._extract_spatial_features(current)
        rows, cols = current.shape
        n_features = features.shape[2]
        flat = features.reshape(-1, n_features)
        valid_indices = np.where(~np.isnan(flat).any(axis=1))[0]
        X = flat[valid_indices]

        model = IsolationForest(contamination=contamination, n_estimators=n_estimators, random_state=42)
        predictions = model.fit_predict(X)
        scores_flat = model.score_samples(X)

        anomaly_flat = np.zeros(rows * cols, dtype=bool)
        anomaly_flat[valid_indices] = predictions == -1
        scores_2d = np.full(rows * cols, np.nan)
        scores_2d[valid_indices] = scores_flat

        # only keep outliers on the LOW side (stress), not unusually green pixels
        anomaly_mask = anomaly_flat.reshape(rows, cols)
        with np.errstate(invalid="ignore"):
            anomaly_mask &= current < np.nanmedian(current)

        logger.info(f"Isolation Forest: contamination={contamination}, anomalous={int(anomaly_mask.sum())} pixels")
        return anomaly_mask, scores_2d.reshape(rows, cols)

    def _lof_detection(self, current: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Local Outlier Factor (LOF) detection based on local density deviation."""
        from sklearn.neighbors import LocalOutlierFactor

        features = self._extract_spatial_features(current)
        rows, cols = current.shape
        n_features = features.shape[2]
        flat = features.reshape(-1, n_features)
        valid_indices = np.where(~np.isnan(flat).any(axis=1))[0]
        X = flat[valid_indices]

        max_samples = 50000
        if len(X) > max_samples:
            rng = np.random.default_rng(42)
            sample_idx = rng.choice(len(X), max_samples, replace=False)
        else:
            sample_idx = np.arange(len(X))

        model = LocalOutlierFactor(n_neighbors=20, contamination=0.05)
        predictions = np.ones(len(X))
        predictions[sample_idx] = model.fit_predict(X[sample_idx])
        scores_flat = np.zeros(len(X))
        scores_flat[sample_idx] = model.negative_outlier_factor_

        anomaly_flat = np.zeros(rows * cols, dtype=bool)
        anomaly_flat[valid_indices] = predictions == -1
        scores_2d = np.full(rows * cols, np.nan)
        scores_2d[valid_indices] = scores_flat
        anomaly_mask = anomaly_flat.reshape(rows, cols)
        with np.errstate(invalid="ignore"):
            anomaly_mask &= current < np.nanmedian(current)
        return anomaly_mask, scores_2d.reshape(rows, cols)

    def _extract_spatial_features(self, data: np.ndarray, window_size: int = 5) -> np.ndarray:
        """
        Extract spatial context features for each pixel.

        Features: [value, local_mean, local_std, deviation_from_local_mean, gradient_mag]
        """
        filled = np.nan_to_num(data, nan=0.0)
        local_count = ndimage.uniform_filter((~np.isnan(data)).astype(float), size=window_size)
        with np.errstate(invalid="ignore", divide="ignore"):
            local_mean = ndimage.uniform_filter(filled, size=window_size) / local_count
            local_sq = ndimage.uniform_filter(filled ** 2, size=window_size) / local_count
        local_mean = np.where(local_count > 0, local_mean, np.nan)
        local_sq = np.where(local_count > 0, local_sq, np.nan)
        local_std = np.sqrt(np.maximum(local_sq - local_mean ** 2, 0))

        gy = ndimage.sobel(filled, axis=0)
        gx = ndimage.sobel(filled, axis=1)
        gradient = np.sqrt(gx ** 2 + gy ** 2)

        return np.stack([data, local_mean, local_std, data - local_mean, gradient], axis=-1)

    def _filter_small_clusters(
        self,
        anomaly_mask: np.ndarray,
        min_area_ha: float,
        profile: Optional[dict] = None,
    ) -> Tuple[np.ndarray, int]:
        """
        Remove anomaly clusters smaller than the minimum area (vectorised).

        Returns (filtered mask, number of clusters removed).
        """
        pixel_size_m = abs(profile["transform"][0]) if profile else 10.0
        pixel_area_ha = (pixel_size_m ** 2) / 10000.0
        min_pixels = max(int(np.ceil(min_area_ha / pixel_area_ha)), 1)

        labeled, n_clusters = ndimage.label(anomaly_mask)
        if n_clusters == 0:
            return np.zeros_like(anomaly_mask, dtype=bool), 0
        sizes = np.bincount(labeled.ravel(), minlength=n_clusters + 1)
        keep = sizes >= min_pixels
        keep[0] = False
        filtered = keep[labeled]
        removed = int(n_clusters - (keep.sum()))
        logger.info(f"Cluster filtering: {int(keep.sum())} kept, {removed} removed (< {min_area_ha} ha)")
        return filtered, removed

    def _compute_anomaly_statistics(
        self,
        anomaly_mask: np.ndarray,
        current: np.ndarray,
        scores: np.ndarray,
    ) -> Dict:
        """Compute summary statistics for detected anomalies."""
        valid = ~np.isnan(current)
        total_valid = int(valid.sum())
        n_anomalous = int(anomaly_mask.sum())

        labeled, n_clusters = ndimage.label(anomaly_mask)
        cluster_sizes = np.bincount(labeled.ravel())[1:] if n_clusters else np.array([])

        anomalous_values = current[anomaly_mask & valid]
        normal_values = current[~anomaly_mask & valid]
        stats = {
            "total_valid_pixels": total_valid,
            "anomalous_pixels": n_anomalous,
            "anomalous_percent": round(n_anomalous / total_valid * 100, 2) if total_valid > 0 else 0.0,
            "n_clusters": int(n_clusters),
            "mean_cluster_size_px": round(float(cluster_sizes.mean()), 1) if n_clusters else 0.0,
            "max_cluster_size_px": int(cluster_sizes.max()) if n_clusters else 0,
            "anomalous_mean_ndvi": round(float(anomalous_values.mean()), 4) if len(anomalous_values) else None,
            "normal_mean_ndvi": round(float(normal_values.mean()), 4) if len(normal_values) else None,
        }
        logger.info(
            f"Anomaly stats: {stats['anomalous_percent']}% anomalous, {n_clusters} clusters, "
            f"anomalous NDVI {stats['anomalous_mean_ndvi']}, normal NDVI {stats['normal_mean_ndvi']}"
        )
        return stats
