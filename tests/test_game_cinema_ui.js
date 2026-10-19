import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const code=fs.readFileSync(new URL('../game/static/cinema.js',import.meta.url),'utf8');
function viewer(){const c={document:{getElementById:()=>null}};vm.runInNewContext(code,c);return c;}
test('transient film looks merge nested cosmetics without changing physical proportions or authored world',()=>{
 const c=viewer(),data={character:{head_radius:17,bones:{hip:{mass:4}},surface:{skin:'#123456',roughness:.5},features:{hair:'none',detail:.2}},art:{key:{x:20,color:'#abcdef'},atmosphere:{wind:.2}},environment:{sky_top:'#123456',clouds:[{x:2}]}},before=JSON.stringify(data);
 const out=c.mergeLook(data,{character:{features:{hair:'bob'},surface:{roughness:.2}},art:{key:{color:'#ffffff'}},environment:{sky_top:'#eeeeee'}});
 assert.equal(JSON.stringify(data),before);assert.equal(out.character.head_radius,17);assert.equal(out.character.bones.hip.mass,4);assert.equal(out.character.features.detail,.2);assert.equal(out.character.features.hair,'bob');assert.equal(out.art.key.x,20);assert.equal(out.art.key.color,'#ffffff');assert.equal(out.environment.clouds[0].x,2);
});
test('speech wraps long words by Unicode code point and constrains line count',()=>{
 const c=viewer(),ctx={measureText:s=>({width:Array.from(s).length*10})};
 const lines=c.speechLines(ctx,'Hello 👋 Dagi abcdefghijk',60);
 assert.ok(lines.length<=5);assert.ok(lines.every(s=>Array.from(s).length<=6));assert.ok(lines.join(' ').includes('👋'));
});
test('authored timelines interpolate colors, arrays and numbers and hold enumerated styles',()=>{
 const c={module:{exports:{}}};vm.runInNewContext(fs.readFileSync(new URL('../game/examples/story-kit.js',import.meta.url),'utf8'),c);
 const kit=c.module.exports,keys=[{at:0,value:{p:[0,10],color:'#000000',style:'a'}},{at:2,value:{p:[10,20],color:'#ffffff',style:'b'}}];
 const middle=kit.sample(keys,1);assert.equal(middle.p[0],5);assert.equal(middle.color,'#808080');assert.equal(middle.style,'a');assert.equal(kit.sample(keys,2).style,'b');assert.equal(kit.sample(keys,10).p[0],10);
 assert.equal(kit.sequence([{duration:1,id:'a'},{duration:2,id:'b'}],2).id,'b');
});
