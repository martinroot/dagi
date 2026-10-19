/* Goal state is derived from source-bound evaluation receipts, never button labels. */
"use strict";
function learningRefresh(plan){
 const root=document.getElementById('learning-skills');if(!root)return;
 const goal=document.getElementById('learning-goal'),status=document.getElementById('learning-status');
 goal.textContent=plan?.goal||'Цель ещё не формализована';
 const labels={unplanned:'Агенту нужно определить измеримый успех и зависимости навыков.',training:'Обучение: следующий шаг выбирается по проверенным зависимостям.',mastered:'Цель прошла все заявленные проверки. Автономные обращения к модели остановлены.',blocked:'Обучение остановлено: нужен разбор блокера или пересмотр плана.'};
 status.textContent=labels[plan?.status||'unplanned'];
 const stamp=JSON.stringify(plan);if(root.dataset.stamp===stamp)return;root.dataset.stamp=stamp;root.replaceChildren();
 const number=v=>typeof v==='number'?Number(v.toFixed(3)):v??'—';
 const names={ready:'В работе / готов к проверке',mastered:'Проверен',blocked:'Заблокирован'};
 for(const s of plan?.skills||[]){
  const row=document.createElement('article');row.className='learning-skill';row.dataset.status=s.status;row.dataset.focus=String(s.id===plan.focus);
  const title=document.createElement('strong');title.textContent=`${s.id===plan.focus?'→ ':''}${s.title} · ${names[s.status]||s.status}`;
  const details=document.createElement('small');details.textContent=`Попытки ${s.attempts}/${s.limit} · fit ${s.score==null?'—':Number(s.score).toFixed(3)}${s.depends.length?' · зависит от '+s.depends.join(', '):''}`;
  row.append(title,details);
  if(s.last||s.reason){const reason=document.createElement('small');reason.textContent=s.reason||`Последняя попытка: ${s.last.applied?'применена':'эксперимент'} · fit ${number(s.last.score)} · ${s.last.passed?'условия выполнены':'условия не выполнены'}${s.last.bottleneck?' · проверить '+s.last.bottleneck:''}`;row.append(reason);}
  if(s.criteria?.length){
   const details=document.createElement('details'),label=document.createElement('summary');label.textContent='Критерии и последняя проверка';details.open=s.id===plan.focus&&s.last&&!s.last.passed;details.append(label);
   const measured=new Map((Array.isArray(s.last?.metrics)?s.last.metrics:[]).map(m=>[m.metric,m]));
   for(const m of s.criteria){const observed=measured.get(m.name),line=document.createElement('small'),target=m.target||{},bounds=[];
    if(target.min!=null)bounds.push('≥ '+number(target.min));if(target.max!=null)bounds.push('≤ '+number(target.max));
    line.textContent=`${observed?(observed.passed?'✓ ':'✕ '):'· '}${m.label||m.name}: ${number(observed?.value)}${m.unit?' '+m.unit:''} · требуется ${bounds.join(' и ')||'проверка в общей функции успеха'}`;line.className='learning-metric';if(observed&&!observed.passed)line.dataset.failed='true';details.append(line);
   }
   if(s.success){const rule=document.createElement('code');rule.textContent='Успех: '+s.success;details.append(rule);}
   if(s.last?.error||s.last?.guard_failures?.length){const failure=document.createElement('small');failure.textContent=s.last.error||'Нарушены ограничения: '+s.last.guard_failures.join('; ');details.append(failure);}
   row.append(details);
  }
  const evaluate=document.createElement('button');evaluate.type='button';evaluate.className='learning-evaluate';evaluate.textContent='Проверить локально · без модели';evaluate.disabled=s.status==='blocked';evaluate.onclick=()=>evaluateSkill(s,evaluate);row.append(evaluate);
  root.append(row);
 }
}

async function evaluateSkill(skill,button){
 const owner=sessionId,version=sceneData?.scene.version;if(!owner)return;
 button.disabled=true;
 try{await api(`game/sessions/${owner}/learning/evaluate`,'POST',{skill:skill.id,world_version:version,contract:skill.contract});if(sessionId===owner)await refreshWorld();}
 catch(exc){if(sessionId===owner)error(exc);}
 finally{if(sessionId===owner)button.disabled=skill.status==='blocked';}
}
