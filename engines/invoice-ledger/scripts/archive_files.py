"""归档 PDF/图片/ZIP。逐项哈希校验，失败返回2；重试不复制同内容文件。"""
import sys, json, hashlib, shutil, argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import _deps
_deps.guard(__file__)
EXT={'.zip','.pdf','.png','.jpg','.jpeg','.bmp','.tif','.tiff'}
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def mapping_archive(workdir, raw_dir, mapping):
    root=Path(workdir).resolve();root.mkdir(parents=True,exist_ok=True)
    raw=Path(raw_dir); results=[]
    for item in mapping:
        try:
            dst=(root/item['dst']).resolve()
            if not dst.is_relative_to(root) or dst==root: raise ValueError('归档目标越界')
            matches=[p for p in raw.iterdir() if p.is_file() and p.name.startswith(item['tool']+'_') and p.suffix.lower() in EXT]
            if len(matches)!=1: raise ValueError(f'源匹配数量不是1：{len(matches)}')
            source=matches[0]
            if item.get('expect') and source.stat().st_size!=int(item['expect']): raise ValueError('附件大小不符')
            if dst.suffix.lower()!=source.suffix.lower(): raise ValueError('目标扩展名与原附件不一致')
            sha=digest(source);dst.parent.mkdir(parents=True,exist_ok=True)
            original=dst; n=2
            while dst.exists() and digest(dst)!=sha:
                dst=original.with_name(f'{original.stem}_{n}{original.suffix}');n+=1
            if not dst.exists():
                temp=dst.with_name(dst.name+'.part')
                with source.open('rb') as src, temp.open('xb') as out: shutil.copyfileobj(src,out)
                if digest(temp)!=sha: raise ValueError('复制后哈希不符')
                temp.replace(dst)
            results.append({'tool':item['tool'],'status':'OK','file':str(dst),'sha256':sha})
        except (OSError,ValueError,KeyError) as e: results.append({'tool':item.get('tool'),'status':'ERROR','reason':str(e)})
    from datetime import datetime
    logs=root/'_归档记录';logs.mkdir(exist_ok=True)
    (logs/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in results: print(json.dumps(r,ensure_ascii=False))
    return 2 if not results or any(r['status']!='OK' for r in results) else 0
def auto_archive(workdir,raw_dir):
    p=Path(workdir)/'待下载清单.tsv'
    if not p.exists(): print('[ERROR] 缺少待下载清单.tsv');return 2
    rows=[line.split('\t') for line in p.read_text(encoding='utf-8-sig').splitlines() if line and not line.startswith('#')]
    mapping=[]
    for f in Path(raw_dir).iterdir():
        if f.suffix.lower() not in EXT:continue
        matches=[r for r in rows if len(r)>=5 and f.name.endswith('_'+r[3])]
        if len(matches)!=1: print('[ERROR] 清单匹配不唯一：'+f.name);return 2
        r=matches[0];mapping.append({'tool':f.name[:-(len(r[3])+1)],'dst':str(Path(r[2])/(r[1]+'_'+r[3]))})
    return mapping_archive(workdir,raw_dir,mapping)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('workdir');p.add_argument('--raw',required=True);p.add_argument('--mapping');a=p.parse_args()
    return mapping_archive(a.workdir,a.raw,json.loads(Path(a.mapping).read_text(encoding='utf-8'))) if a.mapping else auto_archive(a.workdir,a.raw)
if __name__=='__main__':sys.exit(main())
