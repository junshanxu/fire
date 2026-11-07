"""Constraint-masked policy scorer for simulated dispatch.

The small network below has fixed demonstration weights: it is deliberately
labelled as a policy score, not a trained RL model.  Feasibility is decided
first by the rule layer; the policy can only rank feasible candidates.  This
keeps the same action-mask contract needed by a future trained DCMRTA policy.
"""

from __future__ import annotations

from math import exp

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
        # D200 is the switch-operation unit. Routine camera and gas rounds use the inspection robots first.
        if rank and resource.get("type") == "robot" and "D200" in vendor and caps & {"thermal", "gas", "rgb_camera", "aerial_camera"}:
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


def choose_team(task: dict, resources: list[dict], environment: dict, used_ids: set[str] | None = None, floor: float = SUPPORT_FLOOR) -> list[dict]:
    ranked = [row for row in score_candidates(task, resources, environment, used_ids) if not row["hard_blocked"]]
    ranked.sort(key=lambda row: (-row["rank"], -row["probability"], str(row["resource"].get("id"))))
    primary = [row for row in ranked if row["probability"] >= THRESHOLD]
    limit = crew_size(task, environment)
    picked = []
    seen_types = set()
    for row in primary:
        kind = row["resource"].get("type")
        if kind in seen_types:
            continue
        picked.append(row)
        seen_types.add(kind)
        if len(picked) >= limit:
            return picked
    for row in primary:
        if row in picked:
            continue
        picked.append(row)
        if len(picked) >= limit:
            return picked
    for row in ranked:
        if row in picked or row["probability"] < floor:
            continue
        picked.append(row)
        if len(picked) >= limit:
            break
    if not picked and task.get("type") == "drone":
        for row in ranked:
            if row["resource"].get("type") == "drone" and (row["resource"].get("power_percent") or 0) >= 45:
                picked.append(row)
                break
    return picked


def suggest_schemes(task: dict, resources: list[dict], environment: dict, used_ids: set[str] | None = None, limit: int = 3) -> list[dict]:
    """Highest-scoring distinct crews for one task. The first crew is the one to send."""
    taken = set(used_ids or [])
    schemes = []
    floors = (SUPPORT_FLOOR, 0.45, 0.35)
    for index in range(limit):
        team = choose_team(task, resources, environment, taken, floors[min(index, len(floors) - 1)])
        if not team:
            break
        score = round(sum(row["rank"] for row in team) / len(team) * 100, 1)
        schemes.append(
            {
                "score": score,
                "members": [
                    {
                        "id": row["resource"].get("id"),
                        "name": row["resource"].get("name"),
                        "type": row["resource"].get("type"),
                        "score": round(row["rank"] * 100, 1),
                    }
                    for row in team
                ],
            }
        )
        taken.update(row["resource"].get("id") for row in team)
    schemes.sort(key=lambda item: (-item["score"], -len(item["members"])))
    return schemes


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
