"""Costs computed from the same simulated motion and SOC as device telemetry.
All capacities and consumption variation are demo assumptions, not vendor specs.
"""
from datetime import datetime, timezone
from math import hypot, sin, cos, pi

CAPACITY_KWH = {'robot': 1.5, 'dog': .6, 'drone': .3, 'person': 0}


def resource_type(row):
    return row.get('resource_type') or {'ROBOT': 'robot', 'DOG': 'dog', 'DRONE': 'drone', 'PERSON': 'person'}.get(str(row.get('resource_id', '')).split('-')[0], 'robot')


def path_stats(path, meters_per_unit=35):
    distance = ascent = 0
    for a,b in zip(path,path[1:]):
        za,zb=a.get('z',a.get('elevation_m',0)),b.get('z',b.get('elevation_m',0))
        distance += hypot((b['x']-a['x'])*meters_per_unit,(b['y']-a['y'])*meters_per_unit,zb-za)
        ascent += max(0,zb-za)
    return {'distance_m': distance, 'ascent_m': ascent}


def partial_stats(path, progress, meters_per_unit=35):
    total=path_stats(path,meters_per_unit)
    left=total['distance_m']*progress
    ascent=0
    for a,b in zip(path,path[1:]):
        za,zb=a.get('z',a.get('elevation_m',0)),b.get('z',b.get('elevation_m',0))
        length=hypot((b['x']-a['x'])*meters_per_unit,(b['y']-a['y'])*meters_per_unit,zb-za)
        fraction=min(1,left/length) if length else 0
        ascent+=max(0,zb-za)*fraction
        left-=length*fraction
        if left<=0:break
    return {'distance_m':total['distance_m']*progress,'ascent_m':ascent}


def plan_estimate(resource, route, energy_pct, duration=120):
    path=route.get('execution_path') or route.get('path') or []
    stats=path_stats(path,route.get('meters_per_unit',35))
    return {**stats, 'energy_kwh': CAPACITY_KWH.get(resource.get('type'),0)*float(energy_pct or 0)/100,
            'duration_seconds': duration, 'battery_capacity_kwh': CAPACITY_KWH.get(resource.get('type'),0), 'source': '遥测'}


def execution_metrics(row, now=None):
    from platform_app.services.dispatch_service import dispatch_progress, dispatch_path, route_meters_per_unit, RETURN_SECONDS
    now=now or datetime.now(timezone.utc)
    progress=row.get('interrupted_progress',0) if row.get('incident_at') else dispatch_progress(row,now)
    main=dict(row);main.pop('incident_at',None)
    main_units=route_meters_per_unit(main);stats=path_stats(dispatch_path(main),main_units);length=max(1,stats['distance_m'])
    duration=float(row.get('simulation_duration_seconds') or 120)
    capacity=CAPACITY_KWH.get(resource_type(row),0)
    budget=capacity*float(row.get('estimated_energy_pct') or 0)/100
    base=float(row.get('consumption_factor',1))
    factor=base+.1*sin(pi*progress)
    used={**partial_stats(dispatch_path(main),progress,main_units),'duration_seconds':duration*progress,'energy_kwh':budget*(base*progress+.1*(1-cos(pi*progress))/pi)}
    remaining={k:0.0 for k in used}
    if row.get('incident_at'):
        started=datetime.fromisoformat(row['incident_at'].replace('Z','+00:00'))
        back_duration=float(row.get('return_duration_seconds') or RETURN_SECONDS)
        back_progress=min(1,max(0,(now-started).total_seconds()/max(1,back_duration)))
        back_units=route_meters_per_unit(row,True);back=path_stats(dispatch_path(row),back_units)
        totals={**back,'duration_seconds':back_duration,'energy_kwh':budget*back['distance_m']/length*factor}
        partial=partial_stats(dispatch_path(row),back_progress,back_units)
        for k in used:
            used[k]+=partial[k] if k in partial else totals[k]*back_progress
            remaining[k]=totals[k]*(1-back_progress)
        remaining['ascent_m']=back['ascent_m']-partial['ascent_m']
    else:
        for k,total in {**stats,'duration_seconds':duration,'energy_kwh':budget*factor}.items():
            remaining[k]=total*(1-progress)
        remaining['ascent_m']=stats['ascent_m']-used['ascent_m']
    forecast={k:used[k]+remaining[k] for k in used}
    return {'used':used,'remaining':remaining,'forecast':forecast,'baseline':{**stats,'duration_seconds':duration,'energy_kwh':budget},'factor':factor,'progress':progress}


def task_costs(tasks):
    from platform_app.services.dispatch_service import list_dispatches
    history=list_dispatches();by_task={}
    for row in history:by_task.setdefault(row['task_id'],[]).append(row)
    now=datetime.now(timezone.utc)
    for task in tasks:
        attempts=by_task.get(task['id'],[])
        if not attempts:continue
        metrics=[execution_metrics(row,now) for row in attempts]
        task['cost']={key:{unit:sum(m[key][unit] for m in metrics) for unit in ('energy_kwh','distance_m','duration_seconds','ascent_m')} for key in ('used','remaining','forecast')}
        task['cost'].update({'baseline':metrics[-1]['baseline'],'reassignments':max(0,len(attempts)-1),'updated_at':now.isoformat(),'source':'遥测'})
        task['cost']['rates']={unit:sum(m['remaining'][unit]/max(1,m['remaining']['duration_seconds']) for m in metrics if m['remaining']['duration_seconds']>0) for unit in ('energy_kwh','distance_m','duration_seconds','ascent_m')}
    return tasks
