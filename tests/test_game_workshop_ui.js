import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function host(){
 const calls=[],callbacks=[];const nodes=new Map();
 const node=tag=>({tag,children:[],attrs:{},append(...items){this.children.push(...items)},setAttribute(k,v){this.attrs[k]=v}});
 nodes.set('muscle-joint',{value:'right_hand'});
 const context={document:{getElementById:id=>nodes.get(id),createElementNS:(_,tag)=>node(tag),querySelectorAll:()=>[]},window:{addEventListener(){}},sessionId:1,sceneData:{scene:{version:7}},api:(...args)=>{calls.push(args);return Promise.resolve()},humanControl(){throw Error('should dispatch locally')},error(){},setInterval:fn=>{callbacks.push(fn);return callbacks.length},clearInterval(){}};
 vm.runInNewContext(fs.readFileSync(new URL('../game/static/workshop.js',import.meta.url),'utf8'),context);
 return {context,node,calls,callbacks};
}
test('skill icons use bundled SVG paths without relying on emoji fonts',()=>{
 const {context,node}=host(),span=node('span');context.drawSkillIcon(span,'🦾');
 assert.equal(span.children[0].tag,'svg');assert.ok(span.children[0].children.length>0);
 const custom=node('span');context.drawSkillIcon(custom,'ABC');assert.equal(custom.textContent,'ABC');
});
test('skill buttons dispatch version-bound local project events',async()=>{
 const {context,calls}=host();await context.localSkill({id:'pull',target:{type:'project',name:'test'}},7);
 assert.equal(calls[0][0],'game/sessions/1/interact');assert.equal(calls[0][2].widget_id,'pull');assert.equal(calls[0][2].version,7);
});
test('held muscle input stops on a session change instead of acting on a new body',()=>{
 const {context,calls,callbacks}=host();context.manualMuscle(.7);context.sessionId=2;callbacks[0]();
 assert.ok(calls.length>=2);assert.ok(calls.every(c=>c[0]==='game/sessions/1/input'));assert.equal(calls.at(-1)[2].effort,0);
});
