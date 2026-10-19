/* Agent-authored JS executes in disposable workers inside opaque CSP frames.
 * Only validated drawing commands and declared events cross into the viewer. */
"use strict";
const authored = new Map();
let authoredScene = null, authoredSession = null, authoredScope = null;
const workerBootstrap = `(()=>{
const send=self.postMessage.bind(self);let render=null,state={};
for(const name of ['fetch','XMLHttpRequest','WebSocket','EventSource','Worker','SharedWorker','importScripts','postMessage']){
 try{Object.defineProperty(self,name,{value:undefined,writable:false,configurable:false});}catch{}
}
self.addEventListener('message',(event)=>{
 if(!event.isTrusted)return;
 try{
  if(event.data.kind==='compile'){
   render=new Function('input',event.data.code);
   send({kind:'compiled'});return;
  }
  const result=render({...event.data.input,state});
  if(!result||typeof result!=='object'||!Array.isArray(result.commands))throw new Error('Return {commands:[...],state:{...}}');
  const encoded=JSON.stringify(result);
  if(encoded.length>24000||result.commands.length>160)throw new Error('Output limit: 160 commands / 24 KB');
  state=result.state||{};
  send({kind:'result',result:JSON.parse(encoded)});
 }catch(error){send({kind:'error',detail:String(error).slice(0,300)});}
});})();`;

const componentFrame = `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none';script-src 'unsafe-inline' 'unsafe-eval' blob:;worker-src blob:;connect-src 'none';img-src 'none';style-src 'none';frame-src 'none';form-action 'none';base-uri 'none'"><script>
const bootstrap=${JSON.stringify(workerBootstrap).replace(/</g,"\\u003c")};let worker=null,timer=null;
const tell=(value)=>parent.postMessage(value,'*');
onmessage=(event)=>{
 if(event.source!==parent)return;
 if(event.data.kind==='compile'){
  if(worker)worker.terminate();
  const url=URL.createObjectURL(new Blob([bootstrap],{type:'text/javascript'}));
  worker=new Worker(url);URL.revokeObjectURL(url);
  worker.onmessage=(e)=>{clearTimeout(timer);tell(e.data);};
  worker.onerror=(e)=>{clearTimeout(timer);worker.terminate();tell({kind:'error',detail:String(e.message).slice(0,300)});};
 }
 if(!worker)return;
 clearTimeout(timer);timer=setTimeout(()=>{worker.terminate();worker=null;tell({kind:'error',detail:'Worker time limit exceeded'});},event.data.kind==='compile'?500:100);
 worker.postMessage(event.data);
};tell({kind:'ready'});
</script>`;

function authoredReset(){for(const record of authored.values())record.frame.remove();authored.clear();authoredScene=null;authoredSession=null;authoredScope=null;}
function authoredSync(data){
  const scope=data.build?.id||`live:${data.scene.version}`;
  if(authoredSession!==sessionId||authoredScope!==scope){authoredReset();authoredSession=sessionId;authoredScope=scope;}
  authoredScene=data;
  const list=(data.build ? data.preview?.components : data.components)||[];
  for(const [id,record] of authored){if(!list.some(c=>c.id===id&&c.code_hash===record.component.code_hash)){record.frame.remove();authored.delete(id);}}
  for(const component of list){
    const existing=authored.get(component.id);
    if(existing){existing.component=component;continue;}
    const frame=document.createElement('iframe');frame.hidden=true;frame.sandbox='allow-scripts';
    frame.setAttribute('referrerpolicy','no-referrer');frame.setAttribute('aria-hidden','true');
    const record={component,frame,commands:[],status:'pending',detail:'Waiting for code probe',busy:true,event:null,lastFrame:0};
    authored.set(component.id,record);frame.srcdoc=componentFrame;document.body.append(frame);
  }
}
function validCommands(value,component){
  if(!Array.isArray(value)||value.length>160)throw new Error('Invalid draw list');
  for(const c of value){
    if(!c||typeof c!=='object'||!['rect','circle','line','text','button'].includes(c.type))throw new Error('Unknown drawing primitive');
    const numbers=['x','y',...(c.type==='line'?['x2','y2']:c.type==='circle'?['radius']:c.type==='rect'||c.type==='button'?['width','height']:[])];
    for(const name of numbers)if(typeof c[name]!=='number'||!Number.isFinite(c[name])||Math.abs(c[name])>2000)throw new Error('Invalid drawing geometry');
    for(const key of ['fill','stroke'])if(c[key]!==undefined&&(typeof c[key]!=='string'||!/^#[0-9a-fA-F]{6}$/.test(c[key])))throw new Error('Colors must use #RRGGBB');
    if(c.type==='text'||c.type==='button'){if(typeof c.text!=='string'||c.text.length>160)throw new Error('Invalid drawing text');}
    if(c.type==='circle'&&c.radius<0||['rect','button'].includes(c.type)&&(c.width<0||c.height<0))throw new Error('Negative drawing size');
    if(c.size!==undefined&&(typeof c.size!=='number'||!Number.isFinite(c.size)||c.size<6||c.size>60))throw new Error('Text size is 6..60');
    if(c.type==='button'&&!component.events.some(e=>e.id===c.event_id))throw new Error('Button event must be declared in component.events');
  }
  return value;
}
window.addEventListener('message',(event)=>{
  const record=[...authored.values()].find(r=>r.frame.contentWindow===event.source);
  if(!record||!authoredScene)return;
  const data=event.data;
  if(!data||typeof data!=='object')return;
  if(data.kind==='ready'){record.frame.contentWindow.postMessage({kind:'compile',code:record.component.code},'*');return;}
  if(data.kind==='compiled'){record.busy=false;return;}
  if(data.kind==='error'){
    record.status='error';record.detail=String(data.detail||'Component error').slice(0,300);record.busy=false;
    if(typeof studioMeasure==='function')studioMeasure(authoredScene);return;
  }
  if(data.kind==='result'){
    const previous=record.status;
    try{record.commands=validCommands(data.result.commands,record.component);record.status='passed';record.detail='Compiled and executed in an isolated browser worker; draw output validated';}
    catch(error){record.status='error';record.detail=String(error).slice(0,300);record.commands=[];}
    record.busy=false;
    if(previous!==record.status&&typeof studioMeasure==='function')studioMeasure(authoredScene);
  }
});
function authoredReports(){return [...authored.values()].filter(r=>r.status!=='pending').map(r=>({id:r.component.id,code_hash:r.component.code_hash,status:r.status,detail:r.detail}));}
function drawAuthored(ctx,now,data,body,layer){
  if(!data)return;
  for(const record of authored.values()){
    const c=record.component;if(c.layer!==layer)continue;
    if(!record.busy&&record.status!=='error'&&now-record.lastFrame>100){
      record.busy=true;record.lastFrame=now;
      record.frame.contentWindow.postMessage({kind:'frame',input:{width:c.width,height:c.height,time:now/1000,dt:.1,
        scene:{version:data.scene.version,body:body?.nodes||{},position:data.scene.position,goal:data.scene.goal,behaviors:Object.keys(data.scene.behaviors||{}),phase:studioActivity.phase},event:record.event}},'*');
      record.event=null;
    }
    ctx.save();ctx.beginPath();ctx.rect(c.x,c.y,c.width,c.height);ctx.clip();ctx.translate(c.x,c.y);
    if(data.build)ctx.globalAlpha=.65;
    if(record.status==='error'){ctx.fillStyle='#a84330';ctx.font='11px monospace';ctx.fillText('COMPONENT ERROR / '+c.title,4,16);}
    for(const cmd of record.commands){
      ctx.fillStyle=cmd.fill||'#eef0e6';ctx.strokeStyle=cmd.stroke||'#526344';ctx.lineWidth=1.5;
      if(cmd.type==='rect'||cmd.type==='button'){ctx.fillRect(cmd.x,cmd.y,cmd.width,cmd.height);ctx.strokeRect(cmd.x,cmd.y,cmd.width,cmd.height);}
      if(cmd.type==='circle'){ctx.beginPath();ctx.arc(cmd.x,cmd.y,cmd.radius,0,Math.PI*2);ctx.fill();ctx.stroke();}
      if(cmd.type==='line'){ctx.beginPath();ctx.moveTo(cmd.x,cmd.y);ctx.lineTo(cmd.x2,cmd.y2);ctx.stroke();}
      if(cmd.type==='text'||cmd.type==='button'){ctx.fillStyle=cmd.type==='text'?(cmd.fill||'#282d23'):'#282d23';ctx.font=`${cmd.size||12}px monospace`;ctx.fillText(cmd.text,cmd.x+(cmd.type==='button'?8:0),cmd.y+(cmd.type==='button'?20:0));}
    }
    ctx.restore();
  }
}
async function authoredEvent(componentId,eventId){
  if(!sceneData||sceneData.build||runId)return;
  const record=authored.get(componentId),event=record?.component.events.find(e=>e.id===eventId);if(!event)return;
  record.event={id:event.id};
  if(event.target){
    const token=generation;busy(true);
    try{const started=await api(`game/sessions/${sessionId}/interact`,'POST',{component_id:componentId,event_id:eventId,version:sceneData.scene.version});
      if(token!==generation)return;if(started.local){busy(false);await refreshWorld(token);return;}message('user',`Компонент: ${record.component.title} / ${event.label}`);runId=started.run_id;stream(runId,0,token);
    }catch(errorValue){busy(false);throw errorValue;}
  }
}
canvas.addEventListener('click',(event)=>{
  const box=canvas.getBoundingClientRect(),screen=[(event.clientX-box.left)*1000/box.width,(event.clientY-box.top)*600/box.height];
  const [x,y]=typeof screenToWorld==="function"?screenToWorld(screen):screen;
  for(const record of [...authored.values()].reverse()){
    const c=record.component;
    const button=record.commands.findLast(p=>p.type==='button'&&x>=c.x+p.x&&x<=c.x+p.x+p.width&&y>=c.y+p.y&&y<=c.y+p.y+p.height);
    if(button){authoredEvent(c.id,button.event_id).catch(error);return;}
  }
});
