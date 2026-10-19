/* MATTER: authored evolution of a physical actor in one consistent vector world. */
const body=require('./body-controller.js'),{ramp,mix,clamp}=require('./story-kit.js');
module.exports=({t,s,state,event,params})=>{
 const actor=body({t,s,state,event,params}),n=s.joints,d=s.dynamics||{},grow=ramp(t,5,10),detail=ramp(t,8,17),head=n.head;
 const palette={sky_top:mix('#ffffff','#91b4c5',grow),sky_bottom:mix('#ffffff','#f8deba',grow),ground_top:mix('#ffffff','#829782',grow),ground_bottom:mix('#ffffff','#455f5b',grow)};
 let look={character:{style:t<5?'sticks':t<8?'skeleton':'anatomical',surface:{bone:mix('#4d555a','#eee3cf',grow),skin:'#c7a08a',roughness:.72,muscles:.85,bone_visibility:(1-ramp(t,8,11))*.6,markings:0},features:{hair:t<11?'none':'swept',hair_length:.55*ramp(t,11,16),detail,iris:'#4b9e8d',eye_size:.96}},environment:{...palette,sun:{x:740,y:110,radius:27*grow,color:'#fff0ce'},clouds:grow>.05?[{x:210,y:100,scale:Math.max(.1,grow)},{x:820,y:150,scale:Math.max(.1,grow*.8)}]:[]},art:{ambient:.56,key:{x:240,y:65,color:'#ffedcf',intensity:1.05},shadow:.46*grow,rim:.42,grain:.01*grow,vignette:.08*grow,atmosphere:{depth:.8*grow,haze:.3*grow,vegetation:.8*grow,wind:.2}}};
 const rebuild=event?.id==='transform'?t:state.rebuildStarted;actor.state.rebuildStarted=rebuild;
 const revealTime=rebuild===undefined?t-6:t-rebuild;
 if(revealTime>0&&revealTime<5)look.reveal={progress:(revealTime%1.65)/1.65,band:15,color:'#87c5ad'};
 const wink=ramp(t,15.1,15.24)*(1-ramp(t,15.55,15.8)),smile=ramp(t,14.2,15),hello=ramp(t,16,16.5)*(1-ramp(t,18,18.6));
 let expression={focus:actor.air?1:.65,arousal:actor.air?.8:.35,valence:.55*smile,smile:.6*smile,blink_left:wink,mouth:hello*.09*(.5+.5*Math.sin(t*16)),gaze:[head[0]+12,head[1]-2],brow:actor.air?.4:0};
 if(actor.phase==='crouch')expression={...expression,smile:0,brow:.45,focus:1,clench:.4,gaze:[head[0]+12,head[1]+25]};
 if(actor.phase==='push')expression={...expression,smile:0,brow:.7,squint:.3,mouth:.12,clench:.65};
 if(actor.air)expression={...expression,smile:.12,surprise:.2,mouth:.15,clench:.15};
 if(actor.phase==='land')expression={...expression,smile:0,brow:.3,squint:.18,clench:.25};
 let camera={target:'hip',offset:[-6,-30],zoom:t<5?2.4:2.5,ease:.35,letterbox:t<5?0:.035};
 if(t>11&&t<17.9)camera={target:'head',offset:[0,-2],zoom:8.5,ease:.6,letterbox:t<5?0:.035};
 if(t>=18.8&&t<20.5)camera={target:'right_hand',offset:[-1,-2],zoom:10,ease:.5,letterbox:.035};
 if(['crouch','push','flight','land'].includes(actor.phase))camera={target:[500+((d.com?.[0]||500)-500)*.3,410],offset:[0,0],zoom:1.9,ease:.45,letterbox:.035};
 if(t>27&&actor.state.success)camera={target:'head',offset:[0,-2],zoom:8.5,ease:.65,letterbox:t<5?0:.035};
 let beat={rise:'Материя · внутренние мышцы',balance:t<7?'Равновесие':'Развитие мира',crouch:'Подготовка · опора',push:'Отталкивание',flight:'Свободный полёт',land:'Контакт · поглощение энергии'}[actor.phase];
 const lost=actor.state.land!==null&&t-actor.state.land>.5&&Math.abs((d.torso?.angle||0)-1.5)>1;
 const failed=actor.state.launch!==null&&(state.failed||(d.contacts||[]).includes('head')||lost);actor.state.failed=failed;
 if(failed){beat='Посадка не освоена';expression={...expression,valence:-.4,smile:0,focus:1};camera={target:d.com||n.hip,zoom:1.8,ease:.4,letterbox:.035};}
 if(actor.state.success&&!failed){beat='Опора восстановлена';expression={...expression,smile:.5,valence:.6};}
 const speech=hello>.01?{text:"Hello I'm Dagi",progress:ramp(t,16,16.8),opacity:hello,color:'#b6dcca'}:undefined;
 const sinceLand=actor.state.land===null?null:t-actor.state.land;
 const rate=actor.air?.22:sinceLand!==null&&sinceLand<1.2?.22+.78*ramp(sinceLand,.5,1.2):1;
 return {state:actor.state,control:actor.control,look,expression,camera,speech,beat,caption:failed?'Равновесие потеряно: попытка не засчитана.':'',playback:{speed:rate}};
};
