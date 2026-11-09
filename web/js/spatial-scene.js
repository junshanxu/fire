/* One Xiasha map. Satellite and the road basemap share the server affine. */
(() => {
  const ground=(x=50,y=50)=>{const base=34+(40-y)*0.11+(x-70)*0.045;const ridge=4.5*Math.sin((x+8)/22)*Math.cos((y+6)/30);return Math.max(22,Math.min(48,base+ridge));};
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const colors={robot:'#426d89',dog:'#836044',drone:'#306caa',person:'#667967',alert:'#c55b4b'};
  const ACTIVE=new Set(['执行中','已派发','返厂中']);
  const ICON_SRC={robot:'/assets/icons/robot.png',dog:'/assets/icons/robot-dog.png',drone:'/assets/icons/drone.png',person:'/assets/icons/person.png',alert:'/assets/icons/alert.png',patrol:'/assets/icons/patrol.png'};
  class SpatialScene {
    constructor(host){
      this.host=host;this.canvas=host.querySelector('canvas');this.ctx=this.canvas.getContext('2d');this.airportFrame=host.querySelector('[data-airport-ops]');this.airportReady=false;
      this.data={resources:[],tasks:[],incidents:[],plan:null};this.positions=new Map();this.motionCache=new WeakMap();this.bendCache=new WeakMap();this.births=new Map();this.selected=null;
      this.zoom=.85;this.defaultZoom=.85;this.mode='road';this.showAll=false;this.locked=false;this.tiles=new Map();this.panX=0;this.panY=0;this.hit=[];this.last=0;this.lastAltitudePaint=0;this.mouse=null;
      this.icons={};Object.entries(ICON_SRC).forEach(([key,src])=>{const image=new Image();image.src=src;this.icons[key]=image;});
      this.sprites={};this.cutouts=new Map();
      [['tower','/assets/yard/tower.jpg'],['transformer','/assets/yard/transformer.jpg']].forEach(([key,src])=>{const image=new Image();image.onload=()=>{this.cutouts.delete(image);this.tileRevision++;};image.src=src;this.sprites[key]=image;});
      this.centerLat=30.3445;this.centerLon=120.4415;this.meters=4;this.tileRevision=0;
      this.resize=new ResizeObserver(()=>this.measure());this.resize.observe(host);this.measure();
      this.canvas.addEventListener('pointerdown',e=>{this.drag={x:e.clientX,y:e.clientY,moved:false};this.canvas.setPointerCapture(e.pointerId);});
      this.canvas.addEventListener('pointermove',e=>{const r=this.canvas.getBoundingClientRect();this.mouse={x:e.clientX-r.left,y:e.clientY-r.top};if(!this.drag)return;const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;this.drag.moved=this.drag.moved||Math.abs(dx)+Math.abs(dy)>2;if(this.drag.moved)this.setLocked(false);this.panX+=dx;this.panY+=dy;this.drag.x=e.clientX;this.drag.y=e.clientY;});
      this.canvas.addEventListener('pointerup',()=>{if(!this.drag?.moved&&this.mouse){const hit=this.hit.filter(p=>Math.hypot(p.x-this.mouse.x,p.y-this.mouse.y)<18).sort((a,b)=>Math.hypot(a.x-this.mouse.x,a.y-this.mouse.y)-Math.hypot(b.x-this.mouse.x,b.y-this.mouse.y))[0];const select=this.host.querySelector('[data-device-select]');if(hit&&select){this.selected=hit.id;select.value=hit.id;}}this.drag=null;});
      this.canvas.addEventListener('wheel',e=>{e.preventDefault();this.zoom=clamp(this.zoom*Math.exp(-e.deltaY*.001),.3,4);},{passive:false});
      host.querySelector('[data-view-reset]').onclick=()=>{this.zoom=this.defaultZoom;this.panX=0;this.panY=0;};
      host.querySelector('[data-zoom-in]').onclick=()=>this.zoom=clamp(this.zoom*1.2,.3,4);
      host.querySelector('[data-zoom-out]').onclick=()=>this.zoom=clamp(this.zoom/1.2,.3,4);
      host.querySelector('[data-lock-device]').onclick=()=>this.setLocked(!this.locked);
      host.querySelector('[data-show-all]').onclick=()=>{this.showAll=!this.showAll;this.refreshCount();};
      host.querySelector('[data-view-3d]').onclick=()=>this.setMode('road');
      host.querySelector('[data-view-satellite]').onclick=()=>this.setMode('satellite');
      host.querySelector('[data-view-airport]').onclick=()=>this.setMode('airport');
      host.querySelector('[data-device-select]').onchange=e=>this.selected=e.target.value;
      this.onAirportMessage=event=>{if(!this.airportFrame||event.origin!==location.origin||event.source!==this.airportFrame.contentWindow||event.data?.type!=='airport-scene-ready')return;this.airportReady=true;this.host.classList.remove('airport-loading');};
      window.addEventListener('message',this.onAirportMessage);
      host.addEventListener('click',event=>{const row=event.target.closest('[data-altitude-device]');if(!row)return;this.selected=row.dataset.altitudeDevice;const select=host.querySelector('[data-device-select]');if(select)select.value=this.selected;});
      this.setMode('road');
      this.frame=this.frame.bind(this);this.raf=requestAnimationFrame(this.frame);
    }
    setLocked(value){this.locked=Boolean(value);const button=this.host.querySelector('[data-lock-device]');if(button){button.classList.toggle('active',this.locked);button.querySelector('.console-button-label').textContent=this.locked?'已锁定设备':'锁定设备';}}
    measure(){const rect=this.host.querySelector('.space-map').getBoundingClientRect();if(this.w===rect.width&&this.h===rect.height)return;this.w=rect.width;this.h=rect.height;const dpr=Math.min(devicePixelRatio||1,2);this.dpr=dpr;this.canvas.width=this.w*dpr;this.canvas.height=this.h*dpr;this.ctx.setTransform(dpr,0,0,dpr,0,0);}
    update(data){
      const previous=new Set(this.data.tasks.map(t=>t.id));this.data=data;
      const frame=data.plan?.map_frame;if(frame){this.centerLat=frame.center_lat;this.centerLon=frame.center_lon;this.meters=frame.meters_per_unit;}
      const siteSignature=JSON.stringify(frame?.site||null);if(siteSignature!==this.siteSignature){this.siteSignature=siteSignature;this.backgroundKey=null;}
      data.tasks.forEach(t=>{if(!previous.has(t.id)&&t.name.startsWith('紧急'))this.births.set(t.id,performance.now());});
      const select=this.host.querySelector('[data-device-select]');const value=this.selected;
      if(select.options.length!==data.resources.length||[...select.options].some((o,i)=>o.value!==data.resources[i]?.id))select.replaceChildren(...data.resources.map(r=>{const option=document.createElement('option');option.value=r.id;option.textContent=r.name;return option;}));
      if(!data.resources.some(r=>r.id===this.selected))this.selected=data.resources.find(r=>r.type==='drone'&&ACTIVE.has(r.status))?.id||data.resources.find(r=>r.type==='drone')?.id||data.resources[0]?.id;
      select.value=this.selected||value||'';
      this.refreshCount();
    }
    refreshCount(){
      const routes=(this.data.plan?.assignments||[]).length;
      const shown=this.visibleResources().length;
      const node=this.host.querySelector('[data-space-count]');
      if(node)node.textContent=`${shown}/${this.data.resources.length} 台${routes?` · ${routes} 条路线`:''}`;
      const button=this.host.querySelector('[data-show-all]');
      if(button){button.classList.toggle('active',this.showAll);button.setAttribute('aria-pressed',String(this.showAll));button.querySelector('.console-button-label').textContent=this.showAll?'仅看执行':'显示全部';}
    }
    visibleResources(){
      if(this.showAll)return this.data.resources;
      const show=new Set(this.data.resources.filter(r=>ACTIVE.has(r.status)).map(r=>r.id));
      if(this.selected)show.add(this.selected);
      (this.data.plan?.assignments||[]).forEach(a=>{if(a.task_id===this.data.selectedTaskId&&a.resource_id)show.add(a.resource_id);});
      return this.data.resources.filter(r=>show.has(r.id));
    }
    setMode(mode){
      this.mode=['satellite','airport'].includes(mode)?mode:'road';
      const airport=this.mode==='airport';
      this.host.classList.toggle('airport-mode',airport);
      this.host.classList.toggle('airport-loading',airport&&!this.airportReady);
      this.canvas.hidden=airport;
      if(this.airportFrame){this.airportFrame.hidden=!airport;if(airport&&!this.airportFrame.src)this.airportFrame.src=this.airportFrame.dataset.src;}
      this.host.querySelector('[data-view-3d]').classList.toggle('active',this.mode==='road');
      this.host.querySelector('[data-view-satellite]').classList.toggle('active',this.mode==='satellite');
      this.host.querySelector('[data-view-airport]').classList.toggle('active',airport);
      const credit=this.host.querySelector('[data-map-credit]');
      if(credit)credit.textContent=this.mode==='satellite'?'影像 © Google':'© OpenStreetMap contributors';
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
      let z=18;
      const bounds=()=>{const pad=24;return {x0:50-(this.w/2+pad+this.panX)/scale,x1:50+(this.w/2+pad-this.panX)/scale,y0:50-(this.h/2+pad+this.panY)/scale,y1:50+(this.h/2+pad-this.panY)/scale};};
      let box=bounds();
      const span=(zoom,b)=>{const world=2**zoom*256,unit=this.meters/Math.cos(this.centerLat*Math.PI/180)*world/40075016.686;return {unit,tiles:Math.ceil((b.x1-b.x0)*unit/256)*Math.ceil((b.y1-b.y0)*unit/256)};};
      if(span(z,box).tiles>72)z=17;
      const world=2**z*256,lat=this.centerLat*Math.PI/180;
      const cx=(this.centerLon+180)/360*world,cy=(1-Math.asinh(Math.tan(lat))/Math.PI)/2*world,unit=span(z,box).unit;
      const tx0=Math.max(0,Math.floor((cx+(box.x0-50)*unit)/256)),tx1=Math.min(2**z-1,Math.floor((cx+(box.x1-50)*unit)/256));
      const ty0=Math.max(0,Math.floor((cy+(box.y0-50)*unit)/256)),ty1=Math.min(2**z-1,Math.floor((cy+(box.y1-50)*unit)/256));
      for(let tx=tx0;tx<=tx1;tx++)for(let ty=ty0;ty<=ty1;ty++){
        const key=`${this.mode}/${z}/${ty}/${tx}`;let image=this.tiles.get(key);
        if(!image){image=new Image();image.referrerPolicy='no-referrer';image.onload=()=>this.tileRevision++;image.onerror=()=>{if(!this.tileWarning){this.tileWarning=true;window.toast?.('底图暂不可用，站内矢量仍可使用');}};image.src=this.mode==='satellite'?`https://mt1.google.com/vt/lyrs=s&x=${tx}&y=${ty}&z=${z}`:`https://a.tile.openstreetmap.fr/hot/${z}/${tx}/${ty}.png`;this.tiles.set(key,image);}
        const left=this.project({x:50+(tx*256-cx)/unit,y:50+(ty*256-cy)/unit}),right=this.project({x:50+((tx+1)*256-cx)/unit,y:50+((ty+1)*256-cy)/unit});
        if(image.complete&&image.naturalWidth)this.ctx.drawImage(image,left.x,left.y,right.x-left.x+1,right.y-left.y+1);
      }
    }
    project(p){const scale=Math.min(this.w/150,this.h/125)*this.zoom;return {x:this.w/2+(p.x-50)*scale+this.panX,y:this.h/2+(p.y-50)*scale+this.panY,depth:0};}
    station(){
      const site=this.data.plan?.map_frame?.site;if(!site)return;
      const ctx=this.ctx,s=Math.min(this.w/150,this.h/125)*this.zoom;
      const box=(bounds,fill,stroke)=>{const a=this.project({x:bounds[0],y:bounds[1]});ctx.fillStyle=fill;ctx.fillRect(a.x,a.y,(bounds[2]-bounds[0])*s,(bounds[3]-bounds[1])*s);if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.strokeRect(a.x,a.y,(bounds[2]-bounds[0])*s,(bounds[3]-bounds[1])*s);}};
      const label=(name,x,y,size=11)=>{const p=this.project({x,y});ctx.save();ctx.textAlign='center';ctx.textBaseline='middle';ctx.font=`600 ${size}px -apple-system,sans-serif`;ctx.lineWidth=3;ctx.strokeStyle='#f4f8f4cc';ctx.strokeText(name,p.x,p.y);ctx.fillStyle='#203642';ctx.fillText(name,p.x,p.y);ctx.restore();};
      box(site.bounds,this.mode==='satellite'?'#a8cc9340':'#b9d59d55','#526660');
      site.roads.forEach(road=>{const points=road.map(([x,y])=>({x,y}));this.line(points,'#e8edeb',4*s);this.line(points,'#aeb8bd',3.3*s);});
      (site.exterior_roads||[]).forEach(road=>{const points=road.map(([x,y])=>({x,y}));this.line(points,'#edf3f1cc',3*s);this.line(points,'#6b8f9b',1.6*s,[5,4]);});
      if(site.exterior_roads?.length)label('外围巡检通道',52,105,11);
      const pad=(x,y,w,h,fill,stroke)=>{const a=this.project({x,y});ctx.fillStyle=fill;ctx.fillRect(a.x,a.y,w*s,h*s);if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=Math.max(1,s*0.14);ctx.strokeRect(a.x,a.y,w*s,h*s);}};
      const dot=(x,y,r,fill,stroke)=>{const p=this.project({x,y});ctx.beginPath();ctx.arc(p.x,p.y,Math.max(2,r*s),0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.lineWidth=1;ctx.strokeStyle=stroke;ctx.stroke();}};
      const bush=(x,y0,y1)=>{this.line([{x,y:y0},{x,y:y1}],'#2c3e4a',Math.max(2,s*0.22));dot(x,y0,0.38,'#f7f4ea','#2c3e4a');};
      site.buildings.forEach(b=>{box(b.bounds,b.fill,'#4b6472');const [x1,y1,x2,y2]=b.bounds;const w=x2-x1,h=y2-y1;
        if(b.id.startsWith('t')){
          if(!this.placeSprite('transformer',(x1+x2)/2,(y1+y2)/2,h*0.9,'center',w*0.92)){
            pad(x1+1.15,y1+2.3,w-2.3,h-3.6,'#e7eef3','#3c5564');
            for(let i=0;i<4;i++){pad(x1+0.28,y1+2.7+i*1.2,0.72,0.85,'#6f93a8');pad(x2-1,y1+2.7+i*1.2,0.72,0.85,'#6f93a8');}
            for(let i=0;i<3;i++)bush(x1+1.7+i*(w-3.4)/2,y1+0.55,y1+2.3);
            pad(x1+1.4,y2-1.45,w-2.8,0.85,'#8eabbb','#3c5564');
          }
          label(b.name,(x1+x2)/2,y2-0.7,9);
        }else if(b.id==='gis'){
          const n=4,gap=0.28,bw=(w-gap*(n+1))/n;
          this.line([{x:x1+0.3,y:y1+0.85},{x:x2-0.3,y:y1+0.85}],'#b23b3b',Math.max(2,s*0.2));
          for(let i=0;i<n;i++){const x=x1+gap+i*(bw+gap);pad(x,y1+1.7,bw,h-2.6,'#f3f7fb','#3d5870');bush(x+bw/2,y1+0.85,y1+1.7);}
          label('GIS',(x1+x2)/2,y2-1.15,10);
        }else if(b.id==='switch'){
          pad(x1+0.35,y1+0.4,w-0.7,1.15,'#d5e0e8');
          for(let i=1;i<9;i++)this.line([{x:x1+w*i/9,y:y1+1.7},{x:x1+w*i/9,y:y2-0.35}],'#7f93a3',1);
          for(let i=0;i<9;i++)pad(x1+w*i/9+0.35,y2-1.35,w/9-0.7,0.7,'#e7eef2','#607484');
          label(b.name,(x1+x2)/2,(y1+y2)/2,12);
        }else if(b.id==='oil'){
          const p=this.project({x:(x1+x2)/2,y:(y1+y2)/2});
          ctx.beginPath();ctx.ellipse(p.x,p.y,w*s*0.36,h*s*0.32,0,0,Math.PI*2);ctx.fillStyle='#5f8ea0';ctx.fill();ctx.lineWidth=Math.max(2,s*0.25);ctx.strokeStyle='#d7e4ea';ctx.stroke();
          label('事故油池',(x1+x2)/2,(y1+y2)/2,9);
        }else if(b.id==='water'){
          const p=this.project({x:(x1+x2)/2,y:(y1+y2)/2});
          ctx.beginPath();ctx.ellipse(p.x,p.y,w*s*0.38,h*s*0.34,0,0,Math.PI*2);ctx.fillStyle='#6eafc8';ctx.fill();
          ctx.beginPath();ctx.ellipse(p.x,p.y-h*s*0.08,w*s*0.22,h*s*0.1,0,0,Math.PI*2);ctx.strokeStyle='#e7f4f8';ctx.lineWidth=1;ctx.stroke();
          label('消防水池',(x1+x2)/2,y2-1.3,9);
        }else if(b.id==='reactor'){
          for(let i=0;i<3;i++){dot(x1+w*(0.28+i*0.22),y1+h*0.42,0.85,'#d5dde4','#4d6270');dot(x1+w*(0.28+i*0.22),y1+h*0.42,0.35,'#8ea0ad');}
          label('电抗器',(x1+x2)/2,y2-1.2,9);
        }else{
          this.line([{x:x1+0.4,y:(y1+y2)/2},{x:x2-0.4,y:(y1+y2)/2}],'#ffffff88',Math.max(1,s*0.12));
          pad(x1+w*0.35,y2-1.5,w*0.3,1.1,'#ece6dc','#4b6472');
          label(b.name,(x1+x2)/2,y1+h*0.38,9);
        }
      });
      const north=[[46,23],[62,23],[78,23]].map(([x,y])=>this.placeSprite('tower',x,y,11));
      const east=[[106,30],[122,30]].map(([x,y])=>this.placeSprite('tower',x,y,11));
      const pin=(x,y)=>{const p=this.project({x,y});return {x:p.x,y:p.y,top:p.y,h:0};};
      if(north.some(item=>!item)){
        [[46,58],[62,74]].forEach(([a,c])=>{this.line([{x:a,y:21.2},{x:a,y:23.6}],'#5d6c78',Math.max(2,s*0.16));this.line([{x:c,y:21.2},{x:c,y:23.6}],'#5d6c78',Math.max(2,s*0.16));this.line([{x:a,y:21.5},{x:c,y:21.5}],'#5d6c78',Math.max(2,s*0.16));});
        this.line([{x:46,y:21.5},{x:74,y:21.5}],'#c4554a',Math.max(2,s*0.16));
      }else{
        this.hangWire(north[0],north[1]);this.hangWire(north[1],north[2]);this.hangWire(north[2],pin(78,42));
        this.hangWire(pin(81,47),east[0]);this.hangWire(east[0],east[1]);
      }
      label('110kV 进线',78,20.6,10);
      [[53.4,43,53.4,52],[63.6,43,63.6,52]].forEach(([xA,yA,xB,yB])=>this.line([{x:xA,y:yA},{x:xB,y:yB}],'#d7ddd8',Math.max(3,s*0.45)));
      site.points.forEach(p=>{box([p.x-3,p.y-1.5,p.x+3,p.y+1.5],p.name.includes('充电')?'#d9e7ee':'#d3dec5');if(this.zoom>=1.25)label(p.name,p.x,p.y,10);});
      label('110kV 变电站',50,16,14);if(this.zoom>=1.25)label('站内环形道路',58,74,11);
      // Scale bar uses the same four-metre coordinate frame as the planner.
      const p=this.project({x:10,y:84});ctx.fillStyle='#eff5f5e8';ctx.fillRect(p.x-5,p.y-14,12.5*s+10,25);ctx.fillStyle='#304653';ctx.fillRect(p.x,p.y,12.5*s,2);ctx.font='10px monospace';ctx.fillText('50 m',p.x,p.y-3);
    }
    background(){
      const key=[this.w,this.h,this.dpr,this.mode,this.zoom,this.panX,this.panY,this.centerLat,this.centerLon,this.tileRevision,Boolean(this.data.plan?.map_frame?.site)].join('/');
      if(this.backgroundKey!==key){this.backgroundCanvas ||= document.createElement('canvas');const layer=this.backgroundCanvas;layer.width=this.canvas.width;layer.height=this.canvas.height;const original=this.ctx;this.ctx=layer.getContext('2d');this.ctx.setTransform(this.dpr,0,0,this.dpr,0,0);this.ctx.fillStyle='#dce5df';this.ctx.fillRect(0,0,this.w,this.h);this.basemap();this.station();this.ctx=original;this.backgroundKey=key;}
      this.ctx.drawImage(this.backgroundCanvas,0,0,this.w,this.h);
    }
    line(points,color,width=1,dash=[]){if(!points.length)return;const ctx=this.ctx;ctx.beginPath();points.forEach((p,i)=>{const v=this.project(p);i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin='round';ctx.lineCap='round';ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);}
    cutout(image){
      if(!image||!image.complete||!image.naturalWidth)return null;
      const hit=this.cutouts.get(image);if(hit)return hit;
      const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      const g=canvas.getContext('2d',{willReadFrequently:true});g.drawImage(image,0,0);
      const frame=g.getImageData(0,0,canvas.width,canvas.height);const px=frame.data;
      for(let i=0;i<px.length;i+=4){const r=px[i],gv=px[i+1],b=px[i+2];if(r>165&&b>165&&gv<155&&r-gv>40&&b-gv>40){const spill=Math.min(r,b)-gv;px[i+3]=spill>80?0:Math.round(255*(1-spill/80));}}
      g.putImageData(frame,0,0);this.cutouts.set(image,canvas);return canvas;
    }
    placeSprite(name,x,y,heightUnits,anchor='base',maxWidthUnits=0){
      const cut=this.cutout(this.sprites[name]);if(!cut)return null;
      const p=this.project({x,y});const unit=Math.min(this.w/150,this.h/125)*this.zoom;let h=heightUnits*unit;let w=h*cut.width/cut.height;
      if(maxWidthUnits>0&&w>maxWidthUnits*unit){w=maxWidthUnits*unit;h=w*cut.height/cut.width;}
      const top=anchor==='center'?p.y-h/2:p.y-h;
      this.ctx.drawImage(cut,p.x-w/2,top,w,h);
      return {x:p.x,y:p.y,top,w,h};
    }
    hangWire(a,b){
      if(!a||!b)return;const ctx=this.ctx;const unit=Math.min(this.w/150,this.h/125)*this.zoom;const sag=Math.max(6,Math.abs(b.x-a.x)*0.16);
      [-7,0,7].forEach(offset=>{const y1=a.top+a.h*0.3+offset*0.15,y2=b.top+b.h*0.3+offset*0.15;ctx.beginPath();ctx.moveTo(a.x,y1+offset);ctx.quadraticCurveTo((a.x+b.x)/2,(y1+y2)/2+sag+offset,b.x,y2+offset);ctx.strokeStyle='#2a2e32';ctx.lineWidth=Math.max(1.05,unit*0.07);ctx.stroke();});
    }
    bend(path,type,salt=''){
      if(!path||path.length<2)return path||[];
      let bag=this.bendCache.get(path);
      if(!bag){bag=new Map();this.bendCache.set(path,bag);}
      const key=`${type||''}:${salt||''}`;
      const hit=bag.get(key);if(hit)return hit;
      const air=type==='drone'||path.some(point=>(point.z||30)>48);
      const step=air?3.2:1.35;
      const dense=[path[0]];
      for(let i=0;i<path.length-1;i++){
        const a=path[i],b=path[i+1],dist=Math.hypot(b.x-a.x,b.y-a.y),n=Math.max(0,Math.floor(dist/step)-1);
        for(let k=1;k<=n;k++){const t=k/(n+1);dense.push({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:(a.z??30)+((b.z??30)-(a.z??30))*t});}
        dense.push(b);
      }
      const cum=[0];
      for(let i=1;i<dense.length;i++)cum.push(cum[i-1]+Math.hypot(dense[i].x-dense[i-1].x,dense[i].y-dense[i-1].y));
      const total=cum[cum.length-1]||1;
      let phase=0;for(const ch of String(salt))phase+=ch.charCodeAt(0);
      phase+=dense[0].x*1.7+dense[0].y*2.1+dense[dense.length-1].x*0.6;
      const amp=air?2.8:0.42;
      const out=dense.map((point,index)=>{
        if(index===0||index===dense.length-1)return {...point};
        const along=cum[index];
        const fade=Math.min(1,along/7,(total-along)/7);
        const prev=dense[index-1],next=dense[Math.min(dense.length-1,index+1)];
        let dx=next.x-prev.x,dy=next.y-prev.y;const len=Math.hypot(dx,dy)||1;
        const wave=Math.sin(along*0.47+phase)+0.62*Math.sin(along*1.21+phase*1.6)+0.34*Math.sin(along*2.55+phase*0.45);
        const shift=amp*fade*wave/1.96;
        const z=point.z??30;
        return {x:point.x-dy/len*shift,y:point.y+dx/len*shift,z:air?z+shift*0.55:z};
      });
      bag.set(key,out);return out;
    }
    sample(resource,now){
      const motion=resource.motion,path=this.bend(motion?.path,resource.type,resource.id);
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
      if(resource.type==='drone' && ['执行中','已派发'].includes(resource.status)){
        const task=String(resource.task||'');
        const salt=[...(resource.id||'')].reduce((sum,ch)=>sum+ch.charCodeAt(0),0);
        const agl=task.includes('外围')?88+(salt%11):task.includes('上空')?42+(salt%8):58+(salt%6);
        return gz+agl;
      }
      if(Math.abs(z-30)<0.8)return gz;
      return z;
    }
    altTone(z,hi){
      const span=Math.max(36,hi-28);
      const t=clamp((z-28)/span,0,1);
      const light=90-Math.pow(t,0.8)*64;
      const sat=16+t*58;
      return {t,fill:`hsl(207 ${sat}% ${light}%)`,ink:light<56?'#f4f8fb':'#173040'};
    }
    paintAltitude(){
      const scale=this.host.querySelector('[data-altitude-scale]');
      const list=this.host.querySelector('[data-altitude-list]');
      if(!scale||!list)return;
      const devices=(this.visibleResources().length?this.visibleResources():(this.data.resources||[])).map(resource=>{const point=this.positions.get(resource.id)||resource.position||{x:50,y:50};return {id:resource.id,name:resource.name,type:resource.type,z:this.deviceAltitude(resource,point)};});
      if(!devices.length){list.textContent='';scale.innerHTML='';return;}
      const hi=Math.max(60,Math.ceil(Math.max(...devices.map(item=>item.z))/20)*20);
      const key=devices.map(item=>`${item.id}:${Math.round(item.z)}`).join('|')+`@${hi}:${this.selected||''}`;
      if(scale.dataset.key===key)return;
      scale.dataset.key=key;
      const esc=value=>String(value).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
      const ticks=[];
      for(let z=0;z<=hi;z+=hi<=80?10:40)ticks.push(`<span class="alt-tick" style="bottom:${(z/hi)*100}%">${z}</span>`);
      const notches=devices.map(item=>`<i class="alt-notch" style="bottom:${(item.z/hi)*100}%;background:${this.altTone(item.z,hi).fill}"></i>`);
      scale.innerHTML=ticks.join('')+notches.join('');
      scale.style.background=`linear-gradient(to top, ${this.altTone(0,hi).fill}, ${this.altTone(hi*0.45,hi).fill}, ${this.altTone(hi,hi).fill})`;
      scale.style.borderRadius='3px';
      list.innerHTML=[...devices].sort((a,b)=>b.z-a.z).map(item=>{const tone=this.altTone(item.z,hi);return `<button class="alt-row${this.selected===item.id?' chosen':''}" data-altitude-device="${esc(item.id)}" style="background:${tone.fill};color:${tone.ink}"><b>${esc(item.name)}</b><small>${item.z.toFixed(0)} m</small></button>`;}).join('');
    }
    draw(now,dt){
      const ctx=this.ctx;ctx.clearRect(0,0,this.w,this.h);ctx.fillStyle=this.mode==='satellite'?'#d5ddd8':'#e7eef2';ctx.fillRect(0,0,this.w,this.h);
      this.background();
      const assignments=[...(this.data.plan?.assignments||[])].sort((a,b)=>Number(a.task_id===this.data.selectedTaskId)-Number(b.task_id===this.data.selectedTaskId));
      const palette=['#0e8f6e','#2f6fad','#c45b4b','#8a5a32','#6b5bd6','#b07d12'];
      const taskIds=[...new Set(assignments.map(a=>a.task_id))];
      const labeled=new Set();
      assignments.forEach(a=>{
        const on=a.task_id===this.data.selectedTaskId;
        const raw=(a.route?.execution_path||[]).length>1?a.route.execution_path:((a.route?.road_path||[]).length>1?a.route.road_path:(a.route?.path||[]));
        const path=this.bend(raw,a.resource_type,a.resource_id||a.task_id);
        if(path.length<2)return;
        const color=palette[taskIds.indexOf(a.task_id)%palette.length];
        const completed=a.state==='已完成';
        this.line(path,completed?'rgba(202,218,226,.42)':'rgba(255,255,255,.94)',on?8:5);
        this.line(path,completed?`${color}99`:color,on?4:2.6,completed?[6,5]:[]);
        if(labeled.has(a.task_id)||this.zoom<1.25)return;
        labeled.add(a.task_id);
        let meters=0;
        const units=Number(a.route?.meters_per_unit)||this.meters;for(let i=1;i<path.length;i++)meters+=Math.hypot((path[i].x-path[i-1].x)*units,(path[i].y-path[i-1].y)*units);
        const mid=path[Math.floor(path.length/2)];
        const spot=this.project(mid);
        const text=`${a.task_name||'路线'}  ${(meters/1000).toFixed(1)} km`;
        ctx.font='11px -apple-system,sans-serif';
        const width=ctx.measureText(text).width;
        ctx.fillStyle=completed?'rgba(241,247,249,.78)':'rgba(255,255,255,.94)';
        ctx.fillRect(spot.x+8,spot.y-16,width+12,18);
        ctx.fillStyle=color;
        ctx.fillText(text,spot.x+14,spot.y-3);
      });
      this.data.resources.forEach(r=>{if(r.motion?.path?.length>1&&['执行中','已派发','返厂中','充电中'].includes(r.status))this.line(this.bend(r.motion.path,r.type,r.id),r.status==='返厂中'?'#d5814f':(colors[r.type]||'#426d89'),2.2,[5,4]);});
      const events=this.data.tasks.filter(t=>(t.name.startsWith('紧急')||t.interruption)&&t.status!=='已完成');
      events.forEach(task=>{const site=task.route?.waypoints?.[0];if(!site)return;this.badge(this.project(site),'alert',colors.alert,26);});
      this.hit=[];const units=this.visibleResources().map(r=>{const target=this.sample(r,Date.now()),previous=this.positions.get(r.id)||target,alpha=1-Math.exp(-dt*12);const p={x:previous.x+(target.x-previous.x)*alpha,y:previous.y+(target.y-previous.y)*alpha,z:(previous.z??target.z??ground(previous.x,previous.y))+((target.z??ground(target.x,target.y))-(previous.z??target.z??ground(previous.x,previous.y)))*alpha};this.positions.set(r.id,p);return {r,p,v:this.project(p)};});
      units.sort((a,b)=>Number(a.r.id===this.selected)-Number(b.r.id===this.selected));
      units.forEach(({r,p,v})=>{
        const chosen=this.selected===r.id;
        const demoZ=this.deviceAltitude(r,p);
        const tone=this.altTone(demoZ,120);
        this.badge(v,r.type,tone.t<0.12?'#c5ced4':tone.fill,chosen?34:28,chosen);this.hit.push({id:r.id,x:v.x,y:v.y});
        const power=r.power_percent==null?'—':`${Math.round(r.power_percent)}%`;
        if(!this.showAll||chosen)this.tag([`${r.name}  ${r.status}`,`${power} · 海拔 ${Math.round(demoZ)}m`].reverse(),p);
        if(chosen){const geo=this.sceneToLonLat(p.x,p.y);const assignedTask=this.data.tasks.find(task=>String(task.executor||'').split('、').includes(r.name)||task.name===r.task);const taskText=assignedTask?`  巡检任务 ${assignedTask.name}`:'  巡检任务 待命';this.host.querySelector('[data-device-readout]').textContent=`${r.name}  ${r.status}${taskText}   经度 ${geo.lon.toFixed(5)}  纬度 ${geo.lat.toFixed(5)}  海拔 ${demoZ.toFixed(1)} m`;}
      });
      if(this.locked){const chosen=units.find(unit=>unit.r.id===this.selected);if(chosen){this.panX+=(this.w/2-chosen.v.x)*.14;this.panY+=(this.h/2-chosen.v.y)*.14;}}
      if(now-this.lastAltitudePaint>260){this.paintAltitude();this.lastAltitudePaint=now;}
    }
    badge(v,key,ring,size,chosen=false){const ctx=this.ctx,image=this.icons[key];ctx.save();ctx.translate(v.x,v.y);ctx.beginPath();ctx.fillStyle='rgba(255,255,255,.94)';ctx.arc(0,0,size*.58,0,Math.PI*2);ctx.fill();ctx.strokeStyle=chosen?'#264a5d':ring;ctx.lineWidth=chosen?1.6:1.2;ctx.stroke();if(image&&image.complete&&image.naturalWidth)ctx.drawImage(image,-size/2,-size/2,size,size);ctx.restore();}
    frame(now){const elapsed=now-this.last;if(elapsed<33){this.raf=requestAnimationFrame(this.frame);return;}const dt=Math.min(.1,elapsed/1000||.033);this.last=now;if(this.mode!=='airport'&&document.visibilityState==='visible'&&this.host.isConnected&&this.w>0)this.draw(now,dt);this.raf=requestAnimationFrame(this.frame);}
    destroy(){cancelAnimationFrame(this.raf);this.resize.disconnect();window.removeEventListener('message',this.onAirportMessage);}
  }
  window.SpatialScene=SpatialScene;
})();
