'use strict';
(() => {
 const R=Retainer;
 function validateConfig(c,rules){
  R.assert(c&&c.version===R.VERSION&&rules?.version===R.VERSION,'资源版本不兼容');
  const keys=RETAINER_CONFIG.fields.map(f=>f.key);
  R.assert(Array.isArray(c.fields)&&c.fields.length===keys.length&&c.fields.every((f,i)=>f.key===keys[i]&&typeof f.label==='string'&&Array.isArray(f.aliases)&&f.aliases.every(x=>typeof x==='string')),'字段定义不兼容');
  for(const k of ['companyKeywords','criminalKeywords','riskKeywords','criminalStages'])R.assert(Array.isArray(c[k])&&c[k].length&&c[k].every(x=>typeof x==='string'&&x.length>0&&x.length<200),'识别规则错误：'+k);
  for(const k of Object.keys(RETAINER_CONFIG.placeholders))R.assert(typeof c.placeholders?.[k]==='string','占位符定义缺失：'+k);
  R.assert(Object.keys(c.placeholders).length===Object.keys(RETAINER_CONFIG.placeholders).length,'本版不支持增加案件字段');
  for(const k of Object.keys(RETAINER_CONFIG.defaults))R.assert(typeof c.defaults?.[k]==='string','默认信息缺失：'+k);
  for(const k of ['civil','criminal'])R.assert(Array.isArray(c.directories?.[k])&&c.directories[k].includes('01委托手续')&&c.directories[k].every(R.safePath),'案件目录配置错误');
  for(const k of ['fixed','semi_risk','pure_risk'])R.assert(Array.isArray(c.feeClauses?.[k])&&c.feeClauses[k].length&&c.feeClauses[k].every(x=>typeof x==='string'&&x.length),'收费条款配置错误：'+k);
  R.assert(Array.isArray(rules.rules)&&rules.rules.length>0&&rules.rules.length<500,'占位符规则数量错误');
  for(const r of rules.rules){R.assert(['exact','regex_replace','blank_prefix','blank_suffix','underline_after_prefix'].includes(r.mode)&&typeof r.new==='string','注入规则错误');
   if(r.mode==='exact')R.assert((Array.isArray(r.old)?r.old:[r.old]).every(x=>typeof x==='string'&&x.length),'精确匹配文本为空');
   if(r.mode==='regex_replace'){R.assert(typeof r.pattern==='string'&&r.pattern.length<300&&!/\([^)]*[+*][^)]*\)[+*{]/.test(r.pattern),'正则规则过于复杂');new RegExp(r.pattern,'g');}
  }
 }
 /* 可导入的旧版工作包。旧版资源（模板分组、收费条款结构）与本版不兼容，
    因此只接收其中的案件数据，模板与收费条款一律改用本版内置资源。 */
 const LEGACY_VERSIONS=['3.3.0','3.4.0'];
 function validateState(s){
  R.assert(s&&Array.isArray(s.records)&&s.records.length<=100000,'案件数据错误');
  for(const x of s.records){R.assert(x&&x.row&&R.config.fields.every(f=>typeof(x.row[f.key]??'')==='string'),'案件字段数据错误');R.assert(!x.issues||Array.isArray(x.issues)&&x.issues.every(v=>typeof v==='string'),'案件错误清单无效');}
  R.assert(s.index===undefined||Number.isInteger(s.index)&&s.index>=0&&s.index<Math.max(1,s.records.length),'当前案件序号错误');
  R.assert(s.remember===undefined||typeof s.remember==='boolean','本地保存状态错误');
  if(s.workbook){R.assert(Array.isArray(s.workbook.sheets)&&s.workbook.sheets.length,'工作表数据错误');for(const sh of s.workbook.sheets){R.assert(typeof sh.name==='string'&&Array.isArray(sh.rows),'工作表格式错误');for(const row of sh.rows){if(row==null)continue;R.assert(Array.isArray(row)&&row.every(c=>c==null||typeof c.value==='string'),'单元格数据错误');}}R.assert(Number.isInteger(s.sheet)&&s.sheet>=0&&s.sheet<s.workbook.sheets.length&&Number.isInteger(s.header)&&s.header>=1,'工作表选择状态错误');}
  R.assert(!s.mapping||typeof s.mapping==='object'&&!Array.isArray(s.mapping)&&Object.values(s.mapping).every(v=>v===''||v==null||/^\d+$/.test(String(v))),'字段映射数据错误');
 }
 async function pack(kind,state){
  R.assert(['work','resources'].includes(kind),'工作包类型错误');const payload={version:R.VERSION,config:R.config,rules:R.rules,templates:R.templates};if(kind==='work')payload.state=state;
  const b=new TextEncoder().encode(JSON.stringify(payload)),z=new JSZip();z.file('payload.json',b);z.file('manifest.json',JSON.stringify({format:'retainer-offline',version:R.VERSION,kind,sha256:await R.hash(b)},null,2));return z.generateAsync({type:'uint8array',compression:'DEFLATE'});
 }
 async function unpack(data,expected){
  const z=await R.openZip(data);R.assert(z.file('manifest.json')&&z.file('payload.json'),'缺少工作包清单');const m=JSON.parse(await z.file('manifest.json').async('string'));
  R.assert(m.format==='retainer-offline'&&m.kind===expected,'包类型不兼容');
  const legacy=m.version!==R.VERSION;
  if(legacy)R.assert(LEGACY_VERSIONS.includes(m.version),'包版本 '+m.version+' 与当前 '+R.VERSION+' 不兼容，无法导入');
  const b=await z.file('payload.json').async('uint8array');R.assert(await R.hash(b)===m.sha256,'包内容校验失败');
  const p=JSON.parse(new TextDecoder().decode(b));
  if(legacy){
   R.assert(expected==='work','旧版资源包不再导入，请改用本版内置资源');
   validateState(p.state);
   return {version:R.VERSION,config:R.config,rules:R.rules,templates:R.templates,state:p.state,importedFrom:m.version};
  }
  validateConfig(p.config,p.rules);R.assert(Array.isArray(p.templates)&&p.templates.length>0&&p.templates.length<=100,'模板数量错误');
  const ids=new Set();for(const t of p.templates){R.assert(typeof t.id==='string'&&!ids.has(t.id),'模板 ID 重复或为空');ids.add(t.id);await R.validateTemplate(t);}
  if(expected==='work')validateState(p.state);
  return p;
 }
 function applyPackage(p){R.config=R.clone(p.config);R.rules=R.clone(p.rules);R.templates=R.clone(p.templates);}
 const db=()=>new Promise((resolve,reject)=>{if(!window.indexedDB)return reject(Error('浏览器不支持本地存储，请下载工作包'));const req=indexedDB.open('retainer-offline-v3',1);req.onupgradeneeded=()=>req.result.createObjectStore('work');req.onerror=()=>reject(req.error||Error('本地存储不可用'));req.onsuccess=()=>resolve(req.result);req.onblocked=()=>reject(Error('本地存储被其他页面占用'));});
 async function transaction(mode,act){const d=await db();try{return await new Promise((resolve,reject)=>{const t=d.transaction('work',mode),s=t.objectStore('work'),req=act(s);let result;req.onsuccess=()=>{result=req.result;};req.onerror=()=>reject(req.error);t.oncomplete=()=>resolve(result);t.onerror=()=>reject(t.error||Error('本地存储失败'));t.onabort=()=>reject(t.error||Error('本地存储已中止'));});}finally{d.close();}}
 const storage={get:()=>transaction('readonly',s=>s.get('current')),put:v=>transaction('readwrite',s=>s.put(v,'current')),clear:()=>transaction('readwrite',s=>s.delete('current'))};
 async function saveDirectory(result,root,folders){
  let dir;for(let i=0;i<10000;i++){const name=result.normalized.caseName+(i?` (${i})`:'');try{await root.getDirectoryHandle(name);continue;}catch(e){if(e.name!=='NotFoundError')throw e;}dir=await root.getDirectoryHandle(name,{create:true});break;}R.assert(dir,'同名目录过多');
  const sub=async path=>{let h=dir;for(const bit of path.split('/').filter(Boolean))h=await h.getDirectoryHandle(bit,{create:true});return h;};
  if(folders)for(const p of R.config.directories[result.normalized.case_type])await sub(p);
  const target=folders?await sub('01委托手续'):dir;
  for(const f of result.files){const h=await target.getFileHandle(f.name,{create:true}),s=await h.createWritable();try{await s.write(f.bytes);await s.close();}catch(e){await s.abort().catch(()=>{});throw e;}}
  const report=await dir.getFileHandle('生成校验报告.json',{create:true}),w=await report.createWritable();await w.write(JSON.stringify(result.report,null,2));await w.close();return dir.name;
 }
 Object.assign(R,{validateConfig,pack,unpack,applyPackage,storage,saveDirectory});
})();
