import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
function renderer(){const c={};vm.runInNewContext(fs.readFileSync(new URL('../game/static/vector.js',import.meta.url),'utf8'),c);return c;}
test('Bezier geometry, gradient stops, matrix and shadow reach the canvas',()=>{
 const c=renderer(),calls=[],stops=[];
 const ctx={globalAlpha:1,save(){},restore(){},beginPath(){},transform(...m){calls.push(['matrix',...m])},createLinearGradient(...p){calls.push(['gradient',...p]);return{addColorStop(...s){stops.push(s)}}},moveTo(...p){calls.push(['M',...p])},bezierCurveTo(...p){calls.push(['C',...p])},closePath(){calls.push(['Z'])},fill(){calls.push(['fill'])}};
 c.vectorDraw(ctx,{type:'bezier',segments:[['M',0,0],['C',1,2,3,4,5,6],['Z']],fill:{type:'linear',from:[0,0],to:[5,6],stops:[[0,'#ffffff'],[1,'#112233']]},transform:[1,0,0,1,20,30],shadow:{color:'#112233',blur:5,x:2,y:3},blend:'multiply',alpha:.5});
 assert.deepEqual(calls,[['matrix',1,0,0,1,20,30],['gradient',0,0,5,6],['M',0,0],['C',1,2,3,4,5,6],['Z'],['fill']]);assert.deepEqual(stops,[[0,'#ffffff'],[1,'#112233']]);assert.equal(ctx.globalAlpha,.5);assert.equal(ctx.globalCompositeOperation,'multiply');assert.equal(ctx.shadowBlur,5);
});
test('Vector layers preserve depth ordering, front/back split and parallax',()=>{
 const c=renderer(),labels=[],moves=[];c.shot={x:600,y:400};const ctx={globalAlpha:1,save(){},restore(){},translate(...p){moves.push(p)},beginPath(){},fillText(t){labels.push(t)}};
 const layer=(id,depth,parallax)=>({id,depth,parallax,commands:[{type:'text',x:0,y:0,text:id}]});const data={art:{layers:[layer('near',-1,1),layer('front',1,1),layer('far',-5,.2)]}};
 c.vectorLayers(ctx,data,false);assert.deepEqual(labels,['far','near']);assert.deepEqual(moves[0],[80,80]);c.vectorLayers(ctx,data,true);assert.deepEqual(labels,['far','near','front']);
});
