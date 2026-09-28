"""Isolated runtime regression: no modification of the installed skill, ledger or cache."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SK = Path(__file__).resolve().parents[2]

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    work = Path(tempfile.mkdtemp(prefix="invoice-runtime-test-"))
    skill = work / "技能 with spaces"
    shutil.copytree(SK, skill, ignore=shutil.ignore_patterns("__pycache__", "env", "_日志", "_备份", "_候选台账"))
    cache = work / "cache"
    env = dict(os.environ, INVOICE_RUNTIME_CACHE=str(cache), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("INVOICE_RUNTIME_HOPS", None)
    baseline = digest(SK / "发票主台账.xlsx")
    checks = []

    def cmd(script, *args):
        path = skill / "scripts" / script
        code = "import sys,runpy;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_path(sys.argv[0],run_name='__main__')"
        return [sys.executable,"-B","-c",code,str(path.parent),str(path),*args]

    def run(script, *args):
        return subprocess.run(cmd(script,*args),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)

    def check(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ")+name+(": "+detail[-500:] if not ok else ""),flush=True)
        checks.append(ok)

    def runtime():
        lock=json.loads((skill/"vendor/env.lock").read_text(encoding="utf-8"))
        base=cache/"win-amd64"/lock["zip"]["sha256"]
        active=json.loads((base/"active.json").read_text())
        return base/active["generation"]

    r=run("env_check.py","--deep")
    check("read-only cold diagnosis",r.returncode==0 and not cache.exists(),r.stdout+r.stderr)
    initial_lock=json.loads((skill/"vendor/env.lock").read_text(encoding="utf-8"))
    stale=cache/"win-amd64"/initial_lock["zip"]["sha256"]/".build-interrupted"
    stale.mkdir(parents=True);(stale/"partial").write_text("interrupted")
    jobs=[subprocess.Popen(cmd("invoke.py","invoice_db.py","report"),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
    outputs=[j.communicate(timeout=60) for j in jobs]
    check("concurrent cold start",all(j.returncode==0 for j in jobs),repr(outputs))
    first=runtime()
    check("interrupted build is ignored without deleting another process files",stale.exists() and first!=stale)
    check("one published generation",len(list(first.parent.glob("gen-*")))==1)
    r=run("invoice_db.py","report")
    check("direct entry reuses cache",r.returncode==0 and runtime()==first and "[ENV]" not in r.stdout,r.stdout+r.stderr)
    marker=skill/"scripts/probe_exit.py"
    marker.write_text("import sys;sys.exit(2)",encoding="utf-8")
    r=run("invoke.py","probe_exit.py")
    check("exit code 2 preserved",r.returncode==2)
    victim=first/"Lib/site-packages/openpyxl/__init__.py"
    victim.unlink()
    r=run("invoke.py","invoice_db.py","report")
    check("missing dependency rebuilds",r.returncode==0 and runtime()!=first and first.exists(),r.stdout+r.stderr)
    current=runtime()
    victim=current/"Lib/site-packages/openpyxl/__init__.py"
    old=victim.read_bytes(); victim.write_bytes(b"!"+old[1:])
    snap=(current/"ready.json").stat().st_mtime_ns
    r=run("env_check.py","--deep")
    check("deep check detects same-size corruption without repair",r.returncode==1 and runtime()==current and (current/"ready.json").stat().st_mtime_ns==snap)
    r=run("runtime_cache.py","--repair")
    check("explicit repair publishes fresh generation",r.returncode==0 and runtime()!=current,r.stdout+r.stderr)
    lockfile=skill/"vendor/env.lock"; original=lockfile.read_bytes()
    lockfile.write_text("{}",encoding="utf-8")
    r=run("invoke.py","invoice_db.py","report")
    check("invalid lock fails closed",r.returncode==1 and "总记录" not in r.stdout)
    lockfile.write_bytes(original)
    stable=runtime()
    invalid=json.loads(original);invalid["manifest_sha256"]="0"*64
    lockfile.write_text(json.dumps(invalid),encoding="utf-8")
    r=run("invoke.py","invoice_db.py","report")
    check("failed build preserves published pointer",r.returncode==1 and runtime()==stable and stable.exists())
    lockfile.write_bytes(original)
    r=run("invoke.py","invoice_db.py","report")
    check("valid environment remains usable after failed build",r.returncode==0)
    archive=skill/"vendor/env-win_amd64.zip"
    with open(archive,"ab") as f:f.write(b"tamper")
    r=run("invoke.py","invoice_db.py","report")
    check("archive mismatch fails closed even with warm cache",r.returncode==1)
    with open(archive,"r+b") as f:f.truncate(archive.stat().st_size-6)
    # A valid repack changes ZIP identity but keeps dependencies and manifest unchanged.
    lock=json.loads(original)
    with zipfile.ZipFile(archive,"a") as z:z.comment=b"new-environment-identity"
    lock["zip"]["sha256"]=digest(archive);lock["zip"]["size"]=archive.stat().st_size
    lockfile.write_text(json.dumps(lock),encoding="utf-8")
    previous=runtime() if (cache/"win-amd64"/lock["zip"]["sha256"]/"active.json").exists() else None
    r=run("invoke.py","invoice_db.py","report")
    check("new archive identity automatically selects new cache",r.returncode==0 and previous is None and runtime().parent.name==lock["zip"]["sha256"],r.stdout+r.stderr)
    old_skill=skill; skill=work/"迁移后的技能"; old_skill.rename(skill)
    r=run("invoke.py","invoice_db.py","report")
    check("skill relocation works with shared cache",r.returncode==0,r.stdout+r.stderr)
    pollution=skill/"vendor/env";pollution.mkdir();(pollution/"stale.txt").write_text("stale")
    (skill/"_日志").mkdir(exist_ok=True);(skill/"_日志/private.txt").write_text("private")
    r=run("package_skill.py","--out",str(work/"release.zip"))
    ok=False
    if r.returncode==0:
        with zipfile.ZipFile(work/"release.zip") as z:
            ok=not any(n.startswith(("vendor/env/","_日志/")) or n=="发票主台账.xlsx" for n in z.namelist())
    check("package excludes cache logs and private ledger",ok,r.stdout+r.stderr)
    check("real ledger SHA256 unchanged",digest(SK/"发票主台账.xlsx")==baseline)
    print(f"RESULT {sum(checks)}/{len(checks)}; isolated artifacts: {work}")
    return 0 if all(checks) else 1

if __name__=="__main__":
    sys.exit(main())
