/* Resolution-independent landscape. All marks are paths, gradients or ellipses. */
"use strict";
function vectorLandscapeStatic(ctx,env,art){
 const data={art},at=art.atmosphere||{},depth=at.depth??.7,haze=at.haze??.3;
 const sky=ctx.createLinearGradient(0,-300,0,540);sky.addColorStop(0,artTone(artMix(env.sky_top,'#203f58',.2),data));sky.addColorStop(.63,artTone(env.sky_top,data));sky.addColorStop(1,artTone(env.sky_bottom,data));ctx.fillStyle=sky;ctx.fillRect(-2000,-2000,5000,4600);
 const sun=env.sun,light=art.key;
 if(sun?.radius){
  const g=ctx.createRadialGradient(light.x,light.y,0,light.x,light.y,370);g.addColorStop(0,artTone(light.color,data)+'b0');g.addColorStop(.17,artTone(light.color,data)+'33');g.addColorStop(1,artTone(light.color,data)+'00');ctx.fillStyle=g;ctx.fillRect(light.x-370,light.y-370,740,740);
  artEllipse(ctx,sun.x,sun.y,sun.radius,sun.radius,artTone(sun.color,data));
 }
 // Distant strata share the environment palette; authored mountains replace them.
 if(!env.mountains?.length&&depth>.01){
  for(let k=0;k<4;k++){
   const p=k/3,baseY=380+k*37,height=(95-k*15)*depth,color=artMix(env.sky_bottom,env.ground_bottom,.2+p*.23);
   ctx.save();const parallax=(1-p)*.45;if(typeof shot!=='undefined')ctx.translate((shot.x-500)*parallax,(shot.y-300)*parallax*.5);
   ctx.beginPath();ctx.moveTo(-100,540);ctx.lineTo(-100,baseY);
   for(let x=-100;x<=1100;x+=55){const y=baseY-(Math.sin(x*.013+k*1.9)*.4+Math.sin(x*.027+k*.4)*.28+.4)*height;ctx.lineTo(x,y);}
   ctx.lineTo(1100,540);ctx.closePath();const g=ctx.createLinearGradient(0,baseY-height,0,540);g.addColorStop(0,artTone(color,data));g.addColorStop(1,artTone(artMix(color,env.sky_bottom,haze*.6),data));ctx.fillStyle=g;ctx.fill();ctx.restore();
  }
 }
 for(const m of env.mountains||[]){const ys=m.points.map(p=>p[1]),g=ctx.createLinearGradient(0,Math.min(...ys),0,540);g.addColorStop(0,artTone(m.color,data));g.addColorStop(1,artTone(artMix(m.color,env.sky_bottom,haze*.7),data));ctx.beginPath();ctx.moveTo(...m.points[0]);for(const p of m.points.slice(1))ctx.lineTo(...p);ctx.closePath();ctx.fillStyle=g;ctx.fill();}
 const vegetation=at.vegetation??.5;
 if(vegetation>.01&&depth>.01){
  for(let i=0;i<Math.round(55*vegetation);i++){
   const x=i*157%1021,y=494+Math.sin(i*1.7)*8,height=(12+i*23%19)*depth,spread=height*.22;
   ctx.beginPath();ctx.moveTo(x-spread,y);ctx.lineTo(x-spread*.45,y-height*.35);ctx.lineTo(x-spread*.65,y-height*.35);ctx.lineTo(x-spread*.18,y-height*.68);ctx.lineTo(x-spread*.38,y-height*.68);ctx.lineTo(x,y-height);ctx.lineTo(x+spread*.38,y-height*.68);ctx.lineTo(x+spread*.18,y-height*.68);ctx.lineTo(x+spread*.65,y-height*.35);ctx.lineTo(x+spread*.45,y-height*.35);ctx.lineTo(x+spread,y);ctx.closePath();ctx.fillStyle=artTone(artMix(env.ground_bottom,env.sky_bottom,.4+haze*.3),data);ctx.fill();
  }
 }
 const ground=ctx.createLinearGradient(0,540,0,650);ground.addColorStop(0,artTone(artMix(env.ground_top,light.color,.15*light.intensity),data));ground.addColorStop(.05,artTone(env.ground_top,data));ground.addColorStop(1,artTone(env.ground_bottom,data));ctx.fillStyle=ground;ctx.fillRect(-2000,540,5000,2000);
 ctx.strokeStyle=artTone(artMix(env.ground_top,light.color,.25),data);ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(-2000,540);ctx.lineTo(3000,540);ctx.stroke();

}

function vectorLandscapeLive(ctx,env,art,t){
 const data={art},at=art.atmosphere||{},light=art.key;
 const clouds=env.clouds||[];
 for(let i=0;i<clouds.length;i++){
  const cloud=clouds[i],wind=(at.wind||0)*t*2,x=((cloud.x+wind+160)%1320)-160;
  ctx.save();ctx.translate(x,cloud.y);ctx.scale(cloud.scale||1,cloud.scale||1);
  ctx.beginPath();ctx.moveTo(-78,12);ctx.bezierCurveTo(-94,3,-67,-11,-48,-7);ctx.bezierCurveTo(-48,-28,-10,-34,0,-18);ctx.bezierCurveTo(20,-45,62,-26,58,-7);ctx.bezierCurveTo(104,-11,111,15,75,20);ctx.bezierCurveTo(28,28,-34,25,-78,12);ctx.closePath();
  const g=ctx.createLinearGradient(0,-35,0,25);g.addColorStop(0,artTone('#fff9e8',data)+'d0');g.addColorStop(.4,artTone(env.sky_bottom,data)+'b0');g.addColorStop(1,artTone(artMix(env.sky_top,'#657988',.2),data)+'50');ctx.fillStyle=g;ctx.fill();
  ctx.restore();
 }
 const vegetation=at.vegetation??.5;
 if(vegetation>.01){
  for(let group=0;group<3;group++){
   ctx.beginPath();
   for(let i=group;i<Math.round(240*vegetation);i+=3){
    const x=(i*107%1009),y=542+(i*53%59),height=1+(i*17%5),sway=Math.sin(t*1.1+i)*at.wind*1.4;
    ctx.moveTo(x,y);ctx.quadraticCurveTo(x+sway,y-height*.6,x-1+sway,y-height);
   }
   ctx.strokeStyle=artTone(group?artMix(env.ground_bottom,'#1a4240',.1):artMix(env.ground_top,light.color,.45),data);ctx.lineWidth=.65;ctx.stroke();
  }
 }
}
let vectorSceneryCache=null,vectorSceneryKey=null;
function vectorLandscape(ctx,env,art,t){
 const matrix=ctx.getTransform(),width=canvas.width,height=canvas.height;
 // Disposable render cache at the actual backing resolution and camera scale.
 // The editable source remains vector; every changed light, shape or shot rebuilds it.
 const key=JSON.stringify([env,art.mode,art.key,art.atmosphere,width,height,...[matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f].map(v=>Math.round(v*10)/10)]);
 if(key!==vectorSceneryKey){
  if(!vectorSceneryCache)vectorSceneryCache=document.createElement('canvas');
  if(vectorSceneryCache.width!==width||vectorSceneryCache.height!==height){vectorSceneryCache.width=width;vectorSceneryCache.height=height;}
  const target=vectorSceneryCache.getContext('2d');target.setTransform(1,0,0,1,0,0);target.clearRect(0,0,width,height);target.setTransform(matrix);vectorLandscapeStatic(target,env,art);vectorSceneryKey=key;
 }
 ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(vectorSceneryCache,0,0);ctx.restore();
 vectorLandscapeLive(ctx,env,art,t);
}
