/* One Xiasha map. Satellite and the road basemap share the server affine. */
(() => {
  const ground=(x,y)=>30+Math.max(0,50-y)*3+Math.max(0,x-50)*2;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const colors={robot:'#426d89',dog:'#836044',drone:'#306caa',person:'#667967',alert:'#c55b4b'};
  const ACTIVE=new Set(['执行中','已派发','返厂中']);
  const ICON_SRC={robot:'/assets/icons/robot.png',dog:'/assets/icons/robot-dog.png',drone:'/assets/icons/drone.png',person:'/assets/icons/person.png',alert:'/assets/icons/alert.png',patrol:'/assets/icons/patrol.png'};
  class SpatialScene {
    constructor(host){
      this.host=host;this.canvas=host.querySelector('canvas');this.ctx=this.canvas.getContext('2d');
      this.data={resources:[],tasks:[],incidents:[],plan:null};this.positions=new Map();this.motionCache=new WeakMap();this.births=new Map();this.selected=null;
      this.zoom=1.6;this.defaultZoom=1.6;this.mode='road';this.showAll=false;this.locked=false;this.tiles=new Map();this.panX=0;this.panY=0;this.hit=[];this.last=0;this.mouse=null;
      this.icons={};Object.entries(ICON_SRC).forEach(([key,src])=>{const image=new Image();image.src=src;this.icons[key]=image;});
      this.centerLat=30.3165737;this.centerLon=120.3479082;this.meters=70;
      this.resize=new ResizeObserver(()=>this.measure());this.resize.observe(host);this.measure();
      this.canvas.addEventListener('pointerdown',e=>{this.drag={x:e.clientX,y:e.clientY,moved:false};this.canvas.setPointerCapture(e.pointerId);});
      this.canvas.addEventListener('pointermove',e=>{const r=this.canvas.getBoundingClientRect();this.mouse={x:e.clientX-r.left,y:e.clientY-r.top};if(!this.drag)return;const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;this.drag.moved=this.drag.moved||Math.abs(dx)+Math.abs(dy)>2;if(this.drag.moved)this.setLocked(false);this.panX+=dx;this.panY+=dy;this.drag.x=e.clientX;this.drag.y=e.clientY;});
      this.canvas.addEventListener('pointerup',()=>{if(!this.drag?.moved&&this.mouse){const hit=this.hit.filter(p=>Math.hypot(p.x-this.mouse.x,p.y-this.mouse.y)<18).sort((a,b)=>Math.hypot(a.x-this.mouse.x,a.y-this.mouse.y)-Math.hypot(b.x-this.mouse.x,b.y-this.mouse.y))[0];const select=this.host.querySelector('[data-device-select]');if(hit&&select){this.selected=hit.id;select.value=hit.id;}}this.drag=null;});
      this.canvas.addEventListener('wheel',e=>{e.preventDefault();this.zoom=clamp(this.zoom*Math.exp(-e.deltaY*.001),1.15,4);},{passive:false});
      host.querySelector('[data-view-reset]').onclick=()=>{this.zoom=this.defaultZoom;this.panX=0;this.panY=0;};
      host.querySelector('[data-zoom-in]').onclick=()=>this.zoom=clamp(this.zoom*1.2,1.15,4);
      host.querySelector('[data-zoom-out]').onclick=()=>this.zoom=clamp(this.zoom/1.2,1.15,4);
      host.querySelector('[data-lock-device]').onclick=()=>this.setLocked(!this.locked);
      host.querySelector('[data-show-all]').onclick=()=>{this.showAll=!this.showAll;const button=host.querySelector('[data-show-all]');button.classList.toggle('active',this.showAll);button.querySelector('.console-button-label').textContent=this.showAll?'收起':'全部';this.refreshCount();};
      host.querySelector('[data-view-3d]').onclick=()=>this.setMode('road');
      host.querySelector('[data-view-satellite]').onclick=()=>this.setMode('satellite');
      host.querySelector('[data-device-select]').onchange=e=>this.selected=e.target.value;
      host.addEventListener('click',event=>{const row=event.target.closest('[data-altitude-device]');if(!row)return;this.selected=row.dataset.altitudeDevice;const select=host.querySelector('[data-device-select]');if(select)select.value=this.selected;});
      this.setMode('road');
      this.frame=this.frame.bind(this);this.raf=requestAnimationFrame(this.frame);
    }
    setLocked(value){this.locked=Boolean(value);const button=this.host.querySelector('[data-lock-device]');if(button){button.classList.toggle('active',this.locked);button.querySelector('.console-button-label').textContent=this.locked?'已锁定设备':'锁定设备';}}
    measure(){const rect=this.host.querySelector('.space-map').getBoundingClientRect();this.w=rect.width;this.h=rect.height;const dpr=Math.min(devicePixelRatio||1,2);this.canvas.width=this.w*dpr;this.canvas.height=this.h*dpr;this.ctx.setTransform(dpr,0,0,dpr,0,0);}
    update(data){
      const previous=new Set(this.data.tasks.map(t=>t.id));this.data=data;
      const frame=data.plan?.map_frame;if(frame){this.centerLat=frame.center_lat;this.centerLon=frame.center_lon;this.meters=frame.meters_per_unit;}
      data.tasks.forEach(t=>{if(!previous.has(t.id)&&t.name.startsWith('紧急'))this.births.set(t.id,performance.now());});
      const select=this.host.querySelector('[data-device-select]');const value=this.selected;
      if(select.options.length!==data.resources.length||[...select.options].some((o,i)=>o.value!==data.resources[i]?.id))select.replaceChildren(...data.resources.map(r=>{const option=document.createElement('option');option.value=r.id;option.textContent=r.name;return option;}));
      if(!data.resources.some(r=>r.id===this.selected))this.selected=data.resources.find(r=>r.type==='drone')?.id||data.resources[0]?.id;
      select.value=this.selected||value||'';
      this.refreshCount();
    }
    refreshCount(){
      const routes=(this.data.plan?.assignments||[]).length;
      const shown=this.visibleResources().length;
      const node=this.host.querySelector('[data-space-count]');
      if(node)node.textContent=`${shown} 台${routes?` · ${routes} 条路线`:''}`;
    }
    visibleResources(){
      if(this.showAll)return this.data.resources;
      const show=new Set(this.data.resources.filter(r=>ACTIVE.has(r.status)).map(r=>r.id));
      if(this.selected)show.add(this.selected);
      (this.data.plan?.assignments||[]).forEach(a=>{if(a.task_id===this.data.selectedTaskId&&a.resource_id)show.add(a.resource_id);});
      return this.data.resources.filter(r=>show.has(r.id));
    }
    setMode(mode){
      this.mode=mode==='satellite'?'satellite':'road';
      this.host.querySelector('[data-view-3d]').classList.toggle('active',this.mode==='road');
      this.host.querySelector('[data-view-satellite]').classList.toggle('active',this.mode==='satellite');
    }
    sceneToLonLat(x,y){
      const z=15,world=2**z*256,lat0=this.centerLat*Math.PI/180;
      const cx=(this.centerLon+180)/360*world,cy=(1-Math.asinh(Math.tan(lat0))/Math.PI)/2*world;
      const unit=this.meters/Math.cos(lat0)*world/40075016.686;
      const px=cx+(x-50)*unit,py=cy+(y-50)*unit;
      return {lon:px/world*360-180,lat:Math.atan(Math.sinh(Math.PI*(1-2*py/world)))*180/Math.PI};
    }
    basemap(){
      const scale=Math.min(this.w/150,this.h/125)*this.zoom;
      let z=15;
      const bounds=()=>{const pad=24;return {x0:50-(this.w/2+pad+this.panX)/scale,x1:50+(this.w/2+pad-this.panX)/scale,y0:50-(this.h/2+pad+this.panY)/scale,y1:50+(this.h/2+pad-this.panY)/scale};};
      let box=bounds();
      const span=(zoom,b)=>{const world=2**zoom*256,unit=this.meters/Math.cos(this.centerLat*Math.PI/180)*world/40075016.686;return {unit,tiles:Math.ceil((b.x1-b.x0)*unit/256)*Math.ceil((b.y1-b.y0)*unit/256)};};
      if(span(15,box).tiles>72)z=14;
      const world=2**z*256,lat=this.centerLat*Math.PI/180;
      const cx=(this.centerLon+180)/360*world,cy=(1-Math.asinh(Math.tan(lat))/Math.PI)/2*world,unit=span(z,box).unit;
      const tx0=Math.max(0,Math.floor((cx+(box.x0-50)*unit)/256)),tx1=Math.min(2**z-1,Math.floor((cx+(box.x1-50)*unit)/256));
      const ty0=Math.max(0,Math.floor((cy+(box.y0-50)*unit)/256)),ty1=Math.min(2**z-1,Math.floor((cy+(box.y1-50)*unit)/256));
      for(let tx=tx0;tx<=tx1;tx++)for(let ty=ty0;ty<=ty1;ty++){
        const key=`${this.mode}/${z}/${ty}/${tx}`;let image=this.tiles.get(key);
        if(!image){image=new Image();image.referrerPolicy='no-referrer';image.onerror=()=>{if(!this.tileWarning){this.tileWarning=true;window.toast?.('底图暂不可用，可切换另一种视图');}};image.src=this.mode==='satellite'?`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${ty}/${tx}`:`https://a.tile.openstreetmap.fr/hot/${z}/${tx}/${ty}.png`;this.tiles.set(key,image);}
        const left=this.project({x:50+(tx*256-cx)/unit,y:50+(ty*256-cy)/unit}),right=this.project({x:50+((tx+1)*256-cx)/unit,y:50+((ty+1)*256-cy)/unit});
        if(image.complete&&image.naturalWidth)this.ctx.drawImage(image,left.x,left.y,right.x-left.x+1,right.y-left.y+1);
      }
    }
    project(p){const scale=Math.min(this.w/150,this.h/125)*this.zoom;return {x:this.w/2+(p.x-50)*scale+this.panX,y:this.h/2+(p.y-50)*scale+this.panY,depth:0};}
    line(points,color,width=1,dash=[]){if(!points.length)return;const ctx=this.ctx;ctx.beginPath();points.forEach((p,i)=>{const v=this.project(p);i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin='round';ctx.lineCap='round';ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);}
    sample(resource,now){
      const motion=resource.motion,path=motion?.path;
      if(!path?.length)return resource.position||{x:50,y:50,z:30};
      let cached=this.motionCache.get(path);
      if(!cached){let total=0;const lengths=[];const units=Number(motion.meters_per_unit)||35;for(let i=1;i<path.length;i++){const a=path[i-1],b=path[i];const length=Math.hypot(b.x-a.x,b.y-a.y,((b.z??ground(b.x,b.y))-(a.z??ground(a.x,a.y)))/units);lengths.push(length);total+=length;}cached={lengths,total};this.motionCache.set(path,cached);}
      const fraction=clamp((now-Date.parse(motion.started_at))/(Math.max(1,motion.duration_seconds)*1000),0,1);let remaining=cached.total*fraction;
      for(let i=0;i<cached.lengths.length;i++){const len=cached.lengths[i];if(remaining<=len){const a=path[i],b=path[i+1],t=len?remaining/len:0;const p={x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t};p.z=(a.z??ground(a.x,a.y))+((b.z??ground(b.x,b.y))-(a.z??ground(a.x,a.y)))*t;return p;}remaining-=len;}
      const end=path[path.length-1];return {...end,z:end.z??ground(end.x,end.y)};
    }
    tag(lines,p){const ctx=this.ctx,v=this.project(p);ctx.font='10px -apple-system,sans-serif';ctx.lineWidth=3;ctx.strokeStyle='rgba(247,250,250,.92)';ctx.lineJoin='round';lines.forEach((text,index)=>{const y=v.y-18-index*12;ctx.strokeText(text,v.x+18,y);ctx.fillStyle='#314852';ctx.fillText(text,v.x+18,y);});}
    deviceAltitude(resource,point){
      const spot=point||resource.position||{x:50,y:50};
      const gz=ground(spot.x,spot.y);
      const z=spot.z??gz;
      if(resource.type==='drone')return gz+(z-gz>5?z-gz:60);
      return z;
    }
    altTone(z,hi){
      const t=Math.max(0,Math.min(1,(z-25)/Math.max(hi-25,1)));
      const mix=(from,to)=>Math.round(from+(to-from)*t);
      return {t,fill:`rgb(${mix(255,29)},${mix(255,92)},${mix(255,168)})`,ink:t>0.62?'#fff':'#1c2830'};
    }
    paintAltitude(){
      const scale=this.host.querySelector('[data-altitude-scale]');
      const list=this.host.querySelector('[data-altitude-list]');
      if(!scale||!list)return;
      const devices=(this.data.resources||[]).map(resource=>{const point=this.positions.get(resource.id)||resource.position||{x:50,y:50};return {id:resource.id,name:resource.name,type:resource.type,z:this.deviceAltitude(resource,point)};});
      if(!devices.length){list.textContent='';scale.innerHTML='';return;}
      const hi=Math.max(120,Math.ceil(Math.max(...devices.map(item=>item.z))/10)*10);
      const key=devices.map(item=>`${item.id}:${Math.round(item.z)}`).join('|')+`@${hi}:${this.selected||''}`;
      if(scale.dataset.key===key)return;
      scale.dataset.key=key;
      const esc=value=>String(value).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
      const ticks=[];
      for(let z=0;z<=hi;z+=40)ticks.push(`<span class="alt-tick" style="bottom:${(z/hi)*100}%">${z}</span>`);
      const notches=devices.map(item=>`<i class="alt-notch" style="bottom:${(item.z/hi)*100}%;background:${this.altTone(item.z,hi).fill}"></i>`);
      scale.innerHTML=ticks.join('')+notches.join('');
      list.innerHTML=[...devices].sort((a,b)=>b.z-a.z).map(item=>{const tone=this.altTone(item.z,hi);return `<button class="alt-row${this.selected===item.id?' chosen':''}" data-altitude-device="${esc(item.id)}" style="background:${tone.fill};color:${tone.ink}"><b>${esc(item.name)}</b><small>${item.z.toFixed(0)} m</small></button>`;}).join('');
    }
    draw(now,dt){
      const ctx=this.ctx;ctx.clearRect(0,0,this.w,this.h);ctx.fillStyle=this.mode==='satellite'?'#d5ddd8':'#e7eef2';ctx.fillRect(0,0,this.w,this.h);
      this.basemap();
      const assignments=[...(this.data.plan?.assignments||[])].sort((a,b)=>Number(a.task_id===this.data.selectedTaskId)-Number(b.task_id===this.data.selectedTaskId));
      const palette=['#0e8f6e','#2f6fad','#c45b4b','#8a5a32','#6b5bd6','#b07d12'];
      const taskIds=[...new Set(assignments.map(a=>a.task_id))];
      const labeled=new Set();
      assignments.forEach(a=>{
        const on=a.task_id===this.data.selectedTaskId;
        const path=(a.route?.execution_path||[]).length>1?a.route.execution_path:((a.route?.road_path||[]).length>1?a.route.road_path:(a.route?.path||[]));
        if(path.length<2)return;
        const color=palette[taskIds.indexOf(a.task_id)%palette.length];
        this.line(path,'rgba(255,255,255,.94)',on?8:5);
        this.line(path,color,on?4:2.6);
        if(labeled.has(a.task_id))return;
        labeled.add(a.task_id);
        let meters=0;
        const units=Number(a.route?.meters_per_unit)||this.meters;for(let i=1;i<path.length;i++)meters+=Math.hypot((path[i].x-path[i-1].x)*units,(path[i].y-path[i-1].y)*units);
        const mid=path[Math.floor(path.length/2)];
        const spot=this.project(mid);
        const text=`${a.task_name||'路线'}  ${(meters/1000).toFixed(1)} km`;
        ctx.font='11px -apple-system,sans-serif';
        const width=ctx.measureText(text).width;
        ctx.fillStyle='rgba(255,255,255,.94)';
        ctx.fillRect(spot.x+8,spot.y-16,width+12,18);
        ctx.fillStyle=color;
        ctx.fillText(text,spot.x+14,spot.y-3);
      });
      this.data.resources.forEach(r=>{if(r.motion?.path?.length>1&&['执行中','已派发','返厂中','充电中'].includes(r.status))this.line(r.motion.path,r.status==='返厂中'?'#d5814f':(colors[r.type]||'#426d89'),2.2,[5,4]);});
      const events=this.data.tasks.filter(t=>(t.name.startsWith('紧急')||t.interruption)&&t.status!=='已完成');
      events.forEach(task=>{const site=task.route?.waypoints?.[0];if(!site)return;this.badge(this.project(site),'alert',colors.alert,26);});
      this.hit=[];const units=this.visibleResources().map(r=>{const target=this.sample(r,Date.now()),previous=this.positions.get(r.id)||target,alpha=1-Math.exp(-dt*12);const p={x:previous.x+(target.x-previous.x)*alpha,y:previous.y+(target.y-previous.y)*alpha,z:(previous.z??target.z??ground(previous.x,previous.y))+((target.z??ground(target.x,target.y))-(previous.z??target.z??ground(previous.x,previous.y)))*alpha};this.positions.set(r.id,p);return {r,p,v:this.project(p)};});
      units.forEach(({r,p,v})=>{
        const chosen=this.selected===r.id;
        const demoZ=this.deviceAltitude(r,p);
        const tone=this.altTone(demoZ,120);
        this.badge(v,r.type,tone.t<0.12?'#c5ced4':tone.fill,28,chosen);this.hit.push({id:r.id,x:v.x,y:v.y});
        const power=r.power_percent==null?'—':`${Math.round(r.power_percent)}%`;
        if(!this.showAll||chosen)this.tag([`${r.name}  ${r.status}`,`${power} · 海拔 ${Math.round(demoZ)}m`].reverse(),p);
        if(chosen){const geo=this.sceneToLonLat(p.x,p.y);const assignedTask=this.data.tasks.find(task=>String(task.executor||'').split('、').includes(r.name)||task.name===r.task);const taskText=assignedTask?`  巡检任务 ${assignedTask.name}`:'  巡检任务 待命';this.host.querySelector('[data-device-readout]').textContent=`${r.name}  ${r.status}${taskText}   经度 ${geo.lon.toFixed(5)}  纬度 ${geo.lat.toFixed(5)}  海拔 ${demoZ.toFixed(1)} m`;}
      });
      if(this.locked){const chosen=units.find(unit=>unit.r.id===this.selected);if(chosen){this.panX+=(this.w/2-chosen.v.x)*.14;this.panY+=(this.h/2-chosen.v.y)*.14;}}
      this.paintAltitude();
    }
    badge(v,key,ring,size,chosen=false){const ctx=this.ctx,image=this.icons[key];ctx.save();ctx.translate(v.x,v.y);ctx.beginPath();ctx.fillStyle='rgba(255,255,255,.94)';ctx.arc(0,0,size*.58,0,Math.PI*2);ctx.fill();ctx.strokeStyle=chosen?'#264a5d':ring;ctx.lineWidth=chosen?1.6:1.2;ctx.stroke();if(image&&image.complete&&image.naturalWidth)ctx.drawImage(image,-size/2,-size/2,size,size);ctx.restore();}
    frame(now){const dt=Math.min(.1,(now-this.last)/1000||.016);this.last=now;if(this.host.isConnected&&this.w>0)this.draw(now,dt);this.raf=requestAnimationFrame(this.frame);}
    destroy(){cancelAnimationFrame(this.raf);this.resize.disconnect();}
  }
  window.SpatialScene=SpatialScene;
})();
