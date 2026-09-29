"""
DEM Hydrological Processor

Performs hydrological preprocessing of Digital Elevation Models:
- Sink filling (priority-flood, Barnes et al. 2014)
- D8 flow direction and flow accumulation
- Slope (Horn's method)
- Topographic Wetness Index (TWI)
- Stream network extraction (raster and vector)
- Euclidean distance to streams
"""

import heapq
import logging
from collections import deque
from pathlib import Path
from typing import Optional, Union

import numpy as np
from scipy.ndimage import distance_transform_edt

from .utils import ensure_directory, load_config, read_raster, write_raster

logger = logging.getLogger(__name__)

# D8 encoding (ESRI convention): code -> (row offset, col offset)
D8_CODES = np.array([1, 2, 4, 8, 16, 32, 64, 128], dtype=np.int16)
D8_OFFSETS = np.array(
    [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)],
    dtype=np.int64,
)
D8_DIRECTIONS = {int(c): (int(dr), int(dc)) for c, (dr, dc) in zip(D8_CODES, D8_OFFSETS)}


class DEMProcessor:
    """
    Hydrological DEM processing pipeline built on numpy/scipy.

    The DEM comes either from ``config["dem"]["source"]`` or from an explicit
    ``dem_path`` / ``dem_array`` override (used by the demo and the tests).
    """

    D8_DIRECTIONS = D8_DIRECTIONS

    def __init__(
        self,
        config: Union[str, Path, dict] = "config.yaml",
        dem_path: Optional[Union[str, Path]] = None,
        dem_array: Optional[np.ndarray] = None,
        profile: Optional[dict] = None,
        resolution: Optional[float] = None,
    ):
        self.config = load_config(config)
        self.dem_cfg = self.config.get("dem", {})
        self.dem_path = str(dem_path) if dem_path is not None else self.dem_cfg.get("source")
        self.resolution = float(resolution or self.dem_cfg.get("resolution", 30))

        self._dem = None
        self._profile = None
        if dem_array is not None:
            self._dem = np.asarray(dem_array, dtype=np.float64)
            self._profile = profile

    @property
    def dem(self) -> np.ndarray:
        """Lazy-load DEM data."""
        if self._dem is None:
            self._dem, self._profile = read_raster(self.dem_path)
            logger.info(
                f"DEM loaded: {self._dem.shape}, range "
                f"[{np.nanmin(self._dem):.1f}, {np.nanmax(self._dem):.1f}] m"
            )
        return self._dem

    @property
    def profile(self) -> dict:
        """Rasterio profile for the DEM (may be None for a bare array)."""
        if self._profile is None and self._dem is None:
            _ = self.dem
        return self._profile

    # ------------------------------------------------------------------ sinks
    @staticmethod
    def priority_flood(dem: np.ndarray, epsilon: float = 1e-5) -> np.ndarray:
        """
        Fill depressions with the priority-flood algorithm (Barnes et al. 2014).

        All edge cells (and cells next to NaN nodata) are pushed on a
        min-heap. Cells are popped lowest first; every unvisited neighbour
        is raised to at least ``popped + epsilon`` before being pushed. The
        epsilon gradient guarantees that every filled cell keeps a strictly
        lower neighbour, so D8 routing has no flats and no loops.

        Args:
            dem: 2-D elevation array (NaN = nodata, never modified)
            epsilon: minimum drop imposed across filled cells (metres)

        Returns:
            Filled elevation array (same shape, NaN preserved)
        """
        dem = np.asarray(dem, dtype=np.float64)
        rows, cols = dem.shape
        filled = dem.copy()
        valid = ~np.isnan(dem)
        closed = ~valid  # nodata cells are never processed

        # Seed: valid cells on the grid edge or touching a nodata cell
        edge = np.zeros_like(valid)
        edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
        if not valid.all():
            padded = np.pad(valid, 1, constant_values=False)
            touches_nodata = np.zeros_like(valid)
            for dr, dc in D8_OFFSETS:
                touches_nodata |= ~padded[1 + dr: 1 + dr + rows, 1 + dc: 1 + dc + cols]
            edge |= touches_nodata
        seeds = np.argwhere(edge & valid)

        heap = [(float(filled[r, c]), int(r), int(c)) for r, c in seeds]
        heapq.heapify(heap)
        closed[edge & valid] = True

        offsets = [(int(dr), int(dc)) for dr, dc in D8_OFFSETS]
        push, pop = heapq.heappush, heapq.heappop
        while heap:
            z, r, c = pop(heap)
            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols or closed[nr, nc]:
                    continue
                closed[nr, nc] = True
                nz = filled[nr, nc]
                if nz < z + epsilon:
                    nz = z + epsilon
                    filled[nr, nc] = nz
                push(heap, (float(nz), nr, nc))
        return filled

    def fill_sinks(
        self, output_path: Optional[str] = None, epsilon: float = 1e-5
    ) -> np.ndarray:
        """
        Fill sinks in the DEM (priority-flood) and store the result as the
        working DEM used by the other methods.

        Returns:
            Filled DEM array
        """
        logger.info("Filling DEM sinks (priority-flood)")
        original = self.dem
        filled = self.priority_flood(original, epsilon=epsilon)
        n_filled = int(np.sum((filled - original) > epsilon / 2))
        logger.info(f"Sinks filled: {n_filled} cells raised")
        self._dem = filled
        if output_path:
            write_raster(filled, self.profile, output_path)
        return filled

    def fill_sinks_whitebox(self, output_path: Optional[str] = None) -> np.ndarray:
        """
        Optional path: fill sinks with WhiteboxTools (``pip install whitebox``).
        Falls back to the numpy priority-flood when the package is missing.
        """
        try:
            import whitebox  # noqa: F401  (optional dependency)
        except ImportError:
            logger.warning("WhiteboxTools not available, using priority-flood")
            return self.fill_sinks(output_path)

        wbt = whitebox.WhiteboxTools()
        wbt.verbose = False
        temp_dir = ensure_directory("temp")
        input_path = str(temp_dir / "dem_input.tif")
        filled_path = str(temp_dir / "dem_filled.tif")
        write_raster(self.dem, self.profile, input_path)
        wbt.fill_depressions(input_path, filled_path)
        filled, _ = read_raster(filled_path)
        self._dem = filled
        if output_path:
            write_raster(filled, self.profile, output_path)
        return filled

    # ------------------------------------------------------------------ slope
    def compute_slope(self, output_path: Optional[str] = None) -> np.ndarray:
        """Slope in degrees using Horn's 3x3 method."""
        logger.info("Computing slope (Horn's method)")
        dem = self.dem
        res = self.resolution
        padded = np.pad(dem, 1, mode="edge")

        dz_dx = (
            (padded[:-2, 2:] + 2 * padded[1:-1, 2:] + padded[2:, 2:])
            - (padded[:-2, :-2] + 2 * padded[1:-1, :-2] + padded[2:, :-2])
        ) / (8 * res)
        dz_dy = (
            (padded[:-2, :-2] + 2 * padded[:-2, 1:-1] + padded[:-2, 2:])
            - (padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:])
        ) / (8 * res)

        slope_deg = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2)))
        logger.info(
            f"Slope: mean {np.nanmean(slope_deg):.2f} deg, max {np.nanmax(slope_deg):.2f} deg"
        )
        if output_path:
            write_raster(slope_deg, self.profile, output_path)
        return slope_deg

    # ------------------------------------------------------------- flow dir
    def compute_flow_direction(self, output_path: Optional[str] = None) -> np.ndarray:
        """
        D8 flow direction (vectorised).

        The eight neighbour drops (elevation difference / distance) are
        stacked and the steepest positive drop wins. Cells with no lower
        neighbour (outlets, pits, edge cells) get code 0.

        Returns:
            int16 array of D8 codes (1, 2, 4, ... 128; 0 = no flow)
        """
        logger.info("Computing D8 flow direction")
        dem = self.dem
        rows, cols = dem.shape
        padded = np.pad(dem, 1, constant_values=np.nan)
        res = self.resolution

        drops = np.empty((8, rows, cols), dtype=np.float64)
        for k, (dr, dc) in enumerate(D8_OFFSETS):
            neighbour = padded[1 + dr: 1 + dr + rows, 1 + dc: 1 + dc + cols]
            dist = res * (np.sqrt(2.0) if dr != 0 and dc != 0 else 1.0)
            drops[k] = (dem - neighbour) / dist
        drops[np.isnan(drops)] = -np.inf

        best = np.argmax(drops, axis=0)
        max_drop = np.take_along_axis(drops, best[None], axis=0)[0]
        flow_dir = D8_CODES[best]
        flow_dir[(max_drop <= 0) | np.isnan(dem)] = 0
        flow_dir = flow_dir.astype(np.int16)

        if output_path:
            write_raster(flow_dir.astype(np.float64), self.profile, output_path)
        return flow_dir

    # ------------------------------------------------------------- flow acc
    def compute_flow_accumulation(
        self, flow_dir: np.ndarray, output_path: Optional[str] = None
    ) -> np.ndarray:
        """
        Flow accumulation (number of upstream cells, self included) from D8
        codes. In-degree is computed with numpy; the accumulation itself is a
        topological (Kahn) traversal from source cells.

        Returns:
            float64 array of contributing cell counts
        """
        logger.info("Computing flow accumulation")
        rows, cols = flow_dir.shape
        accumulation = np.ones((rows, cols), dtype=np.float64)

        # Receiver index per cell (-1 = none)
        receiver = np.full((rows, cols), -1, dtype=np.int64)
        in_degree = np.zeros((rows, cols), dtype=np.int32)
        rr, cc = np.indices((rows, cols))
        for code, (dr, dc) in zip(D8_CODES, D8_OFFSETS):
            mask = flow_dir == code
            nr, nc = rr[mask] + dr, cc[mask] + dc
            inside = (nr >= 0) & (nr < rows) & (nc >= 0) & (nc < cols)
            src_flat = (rr[mask] * cols + cc[mask])[inside]
            dst_flat = nr[inside] * cols + nc[inside]
            receiver.flat[src_flat] = dst_flat
            np.add.at(in_degree, (nr[inside], nc[inside]), 1)

        receiver = receiver.ravel()
        in_deg = in_degree.ravel()
        acc = accumulation.ravel()
        queue = deque(np.flatnonzero(in_deg == 0).tolist())
        while queue:
            i = queue.popleft()
            j = receiver[i]
            if j >= 0:
                acc[j] += acc[i]
                in_deg[j] -= 1
                if in_deg[j] == 0:
                    queue.append(j)

        accumulation = acc.reshape(rows, cols)
        accumulation[np.isnan(self.dem)] = np.nan
        logger.info(f"Max flow accumulation: {np.nanmax(accumulation):.0f} cells")
        if output_path:
            write_raster(accumulation, self.profile, output_path)
        return accumulation

    # ------------------------------------------------------------------ TWI
    def compute_twi(
        self,
        flow_acc: np.ndarray,
        slope: Optional[np.ndarray] = None,
        output_path: Optional[str] = None,
    ) -> np.ndarray:
        """
        Topographic Wetness Index: TWI = ln(a / tan(b)), with a the specific
        catchment area (m2 per metre of contour) and b the slope.
        """
        logger.info("Computing Topographic Wetness Index (TWI)")
        if slope is None:
            slope = self.compute_slope()
        alpha = flow_acc * self.resolution  # cells * res^2 / res
        slope_rad = np.radians(np.maximum(slope, 0.01))
        twi = np.log(alpha / np.tan(slope_rad))
        twi = np.clip(twi, 0, 30)
        logger.info(f"TWI range: [{np.nanmin(twi):.1f}, {np.nanmax(twi):.1f}]")
        if output_path:
            write_raster(twi, self.profile, output_path)
        return twi

    # -------------------------------------------------------------- streams
    def extract_stream_network(
        self, flow_acc: np.ndarray, threshold: int = 1000, output_path: Optional[str] = None
    ) -> np.ndarray:
        """Binary stream raster: 1 where accumulation >= threshold cells."""
        logger.info(f"Extracting stream network (threshold: {threshold} cells)")
        streams = np.where(flow_acc >= threshold, 1.0, 0.0)
        streams[np.isnan(flow_acc)] = 0.0
        stream_cells = int(np.sum(streams))
        logger.info(
            f"Stream network: {stream_cells} cells "
            f"({stream_cells / streams.size * 100:.2f}% of study area)"
        )
        if output_path:
            write_raster(streams, self.profile, output_path)
        return streams

    def streams_to_vector(self, streams: np.ndarray, flow_dir: np.ndarray, flow_acc=None):
        """
        Convert the stream raster to line geometry: one segment from each
        stream cell centre to its downstream cell centre, merged into lines.

        Returns:
            GeoDataFrame (CRS of the DEM) with 'upstream_km2' per line
        """
        import geopandas as gpd
        from shapely.geometry import LineString
        from shapely.ops import linemerge

        profile = self.profile
        t = profile["transform"]
        rows, cols = streams.shape
        rr, cc = np.nonzero((streams > 0) & (flow_dir > 0))
        if len(rr) == 0:
            return gpd.GeoDataFrame({"upstream_km2": [], "length_m": []}, geometry=[], crs=profile["crs"])

        codes = flow_dir[rr, cc].astype(np.int64)
        k = np.log2(codes).astype(int)  # code 2**k -> offset index k
        nr, nc = rr + D8_OFFSETS[k, 0], cc + D8_OFFSETS[k, 1]
        inside = (nr >= 0) & (nr < rows) & (nc >= 0) & (nc < cols)
        rr, cc, nr, nc = rr[inside], cc[inside], nr[inside], nc[inside]

        def to_xy(r, c):
            return t.c + t.a * (c + 0.5) + t.b * (r + 0.5), t.f + t.d * (c + 0.5) + t.e * (r + 0.5)

        x0, y0 = to_xy(rr, cc)
        x1, y1 = to_xy(nr, nc)
        segments = [LineString([(a, b), (c_, d)]) for a, b, c_, d in zip(x0, y0, x1, y1)]
        ups = flow_acc[rr, cc].astype(float) if flow_acc is not None else np.full(len(rr), np.nan)

        if not segments:
            return gpd.GeoDataFrame({"upstream_km2": [], "length_m": []}, geometry=[], crs=profile["crs"])

        merged = linemerge(segments)
        lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        pixel_km2 = (self.resolution ** 2) / 1e6
        # Upstream area for a merged line = max accumulation of the segments
        # whose midpoint lies on it (midpoints avoid junction double counting)
        midpoints = [seg.interpolate(0.5, normalized=True) for seg in segments]
        seg_gdf = gpd.GeoDataFrame({"acc": ups}, geometry=midpoints, crs=profile["crs"])
        out = gpd.GeoDataFrame(geometry=lines, crs=profile["crs"])
        joined = gpd.sjoin_nearest(seg_gdf, out, how="inner", max_distance=self.resolution)
        out["upstream_km2"] = (
            joined.groupby("index_right")["acc"].max().reindex(out.index) * pixel_km2
        )
        out["upstream_km2"] = out["upstream_km2"].fillna(0.0).round(3)
        out["length_m"] = out.geometry.length.round(1)
        return out

    def compute_distance_to_streams(
        self, streams: np.ndarray, output_path: Optional[str] = None
    ) -> np.ndarray:
        """Euclidean distance (metres) from every cell to the nearest stream cell."""
        logger.info("Computing distance to stream network")
        if not np.any(streams > 0):
            distance_m = np.full(streams.shape, np.nan)
        else:
            distance_m = distance_transform_edt(streams == 0) * self.resolution
        logger.info(f"Max distance to stream: {np.nanmax(distance_m):.0f} m")
        if output_path:
            write_raster(distance_m, self.profile, output_path)
        return distance_m
