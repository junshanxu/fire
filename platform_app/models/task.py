from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4


TASK_TYPES = {"robot", "team", "drone"}


@dataclass
class Task:
    name: str
    station: str
    task_type: str
    executor: str = ""
    planned_time: str = ""
    points: str = ""
    status: str = "待调度"
    task_id: str = ""
    created_at: str = ""
    route_id: str = ""
    requirements: dict | None = None
    route: dict | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "Task":
        name = str(payload.get("name", "")).strip()
        station = str(payload.get("station", "")).strip()
        task_type = str(payload.get("type", "")).strip()
        if not name:
            raise ValueError("请填写任务名称")
        if not station:
            raise ValueError("请填写所属场站")
        if task_type not in TASK_TYPES:
            raise ValueError("任务类型无效")
        return cls(
            name=name[:50],
            station=station[:40],
            task_type=task_type,
            executor=str(payload.get("executor", "")).strip()[:50],
            planned_time=str(payload.get("time", "")).strip()[:30],
            points=str(payload.get("points", "")).strip()[:2000],
            task_id=str(uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            requirements=dict(payload.get("requirements") or {}),
            route=dict(payload.get("route") or {}) or None,
        )

    @classmethod
    def from_record(cls, record: dict) -> "Task":
        return cls(
            name=record["name"],
            station=record["station"],
            task_type=record["task_type"],
            executor=record.get("executor", ""),
            planned_time=record.get("planned_time", ""),
            points=record.get("points", ""),
            status=record.get("status", "待调度"),
            task_id=record.get("task_id", ""),
            created_at=record.get("created_at", ""),
            route_id=record.get("route_id", ""),
            requirements=dict(record.get("requirements") or {}),
            route=dict(record.get("route") or {}) or None,
        )

    def to_record(self) -> dict:
        return asdict(self)

    def to_api(self) -> dict:
        return {
            "id": self.task_id,
            "name": self.name,
            "station": self.station,
            "type": self.task_type,
            "executor": self.executor,
            "time": self.planned_time,
            "points": self.points,
            "status": self.status,
            "created_at": self.created_at,
            "route_id": self.route_id,
            "requirements": self.requirements or {},
            "route": self.route,
        }
