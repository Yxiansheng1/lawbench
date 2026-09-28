"""Bounded ZIP extraction. Reject traversal, Windows ADS, symlinks and nested archives."""
from pathlib import Path, PurePosixPath
import zipfile, hashlib, shutil, tempfile, os, json
def expand_archives(root):
    root=Path(root).resolve()
    for archive in list(root.rglob('*')):
        if archive.suffix.lower()!='.zip' or any(p.startswith('_') for p in archive.relative_to(root).parts[:-1]): continue
        sha=hashlib.sha256(archive.read_bytes()).hexdigest();out=root/'解压'/('pdf-'+sha)
        marker=out/'_manifest.json'
        if marker.exists():
            entries=json.loads(marker.read_text(encoding='utf-8'))
            if all((out/n).is_file() and hashlib.sha256((out/n).read_bytes()).hexdigest()==h for n,h in entries.items()):continue
            raise ValueError('解压目录被修改：'+str(out))
        out.parent.mkdir(exist_ok=True)
        temp=Path(tempfile.mkdtemp(prefix='_unzip-',dir=out.parent))
        try:
            entries={}
            with zipfile.ZipFile(archive) as z:
                infos=z.infolist()
                if len(infos)>5000 or sum(i.file_size for i in infos)>512*1024*1024:raise ValueError('ZIP超过解压限额')
                seen=set()
                for i in infos:
                    path=PurePosixPath(i.filename.replace('\\','/'))
                    if path.is_absolute() or '..' in path.parts or any(':' in p or p.endswith((' ','.')) for p in path.parts):raise ValueError('ZIP非法路径')
                    if (i.external_attr>>16)&0o170000==0o120000:raise ValueError('ZIP含符号链接')
                    key=str(path).casefold()
                    if key in seen:raise ValueError('ZIP含重复路径')
                    seen.add(key)
                    if i.is_dir():continue
                    if path.suffix.lower()!='.pdf':continue
                    target=temp/str(path);target.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(i) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
                    entries[str(path)]=hashlib.sha256(target.read_bytes()).hexdigest()
            (temp/'_manifest.json').write_text(json.dumps(entries),encoding='utf-8');os.replace(temp,out)
        finally:
            if temp.exists():shutil.rmtree(temp)
