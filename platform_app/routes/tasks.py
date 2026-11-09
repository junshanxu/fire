import json
from xml.etree import ElementTree as ET

from platform_app.services.task_service import create_task, list_tasks
from platform_app.services.sample_data_service import get_overview
from platform_app.services.dispatch_service import create_dispatch
from platform_app.services.feedback_service import create_feedback, list_feedback
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
        return 200, build_v1_plan(list_tasks(), overview.get("resources", []), overview.get("environment", {}))
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
