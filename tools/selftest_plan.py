# Author: gorcoding
# Tests the automatic plan engine (page switching at limits), relations, data manager, optional AI and pairing/settings security.
import sys, tempfile, time, shutil, io, logging, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import store
tmp = Path(tempfile.mkdtemp()); store.ROOT = tmp/"data"; store.SET = tmp/"settings.json"
from core.bridge import BRIDGE
import core.ai as AI
import app as A
from datetime import datetime, timedelta, timezone
log = io.StringIO(); logging.getLogger().addHandler(logging.StreamHandler(log))
c = A.app.test_client(); T = {"X-Bridge-Token": BRIDGE.token}; X = {"X-XBS": "1"}
bad = 0
def check(n, ok):
    global bad; print(("PASS " if ok else "FAIL ")+n); bad += 0 if ok else 1
def hb(**k): return c.post("/api/bridge/in/heartbeat", json=dict({"app":"2.1.0","auth":"logged_in","page":"other"}, **k), headers=T).get_json()
def ctl(**k): r = c.post("/api/bridge/control", json=k, headers=X); return r
def st(): return c.get("/api/bridge/status").get_json()
now = datetime.now(timezone.utc); n = [0]
VOC = 'garden tea music football dog walk rain kitchen bread coffee train book movie friend market river hill paint guitar lunch bike storm winter summer piano soup museum ticket window coast harbor camera recipe puzzle ladder orchard'.split()
def rec(u, kind, i=0, text=None):
    n[0] += 1
    return {"id": str(1900000000000000000+n[0]), "username": u, "name": u, "kind": kind, "ts": (now-timedelta(minutes=30*n[0])).isoformat(),
            "text": text or f"unique words {n[0]} alpha beta gamma delta epsilon zeta{n[0]%7} theta{n[0]%5} sample", "likes": 3, "views": 100}
def users(k, names): return [{"username": u, "name": u.upper(), "bio": f"bio of {u} politics"} for u in names]
def rec_post(seq, recs): return c.post("/api/bridge/in/records", json={"seq": seq, "records": recs}, headers=T).get_json()

hb()
# ---- plan: profile Alice -> posts(3) -> replies(2) -> followers(2) -> then search 'europe'(2)
r = ctl(action="start_plan", profiles="@Alice", posts=3, replies=2, followers=2, following=0, queries="europe lang:en", search_limit=2)
check("start_plan ok", r.status_code == 200)
s = st(); steps = s["plan"]["steps"]
check("steps built in order (no following step since limit 0)", [(x["kind"], x["limit"]) for x in steps] == [("profile",1),("posts",3),("replies",2),("followers",2),("search",2)])
h = hb(); check("heartbeat: opens profile page, mode=profile, hold active", any(x["action"]=="open" and x["url"]=="https://x.com/Alice" for x in h["commands"]) and h["mode"] == {"kind":"profile","target":"Alice"} and h["hold"])
seq = h["seq"]
check("stale seq ignored", rec_post(seq-1, [rec("Alice","post")])["accepted"] == 0)
check("records ignored during profile step", rec_post(seq, [rec("Alice","post")])["accepted"] == 0)
r = c.post("/api/bridge/in/profile", json={"seq": seq, "profile": {"username":"alice","name":"Alice A","bio":"hello","location":"Delhi, India","joined":"Joined March 2019","followers":1200,"following":340}}, headers=T).get_json()
h = hb(); check("profile step done -> advanced to posts, same URL not reloaded", st()["plan"]["index"] == 1 and h["mode"]["kind"] == "posts" and not any(x["action"]=="open" for x in h["commands"]))
seq = h["seq"]
mixed = [rec("Alice","post"), rec("someoneelse","post"), rec("Alice","comment"), rec("Alice","post"), rec("Alice","post"), rec("Alice","post")]
res = rec_post(seq, mixed)
check("posts step: only target's posts counted, stops at limit 3", res["accepted"] == 3 and st()["plan"]["steps"][1]["got"] == 3 and st()["plan"]["steps"][1]["status"] == "limit")
h = hb(); check("auto-switched to replies page", h["mode"] == {"kind":"replies","target":"Alice"} and any(x.get("url","").endswith("/Alice/with_replies") for x in h["commands"]))
seq = h["seq"]
res = rec_post(seq, [rec("Alice","post"), rec("Alice","comment"), rec("Alice","comment"), rec("Alice","comment")])
check("replies step: only replies, limit 2 then switch", res["accepted"] == 2 and st()["plan"]["index"] == 3)
h = hb(); check("auto-switched to followers page", h["mode"]["kind"] == "followers" and any(x.get("url","").endswith("/Alice/followers") for x in h["commands"])); seq = h["seq"]
r = c.post("/api/bridge/in/relations", json={"seq": seq, "kind": "following", "users": users("following", ["a"])}, headers=T).get_json()
check("wrong-kind relations ignored", r["accepted"] == 0)
r = c.post("/api/bridge/in/relations", json={"seq": seq, "kind": "followers", "users": users("followers", ["f1","f2","f3"])}, headers=T).get_json()
check("followers step: limit 2 then profile analysed", r["accepted"] == 2)
s = st()
check("profile analysed automatically when its steps finish", any(a["username"].lower() == "alice" and a["analysed"] for a in s["accounts"]))
fl = store.Store("alice").load("followers"); check("followers saved into the one canonical folder", sorted(fl) == ["f1","f2"])
check("analysis.json written for the profile", store.Store("alice").load("analysis")["n"] == 5)
h = hb(); check("auto-switched to the search step", h["mode"]["kind"] == "search" and any("search?q=europe%20lang%3Aen" in x.get("url","") for x in h["commands"])); seq = h["seq"]
res = rec_post(seq, [rec("zed","post"), rec("yan","post"), rec("xia","post")])
s = st(); check("search step limit 2 -> plan complete, state stopped", res["accepted"] == 2 and s["state"] == "stopped" and s["stop_reason"] == "plan complete")
check("no duplicate folders for case variants", len([p for p in store.ROOT.iterdir() if p.is_dir() and p.name.lower() == "alice"]) == 1)

# ---- end-of-results / stall / skip / pause
ctl(action="start_plan", profiles="bob", posts=50, replies=0, autoscroll=True); h = hb(); seq = h["seq"]
BRIDGE.hold_until = 0
hb(end=True, seq=seq-1); check("end flag with wrong seq ignored", st()["plan"]["index"] == 0)
c.post("/api/bridge/in/profile", json={"seq": seq, "profile": {"username":"bob","name":"Bob"}}, headers=T); h = hb(); seq = h["seq"]; BRIDGE.hold_until = 0
hb(end=True, seq=seq); check("end of results on posts page -> next step/finish", st()["plan"]["steps"][1]["status"] == "end" and st()["state"] == "stopped")
ctl(action="start_plan", profiles="carl", posts=50, replies=5); h = hb(); BRIDGE.hold_until = 0; BRIDGE.step_last = time.time()-100
hb(); check("stall (no progress) advances automatically", st()["plan"]["steps"][0]["status"] == "stalled" and st()["plan"]["index"] == 1)
check("skip action moves to next step", ctl(action="skip").status_code == 200 and st()["plan"]["steps"][1]["status"] == "skipped")
ctl(action="start_plan", profiles="dan", posts=5); BRIDGE.hold_until = 0; hb(); BRIDGE.step_last = time.time()-100
hb(challenge="captcha"); BRIDGE.step_last = time.time()-100; hb(challenge="captcha")
check("no stall-advance while paused on challenge", st()["plan"]["index"] == 0 and st()["state"] == "paused")
check("plan validation: nothing to do", ctl(action="start_plan", profiles="", queries="").status_code == 400)
check("plan accepts profile URLs and dedupes", (ctl(action="start_plan", profiles="https://x.com/Eve, @eve  twitter.com/Frank", posts=1).status_code == 200) and [x["target"] for x in st()["plan"]["steps"] if x["kind"] == "profile"] == ["Eve","Frank"])
ctl(action="stop")

# ---- data manager
ov = c.get("/api/manage/list").get_json(); names = {o["username"] for o in ov}
check("manager lists saved profiles with counts", "alice" in names and [o for o in ov if o["username"] == "alice"][0]["posts"] == 3)
check("export writes a file", c.post("/api/manage/export", json={"user":"alice"}, headers=X).get_json()["path"].startswith("data/exports/"))
check("path traversal rejected", c.post("/api/manage/delete", json={"users":["../data","..","../../etc"]}, headers=X).get_json()["deleted"] == [] and (store.ROOT/"alice").exists())
ctl(action="start_plan", profiles="alice", posts=5)
check("delete refused while plan uses the profile", c.post("/api/manage/delete", json={"users":["alice"]}, headers=X).status_code == 409)
ctl(action="stop")
check("delete part (followers)", c.post("/api/manage/delete_part", json={"user":"alice","parts":["followers","bogus"]}, headers=X).get_json()["deleted"] == ["followers"])
check("delete profile", c.post("/api/manage/delete", json={"users":["alice"]}, headers=X).get_json()["deleted"] == ["alice"] and not (store.ROOT/"alice").exists())
check("delete all needs typed confirmation", c.post("/api/manage/delete", json={"all":True}, headers=X).status_code == 400)
check("delete all", c.post("/api/manage/delete", json={"all":True,"confirm":"DELETE"}, headers=X).status_code == 200 and not [p for p in store.ROOT.iterdir() if p.is_dir() and p.name != "exports"])
check("bridge token survives delete-all", (store.ROOT/".bridge_token").exists())

# ---- optional AI
for u in ("ann",):
    s0 = store.Store(u); s0.save("profile", {"username":u,"name":"Ann Real","bio":"secret bio","location":"X","created_at":None,"followers":5,"following":5})
    s0.save("posts", {str(i): {"id":str(i),"text":f"secret post text {VOC[i%len(VOC)]} {VOC[(i*3+1)%len(VOC)]} {VOC[(i*7+2)%len(VOC)]} {VOC[(i*5+3)%len(VOC)]}","ts":(now-timedelta(hours=i)).isoformat(),"kind":"post","rt":False,"source":""} for i in range(30)}); s0.save("comments", {})
check("AI refused without consent", c.post("/api/ai/ann", headers=X).status_code == 403)
c.post("/api/settings", json={"ai_consent":True,"ai_key":"sk-test-123456","ai_provider":"anthropic","ai_model":"claude-haiku-5-5"}, headers=X)
sent = {}
class R:
    status_code = 200
    def __init__(s, j): s._j = j; s.text = json.dumps(j)
    def json(s): return s._j
def fake_post(url, headers=None, json=None, timeout=0):
    sent.update(url=url, headers=headers, body=json)
    if "anthropic" in url: return R({"content":[{"type":"text","text":'```json\n{"assessment":"inconclusive","confidence":"55","reasons":["small sample"]}\n```'}]})
    return R({"choices":[{"message":{"content":'{"assessment":"likely human","confidence":70,"reasons":["x"]}'}}]})
AI.requests.post = fake_post
r = c.post("/api/ai/ann", headers=X); j = r.get_json()
body = json_body = json.dumps(sent["body"])
check("AI call parsed (fenced JSON, str confidence)", r.status_code == 200 and j["assessment"] == "inconclusive" and j["confidence"] == 55)
check("AI default sends NO post text, bio or identity", "secret" not in body and "Ann" not in body and '"ann"' not in body.lower().replace("anthropic",""))
check("AI key only in provider header, hits anthropic url", sent["headers"]["x-api-key"] == "sk-test-123456" and sent["url"].startswith("https://api.anthropic.com/v1/messages"))
c.post("/api/settings", json={"ai_send_samples":True,"ai_n_samples":3,"ai_provider":"openai","ai_base_url":"http://127.0.0.1:11434/v1"}, headers=X)
j = c.post("/api/ai/ann", headers=X).get_json(); body = json.dumps(sent["body"])
check("samples mode sends capped untrusted samples (openai-compatible, local url)", j["assessment"] == "likely human" and sent["url"] == "http://127.0.0.1:11434/v1/chat/completions" and body.count("secret post text") == 3 and "sample_posts_UNTRUSTED" in body)
check("AI result saved to profile", store.Store("ann").load("ai")["confidence"] == 70 and c.get("/api/profile/ann").get_json()["ai"]["assessment"] == "likely human")
s = c.get("/api/settings").get_json(); check("secrets never returned to browser", s["ai_key"] == "••••saved" and "sk-test" not in json.dumps(s))
c.post("/api/settings", json={"ai_key":"••••saved"}, headers=X); check("masked value keeps stored secret", store.get_settings()["ai_key"] == "sk-test-123456")
check("empty value clears secret", (c.post("/api/settings", json={"ai_key":""}, headers=X), store.get_settings()["ai_key"] == "")[1])

# ---- pairing window
check("pairing locked by default", c.get("/api/bridge/pairing").get_json().get("locked") is True)
c.post("/api/bridge/pair/open", headers=X); p = c.get("/api/bridge/pairing").get_json()
check("pairing opens for a short window", p["token"] == BRIDGE.token); BRIDGE.pair_until = 0
check("pairing locks again", c.get("/api/bridge/pairing").get_json().get("locked") is True)
# ---- improved engine
from core.analyze import analyze
a = analyze({"created_at": "2020-01-01T00:00:00+00:00", "followers": 10}, {str(i): {"id":str(i),"text":(("economy " if i < 2 else "")+" ".join(VOC[(i*k+3)%len(VOC)] for k in (1,3,5,7,11))),"ts":(now-timedelta(hours=5*i)).isoformat(),"kind":"post","likes":2,"views":50} for i in range(40)}, {}, {}, {})
check("engine: confidence + engagement present; tiny-topic false positive suppressed",
      a["confidence"]["label"] in ("low","medium") and a["engagement"]["likes"] == 2 and [s for s in a["signals"] if s["name"] == "single-agenda content"][0]["value"] < 0.5)
txt = log.getvalue().lower(); check("no secrets in logs", "sk-test" not in txt and "auth_token" not in txt)
shutil.rmtree(tmp, ignore_errors=True); print("\nFAILURES:", bad); sys.exit(1 if bad else 0)
