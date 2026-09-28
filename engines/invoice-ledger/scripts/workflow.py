"""收集→核验→入账→贴票批次→确认报销。默认不连接邮箱、不确认报销。"""
import sys,argparse,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import _deps
_deps.guard(__file__)
from buyer_verification import atomic_json,buyer_errors
from collection_job import load,save,add_local,expand,analyze,import_ready,reconcile
from mail_collect import collect_eml,collect_imap,download_links,store,digest
from ledger_lock import transaction_lock
import reimbursement as rb
from period_plan import make_plan,require_plan,selected_numbers,scoped_batch

def _has_link_items(state):
    """是否存在正文链接项。只有解析邮件正文的适配器（EML/IMAP）才会产生 kind=='link'；
    MCP已下载文件与本地目录来源不解析正文，故恒为 False。"""
    return any(v.get('kind')=='link' for v in state.get('items',{}).values())

def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('history');p.add_argument('--ledger',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('plan');p.add_argument('--job',required=True);p.add_argument('--period',required=True);p.add_argument('--channel',required=True,choices=['local','eml','imap','mcp']);p.add_argument('--start');p.add_argument('--end');p.add_argument('--history',required=True,choices=['exclude','selected']);p.add_argument('--history-numbers',help='用户逐张确认实际未报并同意纳入本期的完整票号JSON数组')
    p=sub.add_parser('run');p.add_argument('--job',required=True);p.add_argument('--batch',required=True);p.add_argument('--ledger',required=True);p.add_argument('--src');p.add_argument('--eml');p.add_argument('--download-links',action='store_true')
    p=sub.add_parser('collect');p.add_argument('--job',required=True);p.add_argument('--batch',required=True);p.add_argument('--src');p.add_argument('--eml');p.add_argument('--imap-host');p.add_argument('--account');p.add_argument('--start');p.add_argument('--end');p.add_argument('--folder',default='INBOX');p.add_argument('--download-links',action='store_true')
    p=sub.add_parser('attach');p.add_argument('--job',required=True);p.add_argument('--item',required=True);p.add_argument('--file',required=True)
    p=sub.add_parser('exclude');p.add_argument('--job',required=True);p.add_argument('--item',required=True);p.add_argument('--reason',required=True);p.add_argument('--reviewer',required=True);p.add_argument('--confirm',action='store_true')
    for cmd in ('analyze','import'):
        p=sub.add_parser(cmd);p.add_argument('--job',required=True);p.add_argument('--ledger',required=True)
    p=sub.add_parser('prepare');p.add_argument('--ledger',required=True);p.add_argument('--batch',required=True);p.add_argument('--job');p.add_argument('--period',help='直接指定票号时必须确认报销YYYY-MM');p.add_argument('--numbers',help='用户逐张确认实际未报且纳入本期的完整票号JSON数组');p.add_argument('--replace',action='store_true')
    for cmd in ('reprint','reimburse','cancel'):
        p=sub.add_parser(cmd);p.add_argument('--ledger',required=True);p.add_argument('--batch',required=True)
        if cmd in ('reimburse','cancel'):p.add_argument('--apply',action='store_true')
    p=sub.add_parser('review');p.add_argument('--ledger',required=True);p.add_argument('--sha256',required=True);p.add_argument('--reviewer',required=True);p.add_argument('--confirm',action='store_true')
    a=ap.parse_args()
    if a.command=='history':
        with transaction_lock(a.ledger):
            db,rows,cols=rb.db_open(a.ledger);assigned=rb.assigned_numbers(a.ledger);candidates=[]
            for row in rows:
                if row[8]!='未报':continue
                try:rb.verified_row(a.ledger,row);evidence=True
                except ValueError:evidence=False
                candidates.append({'number':str(row[7]),'date':row[2],'amount':str(row[3]),'category':row[1],'source_batch':row[6],'reserved_batch':assigned.get(str(row[7])),'evidence_verified':evidence,'actual_unreimbursed_confirmed':False})
        out=Path(a.out)
        if out.exists():raise ValueError('清单文件已存在，请另选输出路径')
        atomic_json(out,{'note':'未报仅为台账标记；逐张核实实际未报并确认是否纳入本期。缺少原票或已预占的票据不能直接纳入。','candidates':candidates})
        print('历史候选清单：'+str(out));return 0
    if a.command=='plan':
        numbers=json.loads(Path(a.history_numbers).read_text(encoding='utf-8')) if a.history_numbers else []
        plan=make_plan(a.period,a.channel,a.start,a.end,a.history,numbers)
        with transaction_lock(a.job):
            state=load(a.job)
            if state.get('reimbursement_plan') not in (None,plan):raise ValueError('任务已确认的年月或范围不可改写；请另建任务，原批次需先取消后再分配')
            if state.get('items') and not state.get('reimbursement_plan'):raise ValueError('旧任务不得推定报销月份；另建有明确计划的任务后复用原资料')
            state['reimbursement_plan']=plan;save(a.job,state)
        print(json.dumps(plan,ensure_ascii=False,indent=2));return 0
    if a.command=='run':
        import subprocess
        plan=require_plan(load(a.job));a.batch=scoped_batch(plan['period'],a.batch)
        if not a.src and not a.eml:raise ValueError('run需要本地src或eml；真实邮箱先collect完成只读收集')
        steps=[['collect','--job',a.job,'--batch',a.batch],['import','--job',a.job,'--ledger',a.ledger],['prepare','--job',a.job,'--ledger',a.ledger,'--batch',a.batch]]
        if a.src:steps[0]+=['--src',a.src]
        if a.eml:steps[0]+=['--eml',a.eml]
        if a.download_links:steps[0]+=['--download-links']
        for index,step in enumerate(steps):
            if index==2 and rb.batch_path(a.ledger,a.batch).exists():
                state=load(a.job);record=rb.read_batch(a.ledger,rb.batch_path(a.ledger,a.batch))
                selected=set(selected_numbers(state))
                if record['status']=='ready' and selected=={m['number'] for m in record['members']}:
                    print(json.dumps(rb.reprint(a.ledger,a.batch),ensure_ascii=False,indent=2));return 0
                raise ValueError('已有批次与当前结果不同，需明确prepare --replace或另建批次')
            result=subprocess.run([sys.executable,'-B',__file__,*step])
            if result.returncode and not (index==0 and result.returncode==2):return result.returncode
        return 0
    if a.command=='collect':
        job=Path(a.job).resolve();job.mkdir(parents=True,exist_ok=True)
        if not any((a.src,a.eml,a.imap_host,a.download_links)):raise ValueError('请指定本地资料、EML、IMAP或重试链接')
        with transaction_lock(job):
            state=load(job)
            plan=require_plan(state);a.batch=scoped_batch(plan['period'],a.batch)
            if a.imap_host:
                if plan['channel']!='imap' or (a.start,a.end)!=(plan['mail_start'],plan['mail_end_exclusive']):raise ValueError('实际IMAP日期必须与事先确认的搜索范围一致')
            if a.eml and plan['channel']!='eml':raise ValueError('EML来源与已确认渠道不同')
            if a.src and plan['channel'] not in ('local','mcp'):raise ValueError('本地资料来源与已确认渠道不同')
            if state.get('batch') and state['batch']!=a.batch:raise ValueError('同一任务不能改变批次名')
            state['batch']=a.batch
            if a.src:
                src=Path(a.src).resolve()
                if src==job or job.is_relative_to(src) or src.is_relative_to(job):raise ValueError('源目录与任务目录必须分开')
                add_local(job,state,src)
                if plan['channel']=='mcp':
                    # 该渠道只接收已下载的附件文件，不解析邮件正文，因此不存在 kind=='link' 项：
                    # “仅正文链接、无附件”的发票天然不在覆盖范围内，须如实标注而非留白。
                    state['coverage']={'adapter':'mcp-export','complete':False,
                        'body_link_coverage':'covered' if _has_link_items(state) else 'not_covered',
                        'limitation':'仅接收连接器已下载的附件文件；本渠道不解析邮件正文，'
                                     '“仅正文链接、无附件”的发票不在覆盖范围内，须另经只读IMAP/EML收集，'
                                     '或在邮箱内手工取得后用 attach 绑定。服务器可达窗口以实际枚举为准，'
                                     '不得因本次未取到而宣称更早邮件无发票。'}
            if a.eml:
                for p in sorted(Path(a.eml).glob('*.eml')):collect_eml(job,'eml:'+digest(p.read_bytes()),p.read_bytes(),state)
                state['coverage']={'adapter':'eml','complete':False,'limitation':'仅导出的邮件文件，未验收真实邮箱范围'}
            if a.imap_host:
                if not all((a.account,a.start,a.end)):raise ValueError('IMAP需account/start/end；授权码仅本机交互输入')
                collect_imap(job,state,a.imap_host,a.account,a.start,a.end,a.folder)
            save(job,state)
            if a.download_links:
                if not _has_link_items(state):print('[WARN] 本来源不产生正文链接项（MCP已下载文件/本地目录不解析邮件正文），--download-links 在本任务无实际作用；仅正文链接的发票须另经只读IMAP/EML收集或在邮箱内手工取得后补入。',file=sys.stderr)
                download_links(job,state)
            expand(job,state);reconcile(job,state);save(job,state)
            print(json.dumps(state['reconciliation'],ensure_ascii=False,indent=2));return 0 if state['reconciliation']['processing_complete'] else 2
    if a.command=='attach':
        job=Path(a.job)
        with transaction_lock(job):
            state=load(job);item=state['items'][a.item]
            if item['kind']!='link':raise ValueError('只能绑定正文下载链接')
            raw=Path(a.file).read_bytes()
            suffix='.pdf' if raw.startswith(b'%PDF-') else '.zip' if raw.startswith(b'PK') else None
            if suffix is None:raise ValueError('浏览器下载结果不是PDF/ZIP')
            item.update(status='已下载',path=store(job,raw,suffix),sha256=digest(raw),browser_bound=True);item.pop('reason',None)
            expand(job,state);reconcile(job,state);save(job,state)
        return 0
    if a.command=='exclude':
        if not a.confirm or not a.reason.strip() or not a.reviewer.strip():raise ValueError('人工排除须明确理由、核验人及confirm')
        with transaction_lock(a.job):
            from datetime import datetime
            state=load(a.job);item=state['items'][a.item]
            item['manual_exclusion']={'reason':a.reason,'reviewer':a.reviewer,'at':datetime.now().isoformat()}
            item.update(status='人工排除',reason=a.reason);reconcile(a.job,state);save(a.job,state)
        return 0
    if a.command in ('analyze','import'):
        job=Path(a.job)
        with transaction_lock(job):
            state=load(job);require_plan(state);expand(job,state)
            if a.command=='import':rc=import_ready(job,state,a.ledger)
            else:analyze(job,state,a.ledger);rc=0 if state['reconciliation']['processing_complete'] else 2
            print(json.dumps(state['reconciliation'],ensure_ascii=False,indent=2));return rc
    if a.command=='prepare':
        if bool(a.job)==bool(a.numbers):raise ValueError('指定job或numbers之一')
        if a.job:
            with transaction_lock(a.job):
                state=load(a.job);plan=require_plan(state);analyze(a.job,state,a.ledger)
                if not state['reconciliation']['processing_complete']:raise ValueError('收集任务有待处理或数量不符项；先处理或另建明确范围任务')
                numbers=selected_numbers(state)
                if any(i['status']=='可入账' for i in state['items'].values()):raise ValueError('存在未入账发票，请先import')
        else:
            numbers=json.loads(Path(a.numbers).read_text(encoding='utf-8'))
            plan=make_plan(a.period,'local',history='selected',numbers=numbers)
        a.batch=scoped_batch(plan['period'],a.batch)
        record=rb.prepare(a.ledger,a.batch,numbers,a.replace,period=plan['period']);print(json.dumps(record,ensure_ascii=False,indent=2));return 0
    if a.command in ('reprint','reimburse','cancel'):
        if a.command=='cancel' and not a.apply:raise ValueError('取消打印批次须加--apply')
        result=rb.reprint(a.ledger,a.batch) if a.command=='reprint' else rb.reimburse(a.ledger,a.batch,a.apply) if a.command=='reimburse' else rb.cancel(a.ledger,a.batch)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    if a.command=='review':
        if not a.confirm or not a.reviewer.strip():raise ValueError('逐张核对原票后，填写reviewer并加--confirm')
        with transaction_lock(a.ledger):
            records=[json.loads(p.read_text(encoding='utf-8')) for p in (Path(a.ledger)/'_提取记录').glob('*.json')]
            records=[r for r in records if r.get('sha256')==a.sha256]
            if not records:raise ValueError('无对应原票提取记录')
            r=records[-1];fields=r['fields']
            from invoice_integrity import admission_errors
            if buyer_errors(fields) or admission_errors(fields):raise ValueError('字段错误不能通过简单确认放行，需修正识别并重新核验')
            from buyer_verification import fingerprint
            originals=list((Path(a.ledger)/'_原票').glob(a.sha256+'.*'))
            if len(originals)!=1 or fingerprint(originals[0])!=a.sha256:raise ValueError('原票缺失或哈希改变，不能确认')
            from datetime import datetime
            atomic_json(Path(a.ledger)/'_人工核验'/(a.sha256+'.json'),{'sha256':a.sha256,'fields':fields,'reviewer':a.reviewer,'at':datetime.now().isoformat()})
            db,rows,cols=rb.db_open(a.ledger)
            changed=False
            for row in rows:
                if row[7]==fields['发票号码全号'] and row[3]==fields['价税合计（元）'] and row[2]==fields['开票日期'] and row[8]=='⚠OCR待人工':
                    from decimal import Decimal
                    row[8]='红冲' if Decimal(str(row[3]))<0 else '未报';changed=True
            if changed:db._save_ledger(rows)
        print('人工核验已记录，请重新分析任务。');return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('[BLOCKED]',type(e).__name__,str(e));sys.exit(1 if len(sys.argv)>1 and sys.argv[1]=='collect' else 2)
