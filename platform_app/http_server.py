import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from platform_app.config import HOST, PORT
from platform_app.routes.pages import content_type, resolve_static_path
from platform_app.routes.tasks import handle_dispatch, handle_feedback, handle_network_sources, handle_overview, handle_planning, handle_tasks
from platform_app.services.ai_dispatch_service import create_ai_dispatch_plan, create_ai_dispatch_report
from platform_app.services.dispatch_service import reset_dispatch_history, trigger_random_incident
from platform_app.services.task_service import create_emergency_task
from platform_app.services.simulation_service import emergency_event, fault_event, dispatch_waiting, start_demo_round


class PlatformHandler(BaseHTTPRequestHandler):
    server_version = "InspectionControlDemo/1.0"

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/overview":
            status, payload = handle_overview()
            return self._send_json(status, payload)
        if path == "/api/feedback":
            status, payload = handle_feedback("GET")
            return self._send_json(status, payload)
        if path == "/api/tasks":
            status, payload = handle_tasks("GET")
            return self._send_json(status, payload)
        if path == "/api/planning/plan":
            status, payload = handle_planning()
            return self._send_json(status, payload)
        if path == "/api/network-sources":
            status, payload = handle_network_sources()
            return self._send_json(status, payload)
        self._serve_static(path)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/tasks", "/api/dispatch", "/api/feedback", "/api/ai/dispatch-plan", "/api/ai/dispatch-report", "/api/simulation/reset", "/api/simulation/demo", "/api/simulation/incident", "/api/simulation/emergency-task"):
            return self._send_json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._send_json(400, {"error": "无效的请求长度"})
        if length > 1_000_000:
            return self._send_json(413, {"error": "请求内容过大"})
        body = self.rfile.read(length)
        if path == "/api/simulation/reset":
            reset_dispatch_history()
            return self._send_json(200, {"ok": True})
        if path == "/api/simulation/demo":
            try:
                return self._send_json(200, start_demo_round())
            except (RuntimeError, ValueError, OSError) as exc:
                return self._send_json(400, {"error": str(exc)})
        if path == "/api/simulation/emergency-task":
            try:
                payload=json.loads(body.decode('utf-8')) if body else {}
                if not isinstance(payload,dict) or payload.get('type') not in (None,'robot','drone'):
                    return self._send_json(400, {'error':'事件类型无效'})
                return self._send_json(201, emergency_event(payload.get('type')))
            except (ValueError, RuntimeError, UnicodeDecodeError) as exc:
                return self._send_json(400, {"error": str(exc)})
        if path == "/api/simulation/incident":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
                if not isinstance(payload, dict):
                    return self._send_json(400, {"error": "请求内容必须是 JSON 对象"})
                return self._send_json(200, fault_event(payload.get("resource_id")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._send_json(400, {"error": "请求不是有效的 JSON"})
            except ValueError as exc:
                return self._send_json(400, {"error": str(exc)})
        if path == "/api/ai/dispatch-plan":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
                if not isinstance(payload, dict):
                    return self._send_json(400, {"error": "请求内容必须是 JSON 对象"})
                result = create_ai_dispatch_plan()
                return self._send_json(200, result)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._send_json(400, {"error": "请求不是有效的 JSON"})
            except ValueError as exc:
                return self._send_json(503, {"error": str(exc)})
            except RuntimeError as exc:
                return self._send_json(502, {"error": str(exc)})
        if path == "/api/ai/dispatch-report":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
                if not isinstance(payload, dict):
                    return self._send_json(400, {"error": "请求内容必须是 JSON 对象"})
                return self._send_json(200, create_ai_dispatch_report())
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._send_json(400, {"error": "请求不是有效的 JSON"})
            except ValueError as exc:
                return self._send_json(503, {"error": str(exc)})
            except RuntimeError as exc:
                return self._send_json(502, {"error": str(exc)})
        if path == "/api/dispatch":
            status, payload = handle_dispatch(body)
        elif path == "/api/feedback":
            status, payload = handle_feedback("POST", body)
        else:
            status, payload = handle_tasks("POST", body)
        self._send_json(status, payload)

    def _serve_static(self, url_path: str):
        file_path = resolve_static_path(url_path)
        if file_path is None:
            return self._send_json(404, {"error": "Not found"})
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type(file_path)}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        print(f"[{self.log_date_time_string()}] {format_string % args}")


def run():
    server = ThreadingHTTPServer((HOST, PORT), PlatformHandler)
    stop = threading.Event()
    def scheduler():
        while not stop.wait(2):
            try:
                dispatch_waiting()
            except (RuntimeError, ValueError, OSError) as exc:
                print(f"自动调度重试：{exc}")
    worker = threading.Thread(target=scheduler, daemon=True)
    worker.start()
    print(f"总控平台 Demo 已启动：http://{HOST}:{PORT}")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        stop.set()
        worker.join(timeout=3)
        server.server_close()
