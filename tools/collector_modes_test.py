# Author: gorcoding
# Runs collector.js (step modes) in real headless Chromium against MOCK pages that imitate x.com markup.
# Validates logic only - NOT real x.com. Requires: pip install playwright + a chromium build.
import glob, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
JS = (Path(__file__).resolve().parent.parent/"android/app/src/main/assets/collector.js").read_text()
STUB = "window.__msgs=[];window.XBSBridge={postMessage:function(s){window.__msgs.push(JSON.parse(s))}};"
def art(user, pid, text, ctx="", reply=False):
    return f'''<div data-testid="cellInnerDiv"><article data-testid="tweet">{ctx}<div data-testid="User-Name"><div><span>N {user}</span></div><div><span>@{user}</span></div></div>
    {'<div>Replying to @x</div>' if reply else ''}<div data-testid="tweetText" lang="en">{text}</div>
    <a href="/{user}/status/{pid}"><time datetime="2026-11-01T10:00:00.000Z">Nov 1</time></a><div data-testid="like">5</div></article></div>'''
NAV = "<nav><a data-testid='AppTabBar_Profile_Link'>me</a></nav>"
PROFILE = NAV+'''<div data-testid="UserName"><div><span>Alice A</span></div><div><span>@alice</span></div></div><div data-testid="UserDescription">Bio here</div>
<span data-testid="UserLocation">Delhi, India</span><span data-testid="UserJoinDate">Joined March 2019</span>
<a href="/alice/verified_followers"><span>1.2K Followers</span></a><a href="/alice/following"><span>340 Following</span></a>'''
POSTS = PROFILE + art("alice","1000000000000000001","first post") + art("alice","1000000000000000002","second post") + \
        art("bobby","1000000000000000003","other author pinned context") + art("alice","1000000000000000004","reposted", ctx='<div data-testid="socialContext">Alice reposted</div>')
REPLIES = NAV + art("bobby","1000000000000000010","parent tweet by bobby") + art("alice","1000000000000000011","my reply no label") + \
          art("alice","1000000000000000012","reply with label", reply=True) + art("alice","1000000000000000013","an original post")
def cell(u, bio): return f'<div data-testid="UserCell"><a href="/{u}" role="link"><img></a><div><span>{u.upper()}</span></div><div><span>@{u}</span></div><div><span>Follow</span></div><div>{bio}</div></div>'
FOLLOWERS = NAV + cell("f1","likes politics") + cell("f2","india fan") + cell("f3","")
PAGES = {"/alice": POSTS, "/alice/with_replies": REPLIES, "/alice/followers": FOLLOWERS}
fails = 0
def check(n, c):
    global fails; print(("PASS " if c else "FAIL ")+n); fails += 0 if c else 1
exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome") or [None])[0]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]); ctx = b.new_context()
    ctx.route("https://x.com/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<html><body>"+PAGES.get(r.request.url.replace("https://x.com","").split("?")[0], "")+"</body></html>"))
    ctx.add_init_script(STUB+JS)
    def run(path, mode, seq, wait=1800):
        pg = ctx.new_page(); pg.goto("https://x.com"+path)
        pg.evaluate("m=>__xbs.ctl({active:true,seq:%d,mode:m})" % seq, mode); pg.wait_for_timeout(wait)
        m = pg.evaluate("__msgs"); pg.close(); return m
    m = run("/alice", {"kind":"profile","target":"Alice"}, 1, 800)
    pr = [x for x in m if x["t"] == "profile"]
    check("profile step: header read once, seq attached", len(pr) == 1 and pr[0]["seq"] == 1 and pr[0]["profile"]["followers"] == 1200 and pr[0]["profile"]["location"] == "Delhi, India")
    check("profile step sends no tweets", not [x for x in m if x["t"] == "records"])
    m = run("/alice", {"kind":"posts","target":"Alice"}, 2)
    recs = [r for x in m if x["t"] == "records" for r in x["records"]]
    check("posts step: only target's own posts (case-insensitive); repost + other author skipped", [r["id"] for r in recs] == ["1000000000000000001","1000000000000000002"])
    check("posts carry seq", all(x["seq"] == 2 for x in m if x["t"] == "records"))
    m = run("/alice/with_replies", {"kind":"replies","target":"alice"}, 3)
    recs = {r["id"][-2:]: r["kind"] for x in m if x["t"] == "records" for r in x["records"]}
    check("replies step: parent (other author) skipped; reply under parent detected w/o label; labelled reply detected; original post is a post",
          recs == {"11": "comment", "12": "comment", "13": "post"} or recs == {"11": "comment", "12": "comment", "13": "post"})
    m = run("/alice/followers", {"kind":"followers","target":"alice"}, 4)
    rel = [u for x in m if x["t"] == "relations" for u in x["users"]]
    check("followers step: users with names and bios, buttons stripped", [u["username"] for u in rel] == ["f1","f2","f3"] and rel[0]["bio"] == "likes politics" and rel[2]["bio"] == "")
    check("relations message tagged with kind+seq", all(x["kind"] == "followers" and x["seq"] == 4 for x in m if x["t"] == "relations"))
    m = run("/alice", {"kind":"replies","target":"alice"}, 5, 3500)
    check("wrong page for step (replies mode on profile page) => nothing collected", not [x for x in m if x["t"] in ("records","relations")])
    st = [x for x in m if x["t"] == "state"]
    check("diagnostics report scope=false there", st and st[-1]["diag"]["scope"] is False and st[-1]["diag"]["articles"] >= 3)
    pg = ctx.new_page(); pg.goto("https://x.com/alice"); pg.evaluate("__xbs.ctl({active:true,seq:7,mode:{kind:'posts',target:'alice'}})"); pg.wait_for_timeout(1500)
    n1 = len([1 for x in pg.evaluate("__msgs") if x["t"] == "records"]); pg.evaluate("__xbs.ctl({seq:8,mode:{kind:'posts',target:'zed'}})"); pg.wait_for_timeout(1500)
    check("changing step resets state (seen) and re-scopes; new target => no records", n1 == 1 and len([1 for x in pg.evaluate("__msgs") if x["t"] == "records"]) == 1)
    b.close()
print("FAILURES:", fails); sys.exit(1 if fails else 0)
