const { chromium } = require('./load-playwright.cjs');
const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url');
const root=path.resolve(__dirname,'..'),qa=path.resolve(root,'../retainer-qa');fs.mkdirSync(qa,{recursive:true});
(async()=>{
 const summary=[];
 for(const channel of ['msedge','chrome']){
  const browser=await chromium.launch({channel,headless:true});
  try{
   const ctx=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});await ctx.setOffline(true);
   const page=await ctx.newPage(),network=[],errors=[];page.on('request',r=>{if(/^https?:/.test(r.url())&&!/^http:\/\/127\.0\.0\.1:17801\//.test(r.url()))network.push(r.url());});page.on('pageerror',e=>errors.push(e.message));
   await page.goto(pathToFileURL(path.join(root,'启动.html')).href);await page.waitForFunction(()=>window.RETAINER_UI);
   const report=await page.evaluate(()=>Retainer.selftest());fs.writeFileSync(path.join(qa,channel+'-selftest.json'),JSON.stringify(report,null,2));
   console.log(channel,JSON.stringify(report));
   const xlsx=await page.evaluate(async()=>Retainer.base64(await Retainer.standardXlsx()));fs.writeFileSync(path.join(root,'标准案件录入.xlsx'),Buffer.from(xlsx,'base64'));
   await page.locator('#excelFile').setInputFiles(path.join(root,'标准案件录入.xlsx'));await page.waitForFunction(()=>!document.querySelector('#applyMapping').disabled);
   await page.locator('#sheetSelect').selectOption('2');await page.waitForFunction(()=>!document.querySelector('#applyMapping').disabled);await page.locator('#applyMapping').click();
   await page.waitForFunction(()=>document.querySelector('#caseSelect').options.length===3);await page.locator('#checkCase').click();await page.locator('#generate').click();await page.locator('#outputs').waitFor({state:'visible'});
   const output=await page.evaluate(()=>({report:RETAINER_UI.getResult().report,files:RETAINER_UI.getResult().files.map(f=>({name:f.name,base64:Retainer.base64(f.bytes)}))}));
   fs.mkdirSync(path.join(qa,'sample-docs'),{recursive:true});for(const f of output.files)fs.writeFileSync(path.join(qa,'sample-docs',f.name),Buffer.from(f.base64,'base64'));
   const dl=page.waitForEvent('download');await page.locator('#downloadZip').click();await(await dl).saveAs(path.join(qa,channel+'-case.zip'));
   await page.screenshot({path:path.join(qa,channel+'-cases.png'),fullPage:true});
   await page.locator('[data-page="maintenance"]').click();await page.screenshot({path:path.join(qa,channel+'-maintenance.png'),fullPage:true});
   summary.push({browser:channel,selftest:report.success,uiGeneration:output.report.success,files:output.files.length,externalRequests:network,pageErrors:errors});
  } finally {await browser.close();}
 }
 fs.writeFileSync(path.join(qa,'browser-results.json'),JSON.stringify(summary,null,2));console.log('SUMMARY',JSON.stringify(summary));if(summary.some(r=>!r.selftest||r.externalRequests.length||r.pageErrors.length))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
