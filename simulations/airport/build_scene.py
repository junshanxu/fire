"""Extend the official Open-RMF airport world; preserve the generated building."""
from pathlib import Path
import copy
import xml.etree.ElementTree as E
import yaml
from signs import decorate
from fleet_config import DEVICES, CELLS, POINTS, EDGES, CAMERA

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "runtime"
OUT.mkdir(exist_ok=True)

def add(parent, tag, text=None, **attrib):
    e = E.SubElement(parent, tag, attrib)
    if text is not None: e.text = str(text)
    return e

def shape(link, name, size, pose, color, collision=False, cylinder=False):
    v = add(link, "visual", name=name)
    add(v, "pose", pose)
    g = add(v, "geometry")
    if cylinder:
        c = add(g, "cylinder"); add(c, "radius", size[0]); add(c, "length", size[1])
    else:
        add(add(g, "box"), "size", size)
    m = add(v, "material"); add(m, "ambient", color); add(m, "diffuse", color)
    if collision:
        c = add(link, "collision", name=name+"_collision")
        add(c, "pose", pose); c.append(E.fromstring(E.tostring(g)))
    return v

def body(model, name, mass=1, gravity=False):
    l = add(model, "link", name=name)
    add(l, "gravity", str(gravity).lower())
    i = add(l, "inertial"); add(i, "mass", mass)
    inertia=add(i,"inertia")
    for k in ("ixx","iyy","izz"): add(inertia,k,mass*0.04)
    for k in ("ixy","ixz","iyz"): add(inertia,k,0)
    return l

def camera(link, name, pose, wide=False):
    s=add(link,"sensor",name=name,type="camera");add(s,"pose",pose)
    add(s,"always_on","true");add(s,"update_rate",3)
    c=add(s,"camera",name=name);add(c,"horizontal_fov",1.1 if wide else 1.35)
    i=add(c,"image");add(i,"width",960 if wide else 480);add(i,"height",540 if wide else 270);add(i,"format","R8G8B8")
    clip=add(c,"clip");add(clip,"near",0.1);add(clip,"far",350)
    p=add(s,"plugin",name=name+"_ros",filename="libgazebo_ros_camera.so")
    ros=add(p,"ros");add(ros,"namespace","/sensors/"+name)
    add(p,"camera_name",name);add(p,"frame_name",name+"_optical")

def joint(m,name,parent,child,pose,axis):
    j=add(m,"joint",name=name,type="revolute");add(j,"parent",parent);add(j,"child",child)
    add(j,"pose",pose);a=add(j,"axis");add(a,"xyz",axis)
    limit=add(a,"limit");add(limit,"lower",-100000);add(limit,"upper",100000)
    return j

tree=E.parse(ROOT/"generated/airport/airport.world")
w=tree.getroot().find("world")
# Preserve the full architecture and furnishings; run two focused demo fleets.
for inc in list(w.findall("include")):
    if inc.findtext("uri","").split("://")[-1] in ("TinyRobot","DeliveryRobot","CleanerBotA","CleanerBotE","Caddy","TeleportDispenser","TeleportIngestor"):
        w.remove(inc)
for actor in list(w.findall("actor")): w.remove(actor)
for plug in list(w.findall("plugin")):
    if "crowd" in plug.get("name","").lower(): w.remove(plug)
physics=w.find("physics")
if physics is None: physics=add(w,"physics",name="default",type="ode")
for key,value in (("max_step_size",0.004),("real_time_update_rate",250),("real_time_factor",1)):
    e=physics.find(key)
    if e is None: e=add(physics,key)
    e.text=str(value)
gui=w.find("gui")
if gui is None: gui=add(w,"gui")
for p in list(gui.findall("plugin")): gui.remove(p)
cam=gui.find("camera")
if cam is None: cam=add(gui,"camera",name="gui_camera")
cam.find("pose").text="138 -63 23 0 0.78 1.57"
scene=w.find("scene")
if scene is None: scene=add(w,"scene")
for key,value in (("ambient","0.65 0.65 0.65 1"),("background","0.76 0.84 0.91 1"),("shadows","false")):
    e=scene.find(key)
    if e is None:e=add(scene,key)
    e.text=value

dog=add(w,"model",name="inspection_dog");add(dog,"pose","148 -36.5 0.62 0 0 -1.57")
b=body(dog,"body",22)
shape(b,"shell","0.85 0.38 0.28","0 0 0 0 0 0","0.95 0.60 0.10 1",True)
shape(b,"spine","0.55 0.25 0.05","-0.05 0 0.17 0 0 0","0.12 0.14 0.18 1")
shape(b,"head","0.24 0.32 0.22","0.50 0 0.02 0 0 -0.08","0.12 0.14 0.18 1")
shape(b,"eyes","0.025 0.23 0.05","0.63 0 0.05 0 0 0","0.15 0.9 1 1")
shape(b,"lidar",(0.095,0.10),"0.25 0 0.23 0 0 0","0.12 0.14 0.18 1",cylinder=True)
camera(b,"dog","0.64 0 0.1 0 0.08 0")
for i,(x,y) in enumerate(((.29,.25),(.29,-.25),(-.29,.25),(-.29,-.25))):
    upper=body(dog,"upper_"+str(i),0.02)
    add(upper,"pose",f"{x} {y} -0.15 0 0 0")
    shape(upper,"upper","0.09 0.09 0.30","0 0 0 0 0 0","0.18 0.21 0.26 1")
    lower=body(dog,"lower_"+str(i),0.02)
    add(lower,"pose",f"{x} {y} -0.44 0 0 0")
    shape(lower,"lower","0.065 0.065 0.27","0 0 0 0 0 0","0.8 0.83 0.87 1")
    shape(lower,"paw","0.12 0.1 0.08","0 0 -0.15 0 0 0","0.1 0.12 0.14 1")
    joint(dog,"hip_"+str(i),"body","upper_"+str(i),"0 0 0.15 0 0 0","0 1 0")
    joint(dog,"knee_"+str(i),"upper_"+str(i),"lower_"+str(i),"0 0 0.135 0 0 0","0 1 0")
p=add(dog,"plugin",name="dog_motion",filename="libairport_motion.so");add(add(p,"ros"),"namespace","/dog")
add(p,"flying","false")

def clone_agent(source,name,pose,namespace):
    clone=copy.deepcopy(source);clone.set("name",name)
    pose_node=clone.find("pose")
    if pose_node is not None:pose_node.text=pose
    for plug in clone.findall(".//plugin"):
        ros=plug.find("ros")
        if ros is not None:
            ns=ros.find("namespace")
            if ns is not None:ns.text="/"+namespace
        if plug.get("name") in ("dog_motion","flight_motion"):
            plug.set("name",plug.get("name")+"_"+name)
    # Additional agents publish odometry but do not consume camera bandwidth.
    for link in clone.findall("link"):
        for sensor in list(link.findall("sensor")):link.remove(sensor)
    return clone

for name in ("inspection_dog_2","inspection_dog_3"):
    d=DEVICES[name];x,y,z=d["home"]
    w.append(clone_agent(dog,name,f"{x} {y} {z} 0 0 -1.57",d["namespace"]))

dx,dy,dz=DEVICES["inspection_drone"]["home"]
drone=add(w,"model",name="inspection_drone");add(drone,"pose",f"{dx} {dy} {dz} 0 0 0")
b=body(drone,"body",2,True)
shape(b,"shell","0.42 0.32 0.13","0 0 0 0 0 0","0.12 0.19 0.24 1",True)
shape(b,"beacon",(0.06,0.04),"0 0 0.10 0 0 0","0.1 0.95 0.7 1",cylinder=True)
shape(b,"arm1","1.25 0.055 0.05","0 0 0 0 0 0.65","0.25 0.3 0.35 1")
shape(b,"arm2","1.25 0.055 0.05","0 0 0 0 0 -0.65","0.25 0.3 0.35 1")
for y in (-.20,.20):
    shape(b,"skid"+str(y),"0.62 0.035 0.035",f"0 {y} -0.23 0 0 0","0.1 0.15 0.2 1",True)
    shape(b,"strut"+str(y),"0.035 0.035 0.20",f"0 {y} -0.12 0 0 0","0.1 0.15 0.2 1")
shape(b,"gimbal",(0.07,0.09),"0.14 0 -0.13 0 1.57 0","0.1 0.9 0.7 1",cylinder=True)
camera(b,"drone","0.16 0 -0.16 0 0.90 0")
for i,(x,y) in enumerate(((.49,.37),(.49,-.37),(-.49,.37),(-.49,-.37))):
    r=body(drone,"rotor_"+str(i),0.0001,False);add(r,"pose",f"{x} {y} 0.08 0 0 0")
    shape(r,"blade","0.43 0.045 0.014","0 0 0 0 0 0","0.2 0.75 0.83 1")
    joint(drone,"rotor_joint_"+str(i),"body","rotor_"+str(i),"0 0 0 0 0 0","0 0 1")
p=add(drone,"plugin",name="flight_motion",filename="libairport_motion.so");add(add(p,"ros"),"namespace","/drone");add(p,"flying","true")
for name in ("inspection_drone_2","inspection_drone_3"):
    d=DEVICES[name];x,y,z=d["home"]
    w.append(clone_agent(drone,name,f"{x} {y} {z} 0 0 0",d["namespace"]))

# Eight independent models share their poses with controller and fleet config.
for n,d in DEVICES.items():
    x,y,z=d['home']
    if d['type']=='amr':
        inc=add(w,'include');add(inc,'uri','model://TinyRobot');add(inc,'name',n);add(inc,'pose',f'{x} {y} {z} 0 0 -1.57')
    else:
        w.find("model[@name='"+n+"']/pose").text=f'{x} {y} {z} 0 0 '+('-1.57' if d['type']=='dog' else '0')
    m=add(w,'model',name='pad_'+n);add(m,'static','true');add(m,'pose',f'{x} {y} .018 0 0 0')
    l=body(m,'body');color={'dog':'.94 .6 .12 1','drone':'.1 .7 .65 1','amr':'.17 .46 .9 1'}[d['type']]
    shape(l,'pad','1.5 1.5 .015','0 0 0 0 0 0',color)
    if d['type']=='drone':
        for xx in (-.25,.25):shape(l,'h'+str(xx),'.10 .9 .018',f'{xx} 0 .02 0 0 0','1 1 1 1')
        shape(l,'hm','.6 .10 .018','0 0 .02 0 0 0','1 1 1 1')

for c in CELLS:
    x=c['x'];m=add(w,'model',name='workcell_'+c['id']);add(m,'static','true');add(m,'pose',f'{x} -34 0 0 0 0');l=body(m,'body')
    if c['id']=='A':
        for i in range(3):
            xx=(i-1)*.85
            shape(l,'cabinet'+str(i),'.78 .65 1.65',f'{xx} 0 .825 0 0 0','.24 .32 .40 1',True)
            for z in (.5,.9,1.3):shape(l,f'light{i}_{z}', '.5 .03 .06',f'{xx} -.34 {z} 0 0 0','.1 .95 .7 1')
    elif c['id']=='B':
        shape(l,'belt','4 .8 .65','0 0 .325 0 0 0','.19 .24 .31 1',True)
        for i in range(10):shape(l,'roller'+str(i),'.06 .76 .04',f'{-1.8+i*.4} 0 .67 0 0 0','.6 .65 .7 1')
        for i in (-1,1):shape(l,'bag'+str(i),'.55 .4 .42',f'{i} 0 .88 0 0 0','.68 .42 .20 1',True)
    else:
        shape(l,'cabinet','.7 .6 1.2','0 0 .6 0 0 0','.16 .31 .40 1',True)
        shape(l,'mast','.12 .12 2.8','1 0 1.4 0 0 0','.5 .6 .65 1',True)
        shape(l,'sensor','.45 .22 .24','1 -.2 2.65 0 .3 0','.1 .8 .9 1')
    shape(l,'check_pad','1.3 1.3 .018','0 -1.5 .012 0 0 0','.55 .40 .15 1')
    shape(l,'handoff_pad','1.3 1.3 .018','0 -4 .012 0 0 0','.15 .32 .55 1')
    for side in (-2.4,2.4):
        shape(l,'bollard'+str(side),'.15 .15 .65',f'{side} -.6 .325 0 0 0','.95 .65 .15 1',True)
# Lane markings, storage pallets and service counters give the operation context.
for i in range(24):
    m=add(w,'model',name='lane_mark_'+str(i));add(m,'static','true');l=body(m,'body')
    shape(l,'stripe','.65 .07 .01',f'{124+i} -40.2 .012 0 0 0','.85 .85 .6 1')
for i in range(3):
    m=add(w,'model',name='logistics_rack_'+str(i));add(m,'static','true');l=body(m,'body')
    shape(l,'rack','1.8 .8 1.2',f'{127+i*2.2} -44 .6 0 0 0','.17 .28 .38 1',True)
    shape(l,'case','1.2 .5 .45',f'{127+i*2.2} -44 1.42 0 0 0','.25 .55 .85 1',True)
overview=add(w,'model',name='overview_camera');add(overview,'static','true')
add(overview,'pose','137 -60 22 0 0 0');b=body(overview,'body');camera(b,'overview','0 0 0 0 .80 1.57',True)
decorate(w,ROOT)
E.indent(tree);tree.write(OUT/'airport.world',encoding='utf-8',xml_declaration=True)
vertices=[[x,y,{'name':n,**({'is_charger':True,'is_parking_spot':True} if 'dock' in n else {})}] for x,y,n in POINTS]
lanes=[]
for a,b in EDGES:lanes.extend([[a,b,{}],[b,a,{}]])
(OUT/'nav_graph.yaml').write_text(yaml.safe_dump({'building_name':'airport_terminal','levels':{'L1':{'vertices':vertices,'lanes':lanes}}}))
base=yaml.safe_load(Path('/opt/rmf_ws/src/rmf_demos/rmf_demos/config/office/tinyRobot_config.yaml').read_text())
for fleet,port,speed in [('logistics',22011,.7),('inspectionDog',22012,.8)]:
    c=copy.deepcopy(base);f=c['rmf_fleet'];f['name']=fleet;f['fleet_manager']['port']=port
    f['limits']['linear']=[speed,.7];f['limits']['angular']=[.8,1.5];f['account_for_battery_drain']=False;f['reversible']=False
    f['profile']={'footprint':.5 if fleet=='inspectionDog' else .3,'vicinity':.7}
    f['task_capabilities'].update({'loop':True,'delivery':False,'finishing_request':'nothing'})
    template=next(iter(c['robots'].values()));c['robots']={}
    for n,d in DEVICES.items():
        if d.get('fleet')!=fleet:continue
        r=copy.deepcopy(template);r['rmf_config']['start']={'map_name':'L1','waypoint':d['dock'],'orientation':-1.57}
        r['rmf_config']['charger']={'waypoint':d['dock']};r['robot_config']['max_delay']=30;c['robots'][n]=r
    (OUT/(fleet+'.yaml')).write_text(yaml.safe_dump(c))
print('Generated 8 devices, three service areas and two RMF ground fleets.')