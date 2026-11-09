# Author: gorcoding
import re, urllib.parse, html
from collections import Counter
from .geo import tld_country, COUNTRIES
URL=re.compile(r"https?://\S+|www\.\S+",re.I); MEN=re.compile(r"@\w+")
EXCL="-site:x.com -site:twitter.com -site:t.co -site:facebook.com -site:instagram.com"

def build(posts,n,tlds=""):
    seen=set(); out=[]; tl=[t.strip().strip(".") for t in (tlds or "").split(",") if t.strip()]
    for p in sorted(posts.values(),key=lambda x:x["ts"],reverse=True):
        if p.get("rt"): continue
        t=" ".join(MEN.sub(" ",URL.sub(" ",p["text"])).split()); w=t.split()
        if len(w)<8 or t.lower() in seen: continue
        seen.add(t.lower()); phrase=" ".join(w[:12])
        base=f'"{phrase}" {EXCL}'
        for suffix in ([""] if not tl else [f" site:.{x}" for x in tl]):
            out.append({"id":p["id"],"text":t[:200],"query":base+suffix})
            if len(out)>=n: return out
    return out

def links(q):
    e=urllib.parse.quote_plus(q)
    return {"google":"https://www.google.com/search?q="+e,"bing":"https://www.bing.com/search?q="+e,"ddg":"https://duckduckgo.com/?q="+e}

def search(http,q):
    r=http.get("https://html.duckduckgo.com/html/",{"q":q})
    res=[]
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',r.text,re.S):
        href=html.unescape(m.group(1))
        mm=re.search(r"uddg=([^&]+)",href)
        if mm: href=urllib.parse.unquote(mm.group(1))
        dom=urllib.parse.urlparse(href).netloc.lower().replace("www.","")
        if dom: res.append({"url":href,"domain":dom,"title":re.sub(r"<[^>]+>","",m.group(2)).strip(),"country":tld_country(dom)})
    return res

def aggregate(d):
    byc=Counter(); byd=Counter()
    for r in (d or {}).get("results",[]):
        for f in r.get("found",[]):
            byd[f["domain"]]+=1
            if f["country"]: byc[f["country"]]+=1
    return {"countries":[{"iso":k,"name":COUNTRIES[k]["name"],"n":v} for k,v in byc.most_common(15)],
            "domains":byd.most_common(20),"queries":len((d or {}).get("results",[]))}
