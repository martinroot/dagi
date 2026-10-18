import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function studioUi(fetchImpl=async()=>({ok:true,json:async()=>({sessions:[],authenticated:true})})){
  const elements=new Map(),nodes=[];let clock=1000000;
  const ctx=new Proxy({}, {get:(o,k)=>o[k]||(()=>{})});
  function node(){const el={children:[],className:"",dataset:{},style:{setProperty(){}},classList:{toggle(){}},hidden:false,textContent:"",value:"",
    append(...a){this.children.push(...a);},replaceChildren(...a){this.children=a;},setAttribute(){},getBoundingClientRect:()=>({width:800,height:480}),getContext:()=>ctx};nodes.push(el);return el;}
  const document={hidden:false,documentElement:{style:{setProperty(){}},scrollWidth:1280},createElement:node,
    getElementById(id){if(!elements.has(id))elements.set(id,node());return elements.get(id);},
    querySelectorAll(selector){return nodes.filter(el=>el.className.split(" ").includes(selector.slice(1)));}};
  class FakeDate extends Date{static now(){return clock;}}
  const context={document,Date:FakeDate,location:{href:"https://example.com/game/"},URL,innerWidth:1280,innerHeight:900,
    performance:{now:()=>0},requestAnimationFrame(){},setInterval(){},EventSource:class{close(){}},fetch:fetchImpl};
  for(const file of ["game.js","studio.js"])vm.runInNewContext(fs.readFileSync(new URL(`../game/static/${file}`,import.meta.url),"utf8"),context);
  return {context,elements,ctx,clock(value){clock=value;}};
}
const data=()=>({self:{body_id:"stickman:1",session_id:1,code:{engine:"game/world.py"}},scene:{version:0,revision:0,position:{x:180,y:450},objects:[],tick:0},
  widgets:[],theme:{background:"#ffffff",accent:"#e6703a"},activity:{phase:"idle"},server_time:1000,frame:{tick:0,nodes:{hip:[180,450]}}});

test("countdown waits for server activation before showing the updated-world burst",()=>{
  const ui=studioUi(),world=data();world.build={state:"scheduled",activate_at:1003.2,edits:1};
  ui.context.studioRuntime(world);
  ui.context.drawStudio(ui.ctx,0,world,world.frame);
  assert.equal(ui.elements.get("release-number").textContent,"3");
  ui.clock(1001400);ui.context.drawStudio(ui.ctx,0,world,world.frame);
  assert.equal(ui.elements.get("release-number").textContent,"2");
  ui.clock(1002400);ui.context.drawStudio(ui.ctx,0,world,world.frame);
  assert.equal(ui.elements.get("release-number").textContent,"1");
  ui.clock(1003400);ui.context.drawStudio(ui.ctx,0,world,world.frame);
  assert.equal(ui.elements.get("release-number").textContent,"…");
  const updated={...world,scene:{...world.scene,version:1},build:null,last_release:{id:"verified-release"}};
  ui.context.studioRelease(world,updated);ui.context.drawStudio(ui.ctx,100,updated,world.frame);
  assert.equal(ui.elements.get("release-number").textContent,"БАХ");
  assert.equal(ui.elements.get("release-overlay").dataset.releaseId,"verified-release");
  ui.context.drawStudio(ui.ctx,1600,updated,world.frame);
  assert.equal(ui.elements.get("release-overlay").hidden,true);
});

test("development control starts the bounded living mechanism without prescribing an activity",async()=>{
  const ui=studioUi();let action="";
  ui.context.lifeAction=(value)=>{action=value;return Promise.resolve();};
  await ui.elements.get("improve-self").onclick();
  assert.equal(action,"start");
  const html=fs.readFileSync(new URL("../game/static/index.html",import.meta.url),"utf8");
  assert.match(html,/id="life-pause"/);
  assert.match(html,/id="life-iterations"/);
  assert.doesNotMatch(html,/data-prompt=/);
});

test("draft widgets are visibly staged and reset on a session change",()=>{
  const ui=studioUi(),world=data();world.build={state:"building",objective:"try",edits:1,test_count:0};
  world.preview={objects:[],widgets:[{id:"button",kind:"button",x:600,y:70,width:200,height:60,title:"Walk",target:{type:"action",action:"right",frames:30}}]};
  ui.context.studioRefresh(world);
  assert.equal(ui.elements.get("draft-label").hidden,false);
  assert.equal(ui.elements.get("visual-layer").children.length,1);
  assert.equal(ui.elements.get("human-controls").children[0].disabled,true);
  ui.context.studioReset();
  assert.equal(ui.elements.get("visual-layer").children.length,0);
  assert.equal(ui.elements.get("release-overlay").hidden,true);
});

test("runtime API/tool state refreshes even when the physical world revision is unchanged",async()=>{
  let phase="provider";
  const world=data();
  const ui=studioUi(async(url)=>({ok:true,json:async()=>{
    const path=new URL(url).pathname;
    if(path==="/api/auth/session")return {authenticated:true};
    if(path==="/api/game/sessions")return {sessions:[]};
    if(path==="/api/game/sessions/1")return {...world,motion:[],history:[],activity:{phase,tool:"game_build"}};
    return {session:{id:1},messages:[],tool_calls:[],runs:[],event_cursors:{}};
  }}));
  await new Promise(resolve=>setImmediate(resolve));
  await ui.context.selectSession(1,"body");
  assert.match(ui.elements.get("mechanism-phase").textContent,/LLM API/);
  phase="tool";await ui.context.refreshWorld();
  assert.match(ui.elements.get("mechanism-phase").textContent,/game_build/);
});
