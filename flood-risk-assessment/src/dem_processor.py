"""
DEM Hydrological Processor

Performs hydrological preprocessing of Digital Elevation Models:
- Sink filling
- Flow direction & accumulation
- Topographic Wetness Index (TWI)
- Stream network extraction
- Watershed delineation
- Slope & aspect computation
"""

import numpy as np
import rasterio
import logging
from pathlib import Path
from typing import Optional, Tuple

from .utils import load_config, read_raster, write_raster, ensure_directory

logger = logging.getLogger(__name__)


class DEMProcessor:
    """
    Hydrological DEM processing pipeline.

    Provides methods for terrain analysis and hydrological feature
    extraction using numpy-based algorithms and optional WhiteboxTools.
    """

    # D8 flow direction encoding (ArcGIS convention)
    D8_DIRECTIONS = {
        1: (0, 1),    # East
        2: (1, 1),    # Southeast
        4: (1, 0),    # South
        8: (1, -1),   # Southwest
        16: (0, -1),  # West
        32: (-1, -1), # Northwest
        64: (-1, 0),  # North
        128: (-1, 1), # Northeast
    }

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.dem_cfg = self.config["dem"]
        self.dem_path = self.dem_cfg["source"]
        self.resolution = self.dem_cfg["resolution"]

        self._dem = None
        self._profile = None

    @property
    def dem(self) -> np.ndarray:
        """Lazy-load DEM data."""
        if self._dem is None:
            self._dem, self._profile = read_raster(self.dem_path)
            logger.info(
                f"DEM loaded: {self._dem.shape}, "
                f"range [{np.nanmin(self._dem):.1f}, {np.nanmax(self._dem):.1f}] m"
            )
        return self._dem

    @property
    def profile(self) -> dict:
        """Get rasterio profile for the DEM."""
        if self._profile is None:
            _ = self.dem  # trigger load
        return self._profile

    def fill_sinks(self, output_path: Optional[str] = None) -> np.ndarray:
        """
        Fill sinks (depressions) in the DEM to ensure continuous flow.

        Uses the Planchon-Darboux algorithm (priority flood fill).

        Args:
            output_path: optional path to save filled DEM

        Returns:
            Filled DEM array
        """
        logger.info("Filling DEM sinks using priority flood algorithm")

        dem = self.dem.copy()
        rows, cols = dem.shape

        # Priority flood fill (simplified Planchon-Darboux)
        filled = np.full_like(dem, np.inf)

        # Initialize edges with original elevation
        filled[0, :] = dem[0, :]
        filled[-1, :] = dem[-1, :]
        filled[:, 0] = dem[:, 0]
        filled[:, -1] = dem[:, -1]

        # Iteratively raise interior cells
        epsilon = 1e-5
        changed = True
        max_iterations = 1000
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for r in range(1, rows - 1):
                for c in range(1, cols - 1):
                    if np.isnan(dem[r, c]):
                        continue

                    if filled[r, c] > dem[r, c]:
                        # Check 8-connected neighbors
                        for dr in [-1, 0, 1]:
                            for dc in [-1, 0, 1]:
                                if dr == 0 and dc == 0:
                                    continue
                                nr, nc = r + dr, c + dc
                                neighbor_val = filled[nr, nc]

                                if dem[r, c] >= neighbor_val + epsilon:
                                    filled[r, c] = dem[r, c]
                                    changed = True
                                elif filled[r, c] > neighbor_val + epsilon:
                                    filled[r, c] = neighbor_val + epsilon
                                    changed = True

        n_filled = int(np.sum(filled != dem))
        logger.info(f"Sinks filled: {n_filled} cells modified in {iteration} iterations")

        self._dem = filled

        if output_path:
            write_raster(filled, self.profile, output_path)

        return filled

    def fill_sinks_whitebox(self, output_path: Optional[str] = None) -> np.ndarray:
        """
        Fill sinks using WhiteboxTools (faster for large DEMs).

        Requires: pip install whitebox
        """
        try:
            import whitebox
        except ImportError:
            logger.warning("WhiteboxTools not available, falling back to numpy")
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

    def compute_slope(self, output_path: Optional[str] = None) -> np.ndarray:
        """
        Compute slope in degrees using Horn's method (3×3 window).

        Args:
            output_path: optional output path

        Returns:
            Slope array in degrees
        """
        logger.info("Computing slope (Horn's method)")

        dem = self.dem
        res = self.resolution

        # Pad DEM for edge handling
        padded = np.pad(dem, 1, mode="edge")

        # Horn's method partial derivatives
        dz_dx = (
            (padded[:-2, 2:] + 2 * padded[1:-1, 2:] + padded[2:, 2:])
            - (padded[:-2, :-2] + 2 * padded[1:-1, :-2] + padded[2:, :-2])
        ) / (8 * res)

        dz_dy = (
            (padded[:-2, :-2] + 2 * padded[:-2, 1:-1] + padded[:-2, 2:])
            - (padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:])
        ) / (8 * res)

        slope_rad = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
        slope_deg = np.degrees(slope_rad)

        logger.info(
            f"Slope statistics — Mean: {np.nanmean(slope_deg):.1f}°, "
            f"Max: {np.nanmax(slope_deg):.1f}°"
        )

        if output_path:
            write_raster(slope_deg, self.profile, output_path)

        return slope_deg

    def compute_flow_direction(
        self, output_path: Optional[str] = None
    ) -> np.ndarray:
        """
        Compute D8 flow direction from filled DEM.

        Each cell is assigned the direction of its steepest downslope
        neighbor using the D8 encoding.

        Returns:
            Flow direction array (D8 encoded)
        """
        logger.info("Computing D8 flow direction")

        dem = self.dem
        rows, cols = dem.shape
        flow_dir = np.zeros((rows, cols), dtype=np.int16)

        directions = [
            (64, -1, 0),   (128, -1, 1),  (1, 0, 1),    (2, 1, 1),
            (4, 1, 0),     (8, 1, -1),    (16, 0, -1),   (32, -1, -1),
        ]
        distances = [
            self.resolution, self.resolution * np.sqrt(2),
            self.resolution, self.resolution * np.sqrt(2),
            self.resolution, self.resolution * np.sqrt(2),
            self.resolution, self.resolution * np.sqrt(2),
        ]

        for r in range(1, rows - 1):
            for c in range(1, cols - 1):
                if np.isnan(dem[r, c]):
                    continue

                max_drop = -np.inf
                best_dir = 0

                for (code, dr, dc), dist in zip(directions, distances):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and not np.isnan(dem[nr, nc]):
                        drop = (dem[r, c] - dem[nr, nc]) / dist
                        if drop > max_drop:
                            max_drop = drop
                            best_dir = code

                flow_dir[r, c] = best_dir

        if output_path:
            write_raster(flow_dir.astype(np.float64), self.profile, output_path)

        return flow_dir

    def compute_flow_accumulation(
        self, flow_dir: np.ndarray, output_path: Optional[str] = None
    ) -> np.ndarray:
        """
        Compute flow accumulation from D8 flow direction.

        Each cell value represents the number of upstream cells
        that drain through it.

        Args:
            flow_dir: D8 flow direction array

        Returns:
            Flow accumulation array (cell counts)
        """
        logger.info("Computing flow accumulation")

        rows, cols = flow_dir.shape
        accumulation = np.ones((rows, cols), dtype=np.float64)

        # Build receiver graph
        directions = {
            1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
            16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1),
        }

        # Count incoming flows for topological sort
        in_degree = np.zeros((rows, cols), dtype=np.int32)
        for r in range(rows):
            for c in range(cols):
                d = flow_dir[r, c]
                if d in directions:
                    dr, dc = directions[d]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        in_degree[nr, nc] += 1

        # Topological sort (BFS from sources)
        from collections import deque

        queue = deque()
        for r in range(rows):
            for c in range(cols):
                if in_degree[r, c] == 0:
                    queue.append((r, c))

        while queue:
            r, c = queue.popleft()
            d = flow_dir[r, c]
            if d in directions:
                dr, dc = directions[d]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    accumulation[nr, nc] += accumulation[r, c]
                    in_degree[nr, nc] -= 1
                    if in_degree[nr, nc] == 0:
                        queue.append((nr, nc))

        logger.info(f"Max flow accumulation: {np.max(accumulation):.0f} cells")

        if output_path:
            write_raster(accumulation, self.profile, output_path)

        return accumulation

    def compute_twi(
        self,
        flow_acc: np.ndarray,
        slope: Optional[np.ndarray] = None,
        output_path: Optional[str] = None,
    ) -> np.ndarray:
        """
        Compute Topographic Wetness Index.

        TWI = ln(α / tan(β))

        where α = specific catchment area and β = slope in radians.

        Args:
            flow_acc: flow accumulation array (cell counts)
            slope: slope array in degrees (computed if None)
            output_path: optional output path

        Returns:
            TWI array
        """
        logger.info("Computing Topographic Wetness Index (TWI)")

        if slope is None:
            slope = self.compute_slope()

        # Specific catchment area (m² per unit contour length)
        alpha = flow_acc * (self.resolution ** 2) / self.resolution

        # Convert slope to radians, with minimum to avoid division by zero
        slope_rad = np.radians(np.maximum(slope, 0.01))

        twi = np.log(alpha / np.tan(slope_rad))

        # Clip extreme values
        twi = np.clip(twi, 0, 30)

        logger.info(f"TWI range: [{np.nanmin(twi):.1f}, {np.nanmax(twi):.1f}]")

        if output_path:
            write_raster(twi, self.profile, output_path)

        return twi

    def extract_stream_network(
        self,
        flow_acc: np.ndarray,
        threshold: int = 1000,
        output_path: Optional[str] = None,
    ) -> np.ndarray:
        """
        Extract stream network from flow accumulation.

        Args:
            flow_acc: flow accumulation array
            threshold: minimum accumulation to define a stream cell
            output_path: optional output for stream raster

        Returns:
            Binary stream network array (1 = stream, 0 = non-stream)
        """
        logger.info(f"Extracting stream network (threshold: {threshold} cells)")

        streams = np.where(flow_acc >= threshold, 1, 0).astype(np.float64)

        stream_cells = int(np.sum(streams))
        total_cells = streams.size
        stream_density = stream_cells / total_cells * 100

        logger.info(
            f"Stream network: {stream_cells} cells "
            f"({stream_density:.2f}% of study area)"
        )

        if output_path:
            write_raster(streams, self.profile, output_path)

        return streams

    def compute_distance_to_streams(
        self,
        streams: np.ndarray,
        output_path: Optional[str] = None,
    ) -> np.ndarray:
        """
        Compute Euclidean distance from each cell to nearest stream.

        Args:
            streams: binary stream network array
            output_path: optional output path

        Returns:
            Distance array in meters
        """
        from scipy.ndimage import distance_transform_edt

        logger.info("Computing distance to stream network")

        # distance_transform_edt works on False values (non-stream)
        distance_cells = distance_transform_edt(streams == 0)
        distance_m = distance_cells * self.resolution

        logger.info(f"Max distance to stream: {np.max(distance_m):.0f} m")

        if output_path:
            write_raster(distance_m, self.profile, output_path)

        return distance_m
