/* Optional browser integration check. Requires Playwright and a Chromium binary.
   node scripts/verify_agent_browser.cjs /path/to/chromium
   Uses an isolated temp database, test login and no real model credentials. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {resolve}=require('node:path');
const {writeFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const python=process.env.DAGI_TEST_PYTHON||resolve('.venv/bin/python');
const server=spawn(python,['-u','-c',`
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path('tests').resolve()))
from test_core_web import _config
from dagi_core.web import WebApp
with tempfile.TemporaryDirectory() as d:
    def forbidden(*args): raise RuntimeError('Browser QA has no live model provider')
    app=WebApp(_config(Path(d)),provider_factory=forbidden)
    server=app.create_server(host='127.0.0.1',port=0)
    print(server.server_address[1],flush=True)
    server.serve_forever()
`],{cwd:resolve(__dirname,'..')});
server.stderr.on('data',d=>process.stderr.write(d));
(async()=>{
 let browser;
 try{
  const port=await new Promise((resolve,reject)=>{server.stdout.once('data',d=>resolve(Number(d.toString().trim())));server.once('exit',c=>reject(Error('Preview server exited '+c)));});
  browser=await chromium.launch({executablePath:process.argv[2]||undefined,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/game/`);
  await page.fill('#username','admin');await page.fill('#password','local-test-password');await page.locator('#login button').click();
  await page.waitForFunction(()=>document.querySelectorAll('#skills button').length===6);
  const first=await page.locator('#sessions').inputValue();
  await page.locator('[data-skill="somersault"]').click();await page.locator('[data-skill="somersault"][aria-pressed="true"]').waitFor();await page.waitForTimeout(200);
  await page.locator('#stop-motion').click();await page.waitForFunction(()=>document.querySelectorAll('#skills button[aria-pressed="true"]').length===0);await page.waitForTimeout(100);
  const stopped=await page.evaluate(()=>DagiView.pose.pelvis.p);
  await page.waitForTimeout(300);assert.deepEqual(await page.evaluate(()=>DagiView.pose.pelvis.p),stopped);
  await page.locator('[data-skill="vault"]').click();
  await page.locator('#history summary.pass').waitFor({timeout:12000});
  await page.locator('#practice').check();
  await page.waitForFunction(()=>document.querySelectorAll('#skills button[aria-pressed="true"]').length===1,{timeout:7000});
  await page.locator('#stop-motion').click();
  const download=page.waitForEvent('download');await page.locator('#download-log').click();
  assert.match((await download).suggestedFilename(),/^dagi-agent-\d+\.json$/);
  await page.locator('#new-session').click();
  await page.waitForFunction(previous=>document.getElementById('sessions').value!==previous,first);
  assert.equal(await page.locator('#history details').count(),0);
  await page.locator('#sessions').selectOption(first);
  await page.locator('#history summary.pass').waitFor();
  await page.setViewportSize({width:320,height:900});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({errors,skills:6,stopFreezesPose:true,completedReceipt:true,practice:true,export:true,sessionIsolation:true,mobileOverflow:false}));
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
