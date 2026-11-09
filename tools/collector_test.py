# Author: gorcoding
# Runs android/app/src/main/assets/collector.js in a real headless Chromium against a MOCK page that imitates
# x.com's data-testid markup (https://x.com is intercepted; no network). Requires: pip install playwright + a chromium build.
# This validates the extraction/pause/challenge logic only - NOT real x.com, which can change its markup at any time.
import json, sys, glob
from pathlib import Path
from playwright.sync_api import sync_playwright
JS = (Path(__file__).resolve().parent.parent/"android/app/src/main/assets/collector.js").read_text()
STUB = "window.__msgs=[];window.XBSBridge={postMessage:function(s){window.__msgs.push(JSON.parse(s))}};"
def art(user, pid, text, extra="", ctx="", lock=False, reply=False):
    return f'''<article data-testid="tweet">{ctx}<div data-testid="Tweet-User-Avatar"><img src="https://pbs.twimg.com/profile_images/1/a_normal.jpg"></div>
    <div data-testid="User-Name"><div><span>Name {user}</span></div><div><span>@{user}</span></div>{'<svg data-testid="icon-lock"></svg>' if lock else ''}<svg data-testid="icon-verified"></svg></div>
    {'<div>Replying to @someone</div>' if reply else ''}<div data-testid="tweetText" lang="en">{text}</div>
    <a href="/{user}/status/{pid}"><time datetime="2026-11-01T10:00:00.000Z">Nov 1</time></a>
    <div role="group"><div data-testid="reply">12</div><div data-testid="retweet">1.5K</div><div data-testid="like"></div></div>
    <a href="/{user}/status/{pid}/analytics">2.3M</a></article>'''
SEARCH = "<html><body><nav><a data-testid='AppTabBar_Profile_Link'>me</a></nav><main>" + "".join([
    art("alice","1000000000000000001","Europe politics is <b>heated</b> today"),
    art("bob","1000000000000000002","a reply here", reply=True),
    art("carol","1000000000000000003","reposted thing", ctx='<div data-testid="socialContext">Dave reposted</div>'),
    art("erin","1000000000000000004","protected text", lock=True),
    art("alice","1000000000000000001","duplicate id should be ignored"),
]) + "</main></body></html>"
CAPTCHA = "<html><body><iframe src='https://client-api.arkoselabs.com/x'></iframe>" + art("alice","1000000000000000009","t") + "</body></html>"
PROFILE = """<html><body><div data-testid="UserName"><div><span>Alice A</span></div><div><span>@alice</span></div></div><div data-testid="UserDescription">Bio here</div>
<span data-testid="UserLocation">Delhi, India</span><span data-testid="UserJoinDate">Joined March 2019</span>
<a href="/alice/verified_followers"><span>1.2K Followers</span></a><a href="/alice/following"><span>340 Following</span></a></body></html>"""
fails = 0
def check(n, c):
    global fails; print(("PASS " if c else "FAIL ")+n); fails += 0 if c else 1
exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome") or [None])[0]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]); ctx = b.new_context()
    pages = {"/search": SEARCH, "/captcha": CAPTCHA}
    def route(r):
        path = r.request.url.replace("https://x.com", "").split("?")[0]
        body = SEARCH if path == "/search" else CAPTCHA if path == "/search2" else PROFILE if path == "/alice" else "<html></html>"
        r.fulfill(status=200, content_type="text/html", body=body)
    ctx.route("https://x.com/**", route); ctx.add_init_script(STUB+JS)
    pg = ctx.new_page(); pg.goto("https://x.com/search?q=europe"); pg.wait_for_timeout(1500)
    check("inactive collector sends no records", not [m for m in pg.evaluate("__msgs") if m["t"] == "records"])
    pg.wait_for_timeout(2000)
    st = [m for m in pg.evaluate("__msgs") if m["t"] == "state"]
    pg.evaluate("__xbs.ctl({active:true})"); pg.wait_for_timeout(1500)
    recs = [r for m in pg.evaluate("__msgs") if m["t"] == "records" for r in m["records"]]
    check("2 records (post + reply); repost, protected, duplicate skipped", [r["id"] for r in recs] == ["1000000000000000001","1000000000000000002"])
    r = recs[0]
    check("fields: user/name/text/ts", r["username"] == "alice" and r["name"] == "Name alice" and r["text"].startswith("Europe politics is heated") and r["ts"] == "2026-11-01T10:00:00.000Z")
    check("metrics parsed (12, 1.5K=1500, empty=0, 2.3M)", (r["replies"], r["reposts"], r["likes"], r["views"]) == (12, 1500, 0, 2300000))
    check("reply detected as comment", recs[1]["kind"] == "comment" and r["kind"] == "post")
    check("auth/page state reported", any(s["auth"] == "logged_in" and s["page"] == "search" and s["challenge"] is None for s in st))
    pg.evaluate("__xbs.ctl({active:false}); __msgs.length=0; __xbs.ctl({reset:true})"); pg.wait_for_timeout(1500)
    pg.evaluate("document.querySelector('main').insertAdjacentHTML('beforeend', `%s`)" % art("zed","1000000000000000077","new while paused").replace("`","'"))
    pg.wait_for_timeout(1500)
    check("paused (active=false) => nothing collected even when DOM changes", not [m for m in pg.evaluate("__msgs") if m["t"] == "records"])
    pg2 = ctx.new_page(); pg2.goto("https://x.com/search2?q=x"); pg2.evaluate("__xbs.ctl({active:true})"); pg2.wait_for_timeout(3600)
    m2 = pg2.evaluate("__msgs")
    check("captcha iframe reported as challenge, no records sent", any(m["t"] == "state" and m["challenge"] == "captcha" for m in m2) and not [m for m in m2 if m["t"] == "records"])
    pg3 = ctx.new_page(); pg3.goto("https://x.com/alice"); pg3.evaluate("__xbs.profile()"); pg3.wait_for_timeout(300)
    pr = [m for m in pg3.evaluate("__msgs") if m["t"] == "profile"]
    check("profile read", pr and pr[0]["profile"]["location"] == "Delhi, India" and pr[0]["profile"]["followers"] == 1200 and pr[0]["profile"]["following"] == 340 and "March 2019" in pr[0]["profile"]["joined"])
    pg4 = ctx.new_page(); pg4.goto("https://x.com/alice"); pg4.evaluate("__xbs.ctl({active:true})"); pg4.wait_for_timeout(1000)
    check("not collecting outside /search", not [m for m in pg4.evaluate("__msgs") if m["t"] == "records"])
    b.close()
print("FAILURES:", fails); sys.exit(1 if fails else 0)
