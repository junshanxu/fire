"""Qwen dispatch planner."""
import json
import os
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from platform_app.services.sample_data_service import get_overview
from platform_app.services.task_service import list_tasks
from platform_app.services.dispatch_service import TASK_TYPE_FOR_RESOURCE,active_dispatches, list_dispatches
def U(h):
 h=h.replace(" ","")
 return "".join(chr(int(h[i:i+4],16)) for i in range(0,len(h),4))
API_KEY=os.getenv("DASHSCOPE_API_KEY", "").strip()
ENDPOINT="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL="qwen-plus"
def parse_plan(text):
 text=text.strip()
 if text.startswith("```"): text=text.split(chr(10),1)[-1].rsplit("```",1)[0].strip()
 try: obj=json.loads(text)
 except json.JSONDecodeError:
  a,b=text.find("{"),text.rfind("}")
  if a<0 or b<=a: raise RuntimeError("Invalid Qwen JSON")
  obj=json.loads(text[a:b+1])
 if not isinstance(obj,dict) or not isinstance(obj.get("assignments"),list): raise RuntimeError("Invalid Qwen plan format")
 return obj
def create_ai_dispatch_plan():
 if not API_KEY: raise RuntimeError("DASHSCOPE_API_KEY is not configured")
 tasks=list_tasks(); resources=get_overview().get("resources",[])
 pending=[x for x in tasks if x.get("status") in (U("5f858c035ea6"),U("5f856d5353d1"))]
 available=[x for x in resources if x.get("status") in (U("5f85547d"),U("57287ebf"))]
 busy=active_dispatches(); used_t={x.get("task_id") for x in busy}; used_r={x.get("resource_id") for x in busy}
 pending=[x for x in pending if x.get("id") not in used_t]; available=[x for x in available if x.get("id") not in used_r]
 if not pending: return {"model":MODEL,"summary":U("5f53 524d 6ca1 6709 5f85 8c03 5ea6 4efb 52a1"),"assignments":[],"unmatched_tasks":[]}
 data={"tasks":[{k:t.get(k) for k in ("id","name","type","station","time","points","route_id")} for t in pending],"resources":[{k:r.get(k) for k in ("id","name","type","station","status","task","power")} for r in available],"resource_task_type_map":TASK_TYPE_FOR_RESOURCE}
 prompt="Allocate inspection tasks to heterogeneous resources. Use only input IDs; assign each task and resource at most once. Enforce task type, available status and same station. Prefer higher numeric power among eligible resources. Do not invent metrics. Return JSON summary and assignments(task_id,resource_id,reason). Write summary and reasons in concise Chinese. Leave unmatched tasks unassigned."
 body={"model":MODEL,"temperature":0.2,"messages":[{"role":"system","content":prompt},{"role":"user","content":json.dumps(data,ensure_ascii=False)}]}
 req=Request(ENDPOINT,data=json.dumps(body).encode("utf-8"),headers={"Authorization":"Bearer "+API_KEY,"Content-Type":"application/json"},method="POST")
 try:
  with urlopen(req,timeout=45) as response: result=json.loads(response.read().decode("utf-8"))
 except HTTPError as ex: raise RuntimeError(f"Qwen HTTP {ex.code}: {ex.read().decode('utf-8',errors='replace')[:300]}") from ex
 except (URLError,TimeoutError) as ex: raise RuntimeError(f"Qwen connection failed: {ex}") from ex
 try: content=result["choices"][0]["message"]["content"]
 except (KeyError,IndexError,TypeError) as ex: raise RuntimeError("Qwen response missing content") from ex
 if isinstance(content,list): content="".join(p.get("text","") for p in content if isinstance(p,dict))
 plan=parse_plan(str(content)); tm={str(x["id"]):x for x in pending}; rm={str(x["id"]):x for x in available}; seen_t=set();seen_r=set(); matches=[]
 for row in plan["assignments"]:
  if not isinstance(row,dict): continue
  tid,rid=str(row.get("task_id","")),str(row.get("resource_id","")); t=tm.get(tid);r=rm.get(rid)
  if not t or not r or tid in seen_t or rid in seen_r: continue
  if TASK_TYPE_FOR_RESOURCE.get(r.get("type"))!=t.get("type") or r.get("station")!=t.get("station") or r.get("status") not in (U("5f85547d"),U("57287ebf")): continue
  matches.append({"task_id":tid,"task_name":t["name"],"resource_id":rid,"resource_name":r["name"],"reason":str(row.get("reason",""))[:240]});seen_t.add(tid);seen_r.add(rid)
 return {"model":MODEL,"summary":str(plan.get("summary",""))[:500],"assignments":matches,"unmatched_tasks":[x["id"] for x in pending if x["id"] not in seen_t]}


def _qwen_json(system_prompt: str, payload: dict) -> dict:
 if not API_KEY: raise RuntimeError("DASHSCOPE_API_KEY is not configured")
 body={"model":MODEL,"temperature":0.2,"messages":[{"role":"system","content":system_prompt},{"role":"user","content":json.dumps(payload,ensure_ascii=False)}]}
 req=Request(ENDPOINT,data=json.dumps(body).encode("utf-8"),headers={"Authorization":"Bearer "+API_KEY,"Content-Type":"application/json"},method="POST")
 try:
  with urlopen(req,timeout=45) as response: result=json.loads(response.read().decode("utf-8"))
 except HTTPError as ex: raise RuntimeError(f"Qwen HTTP {ex.code}: {ex.read().decode('utf-8',errors='replace')[:300]}") from ex
 except (URLError,TimeoutError) as ex: raise RuntimeError(f"Qwen connection failed: {ex}") from ex
 try: content=result["choices"][0]["message"]["content"]
 except (KeyError,IndexError,TypeError) as ex: raise RuntimeError("Qwen response missing content") from ex
 if isinstance(content,list): content="".join(part.get("text","") for part in content if isinstance(part,dict))
 value=str(content).strip()
 if value.startswith("```"): value=value.split(chr(10),1)[-1].rsplit("```",1)[0].strip()
 try: report=json.loads(value)
 except json.JSONDecodeError:
  left,right=value.find("{"),value.rfind("}")
  if left<0 or right<=left: raise RuntimeError("Invalid Qwen report format")
  report=json.loads(value[left:right+1])
 if not isinstance(report,dict): raise RuntimeError("Invalid Qwen report format")
 return report


def create_ai_dispatch_report():
 """Generate a concise Chinese report from the actual simulation snapshot."""
 overview=get_overview(); tasks=list_tasks(); dispatches=list_dispatches()
 payload={
  "environment":overview.get("environment",{}),
  "tasks":[{"name":row.get("name"),"status":row.get("status"),"executor":row.get("executor"),"progress":row.get("progress"),"cost":row.get("cost")} for row in tasks],
  "resources":[{"name":row.get("name"),"type":row.get("type"),"status":row.get("status"),"task":row.get("task"),"power_percent":row.get("power_percent")} for row in overview.get("resources",[])],
  "incidents":overview.get("incidents",[]),
  "route_reservations":overview.get("route_reservations",[]),
  "dispatch_count":len(dispatches),
 }
 prompt=("You are the reporting assistant for a simulated heterogeneous inspection fleet. "
         "Use only the supplied snapshot. Every factual status, count, device name, event and action must be directly supported by a supplied field. "
         "Never infer or claim return-to-base, offline state, charging, temperature, a fault, a prediction, or a route being blocked/occupied unless that exact state appears in the snapshot. "
         "Task completion does not imply a device returned, went offline, charged, or has a fault. If a conclusion is not supported, say data not supplied instead. "
         "Return JSON only with headline (string <=36 Chinese characters), summary (string <=180 Chinese characters), "
         "decisions (array of 2-4 concise Chinese strings), risks (array of 0-3 concise Chinese strings), and next_action (string <=80 Chinese characters). "
         "Explain actual dispatch, route/cost state, constraints and any needed operator action in plain Chinese.")
 report=_qwen_json(prompt,payload)
 clean=lambda value,limit: str(value or "")[:limit]
 as_list=lambda value,limit:[clean(item,100) for item in (value if isinstance(value,list) else []) if str(item).strip()][:limit]
 return {"model":MODEL,"generated_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"headline":clean(report.get("headline"),36) or "当前调度态势报告","summary":clean(report.get("summary"),180),"decisions":as_list(report.get("decisions"),4),"risks":as_list(report.get("risks"),3),"next_action":clean(report.get("next_action"),80)}
