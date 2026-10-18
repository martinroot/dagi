import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function host(){const context={window:{addEventListener(){}},canvas:{addEventListener(){}},Map,JSON};
  vm.runInNewContext(fs.readFileSync(new URL("../game/static/component-host.js",import.meta.url),"utf8"),context);return context;}

test("authored render output accepts generic drawing code and only declared button events",()=>{
  const ctx=host(),component={events:[{id:"refresh"}]};
  const commands=[{type:"circle",x:10,y:10,radius:5,fill:"#e6703a"},{type:"button",x:0,y:30,width:120,height:32,text:"Refresh",event_id:"refresh"}];
  assert.equal(ctx.validCommands(commands,component),commands);
  assert.throws(()=>ctx.validCommands([{...commands[1],event_id:"arbitrary-host-action"}],component),/declared/);
  assert.throws(()=>ctx.validCommands([{type:"html",html:"<script>"}],component),/primitive/);
  assert.throws(()=>ctx.validCommands([{type:"circle",x:NaN,y:0,radius:5}],component),/geometry/);
  assert.throws(()=>ctx.validCommands(Array(161).fill(commands[0]),component),/draw list/);
});
