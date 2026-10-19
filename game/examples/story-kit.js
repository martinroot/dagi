/* Agent-editable timeline primitives. Pure CommonJS, no DOM or host callbacks. */
const clamp=x=>Math.max(0,Math.min(1,x));
const ease={linear:x=>x,smooth:x=>x*x*(3-2*x),smoother:x=>x*x*x*(x*(x*6-15)+10),in:x=>x*x,out:x=>1-(1-x)*(1-x),back:x=>1+2.70158*(x-1)**3+1.70158*(x-1)**2};
function mix(a,b,u){
 if(typeof a==='number'&&typeof b==='number')return a+(b-a)*u;
 if(Array.isArray(a)&&Array.isArray(b))return a.map((v,i)=>mix(v,b[i]??v,u));
 if(typeof a==='string'&&/^#[\da-f]{6}$/i.test(a)&&/^#[\da-f]{6}$/i.test(b))return '#'+[1,3,5].map(i=>Math.round(mix(parseInt(a.slice(i,i+2),16),parseInt(b.slice(i,i+2),16),u)).toString(16).padStart(2,'0')).join('');
 if(a&&b&&typeof a==='object'&&typeof b==='object'){const o={};for(const k of new Set([...Object.keys(a),...Object.keys(b)]))o[k]=k in a&&k in b?mix(a[k],b[k],u):u===1?b[k]:a[k];return o;}
 return u<1?a:b;
}
function sample(track,t){
 if(!track.length)return null;
 if(t<=track[0].at)return track[0].value;
 for(let i=1;i<track.length;i++){const b=track[i],a=track[i-1];if(t<=b.at)return mix(a.value,b.value,(ease[b.ease||'smoother']||ease.smoother)(clamp((t-a.at)/(b.at-a.at))));}
 return track[track.length-1].value;
}
function sequence(clips,t){let start=0;for(const clip of clips){if(t<start+clip.duration)return {...clip,local:t-start,progress:clamp((t-start)/clip.duration)};start+=clip.duration;}return {...clips.at(-1),local:t-start,progress:1,finished:true};}
module.exports={clamp,ease,mix,sample,sequence,ramp:(t,a,b)=>ease.smoother(clamp((t-a)/(b-a)))};
