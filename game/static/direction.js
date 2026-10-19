/* The director writes data on the server; this viewer smoothly presents it. */
"use strict";
let shot={x:500,y:300,zoom:1,letterbox:0,shake:0},shotSession=null,shotTime=0,directorOverview=false;
function directionData(data,body){return body?.direction||data?.direction||{};}
function cameraTarget(camera,data,body){
  if(Array.isArray(camera.target))return camera.target;
  if(body?.nodes?.[camera.target])return body.nodes[camera.target];
  const object=body?.objects?.find(o=>o[0]===camera.target);if(object)return[object[1],object[2]];
  const part=body?.appendages?.find(p=>p[0]===camera.target);if(part)return part[2];
  return[500,300];
}
function prepareDirection(now,data,body){
  if(shotSession!==sessionId){shotSession=sessionId;shot={x:500,y:300,zoom:1,letterbox:0,shake:0};shotTime=now;directorOverview=false;}
  const camera=directorOverview?{}:directionData(data,body).camera||{},target=cameraTarget(camera,data,body),offset=camera.offset||[0,0];
  const dt=Math.max(0,Math.min(.1,(now-shotTime)/1000));shotTime=now;
  const blend=1-Math.exp(-dt/(camera.ease||.35));
  const goal={x:target[0]+offset[0],y:target[1]+offset[1],zoom:camera.zoom||1,letterbox:camera.letterbox||0,shake:camera.shake||0};
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){goal.shake=0;goal.zoom=Math.min(goal.zoom,1.5);goal.letterbox=0;}
  for(const key of Object.keys(goal))shot[key]+=(goal[key]-shot[key])*blend;
  shot.jx=Math.sin(now*.071)*shot.shake;shot.jy=Math.sin(now*.053)*shot.shake*.6;
  const beat=directionData(data,body).beat||"";
  const indicator=document.getElementById("shot-state");if(indicator)indicator.textContent=directorOverview?"ОБЩИЙ ПЛАН":`${shot.zoom.toFixed(1)}×${beat?' · '+beat:''}`;
}
function applyDirectionCamera(ctx){ctx.translate(500,300);ctx.scale(shot.zoom,shot.zoom);ctx.translate(-shot.x+(shot.jx||0),-shot.y+(shot.jy||0));}
function screenToWorld(point){return[(point[0]-500)/shot.zoom+shot.x-(shot.jx||0),(point[1]-300)/shot.zoom+shot.y-(shot.jy||0)];}
function worldToScreen(point){return[(point[0]-shot.x+(shot.jx||0))*shot.zoom+500,(point[1]-shot.y+(shot.jy||0))*shot.zoom+300];}
function drawProject(ctx,data,body,space,layer){
  const commands=directionData(data,body).draw||[];
  for(const c of commands){
    if((c.space||"world")!==space||(c.layer||"foreground")!==layer)continue;
    ctx.save();ctx.globalAlpha=c.alpha??1;ctx.lineCap="round";ctx.lineJoin="round";ctx.lineWidth=c.width||2;ctx.fillStyle=c.fill||"#58758c";ctx.strokeStyle=c.stroke||"#58758c";ctx.beginPath();
    if(c.type==="line"){ctx.moveTo(c.x,c.y);ctx.lineTo(c.x2,c.y2);}
    if(c.type==="circle")ctx.arc(c.x,c.y,c.radius,0,Math.PI*2);
    if(c.type==="ellipse")ctx.ellipse(c.x,c.y,c.rx,c.ry,c.angle||0,0,Math.PI*2);
    if(c.type==="rect")ctx.roundRect(c.x,c.y,c.w,c.h,Math.min(c.radius||0,c.w/2,c.h/2));
    if(c.type==="path"){ctx.moveTo(...c.points[0]);for(const p of c.points.slice(1))ctx.lineTo(...p);if(c.closed)ctx.closePath();}
    if(c.type==="text"){ctx.font=`${c.size||16}px system-ui`;ctx.fillText(c.text,c.x,c.y);}
    else{if(c.fill)ctx.fill();if(c.stroke||!c.fill)ctx.stroke();}
    ctx.restore();
  }
}
function drawDirectionScreen(ctx,now,data,body){
  if(!data)return;
  drawProject(ctx,data,body,"screen","background");
  const bars=shot.letterbox*600;
  if(bars>.3){ctx.fillStyle="#142238";ctx.fillRect(0,0,1000,bars);ctx.fillRect(0,600-bars,1000,bars);}
  drawProject(ctx,data,body,"screen","foreground");
  const caption=directionData(data,body).caption;
  if(caption){ctx.save();ctx.font="14px system-ui";const width=Math.min(920,ctx.measureText(caption).width+36),y=565-Math.max(0,bars-20);ctx.fillStyle="#172a3ee6";ctx.beginPath();ctx.roundRect((1000-width)/2,y-21,width,34,12);ctx.fill();ctx.textAlign="center";ctx.fillStyle="#f0f7ff";ctx.fillText(caption,500,y);ctx.restore();}
}
const cameraControl=document.getElementById("camera-overview");if(cameraControl)cameraControl.onclick=()=>{directorOverview=!directorOverview;cameraControl.textContent=directorOverview?"Вернуть камеру агенту":"Общий план";};
const projectSignal=document.getElementById("project-signal");if(projectSignal)projectSignal.onclick=()=>{if(sessionId&&sceneData?.scene.active_project)api(`game/sessions/${sessionId}/project-event`,"POST",{version:sceneData.scene.version,id:"human_attention"}).catch(error);};
