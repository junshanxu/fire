import json
from xml.etree import ElementTree as ET

from platform_app.services.task_service import create_task, list_tasks
from platform_app.services.sample_data_service import get_overview
from platform_app.services.dispatch_service import create_dispatch, dispatch_state, list_dispatches
from platform_app.services.feedback_service import create_feedback, list_feedback, operation_feed
from platform_app.services.planning_service import build_v1_plan
from platform_app.services.network_source_service import network_sources


def handle_tasks(method: str, body: bytes = b"") -> tuple[int, dict | list]:
    if method == "GET":
        return 200, list_tasks()
    if method != "POST":
        return 405, {"error": "Method not allowed"}
    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            return 400, {"error": "请求内容必须是 JSON 对象"}
        return 201, create_task(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"error": "请求不是有效的 JSON"}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except RuntimeError as exc:
        return 500, {"error": str(exc)}


def handle_overview() -> tuple[int, dict]:
    try:
        return 200, get_overview()
    except RuntimeError as exc:
        return 500, {"error": str(exc)}


def handle_planning() -> tuple[int, dict]:
    try:
        overview = get_overview()
        tasks = list_tasks()
        plan = build_v1_plan(tasks, overview.get("resources", []), overview.get("environment", {}))
        resource_by_id = {row.get("id"): row for row in overview.get("resources", [])}
        live = []
        recent = []
        completed_tasks = set()
        for dispatch in list_dispatches():
            route = dispatch.get("planned_route")
            state = dispatch_state(dispatch)
            if not route or state not in {"执行中", "已派发", "返厂中", "充电中", "已完成"}:
                continue
            resource = resource_by_id.get(dispatch.get("resource_id"), {})
            entry = {
                "task_id": dispatch.get("task_id"),
                "task_name": dispatch.get("task_name"),
                "resource_id": dispatch.get("resource_id"),
                "resource_name": dispatch.get("resource_name"),
                "resource_type": dispatch.get("resource_type") or resource.get("type"),
                "accepted": True,
                "route": route,
                "bid_quote": dispatch.get("bid_quote"),
                "resolution": dispatch.get("resolution", "执行中的既定路线"),
                "state": state,
            }
            if state == "已完成":
                task_id = dispatch.get("task_id")
                if task_id not in completed_tasks:
                    recent.append(entry)
                    completed_tasks.add(task_id)
            else:
                live.append(entry)
        # Keep a small completed-route trail visible after a simulated task ends;
        # this prevents the spatial scene from appearing empty between demo rounds.
        plan["assignments"] = live + recent[:5] + plan.get("assignments", [])
        plan["live_assignments"] = len(live)
        return 200, plan
    except RuntimeError as exc:
        return 500, {"error": str(exc)}


def handle_network_sources() -> tuple[int, list[dict] | dict]:
    try:
        return 200, network_sources()
    except (OSError, ValueError, ET.ParseError) as exc:
        return 500, {"error": f"路网样例读取失败：{exc}"}


def handle_dispatch(body: bytes) -> tuple[int, dict]:
    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            return 400, {"error": "请求内容必须是 JSON 对象"}
        return 201, create_dispatch(payload, list_tasks())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"error": "请求不是有效的 JSON"}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except RuntimeError as exc:
        return 500, {"error": str(exc)}


def handle_feedback(method: str, body: bytes = b"") -> tuple[int, dict | list]:
    try:
        if method == "GET":
            return 200, operation_feed() + list_feedback()
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            return 400, {"error": "请求内容必须是 JSON 对象"}
        return 201, create_feedback(payload, list_tasks())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"error": "请求不是有效的 JSON"}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except RuntimeError as exc:
        return 500, {"error": str(exc)}
