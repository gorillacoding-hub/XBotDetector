# Author: gorcoding
# XBotScope - local dashboard for X account bot/human/foreign-service pattern analysis.
import hmac, re
from flask import Flask, jsonify, request, send_from_directory, Response, abort
from core import store, runner, analyze, dorks, geo
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

@app.route("/api/settings",methods=["GET","POST"])
def settings():
    if request.method=="POST": return jsonify(store.save_settings(request.get_json(force=True)))
    return jsonify(store.get_settings())

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
    return jsonify(profile=prof,a=a,about=about,dork_queries=qs,dork_results=dd["results"],dork_agg=dorks.aggregate(dd))

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
    return jsonify(BRIDGE.ingest(d.get("records"),d.get("query","")))

@app.post("/api/bridge/in/profile")
@bridge_auth
def b_prof(): return jsonify(BRIDGE.profile((request.get_json(silent=True) or {}).get("profile")))

@app.post("/api/bridge/in/full")
@bridge_auth
def b_full():
    return jsonify(BRIDGE.full_ingest(request.get_json(silent=True) or {}))

@app.get("/api/bridge/status")
def b_status(): return jsonify(BRIDGE.status())

@app.post("/api/bridge/control")
def b_ctl():
    r=BRIDGE.control(request.get_json(silent=True) or {}); return jsonify(r),(200 if r.get("ok") else 400)

@app.get("/api/bridge/pairing")
def b_pair():
    return jsonify(token=BRIDGE.token,port=8080,link=f"xbotscope://pair?token={BRIDGE.token}&port=8080")

if __name__=="__main__":
    print(f"XBotScope {VERSION} by gorcoding -> http://127.0.0.1:8080")
    app.run("127.0.0.1",8080,threaded=True)
