/* First authored short. Powered stage choreography, not a learned policy.
 * Edit the shot keys, palette passes, expression envelopes or limb targets;
 * story-kit is generic and every output remains available to other projects. */
const {sample,ramp,mix,clamp}=require('./story-kit.js');
const shotKeys=[
 [0,[500,330],1],[1.2,[500,330],1],[2.5,[500,440],2.5],[5,[500,410],3.5],[6.4,[500,410],3.5],
 [7.8,[500,365],8.5],[11,[500,365],8.5],[13,[500,385],3.3],
 [22,[500,380],3.3],[24,[500,365],8],[26,[500,350],1.5],
 [30,[540,380],1.65],[33,[550,405],3.25],[36,[550,404],3.5]
].map(([at,p,z])=>({at,value:{p,z}}));
const palettes=[
 {skin:'#dcece7',bone:'#e2efea',accent:'#71dfcc',metallic:.3},
 {skin:'#c49d83',bone:'#f2ddbb',accent:'#e7b869',metallic:.05},
 {skin:'#b5d5d8',bone:'#d8efec',accent:'#6af4d2',metallic:.48}
];
module.exports=({t,s,state,event})=>{
 const torso=s.articulation.head?s.articulation.head.world_angle-s.articulation.head.angle:Math.PI/2;
 let turn=state.turn??Math.round((torso-Math.PI/2)/(2*Math.PI));
 let origin=state.origin||0;
 if(['replay','transform','stunt'].includes(event?.id)){turn=Math.round((torso-Math.PI/2)/(2*Math.PI));}
 if(event?.id==='replay')origin=t;
 let time=Math.max(0,t-origin),extra=state.extra??-100;
 if(event?.id==='human_attention')extra=time;
 if(event?.id==='transform')origin=t-13,time=13;
 if(event?.id==='stunt')origin=t-26,time=26;
 const head=s.joints.head,hip=s.joints.hip;
 const attention=ramp(time,extra,extra+.2)*(1-ramp(time,extra+1,extra+1.5));
 const shot=sample(shotKeys,time);
 // Targets are shot coordinates relative to the measured actor. No body teleport.
 const xOffset=(time<26?500:550)-hip[0];
 const camera={target:[shot.p[0]-xOffset,shot.p[1]+(hip[1]-447)],zoom:shot.z,cut:true,letterbox:.055};
 const wink=ramp(time,8.1,8.22)*(1-ramp(time,8.48,8.7));
 const smile=ramp(time,8.65,9.3),hello=ramp(time,9.4,10.4)*(1-ramp(time,12,12.7));
 const expression={valence:.15+.65*smile,arousal:.45,focus:.8,surprise:.25*(1-smile),smile:.85*smile,blink_left:Math.max(wink,attention*.9),blink_right:0,mouth:.13*hello*(.5+.5*Math.sin(time*17)),brow:.25,gaze:[head[0]+10,head[1]-3],tilt:.02*Math.sin(time*.7)};
 let control={servos:{},rig:{position:[500,447],angle:Math.PI/2+turn*2*Math.PI}};
 const idle={head:-Math.PI/2,left_elbow:.24,right_elbow:-.24,left_hand:-.2,right_hand:.2,left_knee:.12,right_knee:-.12,left_foot:-.25,right_foot:-.25,left_toe:-1.57,right_toe:-1.57};
 let joints={...idle},beat='Общий план';
 if(time>2.5)beat='Фигура';if(time>5)beat='Поясной';if(time>7.8)beat='Лицо · контакт';
 if(time>9.4)beat='Hello, I’m Dagi';
 const phase=clamp((time-13)/10.5)*3,index=Math.min(2,Math.floor(phase)),u=phase-index,progress=time>=23.5?1:ramp(u,0,.86);
 const target=palettes[index],previous=palettes[Math.max(0,index-1)],surface=mix(previous,target,progress);
 let look={character:{style:'ceramic',surface:{...surface,roughness:.3,markings:.8},features:{hair:'swept',hair_length:.85*ramp(time,13,16),hair_color:'#173449',iris:'#62ead1',brow:'#24414d',detail:ramp(time,4,10),eye_size:1.15,freckles:.15}},art:{rim:.8}};
 if(time>=13){
  beat='Материалы · '+(index+1)+'/3';
  look.reveal={progress,band:24,color:target.accent};
  look.environment={sky_top:mix('#132a44','#273456',ramp(time,13,23)),sky_bottom:mix('#6c9c9d','#dcb3a4',ramp(time,13,23)),ground_top:mix('#4d7979','#718d8b',ramp(time,13,23)),ground_bottom:'#192f43'};
  look.art={key:{x:240,y:80,color:mix('#bdeee5','#ffdebc',ramp(time,13,23)),intensity:1.25},rim:.85,atmosphere:{depth:1,haze:.35,vegetation:.9,wind:.3}};
 }
 if(time>=23.5){delete look.reveal;beat='Новый облик';}
 // The explicit rig accelerates/rotates the torso; limbs use relative torques.
 // There are no world-coordinate writes and all collision contacts remain real.
 if(time>=26){
  const q=time-26;
  beat=q<1?'Подготовка':q<3.2?'Сальто · сценическая страховка':q<4.8?'Приземление':'Готов';
  const crouch=ramp(q,0,.65)*(1-ramp(q,.85,1.1));
  const flight=ramp(q,.9,1.45)*(1-ramp(q,2.5,3.2));
  const spin=ramp(q,1.1,2.85),move=ramp(q,.9,3.1),land=ramp(q,3.1,3.4)*(1-ramp(q,3.4,4.3));
  control.rig={position:[500+50*move,447+14*crouch-155*flight+11*land],angle:Math.PI/2+Math.PI*2*(turn+spin),stiffness:2200,damping:190,rotation_stiffness:380000,rotation_damping:23000};
  const tuck=ramp(q,1.1,1.6)*(1-ramp(q,2.35,2.8));
  joints={...idle,left_knee:mix(.12,-1.1,tuck)+.2*crouch,right_knee:mix(-.12,-.95,tuck)-.3*crouch,left_foot:mix(-.25,-1.7,tuck)-.6*crouch,right_foot:mix(-.25,-1.7,tuck)-.6*crouch,left_elbow:mix(.24,-1,tuck),right_elbow:mix(-.24,-1.1,tuck),left_hand:-.5-.8*tuck,right_hand:1.4*tuck};
  expression.focus=1;expression.smile=.4*(1-tuck);expression.valence=.55;
  if(q>=4){
   const ready=ramp(q,4,5.8),breath=Math.sin(q*2.4)*.025;
   control.rig.position=[550,447+8*ready+breath*12];control.rig.angle=Math.PI/2+Math.PI*2*(turn+1)-.08*ready;
   joints={...joints,left_knee:.55*ready,right_knee:-.55*ready,left_foot:-.5*ready,right_foot:-.65*ready,left_elbow:.4*ready,right_elbow:.7*ready,left_hand:-2.7*ready,right_hand:2.6*ready};
   expression.smile=.25;expression.brow=.55;expression.clench=ready;
  }
 }
 for(const [name,angle] of Object.entries(joints))control.servos[name]={angle,stiffness:30000,damping:900,max_torque:name==='head'?27000:66000};
 // Toe torque cap is 90000; head27000; other caps >=66000 in this film body.
 if(time>33)beat='Боевая стойка · упругая страховка';
 const draw=[];
 if(time>29.1&&time<30.9){const v=(time-29.1)/1.8;draw.push({type:'ellipse',x:550,y:538,rx:20+90*v,ry:3+9*v,fill:'#82f5d4',alpha:(1-v)*.25,layer:'background'});}
 let speech=hello>.01?{text:"Hello I'm Dagi",speaker:'DAGI',progress:ramp(time,9.4,10.2),opacity:hello,color:'#aef3df'}:undefined;
 if(attention>.1){speech={text:'I see you.',opacity:attention,color:'#aef3df'};expression.smile=.9;}
 return {state:{origin,extra,turn},camera,expression,look,control,draw,speech,beat};
};
