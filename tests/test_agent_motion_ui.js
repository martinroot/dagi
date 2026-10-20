import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
const code=fs.readFileSync(new URL('../game/static/motion.js',import.meta.url),'utf8');
function viewer(){const c={module:{exports:{}}};new Function('module','exports','globalThis',code)(c.module,c.module.exports,globalThis);return c.module.exports;}
test('a chained route plays as one continuous scene with authored transitions',()=>{
 const M=viewer(),steps=[0,3,5];
 const full=M.route(steps,0);
 assert.deepEqual(full.segs.map(s=>s.kind),['skill','travel','skill','travel','skill']);
 assert.deepEqual(full.segs.map(s=>s.kind==='skill'?s.station:null),[0,null,30,null,50]);
 const seg0End=M.route(steps,full.segs[0].duration-1e-4).pose.pelvis.p;
 const travel=M.route(steps,full.segs[0].duration+1e-4);
 assert.equal(travel.segment.kind,'travel');
 assert.ok(travel.segment.from[0]>seg0End[0]-.6,'travel starts where the first skill ended');
 let prev=null,maxStep=0,minX=1e9,maxX=-1e9;
 for(let e=0;e<=full.total;e+=.02){
  const f=M.route(steps,e),x=f.pose.pelvis.p[0];
  assert.ok(Number.isFinite(x)&&Number.isFinite(f.pose.pelvis.p[1]));
  if(prev!==null)maxStep=Math.max(maxStep,x-prev);
  prev=x;minX=Math.min(minX,x);maxX=Math.max(maxX,x);
 }
 assert.ok(maxStep<.5,`no teleport: max 20ms hip step ${maxStep}`);
 assert.ok(maxX-minX>40,'route spans the whole stage');
 const last=M.route(steps,full.total-1e-4);
 assert.ok(Math.abs(last.pose.pelvis.p[0]-(50+last.pose.pelvis.p[0]-50))<1e-9);
 assert.ok(last.props.some(p=>p.kind==='car'&&Math.abs(p.x-50)<1e-6),'car stages at its station, not at the origin');
});
