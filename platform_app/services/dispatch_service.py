"""Dispatch validation and one-pass simulated inspections."""
import json
import random
from datetime import datetime,timezone
from threading import RLock
from platform_app.config import DISPATCHES_FILE,SAMPLE_DATA_DIR
from platform_app.services.sample_data_service import get_overview
from platform_app.services.planning_service import evaluate_candidate, field_resolution, propose_for_resource
from platform_app.services.planning_service import elevation_m
from math import hypot
def U(h):
 h=h.replace(" ","")
 return "".join(chr(int(h[i:i+4],16)) for i in range(0,len(h),4))
_lock=RLock();TASK_TYPE_FOR_RESOURCE={"robot":"robot","dog":"robot","drone":"drone","person":"team"};SIMULATION_DURATION_SECONDS=120
PENDING=U("5f858c035ea6");READY=U("5f85547d");ONLINE=U("57287ebf");SENT=U("5df26d3e53d1");RUNNING=U("6267884c4e2d");DONE=U("5df25b8c6210")
RETURNING="返厂中";CHARGING="充电中";MAINTENANCE="待检修";RETURN_SECONDS=45;CHARGE_SECONDS=75;DEMO_TIME_SCALE=12
INCIDENT_REASONS=("低电量返场", "传感器故障", "通信不稳定")

def route_meters_per_unit(row, returning=False):
 route=(row.get('return_route') if returning else row.get('planned_route')) or {}
 return float(route.get('meters_per_unit') or (70 if route.get('execution_source')=='osm_road' else 35))

def route_path(row, returning=False):
 route=(row.get('return_route') if returning else row.get('planned_route')) or {}
 if returning:return route.get('path') or []
 if route.get('execution_path'):return route['execution_path']
 if row.get('resource_type') in ('robot','dog','person') and route.get('road_path'):return route['road_path']
 return route.get('path') or []

def path_distance_m(path, meters_per_unit=35):
 return sum(hypot((b['x']-a['x'])*meters_per_unit,(b['y']-a['y'])*meters_per_unit,b.get('z',0)-a.get('z',0)) for a,b in zip(path,path[1:]))

def route_reservation(route):
 path=route.get('execution_path') or route.get('road_path') or route.get('path') or []
 return [f"{round(a['x'],1)}:{round(a['y'],1)}>{round(b['x'],1)}:{round(b['y'],1)}" for a,b in zip(path,path[1:])][:80]

def bid_quote(resource, route, suitability, duration):
 path=route.get('execution_path') or route.get('path') or []
 distance=path_distance_m(path,route.get('meters_per_unit',35));energy=float(suitability.estimated_energy_pct or 0)*float(resource.get('battery_capacity_kwh') or 0)/100
 risk=round(max(0,100-float(suitability.score or 0))/100,3)
 return {'time_s':duration,'energy_kwh':round(energy,3),'distance_m':round(distance),'risk':risk,'total_cost':round(duration/60+energy*18+distance/1000*3+risk*12,2)}

def travel_duration_seconds(route, resource):
 path=(route.get('execution_path') or (route.get('road_path') if resource.get('type') in ('robot','dog','person') else None) or route.get('path') or [])
 units=float(route.get('meters_per_unit') or (70 if path is route.get('road_path') else 35))
 distance=path_distance_m(path,units)
 speed=max(.2,float(resource.get('speed_mps') or 1.0))*max(.75,min(1.25,float(route.get('speed_factor') or 1.0)))
 # Physics uses nominal cruise speed. The clock is explicitly accelerated for the demo.
 service=16+max(0,len(route.get('waypoint_order') or [])-1)*7
 factor=3 if resource.get('type')=='drone' else DEMO_TIME_SCALE
 return max(90 if resource.get('type')=='drone' else 24,min(300,round(distance/(speed*factor)+service)))

def _save_dispatches(history):
 DISPATCHES_FILE.parent.mkdir(parents=True,exist_ok=True)
 temp=DISPATCHES_FILE.with_suffix(".tmp")
 temp.write_text(json.dumps(history,ensure_ascii=False,indent=2)+chr(10),encoding="utf-8")
 temp.replace(DISPATCHES_FILE)
def list_dispatches():
 with _lock:
  if not DISPATCHES_FILE.exists(): return []
  try: value=json.loads(DISPATCHES_FILE.read_text(encoding="utf-8"))
  except json.JSONDecodeError as ex: raise RuntimeError("dispatch history is invalid") from ex
  if not isinstance(value,list): raise RuntimeError("dispatch history must be an array")
  return value
def dispatch_state(row,now=None):
 if row.get("incident_at"):
  started=datetime.fromisoformat(row["incident_at"].replace("Z","+00:00"))
  elapsed=((now or datetime.now(timezone.utc))-started).total_seconds()
  returning_for=int(row.get("return_duration_seconds",RETURN_SECONDS))
  if elapsed<returning_for:return RETURNING
  if row.get('incident_reason') in ('低电量返场','电量异常'):
   return CHARGING if elapsed<returning_for+CHARGE_SECONDS else READY
  return MAINTENANCE
 if row.get("status")!=SENT:return row.get("status",SENT)
 try: started=datetime.fromisoformat(row["created_at"].replace("Z","+00:00"))
 except (KeyError,ValueError):return RUNNING
 elapsed=max(0,((now or datetime.now(timezone.utc))-started).total_seconds())
 return DONE if elapsed>=int(row.get("simulation_duration_seconds",SIMULATION_DURATION_SECONDS)) else RUNNING
def active_dispatches():return [x for x in list_dispatches() if dispatch_state(x) in (SENT,RUNNING,RETURNING,CHARGING)]

def trigger_random_incident(resource_id=None, reason=None):
 with _lock:
  history=list_dispatches()
  active=[row for row in history if dispatch_state(row) in (SENT,RUNNING) and (resource_id is None or row.get("resource_id")==resource_id)]
  if not active:raise ValueError("当前没有可中断的执行任务")
  row=random.choice(active)
  row['resource_type']=row.get('resource_type') or ('drone' if str(row.get('resource_id','')).startswith('DRONE') else 'robot')
  now=datetime.now(timezone.utc)
  position=interpolate_position(row,now)
  path=dispatch_path(row)
  if not position or not path:raise ValueError("设备缺少返厂路线")
  nearest=min(range(len(path)),key=lambda i:((path[i]['x']-position['x'])**2+(path[i]['y']-position['y'])**2+((path[i].get('z',0)-position.get('z',0))/35)**2))
  row["return_route"]={"path":[position,*reversed(path[:nearest+1])],"algorithm":"原巡检路线回溯","meters_per_unit":route_meters_per_unit(row)}
  row["incident_at"]=now.isoformat(timespec="seconds")
  row["incident_reason"]=reason or random.choice(INCIDENT_REASONS)
  row['reservation_state']='已释放';row['reauction_state']='待充电完成后重新竞价' if row['incident_reason'] in ('低电量返场','电量异常') else '待人工复核'
  speed=max(.2,float(row.get('speed_mps') or 1.0))
  row["return_duration_seconds"]=max(18,min(180,round(path_distance_m(row['return_route']['path'],route_meters_per_unit(row))*1.0/(speed*DEMO_TIME_SCALE))))
  row["interrupted_progress"]=dispatch_progress(row,now)
  _save_dispatches(history)
  return {"task_id":row["task_id"],"task_name":row["task_name"],"resource_id":row["resource_id"],"resource_name":row["resource_name"],"reason":row["incident_reason"],"state":RETURNING,"occurred_at":row["incident_at"]}

def recent_incidents():
 return [{"task_id":row.get("task_id"),"task_name":row.get("task_name"),"resource_id":row.get("resource_id"),"resource_name":row.get("resource_name"),"reason":row.get("incident_reason"),"state":dispatch_state(row),"return_route":row.get("return_route"),"incident_at":row.get("incident_at"),"return_duration_seconds":row.get("return_duration_seconds",RETURN_SECONDS),"position":interpolate_position(row)} for row in list_dispatches() if row.get("incident_at")][:5]
def create_dispatch(payload,tasks):
 tid=str(payload.get("task_id","")).strip();rid=str(payload.get("resource_id","")).strip();task=next((x for x in tasks if x.get("id")==tid),None)
 if not task:raise ValueError("Task not found")
 if task.get("status") not in (PENDING,"待派发",SENT,RUNNING):raise ValueError("Task is already dispatched or completed")
 overview=get_overview();resource=next((x for x in overview.get("resources",[]) if x.get("id")==rid),None)
 if not resource:raise ValueError("Resource not found")
 if resource.get("status") not in (READY,ONLINE):raise ValueError("Resource is not available")
 if resource.get("station")!=task.get("station"):raise ValueError("Resource and task must belong to the same station")
 # Give every auction a fresh, inspectable route variant.  The planner uses
 # it only to reorder valid waypoints and perturb cruise speed/altitude.
 variant=f"{datetime.now(timezone.utc).isoformat(timespec='milliseconds')}:{random.randint(1000,9999)}"
 planning_task=dict(task); planning_task['_route_variant']=variant
 proposal=propose_for_resource(planning_task,resource,overview.get("environment",{}))
 if not proposal:
  suitability=evaluate_candidate(planning_task,resource,overview.get("environment",{}))
  raise ValueError("Resource rejected: "+("; ".join(suitability.rejected_by) or "无法规划到达检查点的路线"))
 suitability=proposal["result"];route=proposal["route"]
 reserve=int(resource.get("reserve_pct") or 0)
 margin=8 if suitability.battery_after_pct is not None and suitability.battery_after_pct<reserve else reserve
 route['execution_path']=route.get('road_path') if resource.get('type') in ('robot','dog','person') and route.get('road_path') else route.get('path')
 route.setdefault('execution_source','local_air')
 route.setdefault('meters_per_unit',4)
 duration=travel_duration_seconds(route,resource)
 row={"task_id":tid,"task_name":task["name"],"resource_id":rid,"resource_name":resource["name"],"status":SENT,"created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"simulation_duration_seconds":duration,"planned_route":route,"initial_power_percent":resource.get("power_percent"),"estimated_energy_pct":suitability.estimated_energy_pct,"return_margin_pct":margin,"resolution":field_resolution(task,resource,suitability,proposal["remaining"]),"speed_mps":resource.get('speed_mps'),"simulation_speed_multiplier":DEMO_TIME_SCALE,"route_variant":variant}
 row['resource_type']=resource.get('type');row['bid_quote']=bid_quote(resource,route,suitability,duration);row['reserved_road_segments']=route_reservation(route);row['reservation_state']='占用中'
 row['consumption_factor']=round(.82+random.random()*.32,2)
 with _lock:
  history=list_dispatches();active=active_dispatches()
  if any(x.get("resource_id")==rid for x in active):raise ValueError("Resource already has an active task")
  if any(x.get("task_id")==tid and x.get("resource_id")==rid and dispatch_state(x)!=RETURNING for x in active):raise ValueError("Resource already has an active task")
  history.insert(0,row);_save_dispatches(history)
 return row
def overlay_dispatches(tasks):
 grouped={}
 for row in list_dispatches():
  grouped.setdefault(row.get("task_id"), []).append(row)
 for task in tasks:
  rows=grouped.get(task.get("id")) or []
  if not rows:continue
  active=[row for row in rows if not row.get("incident_at") and dispatch_state(row) in (SENT,RUNNING,RETURNING)]
  row=active[0] if active else rows[0]
  if not active and row.get("incident_at"):
   task["status"]=PENDING;task["executor"]="";task["progress"]="0%";task["interruption"]={"reason":row["incident_reason"],"resource_name":row["resource_name"]}
   task.pop("planned_route",None)
   continue
  names=[]
  for item in active or [row]:
   if item.get("resource_name") and item["resource_name"] not in names:names.append(item["resource_name"])
  state=dispatch_state(row);task["status"]=state;task["executor"]="、".join(names);task["dispatch_started_at"]=row.get("created_at","");task["simulation_duration_seconds"]=int(row.get("simulation_duration_seconds",SIMULATION_DURATION_SECONDS));task["planned_route"]=row.get("planned_route")
  if state==DONE:task["progress"]="100%"
  elif state==RUNNING:
   started=datetime.fromisoformat(row["created_at"].replace("Z","+00:00"));elapsed=max(0,(datetime.now(timezone.utc)-started).total_seconds());task["progress"]=str(min(99,int(elapsed/task["simulation_duration_seconds"]*100)))+"%"
  else:task["progress"]="0%"
 return tasks
def resources_with_dispatches(resources):
 history=list_dispatches();latest={x["resource_id"]:x for x in reversed(history) if x.get("resource_id")}
 active={x["resource_id"]:x for x in reversed(history) if x.get("resource_id") and dispatch_state(x) in (SENT,RUNNING,RETURNING)}
 for resource in resources:
  row=active.get(resource.get("id")) or latest.get(resource.get("id"))
  if row:
   state=dispatch_state(row)
   if resource.get("id") in active:resource["status"]=state;resource["task"]="返场充电" if state==CHARGING else ("返厂" if state==RETURNING else row.get("task_name",""));resource["dispatch_note"]=row.get("resolution") or ""
   elif state==MAINTENANCE:resource["status"]=MAINTENANCE;resource["task"]="待检修"
   position=interpolate_position(row)
   if position is not None:resource["position"]=position
   resource['motion']={'path':dispatch_path(row), 'started_at':row.get('incident_at') or row.get('created_at'), 'duration_seconds':row.get('return_duration_seconds',RETURN_SECONDS) if row.get('incident_at') else row.get('simulation_duration_seconds',SIMULATION_DURATION_SECONDS), 'meters_per_unit':route_meters_per_unit(row,bool(row.get('incident_at'))), 'nominal_speed_mps':row.get('speed_mps',resource.get('speed_mps')),'simulation_speed_multiplier':row.get('simulation_speed_multiplier',DEMO_TIME_SCALE)}
   initial=row.get("initial_power_percent")
   if initial is not None:
    from platform_app.services.cost_service import execution_metrics, CAPACITY_KWH
    metric=execution_metrics(row)
    resource['energy_used_kwh']=round(metric['used']['energy_kwh'],6)
    capacity=CAPACITY_KWH.get(resource.get('type'),0)
    used_pct=metric['used']['energy_kwh']/capacity*100 if capacity else 0
    resource["power_percent"]=max(0,round(initial-used_pct,2))
    resource["power"]=f'{resource["power_percent"]}%'
   if state==CHARGING:
    started=datetime.fromisoformat(row['incident_at'].replace('Z','+00:00'))
    elapsed=(datetime.now(timezone.utc)-started).total_seconds()-float(row.get('return_duration_seconds',RETURN_SECONDS))
    resource['power_percent']=round(min(100,10+90*max(0,elapsed)/CHARGE_SECONDS),1);resource['power']=f"{resource['power_percent']}%"
   elif state==READY and row.get('incident_reason') in ('低电量返场','电量异常'):
    resource['status']=READY;resource['task']='待命';resource['power_percent']=100;resource['power']='100%';resource['dispatch_note']='已完成回场充电'
  position=resource.get('position') or {'x':50,'y':50}
  ground=elevation_m(position['x'],position['y'])
  position.setdefault('z',ground)
  resource['ground_elevation_m']=ground
  resource['altitude_agl_m']=round(max(0,position['z']-ground),2)
 return resources

def dispatch_path(row):
 returning=bool(row.get('incident_at'))
 path=route_path(row,returning)
 if not path:return []
 if any('z' in point for point in path):return path
 if row.get('resource_type')=='drone' or str(row.get('resource_id','')).startswith('DRONE'):
  ground=[{**p,'z':elevation_m(p['x'],p['y'])} for p in path]
  flight=[{**p,'z':p['z']+60} for p in ground]
  return [ground[0],*flight,ground[-1]]
 return [{**p,'z':p.get('elevation_m',elevation_m(p['x'],p['y']))} for p in path] if any('elevation_m' in p for p in path) else path

def dispatch_progress(row,now=None):
 try: started=datetime.fromisoformat(row["created_at"].replace("Z","+00:00"))
 except (KeyError,ValueError):return 0.0
 duration=max(1,int(row.get("simulation_duration_seconds") or SIMULATION_DURATION_SECONDS))
 return min(1.0,max(0.0,((now or datetime.now(timezone.utc))-started).total_seconds()/duration))

def interpolate_position(row,now=None):
 returning=bool(row.get("incident_at"))
 path=dispatch_path(row)
 if not path:return None
 units=route_meters_per_unit(row,returning)
 lengths=[((b['x']-a['x'])**2+(b['y']-a['y'])**2+((b.get('z',0)-a.get('z',0))/units)**2)**.5 for a,b in zip(path,path[1:])]
 if returning:
  started=datetime.fromisoformat(row["incident_at"].replace("Z","+00:00"))
  progress=min(1.0,max(0.0,((now or datetime.now(timezone.utc))-started).total_seconds()/max(1,int(row.get("return_duration_seconds",RETURN_SECONDS)))))
 else:progress=dispatch_progress(row,now)
 remaining=sum(lengths)*progress
 for a,b,length in zip(path,path[1:],lengths):
  if remaining<=length:
   t=remaining/length if length else 0
   point={"x":round(a["x"]+(b["x"]-a["x"])*t,3),"y":round(a["y"]+(b["y"]-a["y"])*t,3)}
   if 'z' in a or 'z' in b:point['z']=round(a.get('z',0)+(b.get('z',0)-a.get('z',0))*t,3)
   return point
  remaining-=length
 return dict(path[-1])


def clear_dispatches():
    with _lock:
        DISPATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
        DISPATCHES_FILE.write_text("[]" + chr(10), encoding="utf-8")


def reset_dispatch_history():
    with _lock:
        DISPATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
        DISPATCHES_FILE.write_text("[]" + chr(10), encoding="utf-8")
        resource_file = SAMPLE_DATA_DIR / "resources.json"
        if resource_file.exists():
            rows = json.loads(resource_file.read_text(encoding="utf-8"))
            for row in rows:
                if row.get("status") == RUNNING:
                    row["status"] = READY
                row["task"] = U("5f85 547d")
            resource_file.write_text(json.dumps(rows, ensure_ascii=True, indent=2) + chr(10), encoding="utf-8")
