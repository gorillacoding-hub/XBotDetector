# Author: gorcoding
# Bridge: receives structured, validated public records from the Android X browser companion and feeds them into
# the storage + analysis pipeline (core.store / core.analyze). Runs automatic multi-step plans
# (profile -> posts -> replies -> followers -> following -> next profile / next search) and switches page when a limit is reached.
# Never receives, stores or logs credentials or session data.
import json, os, random, re, secrets, threading, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from . import store
from .store import Store
from . import analyze as an
from .version import VERSION

UNAME=re.compile(r"^\w{1,15}$"); IDRX=re.compile(r"^\d{5,25}$")
AUTHS={"logged_in","logged_out","unknown"}; PAGES={"search","profile","other"}
CHAL={"captcha","verification","rate_limit","locked","error"}
SECRET_MARKERS=("auth_token","ct0=")
CTRL=re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
STALL={"profile":25,"search":60,"posts":60,"replies":60,"followers":60,"following":60}   # seconds without progress => next step

def get_token():
    store.ROOT.mkdir(parents=True,exist_ok=True); p=store.ROOT/".bridge_token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(24))
        try: os.chmod(p,0o600)
        except OSError: pass
    return p.read_text().strip()

def resolve_user(u):
    """Case-insensitive match to an existing data folder so 'Alice' and 'alice' share one folder."""
    low=u.lower()
    if store.ROOT.exists():
        for d in store.ROOT.iterdir():
            if d.is_dir() and d.name.lower()==low: return d.name
    return u

def search_url(q,sort="top"):
    return "https://x.com/search?q="+quote(q,safe="")+"&src=typed_query"+("&f=live" if sort=="live" else "")

def step_url(st,sort="top"):
    t=st["target"]; k=st["kind"]
    return {"profile":f"https://x.com/{t}","posts":f"https://x.com/{t}","replies":f"https://x.com/{t}/with_replies",
            "followers":f"https://x.com/{t}/followers","following":f"https://x.com/{t}/following"}.get(k) or search_url(t,sort)

def _int(v,lo=0,hi=10**11):
    return int(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and lo<=v<=hi else None

def parse_names(v):
    items=re.split(r"[\s,;]+",v) if isinstance(v,str) else (v if isinstance(v,list) else [])
    out=[]; seen=set()
    for x in items:
        x=str(x).strip()
        m=re.search(r"(?:x|twitter)\.com/(\w{1,15})",x)
        x=(m.group(1) if m else x).lstrip("@")
        if UNAME.match(x) and x.lower() not in seen: seen.add(x.lower()); out.append(x)
    return out[:25]

def parse_lines(v):
    lines=v.splitlines() if isinstance(v,str) else (v if isinstance(v,list) else [])
    return [str(l).strip() for l in lines if str(l).strip() and len(str(l).strip())<=512][:10]

def validate(r):
    """Return a clean post record or None. Unknown keys are ignored."""
    if not isinstance(r,dict): return None
    try:
        pid=str(r.get("id","")); u=str(r.get("username",""))
        if not IDRX.match(pid) or not UNAME.match(u) or not isinstance(r.get("text"),str): return None
        if any(m in json.dumps(r).lower() for m in SECRET_MARKERS): return None
        t=an.ts(r.get("ts")); now=datetime.now(timezone.utc)
        if not t or t<datetime(2006,3,1,tzinfo=timezone.utc) or t>now+timedelta(days=1): return None
        av=str(r.get("avatar") or ""); lang=str(r.get("lang") or "")
        return {"id":pid,"username":u,"name":CTRL.sub("",str(r.get("name") or ""))[:80],"text":CTRL.sub("",r["text"])[:5000],
            "ts":t.astimezone(timezone.utc).isoformat(),"kind":"comment" if r.get("kind")=="comment" else "post",
            "verified":r.get("verified") is True,"avatar":av if av.startswith("https://pbs.twimg.com/") and len(av)<300 else "",
            "lang":lang if re.fullmatch(r"[A-Za-z-]{2,8}",lang) else None,"replies":_int(r.get("replies")),
            "reposts":_int(r.get("reposts")),"likes":_int(r.get("likes")),"views":_int(r.get("views"))}
    except Exception:
        return None

def validate_user(r):
    if not isinstance(r,dict) or not UNAME.match(str(r.get("username",""))): return None
    if any(m in json.dumps(r).lower() for m in SECRET_MARKERS): return None
    return {"username":r["username"],"name":CTRL.sub("",str(r.get("name") or ""))[:80],"bio":CTRL.sub("",str(r.get("bio") or ""))[:500],"location":"","followers":None}

def parse_joined(s):
    s=re.sub(r"^\s*joined\s*","",str(s or ""),flags=re.I).strip()
    for f in ("%B %Y","%b %Y"):
        try: return datetime.strptime(s,f).replace(tzinfo=timezone.utc).isoformat()
        except ValueError: pass
    return None

def classify(a,min_items):
    """Presentation layer ON TOP of the engine scores. Never labels an account from a single indicator."""
    if not a or a.get("n",0)<min_items or a.get("verdict")=="insufficient data": return "insufficient data"
    strong=[s for s in a["signals"] if s["value"]>=0.5]; sc=a["scores"]
    if sc["machine"]>=60 and len(strong)>=3: return "automated"
    top=max(sc["machine"],sc["foreign"])
    if top>=40 or (len(strong)>=2 and top>=25): return "suspicious"
    if strong: return "unusual activity"
    return "no strong indicators"

class Bridge:
    def __init__(s):
        s.lock=threading.RLock(); s.token=get_token(); s.pair_until=0.0
        s.state="idle"; s.query=""; s.sort="top"; s.opts={"autoscroll":False,"max_posts":500,"min_items":20}
        s.last_hb=0.0; s.auth="unknown"; s.page="other"; s.challenge=None; s.challenge_now=False; s.end=False
        s.app_ver=""; s.commands=[]; s.stop_reason=""; s.diag={}; s.seq=0
        s.plan=[]; s.pi=0; s.cur_url=None; s.hold_until=0.0; s.step_last=0.0; s.clear_session()
    def clear_session(s):
        s.session={}; s.accounts={}; s.results={}; s.last_n={}; s.errors=[]; s.rejected=0; s.off_target=0; s.last_ok=0.0; s._clu=None
    def err(s,m): s.errors=(s.errors+[{"t":time.strftime("%H:%M:%S"),"msg":m}])[-20:]
    def connected(s): return time.time()-s.last_hb<15
    def cur_step(s): return s.plan[s.pi] if s.plan and s.pi<len(s.plan) else None
    def targets(s): return {st["target"].lower() for st in s.plan if st["kind"]!="search"}

    # ---------- plan engine
    def _enter(s):
        st=s.plan[s.pi]; st["status"]="running"; s.seq+=1; s.step_last=time.time(); s.end=False
        s.query=f'{st["kind"]}: {st["target"]}'
        url=step_url(st,s.sort)
        if url!=s.cur_url: s.commands.append({"action":"open","url":url}); s.cur_url=url
        s.hold_until=time.time()+random.uniform(6,11)          # settle time after switching page

    def _advance(s,why):
        st=s.cur_step()
        if not st: return
        st["status"]=why; nxt=s.pi+1
        if st["kind"]!="search" and (nxt>=len(s.plan) or s.plan[nxt]["target"].lower()!=st["target"].lower()): s._finish(st["target"])
        if nxt>=len(s.plan):
            s.state="stopped"; s.stop_reason="plan complete"; s.pi=len(s.plan); return
        s.pi=nxt; s._enter()

    def _finish(s,u):
        """All steps for one profile are done -> run the analysis engine on what was collected."""
        u=resolve_user(u); st=Store(u)
        if not (st.dir/"profile.json").exists(): s.err(f"@{u}: no profile data collected (protected/not found?)"); return
        posts=st.load("posts",{}) or {}; com=st.load("comments",{}) or {}
        a=an.analyze(st.load("profile") or {},posts,com,st.load("followers",{}),st.load("following",{}),(st.load("about",{}) or {}).get("country"))
        st.save("analysis",a); n=len(posts)+len(com)
        s.results[u]={"verdict":a["verdict"],"scores":a["scores"],"label":classify(a,s.opts["min_items"]),"n":n}
        acc=s.accounts.setdefault(u,{"items":n,"new":0}); acc["items"]=n; acc["profile"]=True

    # ---------- companion -> backend
    def heartbeat(s,d):
        with s.lock:
            now=time.time(); s.last_hb=now; a=d.get("auth"); s.auth=a if a in AUTHS else "unknown"
            pg=d.get("page"); s.page=pg if pg in PAGES else "other"; s.app_ver=str(d.get("app",""))[:12]
            dg=d.get("diag") if isinstance(d.get("diag"),dict) else {}
            path=str(dg.get("path",""))
            s.diag={"articles":_int(dg.get("articles"),0,10**5),"cells":_int(dg.get("cells"),0,10**5),"seen":_int(dg.get("seen"),0,10**6),
                    "in_scope":dg.get("scope") is True,"path":path if re.fullmatch(r"[\w/\-.]{0,60}",path) else ""}
            c=d.get("challenge"); s.challenge_now=c in CHAL; s.end=d.get("end") is True
            if c in CHAL and not s.challenge:
                s.challenge=c; s.err(f"{c} challenge detected - paused. Solve it in the browser, then press Resume.")
                if s.state=="running": s.state="paused"
            st=s.cur_step()
            if st and s.state=="running" and not s.challenge and now>s.hold_until:
                if d.get("end") is True and d.get("seq")==s.seq: s._advance("end")
                elif s.opts["autoscroll"] and now-s.step_last>STALL[st["kind"]]: s._advance("stalled")
            cmds,s.commands=s.commands,[]
            st=s.cur_step()
            mode={"kind":st["kind"],"target":st["target"]} if st else {"kind":"search","target":""}
            return {"state":s.state,"query":s.query,"opts":s.opts,"commands":cmds,"mode":mode,"seq":s.seq,"hold":now<s.hold_until}

    def ingest(s,records,query="",seq=None):
        with s.lock:
            if s.state!="running": return {"accepted":0,"state":s.state}
            if seq is not None and seq!=s.seq: return {"accepted":0,"state":s.state,"stale":True}
            st=s.cur_step()
            if st and st["kind"] not in ("search","posts","replies"): return {"accepted":0,"state":s.state}
            buf={}; new=0; hit=False
            for r in (records if isinstance(records,list) else [])[:100]:
                c=validate(r)
                if not c: s.rejected+=1; continue
                if st:
                    if st["kind"] in ("posts","replies"):
                        want="post" if st["kind"]=="posts" else "comment"
                        if c["username"].lower()!=st["target"].lower() or c["kind"]!=want: s.off_target+=1; continue
                    if st["got"]>=st["limit"]: hit=True; break
                elif len(s.session)>=s.opts["max_posts"]:
                    s.state="stopped"; s.stop_reason="post limit reached"; break
                if c["id"] in s.session: continue
                s.session[c["id"]]={"u":c["username"],"norm":" ".join(an.toks(c["text"])),"t":an.ts(c["ts"]).timestamp()}
                buf.setdefault(c["username"],[]).append(c); new+=1
                if st:
                    st["got"]+=1
                    if st["got"]>=st["limit"]: hit=True; break
            for u0,recs in buf.items():
                u=resolve_user(u0); sd=Store(u); posts=sd.load("posts",{}) or {}; com=sd.load("comments",{}) or {}
                for c in recs:
                    d=com if c["kind"]=="comment" else posts
                    if c["id"] in posts or c["id"] in com: continue
                    d[c["id"]]={"id":c["id"],"text":c["text"],"ts":c["ts"],"kind":c["kind"],"rt":False,"source":"","lang":c["lang"],
                        "likes":c["likes"],"replies":c["replies"],"reposts":c["reposts"],"views":c["views"],
                        "url":f"https://x.com/{u0}/status/{c['id']}","via":"x.com-browser","query":str(query)[:200]}
                sd.save("posts",posts); sd.save("comments",com)
                prof=sd.load("profile")
                if not prof:
                    prof={"id":u,"username":u,"name":recs[0]["name"],"bio":"","location":"","created_at":None,"followers":None,
                          "following":None,"tweets":None,"verified":recs[0]["verified"],"avatar":recs[0]["avatar"],"via":"x.com-browser"}
                    sd.save("profile",prof)
                a=s.accounts.setdefault(u,{"items":0,"new":0})
                a["items"]=len(posts)+len(com); a["new"]+=len(recs); a["profile"]=bool(prof.get("created_at") or prof.get("followers") is not None)
            if new: s.last_ok=time.time(); s.step_last=time.time(); s._clu=None
            if not st: s.analyse(buf.keys())
            if hit and st: s._advance("limit")
            return {"accepted":new,"state":s.state}

    def relations(s,kind,users,seq=None):
        with s.lock:
            st=s.cur_step()
            if s.state!="running" or not st or st["kind"]!=kind: return {"accepted":0,"state":s.state}
            if seq is not None and seq!=s.seq: return {"accepted":0,"state":s.state,"stale":True}
            u=resolve_user(st["target"]); sd=Store(u); d=sd.load(kind,{}) or {}; seen=st.setdefault("_seen",set()); new=0; hit=False
            for r in (users if isinstance(users,list) else [])[:100]:
                c=validate_user(r)
                if not c or c["username"].lower() in seen: 
                    if not c: s.rejected+=1
                    continue
                seen.add(c["username"].lower()); d.setdefault(c["username"],c); new+=1; st["got"]+=1
                if st["got"]>=st["limit"]: hit=True; break
            if new: sd.save(kind,d); s.last_ok=time.time(); s.step_last=time.time()
            if hit: s._advance("limit")
            return {"accepted":new,"state":s.state}

    def profile(s,p,seq=None):
        with s.lock:
            if not isinstance(p,dict) or not UNAME.match(str(p.get("username",""))): return {"ok":False}
            st=s.cur_step()
            if seq is not None and st and seq!=s.seq: return {"ok":False,"stale":True}
            u=resolve_user(p["username"]); sd=Store(u)
            prof=sd.load("profile") or {"id":u,"username":u,"name":"","bio":"","location":"","created_at":None,
                "followers":None,"following":None,"tweets":None,"verified":False,"avatar":"","via":"x.com-browser"}
            for k,mx in (("name",80),("bio",500),("location",100)):
                v=CTRL.sub("",str(p.get(k) or "")).strip()[:mx]
                if v: prof[k]=v
            j=parse_joined(p.get("joined"))
            if j and not prof.get("created_at"): prof["created_at"]=j
            for k in ("followers","following"):
                v=_int(p.get(k))
                if v is not None: prof[k]=v
            sd.save("profile",prof)
            if u in s.accounts: s.accounts[u]["profile"]=True
            if s.state=="running" and st and st["kind"]=="profile" and u.lower()==st["target"].lower():
                st["got"]=1; s.last_ok=time.time(); s._advance("done")
            else: s.analyse([u],force=True)
            return {"ok":True}

    # ---------- analysis (engine unchanged by the bridge)
    def analyse(s,users,force=False):
        mi=s.opts["min_items"]
        for u in list(users):
            sd=Store(u); posts=sd.load("posts",{}) or {}; com=sd.load("comments",{}) or {}; n=len(posts)+len(com)
            if n<mi or (not force and u in s.results and n-s.last_n.get(u,0)<10): continue
            a=an.analyze(sd.load("profile") or {},posts,com,sd.load("followers",{}),sd.load("following",{}),(sd.load("about",{}) or {}).get("country"))
            sd.save("analysis",a); s.last_n[u]=n
            s.results[u]={"verdict":a["verdict"],"scores":a["scores"],"label":classify(a,mi),"n":n}

    def clusters(s):
        if s._clu and s._clu[0]==len(s.session): return s._clu[1]
        by={}
        for v in s.session.values():
            if len(v["norm"].split())>=6: by.setdefault(v["norm"],[]).append(v)
        norms=list(by)[:600]; sets=[set(n.split()) for n in norms]; par=list(range(len(norms)))
        def f(x):
            while par[x]!=x: par[x]=par[par[x]]; x=par[x]
            return x
        for i in range(len(norms)):
            for j in range(i+1,len(norms)):
                a,b=sets[i],sets[j]
                if min(len(a),len(b))/max(len(a),len(b))>=0.8 and len(a&b)/len(a|b)>=0.8: par[f(i)]=f(j)
        grp={}
        for i,n in enumerate(norms): grp.setdefault(f(i),[]).append(n)
        out=[]
        for ns in grp.values():
            vs=[v for n in ns for v in by[n]]; users=sorted({v["u"] for v in vs})
            if len(users)>=2:
                ts=[v["t"] for v in vs]
                out.append({"text":ns[0][:140],"accounts":users,"n_accounts":len(users),"posts":len(vs),"span_min":round((max(ts)-min(ts))/60,1)})
        out.sort(key=lambda c:-c["n_accounts"]); s._clu=(len(s.session),out); return out

    # ---------- dashboard -> backend
    def forget(s,users):
        """Called after saved data is deleted from the dashboard."""
        with s.lock:
            low={u.lower() for u in users}
            if s.state in ("running","paused") and (low & s.targets()): return False
            for d in (s.accounts,s.results,s.last_n):
                for u in list(d):
                    if u.lower() in low: d.pop(u)
            s._clu=None; return True

    def control(s,d):
        a=d.get("action")
        def bad(m): return {"ok":False,"error":m}
        with s.lock:
            conn=s.connected()
            if a=="start":
                q=str(d.get("query","")).strip()
                if not q or len(q)>512 or "\n" in q: return bad("query required (single line, max 512 chars)")
                if not conn: return bad("browser not connected - open the XBotScope Browser app and pair it")
                s.opts={"autoscroll":d.get("autoscroll") is True,"max_posts":max(1,min(5000,_int(d.get("max_posts"),1,5000) or 500)),
                        "min_items":max(20,min(500,_int(d.get("min_items"),20,500) or 20))}
                s.clear_session(); s.plan=[]; s.pi=0; s.query=q; s.sort="live" if d.get("sort")=="live" else "top"; s.challenge=None
                s.stop_reason=""; s.state="running"; s.seq+=1; s.hold_until=time.time()+random.uniform(3,6); s.cur_url=search_url(q,s.sort)
                s.commands+= [{"action":"reset_seen"},{"action":"open","url":s.cur_url}]
            elif a=="start_plan":
                if not conn: return bad("browser not connected - open the XBotScope Browser app and pair it")
                profiles=parse_names(d.get("profiles")); queries=parse_lines(d.get("queries"))
                if not profiles and not queries: return bad("enter at least one profile or one search query")
                L=lambda k,df: max(0,min(2000,_int(d.get(k),0,2000) if _int(d.get(k),0,2000) is not None else df))
                lim={"posts":L("posts",100),"replies":L("replies",50),"followers":L("followers",0),"following":L("following",0)}
                ql=max(1,L("search_limit",100))
                steps=[]
                for u in profiles:
                    steps.append({"kind":"profile","target":u,"limit":1})
                    for k in ("posts","replies","followers","following"):
                        if lim[k]: steps.append({"kind":k,"target":u,"limit":lim[k]})
                for q in queries: steps.append({"kind":"search","target":q,"limit":ql})
                for x in steps: x.update(got=0,status="pending")
                s.opts={"autoscroll":d.get("autoscroll",True) is not False,"max_posts":5000,"min_items":20}
                s.clear_session(); s.plan=steps; s.pi=0; s.sort="live" if d.get("sort")=="live" else "top"; s.challenge=None
                s.stop_reason=""; s.state="running"; s.cur_url=None; s._enter()
            elif a=="skip":
                if s.state in ("running","paused") and s.cur_step(): 
                    s.state="running"; s.challenge=None; s._advance("skipped")
                else: return bad("no active plan step")
            elif a=="pause":
                if s.state=="running": s.state="paused"
            elif a=="resume":
                if not conn: return bad("browser not connected")
                if s.state!="paused": return bad("nothing to resume (state: %s)"%s.state)
                s.challenge=None; s.state="running"; s.step_last=time.time(); s.hold_until=time.time()+random.uniform(3,6)
            elif a=="stop":
                if s.state in ("running","paused"): s.state="stopped"; s.stop_reason="stopped by user"
            elif a=="clear":
                s.clear_session(); s.commands.append({"action":"reset_seen"})
            elif a=="open":
                if not conn: return bad("browser not connected")
                s.cur_url="https://x.com/home"; s.commands.append({"action":"open","url":s.cur_url})
            elif a=="enrich":
                if not conn: return bad("browser not connected")
                us=[u for u,i in s.accounts.items() if not i.get("profile")][:max(1,min(100,_int(d.get("limit"),1,100) or 30))]
                if not us: return bad("no accounts need profile data")
                s.commands.append({"action":"enrich","usernames":us})
            elif a=="clear_browser":
                if not conn: return bad("browser not connected")
                s.commands.append({"action":"clear_browser"})
            else: return bad("unknown action")
            return {"ok":True,"state":s.state}

    def status(s):
        with s.lock:
            now=time.time(); conn=s.connected(); cl=s.clusters(); inclu={}
            for c in cl:
                for u in c["accounts"]: inclu[u]=inclu.get(u,0)+1
            if not conn: eff="disconnected"+(" (collection NOT active)" if s.state=="running" else "")
            elif s.challenge: eff="paused - challenge ("+s.challenge+")"
            elif s.state=="running": eff="active" if now-s.last_ok<45 else ("running - settling after page switch" if now<s.hold_until else "running - waiting for results")
            else: eff=s.state
            accs=[]
            for u,i in sorted(s.accounts.items(),key=lambda kv:-kv[1]["items"])[:100]:
                r=s.results.get(u); accs.append({"username":u,"items":i["items"],"session":i["new"],"profile":i.get("profile",False),
                    "analysed":bool(r),"verdict":r and r["verdict"],"scores":r and r["scores"],"label":r and r["label"],"clusters":inclu.get(u,0)})
            steps=[{k:v for k,v in x.items() if not k.startswith("_")} for x in s.plan]
            return {"version":VERSION,"connected":conn,"app":s.app_ver,"auth":s.auth if conn else "unknown","page":s.page,"state":s.state,"effective":eff,
                "query":s.query,"sort":s.sort,"opts":s.opts,"challenge":s.challenge,"challenge_visible":s.challenge_now,"end_of_results":s.end,
                "stop_reason":s.stop_reason,"posts":len(s.session),"accounts_found":len(s.accounts),"analysed":len(s.results),
                "awaiting":len(s.accounts)-len(s.results),"rejected":s.rejected,"off_target":s.off_target,"errors":s.errors,
                "last_ok":s.last_ok and time.strftime("%H:%M:%S",time.localtime(s.last_ok)),"accounts":accs,"clusters":cl[:10],
                "plan":{"steps":steps,"index":s.pi,"seq":s.seq},"diag":s.diag}

BRIDGE=Bridge()
