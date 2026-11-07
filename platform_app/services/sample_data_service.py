import json

from platform_app.config import ENVIRONMENT_FILE, SAMPLE_DATA_DIR
from platform_app.services.telemetry_service import TELEMETRY_CONTRACT, enrich_resources


def read_sample_file(name: str) -> list[dict]:
    path = SAMPLE_DATA_DIR / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.name} 格式错误，请检查 sample_data 文件") from exc
    if not isinstance(value, list):
        raise RuntimeError(f"{path.name} 顶层必须是 JSON 数组")
    return value


def list_sample_tasks() -> list[dict]:
    from platform_app.services.substation_site import sample_tasks
    return sample_tasks()


def list_legacy_sample_tasks() -> list[dict]:
    from platform_app.models.task import Task

    routes = {row.get("route_id"): row for row in read_sample_file("routes.json")}
    tasks = [Task.from_record(row).to_api() for row in read_sample_file("tasks.json")]
    for task in tasks:
        task["route"] = routes.get(task.get("route_id"))
    return tasks


def get_overview() -> dict:
    from platform_app.services.terrain_service import TERRAIN_TYPES
    from platform_app.services.simulation_service import event_history
    from platform_app.services.dispatch_service import recent_incidents, resources_with_dispatches, list_dispatches

    resources = enrich_resources(read_sample_file("resources.json"))
    try:
        environment = json.loads(ENVIRONMENT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        environment = {"weather": {"condition": "多云", "wind_mps": 3.2, "precipitation_mm": 0, "visibility_km": 18}, "flight_allowed": True}
    return {
        "stations": read_sample_file("stations.json"),
        "resources": resources_with_dispatches(resources),
        "alarms": read_sample_file("alarms.json"),
        "environment": environment,
        "telemetry_contract": TELEMETRY_CONTRACT,
        "incidents": recent_incidents(),
        "route_reservations": [{"task_id":row.get("task_id"),"resource_name":row.get("resource_name"),"segments":len(row.get("reserved_road_segments") or []),"state":row.get("reservation_state","—"),"reauction_state":row.get("reauction_state")} for row in list_dispatches()[:12]],
        "simulation_events": event_history(),
        "terrain_predictions": TERRAIN_TYPES,
    }
