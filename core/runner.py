# Author: gorcoding
import re
from .http import Http
from .providers import make
from .store import Store
from . import dorks as dk

def run_fetch(ctl,req):
    cfg=ctl.cfg(); u=req["username"].strip().lstrip("@")
    if not re.fullmatch(r"\w{1,15}",u): raise ValueError("invalid username")
    st=Store(u); prov=make(cfg["provider"],Http(ctl),cfg)
    ctl.log(f"@{u}: fetching profile via {cfg['provider']}")
    prof=prov.profile(u); st.save("profile",prof)
    np_,nc,nf,ng=[max(0,int(req.get(k) or 0)) for k in ("posts","comments","followers","following")]
    posts,com=st.load("posts",{}),st.load("comments",{})
    ctl.log(f"cache: {len(posts)} posts, {len(com)} comments already stored - only new items will be added")
    def full(): return len(posts)>=np_ and len(com)>=nc
    def walk(since,until,stop_known,label):
        cur=None; ctl.log(label)
        while not ctl.stop and not full():
            items,cur=prov.timeline(prof,cur,since,until); known=0
            for it in items:
                if it["id"] in posts or it["id"] in com: known+=1; continue
                d,cap=(com,nc) if it["kind"]=="comment" else (posts,np_)
                if len(d)<cap: d[it["id"]]=it
            st.save("posts",posts); st.save("comments",com)
            ctl.progress.update(posts=len(posts),comments=len(com))
            ctl.log(f"page: {len(items)} items ({known} known) -> posts {len(posts)}/{np_}, comments {len(com)}/{nc}")
            if not items or not cur or (stop_known and known): break
    if (np_ or nc):
        ids=[int(i) for i in list(posts)+list(com)]
        if ids and not full(): walk(str(max(ids)),None,True,"checking for new items")
        if not full(): walk(None,str(min(ids)) if ids else None,False,"fetching older items")
    for kind,n,name in (("followers",nf,"followers"),("following",ng,"following")):
        if not n or ctl.stop: continue
        d=st.load(name,{}); cur=None; ctl.log(f"fetching {name} (target {n}, cached {len(d)})")
        while len(d)<n and not ctl.stop:
            items,cur=prov.relations(prof,kind,cur)
            for it in items: d.setdefault(it["username"],it)
            st.save(name,d); ctl.progress[name]=len(d); ctl.log(f"{name}: {len(d)}/{n}")
            if not items or not cur: break
        if cfg.get("deep_relations") and cfg["provider"]=="nitter":
            todo=[k for k,v in d.items() if not v.get("location") and not v.get("deep")][:n]
            ctl.log(f"deep mode: reading {len(todo)} {name} profiles (slow)")
            for i,k in enumerate(todo):
                if ctl.stop: break
                try: p=prov.profile(k); d[k].update(location=p["location"],bio=p["bio"] or d[k].get("bio"),deep=True)
                except Exception as e: d[k]["deep"]=True
                if i%10==9: st.save(name,d)
            st.save(name,d)
    ctl.log("done")

def run_dorks(ctl,u):
    cfg=ctl.cfg(); st=Store(u); http=Http(ctl,"dork_delay")
    posts=st.load("posts",{}) or {}
    qs=dk.build(posts,int(cfg["dork_max"]),cfg.get("dork_tlds",""))
    prev=st.load("dorks",{"results":[]}); done={r["query"] for r in prev["results"]}
    ctl.log(f"{len(qs)} dork queries (cached: {len(done)}). Delay {cfg['dork_delay']}s")
    for i,q in enumerate(qs):
        if ctl.stop: break
        if q["query"] in done: continue
        try: q["found"]=dk.search(http,q["query"])
        except Exception as e: ctl.log(f"search failed: {e}"); break
        prev["results"].append(q); st.save("dorks",prev)
        ctl.progress["dorks"]=f"{i+1}/{len(qs)}"; ctl.log(f"[{i+1}/{len(qs)}] {len(q['found'])} results")
