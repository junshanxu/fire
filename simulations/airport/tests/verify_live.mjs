import fs from 'node:fs/promises';
const base='http://localhost:8092';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const call=async(path,body)=>{let r=await fetch(base+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});let j=await r.json();if(!r.ok)throw Error(path+' '+r.status+' '+JSON.stringify(j));return j};
const assert=(v,m)=>{if(!v)throw Error(m)};
let s;for(let i=0;i<80;i++){s=await call('/api/status');if(s.ready)break;await sleep(1000)}assert(s.ready,'8 devices not ready');
await call('/api/mission',{});
const duplicate=await fetch(base+'/api/mission',{method:'POST'});assert(duplicate.status===409,'Duplicate mission should be rejected');
const motion={},phases=new Set();let pausedTest=false,lastPhase='',started=Date.now();
while(Date.now()-started<480000){s=await call('/api/status');for(const d of s.devices){const p=d.pose;const m=motion[d.id]??={start:[p.x,p.y,p.z],maxDistance:0,maxSpeed:0,maxZ:0};m.maxSpeed=Math.max(m.maxSpeed,p.speed);m.maxZ=Math.max(m.maxZ,p.z);m.maxDistance=Math.max(m.maxDistance,Math.hypot(p.x-m.start[0],p.y-m.start[1],p.z-m.start[2]))}
  const phase=s.mission.cells.map(c=>c.id+':'+c.phase).join(' / ');phases.add(phase);if(phase!==lastPhase){console.log(phase);lastPhase=phase}
  if(!pausedTest && s.mission.cells.some(c=>c.phase==='air')){await call('/api/physics',{action:'pause'});await sleep(1200);const a=await call('/api/status');await sleep(4500);const b=await call('/api/status');assert(b.paused,'Pause flag');assert(Math.abs(b.sim_seconds-a.sim_seconds)<.15,'Clock did not pause');assert(b.devices.length===8&&b.devices.every(d=>d.online&&!d.moving&&d.mode==='已暂停'),'Paused devices must remain visible without motion');await call('/api/physics',{action:'resume'});pausedTest=true;console.log('Pause/resume: passed')}
  if(s.mission.status==='completed')break;if(s.mission.status==='failed')throw Error(s.mission.error);await sleep(650)
}
assert(s.mission.status==='completed','Mission not completed');assert(pausedTest,'Pause test missing');assert(s.mission.task_ids.length===12,'Expected twelve RMF tasks');
const taskMap=Object.fromEntries(s.tasks.map(t=>[t.booking.id,t]));for(const id of s.mission.task_ids)assert(taskMap[id]?.status==='completed','RMF task incomplete '+id);
for(const c of s.mission.cells){assert(c.phase==='completed','Incomplete zone');assert(c.alarm.source==='scenario_injection','Alarm must be labeled simulation');const delivery=s.mission.dispatches.find(d=>d.cell===c.id&&d.target.startsWith('delivery'));assert(delivery.sim>=c.verified_at,'Dispatch occurred before air verification');const meta=s.scene.cells.find(x=>x.id===c.id);const h=c.handoff;assert(h&&h.sim>=c.handoff_started+4,'Handoff dwell missing');assert(Math.hypot(h.dog.x-meta.x,h.dog.y-meta.y)<.45,'Dog not at handoff');assert(Math.hypot(h.amr.x-meta.x,h.amr.y+38)<.45,'AMR not at handoff');assert(motion[c.drone].maxZ>=meta.altitude-.3,'UAV failed to reach altitude')}
for(const d of s.devices){assert(motion[d.id].maxDistance>1&&motion[d.id].maxSpeed>.1,'Device never moved '+d.id);assert(Math.hypot(d.pose.x-d.home[0],d.pose.y-d.home[1])<.45,'Not home '+d.id)}
assert(s.mission.evidence.length===9,'Missing evidence');
const report={passed:true,mission:s.mission.id,wall_seconds:(Date.now()-started)/1000,rmf_tasks:12,evidence:9,pause_resume:true,duplicate_rejected:true,devices:motion,phase_transitions:[...phases]};
await fs.writeFile('runtime/reports/verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
