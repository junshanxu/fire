"""Explainable V1 resource assignment and A*/VRP-style route planning."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import cos, hypot, sin


AVAILABLE_STATES = {"待命", "在线"}
STANDBY_PER_TYPE = {"person": 1, "robot": 1, "dog": 1, "drone": 1}
ENERGY_PER_KM = {"person": 0.0, "robot": 8.0, "dog": 7.0, "drone": 10.0}
DEFAULT_REQUIREMENTS = {
    "team": {"capabilities": ["manual_inspection"], "terrain": "flat", "min_width_m": 0.5, "max_slope_deg": 20},
    "robot": {"capabilities": ["rgb_camera"], "terrain": "flat", "min_width_m": 0.8, "max_slope_deg": 10},
    "drone": {"capabilities": ["aerial_camera"], "terrain": "outdoor", "min_width_m": 0, "max_slope_deg": 90},
}
TYPE_FOR_TASK = {"person": "team", "robot": "robot", "dog": "robot", "drone": "drone"}


@dataclass(frozen=True)
class CandidateResult:
    accepted: bool
    score: float
    reasons: list[str]
    rejected_by: list[str]
    estimated_energy_pct: int
    battery_after_pct: int | None


def _requirements(task: dict) -> dict:
    value = dict(DEFAULT_REQUIREMENTS.get(task.get("type"), {}))
    value.update(task.get("requirements") or {})
    value["capabilities"] = list(value.get("capabilities") or [])
    return value


def _weather(environment: dict) -> dict:
    return (environment or {}).get("weather") or {}


def estimate_energy(task: dict, resource: dict) -> int:
    route = task.get("route") or {}
    distance_km = max(0.2, float(route.get("distance_m") or 1200) / 1000)
    approach = hypot(
        float((resource.get("position") or {}).get("x", 50)) - float((route.get("start") or {}).get("x", 50)),
        float((resource.get("position") or {}).get("y", 50)) - float((route.get("start") or {}).get("y", 50)),
    )
    approach_km = approach * 0.004
    rate = ENERGY_PER_KM.get(resource.get("type"), 8.0)
    climb_budget = max(0, float(route.get("elevation_gain_m") or 0)) / 100 * 3
    return int(round(5 + (distance_km + approach_km * 2) * rate + climb_budget)) if rate else 0


def evaluate_candidate(task: dict, resource: dict, environment: dict) -> CandidateResult:
    requirements = _requirements(task)
    rejected = []
    reasons = []
    allowed_types = requirements.get('allowed_resource_types')
    if allowed_types and resource.get('type') not in allowed_types:
        rejected.append('任务限定执行设备类型')
    if resource.get("status") not in AVAILABLE_STATES:
        rejected.append("设备非空闲或不在线")
    if TYPE_FOR_TASK.get(resource.get("type")) != task.get("type"):
        rejected.append("设备类型与任务不匹配")
    if resource.get("station") != task.get("station"):
        rejected.append("设备不在任务场站")
    missing = sorted(set(requirements["capabilities"]) - set(resource.get("capabilities") or []))
    if missing:
        rejected.append("缺少能力：" + "、".join(missing))
    terrain = requirements.get("terrain")
    if terrain and terrain not in set(resource.get("terrain") or []):
        rejected.append(f"不支持{terrain}地形")
    if float(resource.get("max_slope_deg") or 0) < float(requirements.get("max_slope_deg") or 0):
        rejected.append("最大爬坡角不足")
    resource_width = resource.get("min_width_m")
    required_width = requirements.get("min_width_m")
    if resource_width is not None and required_width is not None and float(resource_width) > float(required_width):
        rejected.append("所需通道宽度不足")

    weather = _weather(environment)
    if resource.get("type") == "drone":
        if float(weather.get("wind_mps") or 0) > float(requirements.get("max_wind_mps") or 8):
            rejected.append("风速超过无人机任务阈值")
        if float(weather.get("precipitation_mm") or 0) > 0:
            rejected.append("降水条件不允许飞行")
        if not environment.get("flight_allowed", True):
            rejected.append("当前空域禁止飞行")

    energy = estimate_energy(task, resource)
    power = resource.get("power_percent")
    reserve = int(resource.get("reserve_pct") or 0)
    battery_after = None if power is None else int(power) - energy
    if power is not None and int(power) < energy + reserve:
        rejected.append(f"电量不足：需 {energy}% + {reserve}% 安全余量")

    route = task.get("route") or {}
    distance = hypot(
        float((resource.get("position") or {}).get("x", 50)) - float((route.get("start") or {}).get("x", 50)),
        float((resource.get("position") or {}).get("y", 50)) - float((route.get("start") or {}).get("y", 50)),
    )
    capability_score = 40 if not missing else max(0, 40 - len(missing) * 20)
    battery_score = 25 if power is None else max(0, min(25, (int(power) - energy - reserve) * 0.6 + 12))
    proximity_score = max(0, 20 - distance * 0.9)
    environment_score = 10 if resource.get("type") != "drone" or not rejected else 4
    score = round(capability_score + battery_score + proximity_score + environment_score + 5, 1)
    if not rejected:
        reasons.extend(
            [
                "在线且当前空闲",
                f"满足 {len(requirements['capabilities'])} 项任务能力",
                f"距任务起点 {distance:.1f} 个场区单位",
            ]
        )
        if power is not None:
            reasons.append(f"预计任务后剩余 {battery_after}% 电量")
        if resource.get("type") == "drone":
            reasons.append(f"风速 {float(weather.get('wind_mps') or 0):.1f} m/s，允许飞行")
        elif float(requirements.get("max_slope_deg") or 0) >= 20:
            reasons.append(f"爬坡能力 {resource.get('max_slope_deg')}°，任务要求 {requirements.get('max_slope_deg')}°")
    return CandidateResult(not rejected, score, reasons, rejected, energy, battery_after)


def astar_grid(start: tuple[int, int], goal: tuple[int, int], blocked: set[tuple[int, int]] | None = None, terrain_cost=False) -> list[tuple[int, int]]:
    blocked = blocked or set()
    start = (max(0, min(100, int(start[0]))), max(0, min(100, int(start[1]))))
    goal = (max(0, min(100, int(goal[0]))), max(0, min(100, int(goal[1]))))
    if start in blocked or goal in blocked:
        raise ValueError("路线起点或检查点位于障碍区")
    frontier = [(0.0, start)]
    came_from = {start: None}
    cost = {start: 0.0}
    moves = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    while frontier:
        _, current = heappop(frontier)
        if current == goal:
            break
        for dx, dy in moves:
            nxt = (current[0] + dx, current[1] + dy)
            if not (0 <= nxt[0] <= 100 and 0 <= nxt[1] <= 100) or nxt in blocked:
                continue
            if dx and dy and ((current[0] + dx, current[1]) in blocked or (current[0], current[1] + dy) in blocked):
                continue
            step = 1.414 if dx and dy else 1.0
            if terrain_cost:
                from platform_app.services.terrain_service import traversal_cost
                step *= traversal_cost(*nxt)
            next_cost = cost[current] + step
            if nxt not in cost or next_cost < cost[nxt]:
                cost[nxt] = next_cost
                priority = next_cost + hypot(goal[0] - nxt[0], goal[1] - nxt[1])
                heappush(frontier, (priority, nxt))
                came_from[nxt] = current
    if goal not in came_from:
        raise ValueError("检查点之间没有可行路径")
    path = []
    current = goal
    while current is not None:
        path.append(current)
        current = came_from[current]
    path.reverse()
    return path


def _nearest_neighbor(start: tuple[int, int], waypoints: list[dict]) -> list[dict]:
    remaining = list(waypoints)
    ordered = []
    current = start
    while remaining:
        best = min(remaining, key=lambda point: hypot(point["x"] - current[0], point["y"] - current[1]))
        ordered.append(best)
        remaining.remove(best)
        current = (best["x"], best["y"])
    return ordered


def _blocked_cells(resource_type: str) -> set[tuple[int, int]]:
    blocked = set()
    if resource_type != "drone":
        from platform_app.services.terrain_service import terrain_at
        blocked.update((x,y) for x in range(101) for y in range(101) if terrain_at(x,y)['probability'] < .1)
        blocked.update((x, y) for x in range(70, 76) for y in range(65, 73))
        blocked.update((x, y) for x in range(63, 70) for y in range(35, 43))
    if resource_type == "robot":
        blocked.update((x, y) for x in range(34, 42) for y in range(50, 66))
    return blocked


ROAD_AXES = (20, 35, 50, 65, 80)


def elevation_m(x, y):
    """Fictional yard relief. The north apron is higher; the south and east fall toward the plain."""
    base = 34 + (40 - y) * 0.11 + (x - 70) * 0.045
    ridge = 4.5 * sin((x + 8) / 22) * cos((y + 6) / 30)
    return round(max(22.0, min(48.0, base + ridge)), 1)


def spatial_point(point, agl=0):
    x, y = point['x'], point['y']
    z = point.get('z', elevation_m(x, y) + agl)
    return {**point, 'z': round(z, 2), 'elevation_m': round(z, 2)}


def road_cells():
    return {(x, y) for x in range(10, 91) for y in range(10, 91) if x in ROAD_AXES or y in ROAD_AXES}


def plan_route(task: dict, resource: dict) -> dict:
    from platform_app.services.substation_site import plan_station_route
    return plan_station_route(task, resource)


def plan_legacy_route(task: dict, resource: dict) -> dict:
    route = task.get("route") or {}
    resource_start = resource.get("position") or {"x": 50, "y": 50}
    task_start = route.get("start") or {"x": 50, "y": 50}
    task_end = route.get("end") or task_start
    ordered = _nearest_neighbor((task_start["x"], task_start["y"]), route.get("waypoints") or [])
    stops = [resource_start, task_start, *ordered, task_end, resource_start]
    blocked = _blocked_cells(resource.get("type", "robot"))
    if resource.get("type") != "drone":
        accessible = road_cells() - blocked
        # Access lanes connect equipment and inspection points to the shared roads.
        for stop in stops:
            point = (int(stop["x"]), int(stop["y"]))
            junction = min(accessible, key=lambda cell: (hypot(cell[0]-point[0], cell[1]-point[1]), cell))
            accessible.update(astar_grid(point, junction, blocked))
        blocked = {(x, y) for x in range(101) for y in range(101)} - accessible
    path: list[tuple[int, int]] = []
    for left, right in zip(stops, stops[1:]):
        leg = astar_grid((left["x"], left["y"]), (right["x"], right["y"]), blocked, terrain_cost=resource.get('type')!='drone')
        path.extend(leg if not path else leg[1:])
    simplified = [path[0]] if path else []
    for index in range(1, len(path) - 1):
        previous = path[index - 1]
        current = path[index]
        following = path[index + 1]
        incoming = (current[0] - previous[0], current[1] - previous[1])
        outgoing = (following[0] - current[0], following[1] - current[1])
        if incoming != outgoing:
            simplified.append(current)
    if path and simplified[-1] != path[-1]:
        simplified.append(path[-1])
    length = sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
    from platform_app.services.xiasha_roads import road_path_for_stops
    road_path = road_path_for_stops(stops)
    spatial_path = [spatial_point({'x': x, 'y': y}) for x, y in simplified]
    if resource.get('type') == 'drone':
        # Terrain-following flight, with explicit takeoff and landing legs.
        spatial_path = [spatial_path[0], *[spatial_point({'x': x, 'y': y}, 60) for x,y in path], spatial_path[-1]]
    return {
        "algorithm": "最近邻检查点排序 + A* 场区路网寻路" if resource.get("type") != "drone" else "最近邻检查点排序 + A* 航线",
        "waypoint_order": [point.get("id", f"P{index + 1}") for index, point in enumerate(ordered)],
        "path": spatial_path,
        "road_path": road_path,
        "coordinate_system": "场区 XY 每单位 35 m，Z 为海拔 m",
        "flight_agl_m": 60 if resource.get('type') == 'drone' else 0,
        "elevation_range_m": [min(p['z'] for p in spatial_path), max(p['z'] for p in spatial_path)],
        "ascent_m": sum(max(0, b['z']-a['z']) for a,b in zip(spatial_path,spatial_path[1:])),
        "home": {"x": resource_start["x"], "y": resource_start["y"]},
        "path_cost": round(length, 1),
        "obstacle_cells": len(blocked),
    }


def _task_slice(task: dict, waypoints: list[dict], distance_m: float, gain: float) -> dict:
    route = dict(task.get("route") or {})
    route["waypoints"] = list(waypoints)
    route["distance_m"] = max(1, round(distance_m))
    route["elevation_gain_m"] = round(gain or 0, 1)
    return {**task, "route": route}


def _waived(result: CandidateResult, resource: dict) -> set[str]:
    waived = set()
    for reason in result.rejected_by:
        if reason == "设备类型与任务不匹配":
            waived.add(reason)
        elif resource.get("type") == "drone" and (
            reason.startswith("不支持") or reason in {"最大爬坡角不足", "所需通道宽度不足"}
        ):
            waived.add(reason)
        elif reason.startswith("电量不足") and result.battery_after_pct is not None and result.battery_after_pct >= 8:
            waived.add(reason)
    return waived


def _relief_ok(result: CandidateResult, resource: dict) -> bool:
    if result.accepted:
        return True
    waived = _waived(result, resource)
    return bool(result.rejected_by) and all(reason in waived for reason in result.rejected_by)


def propose_for_resource(task: dict, resource: dict, environment: dict) -> dict | None:
    """Route a resource on the site. Relief covers a platform switch or a return margin still at or above 8%."""

    def pack(result: CandidateResult, route: dict, remaining: list[dict]) -> dict:
        return {"resource": resource, "result": result, "route": route, "remaining": remaining, "full": not remaining}

    result = evaluate_candidate(task, resource, environment)
    if result.accepted or _relief_ok(result, resource):
        try:
            return pack(result, plan_route(task, resource), [])
        except ValueError:
            pass
    waypoints = list((task.get("route") or {}).get("waypoints") or [])
    for count in range(len(waypoints) - 1, 0, -1):
        try:
            route = plan_route(_task_slice(task, waypoints[:count], 1, 0), resource)
        except ValueError:
            continue
        trial = _task_slice(task, waypoints[:count], route["path_cost"] * 35, route.get("ascent_m") or 0)
        trial_result = evaluate_candidate(trial, resource, environment)
        if trial_result.accepted or _relief_ok(trial_result, resource):
            return pack(trial_result, route, waypoints[count:])
    return None


def field_resolution(task: dict, resource: dict, result: CandidateResult, remaining: list[dict]) -> str:
    requirements = _requirements(task)
    name = resource.get("name") or resource.get("id")
    terrain = requirements.get("terrain")
    width = requirements.get("min_width_m")
    if resource.get("type") == "drone" and terrain not in {None, "flat", "outdoor", "air"}:
        sentence = f"地面过不去。派出{name}，离地 60m 飞过"
    elif terrain == "stairs":
        sentence = f"楼梯轮式机器人过不去。派出{name}，可以走楼梯，爬坡 {resource.get('max_slope_deg')}°"
    elif terrain == "rough":
        sentence = f"碎石坡轮式机器人过不去。派出{name}，能走碎石坡，爬坡 {resource.get('max_slope_deg')}°"
    elif width is not None and resource.get("type") in {"dog", "person"} and float(width) < 0.9:
        sentence = f"通道只有 {width}m，轮式机器人过不去。派出{name}，通过宽度 {resource.get('min_width_m')}m"
    else:
        sentence = f"派出{name}，沿计划路线检查"
    if "gas" in set(requirements.get("capabilities") or []):
        sentence += "，带气体检测"
    elif "thermal" in set(requirements.get("capabilities") or []) and resource.get("type") == "drone":
        sentence += "，带热成像"
    if remaining:
        left = "、".join(str(point.get("id")) for point in remaining if point.get("id"))
        sentence += f"。电量不够走完，先覆盖能返回的路段，剩下 {left}"
    reserve = int(resource.get("reserve_pct") or 0)
    if result.battery_after_pct is not None and result.battery_after_pct < reserve:
        sentence += f"。返回后约剩 {result.battery_after_pct}%，低于常规余量 {reserve}%"
    return sentence


def explain_block(task: dict, resources: list[dict], environment: dict) -> str:
    capable = []
    for resource in resources:
        result = evaluate_candidate(task, resource, environment)
        hard = []
        for reason in result.rejected_by:
            if reason.startswith("电量不足") or reason in {"设备非空闲或不在线", "已分配给其他任务"}:
                continue
            if reason == "设备类型与任务不匹配":
                continue
            if resource.get("type") == "drone" and (reason.startswith("不支持") or reason in {"最大爬坡角不足", "所需通道宽度不足"}):
                continue
            hard.append(reason)
        if not hard:
            capable.append((resource, result))
    if not capable:
        return "没有设备同时具备所需能力并能通过这段地形"
    idle = [(resource, result) for resource, result in capable if "设备非空闲或不在线" not in result.rejected_by]
    if idle:
        resource, result = max(idle, key=lambda item: item[1].battery_after_pct if item[1].battery_after_pct is not None else -1)
        return f"{resource.get('name')} 能执行，但返回后约剩 {result.battery_after_pct}%，低于 8%，这次不派"
    waiting = [item for item in capable if item[0].get("status") == "待检修"] or capable
    resource = max(waiting, key=lambda item: item[0].get("power_percent") or 0)[0]
    return f"{resource.get('name')} 剩 {resource.get('power_percent')}% 且能执行，但当前是{resource.get('status')}，恢复后才能派"


def _pack_assignment(task, resource, result, route, resolution, coverage="full", remaining=None, probability=None):
    from platform_app.services.cost_service import plan_estimate
    estimate = plan_estimate(resource, route, result.estimated_energy_pct)
    risk = round(max(0, 100 - float(result.score or 0)) / 100, 3)
    quote = {"time_s": round(float(estimate["duration_seconds"])), "energy_kwh": round(float(estimate["energy_kwh"]), 3), "distance_m": round(float(estimate["distance_m"])), "risk": risk}
    quote["total_cost"] = round(quote["time_s"] / 60 + quote["energy_kwh"] * 18 + quote["distance_m"] / 1000 * 3 + quote["risk"] * 12, 2)
    row = {
        "task_id": task.get("id"),
        "task_name": task.get("name"),
        "resource_id": resource.get("id"),
        "resource_name": resource.get("name"),
        "resource_type": resource.get("type"),
        "accepted": True,
        "score": result.score,
        "reasons": [resolution, *getattr(result, "reasons", [])],
        "rejected_by": [],
        "estimated_energy_pct": result.estimated_energy_pct,
        "battery_after_pct": result.battery_after_pct,
        "resolution": resolution,
        "coverage": coverage,
        "task_type": task.get("type"),
        "requirements": _requirements(task),
        "route": route,
        "cost_estimate": estimate,
        "bid_quote": quote,
    }
    if probability is not None:
        row["selection_probability"] = round(probability, 4)
        row["network_reason"] = resolution
    if remaining:
        row["remaining_waypoints"] = [point.get("id") for point in remaining if point.get("id")]
    return row


def _urgent(task: dict) -> bool:
    return str(task.get("name") or "").startswith("紧急") or bool(task.get("interruption"))


def _standby_ids(resources: list[dict]) -> set[str]:
    grouped: dict[str, list[dict]] = {}
    for resource in resources:
        if resource.get("status") not in AVAILABLE_STATES:
            continue
        grouped.setdefault(resource.get("type"), []).append(resource)
    held = set()
    for kind, rows in grouped.items():
        rows.sort(key=lambda row: (-(row.get("power_percent") or 0), str(row.get("id"))))
        for row in rows[: STANDBY_PER_TYPE.get(kind, 2)]:
            held.add(row.get("id"))
    return held


def _restore_standby(assignments: list[dict], resources: list[dict]) -> None:
    used = {row["resource_id"] for row in assignments}

    def idle(kind: str) -> int:
        return sum(1 for row in resources if row.get("type") == kind and row.get("status") in AVAILABLE_STATES and row.get("id") not in used)

    for kind, need in STANDBY_PER_TYPE.items():
        while idle(kind) < need:
            victim = next(
                (
                    row
                    for row in reversed(assignments)
                    if row.get("resource_type") == kind
                    and not _urgent({"name": row.get("task_name")})
                    and sum(1 for other in assignments if other.get("task_id") == row.get("task_id")) > 1
                ),
                None,
            )
            if victim is None:
                break
            assignments.remove(victim)
            used.discard(victim["resource_id"])


def build_v1_plan(tasks: list[dict], resources: list[dict], environment: dict) -> dict:
    from platform_app.services.neural_dispatch import combination_policy, score_candidates, team_reason

    pending = [task for task in tasks if task.get("status") in {"待调度", "待派发"}]
    pending.sort(key=lambda task: (0 if _urgent(task) else 1, str(task.get("id"))))
    reserve = _standby_ids(resources)
    used_resources = set()
    assignments = []
    audit = []
    schemes = []
    policies = []
    for task in pending:
        scored = score_candidates(task, resources, environment, used_resources)
        for item in scored:
            result = item["result"]
            audit.append({
                "task_id": task.get("id"),
                "task_name": task.get("name"),
                "resource_id": item["resource"].get("id"),
                "resource_name": item["resource"].get("name"),
                "resource_type": item["resource"].get("type"),
                "accepted": not item["hard_blocked"] and item["probability"] >= 0.8 and item["resource"].get("id") not in used_resources,
                "score": result.score,
                "reasons": result.reasons,
                "rejected_by": result.rejected_by + item["hard_blocked"],
                "estimated_energy_pct": result.estimated_energy_pct,
                "battery_after_pct": result.battery_after_pct,
                "selection_probability": round(item["probability"], 4),
                "policy_rank": round(item["rank"], 4),
                "constraint_mask": item["mask"],
                "policy_source": item["policy_source"],
            })
        blocked_ids = set(used_resources) if _urgent(task) else set(used_resources) | reserve
        policy = combination_policy(task, resources, environment, blocked_ids)
        team = policy["rows"]
        fallback = False
        if not team and reserve - used_resources:
            policy = combination_policy(task, resources, environment, used_resources)
            team = policy["rows"]
            fallback = bool(team)
        public = policy["public"]
        public["fallback"] = fallback
        policies.append(public)
        for scheme in policy["schemes"]:
            schemes.append(scheme)
        placed = []
        for item in team:
            try:
                route = plan_route(task, item["resource"])
            except ValueError as exc:
                item["hard_blocked"].append(str(exc))
                continue
            placed.append((item, route))
        if placed:
            names = "、".join(item["resource"].get("name") or item["resource"].get("id") for item, _route in placed)
            head = policy.get("selected_head") or "组合"
            sentence = f"兜底派出 {names}" if fallback else f"三头打分取「{head}」组合。" + team_reason([item for item, _route in placed], environment)
            for item, route in placed:
                assignments.append(_pack_assignment(task, item["resource"], item["result"], route, sentence, probability=item["probability"]))
                used_resources.add(item["resource"].get("id"))
            continue
        options = []
        for resource in resources:
            if resource.get("id") in used_resources:
                continue
            proposal = propose_for_resource(task, resource, environment)
            if proposal:
                options.append(proposal)
        if not options:
            continue
        proposal = max(
            options,
            key=lambda item: (
                item["full"],
                item["result"].battery_after_pct if item["result"].battery_after_pct is not None else 100,
                item["result"].score,
            ),
        )
        resource = proposal["resource"]
        result = proposal["result"]
        route = proposal["route"]
        sentence = field_resolution(task, resource, result, proposal["remaining"])
        assignments.append(_pack_assignment(task, resource, result, route, "兜底派出 " + sentence, "full" if proposal["full"] else "partial", proposal["remaining"]))
        used_resources.add(resource.get("id"))
    _restore_standby(assignments, resources)
    used_resources = {row["resource_id"] for row in assignments}
    assigned_ids = {row["task_id"] for row in assignments}
    blocked = []
    for task in pending:
        if task.get("id") in assigned_ids:
            continue
        blocked.append({"task_id": task.get("id"), "task_name": task.get("name"), "summary": explain_block(task, resources, environment)})
    from platform_app.services.substation_site import CENTER_LAT, CENTER_LON, METERS_PER_UNIT, site_geometry
    return {
        "version": "V1",
        "algorithm": "硬约束过滤 → 三头 logits（能力 / 续航 / 现场）→ 组合打分派出 → A* 路径规划",
        "environment": environment,
        "map_frame": {'center_lat':CENTER_LAT,'center_lon':CENTER_LON,'meters_per_unit':METERS_PER_UNIT,'site':site_geometry()},
        "assignments": assignments,
        "policies": policies,
        "schemes": schemes,
        "standby": [
            {"id": row.get("id"), "name": row.get("name"), "type": row.get("type")}
            for row in resources
            if row.get("status") in AVAILABLE_STATES and row.get("id") not in used_resources
        ],
        "blocked": blocked,
        "unassigned_task_ids": [task.get("id") for task in pending if task.get("id") not in {row["task_id"] for row in assignments}],
        "audit": audit,
    }
