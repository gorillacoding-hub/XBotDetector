# Author: gorcoding
# Browse / export / delete saved profiles (data/<username>/). Only touches validated folders under data/.
import json, re, shutil, time
from . import store

NAME=re.compile(r"^\w{1,15}$"); PARTS={"posts","comments","followers","following","dorks","analysis","ai","about"}

def _dir(u):
    if not NAME.match(str(u)): return None
    d=store.ROOT/u
    return d if d.is_dir() and d.resolve().parent==store.ROOT.resolve() else None

def overview():
    out=[]
    if not store.ROOT.exists(): return out
    for d in sorted(store.ROOT.iterdir(),key=lambda p:p.name.lower()):
        if not d.is_dir() or not NAME.match(d.name): continue
        files=[f for f in d.glob("*.json")]; st=store.Store(d.name)
        a=st.load("analysis",{}) or {}; p=st.load("profile",{}) or {}
        out.append({"username":d.name,"name":p.get("name",""),"posts":len(st.load("posts",{}) or {}),"comments":len(st.load("comments",{}) or {}),
            "followers":len(st.load("followers",{}) or {}),"following":len(st.load("following",{}) or {}),
            "bytes":sum(f.stat().st_size for f in files),"updated":max([f.stat().st_mtime for f in files] or [0]),
            "verdict":a.get("verdict"),"scores":a.get("scores"),"ai":(d/"ai.json").exists()})
    return out

def delete(users):
    gone=[]
    for u in users:
        d=_dir(u)
        if d: shutil.rmtree(d,ignore_errors=True); gone.append(u)
    return gone

def delete_all():
    return delete([d.name for d in store.ROOT.iterdir() if d.is_dir() and NAME.match(d.name)]) if store.ROOT.exists() else []

def delete_parts(u,parts):
    d=_dir(u)
    if not d: return []
    done=[]
    for p in parts:
        if p in PARTS and (d/f"{p}.json").exists(): (d/f"{p}.json").unlink(); done.append(p)
    return done

def export(u):
    d=_dir(u)
    if not d: return None
    st=store.Store(u); ex=store.ROOT/"exports"; ex.mkdir(exist_ok=True)
    data={k:st.load(k) for k in ("profile","analysis","posts","comments","followers","following","dorks","ai","about")}
    p=ex/f"{u}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(data,ensure_ascii=False,indent=1),encoding="utf-8")
    return str(p.relative_to(store.ROOT.parent))
