/* Browser business engine. No network or executable imported code. */
'use strict';
window.Retainer = (() => {
  const VERSION = '3.4.1', W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
  const clone = x => JSON.parse(JSON.stringify(x));
  const R = {VERSION, W, config: clone(RETAINER_CONFIG), rules: clone(RETAINER_RULES), templates: clone(RETAINER_BUILTIN.templates)};
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const xml = s => {
    assert(!/<!DOCTYPE|<!ENTITY/i.test(s), '不支持 XML 外部实体或文档类型声明');
    const d = new DOMParser().parseFromString(s, 'application/xml');
    assert(!d.getElementsByTagName('parsererror').length, 'XML 格式错误'); return d;
  };
  const serialize = d => new XMLSerializer().serializeToString(d);
  const els = (n, name, ns=W) => [...n.getElementsByTagNameNS(ns, name)];
  const nearest = (n, name) => { for (let p=n.parentNode;p;p=p.parentNode) if(p.localName===name && p.namespaceURI===W) return p; return null; };
  const texts = p => els(p,'t').filter(n=>nearest(n,'p')===p);
  const ptext = p => texts(p).map(n=>n.textContent).join('');
  const escape = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const bytes = s => Uint8Array.from(atob(s),c=>c.charCodeAt(0));
  const base64 = b => { let s=''; for(let i=0;i<b.length;i+=8192) s+=String.fromCharCode(...b.subarray(i,i+8192)); return btoa(s); };
  const hash = async b => [...new Uint8Array(await crypto.subtle.digest('SHA-256',b))].map(x=>x.toString(16).padStart(2,'0')).join('');
  const safeName = name => {
    let n=String(name).replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/^[ .]+|[ .]+$/g,'').slice(0,100);
    assert(n && n!=='.' && n!=='..','文件名不能为空'); if(/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(n)) n='_'+n; return n;
  };
  const safePath = s => typeof s==='string' && !/^[\/]|^[a-z]:/i.test(s) && !s.includes('\\') && s.split('/').every(p=>p && p!=='.' && p!=='..' && !/[<>:"|?*\x00-\x1f]/.test(p));

  function integerCN(value, ordinary=false) {
    let n=BigInt(value); assert(n>=0n && n<10000000000000000n,'金额超出范围（小于一亿亿元）');
    const ds=ordinary?'零一二三四五六七八九':'零壹贰叁肆伍陆柒捌玖', us=ordinary?['','十','百','千']:['','拾','佰','仟'];
    if(!n) return '零'; const chunks=[]; while(n){chunks.push(Number(n%10000n));n/=10000n;} let out='',gap=false;
    for(let i=chunks.length-1;i>=0;i--){const v=chunks[i];if(!v){gap=!!out;continue;}if(out&&(gap||v<1000))out+='零';let part='',zero=false;
      for(let p=3;p>=0;p--){const d=Math.floor(v/10**p)%10;if(d){if(zero)part+='零';part+=ds[d]+us[p];zero=false;}else if(part)zero=true;}
      out+=part+['','万','亿','兆'][i];gap=false;
    } return ordinary?out.replace(/^一十/,'十'):out;
  }
  function money(input) {
    let s=String(input).trim().replace(/，/g,',').replace(/萬/g,'万');
    if(s.includes(',')) assert(/^\d{1,3}(,\d{3})+(\.\d+)?\s*万?元?整?$/.test(s),'千位分隔符格式错误');
    s=s.replace(/,/g,''); const m=/^(\d+)(?:\.(\d+))?\s*(万)?(?:元)?(?:整)?$/.exec(s); assert(m,'金额请填写数字，例如 2.5万元或 50000元');
    const f=m[2]||'', scale=10n**BigInt(f.length), raw=BigInt(m[1]+f)*(m[3]?1000000n:100n);
    assert(raw%scale===0n,'金额精度不能超过分');const cents=raw/scale,yuan=cents/100n,j=Number(cents/10n%10n),fen=Number(cents%10n);
    let upper=integerCN(yuan)+'元';if(!j&&!fen)upper+='整';else{if(j)upper+='零壹贰叁肆伍陆柒捌玖'[j]+'角';else if(yuan)upper+='零';if(fen)upper+='零壹贰叁肆伍陆柒捌玖'[fen]+'分';}
    return {upfront:upper,upfront_short:'¥'+yuan+(cents%100n?'.'+String(cents%100n).padStart(2,'0').replace(/0$/,''):''),cents:String(cents)};
  }
  /** 费率数字 → “百分之十五（15%）” */
  function rateText(r){const a=String(r).split('.');return '百分之'+integerCN(a[0],true)+(a[1]?'点'+[...a[1]].map(c=>'零一二三四五六七八九'[Number(c)]).join(''):'')+`（${r}%）`;}
  /** 结构化判断收费模式：有金额无费率→固定；有金额有费率→半风险；无金额有费率→全风险 */
  function probeFeeKind(desc) {
    const s=String(desc||'').trim().replace(/％/g,'%').replace(/萬/g,'万');
    const hasRate=/(\d+(?:\.\d+)?)\s*%/.test(s)||/百分之/.test(s);
    const rest=s.replace(/(\d+(?:\.\d+)?)\s*%/g,'').replace(/百分之[零〇一二两三四五六七八九十百点\d.]+/g,'');
    const hasAmount=/\d[\d,]*(?:\.\d+)?\s*万?元?/.test(rest);
    if(hasAmount&&hasRate)return 'semi_risk';
    if(!hasAmount&&hasRate)return 'pure_risk';
    if(hasAmount&&!hasRate)return 'fixed';
    return R.config.riskKeywords.some(k=>s.includes(k))?'semi_risk':'fixed';
  }
  function parseFee(input,type) {
    let s=String(input).trim().replace(/％/g,'%').replace(/萬/g,'万'), rate=null;
    const numeric=[...s.matchAll(/(\d+(?:\.\d+)?)\s*%/g)], chinese=[...s.matchAll(/百分之([零〇一二两三四五六七八九十百点\d.]+)/g)];
    assert(numeric.length+chinese.length<=1,'请只填写一个风险费率');
    if(numeric.length){rate=numeric[0][1];s=s.replace(numeric[0][0],'');}
    if(chinese.length){let v=chinese[0][1].replace(/两/g,'二').replace(/〇/g,'零'); if(/^\d+(\.\d+)?$/.test(v))rate=v;else{
      const a=v.split('点'); assert(a.length<=2,'中文百分比格式错误');let whole=-1;for(let i=0;i<=100;i++)if(integerCN(i,true)===a[0])whole=i;
      assert(whole>=0,'无法识别中文百分比');assert(!a[1]||/^[零一二三四五六七八九]+$/.test(a[1]),'小数百分比格式错误');
      rate=String(whole)+(a[1]?'.'+[...a[1]].map(c=>'零一二三四五六七八九'.indexOf(c)).join(''):'');
    }s=s.replace(chinese[0][0],'');}
    const amounts=s.match(/\d[\d,]*(?:\.\d+)?\s*万?元?/g)||[];
    assert(amounts.length<=1 && !/[-负]|结果|另付|后期\s*\d/.test(s),'请提供一个明确金额；多金额、分期或结果收费暂不支持自动生成');
    if(type==='pure_risk'){
      assert(!amounts.length,'全风险收费不填写前期金额，只填风险比例（例如 回款额的15%）');
      assert(rate!==null && Number(rate)>0 && Number(rate)<=100,'全风险收费需要 0 至 100 之间的费率');
      return {upfront:'零元整',upfront_short:'0',cents:'0',risk_rate:rateText(rate)};
    }
    assert(amounts.length===1,'请提供一个明确金额');
    const result=money(amounts[0]);result.risk_rate='百分之___（___%）';
    if(type==='semi_risk'){
      assert(rate!==null && Number(rate)>0 && Number(rate)<=100,'半风险收费需要前期金额和 0 至 100 之间的费率');
      result.risk_rate=rateText(rate);
    }else assert(rate===null && !/风险|回款|分成/.test(s),'固定收费（含刑事模板）不接受比例或结果收费');return result;
  }
  const choose = (v,map,auto) => { if(!v||v==='自动识别'||v==='auto') return auto();assert(Object.hasOwn(map,v),'无法识别选项：'+v);return map[v]; };
  function normalize(input,year=new Date().getFullYear()) {
    const p={};for(const f of R.config.fields)p[f.key]=String(input[f.key]??'').trim();const t=p.cause+' '+p.stage;
    const ct=choose(p.case_type,{'民商事':'civil','民事':'civil','商事':'civil','civil':'civil','刑事':'criminal','criminal':'criminal'},()=> t.includes('纠纷')&&!/刑事|涉嫌|辩护|侦查|审查起诉/.test(t)?'civil':R.config.criminalKeywords.some(k=>t.includes(k))?'criminal':'civil');
    const party=ct==='criminal'?'individual':choose(p.party_type,{'个人':'individual','公司':'company','individual':'individual','company':'company'},()=>R.config.companyKeywords.some(k=>p.plaintiff.includes(k))?'company':'individual');
    const fee=choose(p.fee_type,{'固定':'fixed','半风险':'semi_risk','全风险':'pure_risk','fixed':'fixed','semi_risk':'semi_risk','pure_risk':'pure_risk'},()=>ct==='criminal'?'fixed':probeFeeKind(p.fee_desc));
    assert(ct!=='criminal'||fee==='fixed','刑事模板只支持固定收费');
    if(ct==='criminal'&&!p.defendant)p.defendant=p.plaintiff;
    for(const k of ['plaintiff','defendant','cause','fee_desc','stage'])assert(p[k],R.config.fields.find(f=>f.key===k).label+'不能为空');
    for(const v of Object.values(p))assert(v.length<10000&&!/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v),'字段过长或含有不支持的控制字符');
    const stages=p.stage.replace(/阶段/g,'').split(/[、，,；;/]+/).map(x=>x.trim()).filter(Boolean);assert(stages.length,'代理阶段不能为空');
    if(ct==='criminal')for(const st of stages)assert(R.config.criminalStages.includes(st),'未知刑事阶段：'+st);
    const fi=parseFee(p.fee_desc,fee),cause=p.cause.replace(/纠纷$/,''), crime=p.cause.replace(/^涉嫌\s*/,'').replace(/罪$/,'')+'罪';
    const trimName=s=>{for(const x of ['有限责任公司','股份有限公司','有限公司','有限合伙'])s=s.split(x).join('');return [...s].slice(0,6).join('');};
    const label=ct==='criminal'?`${p.defendant}涉嫌${crime}一案`:`${trimName(p.plaintiff)}vs${trimName(p.defendant)} ${p.cause}`;
    const reps={PLAINTIFF:p.plaintiff,CLIENT:p.plaintiff,DEFENDANT:p.defendant,CAUSE:ct==='criminal'?crime:cause,CRIME:crime,YEAR:String(year),COURT:p.court||'______人民法院',DETENTION:p.detention||'______看守所',LEGAL_REP:p.legal_rep||'______',LEGAL_REP_POSITION:p.legal_rep_position||'______',UPFRONT_FEE:fi.upfront,UPFRONT_FEE_SHORT:fi.upfront_short.replace(/[¥￥]/g,''),RISK_RATE:fi.risk_rate,CASE_LABEL:label,DEFENDANT_CAUSE:`${p.defendant} ${cause}`,CASE_FULL:`${p.plaintiff}与${p.defendant} ${cause}纠纷`,FIRST_STAGE:stages[0]+'阶段',STAGE:ct==='criminal'?stages.map(s=>({'侦查':'①','审查起诉':'②','一审':'③','二审':'④','再审':'⑤','申诉':'申诉'}[s])).join(''):p.stage,STAGE_DESC:stages.at(-1)+(['侦查','审查起诉'].includes(stages.at(-1))?'阶段':'')+'终结'};
    return {input:p,case_type:ct,party_type:party,fee_type:fee,fee_info:fi,replacements:reps,group:ct==='criminal'?'刑事':(party==='company'?'公司委托':'个人委托'),caseName:safeName(ct==='criminal'?`${p.defendant}涉嫌${crime}`:`${p.plaintiff}vs${p.defendant} ${cause}纠纷`)};
  }

  async function openZip(data) {
    assert(data.byteLength<=50*1024*1024,'文件超过 50 MB');const z=await JSZip.loadAsync(data,{checkCRC32:true});const files=Object.values(z.files);assert(files.length<=5000,'压缩包文件数量过多');
    let size=0;for(const f of files){const original=f.unsafeOriginalName||f.name;assert(!original.split(/[\\/]/).includes('..')&&!/^[\/]|^[a-z]:/i.test(original),'压缩包包含非法路径');const fSize=f._data?.uncompressedSize??(f._data?.length??f._data?.byteLength??0);size+=fSize;assert(size<=150*1024*1024,'解压内容超过 150 MB');}
    return z;
  }
  async function checkPackage(z,kind='docx') {
    assert(z.file(kind==='docx'?'word/document.xml':'xl/workbook.xml'),`不是有效的 ${kind} 文件`);
    for(const f of Object.values(z.files)){
      assert(!/vbaProject|embeddings\/|externalLinks\/|activeX\//i.test(f.name),'文件包含宏、嵌入对象或外部链接：'+f.name);
      if(f.name.endsWith('.rels')){const d=xml(await f.async('string'));for(const e of [...d.getElementsByTagNameNS('*','Relationship')])assert(e.getAttribute('TargetMode')!=='External','文件包含外部资源引用：'+e.getAttribute('Target'));}
      if(f.name.endsWith('.xml')){const s=await f.async('string');xml(s);assert(!/macroEnabled|\bDDE(?:AUTO)?\b|\bINCLUDETEXT\b|\bINCLUDEPICTURE\b/i.test(s),'文件包含活动内容：'+f.name);}
    }
  }
  function replaceRange(p,start,end,value) {
    const ns=texts(p);let pos=0;const hits=[];for(const n of ns){const a=pos;pos+=n.textContent.length;if(a<end&&pos>start)hits.push({n,a});}
    if(!hits.length)return false;const first=hits[0],last=hits.at(-1),prefix=first.n.textContent.slice(0,start-first.a),suffix=last.n.textContent.slice(end-last.a);
    first.n.textContent=prefix+value+(first===last?suffix:'');first.n.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve');
    for(const h of hits.slice(1))h.n.textContent=h===last?suffix:'';return true;
  }
  function replaceInPara(p,map) {
    const s=ptext(p),keys=Object.keys(map).filter(Boolean).sort((a,b)=>b.length-a.length);if(!keys.length)return 0;
    const re=new RegExp(keys.map(k=>k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|'),'g');const ms=[...s.matchAll(re)];
    for(const m of ms.reverse())replaceRange(p,m.index,m.index+m[0].length,String(map[m[0]]));return ms.length;
  }
  async function transformDoc(data,action) {
    const z=await openZip(data);await checkPackage(z);const report=[];
    for(const f of Object.values(z.files))if(f.name.startsWith('word/')&&f.name.endsWith('.xml')){const d=xml(await f.async('string'));let changed=false;
      for(const [i,p] of els(d,'p').entries()){const before=serialize(p);action(p,report,`${f.name}:段落${i+1}`);if(before!==serialize(p))changed=true;}
      if(changed)z.file(f.name,serialize(d));
    }return {bytes:await z.generateAsync({type:'uint8array',compression:'DEFLATE'}),report};
  }
  async function inspectDoc(data) {
    const z=await openZip(data);await checkPackage(z);const paragraphs=[],fields=new Set(),locations=[];
    for(const f of Object.values(z.files))if(f.name.startsWith('word/')&&f.name.endsWith('.xml')){const d=xml(await f.async('string'));for(const [i,p] of els(d,'p').entries()){const s=ptext(p);paragraphs.push(s);for(const m of s.matchAll(/\{\{([^{}]+)\}\}/g)){fields.add(m[1]);locations.push({field:m[1],part:f.name,paragraph:i+1});}}}
    return {text:paragraphs.join('\n'),fields:[...fields],locations};
  }
  async function validateTemplate(t) {
    assert(t&&typeof t.base64==='string'&&typeof t.name==='string'&&/\.docx$/i.test(t.name),'模板信息不完整');assert(Object.keys(RETAINER_CONFIG.directories).length,'内置配置缺失');
    assert(['个人委托','公司委托','刑事'].includes(t.group),'未知模板分组');assert(['contract','auth','legalrep','letter','meeting_letter','checklist','extra'].includes(t.tag),'未知文书类型');
    const b=bytes(t.base64);assert(await hash(b)===t.sha256,'模板校验和不匹配：'+t.name);const info=await inspectDoc(b);
    const unknown=info.fields.filter(k=>!Object.hasOwn(R.config.placeholders,k));assert(!unknown.length,'未知占位符：'+unknown.join('、'));assert(info.fields.length,'模板中没有案件占位符');
    const required={contract:[['PLAINTIFF','CLIENT'],['DEFENDANT','DEFENDANT_CAUSE','CASE_FULL'],['STAGE']],auth:[['PLAINTIFF','CLIENT'],['DEFENDANT','DEFENDANT_CAUSE','CASE_FULL'],['STAGE','STAGE_DESC']],legalrep:[['PLAINTIFF'],['LEGAL_REP'],['LEGAL_REP_POSITION']],letter:[['PLAINTIFF'],['CASE_FULL'],['COURT'],['FIRST_STAGE']],meeting_letter:[['DEFENDANT'],['CRIME'],['DETENTION']],checklist:[['CASE_LABEL']],extra:[]};
    for(const alternatives of required[t.tag])assert(alternatives.some(k=>info.fields.includes(k)),`${t.name} 缺少必要字段：${alternatives.join(' 或 ')}`);
    if((t.group==='个人委托'||t.group==='公司委托')&&t.tag==='contract')assert(info.text.includes('本合同律师费约定如下')||(info.text.includes('甲乙双方协商确定')&&info.text.includes('收费模式')),`${t.name} 为民事委托合同，第六条须保留收费条款锚点（应含“甲乙双方协商确定”且含“收费模式”，或含“本合同律师费约定如下”）`);
    return info;
  }
  async function generate(normalized,templates) {
    assert(templates.length,'请至少选择一份文书');const files=[],checks=[];const used=new Set();
    for(const t of templates){const info=await validateTemplate(t);const map={};for(const [k,v] of Object.entries(normalized.replacements))map['{{'+k+'}}']=v;
      let src=bytes(t.base64);if(t.tag==='contract'&&normalized.case_type==='civil')src=(await swapFee(src,normalized.fee_type)).bytes;
      const filled=await transformDoc(src,p=>replaceInPara(p,map));const result=await inspectDoc(filled.bytes);assert(!result.fields.length&&!result.text.includes('{{'),'生成后存在残留占位符：'+t.name);
      for(const k of info.fields){const v=normalized.replacements[k];if(v)assert(result.text.includes(v),`文书缺少字段 ${k}：${t.name}`);}
      let name=safeName(t.name),i=1;while(used.has(name))name=safeName(t.name.replace(/\.docx$/,''))+` (${i++}).docx`;used.add(name);
      files.push({name,bytes:filled.bytes});checks.push({name,passed:true,fields:info.fields,sha256:await hash(filled.bytes)});
    }return {files,report:{success:true,version:VERSION,caseName:normalized.caseName,group:normalized.group,createdAt:new Date().toISOString(),checks},normalized};
  }
  async function caseZip(result,folders=false) {
    const z=new JSZip(),root=result.normalized.caseName+'/';if(folders)for(const d of R.config.directories[result.normalized.case_type])z.folder(root+d);
    for(const f of result.files)z.file(root+(folders?'01委托手续/':'')+f.name,f.bytes);z.file(root+'生成校验报告.json',JSON.stringify(result.report,null,2));return z.generateAsync({type:'uint8array',compression:'DEFLATE'});
  }
  function underlinePlaceholders(p) {
    for(const run of els(p,'r').filter(r=>nearest(r,'p')===p)){
      if([...run.children].some(c=>!['rPr','t','br','tab'].includes(c.localName)))continue;const s=els(run,'t').map(t=>t.textContent).join('');if(!s.includes('{{'))continue;
      const prop=[...run.children].find(c=>c.localName==='rPr');
      for(const child of [...run.children].filter(c=>c.localName!=='rPr')){
        const parts=child.localName==='t'?child.textContent.split(/(\{\{[^{}]+\}\})/).filter(Boolean):[null];
        for(const part of parts){const copy=run.cloneNode(false);if(prop)copy.append(prop.cloneNode(true));const node=child.cloneNode(true);if(part!==null){node.textContent=part;node.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve');}copy.append(node);
          if(part!==null&&/^\{\{/.test(part)){let rp=els(copy,'rPr')[0];if(!rp){rp=p.ownerDocument.createElementNS(W,'w:rPr');copy.prepend(rp);}for(const u of els(rp,'u'))u.remove();const u=p.ownerDocument.createElementNS(W,'w:u');u.setAttributeNS(W,'w:val','single');rp.append(u);}run.before(copy);
        }
      }run.remove();
    }
  }
  function applyRule(p,r) {
    const s=ptext(p);if(r.context&&!s.includes(r.context))return false;
    if(r.mode==='exact'){let n=0;for(const old of (Array.isArray(r.old)?r.old:[r.old]))n+=replaceInPara(p,{[old]:r.new});return !!n;}
    if(r.mode==='regex_replace'){const ms=[...s.matchAll(new RegExp(r.pattern,'g'))];for(const m of ms.reverse())replaceRange(p,m.index,m.index+m[0].length,r.new);return !!ms.length;}
    /* blank_suffix 为保留模式：当前 data/rules.json 未使用，保留以兼容自定义规则包 */
    const start=r.mode==='blank_suffix'?0:s.indexOf(r.prefix)+String(r.prefix||'').length;
    if(r.mode!=='blank_suffix'&&!s.includes(r.prefix))return false;let end=r.suffix?s.indexOf(r.suffix,start):s.length;if(end<start)return false;
    let pos=0;const spans=[];for(const n of texts(p)){const a=pos;pos+=n.textContent.length;const run=nearest(n,'r'),u=run&&els(run,'u')[0];if(!u||['none','0','false'].includes(u.getAttributeNS(W,'val')))continue;
      const l=Math.max(a,start),h=Math.min(pos,end);if(l<h){const v=n.textContent.slice(l-a,h-a);if(r.mode==='underline_after_prefix')spans.push({l,h,v});else for(const m of v.matchAll(/[\s_]+/g))spans.push({l:l+m.index,h:l+m.index+m[0].length,v:m[0]});}}
    if(!spans.length)return false;
    if(r.mode==='underline_after_prefix'){
      const span=spans.find(x=>x.v.trim()&&!x.v.includes('{{'))||spans.find(x=>!x.v.trim());if(!span)return false;return replaceRange(p,span.l,span.h,r.new);
    }
    const l=spans[0].l;let h=spans[0].h;for(const next of spans.slice(1)){if(s.slice(h,next.l).trim())break;h=next.h;}if(s.slice(l,h).includes('{{'))return false;
    return replaceRange(p,l,r.consumeSuffix&&h===end?end+r.suffix.length:h,r.new);
  }
  async function inject(data,group,tag) {
    const ct=group==='刑事'?'criminal':'civil',party=group==='公司委托'?'公司':group==='个人委托'?'个人':group,rules=R.rules.rules.filter(r=>(r.case==='all'||r.case===ct)&&(r.tag==='all'||r.tag===tag)&&(!r.party||r.party===party));
    const hit=new Set();const output=await transformDoc(data,(p,report,location)=>{rules.forEach((r,i)=>{if(applyRule(p,r)){hit.add(i);report.push({location,mode:r.mode,field:r.new});}});underlinePlaceholders(p);
      if(tag==='contract'&&ptext(p).includes('合同号')&&ptext(p).includes('粤连越深圳民字第')){let pr=[...p.children].find(c=>c.localName==='pPr');if(!pr){pr=p.ownerDocument.createElementNS(W,'w:pPr');p.prepend(pr);}let j=els(pr,'jc')[0];if(!j){j=p.ownerDocument.createElementNS(W,'w:jc');pr.append(j);}j.setAttributeNS(W,'w:val','right');}
    });output.report.push({rules:rules.length,matched:hit.size,unmatched:rules.filter((r,i)=>!hit.has(i)).map(r=>({mode:r.mode,context:r.context,new:r.new}))});return output;
  }
  async function clean(data) {
    return transformDoc(data,(p,report,location)=>{let current=null,count=0;for(const r of [...p.children]){
      if(r.localName!=='r'||[...r.children].some(c=>!['rPr','t'].includes(c.localName))){current=null;continue;}
      const prop=x=>{const pr=[...x.children].find(c=>c.localName==='rPr');return pr?serialize(pr):'';};
      if(current&&current.nextSibling===r&&prop(current)===prop(r)){for(const t of [...r.children].filter(c=>c.localName==='t'))current.append(t);r.remove();count++;}else current=r;
    }if(count)report.push({location,mergedRuns:count});});
  }
  async function swapFee(data,type) {
    const clauses=R.config.feeClauses[type];
    assert(Array.isArray(clauses)&&clauses.length,'未知收费类型');
    let found=false;
    const out=await transformDoc(data,(p,report,location)=>{const s=ptext(p);
      const isAnchor=(s.includes('甲乙双方协商确定')&&s.includes('收费模式'))||s.includes('本合同律师费约定如下');
      if(!isAnchor)return;
      assert(!found,'发现多处收费条款，请先整理模板');found=true;
      const old=[];for(let n=p.nextSibling;n&&n.nodeType===1;n=n.nextSibling){const t=n.localName==='p'?ptext(n):'';if(/^\s*(?:[1-9][.．、]|（[1-9]）)/.test(t))old.push(n);else if(!t.trim())continue;else break;}
      const pPr=[...p.children].find(c=>c.localName==='pPr');
      const firstRun=els(p,'r')[0];
      const rPr=firstRun&&[...firstRun.children].find(c=>c.localName==='rPr');
      const before=[s,...old.map(ptext)].join('\n');
      replaceRange(p,0,s.length,clauses[0]);
      for(const n of old)n.remove();
      let anchor=p;
      for(const text of clauses.slice(1)){
        const np=p.ownerDocument.createElementNS(W,'w:p');
        if(pPr)np.append(pPr.cloneNode(true));
        const nr=p.ownerDocument.createElementNS(W,'w:r');
        if(rPr)nr.append(rPr.cloneNode(true));
        const nt=p.ownerDocument.createElementNS(W,'w:t');
        nt.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve');
        nt.textContent=text;nr.append(nt);np.append(nr);
        anchor.after(np);anchor=np;underlinePlaceholders(np);
      }
      underlinePlaceholders(p);
      report.push({location,before,after:clauses.join('\n'),paragraphs:clauses.length});
    });
    assert(found,'未找到收费条款锚点（应含“甲乙双方协商确定”且含“收费模式”，或含“本合同律师费约定如下”）');
    return out;
  }
  const download=(data,name,type='application/octet-stream')=>{const url=URL.createObjectURL(new Blob([data],{type})),a=document.createElement('a');a.href=url;a.download=safeName(name);a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);};
  Object.assign(R,{assert,xml,serialize,els,texts,ptext,escape,bytes,base64,hash,clone,safeName,safePath,integerCN,money,parseFee,normalize,openZip,checkPackage,replaceRange,replaceInPara,transformDoc,inspectDoc,validateTemplate,generate,caseZip,applyRule,inject,clean,swapFee,download});return R;
})();
