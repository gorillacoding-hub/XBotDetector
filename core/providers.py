# Author: gorcoding
import re, html
from datetime import datetime, timezone

def _txt(h): return html.unescape(re.sub(r"<[^>]+>","",re.sub(r"<br\s*/?>","\n",h or ""))).strip()
def _first(p,s,fl=re.S):
    m=re.search(p,s or "",fl); return m.group(1) if m else ""
def _kind(text,reply,rt=False):
    return "comment" if reply else "post"

class ApiProvider:
    """Official X API v2 (needs a bearer token)."""
    base="https://api.twitter.com/2"
    def __init__(s,http,cfg):
        s.h=http; s.tok=cfg.get("bearer","").strip()
        if not s.tok: raise RuntimeError("Bearer token missing (Settings)")
    def _g(s,path,params):
        return s.h.get(s.base+path,params,headers={"Authorization":"Bearer "+s.tok}).json()
    def profile(s,u):
        j=s._g(f"/users/by/username/{u}",{"user.fields":"created_at,description,location,public_metrics,verified,profile_image_url,protected"})
        if "data" not in j: raise RuntimeError("API: "+str(j)[:300])
        d=j["data"]; m=d.get("public_metrics",{})
        return dict(id=d["id"],username=d["username"],name=d.get("name"),bio=d.get("description",""),location=d.get("location",""),
            created_at=d.get("created_at"),followers=m.get("followers_count"),following=m.get("following_count"),
            tweets=m.get("tweet_count"),verified=d.get("verified"),avatar=(d.get("profile_image_url") or "").replace("_normal","_400x400"))
    def timeline(s,prof,cursor,since=None,until=None):
        p={"max_results":100,"tweet.fields":"created_at,lang,referenced_tweets,in_reply_to_user_id,source,public_metrics"}
        if cursor: p["pagination_token"]=cursor
        if since: p["since_id"]=since
        if until: p["until_id"]=until
        j=s._g(f"/users/{prof['id']}/tweets",p)
        if "errors" in j and "data" not in j and "meta" not in j: raise RuntimeError("API: "+str(j)[:300])
        out=[]
        for t in j.get("data",[]):
            refs=[r["type"] for r in t.get("referenced_tweets",[])]
            rt="retweeted" in refs
            out.append(dict(id=t["id"],text=t["text"],ts=t["created_at"],lang=t.get("lang"),source=t.get("source",""),
                kind="comment" if ("replied_to" in refs or t.get("in_reply_to_user_id")) else "post",rt=rt,
                likes=t.get("public_metrics",{}).get("like_count")))
        return out,j.get("meta",{}).get("next_token")
    def relations(s,prof,kind,cursor):
        p={"max_results":1000,"user.fields":"description,location,public_metrics,created_at"}
        if cursor: p["pagination_token"]=cursor
        j=s._g(f"/users/{prof['id']}/{kind}",p)
        out=[dict(username=u["username"],name=u.get("name"),bio=u.get("description",""),location=u.get("location",""),
                  followers=u.get("public_metrics",{}).get("followers_count")) for u in j.get("data",[])]
        return out,j.get("meta",{}).get("next_token")

_FMT=["%b %d, %Y · %I:%M %p UTC","%I:%M %p - %d %b %Y","%d %b %Y"]
def _date(s):
    s=(s or "").replace("\u202f"," ").strip()
    for f in _FMT:
        try: return datetime.strptime(s,f).replace(tzinfo=timezone.utc).isoformat()
        except ValueError: pass
    return None

class NitterProvider:
    """Front-end scraping of a Nitter instance (public or self-hosted). Best effort - markup varies by instance."""
    def __init__(s,http,cfg): s.h=http; s.base=cfg["nitter"].rstrip("/")
    def profile(s,u):
        h=s.h.get(f"{s.base}/{u}").text
        if "profile-card" not in h: raise RuntimeError("Profile not found or instance returned no profile card")
        def stat(c):
            v=_first(rf'class="{c}">.*?profile-stat-num">([\d,]*)<',h).replace(",",""); return int(v) if v else None
        av=_first(r'class="profile-card-avatar"[^>]*href="([^"]+)"',h)
        return dict(id=u,username=u,name=_txt(_first(r'class="profile-card-fullname"[^>]*>([^<]*)<',h)),
            bio=_txt(_first(r'class="profile-bio">(.*?)</div>',h)),location=_txt(_first(r'class="profile-location">.*?<span>([^<]*)</span>',h)),
            created_at=_date(_first(r'profile-joindate">.*?title="([^"]+)"',h)),followers=stat("followers"),following=stat("following"),
            tweets=stat("posts"),verified='icon-ok verified-icon' in h,avatar=(s.base+av) if av.startswith("/") else av)
    def _cursor(s,h):
        c=re.findall(r'class="show-more"><a href="\?cursor=([^"]+)"',h)
        return html.unescape(c[-1]) if c else None
    def timeline(s,prof,cursor,since=None,until=None):
        h=s.h.get(f"{s.base}/{prof['username']}/with_replies",{"cursor":cursor} if cursor else None).text
        out=[]
        for ch in h.split('class="timeline-item')[1:]:
            tid=_first(r'/status/(\d+)',ch)
            if not tid: continue
            ts=_date(_first(r'class="tweet-date"><a[^>]*title="([^"]+)"',ch))
            if not ts: continue
            rt='class="retweet-header"' in ch
            out.append(dict(id=tid,text=_txt(_first(r'class="tweet-content[^"]*"[^>]*>(.*?)</div>',ch)),ts=ts,
                kind="comment" if 'class="replying-to"' in ch else "post",rt=rt,source="",lang=None))
        return out,s._cursor(h)
    def relations(s,prof,kind,cursor):
        h=s.h.get(f"{s.base}/{prof['username']}/{kind}",{"cursor":cursor} if cursor else None).text
        out=[]
        for ch in h.split('class="timeline-item')[1:]:
            un=_first(r'class="username"[^>]*>@([^<]+)<',ch)
            if un: out.append(dict(username=un,name=_txt(_first(r'class="fullname"[^>]*>(.*?)</a>',ch)),
                bio=_txt(_first(r'class="(?:tweet-bio|tweet-content)[^"]*"[^>]*>(.*?)</div>',ch)),location="",followers=None))
        return out,s._cursor(h)

def make(name,http,cfg):
    return ApiProvider(http,cfg) if name=="api" else NitterProvider(http,cfg)
