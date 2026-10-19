/* Procedural anatomy and art direction. No sprites, bitmaps or canned motion. */
"use strict";
let artGrainPath=null,artFinishCache=null,artFinishKey=null;
function artMix(a,b,t){const out=[];for(let i=1;i<7;i+=2)out.push(Math.round(parseInt(a.slice(i,i+2),16)*(1-t)+parseInt(b.slice(i,i+2),16)*t));return '#'+out.map(v=>Math.max(0,Math.min(255,v)).toString(16).padStart(2,'0')).join('');}
function artTone(color,data){if(data.art?.mode!=='noir')return color;const n=Math.round(parseInt(color.slice(1,3),16)*.213+parseInt(color.slice(3,5),16)*.715+parseInt(color.slice(5,7),16)*.072).toString(16).padStart(2,'0');return '#'+n+n+n;}
function artGradient(ctx,x0,y0,x1,y1,color,data,rough=.55,depth=1,metallic=0){
 const art=data.art||{},ambient=art.ambient??.52,key=art.key||{color:'#fff1d0',intensity:.9},base=artTone(color,data);
 const dark=artTone(artMix(base,'#152832',(.28+(1-ambient)*.36)*depth),data),light=artMix(base,artTone(key.color,data),Math.min(.85,(.2+key.intensity*.35)*(1-rough*.45)));
 const g=ctx.createLinearGradient(x0,y0,x1,y1),toon=art.mode==='toon';
 g.addColorStop(0,light);g.addColorStop(toon?.4:.24,light);if(!toon&&metallic>.2){g.addColorStop(.4,base);g.addColorStop(.46,artMix(base,"#ffffff",metallic*.75));g.addColorStop(.5,base);}g.addColorStop(toon?.401:.55,base);g.addColorStop(toon?.76:.8,base);g.addColorStop(toon?.761:1,dark);if(toon)g.addColorStop(1,dark);return g;
}
function artEllipse(ctx,x,y,rx,ry,fill,stroke,width=.7){ctx.beginPath();ctx.ellipse(x,y,Math.max(.1,rx),Math.max(.1,ry),0,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();}}
function artLimb(ctx,a,b,r,color,data,options={}){
 const length=Math.hypot(b[0]-a[0],b[1]-a[1]);if(length<.01)return;
 const angle=Math.atan2(b[1]-a[1],b[0]-a[0]),surface=data.character.surface,shadow=options.back?.25:0;
 ctx.save();ctx.translate(...a);ctx.rotate(angle);
 const light=data.art?.key||{x:180,y:80};const side=(light.x-a[0])*-Math.sin(angle)+(light.y-a[1])*Math.cos(angle);const flip=side>0?-1:1;
 const bone=options.bone,tip=bone?r*.66:r*.58,root=bone?r*.7:r*.62,bulge=bone?r*.45:r;
 ctx.beginPath();ctx.moveTo(0,-root);ctx.bezierCurveTo(length*.22,-bulge*1.1,length*.54,-bulge,length,-tip);ctx.quadraticCurveTo(length+tip,0,length,tip);ctx.bezierCurveTo(length*.55,bulge,length*.22,bulge*1.1,0,root);ctx.quadraticCurveTo(-root,0,0,-root);ctx.closePath();
 ctx.fillStyle=artGradient(ctx,0,-r*flip,0,r*flip,artMix(color,'#1a2e3c',shadow),data,surface.roughness,1,surface.metallic);ctx.fill();
 ctx.strokeStyle=artMix(color,'#182c34',.5);ctx.lineWidth=surface.outline*.55;ctx.stroke();
 ctx.strokeStyle=artMix(color,'#ffffff',.58);ctx.globalAlpha=(data.art?.rim??.5)*.7;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(length*.12,-r*.7*flip);ctx.bezierCurveTo(length*.3,-r*.95*flip,length*.6,-r*.8*flip,length*.85,-r*.5*flip);ctx.stroke();ctx.globalAlpha=1;
 if(!bone&&surface.muscles>.25){ctx.globalAlpha=surface.muscles*.25;ctx.strokeStyle=artMix(color,'#422d37',.6);ctx.lineWidth=.5;for(let i=0;i<3;i++){ctx.beginPath();ctx.moveTo(length*.16,r*(-.35+i*.28));ctx.quadraticCurveTo(length*.45,r*(-.8+i*.4),length*.88,r*(-.25+i*.18));ctx.stroke();}ctx.globalAlpha=1;}
 ctx.restore();
}
function anatomicalTorso(ctx,data,n){
 const c=data.character,s=c.surface,a=n.neck,b=n.hip,l=Math.hypot(b[0]-a[0],b[1]-a[1]),w=Math.max(c.shoulder_width,c.bones.hip.radius*2),h=c.hip_width;
 ctx.save();ctx.translate(...a);ctx.rotate(Math.atan2(b[1]-a[1],b[0]-a[0]));
 const skeleton=c.style==='skeleton',base=c.style==='ceramic'?s.bone:s.skin;
 if(!skeleton){
  ctx.beginPath();ctx.moveTo(0,-4);ctx.bezierCurveTo(5,-w*.58,l*.36,-w*.5,l*.66,-h*.4);ctx.bezierCurveTo(l*.83,-h*.6,l,-h*.63,l+2,0);ctx.bezierCurveTo(l,h*.63,l*.83,h*.6,l*.66,h*.4);ctx.bezierCurveTo(l*.36,w*.5,5,w*.58,0,4);ctx.closePath();
  ctx.fillStyle=artGradient(ctx,0,-w*.6,0,w*.6,base,data,s.roughness,1,s.metallic);ctx.fill();ctx.strokeStyle=artMix(base,'#142e36',.5);ctx.lineWidth=s.outline;ctx.stroke();
  if(c.style==='anatomical'){
   for(const side of [-1,1]){
    artEllipse(ctx,l*.25,side*w*.19,l*.17,w*.23,artGradient(ctx,0,-w*.25,0,w*.4,artMix(s.skin,s.muscle,s.muscles*.5),data,s.roughness,1,s.metallic));
    for(let i=0;i<3;i++)artEllipse(ctx,l*(.48+i*.105),side*w*.08,l*.049,w*.078,artGradient(ctx,0,-w*.25,0,w*.4,artMix(s.skin,s.muscle,s.muscles*.35),data,s.roughness,1,s.metallic));
   }
   sceneLine(ctx,[[l*.12,0],[l*.77,0]],artMix(s.skin,s.muscle,.5),.5);
  }
  if(c.style==='ceramic'){
   ctx.strokeStyle=s.accent;ctx.lineWidth=.9;ctx.beginPath();ctx.moveTo(l*.12,-w*.34);ctx.quadraticCurveTo(l*.48,-w*.2,l*.8,-h*.31);ctx.stroke();
   artEllipse(ctx,l*.2,0,3.1,3.1,artGradient(ctx,0,-4,0,4,s.accent,data,.1));
  }
 }
 ctx.globalAlpha=skeleton?1:s.bone_visibility;
 if(ctx.globalAlpha>.001){
  // Vertebrae and paired curved ribs stay attached to the measured torso.
  for(let i=0;i<10;i++)artEllipse(ctx,l*(.08+i*.078),0,l*.038,2.7,artGradient(ctx,0,-3,0,3,s.bone,data,.65),artMix(s.bone,'#394b4d',.5),.45);
  for(let i=0;i<7;i++){
   const x=l*(.13+i*.063),rw=w*(.47-Math.abs(i-2)*.035),reach=l*.1;
   for(const side of [-1,1]){ctx.beginPath();ctx.moveTo(x,side*1.4);ctx.bezierCurveTo(x-reach*.35,side*rw,x+reach,side*rw,x+reach,side*2);ctx.strokeStyle=artMix(s.bone,'#435451',.3);ctx.lineWidth=2.4;ctx.stroke();ctx.strokeStyle=s.bone;ctx.lineWidth=1.4;ctx.stroke();}
  }
  for(const side of [-1,1]){
   ctx.beginPath();ctx.moveTo(l*.05,0);ctx.quadraticCurveTo(l*.09,side*w*.25,5,side*c.shoulder_width*.5);ctx.strokeStyle=s.bone;ctx.lineWidth=2.4;ctx.stroke();
   ctx.beginPath();ctx.moveTo(l*.75,0);ctx.bezierCurveTo(l*.7,side*h*.65,l*.99,side*h*.55,l,side*h*.25);ctx.quadraticCurveTo(l*.97,side*1,l*.85,side*2);ctx.strokeStyle=artMix(s.bone,'#4b5a55',.3);ctx.lineWidth=3.2;ctx.stroke();ctx.strokeStyle=s.bone;ctx.lineWidth=2;ctx.stroke();
  }
 }
 ctx.globalAlpha=1;
 if(s.markings>.01&&!skeleton){ctx.globalAlpha=s.markings;ctx.strokeStyle=s.accent;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(l*.82,-h*.42);ctx.quadraticCurveTo(l*.9,0,l*.82,h*.42);ctx.stroke();ctx.globalAlpha=1;}
 ctx.restore();
}
function anatomicalHead(ctx,data,body,now){
 const n=body.nodes,c=data.character,s=c.surface,h=n.head,r=c.head_radius,emotion=body.emotion||data.scene.emotion||{},tilt=(body.articulation?.head?.world_angle||0)+(emotion.tilt||0),skeleton=c.style==='skeleton';
 ctx.save();ctx.translate(...h);ctx.rotate(tilt);ctx.scale(s.head_width,1);ctx.translate(-h[0],-h[1]);
 if(typeof paintHair==="function")paintHair(ctx,h,r,data,true);
 const base=skeleton||c.style==='ceramic'?s.bone:s.skin;
 ctx.beginPath();ctx.moveTo(h[0]-r*.77,h[1]+r*.3);ctx.bezierCurveTo(h[0]-r*1.05,h[1]-r*.35,h[0]-r*.65,h[1]-r,h[0],h[1]-r);ctx.bezierCurveTo(h[0]+r*.9,h[1]-r,h[0]+r*1.04,h[1]-.2*r,h[0]+r*.77,h[1]+r*.3);ctx.bezierCurveTo(h[0]+r*.62,h[1]+r*.67,h[0]+r*.35,h[1]+r*.99,h[0],h[1]+r*.98);ctx.bezierCurveTo(h[0]-r*.35,h[1]+r*.99,h[0]-r*.62,h[1]+r*.67,h[0]-r*.77,h[1]+r*.3);ctx.closePath();
 ctx.fillStyle=artGradient(ctx,h[0]-r,h[1]-r,h[0]+r,h[1]+r,base,data,s.roughness,1,s.metallic);ctx.fill();ctx.strokeStyle=artMix(base,'#20343b',.5);ctx.lineWidth=s.outline*.75;ctx.stroke();
 if(!skeleton&&c.features?.detail>.45){
  ctx.save();ctx.clip();
  const g=ctx.createRadialGradient(h[0]-r*.35,h[1]-r*.48,r*.04,h[0]-r*.25,h[1]-r*.35,r*.95);g.addColorStop(0,artTone(artMix(base,'#fff3df',.45),data)+'bb');g.addColorStop(1,base+'00');ctx.fillStyle=g;ctx.fillRect(h[0]-r,h[1]-r,r*2,r*2);
  ctx.beginPath();ctx.moveTo(h[0]+r*.7,h[1]-r*.5);ctx.bezierCurveTo(h[0]+r*.9,h[1]+r*.2,h[0]+r*.55,h[1]+r*.8,h[0],h[1]+r*.98);ctx.bezierCurveTo(h[0]+r*.5,h[1]+r*1.02,h[0]+r*1.2,h[1]+r*.4,h[0]+r*.7,h[1]-r*.5);ctx.fillStyle=artTone(artMix(base,'#614c4f',.35),data)+'55';ctx.fill();ctx.restore();
 }
 if(skeleton){
  for(const side of [-1,1])artEllipse(ctx,h[0]+side*r*.36,h[1]-r*.04,r*.27,r*.3,'#30403e');
  ctx.beginPath();ctx.moveTo(h[0],h[1]+r*.15);ctx.lineTo(h[0]-r*.13,h[1]+r*.4);ctx.lineTo(h[0]+r*.13,h[1]+r*.4);ctx.closePath();ctx.fillStyle='#5b655b';ctx.fill();
  sceneLine(ctx,[[h[0]-r*.42,h[1]+r*.61],[h[0]+r*.42,h[1]+r*.61]],'#7c7c6a',.65);
  for(let i=-2;i<=2;i++)sceneLine(ctx,[[h[0]+i*r*.16,h[1]+r*.52],[h[0]+i*r*.16,h[1]+r*.74]],'#7c7c6a',.45);
 }
 if(s.crest>.02){ctx.fillStyle=s.accent;ctx.beginPath();ctx.moveTo(h[0]-r*.7,h[1]-r*.5);ctx.bezierCurveTo(h[0]-r*.8,h[1]-r*(1+s.crest),h[0]+r*.1,h[1]-r*(1+s.crest*.8),h[0]+r*.6,h[1]-r*.7);ctx.lineTo(h[0]+r*.15,h[1]-r*.9);ctx.closePath();ctx.fill();}
 if(s.markings>.05&&!skeleton){ctx.globalAlpha=s.markings;sceneLine(ctx,[[h[0]+r*.64,h[1]-r*.4],[h[0]+r*.54,h[1]+r*.22]],s.accent,1.2);ctx.globalAlpha=1;}
 if(!skeleton&&c.features?.detail>.45&&typeof paintPortrait==="function")paintPortrait(ctx,h,r,data,{...emotion,tilt:0},now);
 else paintFace(ctx,h,{...data.appearance,head_radius:r,no_cranium:true,eye:skeleton?'#e8d8a7':s.eye}, {...emotion,tilt:0},now,data);
 if(typeof paintHair==="function")paintHair(ctx,h,r,data,false);
 ctx.restore();
}
function paintAnatomy(ctx,now,data,body){
 if(data.character?.style==='sticks'){
  const n=body.nodes;ctx.save();ctx.lineCap='round';ctx.lineJoin='round';
  for(const [a,b] of data.links){if(a==='head')continue;sceneLine(ctx,[n[a],n[b]],'#2e3740',2.1);}
  for(const [k,p] of Object.entries(n)){if(k==='head')continue;artEllipse(ctx,...p,1.7,1.7,'#fbfcfc','#2e3740',.65);}
  artEllipse(ctx,...n.head,data.character.head_radius,data.character.head_radius,'#ffffff','#2e3740',1.7);ctx.restore();return true;
 }

 if(data.art?.mode==="noir"&&data.character){const c=data.character,surface={...c.surface};for(const key of ["skin","muscle","bone","accent","eye"])surface[key]=artTone(surface[key],data);data={...data,character:{...c,surface}};}
 const c=data.character;if(!c)return false;const s=c.surface,n=body.nodes,skeleton=c.style==='skeleton',ink=c.style==='ink';
 const links=data.links.filter(([a,b])=>a!=='head'&&b!=='hip');
 function limb(a,b,back){
  if(!n[a]||!n[b]||!c.bones[b])return;const spec=c.bones[b],r=spec.radius,color=skeleton?s.bone:c.style==='ceramic'?s.bone:ink?s.accent:s.skin;
  if(skeleton){
   const paired=b.endsWith('hand')||b.endsWith('foot'),vx=n[b][0]-n[a][0],vy=n[b][1]-n[a][1],len=Math.hypot(vx,vy)||1;
   for(const side of paired?[-1,1]:[0]){const offset=paired?r*.3*side:0;artLimb(ctx,[n[a][0]-vy/len*offset,n[a][1]+vx/len*offset],[n[b][0]-vy/len*offset,n[b][1]+vx/len*offset],r*(paired?.28:.44),color,data,{bone:true,back});}
  }else artLimb(ctx,n[a],n[b],r*(.72+s.muscles*.18+Math.min(1,body.muscles?.[b]?.activation||0)*.1),color,data,{back});
  const jr=r*(skeleton?.48:.6);artEllipse(ctx,...n[b],jr,jr,artGradient(ctx,n[b][0]-jr,n[b][1]-jr,n[b][0]+jr,n[b][1]+jr,color,data,s.roughness,1,s.metallic),artMix(color,'#243b41',.5),s.outline*.4);
  if(b.endsWith('hand')){
   const angle=Math.atan2(n[b][1]-n[a][1],n[b][0]-n[a][0]);ctx.save();ctx.translate(...n[b]);ctx.rotate(angle);if((body.emotion?.clench||0)>.4){artEllipse(ctx,r*.12,0,r*.85,r*.72,artGradient(ctx,0,-r,0,r,color,data,s.roughness),artMix(color,'#233f48',.4),.45);for(let i=0;i<3;i++)sceneLine(ctx,[[r*.1,(i-1)*r*.32],[r*.55,(i-1)*r*.32]],artMix(color,'#233f48',.3),.45);}else for(let i=0;i<4;i++){const y=(i-1.5)*r*.32;ctx.beginPath();ctx.moveTo(-r*.3,y);ctx.quadraticCurveTo(r*.6,y,r*.7+Math.sin(i+1)*r*.15,y+r*.15);ctx.strokeStyle=artMix(color,'#2a3b40',.15);ctx.lineWidth=skeleton?.75:1.1;ctx.stroke();}ctx.restore();
  }
 }
 for(const [a,b] of links)if(b.startsWith('left'))limb(a,b,true);
 anatomicalTorso(ctx,data,n);
 for(const [a,b] of links)if(!b.startsWith('left'))limb(a,b,false);
 artLimb(ctx,n.neck,n.head,2.7,skeleton?s.bone:s.skin,data,{bone:skeleton});
 for(const p of data.appendages||[]){const f=body.appendages?.find(x=>x[0]===p.id);if(f)artLimb(ctx,f[1],f[2],p.radius,p.color,data,{bone:skeleton});}
 anatomicalHead(ctx,data,body,now);
 return true;
}
function groundProjection(p,light){const h=Math.max(0,540-p[1]),dy=Math.max(80,p[1]-light.y);return[p[0]+Math.max(-2,Math.min(2,(p[0]-light.x)/dy))*h,541];}
function paintPhysicalShadows(ctx,data,body){
 if(!data.art||!data.art.shadow)return;const light=data.art.key,n=body.nodes;
 ctx.save();ctx.strokeStyle='#263a39';ctx.fillStyle='#263a39';ctx.globalAlpha=data.art.shadow*.14;ctx.lineCap='round';
 for(const [a,b] of data.links){if(!n[a]||!n[b])continue;const r=data.character?.bones[b]?.radius||4;sceneLine(ctx,[groundProjection(n[a],light),groundProjection(n[b],light)],'#263a39',r*1.4);}
 const p=groundProjection(n.head,light);artEllipse(ctx,p[0],541,(data.character?.head_radius||12)*1.4,2.2,'#263a39');
 for(const o of data.scene.objects){if(o.kind!=='body')continue;const state=body.objects?.find(x=>x[0]===o.id),p=groundProjection([state?.[1]??o.x,state?.[2]??o.y],light),r=o.radius||o.width/2||20;artEllipse(ctx,p[0],542,r*1.2,2.4,'#263a39');}ctx.restore();
}
function paintArtFinishVector(ctx,data){
 const a=data?.art;if(!a)return;
 ctx.save();
 if(a.exposure!==1){ctx.globalAlpha=Math.abs(a.exposure-1)*.5;ctx.fillStyle=artTone(a.exposure>1?'#fff4df':'#152333',data);ctx.fillRect(0,0,1000,600);ctx.globalAlpha=1;}
 if(a.vignette){const g=ctx.createRadialGradient(500,290,120,500,290,600);g.addColorStop(0,'#10243200');g.addColorStop(1,a.mode==='noir'?`rgba(30,30,30,${a.vignette})`:`rgba(16,36,50,${a.vignette})`);ctx.fillStyle=g;ctx.fillRect(0,0,1000,600);}
 // Fine deterministic vector stippling, never an animated raster/noise texture.
 if(a.grain){if(!artGrainPath){artGrainPath=new Path2D();for(let i=0;i<350;i++)artGrainPath.rect(i*719%1009,i*367%607,.55,.55);}ctx.fillStyle='#253a3b';ctx.globalAlpha=a.grain*.4;ctx.fill(artGrainPath);}
 ctx.restore();
}
function paintArtFinish(ctx,data){
 const a=data?.art;if(!a)return;
 const key=JSON.stringify([canvas.width,canvas.height,a.exposure,a.vignette,a.grain]);
 if(key!==artFinishKey){
  if(!artFinishCache)artFinishCache=document.createElement('canvas');
  artFinishCache.width=canvas.width;artFinishCache.height=canvas.height;
  const target=artFinishCache.getContext('2d');target.setTransform(canvas.width/1000,0,0,canvas.height/600,0,0);paintArtFinishVector(target,data);artFinishKey=key;
 }
 ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(artFinishCache,0,0);ctx.restore();
}
function paintMaterialObject(ctx,obj,state,data){
 const x=state?.[1]??obj.x,y=state?.[2]??obj.y,angle=state?.[3]??obj.angle??0;
 const rx=obj.radius||obj.width/2||Math.max(...obj.vertices.map(p=>Math.abs(p[0]))),ry=obj.radius||obj.height/2||Math.max(...obj.vertices.map(p=>Math.abs(p[1]))),base=obj.color||'#8eaaa7';
 ctx.save();ctx.translate(x,y);ctx.rotate(angle);
 function contour(){ctx.beginPath();if(obj.shape==='circle')ctx.arc(0,0,rx,0,Math.PI*2);else if(obj.shape==='polygon'){ctx.moveTo(...obj.vertices[0]);for(const p of obj.vertices.slice(1))ctx.lineTo(...p);ctx.closePath();}else ctx.roundRect(-rx,-ry,rx*2,ry*2,Math.min(3,rx*.1));}
 const light=data.art.key,dx=light.x-x,dy=light.y-y,lx=(dx*Math.cos(angle)+dy*Math.sin(angle)),ly=(-dx*Math.sin(angle)+dy*Math.cos(angle)),len=Math.hypot(lx,ly)||1,rough=obj.material==='steel'?.2:obj.material==='rubber'?.9:.7;
 contour();ctx.fillStyle=artGradient(ctx,lx/len*rx,ly/len*ry,-lx/len*rx,-ly/len*ry,base,data,rough);ctx.fill();
 ctx.save();ctx.clip();ctx.lineWidth=.5;
 if(obj.material==='wood'){
  for(let i=0;i<20;i++){const yy=-ry+i*ry*.11;ctx.beginPath();ctx.moveTo(-rx,yy);ctx.bezierCurveTo(-rx*.4,yy+Math.sin(i*3)*2,rx*.2,yy-2,rx,yy+Math.sin(i*7)*2);ctx.strokeStyle=artTone(artMix(base,i%3?'#3a342d':'#fff0c3',i%3?.2:.22),data);ctx.stroke();}
 }else if(obj.material==='steel'){
  ctx.globalAlpha=.23;ctx.fillStyle=artTone(light.color,data);ctx.translate(-rx*.5,-ry);ctx.rotate(-.3);ctx.fillRect(0,0,Math.max(1,rx*.18),ry*3);ctx.fillRect(rx*.4,0,Math.max(1,rx*.06),ry*3);
 }else if(obj.material==='stone'){
  for(let i=0;i<18;i++){const px=(i*37%97)/97*rx*2-rx,py=(i*47%89)/89*ry*2-ry;ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px+6+i%9,py+2);ctx.lineTo(px+3,py+6);ctx.closePath();ctx.fillStyle=artTone(artMix(base,i%2?'#233e40':'#eef1cb',.12),data);ctx.fill();}
 }else if(obj.material==='rubber'&&obj.shape==='circle'){
  for(let i=0;i<24;i++){const a=i*Math.PI/12;sceneLine(ctx,[[Math.cos(a)*rx*.81,Math.sin(a)*rx*.81],[Math.cos(a+.04)*rx,Math.sin(a+.04)*rx]],artTone(artMix(base,'#101d25',.4),data),1.4);}
 }
 ctx.restore();contour();ctx.strokeStyle=artTone(artMix(base,'#182f36',.52),data);ctx.lineWidth=.9;ctx.stroke();
 if(obj.shape==='circle'&&(obj.material==='steel'||obj.material==='rubber')){
  const h=obj.material==='rubber'?.42:.2;artEllipse(ctx,0,0,rx*h,rx*h,artGradient(ctx,-rx*h,-rx*h,rx*h,rx*h,obj.material==='rubber'?'#a2b2b1':base,data,.2),artTone(artMix(base,'#122632',.5),data),.7);
  artEllipse(ctx,0,0,Math.max(1,rx*.07),Math.max(1,rx*.07),artTone('#30464c',data));
 }
 ctx.restore();
}
