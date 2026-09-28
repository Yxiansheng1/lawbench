'use strict';
(() => {
 const R=Retainer,S='http://schemas.openxmlformats.org/spreadsheetml/2006/main',REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships';
 const colIndex=s=>[...s].reduce((a,c)=>a*26+c.charCodeAt(0)-64,0)-1;
 const colName=i=>{let s='';for(i++;i;i=Math.floor((i-1)/26))s=String.fromCharCode(65+(i-1)%26)+s;return s;};
 async function readXlsx(data) {
  const z=await R.openZip(data);await R.checkPackage(z,'xlsx');const book=R.xml(await z.file('xl/workbook.xml').async('string'));
  const relFile=z.file('xl/_rels/workbook.xml.rels');R.assert(relFile,'Excel 缺少工作表关联');const rels=R.xml(await relFile.async('string')),targets={};
  for(const e of [...rels.getElementsByTagNameNS('*','Relationship')]){const path=e.getAttribute('Target');R.assert(!/^[a-z]+:/i.test(path),'不读取外部工作表');let p=path.startsWith('/')?path.slice(1):'xl/'+path;const normalized=[];for(const bit of p.split('/')){if(bit==='..')normalized.pop();else if(bit!=='.')normalized.push(bit);}p=normalized.join('/');R.assert(p.startsWith('xl/'),'工作表路径错误');targets[e.getAttribute('Id')]=p;}
  const ss=z.file('xl/sharedStrings.xml'),shared=ss?R.els(R.xml(await ss.async('string')),'si',S).map(si=>R.els(si,'t',S).map(x=>x.textContent).join('')):[];
  const stylesFile=z.file('xl/styles.xml'),formats={};let xfs=[];
  if(stylesFile){const d=R.xml(await stylesFile.async('string'));for(const e of R.els(d,'numFmt',S))formats[e.getAttribute('numFmtId')]=e.getAttribute('formatCode');const x=R.els(d,'cellXfs',S)[0];if(x)xfs=[...x.children].map(e=>formats[e.getAttribute('numFmtId')]||'');}
  const sheets=[];for(const sheet of R.els(book,'sheet',S)){
   const path=targets[sheet.getAttributeNS(REL,'id')],f=z.file(path||'');R.assert(f,'工作表文件不存在：'+sheet.getAttribute('name'));const d=R.xml(await f.async('string')),rows=[];
   for(const row of R.els(d,'row',S)){const index=Number(row.getAttribute('r'))-1;R.assert(Number.isInteger(index)&&index>=0&&index<100000,'工作表行号超过支持范围');const cells=[];
    for(const c of R.els(row,'c',S)){const ref=c.getAttribute('r')||'',m=/^([A-Z]+)[0-9]+$/.exec(ref);R.assert(m,'Excel 单元格地址错误');const ci=colIndex(m[1]);R.assert(ci<512,'工作表列数超过 512');const typ=c.getAttribute('t'),v=R.els(c,'v',S)[0]?.textContent||'',formula=R.els(c,'f',S).length>0;
     let value=typ==='s'?shared[Number(v)]??'':typ==='inlineStr'?R.els(c,'t',S).map(t=>t.textContent).join(''):v;
     if((!typ||typ==='n')&&/^0+$/.test(xfs[Number(c.getAttribute('s'))]||'')&&/^\d+$/.test(value))value=value.padStart(xfs[Number(c.getAttribute('s'))].length,'0');
     cells[ci]={value:String(value),formula,error:typ==='e',ref};
    }rows[index]=cells;
   }sheets.push({name:sheet.getAttribute('name'),rows});
  }R.assert(sheets.length,'Excel 中没有工作表');return {sheets};
 }
 const canonical=s=>String(s??'').normalize('NFKC').toLowerCase().replace(/[\s_\-／/（）()]/g,'');
 function autoMapping(headers){const mapping={},conflicts=[];for(const f of R.config.fields){const names=[f.label,f.key,...f.aliases].map(canonical),hits=[];headers.forEach((h,i)=>{if(names.includes(canonical(h)))hits.push(i);});if(hits.length===1)mapping[f.key]=hits[0];else{mapping[f.key]='';if(hits.length>1)conflicts.push(f.label+'对应多个表头');}}return {mapping,conflicts};}
 function mapRows(sheet,headerRow,mapping){const cols=Object.values(mapping).filter(x=>x!==''&&x!=null).map(Number);R.assert(new Set(cols).size===cols.length,'同一 Excel 列不能同时映射到多个字段');
  const result=[];for(let i=headerRow+1;i<sheet.rows.length;i++){const cells=sheet.rows[i];if(!cells||!cells.some(c=>c?.value))continue;const row={},issues=[],invalidFields={};
   for(const f of R.config.fields){const ci=mapping[f.key],c=ci!==''&&ci!=null?cells[Number(ci)]:null;row[f.key]=c?.value||'';if(c?.formula)issues.push(`${c.ref} 含公式，请先在 Excel 中复制并粘贴为值`);if(c?.error)issues.push(`${c.ref} 含错误值`);}
   for(const f of R.config.fields){const ci=mapping[f.key],c=ci!==''&&ci!=null?cells[Number(ci)]:null;if(c?.formula||c?.error)invalidFields[f.key]=issues.filter(x=>x.startsWith(c.ref+' '));}
   if(Object.values(row).some(Boolean))result.push({row,sourceRow:i+1,issues,invalidFields});
  }return result;
 }
 async function makeXlsx(sheets) {
  const z=new JSZip(),e=R.escape;z.file('[Content_Types].xml',`<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets.map((s,i)=>`<Override PartName="/xl/worksheets/sheet${i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')}</Types>`);
  z.file('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="'+REL+'/officeDocument" Target="xl/workbook.xml"/></Relationships>');
  z.file('xl/workbook.xml',`<workbook xmlns="${S}" xmlns:r="${REL}"><sheets>${sheets.map((s,i)=>`<sheet name="${e(s.name)}" sheetId="${i+1}" r:id="rId${i+1}"/>`).join('')}</sheets></workbook>`);
  z.file('xl/_rels/workbook.xml.rels',`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((s,i)=>`<Relationship Id="rId${i+1}" Type="${REL}/worksheet" Target="worksheets/sheet${i+1}.xml"/>`).join('')}<Relationship Id="styles" Type="${REL}/styles" Target="styles.xml"/></Relationships>`);
  z.file('xl/styles.xml',`<styleSheet xmlns="${S}"><fonts count="2"><font><sz val="11"/><name val="微软雅黑"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="微软雅黑"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF233E3B"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"><alignment vertical="center" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`);
  sheets.forEach((s,si)=>{const rows=s.rows.map((row,ri)=>`<row r="${ri+1}" ht="${ri===0?34:30}" customHeight="1">${row.map((v,ci)=>typeof v==='number'?`<c r="${colName(ci)}${ri+1}" s="2"><v>${v}</v></c>`:`<c r="${colName(ci)}${ri+1}" s="${ri===0?1:0}" t="inlineStr"><is><t xml:space="preserve">${e(v??'')}</t></is></c>`).join('')}</row>`).join('');
   const n=Math.max(...s.rows.map(r=>r.length));const validations=s.input?R.config.fields.flatMap((f,i)=>f.options?[`<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="${colName(i)}2:${colName(i)}5001"><formula1>"${e(f.options.join(','))}"</formula1></dataValidation>`]:[]):[];
   z.file(`xl/worksheets/sheet${si+1}.xml`,`<worksheet xmlns="${S}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${Array.from({length:n},(_,i)=>`<col min="${i+1}" max="${i+1}" width="${s.name==='填写说明'?(i===0?25:90):i===3||i===4?28:22}" customWidth="1"/>`).join('')}</cols><sheetData>${rows}</sheetData>${s.input?`<autoFilter ref="A1:${colName(n-1)}${Math.max(2,s.rows.length)}"/>`:''}${validations.length?`<dataValidations count="${validations.length}">${validations.join('')}</dataValidations>`:''}</worksheet>`);
  });return z.generateAsync({type:'uint8array',compression:'DEFLATE'});
 }
 async function standardXlsx(){const h=R.config.fields.map(f=>f.label);return makeXlsx([
  {name:'案件录入',input:true,rows:[h,Array(h.length).fill('')]},
  {name:'填写说明',rows:[['字段/事项','填写方式'],['基本流程','在“案件录入”每行填写一个案件。HTML 导入后选择一案生成。'],['必填','委托方、对方/当事人、案由/罪名、律师费、代理阶段。刑事当事人留空时与委托人相同。'],['律师费','固定：50000元、2.5万元。半风险：前期2万+12.5%。多金额、分期及结果收费暂不支持。'],['阶段','多个阶段用顿号分隔，如一审、二审、执行；刑事可填侦查、审查起诉、一审、二审、申诉、再审。'],['可选字段','法院、监管场所、法定代表人及职务可留空，生成时保留填写位置。'],['文本与公式','姓名、编号等保存为文本。不要填写公式；已有公式请粘贴为值。'],['自有表','导入时选择工作表和表头行；确认或手工调整字段映射。'],['示例','“示例勿作正式案件”工作表仅用于试用，不是待办理案件。']]},
  {name:'示例勿作正式案件',input:true,rows:[h,['民商事','个人','示例张三','示例李四','买卖合同纠纷',25000,'固定','一审','示例人民法院','','',''],['民商事','公司','示例科技有限公司','示例商贸有限公司','服务合同纠纷','前期2万+12.5%','半风险','一审、二审','','','示例王五','经理'],['刑事','个人','示例家属','示例当事人','集资诈骗',50000,'固定','侦查、审查起诉','','示例看守所','','']]}
 ]);}
 Object.assign(R,{readXlsx,autoMapping,mapRows,makeXlsx,standardXlsx,colName});
})();
