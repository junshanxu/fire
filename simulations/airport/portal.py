"""Web portal and dependency-aware mission coordinator for the Gazebo airport."""
import asyncio, copy, json, threading, time, uuid, queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import numpy as np
from flask import Flask, Response, jsonify, request, send_from_directory
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Image
from rosgraph_msgs.msg import Clock
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import ApiRequest, ApiResponse
from std_msgs.msg import String
from std_srvs.srv import Empty
import websockets
from fleet_config import CELLS, DEVICES, LOCATIONS, CAMERA, POINTS, EDGES

ROOT=Path("/opt/airport")
app=Flask(__name__,static_folder=str(ROOT/"site"),static_url_path="")
lock=threading.RLock()
state={"sim_seconds":0,"clock_received":0,"fleets":{},"tasks":{},"events":[],
       "agents":{},"agents_received":0,"mission":{"status":"idle","steps":[]},"paused":False}
frames={};pending={}
def event(text):
    with lock:
        state["events"].insert(0,{"time":time.time(),"text":text})
        del state["events"][60:]

class Bridge(Node):
    def __init__(self):
        super().__init__("airport_web_bridge")
        self.create_subscription(Clock,"/clock",self.clock,qos_profile_sensor_data)
        self.create_subscription(FleetState,"/fleet_states",self.fleet,10)
        self.create_subscription(String,"/airport/agents",self.agents,10)
        qos=QoSProfile(depth=20,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
        self.pub=self.create_publisher(ApiRequest,"/task_api_requests",qos)
        self.create_subscription(ApiResponse,"/task_api_responses",self.response,qos)
        self.air=self.create_publisher(String,"/airport/air_command",10)
        self.pause=self.create_client(Empty,"/pause_physics")
        self.resume=self.create_client(Empty,"/unpause_physics")
        for name in ("overview","dog","drone"):
            self.create_subscription(Image,"/sensors/"+name+"/"+name+"/image_raw",lambda m,n=name:self.frame(n,m),qos_profile_sensor_data)
    def clock(self,m):
        with lock:state["sim_seconds"]=m.clock.sec+m.clock.nanosec/1e9;state["clock_received"]=time.time()
    def fleet(self,m):
        with lock:state["fleets"][m.name]={"name":m.name,"received":time.time(),"robots":[{"name":r.name,"x":r.location.x,"y":r.location.y,"yaw":r.location.yaw,"level":r.location.level_name,"mode":r.mode.mode,"task_id":r.task_id} for r in m.robots]}
    def agents(self,m):
        with lock:state["agents"]=json.loads(m.data);state["agents_received"]=time.time()
    def response(self,m):
        with lock:
            p=pending.get(m.request_id)
            if p:p["result"]=json.loads(m.json_msg);p["event"].set()
    def frame(self,name,m):
        # Respect row stride, and reject unknown pixel encodings.
        if m.encoding not in ("rgb8","bgr8","rgba8","bgra8"):return
        channels=4 if "a" in m.encoding else 3
        a=np.frombuffer(m.data,dtype=np.uint8).reshape(m.height,m.step)[:,:m.width*channels].reshape(m.height,m.width,channels)
        if m.encoding=="rgb8":a=cv2.cvtColor(a,cv2.COLOR_RGB2BGR)
        elif m.encoding=="rgba8":a=cv2.cvtColor(a,cv2.COLOR_RGBA2BGR)
        elif m.encoding=="bgra8":a=cv2.cvtColor(a,cv2.COLOR_BGRA2BGR)
        ok,j=cv2.imencode(".jpg",a,[cv2.IMWRITE_JPEG_QUALITY,82])
        if ok:
            with lock:frames[name]={"bytes":j.tobytes(),"received":time.time(),"sim":state["sim_seconds"]}

async def observe(ws,_path=None):
    async for raw in ws:
        try:
            p=json.loads(raw)
            if p.get("type")!="task_state_update":continue
            t=p["data"];key=t["booking"]["id"]
            with lock:
                before=state["tasks"].get(key,{}).get("status")
                state["tasks"][key]=t
                if before!=t.get("status"):event("RMF "+key+" → "+str(t.get("status")))
        except (ValueError,KeyError,TypeError):continue
async def ws_server():
    async with websockets.serve(observe,"127.0.0.1",7878):await asyncio.Future()

def rmf_task(fleet,robot,places):
    m=ApiRequest();m.request_id="airport_"+uuid.uuid4().hex
    with lock:start=int(state["sim_seconds"]*1000)
    m.json_msg=json.dumps({"type":"robot_task_request","fleet":fleet,"robot":robot,
        "request":{"unix_millis_earliest_start_time":start,"category":"patrol","description":{"places":places,"rounds":1}}})
    item={"event":threading.Event()}
    with lock:pending[m.request_id]=item
    bridge.pub.publish(m);item["event"].wait(20)
    with lock:pending.pop(m.request_id,None)
    result=item.get("result")
    if not result:raise RuntimeError("RMF 响应超时；请查看任务列表")
    if not result.get("success"):raise RuntimeError("RMF 拒绝任务："+json.dumps(result,ensure_ascii=False))
    task_id=result.get("state",{}).get("booking",{}).get("id")
    if not task_id:raise RuntimeError("RMF 未返回任务编号")
    return task_id

def wait_until(test,label,limit=360):
    deadline=time.monotonic()+limit
    while time.monotonic()<deadline:
        with lock:
            paused=state['paused']
            if state['mission'].get('abort'):raise RuntimeError('另一处工单异常，停止继续派单')
            if not paused and test():return
        if paused:deadline+=.25
        time.sleep(.25)
    raise RuntimeError(label+'：等待超时')

def near(name,xy,tolerance=.45):
    p=state['agents'].get('poses',{}).get(name,{})
    return bool(p and time.time()-p.get('received',0)<3 and ((p['x']-xy[0])**2+(p['y']-xy[1])**2)**.5<tolerance)

def assign(name,action,phase,target=None,cell=None):
    with lock:state['mission']['assignments'][name]={'action':action,'phase':phase,'target':target,'cell':cell}

def cell_stage(cell,stage,detail,**extra):
    with lock:
        c=next(c for c in state['mission']['cells'] if c['id']==cell['id'])
        c.update(phase=stage,detail=detail,**extra)
        state['mission']['timeline'].append({'sim':state['sim_seconds'],'cell':cell['id'],'phase':stage,'detail':detail})
    event(cell['id']+'区 → '+detail)

def ground_go(name,place,action,cell):
    xy=LOCATIONS[place];assign(name,action,'running',xy,cell['id'])
    task=rmf_task(DEVICES[name]['fleet'],name,[place])
    with lock:
        state['mission']['task_ids'].append(task)
        state['mission']['dispatches'].append({'robot':name,'target':place,'task_id':task,'sim':state['sim_seconds'],'cell':cell['id']})
    def complete():
        status=state['tasks'].get(task,{}).get('status')
        if status in ('failed','canceled','killed'):raise RuntimeError(task+' '+status)
        return status=='completed' and near(name,xy)
    wait_until(complete,DEVICES[name]['label']+' 前往 '+place)
    return task

def capture(name,label,cell=''):
    with lock:
        f=frames.get(name);mission_id=state['mission']['id']
        if not f or time.time()-f['received']>5:raise RuntimeError(name+' 相机无新画面')
        filename=mission_id+'-'+cell+'-'+uuid.uuid4().hex[:6]+'-'+name+'.jpg'
        data=f['bytes'];sim=f['sim']
    folder=ROOT/'runtime'/'evidence';folder.mkdir(exist_ok=True)
    (folder/filename).write_bytes(data)
    with lock:state['mission']['evidence'].append({'camera':name,'label':label,'sim_seconds':sim,'url':'/evidence/'+filename})

def air_state(device,air_id):
    a=state['agents'].get('airs',{}).get(device,{})
    p=state['agents'].get('poses',{}).get(device,{})
    if a.get('id')==air_id and time.time()-p.get('received',0)<3:return a
    return {}

def run_cell(cell,pool):
    dog=cell['dog'];drone=cell['drone'];cid=cell['id'];amr=None
    try:
        cell_stage(cell,'inspect','机器狗前往现场，空中与运输任务等待初检')
        ground_go(dog,cell['inspect'],cid+'区地面初检',cell)
        capture('dog' if cid=='A' else 'overview',cid+'区地面到点证据',cid)
        # Explicit scenario injection, never presented as image recognition.
        cell_stage(cell,'air',cell['kind']+'已注入；已满足起飞前置条件',alarm={'source':'scenario_injection','type':cell['kind'],'sim':state['sim_seconds']})
        assign(dog,'现场留守 · 等待空中复核','waiting',None,cid)
        assign(drone,cid+'区空中复核','running',[cell['x'],cell['y']+1.,cell['altitude']],cid)
        air_id=uuid.uuid4().hex
        with lock:next(c for c in state['mission']['cells'] if c['id']==cid)['air_id']=air_id
        bridge.air.publish(String(data=json.dumps({'id':air_id,'action':'survey','device':drone})))
        wait_until(lambda:air_state(drone,air_id).get('verified',False),cid+'区无人机定点复核')
        capture('drone' if cid=='A' else 'overview',cid+'区空中到点复核证据（无 AI 识别）',cid)
        cell_stage(cell,'queue','空中定点复核完成，等待空闲运输机器人',verified=True,verified_at=state['sim_seconds'])
        assign(drone,'返航降落','running',DEVICES[drone]['home'],cid)
        assign(dog,'留守 · 等待运输车分配','waiting',None,cid)
        while amr is None:
            with lock:
                if state['mission'].get('abort'):raise RuntimeError('另一处工单异常，取消等待运力')
            try:amr=pool.get(timeout=1)
            except queue.Empty:continue
        cell_stage(cell,'transport',DEVICES[amr]['label']+' 运送'+cell['cargo'],amr=amr,cargo=cell['cargo'])
        assign(dog,'等待 '+DEVICES[amr]['label']+' 物资到场','waiting',None,cid)
        ground_go(amr,cell['delivery'],cid+'区配送 · '+cell['cargo'],cell)
        # Two distinct physically measured rendezvous pads, 2.5 meters apart.
        def both_present():
            poses=state['agents'].get('poses',{})
            return near(dog,LOCATIONS[cell['inspect']]) and near(amr,LOCATIONS[cell['delivery']]) and all(poses.get(n,{}).get('speed',99)<.08 for n in (dog,amr))
        wait_until(both_present,cid+'区双方到位确认')
        cell_stage(cell,'handoff','双方实际到位，开始模拟物资交接与工单确认',handoff_started=state['sim_seconds'])
        assign(dog,'双方到位 · 模拟工单确认','servicing',None,cid)
        assign(amr,'双方到位 · 模拟物资交接','servicing',None,cid)
        dwell=[None]
        def continuous_presence():
            if not both_present():dwell[0]=None;return False
            if dwell[0] is None:dwell[0]=state['sim_seconds']
            return state['sim_seconds']-dwell[0]>=4.
        wait_until(continuous_presence,cid+'区交接连续驻留')
        capture('overview',cid+'区双方到位交接证据',cid)
        with lock:
            c=next(c for c in state['mission']['cells'] if c['id']==cid)
            c['handoff']={'sim':state['sim_seconds'],'dog':copy.deepcopy(state['agents']['poses'][dog]),'amr':copy.deepcopy(state['agents']['poses'][amr]),'type':'simulated_work_order_acknowledgement'}
        cell_stage(cell,'return','交接已确认，设备返航；运输车返回仓位后释放给下一处任务',resolved=True)
        # Return both ground robots concurrently, then release the actual resource.
        with ThreadPoolExecutor(max_workers=2) as ex:
            jobs=[ex.submit(ground_go,n,DEVICES[n]['dock'],'返回待命位',cell) for n in (dog,amr)]
            for j in jobs:j.result()
        assign(dog,'任务完成 · 待命','idle',None,cid)
        assign(amr,'仓位待命 · 可接受下一处配送','idle')
        pool.put(amr);amr=None
        wait_until(lambda:air_state(drone,air_id).get('status')=='completed' and near(drone,DEVICES[drone]['home']) and abs(state['agents']['poses'][drone]['z']-.4)<.25,cid+'区无人机降落')
        assign(drone,'任务完成 · 已降落','idle',None,cid)
        cell_stage(cell,'completed','现场工单闭环，设备均回到待命位')
    except Exception as e:
        with lock:state['mission']['abort']=True
        cell_stage(cell,'failed',str(e))
        raise
    finally:
        if amr is not None:pool.put(amr)

def run_mission():
    pool=queue.Queue()
    for n in ('logistics_1','logistics_2'):pool.put(n)
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            jobs=[ex.submit(run_cell,c,pool) for c in CELLS]
            for job in jobs:job.result()
        with lock:
            state['mission'].update(status='completed',finished=time.time(),finished_sim=state['sim_seconds'])
            for s in state['mission']['steps']:s['status']='completed'
        event('8 台设备完成三处协同工单，已返回待命位')
    except Exception as e:
        with lock:state['mission'].update(status='failed',error=str(e),finished=time.time())
        event('联合任务异常：'+str(e))
    finally:
        reports=ROOT/'runtime'/'reports';reports.mkdir(exist_ok=True)
        with lock:report=copy.deepcopy(state['mission'])
        (reports/'last-mission.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
@app.get("/")
def index():return send_from_directory(app.static_folder,"index.html")
@app.get("/api/status")
def status():
    with lock:d=copy.deepcopy(state);d["cameras"]={n:{"age":time.time()-f["received"],"sim":f["sim"]} for n,f in frames.items()}
    now=time.time();d["live"]=now-d["clock_received"]<5 and d["sim_seconds"]>0
    d["fleets"]=[f for f in d["fleets"].values() if now-f["received"]<8]
    d["tasks"]=list(d["tasks"].values())
    cells=d["mission"].get("cells",[])
    if cells:
        rank={"queued":0,"inspect":0,"air":1,"queue":2,"transport":2,"handoff":2,"return":3,"completed":4,"failed":-1}
        for i,phases in enumerate((("inspect",),("air",),("queue","transport","handoff"),("return",))):
            completed=all(rank[c["phase"]]>i for c in cells)
            active=any(c.get("phase") in phases for c in cells)
            d["mission"]["steps"][i]["status"]="completed" if completed else ("running" if active else "pending")
    d["scene"]={"camera":CAMERA,"cells":CELLS,"points":POINTS,"edges":EDGES}
    d["devices"]=[]
    for name,meta in DEVICES.items():
        p=d["agents"].get("poses",{}).get(name,{})
        a=d["mission"].get("assignments",{}).get(name,{})
        motion=d["agents"].get("airs" if meta["type"]=="drone" else "dogs",{}).get(name,{})
        online=bool(p and (d["paused"] or now-p.get("received",0)<3))
        moving=online and not d["paused"] and (p.get("speed",0)>.035 or abs(p.get("angular_speed",0))>.06)
        action=a.get("action","等待启动协同任务")
        if meta["type"]=="drone" and motion.get("status")=="running":action=motion.get("label",action)
        if motion.get("blocked"):action=motion["blocked"]
        if not online:mode="遥测离线"
        elif d["paused"]:mode="已暂停"
        elif moving:mode="移动中" if p.get("speed",0)>.035 else "转向中"
        elif meta["type"]=="drone" and p.get("z",0)>1:mode="悬停复核"
        elif a.get("phase")=="waiting":mode="等待联动"
        elif a.get("phase")=="servicing":mode="交接确认"
        elif a.get("phase")=="running":mode="等待调度"
        else:mode="待命"
        target=a.get("target")
        if meta["type"]=="drone" and motion.get("status")=="running":target=motion["route"][motion["index"]][:3]
        if meta["type"]=="drone" and motion.get("status")=="completed":
            action="已降落 · 复核已提交";target=None
            if online and not d["paused"]:mode="待命"
        if meta["type"]=="dog" and a.get("action")=="返回待命位" and not moving and p and ((p["x"]-meta["home"][0])**2+(p["y"]-meta["home"][1])**2)**.5<.45:
            action="已归位 · 等待本区运输车返航"
            if online and not d["paused"]:mode="待命"
        d["devices"].append(dict(id=name,**meta,pose=p,online=online,moving=moving,mode=mode,action=action,phase=a.get("phase","idle"),target=target,workcell=a.get("cell",meta.get("cell"))))
    names={r["name"] for f in d["fleets"] for r in f["robots"]}
    expected={"logistics_1","logistics_2","inspection_dog","inspection_dog_2","inspection_dog_3"}
    d["ready"]=d["live"] and expected.issubset(names) and all(x["online"] for x in d["devices"]) and all(d["cameras"].get(n,{}).get("age",999)<5 for n in ("overview","dog","drone")) and now-d["agents_received"]<5
    return jsonify(d)
@app.post("/api/mission")
def mission():
    d=status().get_json()
    with lock:
        if state["mission"]["status"]=="running":return jsonify(error="联合任务正在运行"),409
        if not d["ready"] or state["paused"]:return jsonify(error="请等待仿真、车队和相机就绪"),503
        state["mission"]={"id":time.strftime("%Y%m%d-%H%M%S"),"status":"running","started":time.time(),"task_ids":[],"evidence":[],
            "cells":[{"id":c["id"],"name":c["name"],"phase":"queued","detail":"等待机器狗派遣","dog":c["dog"],"drone":c["drone"]} for c in CELLS],
            "abort":False,"started_sim":state["sim_seconds"],
            "assignments":{n:{"action":"等待机器狗到点告警" if x["type"]=="drone" else "等待复核结果与配送分配" if x["type"]=="amr" else "等待 RMF 派遣","phase":"waiting"} for n,x in DEVICES.items()},"dispatches":[],"timeline":[],
            "steps":[
                {"name":"三点地面初检","detail":"DOG-01 / DOG-02 / DOG-03 · RMF 多车队并行巡检","status":"pending"},
                {"name":"分层空中复核","detail":"UAV-01 / UAV-02 / UAV-03 · 到点告警后才起飞","status":"pending"},
                {"name":"工具箱条件交接","detail":"复核确认后 AMR-01 / AMR-02 前往不同交接点","status":"pending"},
                {"name":"全队返航与归档","detail":"8 台设备返回待命位，报告和证据保存","status":"pending"}]}
    threading.Thread(target=run_mission,daemon=True).start()
    return jsonify(success=True)
@app.post("/api/physics")
def physics():
    action=(request.get_json(silent=True) or {}).get("action")
    if action not in ("pause","resume"):return jsonify(error="Invalid action"),400
    client=bridge.pause if action=="pause" else bridge.resume
    if not client.service_is_ready():return jsonify(error="Gazebo service unavailable"),503
    done=threading.Event();f=client.call_async(Empty.Request());f.add_done_callback(lambda _:done.set())
    if not done.wait(5):return jsonify(error="Gazebo timeout"),504
    with lock:state["paused"]=action=="pause"
    return jsonify(success=True)
@app.get("/camera/<name>.jpg")
def camera(name):
    with lock:f=frames.get(name)
    if not f:return "",503
    return Response(f["bytes"],mimetype="image/jpeg",headers={"Cache-Control":"no-store","X-Frame-Age":str(time.time()-f["received"])})
@app.get("/stream/<name>")
def stream(name):
    if name not in ("overview","dog","drone"):return "",404
    def generate():
        last=0
        while True:
            with lock:f=frames.get(name)
            if f and f["received"]!=last:
                last=f["received"];yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+f["bytes"]+b"\r\n"
            time.sleep(.12)
    return Response(generate(),mimetype="multipart/x-mixed-replace; boundary=frame")
@app.get("/evidence/<path:name>")
def evidence(name):return send_from_directory(ROOT/"runtime"/"evidence",name)
@app.get("/api/report")
def report():
    with lock:m=copy.deepcopy(state["mission"])
    return Response(json.dumps(m,ensure_ascii=False,indent=2),mimetype="application/json",headers={"Content-Disposition":"attachment; filename=airport-mission.json"})

if __name__=="__main__":
    rclpy.init();bridge=Bridge()
    threading.Thread(target=rclpy.spin,args=(bridge,),daemon=True).start()
    threading.Thread(target=lambda:asyncio.run(ws_server()),daemon=True).start()
    event("机场仿真桥接服务已启动")
    app.run(host="0.0.0.0",port=8080,threaded=True,use_reloader=False)
