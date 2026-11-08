'use strict';
// A single media clock drives the camera atlas, captured positions and task state.
// No backend calls are made: this file can be opened directly from disk.
const DATA = JSON.parse(document.getElementById('session-data').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const COL = {dog:'#f4c467',drone:'#60dec7',amr:'#7cb4ff'};
const ICON = {dog:'⌁',drone:'✣',amr:'▣'};
const PHASE = {queued:'待命',inspect:'地面初检',air:'空中复核',queue:'等待运力',transport:'物资配送',handoff:'交接确认',return:'联合返航',completed:'工单闭环'};
const RANK = {queued:-1,inspect:0,air:1,queue:2,transport:2,handoff:3,return:4,completed:5};
const video = $('#media'), main = $('#overview').getContext('2d');
const dogCam = $('#dog-camera').getContext('2d'), droneCam = $('#drone-camera').getContext('2d');
let started = false, selected = null, view = 'overview', ready = false, lastKey = '', lastEvidence = '', tickAt = 0;
const duration = DATA.frames.length / DATA.fps;
const fmt = s => Math.floor(Math.max(0,s)/60).toString().padStart(2,'0')+':'+Math.floor(Math.max(0,s)%60).toString().padStart(2,'0');
const text = i => DATA.strings[i] || '';

function frame() {
  return DATA.frames[Math.min(DATA.frames.length-1, Math.max(0, Math.floor(video.currentTime*DATA.fps)))];
}
function snapshot() {
  const f = frame();
  const devices = DATA.devices.map((d,i) => {
    const v = f.d[i];
    return {...d, pose:{x:v.p[0],y:v.p[1],z:v.p[2],speed:v.p[3],yaw:v.p[4]},
      moving:started && !video.paused && v.m, mode:!started?'待命':video.paused && !video.ended?'已暂停':text(v.o),
      action:started?text(v.a):'等待联合作业', target:started?v.t:null, workcell:v.c};
  });
  const cells = DATA.cells.map((c,i)=>({...c,phase:started?f.c[i].p:'queued',detail:started?text(f.c[i].d):'地面到点后开放空中复核，复核完成后分配配送车辆。',amr:started?f.c[i].a:null}));
  return {f, devices, cells, done:started && f.done, t:started?video.currentTime:0};
}
function project(x,y,z) {
  const c=DATA.camera, dx=x-c.position[0],dy=y-c.position[1],dz=z-c.position[2];
  const cp=Math.cos(c.pitch),sp=Math.sin(c.pitch),cy=Math.cos(c.yaw),sy=Math.sin(c.yaw);
  const depth=cp*cy*dx+cp*sy*dy-sp*dz;
  if(depth<.1)return null;
  const focal=c.width/(2*Math.tan(c.hfov/2));
  return [c.width/2+focal*(sy*dx-cy*dy)/depth,c.height/2-focal*(sp*cy*dx+sp*sy*dy+cp*dz)/depth];
}
function drawCameras() {
  if(video.readyState<2)return;
  // The atlas has the overview above two synchronized close-up cameras.
  const crop=view==='overview'?[0,0,960,540]:view==='dog'?[0,540,480,270]:[480,540,480,270];
  main.drawImage(video,...crop,0,0,960,540);
  dogCam.drawImage(video,0,540,480,270,0,0,480,270);
  droneCam.drawImage(video,480,540,480,270,0,0,480,270);
}
function drawOverlay(s) {
  $('#overlay').hidden=view!=='overview';
  if(view!=='overview')return;
  const parts=[], occupied=[];
  for(const d of s.devices){
    const p=project(d.pose.x,d.pose.y,d.pose.z+(d.type==='amr'?.12:.08));
    if(!p)continue;
    const [x,y]=p,col=COL[d.type];
    if($('#routes').checked && d.target){
      const t=project(d.target[0],d.target[1],d.target[2]??.1);
      if(t)parts.push(`<path d="M${x} ${y} L${t[0]} ${t[1]}" stroke="${col}" stroke-width="1.5" stroke-dasharray="6 5" opacity=".8"/><circle cx="${t[0]}" cy="${t[1]}" r="5" fill="none" stroke="${col}"/>`);
    }
    const bx=Math.min(840,Math.max(5,x-55)); let by=Math.min(492,Math.max(48,y+(d.type==='amr'?19:-54)));
    for(const r of occupied)if(Math.abs(bx-r[0])<115&&Math.abs(by-r[1])<36)by=Math.max(48,by-38);
    occupied.push([bx,by]);
    parts.push(`<g class="agent-marker ${d.moving?'is-moving ':''}${selected===d.id?'is-selected':''}" data-device="${d.id}" role="button" tabindex="0" aria-label="${d.label} ${esc(d.mode)}"><title>${esc(d.label+' · '+d.action)}</title><circle class="pulse-ring" cx="${x}" cy="${y}" r="16"/><circle cx="${x}" cy="${y}" r="9" fill="none" stroke="${col}" stroke-width="2"/><circle cx="${x}" cy="${y}" r="3" fill="${col}"/><path d="M${x} ${y} L${bx+55} ${by+(d.type==='amr'?0:32)}" stroke="${col}" opacity=".75"/><rect x="${bx}" y="${by}" width="112" height="32" rx="5" fill="#091623" fill-opacity=".95" stroke="${d.moving?'#b8ee72':col}"/><text x="${bx+8}" y="${by+13}" fill="${col}" font-size="11" font-weight="700">${d.label}</text><text x="${bx+8}" y="${by+26}" fill="${d.moving?'#b8ee72':'#e1e9f1'}" font-size="10">${esc(d.mode)}${d.moving?' ▶':''}</text></g>`);
  }
  $('#overlay').innerHTML=parts.join('');
}
function render(force=false) {
  const s=snapshot(), f=s.f, moving=s.devices.filter(d=>d.moving), done=s.cells.filter(c=>c.phase==='completed').length;
  const key=[Math.floor(video.currentTime*DATA.fps),started,video.paused,video.ended,selected,view].join('|');
  if(!force && key===lastKey)return;
  lastKey=key;
  const records=started?DATA.evidence.filter(e=>e.at<=s.t+.05):[];
  $('#connection').textContent=!ready?'正在加载场景':!started?'● 场景就绪':s.done?'✓ 本轮作业完成':video.paused?'Ⅱ 作业已暂停':'● 联合作业执行中';
  $('#clock').textContent=fmt(started?f.clock:0);
  $('#mission-code').textContent=started?'T1 / '+DATA.mission:'T1 / READY';
  $('#overview-metrics').innerHTML=[['设备总数','08','3 DOG · 3 UAV · 2 AMR'],['当前运动',String(moving.length).padStart(2,'0'),moving.map(d=>d.label).join(' · ')||'全队驻留 / 等待调度'],['已完成任务',String(started?f.completed:0).padStart(2,'0'),'巡检、配送与返航任务'],['工单闭环',done+' / 3','配电设备 · 行李输送 · 安防设施']].map((v,i)=>`<div><small>${v[0]}</small><strong class="${i===1?'motion-count':''}">${v[1]}</strong><span>${esc(v[2])}</span></div>`).join('');
  $('#scene-live').textContent=!started?'8 台设备已就绪':s.done?'✓ 三处工单闭环 · 全队归位':video.paused?'Ⅱ 当前作业已暂停':moving.length?'运动中 '+moving.length+' 台 · '+moving.map(d=>d.label).join(' / '):'设备驻留 · 等待联动条件';
  $('#scene-bottom').textContent=s.done?'巡检、复核、交接与归位全部完成':s.cells.some(c=>c.phase==='handoff')?'双方到位 · 连续驻留后确认物资交接':s.cells.some(c=>c.phase==='transport')?'复核结果已确认 · 运输机器人正在配送':s.cells.some(c=>c.phase==='air')?'机器狗到点 · 对应无人机分层复核':'机器狗初检 → 无人机复核 → 运输交接 → 全队归位';
  $('#cells').innerHTML=s.cells.map(c=>`<article class="panel workcell ${c.phase==='completed'?'done':''}"><div class="workcell-title"><b>${esc(c.name)}</b><span>${PHASE[c.phase]}</span></div><div class="dependency-chain">${['初检','复核','配送','交接'].map((n,i)=>`<span class="${RANK[c.phase]>i?'done':RANK[c.phase]===i?'current':''}">${RANK[c.phase]>i?'✓ ':''}${n}</span>${i<3?'<i>→</i>':''}`).join('')}</div><p>${esc(c.detail)}</p><div class="workcell-team">${DATA.devices.find(d=>d.id===c.dog).label} → ${DATA.devices.find(d=>d.id===c.drone).label} → ${c.amr?DATA.devices.find(d=>d.id===c.amr)?.label:'等待运力分配'}</div></article>`).join('');
  const ordered=[...s.devices].sort((a,b)=>({dog:0,drone:1,amr:2}[a.type]-{dog:0,drone:1,amr:2}[b.type])||a.label.localeCompare(b.label));
  $('#devices').innerHTML=ordered.map(d=>`<button class="panel device ${d.moving?'active ':''}${selected===d.id?'selected':''}" style="--device-color:${COL[d.type]}" data-device="${d.id}"><div class="device-top"><b>${ICON[d.type]} ${d.label}</b><span class="device-status ${d.moving?'moving':''}">${d.moving?'● ':''}${esc(d.mode)}</span></div><div class="device-action">${esc(d.action)}</div><div class="device-pos">${d.pose.speed.toFixed(2)} <small>m/s</small><span>${d.type==='drone'?'高度 '+d.pose.z.toFixed(1)+' m':(d.workcell||'仓位')+' 区域'}</span></div></button>`).join('');
  const d=s.devices.find(x=>x.id===selected);
  $('#selected-info').innerHTML=d?`<b style="color:${COL[d.type]}">${d.label}</b><span>${esc(d.mode+' · '+d.action)}</span><small>X ${d.pose.x.toFixed(2)} / Y ${d.pose.y.toFixed(2)} / Z ${d.pose.z.toFixed(2)} m</small>`:'点击画面标签或设备卡，查看设备位置和当前任务。';
  $('#task-count').textContent=String(started?f.tasks:0).padStart(2,'0');
  $('#record-count').textContent=String(records.length).padStart(2,'0');
  $('#start').disabled=!ready || (started && !video.paused && !video.ended);
  $('#start').textContent=s.done?'↻ 再运行一轮':started && video.paused?'▶ 继续联合作业':started?'联合作业执行中':'▶ 启动联合作业';
  $('#pause').disabled=!started||video.paused||s.done;
  $('#reset').disabled=!started;
  $('#play-toggle').disabled=!ready;
  $('#play-toggle').textContent=video.paused?'▶':'Ⅱ';
  $('#play-toggle').setAttribute('aria-label',video.paused?'开始播放':'暂停播放');
  $('#seek').value=video.currentTime;
  $('#timecode').textContent=fmt(video.currentTime)+' / '+fmt(duration);
  const speed=Number($('#speed').value);
  $('#message').textContent=s.done?'三处工单全部闭环。可查看现场记录、导出报告或再次运行。':!started?`全队就绪。当前 ${speed}× 节奏，一轮约 ${Math.ceil(duration/speed)} 秒。`:video.paused?'已暂停。可以选择节点查看，或继续当前作业。':'联合作业执行中，各区域按前置条件推进。';
  const stepNames=['三点地面初检','分层空中复核','共享运力与条件交接','全队返航与归档'];
  const details=['三只机器狗分别到场，完成地面检查。','对应无人机到位悬停，开放后续配送。','两台 AMR 服务三处工单，双方到位后交接。','8 台设备归位，任务记录和现场图像归档。'];
  $('#steps').innerHTML=stepNames.map((name,i)=>{
    const status=!started?'pending':text(f.steps[i]);
    return `<div class="step ${status}"><span class="step-num">${status==='completed'?'✓':i+1}</span><div><b>${name}</b><small>${details[i]}</small></div></div>`;
  }).join('');
  $('#mission-result').innerHTML=s.done?'<div class="result">✓ 12 个任务完成 · 9 张现场记录 · 8 台设备归位</div>':'';
  const ek=records.map(e=>e.id).join(',');
  if(ek!==lastEvidence){lastEvidence=ek;$('#evidence').innerHTML=records.map(e=>`<button class="evidence-item" data-evidence="${e.id}"><img src="${e.image}" loading="lazy" alt="${esc(e.label)}"><span>${esc(e.label)} ↗</span></button>`).join('')||'<p>作业开始后，现场记录随任务进度归档。</p>';}
  const logs=started?DATA.events.filter(e=>e.at<=s.t+.05).slice(-12).reverse():[];
  $('#events').innerHTML=logs.length?logs.map(e=>`<div class="event"><time>T+ ${fmt(e.at)}</time>${esc(e.text)}</div>`).join(''):'<div class="event">设备已准备就绪，等待启动联合作业。</div>';
  document.querySelectorAll('[data-jump]').forEach(b=>b.classList.toggle('passed',started&&Number(b.dataset.jump)<=s.t));
  drawOverlay(s);
}
function setView(v) {
  view=v;
  document.querySelectorAll('.view-tabs [data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view===v));
  $('#view-title').textContent={overview:'航站楼 · 三维作业视图',dog:'DOG-01 · 前视作业视图',drone:'UAV-01 · 空中作业视图'}[v];
  drawCameras(); render(true);
}
async function play() {
  if(!ready)return;
  if(video.ended || snapshot().done){video.currentTime=0;}
  started=true;video.playbackRate=Number($('#speed').value);
  try {await video.play();render(true);} catch(e) {$('#message').textContent='播放被浏览器阻止，请再次点击启动。';}
}
function pause(){video.pause();render(true);}
function reset(){video.pause();started=false;video.currentTime=0;lastEvidence='reset';render(true);}
function jump(seconds){video.pause();started=true;video.currentTime=Math.min(duration-.08,Math.max(0,seconds));render(true);}
function downloadReport() {
  const s=snapshot();
  const report={format:'airport-ops-report-v1',source:'recorded_3d_session',mission:DATA.mission,playhead_seconds:s.t,task_time_seconds:started?s.f.clock:0,devices:s.devices,zones:s.cells,task_ids:started?DATA.taskIds.slice(0,s.f.tasks):[],completed_tasks:started?s.f.completed:0,evidence:started?DATA.evidence.filter(e=>e.at<=s.t).map(({image,...e})=>e):[]};
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='airport-ops-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function showEvidence(id){const e=DATA.evidence.find(x=>x.id===id);if(!e)return;$('#evidence-image').src=e.image;$('#evidence-label').textContent=e.label;$('#evidence-modal').showModal();}
$('#start').addEventListener('click',play);$('#pause').addEventListener('click',pause);$('#reset').addEventListener('click',reset);
$('#play-toggle').addEventListener('click',()=>video.paused?play():pause());
$('#seek').max=duration-.08;$('#seek').addEventListener('input',e=>jump(Number(e.target.value)));
$('#speed').addEventListener('change',e=>{video.playbackRate=Number(e.target.value);render(true);});
$('#routes').addEventListener('change',()=>render(true));$('#export').addEventListener('click',downloadReport);
$('#fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('#scene').requestFullscreen();}catch(e){$('#message').textContent='当前浏览器不支持全屏，请使用窗口最大化。';}});
$('#close-modal').addEventListener('click',()=>$('#evidence-modal').close());
$('#evidence-modal').addEventListener('click',e=>{if(e.target===$('#evidence-modal'))$('#evidence-modal').close();});
document.addEventListener('click',e=>{const b=e.target.closest('[data-device],[data-view],[data-jump],[data-evidence]');if(!b)return;if(b.dataset.device){selected=b.dataset.device;render(true);}if(b.dataset.view)setView(b.dataset.view);if(b.dataset.jump!==undefined)jump(Number(b.dataset.jump));if(b.dataset.evidence)showEvidence(b.dataset.evidence);});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('.agent-marker')){selected=e.target.dataset.device;render(true);}if(e.code==='Space'&&!e.target.closest('button,input,select,a,dialog')){e.preventDefault();video.paused?play():pause();}});
$('#chapters').innerHTML=DATA.chapters.map((c,i)=>`<button data-jump="${c.at}"><span class="chapter-num">${String(i+1).padStart(2,'0')}</span><span>${c.name}<small>${c.note}</small></span><time>${fmt(c.at)}</time></button>`).join('');
video.playbackRate=4;
video.addEventListener('loadeddata',()=>{ready=true;$('#load-state').hidden=true;drawCameras();render(true);});
video.addEventListener('seeked',()=>{drawCameras();render(true);});
video.addEventListener('ended',()=>render(true));
video.addEventListener('error',()=>{$('#load-state').innerHTML='<b>画面加载失败</b><small>请使用最新版 Chrome 或 Edge 打开此文件。</small>';$('#connection').textContent='画面未就绪';});
function tick(now){if(now-tickAt>65){tickAt=now;drawCameras();render();}requestAnimationFrame(tick);}
render(true);requestAnimationFrame(tick);
if(video.readyState>=2){ready=true;$('#load-state').hidden=true;drawCameras();render(true);}
