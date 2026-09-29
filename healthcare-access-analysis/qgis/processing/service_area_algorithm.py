"""
Service Area from Road Lines (Portfolio)

QGIS Processing script: builds a routable graph from a road line layer,
seeds a Dijkstra search at every facility point and returns the dissolved
polygon of all road segments reachable within a travel-time cutoff.

Pure PyQGIS + heapq + numpy (no networkx, no osmnx), so it runs inside the
QGIS Python environment as-is.

Install: Processing Toolbox > Scripts > Create New Script, paste this file,
save as service_area_algorithm.py, then run "Service Area from Road Lines
(Portfolio)" from the Toolbox group "Bhargav Portfolio".
"""

import heapq
import math

import numpy as np
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)


class ServiceAreaAlgorithm(QgsProcessingAlgorithm):
    ROADS = "ROADS"
    FACILITIES = "FACILITIES"
    SPEED_FIELD = "SPEED_FIELD"
    DEFAULT_SPEED = "DEFAULT_SPEED"
    CUTOFF = "CUTOFF"
    BUFFER = "BUFFER"
    OUTPUT = "OUTPUT"

    SNAP_M = 0.5  # line endpoints within 0.5 map units share a graph node

    def tr(self, text):
        return QCoreApplication.translate("Processing", text)

    def createInstance(self):
        return ServiceAreaAlgorithm()

    def name(self):
        return "portfolio_service_area"

    def displayName(self):
        return self.tr("Service Area from Road Lines (Portfolio)")

    def group(self):
        return self.tr("Bhargav Portfolio")

    def groupId(self):
        return "bhargav_portfolio"

    def shortHelpString(self):
        return self.tr(
            "Builds a travel-time graph from a road line layer (endpoints snapped to a "
            "0.5 map-unit grid), runs a multi-source Dijkstra from every facility point "
            "and buffers and dissolves the road segments reached within the cutoff.\n\n"
            "Inputs: road lines (projected CRS, metres), facility points, an optional "
            "numeric speed field in km/h (else the default speed), the cutoff in minutes "
            "and the buffer width around reached roads.\n"
            "Output: one polygon feature (service area) with cutoff_min, n_facilities, "
            "n_segments and area_km2 attributes."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROADS, self.tr("Road lines"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facility points"), [QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.SPEED_FIELD, self.tr("Speed field (km/h, optional)"),
            parentLayerParameterName=self.ROADS, type=QgsProcessingParameterField.Numeric,
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DEFAULT_SPEED, self.tr("Default speed (km/h) when no field or value is missing"),
            QgsProcessingParameterNumber.Double, 40.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUTOFF, self.tr("Cutoff travel time (minutes)"),
            QgsProcessingParameterNumber.Double, 15.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUFFER, self.tr("Buffer around reached roads (map units)"),
            QgsProcessingParameterNumber.Double, 100.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Service area"), QgsProcessing.TypeVectorPolygon))

    # ------------------------------------------------------------------ #
    def _snap_key(self, pt):
        s = self.SNAP_M
        return (round(pt.x() / s) * s, round(pt.y() / s) * s)

    def processAlgorithm(self, parameters, context, feedback):
        roads = self.parameterAsSource(parameters, self.ROADS, context)
        facilities = self.parameterAsSource(parameters, self.FACILITIES, context)
        if roads is None or facilities is None:
            raise QgsProcessingException(self.tr("Could not load the input layers."))
        speed_field = self.parameterAsString(parameters, self.SPEED_FIELD, context)
        default_speed = self.parameterAsDouble(parameters, self.DEFAULT_SPEED, context)
        cutoff_s = 60.0 * self.parameterAsDouble(parameters, self.CUTOFF, context)
        buffer_m = self.parameterAsDouble(parameters, self.BUFFER, context)

        road_crs = roads.sourceCrs()
        if road_crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "The road layer must be in a projected CRS (metres). Reproject it first."))

        speed_idx = -1
        if speed_field:
            speed_idx = roads.fields().indexFromName(speed_field)

        # ---- 1. build the graph ------------------------------------------
        node_index = {}
        node_xy = []
        adjacency = []            # list of lists of (neighbour, seconds)
        segments = []             # (u, v, time_s)
        total = roads.featureCount() or 1
        feedback.pushInfo(self.tr("Building the travel-time graph..."))
        for i, feat in enumerate(roads.getFeatures()):
            if feedback.isCanceled():
                return {}
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            speed = default_speed
            if speed_idx >= 0:
                val = feat.attributes()[speed_idx]
                try:
                    if val is not None and float(val) > 0:
                        speed = float(val)
                except (TypeError, ValueError):
                    pass
            metres_per_s = speed / 3.6
            lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for line in lines:
                for p, q in zip(line[:-1], line[1:]):
                    length = math.hypot(q.x() - p.x(), q.y() - p.y())
                    if length <= 0:
                        continue
                    seconds = length / metres_per_s
                    ids = []
                    for pt in (p, q):
                        key = self._snap_key(pt)
                        idx = node_index.get(key)
                        if idx is None:
                            idx = len(node_xy)
                            node_index[key] = idx
                            node_xy.append(key)
                            adjacency.append([])
                        ids.append(idx)
                    u, v = ids
                    adjacency[u].append((v, seconds))
                    adjacency[v].append((u, seconds))
                    segments.append((u, v, seconds))
            if i % 500 == 0:
                feedback.setProgress(int(40.0 * i / total))
        if not node_xy:
            raise QgsProcessingException(self.tr("The road layer has no usable line geometry."))
        feedback.pushInfo(self.tr(f"Graph: {len(node_xy)} nodes, {len(segments)} segments"))

        # ---- 2. snap facilities to the nearest graph node ----------------
        xy = np.asarray(node_xy, dtype=float)
        transform = None
        if facilities.sourceCrs() != road_crs:
            transform = QgsCoordinateTransform(facilities.sourceCrs(), road_crs, context.transformContext())
        sources = set()
        for feat in facilities.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            if transform is not None:
                geom = QgsGeometry(geom)
                geom.transform(transform)
            pt = geom.asMultiPoint()[0] if geom.isMultipart() else geom.asPoint()
            d2 = (xy[:, 0] - pt.x()) ** 2 + (xy[:, 1] - pt.y()) ** 2
            sources.add(int(np.argmin(d2)))
        if not sources:
            raise QgsProcessingException(self.tr("No facility point could be snapped to the network."))
        feedback.pushInfo(self.tr(f"{len(sources)} facility nodes seeded"))

        # ---- 3. multi-source Dijkstra with heapq -------------------------
        n = len(node_xy)
        dist = [math.inf] * n
        heap = []
        for s in sources:
            dist[s] = 0.0
            heap.append((0.0, s))
        heapq.heapify(heap)
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            if d > cutoff_s:
                break
            for v, w in adjacency[u]:
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        feedback.setProgress(60)

        # ---- 4. buffer reached (and partly reached) segments -------------
        buffers = []
        for k, (u, v, seconds) in enumerate(segments):
            if feedback.isCanceled():
                return {}
            du, dv = dist[u], dist[v]
            if du > cutoff_s and dv > cutoff_s:
                continue
            near, far = (u, v) if du <= dv else (v, u)
            d_near = min(du, dv)
            frac = 1.0 if seconds <= 0 else min(1.0, (cutoff_s - d_near) / seconds)
            x1, y1 = node_xy[near]
            x2, y2 = node_xy[far]
            if frac < 1.0:
                x2, y2 = x1 + frac * (x2 - x1), y1 + frac * (y2 - y1)
            line = QgsGeometry.fromPolylineXY([QgsPointXY(x1, y1), QgsPointXY(x2, y2)])
            buffers.append(line.buffer(buffer_m, 8) if buffer_m > 0 else line)
            if k % 2000 == 0:
                feedback.setProgress(60 + int(30.0 * k / max(1, len(segments))))
        if not buffers:
            raise QgsProcessingException(self.tr("No road segment is reachable within the cutoff."))

        dissolved = QgsGeometry.unaryUnion(buffers)
        if dissolved.isEmpty():
            raise QgsProcessingException(self.tr("Dissolve produced an empty geometry."))
        dissolved.convertToMultiType()
        feedback.setProgress(95)

        # ---- 5. write the sink -------------------------------------------
        fields = QgsFields()
        fields.append(QgsField("cutoff_min", QVariant.Double))
        fields.append(QgsField("n_facilities", QVariant.Int))
        fields.append(QgsField("n_segments", QVariant.Int))
        fields.append(QgsField("area_km2", QVariant.Double))
        sink, dest_id = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                             QgsWkbTypes.MultiPolygon, road_crs)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))
        feat = QgsFeature(fields)
        feat.setGeometry(dissolved)
        feat.setAttributes([cutoff_s / 60.0, len(sources), len(buffers), dissolved.area() / 1e6])
        sink.addFeature(feat, QgsFeatureSink.FastInsert)
        feedback.pushInfo(self.tr(
            f"Service area: {len(buffers)} segments reached, {dissolved.area() / 1e6:.2f} km2"))
        feedback.setProgress(100)
        return {self.OUTPUT: dest_id}
