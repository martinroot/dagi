import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const response = (value) => ({ok:true, status:200, json:async()=>value});
const snapshot = (id, runs = []) => ({session:{id}, runs, messages:[], tool_calls:[], event_cursors:{}});
const world = (id, revision = 0) => ({self:{body_id:`stickman:${id}`,session_id:id,workspace:`/world/${id}`,code:{engine:"game/world.py"},programs:[]},
  scene:{revision,position:{x:180+revision,y:450},tick:revision*60,upright:true,grounded:true,controller:{},physics:{},objects:[],behaviors:{},autonomy_execution:null},
  frame:{tick:revision*60,nodes:{}},links:[],motion:[],history:[]});
function ui(fetch) {
  const elements = new Map(), sources = [], created = [], drawnText = [];
  const canvasContext = {clearRect(){},fillRect(){},beginPath(){},arc(){},fill(){},stroke(){},moveTo(){},lineTo(){},setLineDash(){},save(){},restore(){},fillText(text){drawnText.push(text);}};
  const element = (tagName = "") => ({tagName,children:[],textContent:"",value:"",hidden:false,disabled:false,
    append(...children){this.children.push(...children);},appendChild(child){this.children.push(child);},
    replaceChildren(...children){this.children=children;},getContext(){return canvasContext;},
    click(){this.clicked=true;},remove(){this.removed=true;}});
  const document = {hidden:false,body:element("body"),querySelectorAll:()=>[],
    createElement(tagName){const node=element(tagName);created.push(node);return node;},
    getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}};
  class EventSource {constructor(url){this.url=String(url);sources.push(this);}close(){this.closed=true;}}
  const context = {document,location:{href:"https://example.com/dagi/game/"},URL,Blob,EventSource,
    fetch:(url,options)=>fetch(new URL(url),options),requestAnimationFrame(){},setInterval(){},setTimeout(callback){callback();return 1;},performance:{now:()=>0}};
  vm.runInNewContext(fs.readFileSync(new URL("../game/static/game.js",import.meta.url),"utf8"),context);
  return {context,elements,sources,created,drawnText};
}
const tick = () => new Promise((resolve)=>setImmediate(resolve));

test("game UI keeps API calls inside the mounted prefix and ignores stale session responses",async()=>{
  let resolveOld;
  const delayed = new Promise((resolve)=>resolveOld=resolve);
  const {context,elements} = ui(async(url)=>{
    assert.ok(url.pathname.startsWith("/dagi/api/"));
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/1")return delayed;
    if(path==="sessions/2")return response(snapshot(2));
    if(path==="game/sessions/2")return response(world(2));
    throw new Error(path);
  });
  await tick();
  const old=context.selectSession(1,"old");
  await context.selectSession(2,"new");
  resolveOld(response(snapshot(1))); await old;
  assert.equal(elements.get("title").textContent,"new");
  assert.match(elements.get("identity").textContent,/stickman:2/);
});

test("game UI identifies saved skill versions and displays autonomous execution progress",async()=>{
  const active=world(12,5);
  active.self.programs=[{name:"pace",version:"abc123def456",steps:2,complexity_score:7}];
  active.scene.autonomy_execution={program:"pace",program_version:"abc123def456",complexity_score:7,status:"running",
    cycles_completed:2,cycles_requested:5,frames_executed:48,start_x:200,current_x:210,goal_distance_change:-1.5};
  const {context,elements}=ui(async(url)=>{
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/12")return response(snapshot(12));
    if(path==="game/sessions/12")return response(active);
    throw new Error(path);
  });
  await tick();await context.selectSession(12,"autonomous");
  assert.match(elements.get("identity").textContent,/pace@abc123def456/);
  assert.equal(elements.get("autonomy-status").hidden,false);
  assert.match(elements.get("autonomy-status").textContent,/2\/5 циклов/);
  assert.match(elements.get("autonomy-status").textContent,/Δx 10.00/);
  assert.match(elements.get("autonomy-status").textContent,/goal Δ -1.50/);
});

test("character animates a focused cue during motion and the measured status afterward",async()=>{
  const initial=world(12,5);initial.scene.avatar_state="satisfied";initial.frame.nodes={head:[500,300]};
  const active={...initial,scene:{...initial.scene,revision:6,tick:320},frame:{tick:320,nodes:{head:[510,300]}},motion:[
    {tick:300,nodes:{head:[500,300]}},{tick:320,nodes:{head:[510,300]}}
  ]};
  let reads=0;
  const {context,drawnText}=ui(async(url)=>{
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/12")return response(snapshot(12));
    if(path==="game/sessions/12")return response(++reads===1?initial:active);
    throw new Error(path);
  });
  await tick();await context.selectSession(12,"embodied expression");
  await context.refreshWorld();context.draw(10);
  assert.ok(drawnText.includes("•"));
  context.draw(1000);
  assert.ok(drawnText.includes("✓"));
});

test("game UI renders ladder contact, climbing pose and measured activity from the scene",async()=>{
  const active=world(12,6);
  active.scene.activity="climbing";
  active.scene.contact={object_id:"wind-ladder",kind:"ladder",x:270,y:260,height:280};
  active.scene.objects=[{id:"wind-ladder",kind:"ladder",x:270,y:260,width:35,height:280}];
  active.scene.autonomy_execution={program:"wind_ladder_mount",program_version:"a5fb9711b93f",complexity_score:12,
    verified_complexity:30,climbed_y:24.5,status:"running",cycles_completed:1,cycles_requested:2,
    frames_executed:120,start_x:256,current_x:270};
  active.frame.nodes={head:[270,330],hip:[270,400],neck:[270,345],left_hand:[250,330],right_hand:[292,330],
    left_elbow:[252,350],right_elbow:[288,350],left_knee:[262,442],right_knee:[278,442],left_foot:[258,484],right_foot:[282,484]};
  const {context,elements,drawnText}=ui(async(url)=>{
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/12")return response(snapshot(12));
    if(path==="game/sessions/12")return response(active);
    throw new Error(path);
  });
  await tick();await context.selectSession(12,"ladder contact");await context.refreshWorld();context.draw(10);
  assert.match(elements.get("observation").textContent,/Активность: climbing/);
  assert.match(elements.get("observation").textContent,/Контакт: wind-ladder/);
  assert.match(elements.get("autonomy-status").textContent,/→V30/);
  assert.match(elements.get("autonomy-status").textContent,/подъём 24\.50/);
  assert.ok(drawnText.some((text)=>text.includes("CONTACT")));
});

test("download button saves the selected session's log as JSON",async()=>{
  assert.match(fs.readFileSync(new URL("../game/static/index.html",import.meta.url),"utf8"),/id="download-log"/);
  const requested=[];
  const {context,created}=ui(async(url,options)=>{
    requested.push({path:url.pathname,credentials:options.credentials});
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/12")return response(snapshot(12));
    if(path==="game/sessions/12")return response(world(12));
    if(path==="game/sessions/12/export")return response({format:"dagi-session-export-v1",session:{id:12}});
    throw new Error(path);
  });
  await tick();await context.selectSession(12,"export target");
  await context.downloadSessionLog();
  assert.ok(requested.some((item)=>item.path==="/dagi/api/game/sessions/12/export"&&item.credentials==="same-origin"));
  const anchor=created.find((item)=>item.tagName==="a"&&item.download);
  assert.equal(anchor.download,"dagi-session-12.json");
  assert.equal(anchor.clicked,true);
  assert.equal(anchor.removed,true);
});

test("a delayed lower world revision cannot roll back the displayed body",async()=>{
  let reads=0, resolveOld;
  const delayed=new Promise((resolve)=>resolveOld=resolve);
  const {context,elements}=ui(async(url)=>{
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/1")return response(snapshot(1));
    if(path==="game/sessions/1") {reads++;return reads===2?delayed:response(world(1,reads===1?0:2));}
    throw new Error(path);
  });
  await tick();await context.selectSession(1,"body");
  const old=context.refreshWorld();await context.refreshWorld();
  resolveOld(response(world(1,1)));await old;
  assert.match(elements.get("observation").textContent,/Ревизия: 2/);
});

test("game SSE deduplicates chunks and closes old streams when changing worlds",async()=>{
  const {context,elements,sources}=ui(async(url)=>{
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/1")return response({...snapshot(1,[{run_id:"live",status:"running"}]),event_cursors:{live:0}});
    if(path==="sessions/2")return response(snapshot(2));
    if(path==="game/sessions/1")return response(world(1));
    if(path==="game/sessions/2")return response(world(2));
    throw new Error(path);
  });
  await tick();await context.selectSession(1,"one");
  const source=sources.at(-1), event={lastEventId:"7",data:JSON.stringify({kind:"text",session_id:1,run_id:"live",text:"hello"})};
  source.onmessage(event);source.onmessage(event);
  assert.equal(elements.get("chat").children.length,1);
  assert.equal(elements.get("chat").children[0].children[1].textContent,"hello");
  await context.selectSession(2,"two");
  assert.equal(source.closed,true);
  source.onmessage({...event,lastEventId:"8"});
  assert.equal(elements.get("chat").children.length,0);
});

test("resuming a running game restores in-flight text before reconnecting SSE",async()=>{
  const {context,elements,sources}=ui(async(url)=>{
    const path=url.pathname.slice("/dagi/api/".length);
    if(path==="auth/session")return response({authenticated:true});
    if(path==="game/sessions")return response({sessions:[]});
    if(path==="sessions/1")return response({...snapshot(1,[{run_id:"live",status:"running"}]),event_cursors:{live:9}});
    if(path==="game/sessions/1")return response(world(1));
    if(path === "runs/live/events")return response({events:[{id:9,event:{kind:"text",text:"restored"}}],next_after:9,has_more:false});
    throw new Error(path);
  });
  await tick();await context.selectSession(1,"one");
  const source=sources.at(-1);
  assert.match(source.url,/after=9/);
  source.onmessage({lastEventId:"10",data:JSON.stringify({kind:"text",text:" + live",session_id:1,run_id:"live"})});
  assert.equal(elements.get("chat").children.length,1);
  assert.equal(elements.get("chat").children[0].children[1].textContent,"restored + live");
});
