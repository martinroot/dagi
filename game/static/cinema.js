/* Vector film presentation. All body coordinates still come from the solver. */
"use strict";
function mergeLook(data,look){
 if(!look||!Object.keys(look).length)return data;
 const c=data.character,a=data.art;
 return {...data,character:c&&{...c,...look.character,surface:{...c.surface,...look.character?.surface},features:{...c.features,...look.character?.features}},art:a&&{...a,...look.art,key:{...a.key,...look.art?.key},atmosphere:{...a.atmosphere,...look.art?.atmosphere}},environment:{...data.environment,...look.environment}};
}
function paintHair(ctx,h,r,data,back){
 const f=data.character.features||{},length=f.hair_length??.65;
 if(!f.hair||f.hair==='none'||length<.01)return;
 const x=h[0],y=h[1],color=artTone(f.hair_color||'#243b48',data),detail=f.detail??.3;
 ctx.save();ctx.translate(x,y);ctx.scale(r,r);
 if(back){
  if(f.hair==='bob'){
   ctx.beginPath();ctx.moveTo(-.9,-.4);ctx.bezierCurveTo(-1.5,-1.5,1.3,-1.9,1.04,-.2);ctx.lineTo(1.12,.75*length);ctx.quadraticCurveTo(.7,1,.65,.15);ctx.lineTo(-.7,.1);ctx.lineTo(-1.13,.8*length);ctx.closePath();ctx.fillStyle=artGradient(ctx,-1,-1,1,1,color,data,.6);ctx.fill();
  }ctx.restore();return;
 }
 const top=-.89-length*.29;
 ctx.beginPath();ctx.moveTo(-.83,.04);ctx.bezierCurveTo(-1.13,-.57,-.88,top-.2,-.24,top);
 if(f.hair==='spiky'){
  for(let i=0;i<7;i++){const x=-.62+i*.21;ctx.lineTo(x,top-.22-(i%2)*length*.2);ctx.lineTo(x+.12,top+.1);}
 }else if(f.hair==='swept'){
  ctx.bezierCurveTo(.08,top-.1,.5,top-.19,.96,top-.04);ctx.quadraticCurveTo(.88,top+.14,.79,-.55);ctx.quadraticCurveTo(.44,-.93,-.18,-.64);
 }else if(f.hair==='crop')ctx.bezierCurveTo(.4,top-.09,.9,-1,.88,-.4);
 else ctx.bezierCurveTo(.8,top-.35,1.2,-.7,.83,.02);
 ctx.quadraticCurveTo(.35,-.72,.75,-.28);ctx.lineTo(.84,-.02);ctx.quadraticCurveTo(.58,-.61,-.2,-.64);ctx.quadraticCurveTo(-.5,-.54,-.64,-.15);ctx.lineTo(-.7,.23);ctx.closePath();ctx.fillStyle=artGradient(ctx,-.6,top,1,.1,color,data,.35);ctx.fill();
 ctx.save();ctx.clip();
 for(let i=0;i<Math.round(10+detail*26);i++){
  const u=i/35;ctx.beginPath();ctx.moveTo(-.86+u*.8,.13-u*.65);ctx.bezierCurveTo(-1+u*.7,-.7-u*.5,-.55+u*.8,top-.15,.8+u*.45,top+.04+u*.17);ctx.strokeStyle=artTone(artMix(color,i%4?'#b1c9cc':'#101d2b',i%4?.15:.5),data);ctx.lineWidth=i%4?.012:.019;ctx.stroke();
 }ctx.restore();
 ctx.strokeStyle=artTone(artMix(color,'#d9fff2',.5),data);ctx.lineWidth=.018;ctx.beginPath();ctx.moveTo(-.88,-.58);ctx.bezierCurveTo(-.78,top-.18,.4,top-.37,1.01,top-.04);ctx.stroke();
 ctx.restore();
}
function portraitEllipse(ctx,x,y,rx,ry,fill){ctx.beginPath();ctx.ellipse(x,y,Math.max(.0001,rx),Math.max(.0001,ry),0,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();}
function paintPortrait(ctx,h,r,data,emotion,now){
 const c=data.character,f=c.features||{},s=c.surface,x=h[0],y=h[1],v=emotion.valence||0,smile=Math.max(emotion.smile||0,v*.65),surprise=emotion.surprise||0,detail=f.detail??.3;
 const gaze=emotion.gaze||[x+20,y],gx=Math.max(-.055,Math.min(.055,(gaze[0]-x)/700)),gy=Math.max(-.04,Math.min(.04,(gaze[1]-y)/700));
 // Blink timing uses the physics timeline, so a pause freezes acting too.
 const auto=((now/1000+(data.self?.session_id||1)*.77)%4.7)<.12;
 ctx.save();ctx.translate(x,y);ctx.scale(r,r);
 const base=c.style==='ceramic'?s.bone:s.skin;
 for(const side of [-1,1]){
  const cheek=ctx.createRadialGradient(side*.59,.2,.01,side*.59,.2,.29);cheek.addColorStop(0,artTone(artMix(base,'#dc8f87',.5),data)+'88');cheek.addColorStop(1,base+'00');portraitEllipse(ctx,side*.59,.2,.28,.18,cheek);
  portraitEllipse(ctx,side*.84,.0,.11,.24,artGradient(ctx,side*.78,-.2,side*.95,.18,base,data,.5));
  ctx.beginPath();ctx.moveTo(side*.86,-.07);ctx.quadraticCurveTo(side*.95,-.1,side*.89,.12);ctx.strokeStyle=artTone(artMix(base,'#5c6366',.25),data);ctx.lineWidth=.018;ctx.stroke();
 }
 const squint=Math.max(emotion.squint||0,smile*.15),eyeScale=f.eye_size||1;
 for(const side of [-1,1]){
  const ex=side*.36,ey=-.12-surprise*.04,blink=Math.max(auto?1:0,emotion[side===-1?'blink_left':'blink_right']||0),open=Math.max(.025,(1-blink)*(1-squint*.6)),ew=.23*eyeScale,eh=(.14+surprise*.07)*open;
  const eye=()=>{ctx.beginPath();ctx.moveTo(ex-ew,ey);ctx.bezierCurveTo(ex-ew*.5,ey-eh*1.5,ex+ew*.6,ey-eh*1.2,ex+ew,ey);ctx.quadraticCurveTo(ex,ey+eh*1.1,ex-ew,ey);ctx.closePath();};
  eye();ctx.fillStyle=artGradient(ctx,ex,ey-eh,ex,ey+eh,'#f8f6ee',data,.5);ctx.fill();
  ctx.save();ctx.clip();
  const iris=f.iris||s.eye;portraitEllipse(ctx,ex+gx,ey+gy,.113*eyeScale,.128*eyeScale,artGradient(ctx,ex-.1,ey-.12,ex+.1,ey+.12,iris,data,.15));
  if(detail>.5)for(let i=0;i<48;i++){const a=i*Math.PI/24;sceneLine(ctx,[[ex+gx+Math.cos(a)*.075,ey+gy+Math.sin(a)*.075],[ex+gx+Math.cos(a)*.11,ey+gy+Math.sin(a)*.12]],artTone(artMix(iris,i%2?'#123140':'#f1e3bb',.5),data),.008);}
  portraitEllipse(ctx,ex+gx,ey+gy,.049,.079,'#102b37');portraitEllipse(ctx,ex+gx-.035,ey+gy-.048,.026,.03,'#fff8e5');portraitEllipse(ctx,ex+gx+.04,ey+gy+.04,.012,.015,'#c1fff1');ctx.restore();
  ctx.beginPath();ctx.moveTo(ex-ew,ey);ctx.bezierCurveTo(ex-ew*.5,ey-eh*1.5,ex+ew*.6,ey-eh*1.2,ex+ew,ey);ctx.strokeStyle=artTone(f.brow||'#31414b',data);ctx.lineWidth=.027;ctx.lineCap='round';ctx.stroke();
  ctx.beginPath();ctx.moveTo(ex-ew*.8,ey+.09);ctx.quadraticCurveTo(ex,ey+.16,ex+ew*.8,ey+.09);ctx.strokeStyle=artTone(artMix(base,'#526e78',.2),data);ctx.lineWidth=.012;ctx.stroke();
  const b=-.4-surprise*.12-(emotion.brow||0)*.08;
  ctx.beginPath();ctx.moveTo(ex-ew,b+side*.025);ctx.quadraticCurveTo(ex,b-.095,ex+ew,b-side*.025);ctx.strokeStyle=artTone(f.brow||'#31414b',data);ctx.lineWidth=.032;ctx.stroke();
  if(detail>.5)for(let i=0;i<9;i++){const bx=ex-ew+i*ew/5;sceneLine(ctx,[[bx,b+.01],[bx+.035,b-.035]],artTone(artMix(f.brow||'#31414b','#a3b0ad',.25),data),.008);}
 }
 // Sculpted nose bridge, tip and a soft lower plane.
 ctx.beginPath();ctx.moveTo(-.035,-.05);ctx.quadraticCurveTo(-.1,.13,-.105,.23);ctx.quadraticCurveTo(.015,.28,.105,.22);ctx.strokeStyle=artTone(artMix(base,'#52646e',.32),data);ctx.lineWidth=.018;ctx.stroke();
 ctx.beginPath();ctx.moveTo(.015,-.06);ctx.quadraticCurveTo(.11,.1,.075,.18);ctx.strokeStyle=artTone(artMix(base,'#ffffff',.6),data);ctx.lineWidth=.024;ctx.stroke();
 for(const side of [-1,1])portraitEllipse(ctx,side*.073,.24,.027,.014,artTone(artMix(base,'#283f4a',.42),data));
 const mx=.28+smile*.07,my=.47,op=(emotion.mouth||0)*.2+smile*.06,lip=artTone(f.lips||'#b67470',data);
 ctx.beginPath();ctx.moveTo(-mx,my-smile*.11);ctx.quadraticCurveTo(0,my+.04,mx,my-smile*.11);ctx.quadraticCurveTo(0,my+.04+op*2,-mx,my-smile*.11);ctx.closePath();ctx.fillStyle='#303741';ctx.fill();
 if(op>.025){ctx.save();ctx.clip();ctx.beginPath();ctx.roundRect(-mx*.9,my-.02,mx*1.8,.08+smile*.035,.02);ctx.fillStyle='#faf0df';ctx.fill();if(op>.1)portraitEllipse(ctx,0,my+op*.9,.15,.035,lip);ctx.restore();}
 ctx.beginPath();ctx.moveTo(-mx,my-smile*.11);ctx.quadraticCurveTo(0,my+.015,mx,my-smile*.11);ctx.strokeStyle=artTone(artMix(lip,'#393d43',.25),data);ctx.lineWidth=.021;ctx.stroke();
 ctx.beginPath();ctx.moveTo(-mx*.77,my+.06);ctx.quadraticCurveTo(0,my+.11+op,mx*.77,my+.06);ctx.strokeStyle=lip;ctx.lineWidth=.024;ctx.stroke();
 if(detail>.4){
  ctx.beginPath();ctx.moveTo(-.18,.76);ctx.quadraticCurveTo(.03,.82,.24,.73);ctx.strokeStyle=artTone(artMix(base,'#ffffff',.45),data);ctx.lineWidth=.018;ctx.stroke();
  for(let i=0;i<Math.round((f.freckles||0)*35);i++){const side=i%2?1:-1;portraitEllipse(ctx,side*(.39+(i*13%17)/100),.13+(i*7%13)/100,.009,.007,artTone(artMix(base,'#625052',.37),data));}
 }
 ctx.restore();
}
function speechLines(ctx,text,max){
 const words=text.split(/\s+/),lines=[];let line='';
 for(const word of words){if(ctx.measureText((line?line+' ':'')+word).width>max&&line){lines.push(line);line='';}if(ctx.measureText(word).width>max){for(const char of Array.from(word)){if(ctx.measureText(line+char).width>max){lines.push(line);line='';}line+=char;}}else line+=(line?' ':'')+word;}
 if(line)lines.push(line);return lines.slice(0,5);
}
function paintSpeech(ctx,data,body){
 const speech=directionData(data,body).speech;if(!speech||!body?.nodes?.head)return;
 const text=Array.from(speech.text).slice(0,Math.ceil(Array.from(speech.text).length*(speech.progress??1))).join('');
 const anchor=worldToScreen(body.nodes.head),r=(data.character?.head_radius||12)*shot.zoom*(data.character?.features?.hair!=='none'?1.45:1),bars=shot.letterbox*600;
 ctx.save();ctx.globalAlpha=speech.opacity??1;ctx.font='500 25px system-ui';
 const lines=speechLines(ctx,text,Math.min(430,860)),w=Math.max(160,Math.min(486,Math.max(...lines.map(l=>ctx.measureText(l).width),120)+56)),h=55+lines.length*30;
 const x=Math.max(24,Math.min(976-w,anchor[0]-w*.5)),y=Math.max(bars+18,Math.min(570-bars-h,anchor[1]-r-h-30));
 ctx.shadowColor='#0b1f3655';ctx.shadowBlur=16;ctx.shadowOffsetY=8;
 const g=ctx.createLinearGradient(x,y,x+w,y+h);g.addColorStop(0,'#f7fff7');g.addColorStop(1,'#e0f3ee');ctx.fillStyle=g;ctx.strokeStyle='#b5e5d9';ctx.lineWidth=1.2;ctx.beginPath();ctx.roundRect(x,y,w,h,19);ctx.fill();ctx.stroke();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
 const tail=Math.max(x+22,Math.min(x+w-22,anchor[0]));ctx.beginPath();ctx.moveTo(tail-10,y+h-1);ctx.quadraticCurveTo(tail+2,y+h+21,Math.max(x+5,Math.min(x+w-5,anchor[0])),Math.max(y+h+8,Math.min(y+h+23,anchor[1]-r-5)));ctx.lineTo(tail+10,y+h-1);ctx.fill();
 ctx.font='600 10px ui-monospace,monospace';ctx.fillStyle='#3d7b75';ctx.textAlign='left';ctx.fillText(speech.speaker||'DAGI',x+27,y+24);ctx.fillStyle='#163c48';ctx.font='500 25px system-ui';lines.forEach((l,i)=>ctx.fillText(l,x+27,y+54+i*30));
 ctx.fillStyle=speech.color||'#aef3df';ctx.beginPath();ctx.arc(x+w-23,y+20,3,0,Math.PI*2);ctx.fill();ctx.restore();
}
function paintRevealBand(ctx,data,body,reveal){
 if(!body?.nodes||!reveal||reveal.progress<=0||reveal.progress>=1)return;
 const values=Object.values(body.nodes),top=Math.min(...values.map(p=>p[1]))-35,bottom=Math.max(...values.map(p=>p[1]))+20,y=bottom-(bottom-top)*reveal.progress,band=reveal.band||24;
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 ctx.save();const g=ctx.createLinearGradient(0,y-band,0,y+band);g.addColorStop(0,(reveal.color||'#aaf5e4')+'00');g.addColorStop(.5,(reveal.color||'#aaf5e4')+(reduced?'25':'77'));g.addColorStop(1,(reveal.color||'#aaf5e4')+'00');ctx.fillStyle=g;ctx.fillRect(0,y-band,1000,band*2);
 ctx.lineWidth=.8;ctx.strokeStyle=reveal.color||'#aaf5e4';ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(1000,y);ctx.stroke();
 if(!reduced)for(let i=0;i<24;i++){const x=body.nodes.hip[0]-62+(i*73%127),v=((body.tick*.021+i*.71)%1);ctx.globalAlpha=(1-v)*.6;artEllipse(ctx,x+Math.sin(i*9)*v*12,y-band*v, .5+v*.7,.5+v*.7,reveal.color||'#aaf5e4');}
 ctx.restore();
}
const filmCreate=document.getElementById('new-film');if(filmCreate)filmCreate.onclick=async()=>{try{filmCreate.disabled=true;const data=await api('game/sessions','POST',{title:'Matter · Dagi / Physical Film',film:true});await selectSession(data.session_id,'Matter · Dagi');await lifeAction('play');}catch(exc){error(exc);}finally{filmCreate.disabled=false;}};
for(const [id,event] of [['film-replay','replay'],['film-transform','transform'],['film-stunt','stunt']]){const button=document.getElementById(id);if(button)button.onclick=async()=>{try{if(event==='replay'&&sceneData?.scene.active_project==='Matter / Dagi'){await filmCreate.onclick();return;}await api(`game/sessions/${sessionId}/project-event`,'POST',{version:sceneData.scene.version,id:event});if(!sceneData.life.running)await lifeAction('play');}catch(exc){error(exc);}};}

let physicsEvidence=false;
const evidenceControl=document.getElementById('physics-evidence');if(evidenceControl)evidenceControl.onclick=()=>{physicsEvidence=!physicsEvidence;evidenceControl.setAttribute('aria-pressed',String(physicsEvidence));};
function paintDynamicsEvidence(ctx,data,body){
 const d=body?.dynamics;if(!physicsEvidence||!d?.com)return;
 ctx.save();ctx.lineWidth=1.1/shot.zoom;
 if(d.support){sceneLine(ctx,[[d.support[0],538],[d.support[1],538]],'#279b87',3/shot.zoom);}
 ctx.setLineDash([3/shot.zoom,4/shot.zoom]);sceneLine(ctx,[d.com,[d.com[0],540]],'#278e8990',1/shot.zoom);ctx.setLineDash([]);
 artEllipse(ctx,...d.com,4/shot.zoom,4/shot.zoom,'#f6ffef','#207d76',1/shot.zoom);
 const v=d.velocity||[0,0];sceneLine(ctx,[d.com,[d.com[0]+v[0]*.08,d.com[1]+v[1]*.08]],'#bf714d',1.5/shot.zoom);ctx.restore();
}
function paintPlaybackRate(ctx,data,body){
 const rate=directionData(data,body).playback?.speed??1;if(rate>=.99)return;
 ctx.save();ctx.font='500 12px ui-monospace,monospace';ctx.fillStyle='#234b50';ctx.textAlign='right';ctx.fillText(`SLOW MOTION  ${rate.toFixed(2)}×`,963,550);ctx.restore();
}
