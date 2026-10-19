/* MATTER: authored evolution of a physical actor in one consistent vector world. */
const body=require('./body-controller.js'),{ramp,mix,clamp}=require('./story-kit.js');
module.exports=({t,s,state,event})=>{
 const actor=body({t,s,state,event}),n=s.joints,d=s.dynamics||{},grow=ramp(t,5,10),detail=ramp(t,8,17),head=n.head;
 const palette={sky_top:mix('#ffffff','#a8c8d6',grow),sky_bottom:mix('#ffffff','#f5e9d5',grow),ground_top:mix('#ffffff','#a5b19b',grow),ground_bottom:mix('#ffffff','#697c70',grow)};
 let look={character:{style:t<5?'sticks':t<8?'skeleton':'anatomical',surface:{bone:mix('#4d555a','#eee3cf',grow),skin:'#c28b71',roughness:.6,muscles:.85,bone_visibility:(1-ramp(t,8,11))*.6,markings:0},features:{hair:t<11?'none':'swept',hair_length:.55*ramp(t,11,16),detail,iris:'#4b9e8d',eye_size:1.05}},environment:{...palette,sun:{x:740,y:110,radius:27*grow,color:'#fff0ce'},clouds:grow>.05?[{x:210,y:100,scale:Math.max(.1,grow)},{x:820,y:150,scale:Math.max(.1,grow*.8)}]:[]},art:{ambient:.65,key:{x:240,y:65,color:'#ffedcf',intensity:1.1},shadow:.3*grow,rim:.3,grain:.01*grow,vignette:.08*grow,atmosphere:{depth:.8*grow,haze:.3*grow,vegetation:.8*grow,wind:.2}}};
 if(t>6&&t<11)look.reveal={progress:((t-6)%1.65)/1.65,band:15,color:'#87c5ad'};
 const wink=ramp(t,15.1,15.24)*(1-ramp(t,15.55,15.8)),smile=ramp(t,14.2,15),hello=ramp(t,16,16.5)*(1-ramp(t,18,18.6));
 let expression={focus:actor.air?1:.65,arousal:actor.air?.8:.35,valence:.55*smile,smile:.6*smile,blink_left:wink,mouth:hello*.09*(.5+.5*Math.sin(t*16)),gaze:[head[0]+12,head[1]-2],brow:actor.air?.4:0};
 let camera={target:'hip',offset:[-6,-30],zoom:t<5?2.4:2.5,ease:.35,letterbox:t<5?0:.035};
 if(t>11&&t<19)camera={target:'head',offset:[0,-2],zoom:7.8,ease:.6,letterbox:t<5?0:.035};
 if(['crouch','push','flight','land'].includes(actor.phase))camera={target:[500+((d.com?.[0]||500)-500)*.3,410],offset:[0,0],zoom:1.9,ease:.45,letterbox:.035};
 if(t>27)camera={target:'head',offset:[0,-2],zoom:7.8,ease:.65,letterbox:t<5?0:.035};
 let beat={rise:'Материя · внутренние мышцы',balance:t<7?'Равновесие':'Развитие мира',crouch:'Подготовка · опора',push:'Отталкивание',flight:'Свободный полёт',land:'Контакт · поглощение энергии'}[actor.phase];
 const failed=actor.state.launch!==null&&(d.contacts||[]).includes('head');
 if(failed){beat='Посадка не освоена';expression={...expression,valence:-.4,smile:0,focus:1};camera={target:d.com||n.hip,zoom:1.8,ease:.4,letterbox:.035};}
 const speech=hello>.01?{text:"Hello I'm Dagi",progress:ramp(t,16,16.8),opacity:hello,color:'#b6dcca'}:undefined;
 const sinceLand=actor.state.land===null?null:t-actor.state.land;
 const rate=actor.air?.22:sinceLand!==null&&sinceLand<1.2?.22+.78*ramp(sinceLand,.5,1.2):1;
 return {state:actor.state,control:actor.control,look,expression,camera,speech,beat,caption:failed?'Контакт головой: попытка не засчитана. Контроллер посадки требует доработки.':'',playback:{speed:rate}};
};
