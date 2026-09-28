const {chromium}=require('./load-playwright.cjs');
const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url');
const root=path.resolve(__dirname,'..'),qa=path.resolve(root,'../retainer-qa');
(async()=>{const b=await chromium.launch({channel:'chrome',headless:true});try{const p=await b.newPage();await p.goto(pathToFileURL(path.join(root,'启动.html')).href);await p.waitForFunction(()=>window.Retainer);
 const data=await p.evaluate(async()=>{const results=[];for(const group of ['个人委托','公司委托','刑事']){const input={case_type:group==='刑事'?'刑事':'民商事',party_type:group.startsWith('公司')?'公司':'个人',plaintiff:'张三&A',defendant:'李四<乙>',cause:group==='刑事'?'集资诈骗':'买卖合同纠纷',stage:'一审、二审',fee_desc:'25000元',fee_type:'固定',court:'测试人民法院',detention:'测试看守所',legal_rep:'王五',legal_rep_position:'经理'},n=Retainer.normalize(input),out=await Retainer.generate(n,RETAINER_BUILTIN.templates.filter(t=>t.group===group));results.push({input,normalized:n,files:out.files.map(f=>({name:f.name,base64:Retainer.base64(f.bytes)}))});}return results;});
 fs.writeFileSync(path.join(qa,'parity-data.json'),JSON.stringify(data));console.log('Exported 13 browser-generated documents for independent Python comparison');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
