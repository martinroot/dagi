/* Visual construction and release effects reflect persisted runtime state. */
"use strict";
let studioKey = null, studioSession = null, clockOffset = 0, releaseFlash = null;
let studioActivity = {phase:"idle"}, reportKey = null;
const make = (tag, cls, text) => {const el=document.createElement(tag);el.className=cls||"";if(text!==undefined)el.textContent=text;return el;};
function studioReset(){
  if(typeof authoredReset==="function")authoredReset();
  studioSession=null;studioKey=null;releaseFlash=null;reportKey=null;studioActivity={phase:"idle"};
  $("visual-layer").replaceChildren();$("human-controls").replaceChildren();$("release-overlay").hidden=true;$("draft-label").hidden=true;
}

function studioRuntime(data) {
  studioActivity = data.activity || {phase:runId ? "running" : "idle"};
  if (data.server_time) clockOffset = data.server_time * 1000 - Date.now();
  const names = {idle:"ОЖИДАНИЕ",provider:"LLM API · ЗАПРОС JSON",tool:`ИНСТРУМЕНТ · ${studioActivity.tool || ""}`,running:"ЦИКЛ АГЕНТА"};
  $("mechanism-phase").textContent = names[studioActivity.phase] || "ОЖИДАНИЕ";
  $("mechanism-model").textContent = studioActivity.model ? `${studioActivity.model} · calls ${studioActivity.provider_calls}` : "Модель → JSON → инструмент → наблюдение";
  const drafting=data.build===undefined ? !!sceneData?.build : !!data.build;
  document.querySelectorAll(".human-control").forEach((button)=>{button.disabled=!!runId || studioActivity.phase!=="idle" || drafting;});
}
function studioEvent(event){
  if(event.kind==="tool_call")studioActivity={...studioActivity,phase:"tool",tool:event.tool_name};
  else if(event.kind==="text")studioActivity={...studioActivity,phase:"provider"};
  else if(event.kind==="done")studioActivity={...studioActivity,phase:"idle"};
  else if(event.kind==="started"||event.kind==="tool_result")studioActivity={...studioActivity,phase:"running"};
  studioRuntime({activity:studioActivity});
}
function studioRefresh(data) {
  studioRuntime(data);
  if(typeof authoredSync==="function")authoredSync(data);
  if (studioSession !== sessionId) {studioSession=sessionId;studioKey=null;releaseFlash=null;reportKey=null;}
  const key = `${data.render_key || ""}:${data.build?.state || "live"}:${data.scene.version || 0}:${canvas.getBoundingClientRect().width}:${innerWidth}x${innerHeight}`;
  $("world-version").textContent = `WORLD v${data.scene.version || 0}`;
  document.documentElement.style.setProperty("--agent-accent",data.theme?.accent||"#e6703a");
  const build=data.build;
  $("build-status").textContent = build ? `${build.state.toUpperCase()} · ${build.objective}\nИзменений: ${build.edits} · Тестов: ${build.test_count}/3${build.report ? `\nПроверки: ${build.report.passed ? "ПРОЙДЕНЫ" : "ЕСТЬ ОШИБКИ"}` : ""}` : data.last_release ? `SATISFY · v${data.last_release.version}\n${data.last_release.objective}` : "Чистый мир. Агент может начать свою первую сборку.";
  if (build?.report) $("build-evidence").textContent=pretty(build.report);
  else $("build-evidence").textContent=data.last_release?.report ? pretty(data.last_release.report) : "Нет результатов проверки черновика.";
  $("visual-layer").classList.toggle("is-draft",!!build);
  $("draft-label").hidden=!build;
  if(studioKey===key)return;
  studioKey=key;
  const layer=$("visual-layer"), controls=$("human-controls");layer.replaceChildren();controls.replaceChildren();
  const widgets=(build ? data.preview?.widgets : data.widgets) || [];
  const scale=canvas.getBoundingClientRect().width/1000;
  for(const widget of widgets){
    const card=make("article",`world-widget kind-${widget.kind}`);
    Object.assign(card.style,{left:`${widget.x/10}%`,top:`${widget.y/6}%`,width:`${widget.width/10}%`,height:`${widget.height/6}%`,fontSize:`${Math.max(6,12*scale)}px`,padding:`${8*scale}px`});
    card.dataset.widgetId=widget.id;
    card.append(make("div","widget-type",widget.kind.toUpperCase()),make("strong","widget-title",widget.title));
    if(widget.body)card.append(make("div","widget-body",widget.body));
    if(widget.kind==="todo"){
      for(const item of widget.items){const row=make("div","widget-item",`${item.done ? "[x]" : "[ ]"} ${item.text}`);card.append(row);
        const button=control(`${item.done ? "✓" : "○"} ${item.text}`,widget.id,item.id,data.scene.version);controls.append(button);}
    }
    if(widget.kind==="skill"||widget.kind==="button"){
      const target=widget.target;card.append(make("div","widget-binding",`${target.type} / ${target.name || target.action || "prompt"}`));
      card.onclick=()=>humanControl(widget.id,null,data.scene.version).catch(error);
      card.setAttribute("role","button");card.tabIndex=build?-1:0;
      card.onkeydown=(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();card.click();}};
      controls.append(control(widget.title,widget.id,null,data.scene.version));
    }
    layer.append(card);
  }
  for(const component of (build ? data.preview?.components : data.components)||[]){
    for(const event of component.events||[]){
      const button=make("button","human-control",event.label);button.type="button";
      button.onclick=()=>authoredEvent(component.id,event.id).catch(error);controls.append(button);
    }
  }
  if(!controls.children.length)controls.append(make("span","small","Здесь появятся кнопки и туду, созданные агентом."));
  studioRuntime(data);
  studioMeasure(data);
}
function studioMeasure(data){
  const token=generation, build=data.build;
  const reports=typeof authoredReports==="function"?authoredReports():[];
  const scale=canvas.getBoundingClientRect().width/1000;
  const measurementKey=`${data.render_key}:${innerWidth}x${innerHeight}:${JSON.stringify(reports)}`;
  if(data.render_key && reportKey!==measurementKey){
    reportKey=measurementKey;
    requestAnimationFrame(()=>{
      if(token!==generation||data.render_key!==sceneData?.render_key)return;
      const issues=[];
      document.querySelectorAll(".world-widget").forEach((el)=>{if(el.scrollHeight>el.clientHeight+2||el.scrollWidth>el.clientWidth+2)issues.push(`content_overflow:${el.dataset.widgetId}`);});
      if(scale<.5)issues.push("small_canvas: accessible controls are provided below the world");
      api(`game/sessions/${sessionId}/render-report`,"POST",{version:data.scene.version||0,render_key:data.render_key,view:build?"draft":"live",
        width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,issues:issues.slice(0,24),components:reports}).catch(()=>{});
    });
  }
}
function control(label,id,itemId,version){
  const button=make("button","human-control",label);button.type="button";
  button.onclick=()=>humanControl(id,itemId,version).catch(error);return button;
}
async function humanControl(widgetId,itemId,version){
  if(!sessionId||runId||sceneData?.build||studioActivity.phase!=="idle")return;
  const token=generation;busy(true);
  try{
    const payload={widget_id:widgetId,version};if(itemId)payload.item_id=itemId;
    const data=await api(`game/sessions/${sessionId}/interact`,"POST",payload);
    if(token!==generation)return;
    if(data.local){busy(false);await refreshWorld(token);return;}
    message("user",`Нажата кнопка мира: ${widgetId}${itemId ? ` / ${itemId}` : ""}`);
    runId=data.run_id;stream(runId,0,token);
  }catch(exc){if(token===generation)busy(false);throw exc;}
}
function studioRelease(previous,data){
  if(previous && data.scene.version>previous.scene.version && data.last_release){
    releaseFlash={start:performance.now(),version:data.scene.version,id:data.last_release.id};
    $("release-overlay").dataset.releaseId=data.last_release.id;
  }
}
function drawWorldObject(ctx,o,tick,ghost=false){
  ctx.save();if(ghost){ctx.globalAlpha=.35;ctx.setLineDash([5,5]);}
  if(o.kind==="body"){
    ctx.fillStyle=o.color||"#b7c5a4";ctx.strokeStyle="#52644b";ctx.lineWidth=1.5;
    if(o.shape==="circle"){ctx.beginPath();ctx.arc(o.x,o.y,o.radius,0,Math.PI*2);ctx.fill();ctx.stroke();}
    else{ctx.fillRect(o.x-o.width/2,o.y-o.height/2,o.width,o.height);ctx.strokeRect(o.x-o.width/2,o.y-o.height/2,o.width,o.height);}
  }else if(o.kind==="block"){ctx.fillStyle="#d8decb";ctx.fillRect(o.x,o.y,o.width,o.height);ctx.strokeStyle="#a7b094";ctx.strokeRect(o.x,o.y,o.width,o.height);}
  else if(o.kind==="ladder"){
    ctx.strokeStyle="#b28b55";ctx.lineWidth=4;
    for(const side of [-1,1]){ctx.beginPath();ctx.moveTo(o.x+side*o.width/2,o.y);ctx.lineTo(o.x+side*o.width/2,o.y+o.height);ctx.stroke();}
    for(let y=o.y+10;y<o.y+o.height;y+=18){ctx.beginPath();ctx.moveTo(o.x-o.width/2,y);ctx.lineTo(o.x+o.width/2,y);ctx.stroke();}
  }else if(o.kind==="fan"){
    ctx.strokeStyle="#7892a3";ctx.lineWidth=2;ctx.beginPath();ctx.arc(o.x,o.y,21,0,Math.PI*2);ctx.stroke();
    const angle=o.enabled?tick*.16:0;
    for(let i=0;i<3;i++){const a=angle+i*Math.PI*2/3;ctx.beginPath();ctx.moveTo(o.x,o.y);ctx.lineTo(o.x+Math.cos(a)*17,o.y+Math.sin(a)*17);ctx.stroke();}
    ctx.setLineDash([3,5]);ctx.globalAlpha=ghost ? .15 : .3;ctx.beginPath();ctx.arc(o.x,o.y,o.range,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=ghost ? .35 : 1;ctx.setLineDash([]);
    const a=o.angle*Math.PI/180;ctx.beginPath();ctx.moveTo(o.x+Math.cos(a)*27,o.y+Math.sin(a)*27);ctx.lineTo(o.x+Math.cos(a)*50,o.y+Math.sin(a)*50);ctx.stroke();
  }else{ctx.fillStyle="#e6703a";ctx.beginPath();ctx.arc(o.x,o.y,6,0,Math.PI*2);ctx.fill();}
  if(o.label){ctx.font="12px monospace";ctx.fillStyle="#69715c";ctx.fillText(o.label,o.x,o.y-26);}
  ctx.restore();
}
function drawStudio(ctx,now,data,body){
  if(!data||!body?.nodes?.hip){$("release-overlay").hidden=true;return;}
  if(data.build&&data.preview){for(const o of data.preview.objects){if(!data.scene.objects.some(live=>live.id===o.id))drawWorldObject(ctx,o,body.tick,true);}}
  const phase=studioActivity.phase, active=phase!=="idle", hip=body.nodes.hip;
  const x=Math.min(935,hip[0]+105),y=Math.max(70,hip[1]-100);
  if(active){
    ctx.save();ctx.strokeStyle=data.theme?.accent||"#e6703a";ctx.fillStyle=data.theme?.accent||"#e6703a";ctx.lineWidth=1.5;ctx.setLineDash([4,5]);
    ctx.beginPath();ctx.moveTo(hip[0]+10,hip[1]-60);ctx.lineTo(x,y);ctx.stroke();ctx.setLineDash([]);
    const angle=now*.003;ctx.beginPath();ctx.arc(x,y,25,angle,angle+Math.PI*1.6);ctx.stroke();
    for(let i=0;i<3;i++){const a=angle+i*2.1;ctx.beginPath();ctx.arc(x+Math.cos(a)*25,y+Math.sin(a)*25,3,0,Math.PI*2);ctx.fill();}
    ctx.font="bold 12px monospace";ctx.fillText(phase==="provider"?"LLM":phase==="tool"?"TOOL":"RUN",x-16,y+4);
    ctx.font="10px monospace";ctx.fillText(phase==="provider"?"JSON ↑ / ↓":studioActivity.tool||"agent loop",Math.max(5,x-50),y+43);
    if(data.build){ctx.strokeStyle="#879773";ctx.setLineDash([3,4]);ctx.strokeRect(hip[0]-40,hip[1]-115,85,125);ctx.setLineDash([]);ctx.fillStyle="#6c8055";ctx.fillText(`BUILD / ${data.build.edits}`,hip[0]-35,hip[1]-123);}
    ctx.restore();
  }
  const overlay=$("release-overlay"), number=$("release-number"), label=$("release-label");
  if(data.build?.state==="scheduled"){
    overlay.hidden=false;overlay.className="release-overlay countdown";
    const remaining=data.build.activate_at*1000-(Date.now()+clockOffset);
    number.textContent=remaining>0?String(Math.min(3,Math.ceil(remaining/(data.build.countdown_ms||3000)*3))):"…";
    label.textContent=remaining>0?"SATISFY · ПРОВЕРКИ ПРОЙДЕНЫ":"ОЖИДАНИЕ АКТИВАЦИИ СЕРВЕРОМ";
  }else if(releaseFlash&&now-releaseFlash.start<1400){
    overlay.hidden=false;overlay.className="release-overlay activated";number.textContent="БАХ";label.textContent=`WORLD v${releaseFlash.version} · ОБНОВЛЕНО`;
  }else{overlay.hidden=true;}
}
$("improve-self").onclick=()=>lifeAction("start").catch(error);
$("show-skills").onclick=()=>send("Визуализируй свои реальные навыки вокруг себя: создай карточки skill с привязкой к доступным инструментам или сохранённым программам поведения. Проверь читаемость. Покажи разницу между доступным инструментом и проверенным навыком.").catch(error);
if(typeof ResizeObserver!=="undefined")new ResizeObserver(()=>{if(sceneData)studioRefresh(sceneData);}).observe(canvas);
if(sceneData)studioRefresh(sceneData);
