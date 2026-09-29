"""
Road-network construction.

Two entry points:

* ``build_synthetic_network``: a deterministic, plausible synthetic city street
  grid (residential grid, secondary roads every 5th row/column, two diagonal
  primary arterials, a motorway ring segment, a meandering north-south river
  crossed by exactly three bridges, and random gaps in the residential grid).
* ``load_osm_network``: wraps OSMnx to download and project a real drivable
  network. Needs internet; it is not used by the offline demo.

Edge attributes on every graph: ``length_m``, ``highway``, ``speed_kph``,
``travel_time_s`` (and ``bridge`` for the synthetic graph). Node attributes:
``x``, ``y`` in the projected CRS stored in ``G.graph["crs"]``.
"""

import math

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, Point

# Free-flow speed per road class (km/h).
SPEED_KPH = {"residential": 30, "secondary": 50, "primary": 65, "motorway": 100}
# Average delay at the downstream junction (stop signs, signals) in seconds.
# With 250 m blocks this gives effective speeds of about 16 km/h on
# residential streets, 25 km/h on secondary roads, 40 km/h on arterials and
# free flow on the motorway, which matches typical peak-hour urban driving.
JUNCTION_DELAY_S = {"residential": 25, "secondary": 18, "primary": 12, "motorway": 0}
CLASS_RANK = {"residential": 0, "secondary": 1, "primary": 2, "motorway": 3}

DEFAULT_CRS = "EPSG:32611"
# South-west corner of the 10 km x 10 km Fresno box, UTM zone 11N (metres).
DEFAULT_ORIGIN = (245886.0, 4064660.0)


def _pick_bridge_rows(n: int) -> list:
    """
    Choose three distinct bridge rows: the motorway row (north) plus the
    secondary-road rows closest to 45 % and 70 % of the grid height. The
    southern stretch of the river has no crossing, which is what isolates
    the south-east of the synthetic city.
    """
    secondary_rows = [r for r in range(1, n - 1) if r % 5 == 2]
    rows = [n - 3]
    for frac in (0.45, 0.70):
        target = frac * n
        options = [r for r in secondary_rows if r not in rows] or [
            r for r in range(1, n - 1) if r not in rows
        ]
        rows.append(min(options, key=lambda r: abs(r - target)))
    return rows


def build_synthetic_network(
    n: int = 40,
    spacing_m: float = 250.0,
    seed: int = 42,
    origin_xy: tuple = DEFAULT_ORIGIN,
    removal_fraction: float = 0.08,
    speeds_kph: dict = None,
    junction_delay_s: dict = None,
    crs: str = DEFAULT_CRS,
) -> nx.Graph:
    """
    Build a synthetic undirected street network on an n x n grid.

    Parameters
    ----------
    n : grid nodes per side.
    spacing_m : distance between neighbouring grid nodes (metres).
    seed : random seed for the residential gaps.
    origin_xy : (x, y) of the south-west corner of the study box. Nodes are
        inset by half a spacing so the extent is exactly n * spacing_m.
    removal_fraction : share of all edges removed at random from the
        residential grid (dead ends, missing links).
    speeds_kph / junction_delay_s : per-class overrides of SPEED_KPH and
        JUNCTION_DELAY_S.
    crs : projected CRS string stored in G.graph["crs"].

    Returns
    -------
    networkx.Graph with node attrs x, y and edge attrs length_m, highway,
    speed_kph, travel_time_s, bridge. Graph attrs: crs, n, spacing_m,
    origin_xy, extent_m, river (band Polygon), river_line (LineString),
    bridge_rows, motorway_row, motorway_col.
    """
    if n < 6:
        raise ValueError("n must be at least 6")
    speeds = dict(SPEED_KPH)
    if speeds_kph:
        speeds.update(speeds_kph)
    delays = dict(JUNCTION_DELAY_S)
    if junction_delay_s:
        delays.update(junction_delay_s)

    rng = np.random.default_rng(seed)
    x0, y0 = float(origin_xy[0]), float(origin_xy[1])
    half = spacing_m / 2.0

    def node_id(r, c):
        return r * n + c

    def node_xy(r, c):
        return (x0 + half + c * spacing_m, y0 + half + r * spacing_m)

    G = nx.Graph()
    for r in range(n):
        for c in range(n):
            x, y = node_xy(r, c)
            G.add_node(node_id(r, c), x=x, y=y, row=r, col=c)

    # --- 1. Base grid edges (residential) -------------------------------
    edge_class = {}
    for r in range(n):
        for c in range(n):
            if c + 1 < n:
                edge_class[(node_id(r, c), node_id(r, c + 1))] = "residential"
            if r + 1 < n:
                edge_class[(node_id(r, c), node_id(r + 1, c))] = "residential"

    def upgrade(u, v, cls):
        key = (u, v) if (u, v) in edge_class else (v, u)
        if key not in edge_class:
            edge_class[(u, v)] = cls
            return
        if CLASS_RANK[cls] > CLASS_RANK[edge_class[key]]:
            edge_class[key] = cls

    # --- 2. Secondary roads every 5th row / column ----------------------
    for r in range(n):
        if r % 5 == 2:
            for c in range(n - 1):
                upgrade(node_id(r, c), node_id(r, c + 1), "secondary")
    for c in range(n):
        if c % 5 == 2:
            for r in range(n - 1):
                upgrade(node_id(r, c), node_id(r + 1, c), "secondary")

    # --- 3. Meandering north-south river: the gap column per row --------
    # The river runs between grid column gap_of_row[r] and gap_of_row[r] + 1.
    base_gap = int(round(0.62 * n)) - 1
    amp = max(1.0, n / 25.0)
    gap_of_row = {}
    for r in range(n):
        g = base_gap + int(round(amp * math.sin(2 * math.pi * r / n + 0.7)))
        gap_of_row[r] = int(min(max(g, 1), n - 3))

    def west_bank(r, c):
        return c <= gap_of_row[r]

    # --- 4. Two diagonal primary arterials on the main (west) bank ------
    # They meet the river and stop there: no arterial runs up to a river
    # without a bridge.
    for r in range(n - 1):
        if west_bank(r, r) and west_bank(r + 1, r + 1):
            upgrade(node_id(r, r), node_id(r + 1, r + 1), "primary")
        if west_bank(r, n - 1 - r) and west_bank(r + 1, n - 2 - r):
            upgrade(node_id(r, n - 1 - r), node_id(r + 1, n - 2 - r), "primary")

    # --- 5. Motorway ring segment: along the north edge and down the east
    motorway_row = n - 3
    motorway_col = n - 3
    for c in range(2, n - 3):
        upgrade(node_id(motorway_row, c), node_id(motorway_row, c + 1), "motorway")
    for r in range(int(round(n * 0.5)), motorway_row):
        upgrade(node_id(r, motorway_col), node_id(r + 1, motorway_col), "motorway")

    # --- 6. River band geometry and bridges -----------------------------
    river_pts = []
    # extend beyond the grid so the band spans the whole study box
    river_pts.append((x0 + half + (gap_of_row[0] + 0.5) * spacing_m, y0 - spacing_m))
    for r in range(n):
        river_pts.append((x0 + half + (gap_of_row[r] + 0.5) * spacing_m, node_xy(r, 0)[1]))
    river_pts.append(
        (x0 + half + (gap_of_row[n - 1] + 0.5) * spacing_m, y0 + n * spacing_m + spacing_m)
    )
    river_line = LineString(river_pts)
    river_band = river_line.buffer(0.25 * spacing_m, cap_style="flat")

    bridge_rows = _pick_bridge_rows(n)
    bridge_edges = set()
    for r in bridge_rows:
        g = gap_of_row[r]
        u, v = node_id(r, g), node_id(r, g + 1)
        bridge_edges.add((u, v))
        upgrade(u, v, "secondary")

    # remove every edge that touches the river band unless it is a bridge
    keys = list(edge_class.keys())
    lines = [LineString([node_xy(G.nodes[u]["row"], G.nodes[u]["col"]),
                         node_xy(G.nodes[v]["row"], G.nodes[v]["col"])]) for u, v in keys]
    crosses = shapely.intersects(np.array(lines, dtype=object), river_band)
    for key, hit in zip(keys, crosses):
        if hit and key not in bridge_edges:
            del edge_class[key]

    # --- 7. Random gaps in the residential grid -------------------------
    residential = [k for k, cls in edge_class.items() if cls == "residential"]
    n_remove = int(round(removal_fraction * len(edge_class)))
    if n_remove > 0 and residential:
        idx = rng.choice(len(residential), size=min(n_remove, len(residential)), replace=False)
        for i in sorted(idx, reverse=True):
            del edge_class[residential[i]]

    # --- 8. Add edges with attributes -----------------------------------
    for (u, v), cls in edge_class.items():
        xu, yu = G.nodes[u]["x"], G.nodes[u]["y"]
        xv, yv = G.nodes[v]["x"], G.nodes[v]["y"]
        length = math.hypot(xv - xu, yv - yu)
        speed = float(speeds[cls])
        tt = length / (speed / 3.6) + float(delays[cls])
        G.add_edge(
            u, v,
            length_m=round(length, 3),
            highway=cls,
            speed_kph=speed,
            travel_time_s=round(tt, 3),
            bridge=(u, v) in bridge_edges,
        )

    # keep the largest connected component only (islands are not routable)
    if not nx.is_connected(G):
        largest = max(nx.connected_components(G), key=len)
        G.remove_nodes_from([nd for nd in list(G.nodes) if nd not in largest])

    G.graph.update(
        crs=crs,
        n=n,
        spacing_m=float(spacing_m),
        origin_xy=(x0, y0),
        extent_m=float(n * spacing_m),
        river=river_band,
        river_line=river_line,
        bridge_rows=bridge_rows,
        motorway_row=motorway_row,
        motorway_col=motorway_col,
    )
    return G


def network_to_gdf(G: nx.Graph):
    """
    Convert a graph to (edges_gdf, nodes_gdf).

    edges_gdf columns: u, v, highway, length_m, speed_kph, travel_time_s,
    bridge, geometry (LineString). nodes_gdf columns: node, x, y, geometry.
    """
    crs = G.graph.get("crs", DEFAULT_CRS)
    rows = []
    for u, v, d in G.edges(data=True):
        geom = d.get("geometry")
        if geom is None:
            geom = LineString([(G.nodes[u]["x"], G.nodes[u]["y"]),
                               (G.nodes[v]["x"], G.nodes[v]["y"])])
        rows.append({
            "u": u, "v": v,
            "highway": d.get("highway", "residential"),
            "length_m": float(d.get("length_m", geom.length)),
            "speed_kph": float(d.get("speed_kph", np.nan)),
            "travel_time_s": float(d.get("travel_time_s", np.nan)),
            "bridge": bool(d.get("bridge", False)),
            "geometry": geom,
        })
    edges = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    nodes = gpd.GeoDataFrame(
        {
            "node": list(G.nodes),
            "x": [G.nodes[nd]["x"] for nd in G.nodes],
            "y": [G.nodes[nd]["y"] for nd in G.nodes],
        },
        geometry=[Point(G.nodes[nd]["x"], G.nodes[nd]["y"]) for nd in G.nodes],
        crs=crs,
    )
    return edges, nodes


def river_to_gdf(G: nx.Graph) -> gpd.GeoDataFrame:
    """Return the synthetic river band as a one-row GeoDataFrame (or empty)."""
    crs = G.graph.get("crs", DEFAULT_CRS)
    band = G.graph.get("river")
    if band is None:
        return gpd.GeoDataFrame({"name": []}, geometry=[], crs=crs)
    return gpd.GeoDataFrame({"name": ["river"]}, geometry=[band], crs=crs)


_OSM_CLASS = {
    "motorway": "motorway", "motorway_link": "motorway", "trunk": "motorway",
    "trunk_link": "motorway", "primary": "primary", "primary_link": "primary",
    "secondary": "secondary", "secondary_link": "secondary",
    "tertiary": "secondary", "tertiary_link": "secondary",
}


def osm_to_simple_graph(G_osm) -> nx.Graph:
    """
    Collapse an OSMnx MultiDiGraph (projected, with speeds and travel times)
    into an undirected Graph with this project's attribute names. Parallel
    edges keep the fastest travel time.
    """
    G = nx.Graph()
    for nd, d in G_osm.nodes(data=True):
        G.add_node(nd, x=float(d["x"]), y=float(d["y"]))
    for u, v, d in G_osm.edges(data=True):
        hw = d.get("highway", "residential")
        if isinstance(hw, list):
            hw = hw[0]
        cls = _OSM_CLASS.get(str(hw), "residential")
        tt = float(d.get("travel_time", 0.0))
        length = float(d.get("length", 0.0))
        speed = float(d.get("speed_kph", SPEED_KPH[cls]))
        if G.has_edge(u, v) and G[u][v]["travel_time_s"] <= tt:
            continue
        attrs = dict(length_m=length, highway=cls, speed_kph=speed,
                     travel_time_s=max(tt, 1e-3), bridge=False)
        if d.get("geometry") is not None:
            attrs["geometry"] = d["geometry"]
        G.add_edge(u, v, **attrs)
    G.graph["crs"] = str(G_osm.graph.get("crs", DEFAULT_CRS))
    if not nx.is_connected(G):
        largest = max(nx.connected_components(G), key=len)
        G.remove_nodes_from([nd for nd in list(G.nodes) if nd not in largest])
    return G


def load_osm_network(place_name: str, network_type: str = "drive") -> nx.Graph:
    """
    Download a real drivable street network with OSMnx, add speeds and travel
    times, project it to a local UTM CRS and return it as a simple Graph.

    Not used by the offline demo. Raises RuntimeError with a clear message when
    there is no internet access.
    """
    try:
        import osmnx as ox

        G_osm = ox.graph_from_place(place_name, network_type=network_type)
        G_osm = ox.add_edge_speeds(G_osm)
        G_osm = ox.add_edge_travel_times(G_osm)
        G_osm = ox.project_graph(G_osm)
    except Exception as exc:  # network errors, geocoding failures, etc.
        raise RuntimeError(
            f"Could not download the OpenStreetMap network for '{place_name}'. "
            "This step needs internet access (Nominatim geocoding and the "
            "Overpass API). Run the offline demo with synthetic data instead, "
            f"or retry when online. Original error: {exc}"
        ) from exc
    return osm_to_simple_graph(G_osm)
