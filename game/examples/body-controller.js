/* Explicit controller, not an installed gait. All forces are joint reactions.
 * Static inverse loads and COM/velocity feedback are editable authored source.
 * No body position writes, absolute root motor, free force or flight impulse. */
const P=[.22091620954570063,.8759385833918161,.33166935817396226,-.008257696799927198,-.43937504121711085,.03935272871465046,167479.8633551944,208230.60504403396,3923.3313866862227,.018838073065993662];
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const smooth=x=>{x=clamp(x,0,1);return x*x*(3-2*x)};
// Local simulation search supplies the takeoff/flight parameters; still measured.
const J=[1.164717796406054, 1.1150477799258232, 2.0227304554641883, 0.3961871412818966, 0.9102628397059567, 0.3057947693869325, -1.8912436651630058, -0.9302278704083978, -1.5765594835784995, 4.399060364213683, 1.1198104657783496, -0.9386252853820662, -1.6700458792570383];
module.exports=({t,s,state,event})=>{
 const d=s.dynamics||{},n=s.joints,root=d.torso?.angle??.8,omega=d.torso?.velocity??0,com=d.com||n.hip,vx=d.velocity?.[0]||0,vy=d.velocity?.[1]||0;
 const footx=(n.left_foot[0]+n.right_foot[0])/2+7,error=com[0]-footx;
 let h=P[0]+P[1]*(root-1.64)+P[2]*omega+P[3]*error,k=P[4],toe=-(1.64+P[0]+P[4])+P[5]*error+P[9]*vx;
 let phase='balance',launch=state.launch??null,land=state.land??null,start=state.jumpStart??21;
 if(event?.id==='stunt'&&t>6&&(!launch||land&&t-land>2)){start=t;launch=null;land=null;state.airPose=null;state.landArms=null;}
 const rise=smooth((t-.6)/2),arms=t<2.6?(Math.PI/2-root)*(1-rise):0;
 if(t<2.6){phase='rise';h=1.7*(1-rise)+P[0]*rise+P[1]*(root-1.64)+P[2]*omega+P[3]*error;k=-1.2*(1-rise)+P[4]*rise;toe=-1.3*(1-rise)-(1.64+P[0]+P[4])*rise+P[5]*error+P[9]*vx;}
 const q=t-start;
 if(q>=0&&!land){
  if(q<J[0]){phase='crouch';const u=smooth(q/J[0]);h+=J[1]*u;k-=J[2]*u;toe+=J[3]*u;}
  else if(launch===null){phase='push';h=J[4]+2*(root-1.6)+.6*omega;k=J[5];toe=J[6];if(d.airborne&&vy<-25)launch=t;}
  if(launch!==null){phase='flight';h=Math.PI/2-root+.18;k=-.35;toe=-1.4;if((d.contacts||[]).some(a=>a.endsWith('foot')||a.endsWith('toe'))&&t-launch>.25)land=t;}
 }
 if(land!==null)phase='land';
 const settle=land===null?1:smooth((t-land-.25)/1.7);
 if(land!==null){h=P[0]+P[1]*(root-1.64)+P[2]*omega+P[3]*clamp(error,-20,20);k=P[4]-.2*(1-settle);toe=-(1.64+P[0]+P[4])+clamp(.02*error+.001*vx,-.3,.3);}
 const catchHands=0;
 function actorCatch(){return launch!==null&&vy>80?clamp((vy-80)/160,0,1):0;}
 const armTarget=(Math.PI/2-root)*catchHands;
 const angles={head:-Math.PI/2,left_elbow:armTarget+(arms+.18*rise)*(1-catchHands),right_elbow:armTarget+(arms-.18*rise)*(1-catchHands),left_hand:-.2*rise*(1-catchHands),right_hand:.2*rise*(1-catchHands)};
 if(phase==='crouch'){angles.left_elbow=.6;angles.right_elbow=.6;}
 if(phase==='push'){angles.left_elbow=J[12]??-1.6;angles.right_elbow=J[12]??-1.6;}
 if(land!==null){if(!state.landArms)state.landArms=[s.articulation.left_elbow.angle,s.articulation.right_elbow.angle];const a=smooth((t-land-.2)/2);angles.left_elbow=state.landArms[0]*(1-a)+.18*a;angles.right_elbow=state.landArms[1]*(1-a)-.18*a;}
 const servos={},muscles={};
 for(const side of ['left','right']){angles[side+'_knee']=clamp(h,-1.8,1.8);angles[side+'_foot']=clamp(k,-2.5,.35);angles[side+'_toe']=clamp(toe,-2.5,-.3);}
 for(const [name,requested] of Object.entries(angles)){const range=s.articulation[name],angle=range?clamp(requested,range.min,range.max):requested;const small=name==='head'||name.endsWith('hand')||name.endsWith('elbow');servos[name]={angle,stiffness:name==='head'?60000:small?(phase==='push'?70000:12000+catchHands*48000):name.endsWith('toe')?P[7]:P[6],damping:name==='head'?1500:small?(phase==='push'?1800:300+catchHands*900):P[8]};}
 if(phase==='land')for(const side of ['left','right'])for(const suffix of ['knee','foot','toe']){const servo=servos[side+'_'+suffix];servo.stiffness=50000+settle*(P[6]-50000);servo.damping=3500;}
 if(phase==='flight'){
  // Brace the measured takeoff pose. Internal damping cannot steer the COM
  // or manufacture angular momentum; takeoff must establish a good trajectory.
  if(!state.airPose)state.airPose=Object.fromEntries(Object.entries(s.articulation).map(([name,j])=>[name,j.angle]));
  for(const [name,angle] of Object.entries(state.airPose))servos[name]={angle,stiffness:50000,damping:2000};
 }
 if(phase!=='flight'){
  for(const side of ['left','right']){
   const cop=(n[side+'_foot'][0]+n[side+'_toe'][0])/2,other=(n[(side==='left'?'right':'left')+'_foot'][0]+n[(side==='left'?'right':'left')+'_toe'][0])/2;
   const fraction=phase==='push'&&Math.abs(cop-other)>1?clamp((com[0]-other)/(cop-other),.05,.95):.5;
   for(const [child,pivot,names,cap] of [['knee','pelvis',['knee','foot','toe'],90000],['foot','knee',['foot','toe'],65000],['toe','foot',['toe'],30000]]){
    const origin=n[side+'_'+pivot];let torque=(cop-origin[0])*(d.mass||11.7)*(s.body_model?.gravity||981)*fraction*(phase==='push'?J[9]:1);
    for(const part of names){const name=side+'_'+part,from=part==='knee'?'pelvis':part==='foot'?'knee':'foot',mass=s.body_model?.bones?.[name]?.mass||({knee:1.2,foot:.8,toe:.35}[part]);torque-=((n[name][0]+n[side+'_'+from][0])/2-origin[0])*mass*(s.body_model?.gravity||981);}
    muscles[side+'_'+child]=clamp(torque/(cap*s.body_control.muscle_scale),-1,1);
   }
  }
 }
 return {control:{servos,muscles},phase,state:{...state,jumpStart:start,launch,land},air:phase==='flight'&&d.airborne};
};
