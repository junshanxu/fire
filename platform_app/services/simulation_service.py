"""Automatic dispatch for timestamped demo events."""
from platform_app.services.task_service import create_emergency_task, list_tasks
from platform_app.services.dispatch_service import create_dispatch, trigger_random_incident, list_dispatches, dispatch_state
from platform_app.services.planning_service import build_v1_plan


def auto_assign(task_id):
    from platform_app.services.sample_data_service import get_overview
    tasks = list_tasks()
    overview = get_overview()
    plan = build_v1_plan([task for task in tasks if task['id'] == task_id], overview['resources'], overview['environment'])
    from platform_app.services.neural_dispatch import merge_policies
    merge_policies(plan.get('policies') or [])
    chosen = [item for item in plan['assignments'] if item['task_id'] == task_id]
    if not chosen:
        return {'outcome': '等待可用设备', 'dispatch': None}
    sent = None
    for assignment in chosen:
        try:
            sent = create_dispatch({'task_id': task_id, 'resource_id': assignment['resource_id']}, tasks)
        except ValueError:
            continue
    if sent is None:
        return {'outcome': '等待可用设备', 'dispatch': None}
    return {'outcome': '已自动派发', 'dispatch': sent}


def dispatch_waiting():
    from platform_app.services.sample_data_service import get_overview
    from platform_app.services.cost_service import execution_metrics, CAPACITY_KWH, resource_type
    overview=get_overview()
    resources={r['id']:r for r in overview['resources']}
    for row in list_dispatches():
        if dispatch_state(row)!='执行中':continue
        device=resources.get(row.get('resource_id'))
        if not device:continue
        kind=resource_type(row);capacity=CAPACITY_KWH.get(kind,0)
        metric=execution_metrics(row)
        remaining_pct=metric['remaining']['energy_kwh']/capacity*100 if capacity else 0
        weather=overview['environment'].get('weather',{})
        reason=None
        margin=row.get('return_margin_pct', device.get('reserve_pct', 0))
        # A dispatch already accepted under the thinner return margin stays out unless the battery can no longer cover the rest of the route.
        floor=0 if row.get('return_margin_pct') is not None and margin<device.get('reserve_pct', 0) else margin
        if capacity and float(device.get('power_percent') or 0)<remaining_pct+floor:
            reason='续航预估不足'
        if kind=='drone' and (float(weather.get('wind_mps') or 0)>8 or float(weather.get('precipitation_mm') or 0)>0):
            reason='飞行天气变化'
        if reason:
            try:
                event=trigger_random_incident(row['resource_id'],reason)
                auto_assign(event['task_id'])
            except ValueError:
                pass
    for task in list_tasks():
        if task['status'] in ('待调度', '待派发') and (task['name'].startswith('紧急巡检') or task.get('interruption')):
            auto_assign(task['id'])
    continue_demo_round()


def continue_demo_round():
    """Repeat completed sample patrols while preserving user-created tasks."""
    from platform_app.services.sample_data_service import list_sample_tasks
    from platform_app.services.dispatch_service import _lock, _save_dispatches
    sample_ids = {row['id'] for row in list_sample_tasks()}
    tasks = list_tasks()
    samples = [task for task in tasks if task['id'] in sample_ids]
    if not samples:
        return
    # Each patrol repeats independently; short flights must not wait several
    # minutes for the longest ground route before taking off again.
    from datetime import datetime, timezone
    history = list_dispatches()
    for task in samples:
        if task['status'] != '已完成':
            continue
        attempts = [row for row in history if row.get('task_id') == task['id']]
        if not attempts or any(dispatch_state(row) in ('执行中','已派发','返厂中','充电中') for row in attempts):
            continue
        end = max(datetime.fromisoformat(row['created_at']).timestamp() + row.get('simulation_duration_seconds',120) for row in attempts)
        if datetime.now(timezone.utc).timestamp() - end < 5:
            continue
        with _lock:
            _save_dispatches([row for row in list_dispatches() if row.get('task_id') != task['id']])
        auto_assign(task['id'])
    # New scenario tasks can enter a running round without resetting its devices.
    for task in samples:
        if task['status'] in ('待调度', '待派发'):
            auto_assign(task['id'])
    first_run = all(task['status'] in ('待调度', '待派发') for task in samples)
    if not first_run and any(task['status'] != '已完成' for task in samples):
        return
    with _lock:
        history = list_dispatches()
        if any(dispatch_state(row) in ('执行中', '已派发', '返厂中', '充电中') for row in history):
            return
        if not first_run:
            _save_dispatches([row for row in history if row.get('task_id') not in sample_ids])
    for task in samples:
        auto_assign(task['id'])


def start_demo_round():
    """Restart the scripted round. Each browser refresh begins the same tasks again."""
    from platform_app.services.task_service import clear_runtime_tasks
    from platform_app.services.sample_data_service import get_overview
    from platform_app.services.dispatch_service import clear_dispatches

    clear_dispatches()
    clear_runtime_tasks()
    tasks = list_tasks()
    overview = get_overview()
    plan = build_v1_plan(tasks, overview["resources"], overview["environment"])
    from platform_app.services.neural_dispatch import replace_policies
    replace_policies(plan.get("policies") or [])
    sent = []
    failed = []
    for item in plan.get("assignments") or []:
        try:
            sent.append(create_dispatch({"task_id": item["task_id"], "resource_id": item["resource_id"]}, list_tasks()))
        except ValueError as exc:
            failed.append(f"{item.get('resource_name')}: {exc}")
    return {"started": len(sent), "devices": [row.get("resource_name") for row in sent], "failed": failed, "schemes": plan.get("schemes") or []}


def emergency_event(task_type=None):
    task = create_emergency_task(task_type)
    return {**task, 'occurred_at': task['created_at'], **auto_assign(task['id'])}


def fault_event(resource_id=None):
    event = trigger_random_incident(resource_id)
    return {**event, **auto_assign(event['task_id'])}


def event_history():
    tasks = {task['id']: task for task in list_tasks()}
    history = list_dispatches()
    events = []
    for task in tasks.values():
        if task['name'].startswith('紧急'):
            events.append({'time': task['created_at'], 'kind': '紧急任务', 'name': task['name'], 'status': task['status'], 'coordinates': ((task.get('route') or {}).get('waypoints') or [None])[0], 'device': task.get('executor') or '等待可用设备'})
    for row in history:
        if row.get('incident_at'):
            task = tasks.get(row['task_id'], {})
            events.append({'time': row['incident_at'], 'kind': '故障返厂', 'name': row['resource_name'] + ' · ' + row['incident_reason'], 'status': dispatch_state(row), 'device': ('替补：' + task['executor']) if task.get('executor') else '等待替补设备'})
    return sorted(events, key=lambda event: event['time'], reverse=True)[:12]
