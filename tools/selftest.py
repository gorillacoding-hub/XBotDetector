# Author: gorcoding
# Backend self-test. Simulates the Android companion over the real HTTP routes (Flask test client).
# It does NOT test Android or x.com. Uses a temp data dir.
import sys, os, json, time, tempfile, random, shutil, logging, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import store
tmp = Path(tempfile.mkdtemp()); store.ROOT = tmp/"data"; store.SET = tmp/"settings.json"
import core.bridge as B; B.ROOT = store.ROOT
B.Store = store.Store
from core.bridge import BRIDGE
import app as A
from datetime import datetime, timedelta, timezone
log = io.StringIO(); h = logging.StreamHandler(log); logging.getLogger().addHandler(h); logging.getLogger("werkzeug").addHandler(h); logging.getLogger("werkzeug").setLevel(logging.INFO)
c = A.app.test_client(); T = {"X-Bridge-Token": BRIDGE.token}; X = {"X-XBS": "1"}
ok = 0
def check(name, cond):
    global ok; print(("PASS " if cond else "FAIL ")+name); ok += 0 if cond else 1
def hb(**k): return c.post("/api/bridge/in/heartbeat", json=dict({"app":"2.0.0","auth":"logged_in","page":"search"}, **k), headers=T).get_json()
def ctl(**k): return c.post("/api/bridge/control", json=k, headers=X)
def st(): return c.get("/api/bridge/status").get_json()
VOC = 'garden tea music football dog walk rain kitchen bread coffee train book movie friend market river hill paint guitar lunch bike storm winter summer piano soup museum ticket window coast harbor camera recipe puzzle ladder orchard'.split()
now = datetime.now(timezone.utc); random.seed(3); n = [0]
def rec(u, text, minutes, kind="post"):
    n[0] += 1
    return {"id": str(1700000000000000000+n[0]), "username": u, "name": u.upper(), "text": text, "ts": (now-timedelta(minutes=minutes)).isoformat(),
            "kind": kind, "likes": 1, "replies": 0, "reposts": 0, "views": 10}

# security
check("rejects wrong Host", c.get("/api/bridge/status", headers={"Host":"evil.com"}).status_code == 403)
check("dashboard POST without X-XBS blocked", c.post("/api/bridge/control", json={"action":"stop"}).status_code == 403)
check("bridge without token 401", c.post("/api/bridge/in/heartbeat", json={}).status_code == 401)
check("bridge wrong token 401", c.post("/api/bridge/in/heartbeat", json={}, headers={"X-Bridge-Token":"x"}).status_code == 401)
# not connected
check("start refused when browser disconnected", ctl(action="start", query="europe").status_code == 400)
check("status says disconnected", st()["effective"].startswith("disconnected"))
# connect + start
hb(); check("connected", st()["connected"])
r = ctl(action="start", query='europe lang:en', sort="live", max_posts=500, autoscroll=False)
check("start ok", r.status_code == 200)
cmds = hb()["commands"]; url = [x for x in cmds if x["action"] == "open"][0]["url"]
check("open command has query url unchanged", url.startswith("https://x.com/search?q=europe%20lang%3Aen") and "f=live" in url)
# ingest: bot-like account, human-like account, two coordinated accounts
recs = []
for i in range(60): recs.append(rec("botty", "BREAKING: Muslims immigrants invade Europe wake up retweet this now friends", 6000-90*i))
for i in range(40): recs.append(rec("humanx", " ".join(random.sample(VOC, 9)), random.choice(range(20000)) if False else (random.randint(0, 13)*1440 + random.choice(range(480, 1320)))))
for u in ("coord1", "coord2", "coord3"): recs.append(rec(u, "The government hides the truth about the border crisis and nobody reports it anymore", 30))
bad = [{"id":"abc","username":"x","text":"t","ts":"2026-01-01T00:00:00Z"}, {"id":"1234567","username":"a b","text":"t","ts":now.isoformat()},
       rec("leaky", "hello auth_token=abcdef", 5), "garbage", {"id":"1234567","username":"ok","text":"t","ts":"2999-01-01T00:00:00Z"}]
for i in range(0, len(recs), 50): res = c.post("/api/bridge/in/records", json={"query":"q","records":recs[i:i+50]+(bad if i == 0 else [])}, headers=T).get_json()
s = st()
check("posts collected = 103", s["posts"] == 103)
check("5 malformed/leaky records rejected", s["rejected"] == 5)
check("unique accounts = 5", s["accounts_found"] == 5)
check("analysed accounts (>=20 items) = 2", s["analysed"] == 2 and s["awaiting"] == 3)
bysc = {a["username"]: a for a in s["accounts"]}
print("   scores:",{k:v["scores"] for k,v in bysc.items() if v["scores"]}, {k:v["label"] for k,v in bysc.items()})
check("bot-like account scored machine-leaning", bysc["botty"]["scores"]["machine"] > bysc["humanx"]["scores"]["machine"])
check("labels: bot-like=suspicious/automated, human-like not", bysc["botty"]["label"] in ("automated", "suspicious") and bysc["humanx"]["label"] in ("unusual activity","no strong indicators"))
check("coordination cluster found (3 accounts)", any(cl["n_accounts"] == 3 for cl in s["clusters"]))
# V1 compatibility: scores identical to calling V1 analyze directly
from core import analyze as an
sd = store.Store("botty"); direct = an.analyze(sd.load("profile"), sd.load("posts"), sd.load("comments"), {}, {}, None)
check("score identical to V1 analyze()", direct["scores"] == bysc["botty"]["scores"])
check("V1 /api/profile works on browser-collected user", c.get("/api/profile/botty").status_code == 200)
# pause / resume / stop
ctl(action="pause"); r = c.post("/api/bridge/in/records", json={"records":[rec("botty","x y z a b c d e",1)]}, headers=T).get_json()
check("paused => records not accepted", r["accepted"] == 0 and r["state"] == "paused")
check("resume ok", ctl(action="resume").status_code == 200 and st()["state"] == "running")
# challenge
hb(challenge="captcha"); s = st()
check("captcha pauses collection + notifies", s["state"] == "paused" and s["challenge"] == "captcha" and any("captcha" in e["msg"] for e in s["errors"]))
hb(); check("still paused after challenge cleared until user resumes", st()["state"] == "paused")
check("explicit resume recovers", ctl(action="resume").status_code == 200 and st()["state"] == "running" and st()["challenge"] is None)
# disconnect / reconnect
BRIDGE.last_hb = time.time()-60
s = st(); check("disconnect: not shown as active", s["effective"].startswith("disconnected") and "NOT active" in s["effective"])
hb(); check("reconnect", st()["connected"] and st()["effective"] in ("active","running - waiting for results"))
# 'active' only when records recent
BRIDGE.last_ok = time.time()-300; BRIDGE.hold_until = 0; check("no recent records => not 'active'", st()["effective"] == "running - waiting for results")
# clear session keeps history
files_before = len(list((store.ROOT/"botty").glob("*.json")))
ctl(action="clear"); s = st()
check("clear session resets counters", s["posts"] == 0 and s["accounts_found"] == 0)
check("clear session keeps saved data", len(list((store.ROOT/"botty").glob("*.json"))) == files_before)
# profile enrichment path
ctl(action="start", query="x", max_posts=500); c.post("/api/bridge/in/records", json={"records":[rec("newguy","some words here to be a post ok",5)]}, headers=T)
check("enrich command queued for accounts w/o profile", ctl(action="enrich").status_code == 200 and any(x["action"] == "enrich" for x in hb()["commands"]))
c.post("/api/bridge/in/profile", json={"profile":{"username":"newguy","name":"New","bio":"hi","location":"India","joined":"Joined March 2019","followers":12,"following":30}}, headers=T)
p = store.Store("newguy").load("profile"); check("profile merged (age, followers)", p["created_at"].startswith("2019-03") and p["followers"] == 12)
ctl(action="stop"); check("stop", st()["state"] == "stopped")
check("clear_browser command goes to connected app", ctl(action="clear_browser").status_code == 200 and any(x["action"] == "clear_browser" for x in hb()["commands"]))
# logs
txt = log.getvalue().lower()
check("no credentials/cookies in logs", not any(k in txt for k in ("auth_token", "ct0=", "x-bridge-token", BRIDGE.token.lower())))
# V1 endpoints
check("V1 endpoints still respond", all(c.get(u).status_code == 200 for u in ("/", "/api/users", "/api/job", "/api/settings", "/api/version")))
shutil.rmtree(tmp, ignore_errors=True)
print("\nFAILURES:", ok); sys.exit(1 if ok else 0)
