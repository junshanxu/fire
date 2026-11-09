import json
import math
from datetime import datetime, timedelta
from threading import RLock
from uuid import uuid4

from platform_app.config import DATA_DIR


FEEDBACK_FILE = DATA_DIR / "feedback.json"
_lock = RLock()


def list_feedback() -> list[dict]:
    with _lock:
        if not FEEDBACK_FILE.exists():
            return []
        value = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise RuntimeError("feedback.json 顶层必须是数组")
        return value


def create_feedback(payload: dict, tasks: list[dict]) -> dict:
    task_id = str(payload.get("task_id", "")).strip()
    kind = str(payload.get("kind", "")).strip()
    message = str(payload.get("message", "")).strip()
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        raise ValueError("请选择有效任务")
    if kind not in ("完成反馈", "异常反馈"):
        raise ValueError("反馈类型无效")
    if not message:
        raise ValueError("请填写反馈内容")
    record = {"id": str(uuid4()), "task_id": task_id, "task_name": task["name"], "station": task["station"], "kind": kind, "message": message[:1000], "time": datetime.now().strftime("%H:%M"), "created_at": datetime.now().isoformat(timespec="seconds")}
    with _lock:
        records = list_feedback()
        records.insert(0, record)
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = FEEDBACK_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(FEEDBACK_FILE)
    return record


_IMAGES = {
    "thermal": "/assets/feedback/transformer-bank-real.jpg",
    "radiator": "/assets/feedback/transformer-real.jpg",
    "visual": "/assets/feedback/gis-real.jpg",
    "gauge": "/assets/feedback/pressure-gauge.jpg",
    "manual": "/assets/feedback/pump-room.jpg",
    "yard": "/assets/feedback/substation-public-domain.jpg",
    "bank": "/assets/feedback/transformer-yard.jpg",
    "fence": "/assets/feedback/yard-fence-real.jpg",
    "line": "/assets/feedback/tower-real.jpg",
    "propeller": "/assets/feedback/drone-propeller.jpg",
}

# Readings stay tied to the waypoint the crew has actually reached.
_POINT_READINGS = {
    "1号主变测温位": ("红外测温", "A相套管 43.8°C，B相 44.1°C，C相 43.6°C，三相温差 0.5°C。", "设备回传", "thermal"),
    "2号主变测温位": ("红外测温", "A相套管 63.4°C，高出 B/C 相约 18°C，已标成复测点。", "异常反馈", "thermal"),
    "3号主变测温位": ("红外测温", "三相套管 45.2–46.0°C，与负荷曲线相符。", "设备回传", "radiator"),
    "GIS北侧压力表": ("设备巡检", "北侧 SF6 压力 0.52 MPa，密度继电器未动作。", "设备回传", "gauge"),
    "GIS南侧气体检测": ("设备巡检", "南侧 SF6 压力 0.49 MPa，检测仪无泄漏报警。", "设备回传", "gauge"),
    "消防泵房门口": ("设施复核", "泵组外观完好，出口压力 0.32 MPa，现场已拍照。", "设备回传", "manual"),
    "消防沙箱": ("设施复核", "沙量约八成，箱门关闭，铲具在位。", "设备回传", "manual"),
    "辅助用房门口": ("设施复核", "通道无堆物，应急灯试验正常。", "设备回传", "manual"),
    "电抗器室门口": ("设施复核", "室门关闭，室内无异常气味。", "设备回传", "manual"),
    "1号主变上方": ("航拍测温", "可见光与热成像已回传，未见异常放电。", "设备回传", "thermal"),
    "2号主变上方": ("航拍测温", "高位套管温度与地面测点一致，温差 1.2°C。", "设备回传", "bank"),
    "3号主变上方": ("航拍测温", "散热器组温度均匀，最高 47.6°C。", "设备回传", "radiator"),
    "GIS屋面": ("航拍测温", "屋面无积水，避雷针连接可见。", "设备回传", "visual"),
    "事故油池观察位": ("渗漏复核", "池壁干燥，液位在标线内，未见油膜。", "设备回传", "yard"),
    "排油通道复核位": ("渗漏复核", "排油管阀门关闭，地面无新鲜油渍。", "设备回传", "yard"),
    "东门外通道": ("围界巡检", "东门外通道畅通，热成像未见滞留热源。", "设备回传", "fence"),
    "东南围界": ("围界巡检", "东南段围栏连续，底部无掏挖痕迹。", "设备回传", "fence"),
    "西南围界": ("围界巡检", "西南段照明正常，周界无翻越迹象。", "设备回传", "fence"),
    "西北围界": ("围界巡检", "西北段排水沟通畅。", "设备回传", "fence"),
    "东北围界": ("围界巡检", "东北段围栏门关闭并上锁。", "设备回传", "fence"),
    "北侧进线西段": ("外围巡线", "北侧进线走廊清晰，导线弧垂目视正常。", "设备回传", "line"),
    "北侧进线进站": ("外围巡线", "进线构架与站内 GIS 连接可见，无异物。", "设备回传", "line"),
    "东侧出线": ("外围巡线", "东侧出线导线间距正常，无新增施工。", "设备回传", "line"),
    "东侧出线末端": ("外围巡线", "出线末端可见光已归档。", "设备回传", "line"),
    "东北外围巡线点": ("外围巡线", "东北走廊清晰，导线弧垂目视正常。", "设备回传", "line"),
    "东南外围巡线点": ("外围巡线", "东南侧树障距离足够，无新增施工。", "设备回传", "line"),
    "西南外围巡线点": ("外围巡线", "西南走廊无异物，测距回传正常。", "设备回传", "line"),
    "西北外围巡线点": ("外围巡线", "西北走廊可见光已归档。", "设备回传", "line"),
}


def _clock(moment: datetime) -> str:
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%H:%M")


def _started(task: dict) -> datetime:
    raw = str(task.get("dispatch_started_at") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now().astimezone()


def _progress(task: dict) -> float:
    raw = str(task.get("progress") or "0").rstrip("%")
    try:
        return max(0.0, min(1.0, float(raw) / 100))
    except ValueError:
        return 0.0


def _reading(task: dict, device: str, label: str, moment: datetime, enroute: bool = False) -> dict:
    if enroute:
        destination = _POINT_READINGS.get(label)
        sensor, message, kind, image = ("行程", f"已离开停放点，正前往{label}。", "设备回传", destination[3] if destination else "yard")
    else:
        sensor, message, kind, image = _POINT_READINGS.get(
            label,
            ("巡检回传", f"{label}已检查，图像已上传。", "设备回传", "visual"),
        )
    return {
        "id": f"live-{task.get('id')}-{label}",
        "task_id": task.get("id"),
        "task_name": task.get("name"),
        "device": device,
        "kind": kind,
        "sensor": sensor,
        "message": message,
        "time": _clock(moment),
        "source": "设备回传",
        "image": _IMAGES[image],
        "sort_at": moment.timestamp(),
    }


def _yard_notes(resources: list[dict]) -> list[dict]:
    now = datetime.now().astimezone()
    shift = now.replace(hour=7, minute=42, second=0, microsecond=0)
    if shift > now:
        shift = shift - timedelta(days=1)
    notes = []
    for resource in resources:
        status = resource.get("status")
        name = resource.get("name") or resource.get("id")
        if status == "充电中":
            power = resource.get("power_percent")
            power_text = f"{round(power)}%" if isinstance(power, (int, float)) else "回升中"
            moment = now
            message = f"停在充电桩，电量 {power_text}，充满后转待命。"
            image = "bank"
        elif status == "离线" and resource.get("type") == "person":
            moment = shift
            message = "手持终端未登录。本日休班，不参与这一轮派工。"
            image = ""
        elif status == "离线":
            moment = shift + timedelta(minutes=34)
            power = resource.get("power_percent")
            last = f"{round(power)}%" if isinstance(power, (int, float)) else "无读数"
            message = f"东侧围界链路中断。最后一次电量 {last}，本轮已由在线单元补位。"
            image = "fence"
        elif status in {"检修", "待检修"}:
            moment = shift + timedelta(minutes=46)
            message = "桨叶检查未完成，暂不放飞。"
            image = "propeller"
        else:
            continue
        notes.append({
            "id": f"yard-{resource.get('id')}",
            "device": name,
            "kind": "设备回传",
            "sensor": "状态",
            "message": message,
            "time": _clock(moment),
            "source": "站内值班",
            "sort_at": moment.timestamp(),
        })
        if image:
            notes[-1]["image"] = _IMAGES[image]
    return notes


def operation_feed() -> list[dict]:
    """Live, fictional returns derived from the patrol that is actually running."""
    from platform_app.services.sample_data_service import get_overview
    from platform_app.services.task_service import list_tasks

    rows: list[dict] = []
    for task in list_tasks():
        points = list((task.get("route") or {}).get("waypoints") or [])
        if not points or task.get("status") not in {"执行中", "已派发", "已完成"}:
            continue
        names = [part for part in str(task.get("executor") or "").split("、") if part]
        device = names[0] if names else "巡检设备"
        started = _started(task)
        duration = max(30, int(task.get("simulation_duration_seconds") or 90))
        progress = 1.0 if task.get("status") == "已完成" else _progress(task)
        reached = len(points) if task.get("status") == "已完成" else math.floor(progress * len(points))
        if reached <= 0:
            rows.append(_reading(task, device, str(points[0].get("id") or "检查点"), started, enroute=True))
            continue
        for index in range(reached):
            label = str(points[index].get("id") or f"检查点{index + 1}")
            moment = started + timedelta(seconds=duration * (index + 1) / len(points))
            rows.append(_reading(task, device, label, moment))
    yard = _yard_notes(get_overview().get("resources") or [])
    rows.sort(key=lambda item: item.get("sort_at") or 0, reverse=True)
    alerts = [item for item in rows if item.get("kind") == "异常反馈"]
    normal = [item for item in rows if item.get("kind") != "异常反馈"]
    chosen = alerts[:1]
    for item in normal:
        if len(chosen) >= 5:
            break
        chosen.append(item)
    chosen.sort(key=lambda item: item.get("sort_at") or 0, reverse=True)
    pictured = [item for item in yard if item.get("image")]
    plain = [item for item in yard if not item.get("image")]
    ordered = chosen + pictured + plain
    for item in ordered:
        item.pop("sort_at", None)
    return ordered[:8]
