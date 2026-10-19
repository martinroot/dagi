/* One vector vocabulary for authored scenery and live project graphics. */
"use strict";
function vectorPaint(ctx,p,data){
 const tone=color=>data?.art?.mode==='noir'&&typeof artTone==='function'?artTone(color,data):color;
 if(typeof p==='string')return tone(p);
 if(!p)return '#58758c';
 const g=p.type==='radial'?ctx.createRadialGradient(...p.from,0,...p.to,p.radius):ctx.createLinearGradient(...p.from,...p.to);
 for(const [at,color] of p.stops)g.addColorStop(at,tone(color));return g;
}
function vectorDraw(ctx,c,data){
 ctx.save();ctx.globalAlpha*=c.alpha??1;ctx.globalCompositeOperation=c.blend||'source-over';
 if(c.transform)ctx.transform(...c.transform);
 if(c.shadow){ctx.shadowColor=c.shadow.color;ctx.shadowBlur=c.shadow.blur||0;ctx.shadowOffsetX=c.shadow.x||0;ctx.shadowOffsetY=c.shadow.y||0;}
 ctx.lineCap='round';ctx.lineJoin='round';ctx.lineWidth=c.width||2;ctx.fillStyle=vectorPaint(ctx,c.fill,data);ctx.strokeStyle=vectorPaint(ctx,c.stroke,data);ctx.beginPath();
 if(c.type==='line'){ctx.moveTo(c.x,c.y);ctx.lineTo(c.x2,c.y2);}
 if(c.type==='circle')ctx.arc(c.x,c.y,c.radius,0,Math.PI*2);
 if(c.type==='ellipse')ctx.ellipse(c.x,c.y,c.rx,c.ry,c.angle||0,0,Math.PI*2);
 if(c.type==='rect')ctx.roundRect(c.x,c.y,c.w,c.h,Math.min(c.radius||0,c.w/2,c.h/2));
 if(c.type==='path'){ctx.moveTo(...c.points[0]);for(const p of c.points.slice(1))ctx.lineTo(...p);if(c.closed)ctx.closePath();}
 if(c.type==='bezier')for(const p of c.segments){const args=p.slice(1);if(p[0]==='M')ctx.moveTo(...args);if(p[0]==='L')ctx.lineTo(...args);if(p[0]==='Q')ctx.quadraticCurveTo(...args);if(p[0]==='C')ctx.bezierCurveTo(...args);if(p[0]==='Z')ctx.closePath();}
 if(c.type==='text'){ctx.font=`${c.size||16}px system-ui`;ctx.fillText(c.text,c.x,c.y);}else{if(c.fill)ctx.fill();if(c.stroke||!c.fill)ctx.stroke();}
 ctx.restore();
}
function vectorLayers(ctx,data,front){
 for(const layer of [...(data.art?.layers||[])].sort((a,b)=>(a.depth??-1)-(b.depth??-1))){
  if(((layer.depth??-1)>=0)!==front)continue;
  ctx.save();ctx.globalAlpha=layer.opacity??1;
  const p=1-(layer.parallax??1);if(typeof shot!=='undefined')ctx.translate((shot.x-500)*p,(shot.y-300)*p);
  for(const c of layer.commands)vectorDraw(ctx,c,data);ctx.restore();
 }
}
