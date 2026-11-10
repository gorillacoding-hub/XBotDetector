from pathlib import Path
import re
import shutil
import sys

ROOT = Path.cwd()
FILES = [
    "core/bridge.py",
    "app.py",
    "android/app/src/main/assets/collector.js",
    "android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
    "static/index.html",
]
for f in FILES:
    if not (ROOT / f).is_file():
        sys.exit("Missing file: " + f + "\nRun this script from the XBotDetector repository root.")

def patch(path, old, new, count=1):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    n = s.count(old)
    if n != count:
        sys.exit(f"Patch stopped: {path}: expected {count} anchor(s), found {n}. No further files changed.")
    p.write_text(s.replace(old, new, count), encoding="utf-8")

# Back up every file before changing anything.
for f in FILES:
    p = ROOT / f
    shutil.copy2(p, p.with_suffix(p.suffix + ".fullfetch.bak"))

# ----------------------------------------------------------------------
# BACKEND: dedicated browser full-fetch state and ingestion.
# Existing search ingest() and core/analyze.py remain untouched.
# ----------------------------------------------------------------------
patch("core/bridge.py",
'''        s.app_ver=""; s.commands=[]; s.stop_reason=""; s.clear_session()
''',
'''        s.app_ver=""; s.commands=[]; s.stop_reason=""
        s.full={"status":"idle","username":"","stage":"","profile_only":False,
                "limits":{"posts":500,"comments":500,"followers":200,"following":200},
                "counts":{"posts":0,"comments":0,"followers":0,"following":0},
                "message":"","started":0,"finished":0}
        s.clear_session()
''')

anchor = '''    # ---- analysis (existing V1 engine, unchanged)
'''
insert = '''    # ---- dedicated full-profile browser ingestion
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

'''
patch("core/bridge.py", anchor, insert + anchor)

# Add full-fetch control actions before the unknown-action branch.
patch("core/bridge.py",
'''            elif a=="clear_browser":
                if not conn: return bad("browser not connected")
                s.commands.append({"action":"clear_browser"})
            else: return bad("unknown action")
''',
'''            elif a=="full_fetch":
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
''')

patch("core/bridge.py",
'''                "accounts":accs,"clusters":cl[:10]}
''',
'''                "accounts":accs,"clusters":cl[:10],"full_fetch":dict(s.full)}
''')

# ----------------------------------------------------------------------
# Flask endpoint for full-fetch messages.
# ----------------------------------------------------------------------
patch("app.py",
'''@app.get("/api/bridge/status")
def b_status(): return jsonify(BRIDGE.status())
''',
'''@app.post("/api/bridge/in/full")
@bridge_auth
def b_full():
    return jsonify(BRIDGE.full_ingest(request.get_json(silent=True) or {}))

@app.get("/api/bridge/status")
def b_status(): return jsonify(BRIDGE.status())
''')

# ----------------------------------------------------------------------
# COLLECTOR: public DOM extraction for profile, timeline, replies,
# followers and following. Existing search scan() is not modified.
# ----------------------------------------------------------------------
patch("android/app/src/main/assets/collector.js",
'''  function ctl(o) {
''',
'''  // ---- full profile collection: public, rendered X page DOM only
  var FULL = null;
  function fullProfile() {
    var m=location.pathname.match(/^\\\\/(\\\\w{1,15})(?:\\\\/|$)/);
    if(!m) return null;
    var un=document.querySelector('[data-testid="UserName"]');
    if(!un || un.querySelector('[data-testid="icon-lock"]')) return null;
    function q(sel){var e=document.querySelector(sel);return e?(e.innerText||"").trim():"";}
    function fol(suffix){var a=document.querySelector('a[href$="/'+suffix+'"]');return a?num(a.innerText):null;}
    var av=document.querySelector('[data-testid="UserAvatar-Container-unknown"] img, img[src*="profile_images"]');
    return {username:m[1],name:((un.innerText||"").split("\\\\n")[0]||"").slice(0,80),
      bio:q('[data-testid="UserDescription"]'),location:q('[data-testid="UserLocation"]'),
      joined:q('[data-testid="UserJoinDate"]'),followers:fol("followers"),
      following:fol("following"),avatar:av?av.src:""};
  }
  function fullSendProgress(msg) {
    send({t:"full_progress",stage:FULL?FULL.kind:"",message:msg||""});
  }
  function fullScan() {
    if(!FULL || challenge()) return;
    var out=[];
    if(FULL.kind==="followers" || FULL.kind==="following") {
      document.querySelectorAll('[data-testid="UserCell"]').forEach(function(cell){
        var a=cell.querySelector('a[href^="/"]');
        if(!a) return;
        var m=(a.getAttribute("href")||"").match(/^\\\\/(\\\\w{1,15})\\\\/?$/);
        if(!m || FULL.seen.has(m[1].toLowerCase())) return;
        FULL.seen.add(m[1].toLowerCase());
        var nm=cell.querySelector('[data-testid="User-Name"]');
        var bio=cell.querySelector('[data-testid="UserDescription"]');
        var loc=cell.querySelector('[data-testid="UserLocation"]');
        out.push({username:m[1],name:nm?(nm.innerText||"").split("\\\\n")[0]:"",
          bio:bio?bio.innerText:"",location:loc?loc.innerText:""});
      });
      if(out.length) send({t:"full_relations",kind:FULL.kind,users:out});
    } else {
      tweets().forEach(function(a){
        if(a.parentElement && a.parentElement.closest("article")) return;
        var t=a.querySelector("time"),link=t&&t.closest("a");
        var m=link&&(link.getAttribute("href")||"").match(/^\\\\/(\\\\w{1,15})\\\\/status\\\\/(\\\\d+)/);
        if(!t||!m||m[1].toLowerCase()!==FULL.username.toLowerCase()||FULL.seen.has(m[2])) return;
        FULL.seen.add(m[2]);
        var tx=a.querySelector('[data-testid="tweetText"]'),nm=a.querySelector('[data-testid="User-Name"]');
        var av=a.querySelector('[data-testid="Tweet-User-Avatar"] img');
        out.push({id:m[2],username:m[1],name:nm?(nm.innerText||"").split("\\\\n")[0]:"",
          text:tx?tx.innerText:"",ts:t.getAttribute("datetime"),
          kind:FULL.kind==="comments"?"comment":"post",
          verified:!!a.querySelector('[data-testid="icon-verified"]'),avatar:av?av.src:"",
          lang:tx?tx.getAttribute("lang"):null,replies:metric(a,"reply"),
          reposts:metric(a,"retweet"),likes:metric(a,"like")});
      });
      if(out.length) send({t:"full_records",kind:FULL.kind,records:out});
    }
    var count=FULL.seen.size;
    fullSendProgress(FULL.kind+": "+count+" collected");
    if(count>=FULL.limit) { fullFinish("limit reached"); return; }
    var h=document.documentElement.scrollHeight;
    FULL.stuck=(h===FULL.lastH)?FULL.stuck+1:0; FULL.lastH=h;
    if(FULL.stuck>=5) { fullFinish("end of available page results"); return; }
    window.scrollBy({top:Math.round(window.innerHeight*.8),behavior:"smooth"});
    FULL.timer=setTimeout(fullScan,3500+Math.random()*1800);
  }
  function fullFinish(reason) {
    if(!FULL) return;
    var kind=FULL.kind;
    clearTimeout(FULL.timer);
    FULL=null;
    send({t:"full_done",kind:kind,message:reason||"complete"});
  }
  function startFull(kind,username,limit) {
    clearTimeout(FULL&&FULL.timer);
    FULL={kind:kind,username:username,limit:Math.max(0,Number(limit)||0),
      seen:new Set(),stuck:0,lastH:0,timer:null};
    if(kind==="profile") {
      var p=fullProfile();
      if(p) send({t:"full_profile",profile:p});
      fullFinish(p?"profile collected":"profile not available (protected or page not loaded)");
      return;
    }
    if(FULL.limit===0) { fullFinish("limit set to zero"); return; }
    fullScan();
  }

  function ctl(o) {
''')

patch("android/app/src/main/assets/collector.js",
'''  window.__xbs = { ctl: ctl, profile: profile };
''',
'''  window.__xbs = { ctl: ctl, profile: profile, startFull: startFull, stopFull: function(){fullFinish("stopped");} };
''')

# ----------------------------------------------------------------------
# ANDROID: receive full-fetch commands and coordinate profile -> posts ->
# replies -> followers -> following using visible X pages.
# ----------------------------------------------------------------------
patch("android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
'''    private var enriching = false
''',
'''    private var enriching = false
    private var fullRunning = false
    private var fullUser = ""
    private var fullOnlyProfile = false
    private var fullLimits = JSONObject()
    private val fullStages = ArrayDeque<String>()
    private var fullStage = ""
''')

patch("android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
'''            "profile" -> {
                val body = JSONObject().put("profile", o.optJSONObject("profile") ?: JSONObject())
                client.post("/api/bridge/in/profile", body) { }
            }
''',
'''            "profile" -> {
                val body = JSONObject().put("profile", o.optJSONObject("profile") ?: JSONObject())
                client.post("/api/bridge/in/profile", body) { }
            }
            "full_profile" -> {
                val body=JSONObject().put("kind","profile")
                    .put("profile",o.optJSONObject("profile") ?: JSONObject())
                client.post("/api/bridge/in/full",body) { }
            }
            "full_records" -> {
                val body=JSONObject().put("kind",o.optString("kind"))
                    .put("records",o.optJSONArray("records") ?: JSONArray())
                client.post("/api/bridge/in/full",body) { }
            }
            "full_relations" -> {
                val body=JSONObject().put("kind",o.optString("kind"))
                    .put("users",o.optJSONArray("users") ?: JSONArray())
                client.post("/api/bridge/in/full",body) { }
            }
            "full_progress" -> {
                val body=JSONObject().put("kind","progress")
                    .put("stage",o.optString("stage")).put("message",o.optString("message"))
                client.post("/api/bridge/in/full",body) { }
            }
            "full_done" -> onFullStageDone(o.optString("kind"),o.optString("message"))
''')

patch("android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
'''            "clear_browser" -> clearSession()
''',
'''            "full_fetch" -> {
                if (fullRunning) return
                fullUser=o.optString("username")
                fullOnlyProfile=o.optBoolean("profile_only",false)
                fullLimits=o.optJSONObject("limits") ?: JSONObject()
                fullStages.clear()
                fullStages.addLast("profile")
                if (!fullOnlyProfile) {
                    fullStages.addLast("posts")
                    fullStages.addLast("comments")
                    fullStages.addLast("followers")
                    fullStages.addLast("following")
                }
                fullRunning=true
                enriching=true
                runNextFullStage()
            }
            "stop_full" -> {
                fullRunning=false; enriching=false; fullStages.clear()
                web.evaluateJavascript("window.__xbs&&window.__xbs.stopFull()",null)
                updateStatus()
            }
            "clear_browser" -> clearSession()
''')

patch("android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
'''    // ---------- optional slow profile enrichment (user-triggered from the dashboard)
''',
'''    // ---------- full profile fetch (public rendered DOM only)
    private fun runNextFullStage() {
        if (!fullRunning) return
        if (pageChallenge != null) {
            ui.postDelayed({ runNextFullStage() },3000); return
        }
        if (fullStages.isEmpty()) {
            fullRunning=false; enriching=false
            client.post("/api/bridge/in/full",JSONObject().put("kind","done")
                .put("message","Browser full fetch completed")) { }
            pushControl(); updateStatus(); return
        }
        fullStage=fullStages.removeFirst()
        val suffix=when(fullStage) {
            "profile","posts" -> ""
            "comments" -> "/with_replies"
            "followers" -> "/followers"
            "following" -> "/following"
            else -> ""
        }
        web.loadUrl("https://x.com/$fullUser$suffix")
        ui.postDelayed({
            if (!fullRunning) return@postDelayed
            val limit=fullLimits.optInt(fullStage,500)
            val js="window.__xbs&&window.__xbs.startFull(" +
                "'$fullStage','$fullUser',$limit)"
            web.evaluateJavascript(js,null)
            updateStatus()
        },6500)
    }

    private fun onFullStageDone(kind:String,message:String) {
        if (!fullRunning || kind!=fullStage) return
        client.post("/api/bridge/in/full",JSONObject().put("kind","progress")
            .put("stage",kind).put("message",message)) { }
        ui.postDelayed({ runNextFullStage() },2500L+(2500..5000).random())
    }

    // ---------- optional slow profile enrichment (user-triggered from the dashboard)
''')

patch("android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
'''        enrichQueue.clear(); enriching = false
''',
'''        enrichQueue.clear(); enriching = false
        fullRunning=false; fullStages.clear()
''')

patch("android/app/src/main/java/com/gorcoding/xbotscope/MainActivity.kt",
'''            (if (enriching) " · enriching ${enrichQueue.size} left" else "") +
''',
'''            (if (fullRunning) " · full fetch @${fullUser}: $fullStage" else "") +
            (if (enriching && !fullRunning) " · enriching ${enrichQueue.size} left" else "") +
''')

# ----------------------------------------------------------------------
# DASHBOARD: independent browser full-fetch form and live progress.
# ----------------------------------------------------------------------
patch("static/index.html",
''' <div id="bacc" style="margin-top:10px"></div><div id="bclu"></div><div id="berr"></div></div>
''',
''' <div class="card" style="margin-top:10px">
  <h3>Browser · Full profile fetch</h3>
  <label>Public X username</label><input id="bfuser" placeholder="@username" autocapitalize="off">
  <label><input id="bfonly" type="checkbox" style="width:auto"> Profile only (skip posts, replies, followers and following)</label>
  <div class="row">
   <div><label>Posts</label><input id="bfposts" type="number" min="0" max="5000" value="500"></div>
   <div><label>Replies</label><input id="bfcomments" type="number" min="0" max="5000" value="500"></div>
   <div><label>Followers</label><input id="bffollowers" type="number" min="0" max="5000" value="200"></div>
   <div><label>Following</label><input id="bffollowing" type="number" min="0" max="5000" value="200"></div>
  </div>
  <button onclick="startBrowserFull()">Start full fetch</button>
  <button class="dng" onclick="bc('stop_full')">Stop full fetch</button>
  <div id="bfullstatus" class="mu" style="margin-top:8px">No browser full fetch running.</div>
 </div>
 <div id="bacc" style="margin-top:10px"></div><div id="bclu"></div><div id="berr"></div></div>
''')

patch("static/index.html",
'''async function bc(action){const o={action};if(action=='start')Object.assign(o,{query:$('#bq').value,sort:$('#bsort').value,max_posts:+$('#bmax').value,min_items:+$('#bmin').value,autoscroll:$('#bauto').checked});
 const r=await api('/api/bridge/control',o);if(!r.ok)alert(r.error||'failed');bstat(true)}
''',
'''async function bc(action){const o={action};if(action=='start')Object.assign(o,{query:$('#bq').value,sort:$('#bsort').value,max_posts:+$('#bmax').value,min_items:+$('#bmin').value,autoscroll:$('#bauto').checked});
 const r=await api('/api/bridge/control',o);if(!r.ok)alert(r.error||'failed');bstat(true)}
async function startBrowserFull(){
 const username=$('#bfuser').value.trim().replace(/^@/,'');
 if(!username){alert('Enter an X username');return}
 const o={action:'full_fetch',username,profile_only:$('#bfonly').checked,
  posts:+$('#bfposts').value,comments:+$('#bfcomments').value,
  followers:+$('#bffollowers').value,following:+$('#bffollowing').value};
 const r=await api('/api/bridge/control',o);
 if(!r.ok)alert(r.error||'Could not start full fetch');
 bstat(true);
}
''')

patch("static/index.html",
''' $('#bver').textContent='v'+b.version;
 const ok=b.effective=='active',warn=b.challenge||!b.connected;
''',
''' $('#bver').textContent='v'+b.version;
 const f=b.full_fetch||{};
 $('#bfullstatus').innerHTML=f.status==='idle'?'No browser full fetch running.':
  `<b>${esc(f.status)}</b> · @${esc(f.username)} · ${esc(f.stage)}<br>${esc(f.message||'')}
   <br>Posts: ${f.counts?.posts||0} · Replies: ${f.counts?.comments||0}
   · Followers: ${f.counts?.followers||0} · Following: ${f.counts?.following||0}`;
 const ok=b.effective=='active',warn=b.challenge||!b.connected;
''')

print("Full-fetch patch applied.")
print("Backups: *.fullfetch.bak")
print("Next: run the validation/build commands shown below.")
