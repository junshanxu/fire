"""Hand-traced fictional 110 kV station. XY units are four metres."""
from heapq import heappop, heappush
from math import hypot
from datetime import datetime, timezone
import random

SCENARIO_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec='seconds')

METERS_PER_UNIT = 4.0
CENTER_LAT = 30.3445
CENTER_LON = 120.4415
HOME = {'x': 46, 'y': 25, 'z': 30}
# Shared vector geometry is also used for navigation, not just a picture overlay.
SEGMENTS = [
    ((25,33),(88,33)), ((88,33),(88,74)), ((88,74),(25,74)), ((25,74),(25,33)),
    ((46,25),(46,33)), ((70,25),(70,33)), ((88,33),(95,33)),
    ((34,33),(34,40)), ((34,40),(82,40)), ((82,40),(82,70)),
    ((34,40),(34,55)), ((34,55),(82,55)), ((34,70),(82,70)),
    ((34,55),(25,55)), ((34,70),(25,70)), ((82,55),(88,55)),
    ((82,70),(88,70)), ((18,44),(25,44)), ((18,59),(25,59)),
    ((18,70),(25,70)), ((40,70),(40,74)), ((57,70),(57,74)),
]
# Fictional peripheral access lanes, connected to the site only at the east gate.
EXTERIOR_SEGMENTS = [((95,33),(130,33)), ((130,0),(130,100)),
                     ((130,100),(-20,100)), ((-20,100),(-20,0)), ((-20,0),(130,0))]
BUILDINGS = [
    {'id':'water','name':'消防水池','bounds':[9,26,19,38],'fill':'#e59b87'},
    {'id':'pump','name':'消防泵房','bounds':[9,39,17,46],'fill':'#d68c74'},
    {'id':'aux','name':'辅助用房','bounds':[9,53,17,63],'fill':'#a7b7c5'},
    {'id':'reactor','name':'电抗器室','bounds':[9,66,17,74],'fill':'#a7b7c5'},
    {'id':'oil','name':'事故油池','bounds':[36,43,42,51],'fill':'#75adc1'},
    {'id':'t1','name':'1号主变','bounds':[45,43,51,52],'fill':'#78b9d2'},
    {'id':'t2','name':'2号主变','bounds':[56,43,62,52],'fill':'#78b9d2'},
    {'id':'t3','name':'3号主变','bounds':[66,43,72,52],'fill':'#78b9d2'},
    {'id':'gis','name':'110kV GIS区','bounds':[75,43,81,52],'fill':'#8bb8dc'},
    {'id':'switch','name':'配电装置楼','bounds':[34,57,82,67],'fill':'#95a7b8'},
]

def site_geometry():
    return {'name':'虚构110kV变电站','bounds':[5,20,96,80], 'roads':SEGMENTS,
            'buildings':BUILDINGS, 'exterior_roads':EXTERIOR_SEGMENTS, 'meters_per_unit':METERS_PER_UNIT,
            'points':[{'name':'充电停靠 A','x':46,'y':25}, {'name':'充电停靠 B','x':70,'y':25},
                      {'name':'消防沙箱','x':25,'y':25}, {'name':'应急集合点','x':87,'y':25},
                      {'name':'大门','x':95,'y':33}]}

def cells():
    result=set()
    for (x1,y1),(x2,y2) in SEGMENTS + EXTERIOR_SEGMENTS:
        for x in range(min(x1,x2),max(x1,x2)+1):
            for y in range(min(y1,y2),max(y1,y2)+1): result.add((x,y))
    return result

def ground_route(stops):
    accessible=cells(); result=[]
    for a,b in zip(stops,stops[1:]):
        start=(round(a['x']),round(a['y'])); goal=(round(b['x']),round(b['y']))
        if start not in accessible or goal not in accessible:
            raise ValueError('地面检查点必须设置在站内或外围通道上')
        queue=[(0,start)]; costs={start:0}; parents={start:None}
        while queue:
            _,p=heappop(queue)
            if p==goal: break
            for q in ((p[0]+1,p[1]),(p[0]-1,p[1]),(p[0],p[1]+1),(p[0],p[1]-1)):
                value=costs[p]+1
                if q in accessible and value<costs.get(q,float('inf')):
                    costs[q]=value; parents[q]=p
                    heappush(queue,(value+hypot(q[0]-goal[0],q[1]-goal[1]),q))
        if goal not in parents: raise ValueError('站内通道不连通')
        leg=[]; p=goal
        while p is not None: leg.append({'x':p[0],'y':p[1],'z':30}); p=parents[p]
        result.extend(list(reversed(leg)) if not result else list(reversed(leg))[1:])
    return result

def plan_station_route(task,resource):
    route=task.get('route') or {}; start=resource.get('position') or HOME
    # A route variant changes on every re-auction.  It only permutes valid
    # inspection points and never changes the task boundary or road graph.
    waypoints=[dict(point) for point in (route.get('waypoints') or [])]
    variant=str(task.get('_route_variant') or '0')
    rng=random.Random(f"{task.get('id','task')}:{resource.get('id','resource')}:{variant}")
    rng.shuffle(waypoints)
    altitude=round(30+rng.uniform(34,46),1) if resource.get('type')=='drone' else 30
    stops=[start,*waypoints,HOME]
    if resource.get('type')=='drone':
        # Explicit takeoff, inspection legs, and landing at the charging bay.
        path=[{**dict(start),'z':max(30,float(start.get('z',30)))}, *[{**p,'z':altitude} for p in stops],dict(HOME)]
    else: path=ground_route(stops)
    distance=sum(hypot((b['x']-a['x'])*4,(b['y']-a['y'])*4,b.get('z',30)-a.get('z',30)) for a,b in zip(path,path[1:]))
    return {'algorithm':'站内与外围通道 A*' if resource.get('type')!='drone' else '巡检航点与起降航段',
            'path':path,'road_path':path if resource.get('type')!='drone' else [],
            'execution_path':path,'execution_source':'substation','meters_per_unit':4,
            'coordinate_system':'站区 XY 每单位4m；Z海拔m','home':dict(HOME),
            'waypoint_order':[p['id'] for p in waypoints], 'waypoints':waypoints,
            'route_variant':variant,
            'cruise_altitude_m':altitude if resource.get('type')=='drone' else 30,
            'speed_factor':round(rng.uniform(.9,1.1),3),
            'path_cost':round(distance/4,2),'distance_m':round(distance,2),'ascent_m':round(max(0,altitude-30),1) if resource.get('type')=='drone' else 0,
            'elevation_range_m':[30,altitude if resource.get('type')=='drone' else 30], 'obstacle_cells':0}

def sample_tasks():
    definitions=[
        ('transformer','主变红外测温','robot',['thermal'],[(46,55,'1号主变测温位'),(61,55,'2号主变测温位'),(74,55,'3号主变测温位')]),
        ('gis','GIS设备状态巡检','robot',['rgb_camera','gas'],[(82,40,'GIS北侧压力表'),(82,55,'GIS南侧气体检测')]),
        ('fire','消防设施人工复核','team',['manual_inspection'],[(18,44,'消防泵房门口'),(25,33,'消防沙箱'),(18,59,'辅助用房门口'),(18,70,'电抗器室门口')]),
        ('air','站区上空设备巡查','drone',['aerial_camera','thermal'],[(49,40,'1号主变上方'),(61,40,'2号主变上方'),(74,40,'3号主变上方'),(82,46,'GIS屋面')]),
        ('oil','紧急事故油池渗漏复核','robot',['rgb_camera'],[(34,48,'事故油池观察位'),(34,55,'排油通道复核位')]),
        ('perimeter','站外围界与通道巡检','robot',['rgb_camera','thermal'],[(130,33,'东门外通道'),(130,100,'东南围界'),(-20,100,'西南围界'),(-20,0,'西北围界'),(130,0,'东北围界')]),
        ('outer-air','无人机外围巡线','drone',['aerial_camera','thermal'],[(46,18,'北侧进线西段'),(78,18,'北侧进线进站'),(106,26,'东侧出线'),(124,26,'东侧出线末端')]),
    ]
    tasks=[]
    for key,name,kind,capabilities,points in definitions:
        route={'route_id':f'grid-{key}','name':name,'start':dict(HOME),'end':dict(HOME),
               'waypoints':[{'id':label,'x':x,'y':y,'z':30} for x,y,label in points], 'distance_m':650}
        tasks.append({'id':f'grid-{key}','name':name,'type':kind,'station':'dispatch-pool','status':'待调度',
                      'executor':'','progress':'0%','time':'','created_at':SCENARIO_STARTED_AT,'route_id':route['route_id'],'route':route,
                      'points':' → '.join(p['id'] for p in route['waypoints']),
                      'requirements':{'capabilities':capabilities,'terrain':'outdoor' if kind=='drone' else 'flat','min_width_m':1.2,'max_slope_deg':5,
                                      'allowed_resource_types':['drone'] if kind=='drone' else (['person'] if kind=='team' else ['robot','dog'])}})
    return tasks
