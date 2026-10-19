/* Physical scene presentation and local muscle/skill controls. */
"use strict";
let workshopStamp=0,workshopSkillsKey=null,muscleTimer=null,muscleOwner=null,muscleEffort=0;
const skillPaths={
 muscle:['M3 15l3-7 4 1 1-5 4 1 2 6 4 2v5l-6 3H8l-5-4z','M8 17c2-5 7-6 10-2'],
 rope:['M7 16C0 16 2 5 9 6c8 1 7 13 1 12-4 0-5-9 0-10 7-2 5 14 12 12'],
 wheel:['M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0z','M12 4v16M4 12h16M6.4 6.4l11.2 11.2M6.4 17.6 17.6 6.4'],
 hand:['M7 13V6a1.5 1.5 0 0 1 3 0v5-7a1.5 1.5 0 0 1 3 0v7-6a1.5 1.5 0 0 1 3 0v7-4a1.5 1.5 0 0 1 3 0v7c0 5-3 7-7 7-3 0-4-1-6-4l-3-4a1.6 1.6 0 0 1 2.5-2l2 3'],
 spark:['m12 3 2.5 6 6.5 3-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-3z']
};
function drawSkillIcon(node,value){
 const aliases={'🦾':'muscle','🪢':'rope','🛞':'wheel','🫳':'hand','✦':'spark'},name=aliases[value]||value,paths=skillPaths[name];
 if(!paths){node.textContent=value||'✦';return;}
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 for(const [key,val] of Object.entries({viewBox:'0 0 24 24',width:'29',height:'29',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(key,val);
 for(const d of paths){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);svg.append(path);}node.append(svg);
}
function paintEnvironment(ctx,env){
  if(!env)return false;
  const sky=ctx.createLinearGradient(0,0,0,540);sky.addColorStop(0,env.sky_top);sky.addColorStop(1,env.sky_bottom);ctx.fillStyle=sky;ctx.fillRect(0,0,1000,600);
  const sun=env.sun;if(sun?.radius){const glow=ctx.createRadialGradient(sun.x,sun.y,sun.radius*.3,sun.x,sun.y,sun.radius*3);glow.addColorStop(0,sun.color+'aa');glow.addColorStop(1,sun.color+'00');ctx.fillStyle=glow;ctx.fillRect(sun.x-sun.radius*3,sun.y-sun.radius*3,sun.radius*6,sun.radius*6);ctx.fillStyle=sun.color;ctx.beginPath();ctx.arc(sun.x,sun.y,sun.radius,0,Math.PI*2);ctx.fill();}
  for(const m of env.mountains||[]){ctx.fillStyle=m.color;ctx.beginPath();ctx.moveTo(...m.points[0]);for(const p of m.points.slice(1))ctx.lineTo(...p);ctx.closePath();ctx.fill();}
  for(const c of env.clouds||[]){ctx.save();ctx.translate(c.x,c.y);ctx.scale(c.scale||1,c.scale||1);ctx.fillStyle='#ffffffb0';ctx.beginPath();ctx.ellipse(-22,7,37,14,0,0,Math.PI*2);ctx.ellipse(8,-1,29,23,0,0,Math.PI*2);ctx.ellipse(35,9,38,13,0,0,Math.PI*2);ctx.fill();ctx.restore();}
  const ground=ctx.createLinearGradient(0,540,0,600);ground.addColorStop(0,env.ground_top);ground.addColorStop(1,env.ground_bottom);ctx.fillStyle=ground;ctx.fillRect(0,540,1000,60);
  ctx.strokeStyle=env.ground_top;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(0,540);ctx.lineTo(1000,540);ctx.stroke();
  ctx.strokeStyle='#ffffff16';ctx.lineWidth=.8;
  for(let x=0;x<1000;x+=13){const y=543+(x*17%51);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+3,y-3);ctx.stroke();}
  return true;
}
function paintConnections(ctx,data,body){
  for(const r of body?.ropes||[]){ctx.save();ctx.strokeStyle=r.broken?'#bb7868':r.color;ctx.lineWidth=r.radius*2;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();for(const segment of r.segments){ctx.moveTo(...segment[0]);ctx.lineTo(...segment[1]);}ctx.stroke();ctx.restore();}
  for(const [id,j] of Object.entries(body?.mechanisms||{})){
    if(id.endsWith(':rotation'))continue;ctx.save();ctx.strokeStyle=j.broken?'#c27765':'#7c91a0';ctx.lineWidth=1.8;
    if(['pin','slide','spring','weld'].includes(j.type)){ctx.setLineDash(j.type==='spring'?[3,3]:[]);ctx.beginPath();ctx.moveTo(...j.a);ctx.lineTo(...j.b);ctx.stroke();}
    for(const p of [j.a,j.b]){ctx.fillStyle='#f6f4df';ctx.beginPath();ctx.arc(...p,3.6,0,Math.PI*2);ctx.fill();ctx.stroke();}
    if(j.type==='motor'){ctx.strokeStyle='#57aeb0';ctx.beginPath();ctx.arc(...j.a,8,-.6,3.6);ctx.stroke();}
    ctx.restore();
  }
}
function workshopRefresh(data,body,now){
  if(!data||now-workshopStamp<160)return;workshopStamp=now;
  const physical=data.body_control?.mode==='physical'||data.scene?.body_control?.mode==='physical';
  const mode=document.getElementById('physics-mode');if(mode){mode.textContent=physical?'МЫШЦЫ · БЕЗ АВТОБАЛАНСА':'ASSISTED · УДЕРЖАНИЕ ПОЗЫ';mode.dataset.mode=physical?'physical':'assisted';}
  const energy=body?.energy||data.scene?.energy||{};const work=document.getElementById('physical-work');if(work)work.textContent=`Мышцы ${(energy.muscle_work||0).toFixed(2)} Дж · моторы ${(energy.motor_work||0).toFixed(2)} Дж`;
  const ropes=body?.ropes||[],tension=document.getElementById('rope-load');if(tension)tension.textContent=ropes.map(r=>`${r.id}: ${(r.tension/100).toFixed(1)} Н${r.broken?' · ОБРЫВ':''}`).join(' · ');
  const control=document.getElementById('muscle-console');if(control)control.hidden=!physical;
  const select=document.getElementById('muscle-joint'),joints=Object.keys(body?.articulation||{});
  if(select&&joints.length&&select.dataset.names!==joints.join(',')){const previous=select.value;select.replaceChildren();for(const name of joints){const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option);}select.value=joints.includes(previous)?previous:joints.includes('right_hand')?'right_hand':joints[0];select.dataset.names=joints.join(',');}
  const angle=document.getElementById('muscle-angle'),joint=body?.articulation?.[select?.value];if(angle)angle.textContent=joint?`${(joint.angle*180/Math.PI).toFixed(0)}° · усилие ${muscleEffort.toFixed(1)}`:'Пока нет физического измерения';
  const key=JSON.stringify([sessionId,data.widgets,data.scene.version,!!data.build]);
  if(key!==workshopSkillsKey){workshopSkillsKey=key;const hotbar=document.getElementById('skill-hotbar');if(hotbar){hotbar.replaceChildren();const skills=(data.widgets||[]).filter(w=>w.kind==='skill');for(const skill of skills){const button=document.createElement('button');button.className='game-skill';button.type='button';button.disabled=!!data.build;button.title=skill.body||skill.title;button.dataset.hotkey=skill.hotkey||'';const icon=document.createElement('span');icon.className='skill-icon';drawSkillIcon(icon,skill.icon||'✦');const title=document.createElement('strong');title.textContent=skill.title;const key=document.createElement('kbd');key.textContent=skill.hotkey||'↗';button.append(icon,title,key);button.onclick=()=>localSkill(skill,data.scene.version).catch(error);hotbar.append(button);}if(!skills.length){const note=document.createElement('span');note.className='small';note.textContent='Здесь появятся навыки с иконками, созданные агентом.';hotbar.append(note);}}}
}
async function localSkill(skill,version){
  if(!sessionId||sceneData?.build)return;
  if(skill.target.type==='project')await api(`game/sessions/${sessionId}/interact`,'POST',{version,widget_id:skill.id});
  else await humanControl(skill.id,null,version);
}
function stopMuscle(){clearInterval(muscleTimer);muscleTimer=null;muscleEffort=0;const owner=muscleOwner;muscleOwner=null;if(owner)api(`game/sessions/${owner.session}/input`,'POST',{type:'muscle',joint:owner.joint,effort:0}).catch(error);}
function manualMuscle(effort){
  stopMuscle();const joint=document.getElementById('muscle-joint')?.value;if(!sessionId||!joint)return;
  muscleOwner={session:sessionId,joint};muscleEffort=effort;
  const send=()=>{if(!muscleOwner||muscleOwner.session!==sessionId){stopMuscle();return;}api(`game/sessions/${muscleOwner.session}/input`,'POST',{type:'muscle',joint,effort}).catch(error);};send();muscleTimer=setInterval(send,110);
}
for(const [id,value] of [['muscle-negative',-.7],['muscle-positive',.7]]){const button=document.getElementById(id);if(button){button.onpointerdown=event=>{event.preventDefault();button.setPointerCapture(event.pointerId);manualMuscle(value);};button.onpointerup=stopMuscle;button.onpointercancel=stopMuscle;}}
window.addEventListener('blur',stopMuscle);
window.addEventListener('keydown',event=>{if(['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName)||event.repeat)return;const button=[...document.querySelectorAll('.game-skill')].find(b=>b.dataset.hotkey===event.key);if(button&&!button.disabled){event.preventDefault();button.click();}});
