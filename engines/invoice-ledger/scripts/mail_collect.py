"""Read-only IMAP/EML collection and bounded public HTTP downloads; no send/mark-read operations."""
from pathlib import Path
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import hashlib,re,json,ssl,imaplib,getpass,urllib.request,urllib.parse,socket,ipaddress
from buyer_verification import atomic_json
MAX_BYTES=64*1024*1024
def safe_url(url):
    u=urllib.parse.urlsplit(url)
    if u.scheme not in ('https','http') or not u.hostname or u.username or u.password:raise ValueError('非法下载URL')
    addresses=socket.getaddrinfo(u.hostname,u.port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('拒绝非公网下载地址')
    return url
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        safe_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
class Links(HTMLParser):
    def __init__(self):super().__init__();self.items=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':self.current=[dict(attrs).get('href',''),'']
    def handle_data(self,data):
        if self.current is not None:self.current[1]+=data
    def handle_endtag(self,tag):
        if tag.lower()=='a' and self.current is not None:self.items.append(self.current);self.current=None
def links(text,base=''):
    parser=Links();parser.feed(text)
    found=[urllib.parse.urljoin(base,u) for u,label in parser.items if re.search(r'发票|下载|PDF',label,re.I) or re.search(r'\.pdf(?:\?|$)|invoice|fapiao|epiao|fp51|nnfp',u,re.I)]
    for line in re.sub(r'<[^>]+>',' ',text).splitlines():
        if re.search(r'发票|下载|PDF|票据|invoice|fapiao|epiao|fp51|nnfp',line,re.I) and not re.search(r'退订|unsubscribe',line,re.I):
            found += re.findall(r'https?://[^\s<>"\u3000]+',line)
    return sorted({u.rstrip('。，);') for u in found if u.startswith(('http://','https://'))})
def fetch_document(url,depth=0,seen=None):
    if depth>3:raise ValueError('跳转页超过限制，需要浏览器处理')
    seen=set() if seen is None else seen
    if url in seen:raise ValueError('链接循环')
    seen.add(url);safe_url(url)
    opener=urllib.request.build_opener(SafeRedirect())
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'InvoiceCollector/3.9'}),timeout=20) as response:
        data=response.read(MAX_BYTES+1);actual=response.geturl()
    if len(data)>MAX_BYTES:raise ValueError('下载文件过大')
    if data.startswith(b'%PDF-'):return data,'.pdf'
    if data.startswith(b'PK\x03\x04'):return data,'.zip'
    candidates=links(data.decode('utf-8',errors='replace'),actual)
    if len(candidates)==1:return fetch_document(candidates[0],depth+1,seen)
    raise ValueError('未取得PDF/ZIP：可能需登录、验证码或选择下载按钮，请用浏览器处理后绑定文件')
def digest(data):return hashlib.sha256(data).hexdigest()
def store(root,data,suffix):
    manifest=Path(root)/'collection.json'
    state=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    period=state.get('reimbursement_plan',{}).get('period')
    if period:
        from period_plan import require_plan
        period=require_plan(state)['period']
    directory=(Path(root)/period if period else Path(root))/'原始资料';directory.mkdir(parents=True,exist_ok=True)
    p=directory/(digest(data)+suffix.lower())
    if p.exists() and digest(p.read_bytes())!=digest(data):raise ValueError('原始资料哈希不符')
    if not p.exists():p.write_bytes(data)
    return str(p.relative_to(root))
def collect_eml(job,source_id,data,state):
    mail=BytesParser(policy=policy.default).parsebytes(data)
    key=source_id;messages=state.setdefault('messages',{})
    # Save immutable MIME source so a resumed job can always re-enumerate missing items.
    raw=store(job,data,'.eml');body=[]
    for part in mail.walk():
        if part.get_content_type() in ('text/plain','text/html') and part.get_content_disposition()!='attachment':
            try:body.append(part.get_content())
            except Exception:pass
    text='\n'.join(body);subject=str(mail.get('Subject',''))
    expected=re.search(r'(?:开具|共|包含|合计)\s*(\d+)\s*张(?:电子)?发票',text)
    messages[key]={'subject':subject,'date':str(mail.get('Date','')),'raw':raw,'expected_invoices':int(expected[1]) if expected else None,'enumerated':False}
    for i,part in enumerate(mail.walk()):
        name=part.get_filename()
        if not name:continue
        entry_id=digest((key+'|attachment|'+str(i)).encode());items=state.setdefault('items',{})
        if entry_id in items:continue
        record={'id':entry_id,'message':key,'kind':'attachment','name':name}
        suffix=Path(name).suffix.lower()
        if suffix not in ('.pdf','.zip'):record['status']='未选取';record['reason']='仅选择PDF和包含PDF的ZIP'
        else:
            raw=part.get_payload(decode=True) or b''
            if not raw or len(raw)>MAX_BYTES:record.update(status='下载失败',reason='附件为空或过大')
            elif not ((suffix=='.pdf' and raw.startswith(b'%PDF-')) or (suffix=='.zip' and raw.startswith(b'PK'))):record.update(status='下载失败',reason='附件内容与格式不符')
            else:record.update(status='已下载',path=store(job,raw,suffix),sha256=digest(raw))
        items[entry_id]=record
    if '发票' in subject+text:
        for url in links(text):
            entry_id=digest((key+'|link|'+url).encode())
            state.setdefault('items',{}).setdefault(entry_id,{'id':entry_id,'message':key,'kind':'link','url':url,'name':'正文链接','status':'待下载'})
    messages[key]['enumerated']=True
def download_links(job,state):
    for record in state.get('items',{}).values():
        if record['kind']!='link' or record['status'] not in ('待下载','需浏览器处理'):continue
        try:
            data,suffix=fetch_document(record['url']);record.update(status='已下载',path=store(job,data,suffix),sha256=digest(data))
            record.pop('reason',None)
        except Exception as e:record.update(status='需浏览器处理',reason=str(e))
        atomic_json(Path(job)/'collection.json',state)
def collect_imap(job,state,host,account,start,end,folder='INBOX'):
    # Password is entered only on this machine, never in config, arguments or logs.
    password=getpass.getpass('请输入邮箱IMAP授权码（不保存）：')
    conn=imaplib.IMAP4_SSL(host,993,ssl_context=ssl.create_default_context(),timeout=30)
    state['coverage']={'adapter':'imap','host':host,'folder':folder,'start':start,'end_exclusive':end,'complete':False,'limitation':'服务器返回范围；不证明服务器未隐藏历史邮件'}
    try:
        conn.login(account,password);password=None
        status,_=conn.select(folder,readonly=True)
        if status!='OK':raise ValueError('无法只读打开邮箱')
        from datetime import date
        a=date.fromisoformat(start);b=date.fromisoformat(end)
        if a>=b:raise ValueError('日期范围错误')
        months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        fmt=lambda d:f'{d.day:02d}-{months[d.month-1]}-{d.year}'
        status,reply=conn.uid('search',None,'SINCE',fmt(a),'BEFORE',fmt(b))
        if status!='OK':raise ValueError('邮件搜索失败')
        validity=conn.response('UIDVALIDITY')[1]
        if not validity or not validity[0]:raise ValueError('邮箱未返回UIDVALIDITY，不能可靠续跑')
        scope=host+'|'+account+'|'+folder+'|'+repr(validity)
        uids=reply[0].split();failures=[]
        state['coverage']['discovered_messages']=len(uids)
        for uid in uids:
            key=digest((scope+'|'+uid.decode()).encode())
            if state.get('messages',{}).get(key,{}).get('enumerated'):continue
            try:
                status,data=conn.uid('fetch',uid,'(BODY.PEEK[])')
                chunks=[x[1] for x in data if isinstance(x,tuple)]
                if status!='OK' or len(chunks)!=1:raise ValueError('邮件读取不完整')
                collect_eml(job,key,chunks[0],state)
            except Exception as e:failures.append({'uid':uid.decode(),'reason':str(e)})
            state['coverage']['failures']=failures;atomic_json(Path(job)/'collection.json',state)
        state['coverage'].update(complete=not failures,failures=failures)
    finally:
        atomic_json(Path(job)/'collection.json',state)
        try:conn.logout()
        except Exception:pass
