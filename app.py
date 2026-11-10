# Author: gorcoding
# XBotScope - local dashboard for X account bot/human/foreign-service pattern analysis.
import hmac, re
from flask import Flask, jsonify, request, send_from_directory, Response, abort
from core import store, runner, analyze, dorks, geo, manage, ai
from core.bridge import BRIDGE
from core.version import VERSION
from core.job import JOB, start

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 512*1024

@app.before_request
def guard():
    # local-only hardening (V2): block DNS-rebinding and cross-site POSTs to the dashboard API
    if request.host.split(":")[0] not in ("127.0.0.1","localhost"): abort(403)
    if request.method=="POST" and not request.path.startswith("/api/bridge/in/") and request.headers.get("X-XBS")!="1": abort(403)

def bridge_auth(f):
    from functools import wraps
    @wraps(f)
    def w(*a,**k):
        if request.remote_addr not in ("127.0.0.1","::1") or not hmac.compare_digest(request.headers.get("X-Bridge-Token",""),BRIDGE.token):
            return jsonify(error="unauthorized"),401
        return f(*a,**k)
    return w
USER = re.compile(r"^\w{1,15}$")

@app.get("/")
def index(): return send_from_directory("static","index.html")

SECRET=("bearer","ai_key","cookies")
@app.route("/api/settings",methods=["GET","POST"])
def settings():
    if request.method=="POST":
        d=request.get_json(force=True); cur=store.get_settings()
        for k in SECRET:
            if str(d.get(k,"")).startswith("\u2022\u2022\u2022\u2022"): d[k]=cur.get(k,"")
        store.save_settings(d)
    s=dict(store.get_settings())
    for k in SECRET: s[k]="\u2022\u2022\u2022\u2022saved" if s.get(k) else ""
    return jsonify(s)

@app.post("/api/fetch")
def fetch():
    d=request.get_json(force=True); u=(d.get("username") or "").strip().lstrip("@")
    if not USER.match(u): return jsonify(ok=False,error="invalid username"),400
    if "live" in d: store.save_settings({"live":bool(d["live"])})
    d["username"]=u
    return jsonify(ok=start("fetch",runner.run_fetch,d))

@app.post("/api/dorks/<u>")
def run_dorks(u):
    if not USER.match(u): return jsonify(ok=False),400
    if "live" in (request.get_json(silent=True) or {}): store.save_settings({"live":bool(request.json["live"])})
    return jsonify(ok=start("dorks",runner.run_dorks,u))

@app.get("/api/job")
def job():
    return jsonify(status=JOB.status,kind=JOB.kind,logs=JOB.logs[-80:],progress=JOB.progress,url=JOB.paused_url)

@app.post("/api/job/<action>")
def job_action(action):
    if action=="resume": JOB.resume()
    elif action=="stop": JOB.halt()
    return jsonify(ok=True)

@app.get("/api/users")
def users(): return jsonify(store.list_users())

@app.get("/api/profile/<u>")
def profile(u):
    if not USER.match(u): return jsonify(error="bad user"),400
    st=store.Store(u); prof=st.load("profile")
    if not prof: return jsonify(error="no data for this user - fetch first"),404
    about=st.load("about",{}).get("country")
    a=analyze.analyze(prof,st.load("posts",{}),st.load("comments",{}),st.load("followers",{}),st.load("following",{}),about)
    st.save("analysis",a)
    qs=dorks.build(st.load("posts",{}),int(store.get_settings()["dork_max"]),store.get_settings().get("dork_tlds",""))
    for q in qs: q["links"]=dorks.links(q["query"])
    dd=st.load("dorks",{"results":[]})
    return jsonify(profile=prof,a=a,about=about,ai=st.load("ai"),dork_queries=qs,dork_results=dd["results"],dork_agg=dorks.aggregate(dd))

@app.post("/api/about/<u>")
def about(u):
    c=geo.parse_country(request.get_json(force=True).get("country",""))
    store.Store(u).save("about",{"country":c}); return jsonify(ok=True,country=c)

@app.get("/api/wordlist/<u>")
def wordlist(u):
    a=store.Store(u).load("analysis",{}) or {}
    return Response("\n".join(a.get("wordlist",[])),mimetype="text/plain",
                    headers={"Content-Disposition":f"attachment; filename={u}_wordlist.txt"})

@app.get("/api/version")
def version(): return jsonify(version=VERSION)

@app.post("/api/bridge/in/heartbeat")
@bridge_auth
def b_hb(): return jsonify(BRIDGE.heartbeat(request.get_json(silent=True) or {}))

@app.post("/api/bridge/in/records")
@bridge_auth
def b_rec():
    d=request.get_json(silent=True) or {}
    return jsonify(BRIDGE.ingest(d.get("records"),d.get("query",""),d.get("seq")))

@app.post("/api/bridge/in/profile")
@bridge_auth
def b_prof():
    d=request.get_json(silent=True) or {}
    return jsonify(BRIDGE.profile(d.get("profile"),d.get("seq")))

@app.post("/api/bridge/in/relations")
@bridge_auth
def b_rel():
    d=request.get_json(silent=True) or {}
    return jsonify(BRIDGE.relations(d.get("kind"),d.get("users"),d.get("seq")))

@app.get("/api/bridge/status")
def b_status(): return jsonify(BRIDGE.status())

@app.post("/api/bridge/control")
def b_ctl():
    r=BRIDGE.control(request.get_json(silent=True) or {}); return jsonify(r),(200 if r.get("ok") else 400)

@app.post("/api/bridge/pair/open")
def b_pair_open():
    import time; BRIDGE.pair_until=time.time()+120; return jsonify(ok=True,seconds=120)

@app.get("/api/bridge/pairing")
def b_pair():
    import time
    if time.time()>BRIDGE.pair_until: return jsonify(locked=True)
    return jsonify(token=BRIDGE.token,port=8080,link=f"xbotscope://pair?token={BRIDGE.token}&port=8080")

# ---------- saved data manager
@app.get("/api/manage/list")
def m_list(): return jsonify(manage.overview())

@app.post("/api/manage/delete")
def m_delete():
    d=request.get_json(silent=True) or {}
    if d.get("all"):
        if d.get("confirm")!="DELETE": return jsonify(ok=False,error="type DELETE to confirm"),400
        users=[x["username"] for x in manage.overview()]
    else: users=[u for u in (d.get("users") or []) if isinstance(u,str)]
    if not BRIDGE.forget(users): return jsonify(ok=False,error="a collection plan is using one of these profiles - stop it first"),409
    return jsonify(ok=True,deleted=manage.delete(users))

@app.post("/api/manage/delete_part")
def m_delete_part():
    d=request.get_json(silent=True) or {}
    return jsonify(ok=True,deleted=manage.delete_parts(str(d.get("user","")),d.get("parts") or []))

@app.post("/api/manage/export")
def m_export():
    p=manage.export(str((request.get_json(silent=True) or {}).get("user","")))
    return (jsonify(ok=True,path=p) if p else (jsonify(ok=False,error="unknown user"),404))

# ---------- optional AI second opinion
@app.post("/api/ai/<u>")
def ai_review(u):
    if not USER.match(u): return jsonify(error="bad user"),400
    cfg=store.get_settings()
    if not cfg.get("ai_consent"): return jsonify(error="AI review is off: enable it and tick the consent box in Settings"),403
    st=store.Store(u); prof=st.load("profile")
    if not prof: return jsonify(error="no data for this user"),404
    posts,com=st.load("posts",{}),st.load("comments",{})
    a=analyze.analyze(prof,posts,com,st.load("followers",{}),st.load("following",{}),(st.load("about",{}) or {}).get("country"))
    try: res=ai.ask(cfg,ai.build_payload(a,prof,posts,com,cfg))
    except Exception as e: return jsonify(error=str(e)[:300]),502
    import time
    res.update(model=cfg.get("ai_model"),provider=cfg.get("ai_provider"),at=time.strftime("%Y-%m-%d %H:%M"),sent_samples=bool(cfg.get("ai_send_samples")))
    st.save("ai",res); return jsonify(res)

if __name__=="__main__":
    print(f"XBotScope {VERSION} by gorcoding -> http://127.0.0.1:8080")
    app.run("127.0.0.1",8080,threaded=True)
