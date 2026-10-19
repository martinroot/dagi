/* Presentation only. Every limb/object position comes from the physics stream. */
"use strict";
let backdropCache=null,backdropKey=null;
let sceneViewport={width:1000,height:600,scale:1}, pointerDrag=null, pointerSent=0;
let sceneQuality="auto",scenePixelCap=2,sceneLastPaint=0,sceneIntervals=[],sceneFastFrames=0;
function resizeScene(canvas,ctx){
  const now=performance.now();
  if(sceneLastPaint&&now-sceneLastPaint<150){sceneIntervals.push(now-sceneLastPaint);if(sceneIntervals.length>45)sceneIntervals.shift();}
  sceneLastPaint=now;
  if(sceneQuality==="auto"&&sceneIntervals.length===45){
    const average=sceneIntervals.reduce((a,b)=>a+b,0)/45;
    if(average>22&&scenePixelCap>1){scenePixelCap=Math.max(1,scenePixelCap-.25);sceneIntervals=[];sceneFastFrames=0;}
    else if(average<17.5&&++sceneFastFrames>600&&scenePixelCap<2){scenePixelCap+=.25;sceneIntervals=[];sceneFastFrames=0;}
  }
  const width=canvas.getBoundingClientRect().width||1000,height=width*.6,dpr=Math.min(devicePixelRatio||1,sceneQuality==='high'?2.5:sceneQuality==='economy'?1:scenePixelCap);
  const w=Math.round(width*dpr),h=Math.round(height*dpr);
  if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
  ctx.setTransform(w/1000,0,0,h/600,0,0);sceneViewport={width,height,scale:width/1000};
}
function sceneLine(ctx,points,color,width){ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(...points[0]);for(const p of points.slice(1))ctx.lineTo(...p);ctx.stroke();}
function shadow(ctx,x,y,rx,ry,opacity){ctx.save();ctx.fillStyle=`rgba(32,48,64,${opacity})`;ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,Math.PI*2);ctx.fill();ctx.restore();}
function paintObject(ctx,obj,state,data){
  if(data?.art&&obj.kind==="body"){paintMaterialObject(ctx,obj,state,data);return;}
  const x=state?.[1]??obj.x,y=state?.[2]??obj.y,angle=state?.[3]??obj.angle??0;
  if(obj.kind!=="body"){drawWorldObject(ctx,obj,displayed?.tick||0);return;}
  const rx=obj.shape==="circle"?obj.radius:obj.shape==="polygon"?Math.max(...obj.vertices.map(p=>Math.abs(p[0]))):obj.width/2,ry=obj.shape==="circle"?obj.radius:obj.shape==="polygon"?Math.max(...obj.vertices.map(p=>Math.abs(p[1]))):obj.height/2;
  const altitude=Math.max(0,540-y-ry);shadow(ctx,x,541,Math.max(7,rx*(1-altitude/900)),Math.max(2,5-altitude/100),.12*Math.max(.15,1-altitude/600));
  ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.lineWidth=1.4;
  if(obj.shape==="circle"){
    const g=ctx.createRadialGradient(-rx*.32,-rx*.4,1,rx*.25,rx*.3,rx*1.3);g.addColorStop(0,"#ffffff");g.addColorStop(.22,obj.color||"#8ba8c1");g.addColorStop(1,"#354e63");ctx.fillStyle=g;
    ctx.beginPath();ctx.arc(0,0,rx,0,Math.PI*2);ctx.fill();ctx.strokeStyle="#ffffff99";ctx.stroke();
    ctx.strokeStyle="#ffffff66";ctx.lineWidth=Math.max(2,rx*.11);ctx.beginPath();ctx.arc(0,0,rx*.69,-1.2,1.2);ctx.stroke();
  }else{
    const g=ctx.createLinearGradient(0,-ry,0,ry);g.addColorStop(0,obj.color||"#9caecc");g.addColorStop(1,"#536778");ctx.fillStyle=g;ctx.beginPath();if(obj.shape==="polygon"){ctx.moveTo(...obj.vertices[0]);for(const p of obj.vertices.slice(1))ctx.lineTo(...p);ctx.closePath();}else{ctx.roundRect(-rx,-ry,rx*2,ry*2,Math.min(6,rx*.2));}ctx.fill();ctx.strokeStyle="#ffffffa0";ctx.stroke();
    sceneLine(ctx,[[-rx+5,-ry+5],[rx-5,-ry+5]],"#ffffff66",2);
  }ctx.restore();
}
function paintFace(ctx,head,skin,emotion,now,data){
  const [x,y]=head,r=skin.head_radius||13,life=data.life||{},mode=data.scene.avatar_state;
  let valence=emotion.valence||0,arousal=emotion.arousal??.25,focus=emotion.focus??.4;
  if(data.scene.policy_error)valence=-.8;
  if(life.thinking&&!data.scene.active_project){focus=.9;arousal=.5;}
  const release=data.last_release?.activated_at||0;
  if(Date.now()/1000-release<2&&!data.scene.active_project)valence=.85;
  const surprise=emotion.surprise||0,mouth=emotion.mouth||surprise*.65;
  ctx.save();ctx.translate(x,y);ctx.rotate(emotion.tilt||0);ctx.translate(-x,-y);
  const gaze=emotion.gaze||data.scene.objects?.[0]&&[data.scene.objects[0].x,data.scene.objects[0].y]||[x+40,y];
  const gx=Math.max(-2.4,Math.min(2.4,(gaze[0]-x)/65)),gy=Math.max(-1.5,Math.min(1.5,(gaze[1]-y)/100));
  const blink=((now/1000+data.self.session_id*.77)%4.7)<.13;
  if(!skin.no_cranium){const g=ctx.createRadialGradient(x-r*.4,y-r*.5,1,x,y,r*1.4);g.addColorStop(0,"#ffffff");g.addColorStop(1,skin.fill||"#e6edf1");ctx.fillStyle=g;ctx.strokeStyle=skin.stroke||"#26384b";ctx.lineWidth=skin.line_width||5;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.stroke();}
  const faceInk=skin.eye||"#243649";ctx.fillStyle=faceInk;ctx.strokeStyle=faceInk;ctx.lineWidth=1.5;
  for(const side of [-1,1]){
    const ex=x+side*r*.36,ey=y-r*.12;
    if(blink||emotion.squint>.8){sceneLine(ctx,[[ex-2,ey],[ex+2,ey]],faceInk,1.7);}
    else{ctx.beginPath();ctx.ellipse(ex+gx,ey+gy,1.5+surprise*.8,1.7+arousal*.8+surprise*1.6,0,0,Math.PI*2);ctx.fill();}
    const tilt=valence<-.2?side*-1.6:side*.4;
    sceneLine(ctx,[[ex-2.5,ey-4-focus-surprise*4+tilt],[ex+2.5,ey-4-focus-surprise*4-tilt]],faceInk,1.2);
  }
  ctx.beginPath();
  if(mouth>.2){ctx.ellipse(x,y+r*.4,2+mouth*2,1+mouth*4,0,0,Math.PI*2);ctx.fill();}
  else{ctx.moveTo(x-3.6,y+r*.36);ctx.quadraticCurveTo(x,y+r*.36+valence*5,x+3.6,y+r*.36);ctx.stroke();}
  if(valence>.5){ctx.fillStyle="#dd927a55";for(const side of [-1,1]){ctx.beginPath();ctx.ellipse(x+side*7,y+3,2.6,1.5,0,0,Math.PI*2);ctx.fill();}}
  ctx.restore();
}
function paintScene(ctx,now,data,body){
  const vectorWorld=!!(data?.art&&data?.environment);
  const key=(data?.theme?.background||"default")+JSON.stringify(data?.environment||null);
  if(!vectorWorld&&backdropKey!==key){
    backdropKey=key;backdropCache=document.createElement("canvas");backdropCache.width=1000;backdropCache.height=600;
    const target=backdropCache.getContext("2d");
    ((ctx)=>{
  if(typeof paintEnvironment==="function"&&paintEnvironment(ctx,data?.environment))return;
  const base=data?.theme?.background;
  const bg=ctx.createLinearGradient(0,0,0,600);bg.addColorStop(0,base&&base!=="#ffffff"?base:"#e9eff5");bg.addColorStop(.75,"#f8fafb");bg.addColorStop(1,"#dde5e8");ctx.fillStyle=bg;ctx.fillRect(0,0,1000,600);
  const light=ctx.createRadialGradient(680,110,5,680,110,600);light.addColorStop(0,"#ffffffaa");light.addColorStop(1,"#ffffff00");ctx.fillStyle=light;ctx.fillRect(0,0,1000,540);
  ctx.strokeStyle="#d7e1e85a";ctx.lineWidth=.7;
  for(let x=0;x<=1000;x+=80)sceneLine(ctx,[[x,0],[x,540]],"#d8e3eb33",.8);
  const ground=ctx.createLinearGradient(0,540,0,600);ground.addColorStop(0,"#d9e3e4");ground.addColorStop(1,"#e7eeef");ctx.fillStyle=ground;ctx.fillRect(0,540,1000,60);sceneLine(ctx,[[0,540],[1000,540]],"#b2c4ce",1.3);
  for(let x=0;x<1000;x+=40)sceneLine(ctx,[[x,540],[x-35,600]],"#c3d1d644",.6);
    })(target);
  }
  ctx.clearRect(0,0,1000,600);
  if(vectorWorld)vectorLandscape(ctx,data.environment,data.art,(body?.tick||0)/60);else ctx.drawImage(backdropCache,0,0,1000,600);
  if(!data||!body?.nodes?.head)return;
  vectorLayers(ctx,data,false);
  if(typeof drawAuthored==="function")drawAuthored(ctx,now,data,body,"background");
  if(typeof drawProject==="function")drawProject(ctx,data,body,"world","background");
  paintPhysicalShadows(ctx,data,body);
  const states=new Map((body.objects||[]).map(o=>[o[0],o]));
  for(const o of data.scene.objects)paintObject(ctx,o,states.get(o.id),data);
  if(typeof paintConnections==="function")paintConnections(ctx,data,body);
  const n=body.nodes,skin=data.appearance||{};
  const hideBody=typeof directionData==="function"&&directionData(data,body).hide_body;
  if(!hideBody&&!(data.character&&paintAnatomy(ctx,now,data,body))){
  const groundX=(n.left_foot[0]+n.right_foot[0])/2,altitude=Math.max(0,535-Math.max(n.left_foot[1],n.right_foot[1]));
  shadow(ctx,groundX,541,34,5,.15*Math.max(.2,1-altitude/200));
  ctx.save();ctx.lineCap="round";ctx.lineJoin="round";
  const ink=skin.stroke||"#25374b",width=skin.line_width||5;
  for(const [a,b] of data.links){
    if(a==="head")continue;
    sceneLine(ctx,[[n[a][0]+1.3,n[a][1]+1.3],[n[b][0]+1.3,n[b][1]+1.3]],"#142a3b12",width+2);
    sceneLine(ctx,[n[a],n[b]],ink,width);
    sceneLine(ctx,[[n[a][0]-.8,n[a][1]],[n[b][0]-.8,n[b][1]]],"#ffffff22",1);
  }
  for(const name of ["left_foot","right_foot"]){const p=n[name];sceneLine(ctx,[[p[0]-4,p[1]],[p[0]+6,p[1]]],ink,width+1);}
  for(const name of ["left_hand","right_hand"]){const p=n[name];ctx.fillStyle=skin.accent||"#6b8dba";ctx.beginPath();ctx.arc(...p,Math.max(2,width*.48),0,Math.PI*2);ctx.fill();}
  for(const part of data.appendages||[]){const state=body.appendages?.find(p=>p[0]===part.id);if(state){sceneLine(ctx,[state[1],state[2]],part.color,part.radius*2);ctx.fillStyle=part.color;ctx.beginPath();ctx.arc(...state[2],part.radius*1.3,0,Math.PI*2);ctx.fill();}}
  paintFace(ctx,n.head,skin,{...(body.emotion||data.scene.emotion||{}),tilt:(body.emotion?.tilt||0)+(data.body_control?.mode==="physical"?(body.articulation?.head?.world_angle||0):0)},now,data);
  if(data.life?.thinking){
    const x=n.head[0]+30,y=n.head[1]-25;
    for(let i=0;i<3;i++){ctx.fillStyle=`rgba(91,126,165,${.3+.5*(.5+.5*Math.sin(now/230-i))})`;ctx.beginPath();ctx.arc(x+i*7,y-Math.sin(now/230-i)*2,2,0,Math.PI*2);ctx.fill();}
  }
  ctx.restore();
  }
  vectorLayers(ctx,data,true);
  if(typeof drawProject==="function")drawProject(ctx,data,body,"world","foreground");
  if(typeof drawAuthored==="function")drawAuthored(ctx,now,data,body,"foreground");
}
function worldPointer(event){const r=canvas.getBoundingClientRect(),p=[(event.clientX-r.left)/r.width*1000,(event.clientY-r.top)/r.height*600];return typeof screenToWorld==="function"?screenToWorld(p):p;}
async function directInput(body){if(sessionId)await api(`game/sessions/${sessionId}/input`,"POST",body);}
canvas.addEventListener("pointerdown",event=>{
  if(!sceneData)return;const [x,y]=worldPointer(event),states=new Map((displayed?.objects||[]).map(o=>[o[0],o]));
  const obj=[...sceneData.scene.objects].reverse().find(o=>{if(o.kind!=="body"||o.motion==="static")return false;const s=states.get(o.id),dx=x-(s?.[1]??o.x),dy=y-(s?.[2]??o.y);return o.shape==="circle"?Math.hypot(dx,dy)<o.radius+10:Math.abs(dx)<o.width/2+8&&Math.abs(dy)<o.height/2+8;});
  if(obj){pointerDrag=obj.id;canvas.setPointerCapture(event.pointerId);directInput({type:"grab",id:obj.id,x,y}).catch(error);}
});
canvas.addEventListener("pointermove",event=>{if(!pointerDrag||performance.now()-pointerSent<35)return;pointerSent=performance.now();const[x,y]=worldPointer(event);directInput({type:"grab",id:pointerDrag,x,y}).catch(error);});
canvas.addEventListener("pointerup",()=>{if(pointerDrag){pointerDrag=null;directInput({type:"release"}).catch(error);}});
canvas.addEventListener("pointercancel",()=>{pointerDrag=null;directInput({type:"release"}).catch(error);});
window.addEventListener("keydown",event=>{if(["TEXTAREA","INPUT","SELECT"].includes(event.target.tagName))return;if(["ArrowLeft","ArrowRight"," "].includes(event.key)){event.preventDefault();if(sceneData?.body_control?.mode==="physical"){if(event.key===" ")stopMuscle();else manualMuscle(event.key==="ArrowLeft"?-.7:.7);return;}directInput({type:"drive",drive:event.key==="ArrowLeft"?-1:event.key==="ArrowRight"?1:0,jump:event.key===" "}).catch(error);}});
window.addEventListener("keyup",event=>{if(["ArrowLeft","ArrowRight"].includes(event.key)&&sceneData?.body_control?.mode==="physical"){stopMuscle();return;}if(["ArrowLeft","ArrowRight"].includes(event.key))directInput({type:"drive",drive:0}).catch(error);});

let visionFrames=[],visionScope=null,visionLast=0;
async function captureVision(){
  if(!sessionId||!sceneData)return;
  if(!$("vision-enabled").checked)return;
  const id=sessionId,version=sceneData.scene.version;
  const scope=`${id}:${version}`;
  if(scope!==visionScope){visionScope=scope;visionFrames=[];visionLast=0;}
  const current=document.createElement("canvas");current.width=384;current.height=230;
  const target=current.getContext("2d");target.drawImage(canvas,0,0,384,230);
  target.fillStyle="#172a3e";target.fillRect(0,0,384,18);target.fillStyle="#eff7ff";target.font="11px monospace";target.fillText(`v${version} · ${(displayed?.tick/60||0).toFixed(1)}s`,8,13);
  if(!visionFrames.length||performance.now()-visionLast>800){visionLast=performance.now();visionFrames.push(current);visionFrames=visionFrames.slice(-3);}
  const preview=document.createElement("canvas");preview.width=384*visionFrames.length;preview.height=230;
  visionFrames.forEach((frame,i)=>preview.getContext("2d").drawImage(frame,i*384,0));
  const image=preview.toDataURL("image/jpeg",.5);
  if(image.length<60000)await api(`game/sessions/${id}/vision`,"POST",{image,version}).catch(()=>{});
}
$("vision-enabled").onchange=()=>{$("vision-enabled").checked?captureVision().catch(()=>{}):api(`game/sessions/${sessionId}/vision`,"POST",{enabled:false}).catch(()=>{});};
setInterval(()=>{if(!document.hidden&&sessionId)captureVision().catch(()=>{});},2500);

const qualityControl=document.getElementById("render-quality");if(qualityControl)qualityControl.onchange=()=>{sceneQuality=qualityControl.value;sceneIntervals=[];sceneFastFrames=0;};
