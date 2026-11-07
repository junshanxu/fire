"""Deterministic simulation telemetry with published ZJ Humanoid ROS topic names."""

from __future__ import annotations

import re
import random
import time
from platform_app.services.planning_service import elevation_m
from platform_app.services.cost_service import CAPACITY_KWH


TYPE_PROFILES = {
    "person": {
        "capabilities": ["manual_inspection", "rgb_camera"],
        "terrain": ["flat", "stairs", "rough", "narrow"],
        "max_slope_deg": 35,
        "min_width_m": 0.5,
        "speed_mps": 1.2,
        "reserve_pct": 0,
    },
    "robot": {
        "capabilities": ["rgb_camera", "thermal", "gas", "lidar"],
        "terrain": ["flat", "indoor"],
        "max_slope_deg": 12,
        "min_width_m": 0.9,
        "speed_mps": 1.2,
        "reserve_pct": 20,
    },
    "dog": {
        "capabilities": ["rgb_camera", "thermal", "gas", "lidar"],
        "terrain": ["flat", "stairs", "rough", "narrow"],
        "max_slope_deg": 35,
        "min_width_m": 0.65,
        "speed_mps": 1.4,
        "reserve_pct": 20,
    },
    "drone": {
        "capabilities": ["rgb_camera", "thermal", "aerial_camera"],
        "terrain": ["air", "outdoor"],
        "max_slope_deg": 90,
        "min_width_m": 0,
        "speed_mps": 6.0,
        "reserve_pct": 25,
    },
}


POSITION_SEEDS = {
    "person": [(44, 54), (47, 57), (53, 56), (56, 53), (43, 48), (50, 51), (41, 51)],
    "robot": [(42, 45), (46, 43), (51, 44), (55, 46), (58, 43)],
    "dog": [(40, 50), (44, 48), (52, 49), (57, 51), (60, 48)],
    "drone": [(45, 59), (49, 61), (54, 60), (58, 57), (61, 61)],
}

# One random but stable layout per server process: a refresh does not make a
# moving device teleport, while the next demo/restart gets a different legal
# starting arrangement.  All candidates below lie on the station graph.
_SCENARIO_SEED = random.SystemRandom().randint(0, 2**31 - 1)
_BOOT = time.monotonic()
# Standby units stay at the gate, muster point, or charging apron.
# Inspection roads are only for units that have actually been dispatched.
_POSITION_POOLS = {
    'person': [(95, 33), (93, 33), (91, 33), (89, 33), (86, 33), (84, 33), (82, 33)],
    'robot': [(46, 25), (70, 25), (46, 28), (70, 28), (46, 31), (70, 31), (48, 28)],
    'dog': [(40, 33), (44, 33), (50, 33), (55, 33), (60, 33), (66, 33), (74, 33)],
    'drone': [(42, 25), (44, 25), (48, 25), (66, 25), (68, 25), (72, 25), (74, 25)],
}


TELEMETRY_CONTRACT = {
    "soc": "/zj_humanoid/chassis/charge_state",
    "odom": "/zj_humanoid/chassis/odom_info",
    "state": "/zj_humanoid/chassis/agv_state",
    "motor": "/zj_humanoid/chassis/motor_info",
    "navigation": "/zj_humanoid/navigation/navigation_status",
    "mode": "仿真遥测 · ROS1 接口参考",
    "reference": "ZJ-Humanoid Navi02 ROS1 SDK",
}


def parse_power(value) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return max(0, min(100, int(match.group()))) if match else None


def enrich_resources(resources: list[dict]) -> list[dict]:
    enriched = []
    for item in resources:
        row = dict(item)
        resource_type = row.get("type", "person")
        profile = TYPE_PROFILES.get(resource_type, TYPE_PROFILES["person"])
        match = re.search(r"(\d+)$", str(row.get("id", "")))
        index = max(0, (int(match.group()) - 1) if match else 0)
        positions = POSITION_SEEDS.get(resource_type, POSITION_SEEDS["person"])
        # All initial ground poses lie on the same vector navigation network.
        x, y = _POSITION_POOLS.get(resource_type, [(46,25)])[index % 7]
        power = parse_power(row.get("power"))
        if power is not None:
            # Small telemetry noise, bounded so a resource does not become
            # infeasible solely because a dashboard refreshed.
            power=max(0,min(100,power+random.Random(f'{_SCENARIO_SEED}:{row.get("id")}').randint(-2,2)))
        ground = elevation_m(x, y)
        clearance = 0
        row.update(
            {
                "power_percent": power,
                "battery_applicable": power is not None,
                "battery_capacity_kwh": CAPACITY_KWH.get(resource_type,0),
                "position": {"x": x, "y": y, "z": ground + clearance},
                "ground_elevation_m": ground,
                "altitude_agl_m": clearance,
                "capabilities": list(profile["capabilities"]),
                "terrain": list(profile["terrain"]),
                "max_slope_deg": profile["max_slope_deg"],
                "min_width_m": profile["min_width_m"],
                "speed_mps": profile["speed_mps"],
                "simulation_speed_multiplier": 12,
                "reserve_pct": profile["reserve_pct"],
                "signal_percent": max(58, 96 - index * 7),
                "last_seen_seconds": 3 + index * 2,
                "telemetry_state": "在线" if row.get("status") != "离线" else "断连",
            }
        )
        if row.get("status") == "充电中" and row.get("power_percent") is not None:
            row["power_percent"] = min(96, row["power_percent"] + int((time.monotonic() - _BOOT) / 30))
        if row.get("power_percent") is not None:
            row["power"] = f"{round(row['power_percent'])}%"
        if row.get("status") == "离线":
            row["signal_percent"] = 0
            row["last_seen_seconds"] = 18 * 60
            row["telemetry_state"] = "断连"
        elif row.get("status") == "检修":
            row["telemetry_state"] = "检修"
        enriched.append(row)
    return enriched
