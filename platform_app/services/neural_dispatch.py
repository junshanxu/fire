"""Constraint-masked policy scorer for simulated dispatch.

The small network below has fixed demonstration weights: it is deliberately
labelled as a policy score, not a trained RL model.  Feasibility is decided
first by the rule layer; the policy can only rank feasible candidates.  Each
task then gets three logit heads (能力, 续航, 现场).  Each head proposes one
device combination, and the combination with the highest joint logit is sent.
"""

from __future__ import annotations

import json
from math import exp, hypot

from platform_app.services.planning_service import evaluate_candidate


# wind, precip, flight_allowed, battery, idle, capability, terrain, type_match,
# drone, drone_wind, drone_precip
FEATURE_NAMES = (
    "wind",
    "precip",
    "flight_allowed",
    "battery",
    "idle",
    "capability",
    "terrain",
    "type_match",
    "drone",
    "drone_wind",
    "drone_precip",
)

# Two-layer example: hidden readiness, weather, passage, and battery.
HIDDEN_WEIGHTS = (
    (0.0, 0.0, 0.0, 2.4, 0.8, 1.6, 3.4, 1.2, 0.0, 0.0, 0.0),
    (-0.3, 0.0, 1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -11.0, -9.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 1.8, 4.4, 1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 14.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
)
HIDDEN_BIAS = (-5.2, 2.2, -4.0, -11.2)
OUTPUT_WEIGHTS = (1.8, 1.6, 2.6, 3.4)
OUTPUT_BIAS = -6.15
THRESHOLD = 0.80
SUPPORT_FLOOR = 0.60
MAX_TEAM = 4
# Three dispatch heads. Each emits one logit per feasible device.
# 能力: type and sensor fit. 续航: battery left after the route. 现场: wind, rain, terrain.
HEADS = ("能力", "续航", "现场")
# Feature order: FEATURE_NAMES, then margin, proximity, dog, robot, signal, switchgear, ios.
HEAD_WEIGHTS = (
    (0.0, 0.0, 0.1, 0.0, 0.15, 2.5, 1.4, 2.0, 0.1, -0.15, -0.15, 0.2, 0.0, 0.35, 1.15, 1.1, -2.4, 1.15),
    (0.0, 0.0, 0.1, 3.1, 0.45, 0.15, 0.1, 0.15, 0.0, -0.1, -0.1, 2.4, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0),
    (-1.2, -1.4, 1.0, 0.15, 0.1, 0.1, 0.6, 0.1, -0.15, -2.2, -2.4, 0.1, 2.8, 0.4, 0.05, 1.35, -0.15, -0.75),
)
HEAD_BIAS = (-1.15, -2.35, -0.85)


def feasibility_mask(resource: dict, result, used_ids: set[str] | None = None) -> dict[str, bool]:
    """Return named hard constraints; True means the action is unavailable.

    A robot task may be served by a four-legged unit in this simulator. All
    other evaluation rejections are hard constraints and must have zero
    selection probability.
    """
    used_ids = used_ids or set()
    rejected = set(result.rejected_by)
    dog_substitution = resource.get("type") == "dog" and rejected == {"设备类型与任务不匹配"}
    return {
        "busy_or_offline": "设备非空闲或不在线" in rejected,
        "already_reserved": resource.get("id") in used_ids,
        "wrong_station": "设备不在任务场站" in rejected,
        "type": "设备类型与任务不匹配" in rejected and not dog_substitution,
        "capability": any(reason.startswith("缺少能力") for reason in rejected),
        "terrain": any(reason.startswith("不支持") or reason in {"最大爬坡角不足", "所需通道宽度不足"} for reason in rejected),
        "weather_or_airspace": any(reason.startswith(prefix) for reason in rejected for prefix in ("风速", "降水", "当前空域")),
        "energy_return_reserve": any(reason.startswith("电量不足") for reason in rejected),
    }


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponent = exp(-value)
        return 1.0 / (1.0 + exponent)
    exponent = exp(value)
    return exponent / (1.0 + exponent)


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def feature_vector(task: dict, resource: dict, environment: dict, result) -> list[float]:
    weather = (environment or {}).get("weather") or {}
    wind = _clip(float(weather.get("wind_mps") or 0) / 12)
    precip = _clip(float(weather.get("precipitation_mm") or 0) / 5)
    flight = 1.0 if (environment or {}).get("flight_allowed", True) else 0.0
    power = resource.get("power_percent")
    battery = 1.0 if power is None else _clip(float(power) / 100)
    idle = 1.0 if resource.get("status") in {"待命", "在线"} else 0.0
    rejected = list(result.rejected_by)
    capability = 0.0 if any(reason.startswith("缺少能力") for reason in rejected) else 1.0
    terrain_blocked = any(reason.startswith("不支持") or reason in {"最大爬坡角不足", "所需通道宽度不足"} for reason in rejected)
    terrain = 0.0 if terrain_blocked else 1.0
    type_match = 0.0 if "设备类型与任务不匹配" in rejected else 1.0
    drone = 1.0 if resource.get("type") == "drone" else 0.0
    return [wind, precip, flight, battery, idle, capability, terrain, type_match, drone, drone * wind, drone * precip]


def forward(features: list[float]) -> float:
    hidden = []
    for weights, bias in zip(HIDDEN_WEIGHTS, HIDDEN_BIAS):
        total = bias + sum(weight * value for weight, value in zip(weights, features))
        hidden.append(_sigmoid(total))
    logit = OUTPUT_BIAS + sum(weight * value for weight, value in zip(OUTPUT_WEIGHTS, hidden))
    return _sigmoid(logit)


def hard_reasons(resource: dict, result, used_ids: set[str] | None = None) -> list[str]:
    mask = feasibility_mask(resource, result, used_ids)
    labels = {
        "busy_or_offline": "设备非空闲或不在线",
        "already_reserved": "已分配给其他任务",
        "wrong_station": "设备不在任务场站",
        "type": "设备类型与任务不匹配",
        "capability": next((x for x in result.rejected_by if x.startswith("缺少能力")), "缺少任务能力"),
        "terrain": next((x for x in result.rejected_by if x.startswith("不支持") or x in {"最大爬坡角不足", "所需通道宽度不足"}), "地形不可通行"),
        "weather_or_airspace": next((x for x in result.rejected_by if x.startswith(("风速", "降水", "当前空域"))), "天气或空域不可用"),
        "energy_return_reserve": next((x for x in result.rejected_by if x.startswith("电量不足")), "返场电量不足"),
    }
    return [labels[key] for key, blocked in mask.items() if blocked]


def score_candidates(task: dict, resources: list[dict], environment: dict, used_ids: set[str] | None = None) -> list[dict]:
    used_ids = used_ids or set()
    scored = []
    for resource in resources:
        result = evaluate_candidate(task, resource, environment)
        mask = feasibility_mask(resource, result, used_ids)
        blocked = hard_reasons(resource, result, used_ids)
        features = feature_vector(task, resource, environment, result)
        probability = 0.0 if blocked else forward(features)
        # The fixed policy ranks only feasible actions; the explicit score
        # keeps route proximity and post-task battery visible to operators.
        priority = min(1.0, max(0.0, float(task.get("priority") or 0) / 5))
        rank = 0.0 if blocked else round(0.62 * probability + 0.33 * (float(result.score) / 100) + 0.05 * priority, 6)
        vendor = str(resource.get("vendor") or "")
        caps = set((task.get("requirements") or {}).get("capabilities") or [])
        # 开关室操作机器人负责操作，例行表计、测温和气体巡检优先派室外轮式巡检机器人。
        if rank and resource.get("type") == "robot" and "开关室操作" in vendor and caps & {"thermal", "gas", "rgb_camera", "aerial_camera"}:
            rank = round(rank * 0.9, 6)
        scored.append(
            {
                "resource": resource,
                "result": result,
                "probability": probability,
                "hard_blocked": blocked,
                "mask": mask,
                "features": features,
                "policy_source": "fixed_policy_demo",
                "rank": rank,
            }
        )
    return scored


def crew_size(task: dict, environment: dict) -> int:
    """How many devices this task needs, from its own conditions."""
    requirements = task.get("requirements") or {}
    waypoints = (task.get("route") or {}).get("waypoints") or []
    urgent = str(task.get("name") or "").startswith("紧急") or bool(task.get("interruption"))
    terrain = requirements.get("terrain") or "flat"
    if task.get("type") == "drone":
        # One aircraft flies a sortie. The ground crew does not launch a second airframe for the same line.
        return 1
    if task.get("type") == "team":
        # Substation rounds go out in pairs. A third person joins only for an urgent sweep.
        return 3 if urgent else 2
    # A road inspection is a pair. A third unit joins for a long route, stairs, or an urgent multi-point job.
    size = 2 if len(waypoints) >= 2 or urgent else 1
    if terrain in {"stairs", "rough"}:
        size = 3
    return min(size, MAX_TEAM)


# margin, proximity, dog, robot, signal, switchgear, ios
HEAD_EXTRA = ("margin", "proximity", "dog", "robot", "signal", "switchgear", "ios")
_HEAD_WIDTH = len(FEATURE_NAMES) + len(HEAD_EXTRA)


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    peak = max(values)
    lifted = [exp(value - peak) for value in values]
    total = sum(lifted) or 1.0
    return [item / total for item in lifted]


def _task_anchor(task: dict) -> tuple[float, float]:
    route = task.get("route") or {}
    points = route.get("waypoints") or []
    if points:
        return (
            sum(float(point.get("x") or 0) for point in points) / len(points),
            sum(float(point.get("y") or 0) for point in points) / len(points),
        )
    start = route.get("start") or {}
    return float(start.get("x") or 50), float(start.get("y") or 50)


def head_features(task: dict, resource: dict, result, base: list[float]) -> list[float]:
    """Per-device input for the three dispatch heads."""
    power_after = result.battery_after_pct
    margin = 0.82 if power_after is None else _clip((float(power_after) + 15) / 100)
    anchor_x, anchor_y = _task_anchor(task)
    position = resource.get("position") or {}
    distance = hypot(float(position.get("x", 50)) - anchor_x, float(position.get("y", 50)) - anchor_y)
    proximity = _clip(1 - distance / 90)
    kind = resource.get("type")
    vendor = str(resource.get("vendor") or "")
    required = set((task.get("requirements") or {}).get("capabilities") or [])
    outdoor_job = task.get("type") != "drone" and bool(required & {"thermal", "gas", "rgb_camera", "aerial_camera"})
    switchgear = 1.0 if outdoor_job and "开关室操作" in vendor else 0.0
    signal = _clip(float(resource.get("signal_percent") or 0) / 100)
    ios = 1.0 if str(resource.get("protocol") or "") == "iOS" else 0.0
    return [
        *base,
        margin,
        proximity,
        1.0 if kind == "dog" else 0.0,
        1.0 if kind == "robot" else 0.0,
        signal,
        switchgear,
        ios,
    ]


def head_logits(features: list[float]) -> list[float]:
    logits = []
    for weights, bias in zip(HEAD_WEIGHTS, HEAD_BIAS):
        logits.append(round(bias + sum(weight * value for weight, value in zip(weights, features)), 4))
    return logits


def _pick_crew(ordered: list[dict], size: int) -> list[dict]:
    picked = []
    seen_types = set()
    for row in ordered:
        kind = row["resource"].get("type")
        if kind in seen_types:
            continue
        picked.append(row)
        seen_types.add(kind)
        if len(picked) >= size:
            return picked
    for row in ordered:
        if row in picked:
            continue
        picked.append(row)
        if len(picked) >= size:
            break
    return picked


def _member_public(row: dict) -> dict:
    resource = row["resource"]
    return {
        "id": resource.get("id"),
        "name": resource.get("name"),
        "type": resource.get("type"),
        "logits": list(row["logits"]),
    }


def combination_policy(task: dict, resources: list[dict], environment: dict, used_ids: set[str] | None = None) -> dict:
    """Score one task with three logit heads and choose a device combination.

    Hard-blocked devices stay at zero and cannot enter a combination.  Each
    head ranks the feasible devices and proposes one crew.  The crew whose
    members have the highest sum of all three logits is the one to send.
    """
    from platform_app.services.planning_service import plan_route

    feasible = []
    for row in score_candidates(task, resources, environment, used_ids):
        if row["hard_blocked"]:
            continue
        try:
            plan_route(task, row["resource"])
        except ValueError as exc:
            row["hard_blocked"].append(str(exc))
            continue
        features = head_features(task, row["resource"], row["result"], row["features"])
        if len(features) != _HEAD_WIDTH:
            raise RuntimeError("调度头输入宽度与权重不一致")
        row["logits"] = head_logits(features)
        feasible.append(row)
    size = crew_size(task, environment)
    by_head = []
    for index, name in enumerate(HEADS):
        ordered = sorted(feasible, key=lambda row: (-row["logits"][index], str(row["resource"].get("id"))))
        by_head.append(_pick_crew(ordered, size))
    probabilities = list(zip(*(_softmax([row["logits"][index] for row in feasible]) for index in range(len(HEADS))))) if feasible else []
    for row, probs in zip(feasible, probabilities):
        row["head_probs"] = [round(value, 4) for value in probs]
    combinations = []
    for name, members in zip(HEADS, by_head):
        head_index = HEADS.index(name)
        head_logit = round(sum(row["logits"][head_index] for row in members), 4) if members else None
        joint = round(sum(sum(row["logits"]) for row in members), 4) if members else None
        combinations.append(
            {
                "head": name,
                "logit": head_logit,
                "joint": joint,
                "selected": False,
                "members": [_member_public(row) for row in members],
                "_rows": members,
            }
        )
    chosen = None
    chosen_key = None
    for combo in combinations:
        if combo["joint"] is None:
            continue
        key = (combo["joint"], -HEADS.index(combo["head"]))
        if chosen_key is None or key > chosen_key:
            chosen_key = key
            chosen = combo
    if chosen is not None:
        chosen["selected"] = True
    ranked_devices = sorted(feasible, key=lambda row: (-sum(row["logits"]), str(row["resource"].get("id"))))
    visible = []
    seen_ids = set()
    for row in list(chosen["_rows"] if chosen else []) + ranked_devices:
        identity = row["resource"].get("id")
        if identity in seen_ids:
            continue
        seen_ids.add(identity)
        visible.append(row)
        if len(visible) >= 6:
            break
    public_combinations = []
    schemes = []
    for combo in combinations:
        item = {key: value for key, value in combo.items() if key != "_rows"}
        public_combinations.append(item)
        schemes.append(
            {
                "task_id": task.get("id"),
                "task_name": task.get("name"),
                "head": combo["head"],
                "score": combo["joint"],
                "selected": combo["selected"],
                "members": combo["members"],
            }
        )
    return {
        "rows": list(chosen["_rows"]) if chosen else [],
        "selected_head": chosen["head"] if chosen else None,
        "schemes": schemes,
        "public": {
            "task_id": task.get("id"),
            "task_name": task.get("name"),
            "selected_head": chosen["head"] if chosen else None,
            "fallback": False,
            "heads": list(HEADS),
            "combinations": public_combinations,
            "devices": [
                {
                    "id": row["resource"].get("id"),
                    "name": row["resource"].get("name"),
                    "type": row["resource"].get("type"),
                    "logits": list(row["logits"]),
                    "probs": list(row.get("head_probs") or []),
                }
                for row in visible
            ],
        },
    }


def load_policies() -> list[dict]:
    path = _policy_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def replace_policies(policies: list[dict]) -> None:
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(policies), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_policies(policies: list[dict]) -> None:
    by_id = {row.get("task_id"): row for row in load_policies() if row.get("task_id")}
    for row in policies:
        if row.get("task_id"):
            by_id[row["task_id"]] = row
    replace_policies(list(by_id.values()))


def _policy_path():
    from platform_app.config import DATA_DIR

    return DATA_DIR / "dispatch_policies.json"


def choose_team(task: dict, resources: list[dict], environment: dict, used_ids: set[str] | None = None, floor: float = SUPPORT_FLOOR) -> list[dict]:
    del floor
    return combination_policy(task, resources, environment, used_ids)["rows"]


def suggest_schemes(task: dict, resources: list[dict], environment: dict, used_ids: set[str] | None = None, limit: int = 3) -> list[dict]:
    """Three head-level crews for one task. The selected crew is the one to send."""
    del limit
    return combination_policy(task, resources, environment, used_ids)["schemes"]


def team_reason(picks: list[dict], environment: dict) -> str:
    weather = (environment or {}).get("weather") or {}
    wind = float(weather.get("wind_mps") or 0)
    precip = float(weather.get("precipitation_mm") or 0)
    flight = "允许飞行" if (environment or {}).get("flight_allowed", True) else "禁止飞行"
    names = "、".join(f"{row['resource'].get('name')}（{row['probability'] * 100:.0f}%）" for row in picks)
    terrain_note = "地形和通道过得去" if all(row["features"][6] >= 1 for row in picks) else "部分设备地形受限，只留下过得去的"
    battery_note = "电量更高的优先"
    if any(row["resource"].get("type") == "drone" for row in picks) and wind >= 3:
        battery_note = "有风，只留下电量足够的无人机"
    elif len(picks) == 1:
        battery_note = "现场只留得下一台"
    elif len({row["resource"].get("type") for row in picks}) == 1 and len(picks) > 1:
        battery_note = "同一类里再补能上去的"
    return f"调度判断：风速 {wind:.1f} m/s，降水 {precip:.0f} mm，{flight}。{terrain_note}，{battery_note}。出任 {names}。"
