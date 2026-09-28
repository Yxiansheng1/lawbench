"""Buyer field verification and content-addressed evidence. Historical absence is not approval."""
from pathlib import Path
import re, json, hashlib, os, uuid
# 购买方名称不写死：解析顺序为 环境变量 INVOICE_BUYER → 技能根目录 buyer.json 的 "购买方名称"。
# 未配置时一律判「待核」并在原因中给出配置指引，绝不猜测、绝不放行。
BUYER_ENV='INVOICE_BUYER'
BUYER_CONFIG=Path(__file__).resolve().parent.parent/'buyer.json'
UNSET_BUYER='未配置购买方名称：请设置环境变量 INVOICE_BUYER，或在技能根目录 buyer.json 写入 {"购买方名称": "..."}'
# 购方列的取值截断点。除横排版式的「销售方/销方」外，数电票竖排版式把销方列写作「销 名称：」，
# compact 后成「销名称：」，必须一并截断，否则会把销方名称粘进购方值并误判为"抬头错误"。
BUYER_SPLIT=re.compile(r'(?:销售方|销方|销[ \t]*名称|纳税人识别号|统一社会信用代码|税号|地址|开户行|电话)')
def normalize(value):return re.sub(r'\s+','',str(value or '')).replace('(','（').replace(')','）')
def configured_buyer():
    """返回规范化后的已配置购买方名称；未配置返回空串。"""
    env=os.environ.get(BUYER_ENV)
    if env and env.strip():return normalize(env)
    try:data=json.loads(BUYER_CONFIG.read_text(encoding='utf-8'))
    except (OSError,ValueError):return ''
    return normalize(data.get('购买方名称') or '')
def parse_buyer(text,expected=None):
    # Only an explicitly labelled BUYER field/section qualifies. Never search for company anywhere.
    # 竖排表格版式（数电票，如 Suwell 转 OFD→PDF）把"购买方信息"拆行显示，标签实际呈现为「购 名称：」，
    # compact 后为「购名称：」，故标签允许 购买方/购方/购 三种写法。
    expected=configured_buyer() if expected is None else normalize(expected)
    compact=re.sub(r'(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])','',text)
    patterns=[r'(?m)^\s*(?:购买方|购方|购)\s*(?:名称|抬头)\s*[:：]\s*([^\r\n]+)',
              r'(?m)^\s*(?:购买方|购方|购)(?:信息)?\s*[:：]?\s*(?:\n\s*)?名称\s*[:：]\s*([^\r\n]+)']
    values=[]
    for pattern in patterns:
        for match in re.findall(pattern,compact):
            value=BUYER_SPLIT.split(match)[0].strip()
            if value:values.append(value)
    normalized={normalize(v) for v in values}
    if not expected:
        return {'购买方名称':values[0] if len(normalized)==1 else '','抬头核验':'待核','抬头原因':UNSET_BUYER}
    if len(normalized)!=1:return {'购买方名称':'','抬头核验':'待核','抬头原因':'购买方字段缺失或多个名称不一致'}
    value=values[0];ok=normalize(value)==expected
    return {'购买方名称':value,'抬头核验':'通过' if ok else '错误','抬头原因':'' if ok else '购买方与已配置的购买方名称不一致'}
def annotate(text,result,expected=None):
    result.update(parse_buyer(text,expected))
    result['材料类型']='辅助材料' if re.search(r'汇总单|行程单',text[:200]) else '发票'
    numbers=set(re.findall(r'发票号码\s*[:：]\s*(\d{8,20})(?!\d)',text))
    if len(numbers)>1:result['_identity_error']='一个PDF出现多个发票号码，需拆分核对'
    return result
def buyer_errors(fields,expected=None):
    expected=configured_buyer() if expected is None else normalize(expected)
    errors=[]
    if not expected:errors.append(UNSET_BUYER)
    elif fields.get('抬头核验')!='通过' or normalize(fields.get('购买方名称'))!=expected:
        errors.append('购买方抬头错误' if fields.get('抬头核验')=='错误' else '购买方抬头待核')
    if fields.get('材料类型')!='发票':errors.append('辅助材料不能作为明细发票')
    if fields.get('_identity_error'):errors.append(fields['_identity_error'])
    return errors
def fingerprint(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)
def proofs(ledger,number,amount,date):
    matches=[]
    for p in (Path(ledger)/'_提取记录').glob('*.json'):
        item=json.loads(p.read_text(encoding='utf-8'));f=item.get('fields',{})
        if (f.get('发票号码全号'),f.get('价税合计（元）'),f.get('开票日期'))!=(number,amount,date):continue
        if buyer_errors(f):continue
        if f.get('_ocr'):
            approval=Path(ledger)/'_人工核验'/(item['sha256']+'.json')
            if not approval.exists():continue
            a=json.loads(approval.read_text(encoding='utf-8'))
            if a.get('sha256')!=item['sha256'] or a.get('fields')!=f:continue
        candidates=list((Path(ledger)/'_原票').glob(item['sha256']+'.*'))
        if len(candidates)==1 and fingerprint(candidates[0])==item['sha256']:
            matches.append({**item,'archived':str(candidates[0])})
    return matches
def check_row(ledger,row):
    return bool(proofs(ledger,str(row[7]),str(row[3]),str(row[2])))
