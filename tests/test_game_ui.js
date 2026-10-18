import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const response = (value) => ({ok:true, status:200, json:async()=>value});
const snapshot = (id, runs = []) => ({session:{id}, runs, messages:[], tool_calls:[], event_cursors:{}});
const world = (id, revision = 0) => ({self:{body_id:`stickman:${id}`,session_id:id,workspace:`/world/${id}`,code:{engine:"game/world.py"}},
  scene:{revision,position:{x:180+revision,y:450},tick:revision*60,upright:true,grounded:true,controller:{},physics:{},objects:[],behaviors:{}},
  frame:{tick:revision*60,nodes:{}},motion:[],history:[]});
function ui(fetch) {
  const elements = new Map(), sources = [];
  const element = () => ({children:[],textContent:"",value:"",hidden:false,disabled:false,
    append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},getContext(){return {};}});
  const document = {hidden:false,querySelectorAll:()=>[],createElement:element,
    getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}};
  class EventSource {constructor(url){this.url=String(url);sources.push(this);}close(){this.closed=true;}}
  const context = {document,location:{href:"https://example.com/dagi/game/"},URL,EventSource,
    fetch:(url,options)=>fetch(new URL(url),options),requestAnimationFrame(){},setInterval(){},performance:{now:()=>0}};
  vm.runInNewContext(fs.readFileSync(new URL("../game/static/game.js",import.meta.url),"utf8"),context);
  return {context,elements,sources};
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
