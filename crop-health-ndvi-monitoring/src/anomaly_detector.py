"""
Spatial Anomaly Detection for Crop Health

Detects areas of crop stress by identifying pixels that deviate
significantly from expected values (field average or phenology baseline).

Methods:
    - Z-score thresholding
    - Isolation Forest (unsupervised ML)
    - Local Outlier Factor (LOF)
"""

import numpy as np
import geopandas as gpd
from scipy import ndimage
import logging
from typing import Dict, Optional, Tuple, List
from pathlib import Path

from .utils import load_config, write_raster

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Detects spatial anomalies in vegetation index maps.

    Identifies areas where crop health deviates significantly from
    expected patterns, indicating potential stress, disease, or damage.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.anomaly_cfg = self.config["anomaly"]

    def detect(
        self,
        current: np.ndarray,
        baseline: Optional[np.ndarray] = None,
        method: Optional[str] = None,
        profile: Optional[dict] = None,
        output_path: Optional[str] = None,
    ) -> Tuple[np.ndarray, Dict]:
        """
        Detect anomalous (stressed) areas in a vegetation index map.

        Args:
            current: current observation array (e.g., NDVI)
            baseline: expected baseline array (from phenology or historical)
            method: detection method (z_score, isolation_forest, lof)
            profile: rasterio profile for output
            output_path: optional path to save anomaly map

        Returns:
            tuple: (anomaly binary mask, statistics dict)
        """
        method = method or self.anomaly_cfg["method"]
        logger.info(f"Detecting anomalies using method: {method}")

        if method == "z_score":
            anomaly_map, scores = self._z_score_detection(current, baseline)
        elif method == "isolation_forest":
            anomaly_map, scores = self._isolation_forest_detection(current)
        elif method == "lof":
            anomaly_map, scores = self._lof_detection(current)
        else:
            raise ValueError(f"Unknown anomaly detection method: {method}")

        # Filter small clusters
        min_area_ha = self.anomaly_cfg.get("min_cluster_ha", 0.5)
        anomaly_map = self._filter_small_clusters(anomaly_map, min_area_ha, profile)

        stats = self._compute_anomaly_statistics(anomaly_map, current, scores)

        if output_path and profile:
            write_raster(anomaly_map.astype(np.float64), profile, output_path)
            logger.info(f"Anomaly map saved to: {output_path}")

        return anomaly_map, stats

    def _z_score_detection(
        self,
        current: np.ndarray,
        baseline: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Z-score based anomaly detection.

        Computes per-pixel z-scores relative to:
        - The baseline (phenology-expected) if provided
        - The field-level mean and std if no baseline

        Pixels with z-score below threshold are flagged as anomalous.
        """
        threshold = self.anomaly_cfg.get("z_score_threshold", -1.5)

        if baseline is not None:
            # Deviation from expected phenology
            residuals = current - baseline
            mean_residual = np.nanmean(residuals)
            std_residual = np.nanstd(residuals)
        else:
            # Deviation from field-level mean
            residuals = current.copy()
            mean_residual = np.nanmean(current)
            std_residual = np.nanstd(current)

        if std_residual == 0:
            std_residual = 1e-10

        z_scores = (residuals - mean_residual) / std_residual

        # Negative z-scores indicate below-average health
        anomaly_mask = z_scores < threshold

        # Mask NaN areas
        anomaly_mask = np.where(np.isnan(current), False, anomaly_mask)

        logger.info(
            f"Z-score detection: threshold={threshold}, "
            f"anomalous={np.sum(anomaly_mask)}/{np.sum(~np.isnan(current))} pixels "
            f"({np.sum(anomaly_mask)/np.sum(~np.isnan(current))*100:.1f}%)"
        )

        return anomaly_mask, z_scores

    def _isolation_forest_detection(
        self, current: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Isolation Forest anomaly detection.

        Uses spatial context (local window statistics) as features
        for unsupervised outlier detection.
        """
        from sklearn.ensemble import IsolationForest

        iso_cfg = self.anomaly_cfg.get("isolation_forest", {})
        contamination = iso_cfg.get("contamination", 0.05)
        n_estimators = iso_cfg.get("n_estimators", 100)

        # Build feature matrix from spatial context
        features = self._extract_spatial_features(current)

        # Flatten and filter valid pixels
        valid_mask = ~np.isnan(features[:, :, 0])
        rows, cols = current.shape
        valid_indices = np.where(valid_mask.flatten())[0]

        n_features = features.shape[2]
        X = features.reshape(-1, n_features)[valid_indices]

        # Fit Isolation Forest
        model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            random_state=42,
        )
        predictions = model.fit_predict(X)
        scores_flat = model.score_samples(X)

        # Map back to 2D
        anomaly_flat = np.zeros(rows * cols, dtype=bool)
        anomaly_flat[valid_indices] = predictions == -1

        scores_2d = np.full(rows * cols, np.nan)
        scores_2d[valid_indices] = scores_flat

        anomaly_mask = anomaly_flat.reshape(rows, cols)
        scores = scores_2d.reshape(rows, cols)

        logger.info(
            f"Isolation Forest: contamination={contamination}, "
            f"anomalous={np.sum(anomaly_mask)} pixels"
        )

        return anomaly_mask, scores

    def _lof_detection(
        self, current: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Local Outlier Factor (LOF) detection.

        Detects anomalies based on local density deviation.
        """
        from sklearn.neighbors import LocalOutlierFactor

        features = self._extract_spatial_features(current)
        valid_mask = ~np.isnan(features[:, :, 0])
        rows, cols = current.shape
        valid_indices = np.where(valid_mask.flatten())[0]

        n_features = features.shape[2]
        X = features.reshape(-1, n_features)[valid_indices]

        # Subsample for large datasets
        max_samples = 50000
        if len(X) > max_samples:
            rng = np.random.default_rng(42)
            sample_idx = rng.choice(len(X), max_samples, replace=False)
        else:
            sample_idx = np.arange(len(X))

        model = LocalOutlierFactor(n_neighbors=20, contamination=0.05)
        predictions = np.ones(len(X))
        predictions[sample_idx] = model.fit_predict(X[sample_idx])

        scores_flat = np.full(len(X), 0.0)
        scores_flat[sample_idx] = model.negative_outlier_factor_

        anomaly_flat = np.zeros(rows * cols, dtype=bool)
        anomaly_flat[valid_indices] = predictions == -1

        scores_2d = np.full(rows * cols, np.nan)
        scores_2d[valid_indices] = scores_flat

        return anomaly_flat.reshape(rows, cols), scores_2d.reshape(rows, cols)

    def _extract_spatial_features(
        self, data: np.ndarray, window_size: int = 5
    ) -> np.ndarray:
        """
        Extract spatial context features for each pixel.

        Features: [value, local_mean, local_std, local_median, gradient_mag]
        """
        pad = window_size // 2

        # Local statistics using uniform filter
        local_mean = ndimage.uniform_filter(
            np.nan_to_num(data, nan=0), size=window_size
        )
        local_count = ndimage.uniform_filter(
            (~np.isnan(data)).astype(float), size=window_size
        )
        local_mean = np.where(local_count > 0, local_mean / np.maximum(local_count, 1e-10), np.nan)

        # Local standard deviation
        local_sq_mean = ndimage.uniform_filter(
            np.nan_to_num(data ** 2, nan=0), size=window_size
        )
        local_sq_mean = np.where(local_count > 0, local_sq_mean / np.maximum(local_count, 1e-10), np.nan)
        local_std = np.sqrt(np.maximum(local_sq_mean - local_mean ** 2, 0))

        # Gradient magnitude (Sobel)
        gy = ndimage.sobel(np.nan_to_num(data, nan=0), axis=0)
        gx = ndimage.sobel(np.nan_to_num(data, nan=0), axis=1)
        gradient = np.sqrt(gx ** 2 + gy ** 2)

        features = np.stack([
            data,
            local_mean,
            local_std,
            data - local_mean,  # deviation from local mean
            gradient,
        ], axis=-1)

        return features

    def _filter_small_clusters(
        self,
        anomaly_mask: np.ndarray,
        min_area_ha: float,
        profile: Optional[dict] = None,
    ) -> np.ndarray:
        """
        Remove anomaly clusters smaller than minimum area threshold.

        Args:
            anomaly_mask: binary anomaly mask
            min_area_ha: minimum cluster size in hectares
            profile: rasterio profile for pixel size

        Returns:
            Filtered anomaly mask
        """
        if profile:
            pixel_size_m = abs(profile["transform"][0])
        else:
            pixel_size_m = 10  # Default Sentinel-2 resolution

        pixel_area_ha = (pixel_size_m ** 2) / 10000
        min_pixels = int(min_area_ha / pixel_area_ha)

        # Label connected components
        labeled, n_clusters = ndimage.label(anomaly_mask)

        filtered = np.zeros_like(anomaly_mask)
        clusters_kept = 0

        for i in range(1, n_clusters + 1):
            cluster_size = np.sum(labeled == i)
            if cluster_size >= min_pixels:
                filtered[labeled == i] = True
                clusters_kept += 1

        removed = n_clusters - clusters_kept
        logger.info(
            f"Cluster filtering: {clusters_kept} kept, "
            f"{removed} removed (< {min_area_ha} ha)"
        )

        return filtered

    def _compute_anomaly_statistics(
        self,
        anomaly_mask: np.ndarray,
        current: np.ndarray,
        scores: np.ndarray,
    ) -> Dict:
        """Compute summary statistics for detected anomalies."""
        total_valid = int(np.sum(~np.isnan(current)))
        n_anomalous = int(np.sum(anomaly_mask))

        # Label clusters for per-cluster stats
        labeled, n_clusters = ndimage.label(anomaly_mask)

        cluster_sizes = []
        for i in range(1, n_clusters + 1):
            cluster_sizes.append(int(np.sum(labeled == i)))

        anomalous_values = current[anomaly_mask & ~np.isnan(current)]

        stats = {
            "total_valid_pixels": total_valid,
            "anomalous_pixels": n_anomalous,
            "anomalous_percent": round(n_anomalous / total_valid * 100, 2) if total_valid > 0 else 0,
            "n_clusters": n_clusters,
            "mean_cluster_size_px": round(np.mean(cluster_sizes), 1) if cluster_sizes else 0,
            "max_cluster_size_px": max(cluster_sizes) if cluster_sizes else 0,
            "anomalous_mean_ndvi": round(float(np.nanmean(anomalous_values)), 4) if len(anomalous_values) > 0 else None,
            "normal_mean_ndvi": round(
                float(np.nanmean(current[~anomaly_mask & ~np.isnan(current)])), 4
            ),
        }

        logger.info(
            f"Anomaly stats — {stats['anomalous_percent']}% anomalous, "
            f"{n_clusters} clusters, "
            f"anomalous NDVI: {stats['anomalous_mean_ndvi']}, "
            f"normal NDVI: {stats['normal_mean_ndvi']}"
        )

        return stats
