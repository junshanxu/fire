"""Road graphs shared by the reference map and its route preview.

The live dispatch site keeps its own coordinates. Each imported source is a
separate graph: geometry, links, and the highlighted route all come from it.
"""

from __future__ import annotations

from functools import lru_cache
from heapq import heappop, heappush
from math import cos, hypot, inf, radians, sin
from pathlib import Path
from xml.etree import ElementTree as ET

from platform_app.config import NETWORK_ASSETS_DIR


DRIVING_LANES = {"driving", "entry", "exit", "onRamp", "offRamp", "connectingRamp", "slipLane"}
XODR_CATALOG = (
    ("esmini-curves-elevation.xodr", "esmini-elevation", "esmini · 高程道路", "https://github.com/esmini/esmini/blob/master/resources/xodr/curves_elevation.xodr"),
    ("multi_intersections.xodr", "esmini-intersections", "esmini · 路口路网", "https://github.com/esmini/esmini/blob/master/resources/xodr/multi_intersections.xodr"),
    ("fabriksgatan.xodr", "esmini-fabriksgatan", "esmini · 城市道路", "https://github.com/esmini/esmini/blob/master/resources/xodr/fabriksgatan.xodr"),
)


def _cubic(segment: dict, ds: float) -> float:
    return segment["a"] + ds * (segment["b"] + ds * (segment["c"] + ds * segment["d"]))


def _cubic_slope(segment: dict, ds: float) -> float:
    return segment["b"] + ds * (2 * segment["c"] + 3 * ds * segment["d"])


def _elevation_at(segments: list[dict], station: float) -> tuple[float, float]:
    chosen = None
    for segment in segments:
        if segment["s"] <= station + 1e-6:
            chosen = segment
        else:
            break
    if chosen is None:
        return 0.0, 0.0
    ds = station - chosen["s"]
    return _cubic(chosen, ds), _cubic_slope(chosen, ds)


def _sample_primitive(x: float, y: float, heading: float, length: float, kind: str, attrs: dict) -> list[tuple[float, float, float]]:
    if kind == "spiral":
        steps = max(1, round(length / 1.0))
        start = float(attrs.get("curvStart", 0))
        end = float(attrs.get("curvEnd", 0))

        def turn(ds: float) -> float:
            return heading + start * ds + (end - start) * ds * ds / (2 * length)

        px, py, previous = x, y, 0.0
        points = [(0.0, px, py)]
        for index in range(1, steps + 1):
            ds = length * index / steps
            mid = (previous + ds) / 2
            px += (ds - previous) * cos(turn(mid))
            py += (ds - previous) * sin(turn(mid))
            points.append((ds, px, py))
            previous = ds
        return points

    steps = max(1, round(length / 8))
    if kind == "arc":
        curvature = float(attrs.get("curvature", 0))
        points = []
        for index in range(steps + 1):
            ds = length * index / steps
            if abs(curvature) < 1e-9:
                px, py = x + ds * cos(heading), y + ds * sin(heading)
            else:
                turned = heading + curvature * ds
                px = x + (sin(turned) - sin(heading)) / curvature
                py = y - (cos(turned) - cos(heading)) / curvature
            points.append((ds, px, py))
        return points
    if kind == "paramPoly3":
        span = length if attrs.get("pRange", "normalized") == "arcLength" else 1.0
        au, bu, cu, du = (float(attrs.get(key, 0)) for key in ("aU", "bU", "cU", "dU"))
        av, bv, cv, dv = (float(attrs.get(key, 0)) for key in ("aV", "bV", "cV", "dV"))
        points = []
        for index in range(steps + 1):
            ds = length * index / steps
            parameter = span * index / steps
            local_u = au + parameter * (bu + parameter * (cu + parameter * du))
            local_v = av + parameter * (bv + parameter * (cv + parameter * dv))
            px = x + local_u * cos(heading) - local_v * sin(heading)
            py = y + local_u * sin(heading) + local_v * cos(heading)
            points.append((ds, px, py))
        return points
    if kind == "poly3":
        av, bv, cv, dv = (float(attrs.get(key, 0)) for key in ("a", "b", "c", "d"))
        points = []
        for index in range(steps + 1):
            ds = length * index / steps
            local_v = av + ds * (bv + ds * (cv + ds * dv))
            px = x + ds * cos(heading) - local_v * sin(heading)
            py = y + ds * sin(heading) + local_v * cos(heading)
            points.append((ds, px, py))
        return points
    points = []
    for index in range(steps + 1):
        ds = length * index / steps
        points.append((ds, x + ds * cos(heading), y + ds * sin(heading)))
    return points


def _geometry_kind(geometry: ET.Element) -> tuple[str, dict]:
    for child in geometry:
        if child.tag in {"line", "arc", "spiral", "poly3", "paramPoly3"}:
            return child.tag, child.attrib
    return "line", {}


def _link(node: ET.Element | None) -> dict | None:
    if node is None:
        return None
    return {"type": node.attrib.get("elementType", ""), "id": node.attrib.get("elementId", ""), "contact": node.attrib.get("contactPoint", "start")}


def _directions(road: ET.Element) -> tuple[bool, bool]:
    forward = backward = False
    for lane in road.findall("./lanes/laneSection/left/lane") + road.findall("./lanes/laneSection/right/lane"):
        if lane.attrib.get("type") not in DRIVING_LANES:
            continue
        lane_id = int(float(lane.attrib.get("id", "0")))
        if lane_id < 0:
            forward = True
        elif lane_id > 0:
            backward = True
    if not forward and not backward:
        forward = True
    return forward, backward


def _downsample(points: list[dict], spacing: float = 10) -> list[dict]:
    if len(points) < 3:
        return points
    kept = [points[0]]
    for point in points[1:-1]:
        previous = kept[-1]
        if hypot(point["x"] - previous["x"], point["y"] - previous["y"]) >= spacing:
            kept.append(point)
    kept.append(points[-1])
    return kept


def _join_ports(roads: list[dict], junctions: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(item: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(item, item)
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    known = {road["id"] for road in roads}
    by_id = {road["id"]: road for road in roads}
    for road in roads:
        for end_name, link in road["links"].items():
            if not link or link["type"] != "road" or link["id"] not in known:
                continue
            this_end = "start" if end_name == "predecessor" else "end"
            union((road["id"], this_end), (link["id"], link["contact"]))
    for junction in junctions:
        for connection in junction["connections"]:
            incoming = by_id.get(connection["incoming"])
            if incoming is None or connection["connecting"] not in known:
                continue
            incoming_end = None
            for end_name, link in incoming["links"].items():
                if link and link["type"] == "junction" and link["id"] == junction["id"]:
                    incoming_end = "start" if end_name == "predecessor" else "end"
            if incoming_end is None:
                continue
            union((incoming["id"], incoming_end), (connection["connecting"], connection["contact"]))
    for road in roads:
        find((road["id"], "start"))
        find((road["id"], "end"))
    return parent


def _route_across(roads: list[dict], ports: dict[tuple[str, str], tuple[str, str]]) -> dict:
    def find(item: tuple[str, str]) -> tuple[str, str]:
        while ports[item] != item:
            ports[item] = ports[ports[item]]
            item = ports[item]
        return item

    adjacency: dict[tuple[str, str], list[tuple]] = {}
    for road in roads:
        start, end = find((road["id"], "start")), find((road["id"], "end"))
        length = road["length_m"]
        if length <= 0 or start == end:
            continue
        if road["forward"]:
            adjacency.setdefault(start, []).append((end, length, road["id"], road["points"]))
        if road["backward"]:
            adjacency.setdefault(end, []).append((start, length, road["id"], list(reversed(road["points"]))))
    if not adjacency:
        return {"length_m": 0, "road_ids": [], "path": []}

    def farthest(origin: tuple[str, str]) -> tuple[tuple[str, str], dict]:
        distance = {origin: 0.0}
        previous: dict = {}
        queue = [(0.0, origin)]
        while queue:
            travelled, node = heappop(queue)
            if travelled != distance.get(node):
                continue
            for nxt, weight, road_id, polyline in adjacency.get(node, ()):
                candidate = travelled + weight
                if candidate < distance.get(nxt, inf):
                    distance[nxt] = candidate
                    previous[nxt] = (node, road_id, polyline)
                    heappush(queue, (candidate, nxt))
        far = max(distance, key=distance.get)
        return far, previous

    start = next(iter(adjacency))
    first, _ = farthest(start)
    finish, previous = farthest(first)
    pieces = []
    road_ids = []
    node = finish
    while node != first:
        if node not in previous:
            break
        node, road_id, polyline = previous[node]
        pieces.append(polyline)
        road_ids.append(road_id)
    pieces.reverse()
    road_ids.reverse()
    path: list[dict] = []
    for polyline in pieces:
        if path and polyline and hypot(path[-1]["x"] - polyline[0]["x"], path[-1]["y"] - polyline[0]["y"]) < 1.5:
            polyline = polyline[1:]
        path.extend(polyline)
    collapsed = []
    for road_id in road_ids:
        if not collapsed or collapsed[-1] != road_id:
            collapsed.append(road_id)
    length = 0.0
    for left, right in zip(path, path[1:]):
        length += hypot(right["x"] - left["x"], right["y"] - left["y"])
    return {"length_m": round(length, 1), "road_ids": collapsed, "path": path}


def _scene_frame(lines: list[list[dict]], route: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    points = [point for line in lines for point in line] + route
    if not points:
        return [], []
    min_x, max_x = min(point["x"] for point in points), max(point["x"] for point in points)
    min_y, max_y = min(point["y"] for point in points), max(point["y"] for point in points)
    min_z, max_z = min(point.get("z", 0) for point in points), max(point.get("z", 0) for point in points)
    span = max(max_x - min_x, max_y - min_y, 1e-9)
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    z_span = max_z - min_z

    def convert(point: dict) -> dict:
        z = 30 if z_span < 0.2 else 30 + (point.get("z", 0) - min_z) / z_span * 55
        return {
            "x": round(50 + (point["x"] - center_x) / span * 78, 2),
            "y": round(50 - (point["y"] - center_y) / span * 78, 2),
            "z": round(z, 2),
        }

    return [[convert(point) for point in line] for line in lines], [convert(point) for point in route]


def _summary(roads: list[dict], junctions: int) -> dict:
    points = [point for road in roads for point in road["points"]]
    grades = [abs(point.get("slope", 0)) for point in points]
    elevations = [point.get("z", 0) for point in points] or [0]
    return {
        "roads": len(roads),
        "junctions": junctions,
        "length_m": round(sum(road["length_m"] for road in roads), 1),
        "elevation_m": [round(min(elevations), 2), round(max(elevations), 2)],
        "max_grade_pct": round(max(grades, default=0) * 100, 2),
    }


def parse_opendrive(path: Path) -> dict:
    root = ET.parse(path).getroot()
    junctions = []
    for junction in root.findall("junction"):
        junctions.append({
            "id": junction.attrib.get("id", ""),
            "connections": [
                {"incoming": item.attrib.get("incomingRoad", ""), "connecting": item.attrib.get("connectingRoad", ""), "contact": item.attrib.get("contactPoint", "start")}
                for item in junction.findall("connection")
            ],
        })
    roads = []
    max_join_error = 0.0
    for road in root.findall("road"):
        elevation = [
            {key: float(node.attrib.get(key, 0)) for key in ("s", "a", "b", "c", "d")}
            for node in road.findall("./elevationProfile/elevation")
        ]
        elevation.sort(key=lambda item: item["s"])
        samples: list[tuple[float, float, float]] = []
        previous_end = None
        for geometry in road.findall("./planView/geometry"):
            station, x, y, heading, length = (float(geometry.attrib[key]) for key in ("s", "x", "y", "hdg", "length"))
            if previous_end is not None:
                max_join_error = max(max_join_error, hypot(previous_end[0] - x, previous_end[1] - y))
            kind, attrs = _geometry_kind(geometry)
            primitive = _sample_primitive(x, y, heading, length, kind, attrs)
            if samples and primitive:
                primitive = primitive[1:]
            samples.extend((station + ds, px, py) for ds, px, py in primitive)
            previous_end = (primitive[-1][1], primitive[-1][2]) if primitive else (x, y)
        points = []
        for station, x, y in samples:
            z, slope = _elevation_at(elevation, station)
            points.append({"x": x, "y": y, "z": z, "s": station, "slope": slope})
        points = _downsample(points)
        forward, backward = _directions(road)
        roads.append({
            "id": road.attrib.get("id", ""),
            "length_m": float(road.attrib.get("length", 0)),
            "forward": forward,
            "backward": backward,
            "links": {"predecessor": _link(road.find("./link/predecessor")), "successor": _link(road.find("./link/successor"))},
            "points": points,
        })
    route = _route_across(roads, _join_ports(roads, junctions))
    return {"roads": roads, "junctions": len(junctions), "route": route, "max_join_error_m": max_join_error}


def parse_osm(path: Path) -> dict:
    root = ET.parse(path).getroot()
    raw_nodes = {node.attrib["id"]: (float(node.attrib["lon"]), float(node.attrib["lat"])) for node in root.findall("node")}
    if not raw_nodes:
        return {"roads": [], "junctions": 0, "route": {"length_m": 0, "road_ids": [], "path": []}, "max_join_error_m": 0}
    lon0 = sum(item[0] for item in raw_nodes.values()) / len(raw_nodes)
    lat0 = sum(item[1] for item in raw_nodes.values()) / len(raw_nodes)
    scale_x = 111_320 * cos(radians(lat0))
    nodes = {key: {"x": (lon - lon0) * scale_x, "y": (lat - lat0) * 110_540, "z": 0, "slope": 0} for key, (lon, lat) in raw_nodes.items()}
    roads = []
    adjacency: dict[str, list[tuple]] = {}
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if "highway" not in tags:
            continue
        refs = [node.attrib["ref"] for node in way.findall("nd") if node.attrib["ref"] in nodes]
        if len(refs) < 2:
            continue
        points = [dict(nodes[ref]) for ref in refs]
        length = sum(hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(points, points[1:]))
        oneway = tags.get("oneway", "no").lower()
        forward, backward = (False, True) if oneway in {"-1", "reverse"} else (True, False) if oneway in {"yes", "true", "1"} else (True, True)
        roads.append({"id": way.attrib.get("id", ""), "length_m": length, "points": points})
        for left, right in zip(refs, refs[1:]):
            segment = hypot(nodes[right]["x"] - nodes[left]["x"], nodes[right]["y"] - nodes[left]["y"])
            if forward:
                adjacency.setdefault(left, []).append((right, segment, way.attrib.get("id", ""), [nodes[left], nodes[right]]))
            if backward:
                adjacency.setdefault(right, []).append((left, segment, way.attrib.get("id", ""), [nodes[right], nodes[left]]))
    route = _route_across_adjacency(adjacency)
    return {"roads": roads, "junctions": 0, "route": route, "max_join_error_m": 0}


def _route_across_adjacency(adjacency: dict[str, list[tuple]]) -> dict:
    if not adjacency:
        return {"length_m": 0, "road_ids": [], "path": []}

    def farthest(origin: str) -> tuple[str, dict]:
        distance = {origin: 0.0}
        previous: dict = {}
        queue = [(0.0, origin)]
        while queue:
            travelled, node = heappop(queue)
            if travelled != distance.get(node):
                continue
            for nxt, weight, road_id, polyline in adjacency.get(node, ()):
                candidate = travelled + weight
                if candidate < distance.get(nxt, inf):
                    distance[nxt] = candidate
                    previous[nxt] = (node, road_id, polyline)
                    heappush(queue, (candidate, nxt))
        return max(distance, key=distance.get), previous

    start = next(iter(adjacency))
    first, _ = farthest(start)
    finish, previous = farthest(first)
    pieces = []
    road_ids = []
    node = finish
    while node != first and node in previous:
        node, road_id, polyline = previous[node]
        pieces.append(polyline)
        road_ids.append(road_id)
    pieces.reverse()
    road_ids.reverse()
    path: list[dict] = []
    for polyline in pieces:
        if path and polyline and hypot(path[-1]["x"] - polyline[0]["x"], path[-1]["y"] - polyline[0]["y"]) < 0.2:
            polyline = polyline[1:]
        path.extend(dict(point) for point in polyline)
    collapsed = []
    for road_id in road_ids:
        if not collapsed or collapsed[-1] != road_id:
            collapsed.append(road_id)
    length = sum(hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(path, path[1:]))
    return {"length_m": round(length, 1), "road_ids": collapsed, "path": path}


def _publish(source_id: str, name: str, kind: str, attribution: str, source_url: str, parsed: dict) -> dict:
    lines, route_path = _scene_frame([road["points"] for road in parsed["roads"]], parsed["route"]["path"])
    return {
        "id": source_id,
        "name": name,
        "kind": kind,
        "active_for_planning": False,
        "routable": bool(route_path),
        "attribution": attribution,
        "source_url": source_url,
        "summary": _summary(parsed["roads"], parsed["junctions"]),
        "lines": lines,
        "route": {**parsed["route"], "path": route_path, "road_count": len(parsed["route"]["road_ids"])},
    }


@lru_cache(maxsize=1)
def network_sources() -> list[dict]:
    sources = []
    for filename, source_id, name, url in XODR_CATALOG:
        parsed = parse_opendrive(NETWORK_ASSETS_DIR / filename)
        sources.append(_publish(source_id, name, "OpenDRIVE 路网", "esmini · MPL-2.0", url, parsed))
    osm = parse_osm(NETWORK_ASSETS_DIR / "osmnx-munich-sample.osm")
    sources.append(_publish(
        "osmnx-osm",
        "OSMnx · OSM 路网",
        "OSM 道路图",
        "© OpenStreetMap contributors · ODbL",
        "https://github.com/gboeing/osmnx-examples",
        osm,
    ))
    return sources
