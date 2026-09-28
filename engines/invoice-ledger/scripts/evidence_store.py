"""Retain immutable source bytes and extraction records outside distribution assets."""
from pathlib import Path
import hashlib, json, os, uuid
from datetime import datetime

def preserve(ledger, source, fields, batch):
    raw = Path(source).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    root = Path(ledger)/'_原票';root.mkdir(parents=True, exist_ok=True)
    target = root/(digest + Path(source).suffix.lower())
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError('原票档案哈希不一致，停止写入')
    else:
        temp = root/(uuid.uuid4().hex+'.tmp');temp.write_bytes(raw);os.replace(temp,target)
    records = Path(ledger)/'_提取记录';records.mkdir(parents=True,exist_ok=True)
    record={'source':str(source),'sha256':digest,'batch':batch,'fields':fields,'at':datetime.now().isoformat()}
    (records/(uuid.uuid4().hex+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
