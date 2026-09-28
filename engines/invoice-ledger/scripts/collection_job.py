"""Durable collection manifest. Every discovered object has a terminal or pending disposition."""
from pathlib import Path
from decimal import Decimal
import json,zipfile,hashlib,csv,subprocess,sys
from buyer_verification import atomic_json,buyer_errors
from invoice_integrity import admission_errors
from mail_collect import store,digest
def load(job):
    p=Path(job)/'collection.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'schema':1,'items':{},'messages':{},'coverage':{'adapter':'local','complete':False,'limitation':'仅本地输入，未验收真实邮箱'}}
def save(job,state):atomic_json(Path(job)/'collection.json',state)
def add_local(job,state,source):
    source=Path(source);files=[source] if source.is_file() else sorted(source.rglob('*'))
    for p in files:
        if not p.is_file():continue
        data=p.read_bytes();key=digest((str(p.resolve())+'|'+digest(data)).encode())
        if key in state['items']:continue
        rec={'id':key,'kind':'local','name':p.name,'source':str(p),'message':''}
        if p.suffix.lower() not in ('.pdf','.zip'):rec.update(status='未选取',reason='仅选择PDF和ZIP')
        elif not (data.startswith(b'%PDF-') or data.startswith(b'PK')):rec.update(status='下载失败',reason='文件魔数不匹配')
        else:rec.update(status='已下载',path=store(job,data,p.suffix),sha256=digest(data))
        state['items'][key]=rec
    save(job,state)
def expand(job,state):
    for parent in list(state['items'].values()):
        if parent.get('status')!='已下载' or not parent.get('path','').lower().endswith('.zip'):continue
        try:
            with zipfile.ZipFile(Path(job)/parent['path']) as z:
                infos=z.infolist()
                if len(infos)>5000 or sum(i.file_size for i in infos)>512*1024*1024:raise ValueError('压缩包超过安全限额')
                for n,i in enumerate(infos):
                    if i.is_dir():continue
                    key=digest((parent['id']+'|zip|'+str(n)).encode())
                    if key in state['items']:continue
                    child={'id':key,'parent':parent['id'],'message':parent.get('message',''),'kind':'zip-entry','name':i.filename}
                    if Path(i.filename).suffix.lower()!='.pdf':child.update(status='未选取',reason='ZIP仅选择PDF')
                    elif i.flag_bits&1:child.update(status='待处理',reason='加密PDF条目')
                    elif (i.external_attr>>16)&0o170000==0o120000:child.update(status='待处理',reason='拒绝符号链接条目')
                    else:
                        # Original member paths are metadata only; bytes are stored under SHA256 names.
                        raw=z.read(i)
                        if not raw.startswith(b'%PDF-'):child.update(status='待处理',reason='PDF内容非法')
                        else:child.update(status='已下载',path=store(job,raw,'.pdf'),sha256=digest(raw))
                    state['items'][key]=child
            parent['status']='已展开'
        except Exception as e:parent.update(status='待处理',reason='ZIP处理失败：'+str(e))
    save(job,state)
def analyze(job,state,ledger):
    import extract_fields as fields
    import invoice_db as db
    from evidence_store import preserve
    from ledger_lock import transaction_lock
    from buyer_verification import proofs
    root=Path(ledger);db.LEDGER_DIR=root;db.LEDGER_FILE=root/'发票主台账.xlsx'
    with transaction_lock(root):
        rows,columns=db._load_ledger();full,triple=db._build_index(rows,columns)
        groups={}
        for item in state['items'].values():
            if item.get('manual_exclusion'):
                item.update(status='人工排除',reason=item['manual_exclusion']['reason']);continue
            if not item.get('path','').lower().endswith('.pdf'):continue
            path=Path(job)/item['path']
            if not path.exists() or digest(path.read_bytes())!=item.get('sha256'):item.update(status='待处理',reason='原文件缺失或改变');continue
            try:r=fields.extract_from_pdf(str(path))
            except Exception as e:item.update(status='待核',reason=str(e));continue
            item['fields']=r;preserve(root,path,r,state.get('batch','收集'))
            if r.get('材料类型')=='辅助材料':item.update(status='辅助材料',reason='汇总单或行程单');continue
            problems=admission_errors(r,db.CATEGORY_WHITELIST)+buyer_errors(r)
            if r.get('_extract_error'):problems.append(r['_extract_error'])
            if problems:item.update(status='抬头错误' if r.get('抬头核验')=='错误' and not r.get('_ocr') else '待核',reason='；'.join(problems));continue
            if r.get('_ocr') and not proofs(root,r['发票号码全号'],r['价税合计（元）'],r['开票日期']):item.update(status='待核',reason='OCR需人工确认');continue
            if Decimal(r['价税合计（元）'])<0:item.update(status='红字待核',reason='单独处理红字票');continue
            number=r['发票号码全号'];groups.setdefault(number,[]).append(item)
        for number,items in groups.items():
            signatures={(i['fields']['价税合计（元）'],i['fields']['开票日期'],i['fields']['发票类别']) for i in items}
            if len(signatures)>1:
                for i in items:i.update(status='冲突',reason='本批同号关键字段不同')
                continue
            item=items[0];r=item['fields'];kind,_,reason,_=db.classify_incoming(number,r['发票号码后五位'],r['价税合计（元）'],r['开票日期'],full,triple)
            existing=full.get(number)
            if kind=='conflict':item.update(status='冲突',reason=reason)
            elif existing:
                st=existing['status']
                if st=='已报':item.update(status='历史已报',reason='不得重复报销')
                elif st=='未报':item.update(status='历史未报',reason='复用原台账记录')
                else:item.update(status='待核',reason='历史状态：'+st)
            elif kind=='dup':item.update(status='待核',reason=reason)
            else:item.update(status='可入账',reason='核验通过')
            for duplicate in items[1:]:duplicate.update(status='重复',reason='与本批'+item['id']+'同票',duplicate_of=item['id'])
    reconcile(job,state);save(job,state)
def reconcile(job,state):
    status={}
    for item in state['items'].values():status[item['status']]=status.get(item['status'],0)+1
    discrepancies=[]
    for key,msg in state['messages'].items():
        eligible=[i for i in state['items'].values() if i.get('message')==key and i.get('fields',{}).get('材料类型')=='发票' and i['fields'].get('发票号码全号')]
        unique={i['fields']['发票号码全号'] for i in eligible}
        msg['pdf_invoice_files']=len(eligible);msg['unique_invoices']=len(unique)
        if msg.get('expected_invoices') is not None and len(unique)!=msg['expected_invoices']:discrepancies.append({'message':key,'expected':msg['expected_invoices'],'actual':len(unique)})
    pending={'已下载','待下载','需浏览器处理','下载失败','待处理','待核','冲突','红字待核'}
    state['reconciliation']={'total_objects':len(state['items']),'statuses':status,'count_discrepancies':discrepancies,'processing_complete':not discrepancies and not any(i['status'] in pending for i in state['items'].values()),'mailbox_scope_complete':bool(state['coverage'].get('complete'))}
    admitted={i['fields']['发票号码全号']:Decimal(i['fields']['价税合计（元）']) for i in state['items'].values() if i.get('admitted_this_job')}
    historical={i['fields']['发票号码全号']:Decimal(i['fields']['价税合计（元）']) for i in state['items'].values() if i['status']=='历史未报' and not i.get('admitted_this_job')}
    eligible={i['fields']['发票号码全号']:Decimal(i['fields']['价税合计（元）']) for i in state['items'].values() if i['status']=='历史未报'}
    state['reconciliation'].update(new_recorded_amount=str(sum(admitted.values(),Decimal(0))),historical_unpaid_amount=str(sum(historical.values(),Decimal(0))),eligible_unpaid_amount=str(sum(eligible.values(),Decimal(0))))
    if state.get('reimbursement_plan'):
        from period_plan import require_plan,selected_numbers
        plan=require_plan(state)
        state['reconciliation'].update(reimbursement_plan=plan,selected_numbers=selected_numbers(state),historical_unpaid_not_automatically_selected=True)
    with (Path(job)/'收集对账表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['记录ID','邮件ID','父记录','文件或链接','状态','原因','票号','购买方','日期','金额','类别'])
        for i in state['items'].values():
            r=i.get('fields',{});values=[i['id'],i.get('message',''),i.get('parent',''),i.get('name',''),i['status'],i.get('reason',''),r.get('发票号码全号',''),r.get('购买方名称',''),r.get('开票日期',''),r.get('价税合计（元）',''),r.get('发票类别','')]
            w.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@')) else v for v in values])
def import_ready(job,state,ledger):
    analyze(job,state,ledger)
    candidates=[i for i in state['items'].values() if i['status']=='可入账']
    for i in candidates:
        p=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('invoice_db.py')),'import','--src',str(Path(job)/i['path']),'--ledger',str(ledger),'--batch',state.get('batch','收集')],capture_output=True,text=True,encoding='utf-8',errors='replace')
        logs=Path(job)/'运行日志';logs.mkdir(exist_ok=True);(logs/(i['id']+'.txt')).write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
        if p.returncode not in (0,2):i.update(status='待处理',reason='入账失败，见运行日志');save(job,state);return 2
        if p.returncode==0:i['admitted_this_job']=True
    analyze(job,state,ledger)
    return 0 if state['reconciliation']['processing_complete'] else 2
