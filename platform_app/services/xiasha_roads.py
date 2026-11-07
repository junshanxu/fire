"""Affine the demo site onto the Xiasha road graph and route along it.

The live dispatch still plans in site XY. This module only places those
checkpoints on the public road network around 杭州电子科技大学（下沙校区） and
walks OpenStreetMap highway geometry. It does not invent elevation.
"""

from __future__ import annotations

from functools import lru_cache
from heapq import heappop, heappush
from math import asin, asinh, atan, cos, hypot, inf, pi, radians, sin, sinh, tan
from xml.etree import ElementTree as ET

from platform_app.config import NETWORK_ASSETS_DIR


# Bounding-box center of OSM relation 杭州电子科技大学(下沙校区), not the west-side label.
CENTER_LAT = 30.3165737
CENTER_LON = 120.3479082
METERS_PER_UNIT = 70.0
TILE_ZOOM = 15
EARTH_CIRCUMFERENCE_M = 40_075_016.686
OSM_FILE = NETWORK_ASSETS_DIR / "osm-xiasha.osm"
ATTRIBUTION = "© OpenStreetMap contributors · ODbL"
FRAME_NOTE = "杭州电子科技大学（下沙校区），路线沿道路。"

HIGHWAY_SKIP = {"footway", "cycleway", "path", "steps", "corridor", "bridleway", "proposed", "construction", "raceway", "bus_guideway"}


def map_frame() -> dict:
    return {
        "center_lon": CENTER_LON,
        "center_lat": CENTER_LAT,
        "meters_per_unit": METERS_PER_UNIT,
        "tile_zoom": TILE_ZOOM,
        "attribution": ATTRIBUTION,
        "note": FRAME_NOTE,
    }


def _mercator(lon: float, lat: float, zoom: int = TILE_ZOOM) -> tuple[float, float]:
    world = 2**zoom * 256
    x = (lon + 180) / 360 * world
    y = (1 - asinh(tan(radians(lat))) / pi) / 2 * world
    return x, y


def _pixels_per_unit(zoom: int = TILE_ZOOM) -> float:
    world = 2**zoom * 256
    return METERS_PER_UNIT / cos(radians(CENTER_LAT)) * world / EARTH_CIRCUMFERENCE_M


def lonlat_to_scene(lon: float, lat: float) -> tuple[float, float]:
    cx, cy = _mercator(CENTER_LON, CENTER_LAT)
    px, py = _mercator(lon, lat)
    unit = _pixels_per_unit()
    return 50 + (px - cx) / unit, 50 + (py - cy) / unit


def scene_to_lonlat(x: float, y: float) -> tuple[float, float]:
    cx, cy = _mercator(CENTER_LON, CENTER_LAT)
    unit = _pixels_per_unit()
    px = cx + (x - 50) * unit
    py = cy + (y - 50) * unit
    world = 2**TILE_ZOOM * 256
    lon = px / world * 360 - 180
    lat = atan(sinh(pi * (1 - 2 * py / world))) * 180 / pi
    return lon, lat


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * radius * asin(min(1, a ** 0.5))


def _load_graph() -> tuple[dict, dict, dict]:
    root = ET.parse(OSM_FILE).getroot()
    raw_nodes = {node.attrib["id"]: (float(node.attrib["lon"]), float(node.attrib["lat"])) for node in root.findall("node")}
    directed: dict[str, list[tuple[str, float]]] = {}
    undirected: dict[str, list[tuple[str, float]]] = {}
    used: set[str] = set()

    def add(graph: dict, left: str, right: str, length: float) -> None:
        if left == right or length <= 0:
            return
        graph.setdefault(left, []).append((right, length))

    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        highway = tags.get("highway")
        if not highway or highway in HIGHWAY_SKIP:
            continue
        refs = [node.attrib["ref"] for node in way.findall("nd") if node.attrib["ref"] in raw_nodes]
        if len(refs) < 2:
            continue
        oneway = tags.get("oneway", "no").lower()
        forward = oneway not in {"-1", "reverse"}
        backward = oneway not in {"yes", "true", "1"}
        for left, right in zip(refs, refs[1:]):
            lon1, lat1 = raw_nodes[left]
            lon2, lat2 = raw_nodes[right]
            length = _haversine_m(lon1, lat1, lon2, lat2)
            if forward:
                add(directed, left, right, length)
            if backward:
                add(directed, right, left, length)
            add(undirected, left, right, length)
            add(undirected, right, left, length)
            used.add(left)
            used.add(right)
    scene = {}
    for node_id in used:
        lon, lat = raw_nodes[node_id]
        x, y = lonlat_to_scene(lon, lat)
        scene[node_id] = (lon, lat, x, y)
    return scene, directed, undirected


@lru_cache(maxsize=1)
def _graphs() -> tuple[dict, dict, dict]:
    return _load_graph()


def _snap(x: float, y: float, scene: dict) -> str | None:
    best = None
    best_d = inf
    for node_id, (_, _, nx, ny) in scene.items():
        distance = hypot(nx - x, ny - y)
        if distance < best_d:
            best, best_d = node_id, distance
    return best


def _shortest(start: str, goal: str, adjacency: dict, scene: dict) -> list[str]:
    if start == goal:
        return [start]
    heuristic = lambda node: hypot(scene[node][2] - scene[goal][2], scene[node][3] - scene[goal][3]) * METERS_PER_UNIT
    queue = [(heuristic(start), 0.0, start)]
    came: dict[str, str | None] = {start: None}
    cost = {start: 0.0}
    while queue:
        _, travelled, node = heappop(queue)
        if travelled != cost.get(node):
            continue
        if node == goal:
            break
        for nxt, weight in adjacency.get(node, ()):
            candidate = travelled + weight
            if candidate < cost.get(nxt, inf):
                cost[nxt] = candidate
                came[nxt] = node
                heappush(queue, (candidate + heuristic(nxt), candidate, nxt))
    if goal not in came:
        return []
    path = []
    node: str | None = goal
    while node is not None:
        path.append(node)
        node = came[node]
    path.reverse()
    return path


def _polyline(node_ids: list[str], scene: dict) -> list[dict]:
    points = []
    for node_id in node_ids:
        lon, lat, x, y = scene[node_id]
        point = {"x": round(x, 2), "y": round(y, 2), "lon": round(lon, 6), "lat": round(lat, 6)}
        if points and hypot(point["x"] - points[-1]["x"], point["y"] - points[-1]["y"]) < 0.04:
            continue
        points.append(point)
    return points


@lru_cache(maxsize=512)
def _cached_path(stops: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float, float, float], ...]:
    scene, directed, undirected = _graphs()
    if not scene:
        return tuple()
    snapped = []
    for x, y in stops:
        node = _snap(x, y, scene)
        if node and (not snapped or snapped[-1] != node):
            snapped.append(node)
    if not snapped:
        return tuple()
    chosen = []
    for left, right in zip(snapped, snapped[1:]):
        leg = _shortest(left, right, directed, scene) or _shortest(left, right, undirected, scene)
        if not leg:
            continue
        if chosen and leg[0] == chosen[-1]:
            leg = leg[1:]
        chosen.extend(leg)
    if not chosen:
        chosen = snapped[:1]
    packed = []
    for point in _polyline(chosen, scene):
        packed.append((point["x"], point["y"], point["lon"], point["lat"]))
    return tuple(packed)


def road_path_for_stops(stops: list[dict]) -> list[dict]:
    """Map site checkpoints onto Xiasha roads and return one centerline."""
    try:
        cleaned = []
        for stop in stops:
            x, y = float(stop["x"]), float(stop["y"])
            if cleaned and abs(cleaned[-1][0] - x) < 0.05 and abs(cleaned[-1][1] - y) < 0.05:
                continue
            cleaned.append((round(x, 2), round(y, 2)))
        if not cleaned:
            return []
        return [{"x": x, "y": y, "lon": lon, "lat": lat} for x, y, lon, lat in _cached_path(tuple(cleaned))]
    except (ET.ParseError, OSError, KeyError, ValueError):
        return []
