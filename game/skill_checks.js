/* Server-side checks over the same executable motion used by the viewer. */
function checkSkill(index) {
 const {scene,clips,massProps,F0,F1,LADDER,rung,solePoint}=DagiMotion;
 const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
 let reach=0,boneError=0,finite=true,maxStep=0,last=null,handContact=0,footContact=0,rungError=0,rungSamples=0,first,lastPose,trajectory=[];
 for(let j=0;j<=Math.ceil(clips[index].duration*120);j++){
  let t=Math.min(j/120,clips[index].duration),p=scene(index,t).pose;
  if(j%12===0)trajectory.push({time:t,phase:p.meta.phase,hip:p.pelvis.p,head:p.head.p,hands:[p.handl.b,p.handr.b],feet:[p.footl.ankle,p.footr.ankle],contacts:p.meta.contacts||[],airborne:!!p.meta.air});
  if(!first)first=p;lastPose=p;reach=Math.max(reach,p.meta.error||0);
  for(let side of ['l','r'])for(let [name,L]of [['thigh',.44],['calf',.44],['arm',.29],['forearm',.27]])boneError=Math.max(boneError,Math.abs(dist(p[name+side].a,p[name+side].b)-L));
  for(let [name,b]of Object.entries(p))if(name!=='meta')finite=finite&&b.p.every(Number.isFinite);
  if(last)maxStep=Math.max(maxStep,dist(p.pelvis.p,last.pelvis.p));last=p;
  for(let co of p.meta.contacts||[]){if(co.kind==='hand')handContact++;if(co.kind==='foot')footContact++;
   if(index===3&&co.kind==='foot'&&co.label?.startsWith('Ступень')){
    let k=Number(co.label.split(' ')[1])-1,r=rung(k);
    if(k<0||k>=LADDER.count)rungError=100;
    for(let s of ['l','r']){let f=p['foot'+s],toe=solePoint({p:f.ankle,a:f.angle},[.16,-.075]);if(dist(toe,co.p)<.035){rungSamples++;rungError=Math.max(rungError,Math.abs(toe[1]-r.y-.018));}}
   }
  }
 }
 let checks=[{name:'Конечные координаты',passed:finite,value:finite},
 {name:'Длина костей',passed:boneError<1e-6,value:boneError,limit:1e-6,unit:'m'},
 {name:'Достижимость суставов',passed:reach<.002,value:reach,limit:.002,unit:'m'},
 {name:'Непрерывность положения',passed:maxStep<.14,value:maxStep,limit:.14,unit:'m / 120Hz'}];
 if(index<2){let f=index===0?F0:F1,err=0,momentum=0,dt=f.T/f.N;for(let j=1;j<f.N;j++){let t=j*dt,p=f.at(t),expected=[f.C0[0]+f.v[0]*t,f.C0[1]+f.v[1]*t-4.905*t*t];err=Math.max(err,dist(massProps(p).c,expected));let a=f.tables[j-1],w=(f.angles[j]-f.angles[j-1])/dt;momentum=Math.max(momentum,Math.abs(a.I*w+a.H-f.L));}
 checks.push({name:'Баллистика центра масс',passed:err<1e-6,value:err,limit:1e-6,unit:'m'},{name:'Сохранение момента импульса',passed:momentum<1e-6,value:momentum,limit:1e-6});
 if(index===0){let p=scene(0,4.3).pose;checks.push({name:'Колено и кулак у пола',passed:Math.min(p.calfl.a[1],p.calfr.a[1])<.06&&Math.min(p.handl.b[1],p.handr.b[1])<.06,value:Math.min(p.handl.b[1],p.handr.b[1])});}
 }
 if(index===2)checks.push({name:'Опора рукой и продолжение движения',passed:handContact>10&&lastPose.pelvis.p[0]>first.pelvis.p[0]+2,value:handContact});
 if(index===3)checks.push({name:'Стопы на существующих ступенях',passed:rungSamples>100&&rungError<.001,value:rungError,limit:.001,unit:'m'},{name:'Подъём на площадку',passed:lastPose.pelvis.p[1]>LADDER.top+.6,value:lastPose.pelvis.p[1],unit:'m'});
 if(index===4)checks.push({name:'Зацеп руками и выход на верх',passed:handContact>30&&lastPose.pelvis.p[1]>2.4,value:handContact});
 if(index===5){let p=lastPose,sh=p.torso.b;checks.push({name:'Посадка и руки на руле',passed:p.pelvis.p[0]>4&&p.pelvis.p[0]<4.4&&Math.abs(p.handl.b[0]-4.61)<.03&&Math.abs(p.handr.b[0]-4.69)<.03,value:p.pelvis.p});}
 return {passed:checks.every(c=>c.passed),checks,trajectory,samples:Math.ceil(clips[index].duration*120)+1,scope:'Reference trajectory geometry; no learned muscle controller or general collision proof'};
}
