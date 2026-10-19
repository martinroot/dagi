/* The director writes data on the server; this viewer smoothly presents it. */
"use strict";
let shot={x:500,y:300,zoom:1,letterbox:0,shake:0},shotSession=null,shotTime=0,directorOverview=false,characterFocus=null;
function directionData(data,body){return body?.direction||data?.direction||{};}
function cameraTarget(camera,data,body){
  if(Array.isArray(camera.target))return camera.target;
  if(body?.nodes?.[camera.target])return body.nodes[camera.target];
  const object=body?.objects?.find(o=>o[0]===camera.target);if(object)return[object[1],object[2]];
  const part=body?.appendages?.find(p=>p[0]===camera.target);if(part)return part[2];
  return[500,300];
}
function prepareDirection(now,data,body){
  if(shotSession!==sessionId){shotSession=sessionId;shot={x:500,y:300,zoom:1,letterbox:0,shake:0};shotTime=now;directorOverview=false;characterFocus=null;}
  const camera=characterFocus?{target:characterFocus==="head"?"head":"hip",zoom:characterFocus==="head"?4:2.5,offset:[0,characterFocus==="head"?20:-15],ease:.25}:directorOverview?{}:directionData(data,body).camera||{},target=cameraTarget(camera,data,body),offset=camera.offset||[0,0];
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
    vectorDraw(ctx,c,data);
  }
}
function drawDirectionScreen(ctx,now,data,body){
  if(!data)return;
  if(typeof paintArtFinish==="function")paintArtFinish(ctx,data);
  drawProject(ctx,data,body,"screen","background");
  const bars=shot.letterbox*600;
  if(bars>.3){ctx.fillStyle="#142238";ctx.fillRect(0,0,1000,bars);ctx.fillRect(0,600-bars,1000,bars);}
  drawProject(ctx,data,body,"screen","foreground");
  const caption=directionData(data,body).caption;
  if(caption){ctx.save();ctx.font="14px system-ui";const width=Math.min(920,ctx.measureText(caption).width+36),y=565-Math.max(0,bars-20);ctx.fillStyle="#172a3ee6";ctx.beginPath();ctx.roundRect((1000-width)/2,y-21,width,34,12);ctx.fill();ctx.textAlign="center";ctx.fillStyle="#f0f7ff";ctx.fillText(caption,500,y);ctx.restore();}
}
const cameraControl=document.getElementById("camera-overview");if(cameraControl)cameraControl.onclick=()=>{characterFocus=null;directorOverview=!directorOverview;cameraControl.textContent=directorOverview?"Вернуть камеру агенту":"Общий план";};
const projectSignal=document.getElementById("project-signal");if(projectSignal)projectSignal.onclick=()=>{if(sessionId&&sceneData?.scene.active_project)api(`game/sessions/${sessionId}/project-event`,"POST",{version:sceneData.scene.version,id:"human_attention"}).catch(error);};

for(const name of ["body","head"]){const button=document.getElementById("camera-"+name);if(button)button.onclick=()=>{characterFocus=characterFocus===name?null:name;directorOverview=false;};}
