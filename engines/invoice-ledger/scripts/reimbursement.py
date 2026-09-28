"""Verified print batches. Reservations, immutable revisions and reimbursement journal share ledger lock."""
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import json,re,csv,hashlib,shutil,html
from buyer_verification import atomic_json,proofs,fingerprint
from ledger_lock import transaction_lock
def batches(ledger):
    return [json.loads(p.read_text(encoding='utf-8')) for p in (Path(ledger)/'_报销批次').glob('*.json')]
def assigned_numbers(ledger,exclude=None):
    return {m['number']:b['batch'] for b in batches(ledger) if b['batch']!=exclude and b['status'] in ('ready','paying','paid') for m in b['members']}
def batch_path(ledger,batch):
    if not re.fullmatch(r'[\w-]{1,80}',batch):raise ValueError('批次名只允许字母、数字、汉字、下划线或连字符，长度1-80')
    return Path(ledger)/'_报销批次'/(batch+'.json')
def read_batch(ledger,path):
    r=json.loads(Path(path).read_text(encoding='utf-8'))
    root=Path(ledger).resolve()
    relative=Path(r.get('folder_relative',str(Path('_打印包')/r['batch']/f'v{r["version"]:03d}')))
    folder=(root/relative).resolve()
    if not folder.is_relative_to(root/'_打印包'):raise ValueError('打印包路径越界')
    r['folder']=str(folder);return r
def db_open(ledger):
    import invoice_db as db
    db.LEDGER_DIR=Path(ledger);db.LEDGER_FILE=Path(ledger)/'发票主台账.xlsx'
    rows,cols=db._load_ledger();return db,rows,cols
def verified_row(ledger,row):
    evidence=proofs(ledger,str(row[7]),str(row[3]),str(row[2]))
    evidence=[p for p in evidence if p['fields'].get('发票类别')==row[1] and p['archived'].lower().endswith('.pdf')]
    if not evidence:raise ValueError('原票、抬头或分类核验缺失：'+str(row[7]))
    return evidence[-1]
def prepare(ledger,batch,numbers,replace=False,period=None):
    import pypdfium2 as pdfium
    import invoice_renamer
    with transaction_lock(ledger):
        path=batch_path(ledger,batch);old=read_batch(ledger,path) if path.exists() else None
        if period:
            from period_plan import make_plan
            make_plan(period,'local',history='exclude')
        if old and old.get('reimbursement_period')!=period:raise ValueError('不可改写原批次的报销月份；先取消旧批次，再按已确认的新月份建批次')
        if old and old['status'] in ('paid','paying'):raise ValueError('已报或报销提交中的批次不可重建')
        if old and not replace:raise ValueError('批次已存在；重印使用reprint，修订须显式--replace')
        if not numbers or len(numbers)!=len(set(numbers)):raise ValueError('必须选择非空且不重复的票号清单')
        db,rows,cols=db_open(ledger);gate=db.ledger_gate(rows,cols,db.EXCLUDED_FROM_TOTAL)
        if gate:raise ValueError('台账完整性检查未通过：'+str(gate[:3]))
        available=assigned_numbers(ledger,exclude=batch);chosen=[]
        for number in numbers:
            if number in available:raise ValueError('发票已分配到批次：'+available[number])
            matches=[r for r in rows if str(r[7])==number and r[8] not in db.EXCLUDED_FROM_TOTAL]
            if len(matches)!=1 or matches[0][8]!='未报':raise ValueError('发票不是唯一的未报记录：'+number)
            row=matches[0]
            if Decimal(str(row[3]))<=0:raise ValueError('红字或零金额不得进入普通贴票包')
            evidence=verified_row(ledger,row);chosen.append((row,evidence))
        order={r['name']:i for i,r in enumerate(invoice_renamer.CATEGORY_RULES)}
        chosen.sort(key=lambda x:(order.get(x[0][1],999),x[0][2],x[0][7]))
        version=(old['version']+1) if old else 1
        folder=(Path(ledger)/'_打印包'/period/batch if period else Path(ledger)/'_打印包'/batch)/f'v{version:03d}'
        if folder.exists():
            # An interrupted build may leave an unregistered folder. Keep it as evidence, use next version.
            while folder.exists():version+=1;folder=folder.with_name(f'v{version:03d}')
        folder.mkdir(parents=True)
        merged=pdfium.PdfDocument.new();members=[];page_number=1;categories={}
        try:
            for seq,(row,ev) in enumerate(chosen,1):
                name=f'{seq:03d}_{row[1]}_{row[2]}_{row[3]}_{row[7]}.pdf'
                dest=folder/row[1]/name;dest.parent.mkdir(exist_ok=True);shutil.copy2(ev['archived'],dest)
                source=pdfium.PdfDocument(str(dest))
                try:
                    count=len(source)
                    if not count:raise ValueError('空PDF')
                    merged.import_pages(source)
                finally:source.close()
                members.append({'seq':seq,'number':str(row[7]),'category':row[1],'date':row[2],'amount':str(row[3]),'ledger_snapshot':list(row),'source_sha256':ev['sha256'],'file':str(dest.relative_to(folder)),'start_page':page_number,'end_page':page_number+count-1})
                page_number+=count;categories[row[1]]=categories.get(row[1],Decimal(0))+Decimal(str(row[3]))
            pdf=folder/'贴票打印.pdf';merged.save(str(pdf))
        finally:merged.close()
        reread=pdfium.PdfDocument(str(pdf))
        try:
            if len(reread)!=page_number-1:raise ValueError('合并PDF页数不符')
        finally:reread.close()
        with (folder/'贴票顺序清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['贴票序号','类别','日期','金额','发票号码（文本）','起始页','结束页'])
            for m in members:w.writerow([m['seq'],m['category'],m['date'],m['amount'],"'"+m['number'],m['start_page'],m['end_page']])
            for c,a in categories.items():w.writerow(['分类小计',c,'',str(a)])
            w.writerow(['合计','','',str(sum(categories.values(),Decimal(0)))])
        table=''.join('<tr>'+''.join('<td>'+html.escape(str(m[k]))+'</td>' for k in ['seq','category','date','amount','number','start_page','end_page'])+'</tr>' for m in members)
        (folder/'贴票清单.html').write_text('<!doctype html><meta charset="utf-8"><title>贴票清单</title><style>body{font:14px sans-serif}td,th{padding:8px;border:1px solid #aaa}table{border-collapse:collapse}</style><h1>'+html.escape(batch)+f' / 第{version}版</h1><p>购买方：广东连越（深圳）律师事务所。打印不等于已报销。</p><table><tr><th>序号</th><th>类别</th><th>日期</th><th>金额</th><th>票号</th><th>起页</th><th>末页</th></tr>'+table+'</table><p>合计：'+str(sum(categories.values(),Decimal(0)))+'元</p>',encoding='utf-8')
        record={'schema':1,'batch':batch,'version':version,'status':'ready','created_at':datetime.now().isoformat(),'folder':str(folder),'members':members,'categories':{c:str(a) for c,a in categories.items()},'total':str(sum(categories.values(),Decimal(0))),'page_count':page_number-1}
        record['folder_relative']=str(folder.relative_to(Path(ledger)))
        record['reimbursement_period']=period
        record['artifacts']={str(p.relative_to(folder)):fingerprint(p) for p in folder.rglob('*') if p.is_file()}
        if old:
            history=path.parent/'历史';history.mkdir(exist_ok=True);atomic_json(history/(batch+f'-v{old["version"]}.json'),{**old,'status':'superseded'})
        atomic_json(path,record)
        if old:(Path(old['folder'])/'旧版作废.txt').write_text('此打印包已被新版本替代；请勿混用。',encoding='utf-8')
        return record
def check_artifacts(record):
    root=Path(record['folder'])
    for name,sha in record['artifacts'].items():
        p=root/name
        if not p.is_file() or fingerprint(p)!=sha:raise ValueError('打印包文件缺失或改变：'+name)
def reprint(ledger,batch):
    with transaction_lock(ledger):
        record=read_batch(ledger,batch_path(ledger,batch))
        if record['status'] not in ('ready','paid'):raise ValueError('批次当前不可打印')
        check_artifacts(record)
        db,rows,cols=db_open(ledger)
        for m in record['members']:
            selected=[r for r in rows if str(r[7])==m['number'] and r[8] not in db.EXCLUDED_FROM_TOTAL]
            expected='已报' if record['status']=='paid' else '未报'
            if len(selected)!=1 or selected[0][8]!=expected or list(selected[0][:8])!=m['ledger_snapshot'][:8]:raise ValueError('台账已变化，原打印包不可重印')
            verified_row(ledger,selected[0])
        return record
def reimburse(ledger,batch,apply=False):
    with transaction_lock(ledger):
        path=batch_path(ledger,batch);record=read_batch(ledger,path);db,rows,cols=db_open(ledger)
        if record['status']=='paid':return record
        if record['status'] not in ('ready','paying'):raise ValueError('批次不可确认报销')
        check_artifacts(record)
        selected=[]
        for m in record['members']:
            matches=[r for r in rows if str(r[7])==m['number'] and r[8] not in db.EXCLUDED_FROM_TOTAL]
            if len(matches)!=1:raise ValueError('台账票据不存在、重复或已冻结')
            row=matches[0]
            if list(row[:8])!=m['ledger_snapshot'][:8]:raise ValueError('台账字段变化，需重新生成批次')
            if row[8] not in (('未报','已报') if record['status']=='paying' else ('未报',)):raise ValueError('发票已报或不可报销')
            ev=verified_row(ledger,row)
            if ev['sha256']!=m['source_sha256']:raise ValueError('原票证据发生变化')
            selected.append(row)
        if db.ledger_gate(rows,cols,db.EXCLUDED_FROM_TOTAL):raise ValueError('台账完整性失败')
        if not apply:return {**record,'dry_run':True}
        record['status']='paying';atomic_json(path,record)
        for row in selected:row[8]='已报'
        if db._save_ledger(rows)<0:raise RuntimeError('台账写入失败；保留paying日志，重试同批次恢复')
        record.update(status='paid',paid_at=datetime.now().isoformat());atomic_json(path,record);return record
def cancel(ledger,batch):
    with transaction_lock(ledger):
        path=batch_path(ledger,batch);r=read_batch(ledger,path)
        if r['status'] in ('paying','paid'):raise ValueError('不能取消已报或提交中的批次')
        r['status']='cancelled';atomic_json(path,r)
        (Path(r['folder'])/'旧版作废.txt').write_text('批次已取消，不可用于报销。',encoding='utf-8')
        return r
