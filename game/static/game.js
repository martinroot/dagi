/* The browser renders server physics. It never invents a successful action. */
"use strict";
const $ = (id) => document.getElementById(id);
const apiRoot = new URL("../api/", location.href);
let sessionId = null, runId = null, source = null, generation = 0, revision = -1;
let sceneData = null, displayed = null, animation = null, polling = false;
const toolCards = new Map();
const seenLifeRuns = new Set();
let trailFrames = [];
let policyControlsKey = null;
let frameSource=null, frameQueue=[], frameLive=false, frameVersion=-1, frameTick=-1, frameMetaPending=false;
const canvas = $("world"), ctx = canvas.getContext("2d");
const pretty = (value) => JSON.stringify(value, null, 2);

async function api(path, method = "GET", body) {
  const response = await fetch(new URL(path, apiRoot), {method, credentials:"same-origin",
    headers:body === undefined ? {} : {"Content-Type":"application/json"},
    body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}
function error(exc) { $("error").textContent = exc.message || String(exc); }
function showLogin() {
  generation++; closeStream(); closeFrames(); sessionId = null; runId = null;
  sceneData = displayed = animation = null; revision = -1;
  $("lab").hidden = true; $("login").hidden = false; $("logout").hidden = true;
}
function closeStream() { if (source) source.close(); source = null; }
function closeFrames(){if(frameSource)frameSource.close();frameSource=null;frameLive=false;frameQueue=[];frameVersion=-1;frameTick=-1;}
function busy(active) {
  $("send").disabled = active || !sessionId; $("stop").hidden = !active;
  $("download-log").disabled = !sessionId;
  $("run-state").textContent = active ? "RUNNING" : "READY";
  $("status").textContent = active ? "● Агент действует" : sessionId ? "○ Мир на паузе" : "Выберите сессию";
}
function message(role, body, kind = "") {
  const el = document.createElement("div"); el.className = `message ${role} ${kind}`;
  const label = document.createElement("div"); label.className = "role";
  label.textContent = ({user:"ВЫ", assistant:"DAGI / BODY AGENT", tool:"TOOL EVIDENCE"})[role] || role;
  const content = document.createElement("div"); content.className = "body"; content.textContent = body || "";
  el.append(label, content); $("chat").append(el); $("chat").scrollTop = $("chat").scrollHeight;
  return content;
}
function toolEvidence(event) {
  const key = event.tool_call_id;
  const prior = key ? toolCards.get(key) : null;
  if (prior) {
    prior.summary.textContent = `${event.tool_name || "tool"} · ${event.outcome || event.kind}`;
    prior.pre.textContent = `${prior.arguments}\n\n${event.text || ""}`;
    return;
  }
  const el = document.createElement("details"); el.className = "message tool";
  const summary = document.createElement("summary");
  summary.textContent = `${event.tool_name || "tool"} · ${event.outcome || event.kind}`;
  const pre = document.createElement("pre"); pre.textContent = event.text || pretty(event.tool_args || {});
  el.append(summary, pre); $("chat").append(el);
  if (key) toolCards.set(key, {summary, pre, arguments:pretty(event.tool_args || {})});
}
async function sessions() {
  const data = await api("game/sessions"); $("sessions").replaceChildren();
  for (const session of data.sessions) {
    const button = document.createElement("button"); button.textContent = `${session.title}\n#${session.id}`;
    button.className = session.id === sessionId ? "selected" : "";
    button.onclick = () => selectSession(session.id, session.title).catch(error);
    $("sessions").append(button);
  }
  return data.sessions;
}
async function selectSession(id, title) {
  const token = ++generation; closeStream(); closeFrames(); sessionId = id; runId = null; revision = -1;
  sceneData = displayed = animation = null; trailFrames = []; seenLifeRuns.clear(); policyControlsKey = null;
  if(typeof studioReset==="function")studioReset();
  $("title").textContent = title || `Эксперимент #${id}`; $("chat").replaceChildren(); toolCards.clear(); busy(false);
  const snapshot = await api(`sessions/${id}`);
  if (token !== generation) return;
  const savedCalls = new Map(snapshot.tool_calls.map((call) => [call.tool_call_id, call]));
  function savedTool(item) {
    toolEvidence({kind:"tool_result",tool_call_id:item.tool_call_id,tool_name:item.name,outcome:item.status,text:item.result||item.error,tool_args:item.arguments});
  }
  for (const item of snapshot.messages) {
    const msg = item.message || item;
    if ((msg.role === "user" || msg.role === "assistant") && msg.content) {
      if(msg.role==="user"&&msg.content.startsWith("Continue your own development in this living world."))message("assistant","Самостоятельная итерация развития");
      else message(msg.role,msg.content);
    }
    for (const call of msg.tool_calls || []) {
      const saved = savedCalls.get(call.id);
      if (saved) savedTool(saved);
    }
  }
  for (const item of snapshot.tool_calls.slice(-20)) if (!toolCards.has(item.tool_call_id)) savedTool(item);
  await refreshWorld(token);
  if (token !== generation) return;
  connectFrames(id,token);
  const running = snapshot.runs.find((run) => run.status === "running");
  if (running) {
    runId = running.run_id; busy(true);
    const through = snapshot.event_cursors[runId] || 0;
    const pending = await restorePendingText(runId, through, token, snapshot.messages);
    if (token !== generation) return;
    stream(runId, through, token, pending);
  }
  await sessions();
}
async function restorePendingText(id, through, token, messages) {
  let after = 0, pending = "";
  while (BigInt(after) < BigInt(through)) {
    const page = await api(`runs/${id}/events?format=json&after=${after}&through=${through}&limit=500`);
    if (token !== generation) return null;
    for (const row of page.events) {
      if (row.event.kind === "text") pending += row.event.text || "";
      else if (["tool_call", "tool_result", "done"].includes(row.event.kind)) pending = "";
    }
    if (BigInt(page.next_after) <= BigInt(after)) throw new Error("Event replay cursor did not advance");
    after = page.next_after;
    if (!page.has_more) break;
  }
  if (!pending) return null;
  const last = messages.at(-1);
  if (last && last.role === "assistant" && last.content === pending) return null;
  return message("assistant", pending);
}
async function refreshWorld(token = generation) {
  const id = sessionId;
  if (!id) return;
  const data = await api(`game/sessions/${id}`);
  if (token !== generation || id !== sessionId || data.scene.revision < revision) return;
  lifeRefresh(data);
  if(typeof studioRuntime==="function")studioRuntime(data);
  if(data.scene.revision === revision)return;
  const previous=sceneData, changedVersion=previous && data.scene.version!==previous.scene.version;
  if(typeof studioRelease==="function")studioRelease(previous,data);
  const hadFrame = displayed !== null;
  const oldTick = displayed ? displayed.tick : 0;
  revision = data.scene.revision; sceneData = data;
  if(data.frame?.nodes?.head){trailFrames.push(data.frame);trailFrames=trailFrames.slice(-12);}
  const motion = hadFrame && !changedVersion ? data.motion.filter((frame) => frame.tick >= oldTick) : [];
  animation = motion.length > 1 ? {frames:motion, start:performance.now(), duration:Math.min(4000, (motion.at(-1).tick - motion[0].tick) / 60 * 1000)} : null;
  if(frameLive){animation=null;}
  else if (!animation) displayed = data.frame;
  $("body-id").textContent = data.self.body_id;
  const programs = [...(data.self.programs || []),...(data.policies || [])].map((program) => `${program.name}@${program.version}`).join(", ") || "нет сохранённых программ";
  $("identity").textContent = `Я: ${data.self.body_id}\nСессия: ${data.self.session_id}\nСреда: browser canvas + чат\nВосприятие: датчики + кадр canvas при включённом зрении\nКод тела: ${data.self.code.engine}\nМоё поведение: controller + versioned skills\nМои программы: ${programs}\nРабочая папка: ${data.self.workspace}\nЧеловек видит тело и результаты действий`;
  const s = data.scene;
  const autonomy = s.autonomy_execution, autonomyBadge = $("autonomy-status");
  autonomyBadge.hidden = !autonomy;
  if (autonomy) {
    autonomyBadge.className = `autonomy-status ${autonomy.status || ""}`;
    const dx = (Number(autonomy.current_x) - Number(autonomy.start_x)).toFixed(2);
    const goalDelta = typeof autonomy.goal_distance_change === "number" ? ` · goal Δ ${autonomy.goal_distance_change > 0 ? "+" : ""}${autonomy.goal_distance_change.toFixed(2)}` : "";
    autonomyBadge.textContent = `SELF PROGRAM ${autonomy.program}@${autonomy.program_version} · ${(autonomy.status || "").toUpperCase()} · ${autonomy.cycles_completed}/${autonomy.cycles_requested} циклов · ${autonomy.frames_executed} кадров · Δx ${dx}${goalDelta}`;
  }
  $("observation").textContent = `Позиция: x=${s.position.x}, y=${s.position.y}\nСтоит: ${s.upright ? "да" : "нет"} · Опора: ${s.grounded ? "да" : "нет"}\nРевизия: ${s.revision} · Кадр: ${s.tick}\n\n${s.goal ? `${s.goal.label}\nЦель x=${s.goal.x} ±${s.goal.tolerance}\nРасстояние: ${s.goal.distance} · signed_error: ${s.goal.signed_error} · курс: ${s.goal.direction_to_goal}\nПроверка позы: ${s.goal.passed ? "ПРОЙДЕНА" : "НЕ ПРОЙДЕНА"}` : "Цель ещё не задана"}`;
  $("reflection").textContent = pretty(s.latest_reflection || s.last_action || {status:"Готов к первому эксперименту"});
  $("scene").textContent = pretty({physics:s.physics, controller:s.controller, objects:s.objects, behaviors:s.behaviors, goal:s.goal});
  $("history").textContent = pretty(data.history);
  if(typeof studioRefresh==="function")studioRefresh(data);
}
function stream(id, after, token, pending = null) {
  closeStream(); let assistant = pending; let cursor = BigInt(after);
  const connection = new EventSource(new URL(`runs/${encodeURIComponent(id)}/events?after=${after}`, apiRoot)); source = connection;
  connection.onmessage = (event) => {
    if (token !== generation || runId !== id) return;
    if (event.lastEventId) { const next = BigInt(event.lastEventId); if (next <= cursor) return; cursor = next; }
    const data = JSON.parse(event.data);
    if (data.session_id !== sessionId || data.run_id !== id) return;
    if(typeof studioEvent==="function")studioEvent(data);
    if (data.kind === "text") {
      if (!assistant) assistant = message("assistant", "");
      assistant.textContent += data.text || ""; $("chat").scrollTop = $("chat").scrollHeight;
    } else if (data.kind === "tool_call" || data.kind === "tool_result") {
      assistant = null; toolEvidence(data); refreshWorld(token).catch(error);
    } else if (data.kind === "error") { message("error", data.text, "error"); }
    else if (data.kind === "done") {
      connection.close(); if (source === connection) source = null;
      runId = null; busy(false); $("run-state").textContent = data.status.toUpperCase();
      refreshWorld(token).catch(error);
    }
  };
  connection.onerror = () => {
    if (token === generation && source === connection) {
      $("run-state").textContent = "RECONNECTING";
      api("auth/session").catch(error);
    }
  };
}
async function downloadSessionLog() {
  const id = sessionId;
  if (!id) return;
  const payload = await api(`game/sessions/${id}/export`);
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type:"application/json;charset=utf-8"});
  const url = URL.createObjectURL(blob), anchor = document.createElement("a");
  anchor.href = url; anchor.download = `dagi-session-${id}.json`;
  document.body.appendChild(anchor); anchor.click();
  setTimeout(() => {anchor.remove(); URL.revokeObjectURL(url);}, 1000);
}
$("download-log").onclick = () => downloadSessionLog().catch(error);

async function send(text) {
  if (!sessionId || runId) return;
  $("error").textContent = "";
  const token = generation, id = sessionId;
  busy(true);
  try {
    if(typeof captureVision==="function")await captureVision();
    const data = await api(`sessions/${id}/runs`, "POST", {message:text});
    if (token !== generation) return;
    message("user", text); $("message").value = ""; runId = data.run_id; stream(runId, 0, token);
  } catch (exc) { if (token === generation) busy(false); throw exc; }
}
$("compose").onsubmit = (event) => {event.preventDefault(); const text = $("message").value.trim(); if (text) send(text).catch(error);};
document.querySelectorAll("[data-prompt]").forEach((button) => button.onclick = () => {$("message").value = button.dataset.prompt; $("message").focus();});
$("new-session").onclick = async () => {
  try { const data = await api("game/sessions", "POST", {title:"Чистый мир"}); await selectSession(data.session_id, "Чистый мир"); } catch (exc) { error(exc); }
};
$("stop").onclick = async () => { if (runId) try {await api(`runs/${runId}/cancel`, "POST", {});} catch (exc) {error(exc);} };
$("login").onsubmit = async (event) => {
  event.preventDefault();
  try {await api("auth/login", "POST", {username:$("username").value, password:$("password").value}); $("password").value=""; await init();} catch (exc) {error(exc);}
};
$("logout").onclick = async () => {try {await api("auth/logout", "POST", {}); showLogin();} catch (exc) {error(exc);} };

function drawAvatarExpression(ctx, head, state, now) {
  const [x,y]=head, mode=state||"resting";
  ctx.save();ctx.strokeStyle="#282d23";ctx.fillStyle="#282d23";ctx.lineWidth=1.3;ctx.lineCap="round";
  if(mode==="resting"){
    ctx.beginPath();ctx.moveTo(x-6,y-2);ctx.lineTo(x-2,y-1);ctx.moveTo(x+2,y-1);ctx.lineTo(x+6,y-2);ctx.stroke();
  }else{
    ctx.beginPath();ctx.arc(x-4,y-2,1.1,0,Math.PI*2);ctx.arc(x+4,y-2,1.1,0,Math.PI*2);ctx.fill();
  }
  ctx.beginPath();
  if(mode==="satisfied")ctx.arc(x,y+2,4,Math.PI*.12,Math.PI*.88);
  else if(mode==="uncertain")ctx.arc(x,y+7,4,Math.PI*1.12,Math.PI*1.88);
  else {ctx.moveTo(x-3,y+5);ctx.lineTo(x+3,y+5);}
  ctx.stroke();
  const glyph={focused:"•",satisfied:"✓",uncertain:"?",curious:"…",resting:"z"}[mode]||"·";
  ctx.font="12px system-ui";ctx.textAlign="center";ctx.fillStyle=mode==="uncertain"?"#d07a3e":"#739953";
  ctx.fillText(glyph,x,y-15+(mode==="focused"?Math.sin(now/160)*1.5:Math.sin(now/420)*.6));
  ctx.restore();
}

function draw(now) {
  if(frameLive&&frameQueue.length){displayed=interpolatedFrame(now);animation=null;}
  if(typeof resizeScene==="function")resizeScene(canvas,ctx);
  if(typeof paintScene==="function"){paintScene(ctx,now,sceneData,displayed);if(typeof drawStudio==="function")drawStudio(ctx,now,sceneData,displayed);requestAnimationFrame(draw);return;}
  if (animation) {
    const fraction = animation.duration ? Math.min(1, (now - animation.start) / animation.duration) : 1;
    const first = animation.frames[0].tick, last = animation.frames.at(-1).tick;
    const tick = first + fraction * (last - first);
    let i = animation.frames.findIndex((frame) => frame.tick >= tick); if (i < 0) i = animation.frames.length - 1;
    const a = animation.frames[Math.max(0, i - 1)], b = animation.frames[i];
    const ratio = a.tick === b.tick ? 1 : (tick - a.tick) / (b.tick - a.tick);
    displayed = {tick, nodes:Object.fromEntries(Object.keys(a.nodes).map((key) => [key, [a.nodes[key][0] + (b.nodes[key][0] - a.nodes[key][0]) * ratio, a.nodes[key][1] + (b.nodes[key][1] - a.nodes[key][1]) * ratio]]))};
    if (fraction === 1) {displayed = sceneData.frame; animation = null;}
  }
  ctx.clearRect(0, 0, 1000, 600); ctx.fillStyle=sceneData?.theme?.background || "#fff";ctx.fillRect(0,0,1000,600);
  ctx.fillStyle="#e6e9df";
  for (let x=20;x<1000;x+=30) for(let y=30;y<540;y+=30){ctx.beginPath();ctx.arc(x,y,1,0,Math.PI*2);ctx.fill();}
  ctx.fillStyle="#f0f1eb";ctx.fillRect(0,540,1000,60);ctx.strokeStyle="#bec5b3";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,540);ctx.lineTo(1000,540);ctx.stroke();
  if(typeof drawAuthored==="function")drawAuthored(ctx,now,sceneData,displayed,"background");
  if (sceneData) {
    for(const o of sceneData.scene.objects){
      if(typeof drawWorldObject==="function"){drawWorldObject(ctx,o,displayed?.tick||0);continue;}
      if(o.kind==="block"){ctx.fillStyle="#d8decb";ctx.fillRect(o.x,o.y,o.width,o.height);ctx.strokeStyle="#a7b094";ctx.strokeRect(o.x,o.y,o.width,o.height);}
      else {ctx.fillStyle="#e6703a";ctx.beginPath();ctx.arc(o.x,o.y,6,0,Math.PI*2);ctx.fill();}
      if(o.label){ctx.font="12px monospace";ctx.fillStyle="#69715c";ctx.fillText(o.label,o.x,o.y-12);}
    }
    const goal=sceneData.scene.goal;
    if(goal){ctx.fillStyle=goal.passed?"#73995322":"#e6703a18";ctx.fillRect(goal.x-goal.tolerance,75,goal.tolerance*2,465);ctx.strokeStyle="#e6703a";ctx.setLineDash([5,6]);ctx.beginPath();ctx.moveTo(goal.x,100);ctx.lineTo(goal.x,540);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#c16a3d";ctx.font="12px monospace";ctx.fillText(`TARGET x=${goal.x}`,Math.min(goal.x+12,850),90);}
  }
  if(displayed&&sceneData){
    const n=displayed.nodes;const skin=sceneData.appearance||{};
    const tail=trailFrames.slice(-Math.round(skin.trail||0));
    for(let i=0;i<tail.length;i++){
      ctx.save();ctx.globalAlpha=(i+1)/tail.length*.12;ctx.strokeStyle=skin.accent||"#e6703a";ctx.lineWidth=skin.line_width||5;ctx.lineCap="round";
      for(const [a,b] of sceneData.links){const t=tail[i].nodes;if(t[a]&&t[b]){ctx.beginPath();ctx.moveTo(...t[a]);ctx.lineTo(...t[b]);ctx.stroke();}}ctx.restore();
    }
    ctx.lineWidth=skin.line_width||5;ctx.lineCap="round";ctx.strokeStyle=skin.stroke||"#282d23";
    for(const [a,b] of sceneData.links){ctx.beginPath();ctx.moveTo(...n[a]);ctx.lineTo(...n[b]);ctx.stroke();}
    ctx.fillStyle=skin.fill||"#fff";ctx.beginPath();ctx.arc(...n.head,skin.head_radius||12,0,Math.PI*2);ctx.fill();ctx.stroke();
    drawAvatarExpression(ctx,n.head,animation?"focused":sceneData.scene.avatar_state,now);
    ctx.fillStyle=skin.accent||sceneData.theme?.accent||"#e6703a";for(const [name,p] of Object.entries(n)){if(name==="head")continue;ctx.beginPath();ctx.arc(...p,skin.joint_radius??3.5,0,Math.PI*2);ctx.fill();}
    ctx.font="11px monospace";ctx.fillStyle="#e6703a";ctx.fillText("SELF",n.head[0]+22,n.head[1]-8);
    $("clock").textContent=`t = ${(displayed.tick/60).toFixed(2)} s · 60 Hz`;
    const life=sceneData.life||{};
    $("pose").textContent=sceneData.build?"Проверяю изменения · тело на паузе":life.running?"Живой мир · локальное исполнение":animation?"Воспроизведение серверного действия":"Мир на паузе";
    if(life.intent){
      const bx=Math.max(12,Math.min(770,n.head[0]+28)),by=Math.max(70,n.head[1]-36);
      ctx.save();ctx.fillStyle="#ffffffee";ctx.fillRect(bx-8,by-18,220,30);ctx.font="12px system-ui";ctx.fillStyle="#536348";ctx.fillText(life.intent.slice(0,34),bx,by+1);ctx.restore();
    }
  }
  if(typeof drawAuthored==="function")drawAuthored(ctx,now,sceneData,displayed,"foreground");
  if(typeof drawStudio==="function")drawStudio(ctx,now,sceneData,displayed);
  requestAnimationFrame(draw);
}
function connectFrames(id,token){
  const connection=new EventSource(new URL(`game/sessions/${id}/frames`,apiRoot));frameSource=connection;
  connection.onmessage=(event)=>{
    if(token!==generation||sessionId!==id)return;
    const packet=JSON.parse(event.data);
    if(packet.frame.tick<frameTick&&packet.version===frameVersion)return;
    const stamp=performance.now();frameTick=packet.frame.tick;frameVersion=packet.version;
    frameQueue.push({at:stamp,...packet.frame});frameQueue=frameQueue.slice(-12);frameLive=true;
    if(sceneData){
      const changed=sceneData.scene.version!==packet.version;
      sceneData.life=packet.life;sceneData.scene.emotion=packet.emotion;sceneData.scene.contacts=packet.contacts;
      sceneData.scene.policy_error=packet.error;sceneData.scene.tick=packet.frame.tick;
      if(packet.release?.state==="scheduled")sceneData.build=packet.release;
      if(changed&&!frameMetaPending){frameMetaPending=true;refreshWorld(token).catch(error).finally(()=>frameMetaPending=false);}
    }
    $("clock").textContent=`${(packet.frame.tick/60).toFixed(1)} s · PHYSICS 60 Hz`;
    $("pose").textContent=packet.error?"Контроллер требует исправления":packet.life.running?"Прямой поток кадров · локальный код":"Пауза";
  };
  connection.onerror=()=>{if(frameSource===connection){frameLive=false;$("pose").textContent="Восстанавливаю поток кадров…";}};
}
function interpolatedFrame(now){
  const target=now-70;
  let i=frameQueue.findIndex(f=>f.at>=target);if(i<0)return frameQueue.at(-1);if(i===0)return frameQueue[0];
  const a=frameQueue[i-1],b=frameQueue[i],t=Math.max(0,Math.min(1,(target-a.at)/(b.at-a.at||1)));
  const nodes=Object.fromEntries(Object.keys(b.nodes).map(k=>[k,[a.nodes[k][0]+(b.nodes[k][0]-a.nodes[k][0])*t,a.nodes[k][1]+(b.nodes[k][1]-a.nodes[k][1])*t]]));
  const prior=new Map((a.objects||[]).map(o=>[o[0],o]));
  const objects=(b.objects||[]).map(o=>{const p=prior.get(o[0])||o;return[o[0],p[1]+(o[1]-p[1])*t,p[2]+(o[2]-p[2])*t,p[3]+(o[3]-p[3])*t];});
  return{tick:a.tick+(b.tick-a.tick)*t,nodes,objects};
}
async function lifeAction(action,name) {
  if(!sessionId)return;
  const token=generation;
  const payload={action};
  if(action==="start")payload.iterations=Number($("life-iterations").value)||5;
  if(name)payload.name=name;
  if(action==="start"&&typeof captureVision==="function")await captureVision();
  await api(`game/sessions/${sessionId}/life`,"POST",payload);
  if(token===generation)await refreshWorld(token);
}
function lifeRefresh(data){
  const life=data.life||{}, policies=data.policies||[];
  const working=!!life.thinking;
  const blocked=!!data.scene.policy_error;
  $("life-status").textContent=life.running?(blocked?"Контроллер требует исправления":working?`Развивается · итерация ${life.iteration}/${life.limit}`:life.iteration>=life.limit&&life.limit?`Занимается своим делом · попыток завершено: ${life.iteration}`:"Живёт · локальный контроллер"):"На паузе";
  $("life-intent").textContent=data.scene.policy_error||life.error||life.intent||"Чистый скелет. Следующее занятие выберет агент.";
  $("life-pause").disabled=!life.running;
  $("life-play").disabled=!data.scene.active_policy||!!data.build||!!life.running;
  $("improve-self").disabled=working||!!runId;
  if(life.running)$("status").textContent=working?"● Развивается":"● Живёт";
  const key=JSON.stringify([policies,data.scene.active_policy,!!data.build]);
  if(key!==policyControlsKey){
    policyControlsKey=key;$("policy-controls").replaceChildren();
    for(const p of policies){
      const button=document.createElement("button");button.type="button";button.textContent=`${p.name===data.scene.active_policy?"● ":"▷ "}${p.name}`;button.title=p.description||p.name;button.disabled=!!data.build;
      button.onclick=()=>lifeAction("select",p.name).then(()=>lifeAction("play")).catch(error);$("policy-controls").append(button);
    }
    if(!policies.length)$("policy-controls").textContent="Здесь появятся программы, созданные агентом. Их можно запускать без обращения к модели.";
  }
  const versions=data.evolution||[];
  const timelineKey=JSON.stringify(versions);
  if($("evolution-history").dataset.key!==timelineKey){
    $("evolution-history").dataset.key=timelineKey;$("evolution-history").replaceChildren();
    for(const change of [...versions].reverse()){
      const row=document.createElement("div");row.className="evolution-entry";
      const title=document.createElement("strong");title.textContent=`v${change.version} · ${change.objective}`;row.append(title);
      const a=change.trial?.baseline,b=change.trial?.candidate;
      if(a&&b){const detail=document.createElement("span");detail.textContent=`Проверено ${b.frames||0} кадров · перемещение ${a.dx??"?"} → ${b.dx??"?"} · доля устойчивых поз ${a.upright_ratio??"?"} → ${b.upright_ratio??"?"}`;row.append(detail);}
      $("evolution-history").append(row);
    }
  }
  const background=life.run_id;
  if(background&&!runId&&!seenLifeRuns.has(background)){
    seenLifeRuns.add(background);runId=background;busy(true);message("assistant",`Самостоятельная итерация ${life.iteration}/${life.limit}`);stream(background,0,generation);
  }
}
$("life-pause").onclick=()=>lifeAction("pause").catch(error);
$("life-play").onclick=()=>lifeAction("play").catch(error);
async function init() {
  await api("auth/session"); $("error").textContent=""; $("login").hidden=true; $("lab").hidden=false; $("logout").hidden=false;
  busy(false); const list=await sessions(); if(list.length) await selectSession(list[0].id,list[0].title);
}
setInterval(async()=>{if(polling||!sessionId||document.hidden)return;polling=true;try{await refreshWorld();}catch(exc){error(exc);}finally{polling=false;}},1500);
requestAnimationFrame(draw); init().catch(error);
