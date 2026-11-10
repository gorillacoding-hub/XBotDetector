# Author: gorcoding
# V2 bridge: receives structured, validated public search-result records from the Android X browser
# companion and feeds them into the existing V1 storage + analysis pipeline (core.store / core.analyze).
# Never receives, stores or logs credentials or session data.
import json, os, re, secrets, threading, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from .store import Store, ROOT
from . import analyze as an
from .version import VERSION

UNAME=re.compile(r"^\w{1,15}$"); IDRX=re.compile(r"^\d{5,25}$")
AUTHS={"logged_in","logged_out","unknown"}; PAGES={"search","profile","other"}
CHAL={"captcha","verification","rate_limit","locked","error"}
SECRET_MARKERS=("auth_token","ct0=")          # defence in depth: records containing these are dropped
CTRL=re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def get_token():
    ROOT.mkdir(parents=True,exist_ok=True); p=ROOT/".bridge_token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(24))
        try: os.chmod(p,0o600)
        except OSError: pass
    return p.read_text().strip()

def search_url(q,sort):
    return "https://x.com/search?q="+quote(q,safe="")+"&src=typed_query"+("&f=live" if sort=="live" else "")

def _int(v,lo=0,hi=10**11):
    return int(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and lo<=v<=hi else None

def validate(r):
    """Return a clean record or None. Unknown keys are ignored."""
    if not isinstance(r,dict): return None
    try:
        pid=str(r.get("id","")); u=str(r.get("username",""))
        if not IDRX.match(pid) or not UNAME.match(u) or not isinstance(r.get("text"),str): return None
        low=json.dumps(r).lower()
        if any(m in low for m in SECRET_MARKERS): return None
        t=an.ts(r.get("ts"))
        now=datetime.now(timezone.utc)
        if not t or t<datetime(2006,3,1,tzinfo=timezone.utc) or t>now+timedelta(days=1): return None
        av=str(r.get("avatar") or ""); lang=str(r.get("lang") or "")
        return {"id":pid,"username":u,"name":CTRL.sub("",str(r.get("name") or ""))[:80],"text":CTRL.sub("",r["text"])[:5000],
            "ts":t.astimezone(timezone.utc).isoformat(),"kind":"comment" if r.get("kind")=="comment" else "post",
            "verified":r.get("verified") is True,"avatar":av if av.startswith("https://pbs.twimg.com/") and len(av)<300 else "",
            "lang":lang if re.fullmatch(r"[A-Za-z-]{2,8}",lang) else None,"replies":_int(r.get("replies")),
            "reposts":_int(r.get("reposts")),"likes":_int(r.get("likes")),"views":_int(r.get("views"))}
    except Exception:
        return None

def parse_joined(s):
    s=re.sub(r"^\s*joined\s*","",str(s or ""),flags=re.I).strip()
    for f in ("%B %Y","%b %Y"):
        try: return datetime.strptime(s,f).replace(tzinfo=timezone.utc).isoformat()
        except ValueError: pass
    return None

def classify(a,min_items):
    """Presentation layer ON TOP of unchanged V1 scores: separates automated / suspicious / unusual.
    Never labels an account from a single indicator."""
    if not a or a.get("n",0)<min_items or a.get("verdict")=="insufficient data": return "insufficient data"
    strong=[s for s in a["signals"] if s["value"]>=0.5]; sc=a["scores"]
    if sc["machine"]>=60 and len(strong)>=3: return "automated"
    top=max(sc["machine"],sc["foreign"])
    if top>=40 or (len(strong)>=2 and top>=25): return "suspicious"
    if strong: return "unusual activity"
    return "no strong indicators"

class Bridge:
    def __init__(s):
        s.lock=threading.RLock(); s.token=get_token()
        s.state="idle"; s.query=""; s.sort="top"; s.opts={"autoscroll":False,"max_posts":500,"min_items":20}
        s.last_hb=0.0; s.auth="unknown"; s.page="other"; s.challenge=None; s.challenge_now=False; s.end=False
        s.app_ver=""; s.commands=[]; s.stop_reason=""
        s.full={"status":"idle","username":"","stage":"","profile_only":False,
                "limits":{"posts":500,"comments":500,"followers":200,"following":200},
                "counts":{"posts":0,"comments":0,"followers":0,"following":0},
                "message":"","started":0,"finished":0}
        s.clear_session()
    def clear_session(s):
        s.session={}; s.accounts={}; s.results={}; s.last_n={}; s.errors=[]; s.rejected=0; s.last_ok=0.0; s._clu=None
    def err(s,m): s.errors=(s.errors+[{"t":time.strftime("%H:%M:%S"),"msg":m}])[-20:]
    def connected(s): return time.time()-s.last_hb<15

    # ---- companion -> backend
    def heartbeat(s,d):
        with s.lock:
            s.last_hb=time.time(); a=d.get("auth"); s.auth=a if a in AUTHS else "unknown"
            pg=d.get("page"); s.page=pg if pg in PAGES else "other"; s.app_ver=str(d.get("app",""))[:12]
            c=d.get("challenge"); s.challenge_now=c in CHAL; s.end=d.get("end") is True
            if c in CHAL and not s.challenge:
                s.challenge=c; s.err(f"{c} challenge detected - collection paused. Solve it in the browser, then press Resume.")
                if s.state=="running": s.state="paused"
            cmds,s.commands=s.commands,[]
            return {"state":s.state,"query":s.query,"opts":s.opts,"commands":cmds}

    def ingest(s,records,query=""):
        with s.lock:
            if s.state!="running": return {"accepted":0,"state":s.state}
            buf={}; new=0
            for r in (records if isinstance(records,list) else [])[:100]:
                c=validate(r)
                if not c: s.rejected+=1; continue
                if c["id"] in s.session: continue
                if len(s.session)>=s.opts["max_posts"]:
                    s.state="stopped"; s.stop_reason="post limit reached"; break
                s.session[c["id"]]={"u":c["username"],"norm":" ".join(an.toks(c["text"])),"t":an.ts(c["ts"]).timestamp()}
                buf.setdefault(c["username"],[]).append(c); new+=1
            for u,recs in buf.items():
                st=Store(u); posts=st.load("posts",{}) or {}; com=st.load("comments",{}) or {}
                for c in recs:
                    d=com if c["kind"]=="comment" else posts
                    if c["id"] in posts or c["id"] in com: continue
                    d[c["id"]]={"id":c["id"],"text":c["text"],"ts":c["ts"],"kind":c["kind"],"rt":False,"source":"","lang":c["lang"],
                        "likes":c["likes"],"replies":c["replies"],"reposts":c["reposts"],"views":c["views"],
                        "url":f"https://x.com/{u}/status/{c['id']}","via":"x.com-browser","query":str(query)[:200]}
                st.save("posts",posts); st.save("comments",com)
                prof=st.load("profile")
                if not prof:
                    prof={"id":u,"username":u,"name":recs[0]["name"],"bio":"","location":"","created_at":None,"followers":None,
                          "following":None,"tweets":None,"verified":recs[0]["verified"],"avatar":recs[0]["avatar"],"via":"x.com-browser"}
                    st.save("profile",prof)
                a=s.accounts.setdefault(u,{"items":0,"new":0})
                a["items"]=len(posts)+len(com); a["new"]+=len(recs); a["profile"]=bool(prof.get("created_at") or prof.get("followers") is not None)
            if new: s.last_ok=time.time(); s._clu=None
            s.analyse(buf.keys())
            return {"accepted":new,"state":s.state}

    def profile(s,p):
        with s.lock:
            if not isinstance(p,dict) or not UNAME.match(str(p.get("username",""))): return {"ok":False}
            u=p["username"]; st=Store(u); prof=st.load("profile") or {"id":u,"username":u,"name":"","bio":"","location":"","created_at":None,
                "followers":None,"following":None,"tweets":None,"verified":False,"avatar":"","via":"x.com-browser"}
            for k,mx in (("name",80),("bio",500),("location",100)):
                v=CTRL.sub("",str(p.get(k) or "")).strip()[:mx]
                if v: prof[k]=v
            j=parse_joined(p.get("joined"))
            if j and not prof.get("created_at"): prof["created_at"]=j
            for k in ("followers","following"):
                v=_int(p.get(k))
                if v is not None: prof[k]=v
            st.save("profile",prof)
            if u in s.accounts: s.accounts[u]["profile"]=True
            s.analyse([u],force=True); return {"ok":True}

    # ---- dedicated full-profile browser ingestion
    def full_ingest(s,d):
        with s.lock:
            job=s.full
            if job["status"] not in ("running","paused"):
                return {"ok":False,"accepted":0,"error":"no active full fetch"}
            u=job["username"]; st=Store(u); kind=str(d.get("kind",""))
            if kind=="profile":
                p=d.get("profile") or {}
                if p.get("username")!=u: return {"ok":False,"accepted":0}
                s.profile(p)
                return {"ok":True,"accepted":1}
            if kind in ("posts","comments"):
                buf={}
                arr=d.get("records")
                if not isinstance(arr,list): arr=[]
                accepted=0
                file="comments" if kind=="comments" else "posts"
                data=st.load(file,{}) or {}
                for raw in arr[:100]:
                    c=validate(raw)
                    if not c or c["username"].lower()!=u.lower(): continue
                    target=data
                    if c["id"] not in target:
                        target[c["id"]]={"id":c["id"],"text":c["text"],"ts":c["ts"],
                            "kind":kind[:-1] if kind=="comments" else "post","rt":False,
                            "source":"","lang":c["lang"],"likes":c["likes"],
                            "replies":c["replies"],"reposts":c["reposts"],"views":c["views"],
                            "url":f"https://x.com/{u}/status/{c['id']}","via":"x.com-browser-full"}
                        accepted+=1
                st.save(file,data)
                job["counts"][kind]=len(data)
                if accepted:
                    s.last_ok=time.time()
                    s.analyse([u],force=True)
                return {"ok":True,"accepted":accepted,"count":len(data)}
            if kind in ("followers","following"):
                arr=d.get("users")
                if not isinstance(arr,list): arr=[]
                data=st.load(kind,{}) or {}
                accepted=0
                for raw in arr[:200]:
                    if not isinstance(raw,dict): continue
                    name=str(raw.get("username","")).strip().lstrip("@")
                    if not UNAME.match(name) or name.lower()==u.lower(): continue
                    data[name]={"username":name,
                        "name":CTRL.sub("",str(raw.get("name","")))[:80],
                        "bio":CTRL.sub("",str(raw.get("bio","")))[:500],
                        "location":CTRL.sub("",str(raw.get("location","")))[:100]}
                    accepted+=1
                st.save(kind,data)
                job["counts"][kind]=len(data)
                s.analyse([u],force=True)
                return {"ok":True,"accepted":accepted,"count":len(data)}
            if kind=="progress":
                job["stage"]=str(d.get("stage",""))[:30]
                job["message"]=str(d.get("message",""))[:160]
                return {"ok":True}
            if kind=="done":
                job["status"]="done"; job["stage"]="complete"
                job["message"]=str(d.get("message","Completed"))[:160]
                job["finished"]=time.time()
                s.analyse([u],force=True)
                return {"ok":True}
            return {"ok":False,"error":"unknown full-fetch payload"}

    # ---- analysis (existing V1 engine, unchanged)
    def analyse(s,users,force=False):
        mi=s.opts["min_items"]
        for u in list(users):
            st=Store(u); posts=st.load("posts",{}) or {}; com=st.load("comments",{}) or {}; n=len(posts)+len(com)
            if n<mi or (not force and u in s.results and n-s.last_n.get(u,0)<10): continue
            prof=st.load("profile") or {}
            a=an.analyze(prof,posts,com,st.load("followers",{}),st.load("following",{}),(st.load("about",{}) or {}).get("country"))
            st.save("analysis",a); s.last_n[u]=n
            s.results[u]={"verdict":a["verdict"],"scores":a["scores"],"label":classify(a,mi),"n":n}

    # ---- coordination: same/near-same text posted by different accounts in this session
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

    # ---- dashboard -> backend
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
                s.clear_session(); s.query=q; s.sort="live" if d.get("sort")=="live" else "top"; s.challenge=None; s.stop_reason=""; s.state="running"
                s.commands+= [{"action":"reset_seen"},{"action":"open","url":search_url(q,s.sort)}]
            elif a=="pause":
                if s.state=="running": s.state="paused"
            elif a=="resume":
                if not conn: return bad("browser not connected")
                if s.state!="paused": return bad("nothing to resume (state: %s)"%s.state)
                s.challenge=None; s.state="running"
            elif a=="stop":
                if s.state in ("running","paused"): s.state="stopped"; s.stop_reason="stopped by user"
            elif a=="clear":
                s.clear_session(); s.commands.append({"action":"reset_seen"})
            elif a=="open":
                if not conn: return bad("browser not connected")
                s.commands.append({"action":"open","url":"https://x.com/home"})
            elif a=="enrich":
                if not conn: return bad("browser not connected")
                us=[u for u,i in s.accounts.items() if not i.get("profile")][:max(1,min(100,_int(d.get("limit"),1,100) or 30))]
                if not us: return bad("no accounts need profile data")
                s.commands.append({"action":"enrich","usernames":us})
            elif a=="full_fetch":
                if not conn: return bad("browser not connected")
                u=str(d.get("username","")).strip().lstrip("@")
                if not UNAME.match(u): return bad("enter a valid X username")
                if s.full.get("status")=="running": return bad("a browser full fetch is already running")
                po=d.get("profile_only") is True
                limits={}
                for k,default,maximum in (("posts",500,5000),("comments",500,5000),
                                          ("followers",200,5000),("following",200,5000)):
                    try: limits[k]=max(0,min(maximum,int(d.get(k,default))))
                    except (TypeError,ValueError): limits[k]=default
                s.full={"status":"running","username":u,"stage":"profile",
                        "profile_only":po,"limits":limits,
                        "counts":{"posts":0,"comments":0,"followers":0,"following":0},
                        "message":"Starting browser fetch","started":time.time(),"finished":0}
                s.commands.append({"action":"full_fetch","username":u,
                                   "profile_only":po,"limits":limits})
            elif a=="stop_full":
                if s.full.get("status")=="running":
                    s.full["status"]="stopped"; s.full["message"]="Stopped by user"
                    s.commands.append({"action":"stop_full"})
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
            if not conn: eff="disconnected" + (" (collection NOT active)" if s.state=="running" else "")
            elif s.challenge: eff="paused - challenge ("+s.challenge+")"
            elif s.state=="running": eff="active" if now-s.last_ok<45 else "running - waiting for results"
            else: eff=s.state
            accs=[]
            for u,i in sorted(s.accounts.items(),key=lambda kv:-kv[1]["items"])[:100]:
                r=s.results.get(u); accs.append({"username":u,"items":i["items"],"session":i["new"],"profile":i.get("profile",False),
                    "analysed":bool(r),"verdict":r and r["verdict"],"scores":r and r["scores"],"label":r and r["label"],"clusters":inclu.get(u,0)})
            return {"version":VERSION,"connected":conn,"app":s.app_ver,"auth":s.auth if conn else "unknown","page":s.page,"state":s.state,"effective":eff,
                "query":s.query,"sort":s.sort,"opts":s.opts,"challenge":s.challenge,"challenge_visible":s.challenge_now,"end_of_results":s.end,
                "stop_reason":s.stop_reason,"posts":len(s.session),"accounts_found":len(s.accounts),"analysed":len(s.results),
                "awaiting":len(s.accounts)-len(s.results),"rejected":s.rejected,"errors":s.errors,"last_ok":s.last_ok and time.strftime("%H:%M:%S",time.localtime(s.last_ok)),
                "accounts":accs,"clusters":cl[:10],"full_fetch":dict(s.full)}

BRIDGE=Bridge()
