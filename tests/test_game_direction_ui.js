import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function viewer(reduced=false){
 const elements=new Map(['shot-state','camera-overview','project-signal'].map(id=>[id,{}]));
 const calls=[];
 const c={document:{getElementById:id=>elements.get(id)},sessionId:1,sceneData:{scene:{version:2,active_project:'custom'}},matchMedia:()=>({matches:reduced}),api:(...args)=>{calls.push(args);return Promise.resolve()},error(){}};
 for(const f of ['vector.js','direction.js'])vm.runInNewContext(fs.readFileSync(new URL('../game/static/'+f,import.meta.url),'utf8'),c);
 const body={nodes:{head:[200,350]},objects:[['wheel',600,400,0]],appendages:[['extra',[200,360],[240,340]]],direction:{camera:{target:'head',zoom:3,ease:.05},beat:'notice'}};
 return {c,elements,calls,body};
}
test('camera follows live joints and pointer transform exactly reverses projection',()=>{
 const {c,body}=viewer();for(let i=0;i<60;i++)c.prepareDirection(i*16,{},body);
 const screen=c.worldToScreen([200,350]);assert.ok(Math.abs(screen[0]-500)<.1);
 const original=c.screenToWorld(screen);assert.ok(Math.abs(original[0]-200)<1e-8&&Math.abs(original[1]-350)<1e-8);
 assert.ok(c.worldToScreen([210,350])[0]-screen[0]>29);
});
test('camera can track physical objects and newly attached body parts',()=>{
 const {c,body}=viewer();assert.deepEqual([...c.cameraTarget({target:'wheel'},{},body)],[600,400]);
 assert.deepEqual([...c.cameraTarget({target:'extra'},{},body)],[240,340]);
});
test('human overview overrides shot without changing world',()=>{
 const {c,elements,body}=viewer();for(let i=0;i<60;i++)c.prepareDirection(i*16,{},body);
 elements.get('camera-overview').onclick();for(let i=60;i<300;i++)c.prepareDirection(i*16,{},body);
 assert.ok(Math.abs(c.worldToScreen([500,300])[0]-500)<.1);
 assert.equal(elements.get('shot-state').textContent,'ОБЩИЙ ПЛАН');
});
test('reduced motion caps zoom and removes authored shake',()=>{
 const {c,body}=viewer(true);body.direction.camera.shake=5;
 for(let i=0;i<60;i++)c.prepareDirection(i*16,{},body);
 assert.ok(c.worldToScreen([210,350])[0]-c.worldToScreen([200,350])[0]<=15.01);
});
test('draw layers keep screen graphics separate from physical world coordinates',()=>{
 const {c,body}=viewer();const labels=[];
 body.direction.draw=[{type:'text',x:10,y:20,text:'world'},{type:'text',x:10,y:20,text:'screen',space:'screen'}];
 const ctx={save(){},restore(){},beginPath(){},fillText(text){labels.push(text)}};
 c.drawProject(ctx,{},body,'world','foreground');assert.deepEqual(labels,['world']);
 c.drawProject(ctx,{},body,'screen','foreground');assert.deepEqual(labels,['world','screen']);
});
test('human attention is sent as a local version-bound event',async()=>{
 const {c,elements,calls}=viewer();await elements.get('project-signal').onclick();
 assert.equal(calls[0][0],'game/sessions/1/project-event');
 assert.equal(calls[0][2].id,'human_attention');assert.equal(calls[0][2].version,2);
});
