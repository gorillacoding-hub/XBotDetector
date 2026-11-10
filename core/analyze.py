# Author: gorcoding
import re, statistics
from collections import Counter
from datetime import datetime, timezone
from .wordlist import STOP, TOPICS, BOT_WORDS, AUTO_CLIENTS
from .geo import COUNTRIES, country_of, parse_country, tz_candidates

URL=re.compile(r"https?://\S+|www\.\S+",re.I); MEN=re.compile(r"@\w+"); WRD=re.compile(r"[^\W\d_]{3,}")
W2T={w:t for t,ws in TOPICS.items() for w in ws.split()}

def clean(t): return MEN.sub(" ",URL.sub(" ",t or ""))
def toks(t): return WRD.findall(clean(t).lower())
def meaningful(t): return [w for w in toks(t) if w not in STOP]
def topic_of(w): return W2T.get(w) or W2T.get(w.rstrip("s"))
def ts(s):
    try: d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    except Exception: return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
def cl(x): return max(0.0,min(1.0,x))

def duplicates(items):
    norms=[" ".join(toks(i["text"])) for i in items]
    cnt=Counter(n for n in norms if len(n)>=15)
    exact={n for n,c in cnt.items() if c>=2}
    distinct=[n for n in cnt if len(n.split())>=6]; sets=[(n,set(n.split())) for n in distinct]; near=set()
    for a in range(len(sets)):
        na,sa=sets[a]
        for b in range(a+1,len(sets)):
            nb,sb=sets[b]
            if min(len(sa),len(sb))/max(len(sa),len(sb))<0.8: continue
            if len(sa&sb)/len(sa|sb)>=0.8: near.add(na); near.add(nb)
    dup_items=sum(1 for n in norms if n in exact or n in near)
    groups=[{"text":n[:140],"count":c} for n,c in cnt.most_common(15) if c>=2]
    tri=Counter()
    for i in items:
        w=toks(i["text"])
        tri.update({" ".join(w[k:k+3]) for k in range(len(w)-2) if not all(x in STOP for x in w[k:k+3])})
    return {"rate":dup_items/len(items) if items else 0,"groups":groups,"near_pairs":len(near),
            "phrases":[{"text":k,"count":v} for k,v in tri.most_common(15) if v>=3]}

def relations(users,user_words):
    ctry=Counter(); topics=Counter(); words=Counter(); scored=[]; unknown=0
    for u in users.values():
        txt=f"{u.get('location','')} {u.get('bio','')}"; c=country_of(u.get("location","")) or country_of(u.get("bio",""))
        if c: ctry[c]+=1
        else: unknown+=1
        ws=set(meaningful(u.get("bio",""))); words.update(ws)
        for w in ws:
            t=topic_of(w)
            if t: topics[t]+=1
        ov=ws&user_words
        if ov: scored.append((len(ov),u["username"],sorted(ov)[:6]))
    tot=sum(ctry.values()) or 1
    return {"n":len(users),"unknown":unknown,"countries":[{"iso":k,"name":COUNTRIES[k]["name"],"n":v,"pct":round(100*v/tot,1)} for k,v in ctry.most_common(12)],
            "topics":topics.most_common(10),"words":[w for w in words.most_common(25) if w[1]>=2],
            "similar":[{"user":u,"shared":o} for _,u,o in sorted(scored,reverse=True)[:10]]}

def analyze(prof,posts,comments,followers,following,about=None):
    items=[dict(i) for i in list(posts.values())+list(comments.values()) if ts(i.get("ts"))]
    for i in items: i["_t"]=ts(i["ts"])
    items.sort(key=lambda i:i["_t"]); n=len(items); out={"n":n}
    created=ts(prof.get("created_at")); now=datetime.now(timezone.utc)
    out["age_days"]=(now-created).days if created else None
    claimed=parse_country(about) if about else (country_of(prof.get("location","")) or country_of(prof.get("bio","")))
    out["claimed"]=claimed and {"iso":claimed,"name":COUNTRIES[claimed]["name"]}
    hours=[0]*24; wd=[0]*7
    for i in items: hours[i["_t"].hour]+=1; wd[i["_t"].weekday()]+=1
    out["hours"]=hours; out["weekdays"]=wd
    words=Counter(); tcnt=Counter(); twords=Counter(); botn=0; urls=0; rts=0; src=Counter(); langs=Counter()
    for i in items:
        low=i["text"].lower(); mw=meaningful(i["text"]); words.update(mw)
        for w in mw:
            t=topic_of(w)
            if t: tcnt[t]+=1; twords[w]+=1
        botn+= any(b in low for b in BOT_WORDS); urls+= bool(URL.search(i["text"])); rts+= bool(i.get("rt") or low.startswith("rt @"))
        if i.get("source"): src[re.sub(r"<[^>]+>","",i["source"])]+=1
        if i.get("lang"): langs[i["lang"]]+=1
    top=[(w,c) for w,c in words.most_common(60) if c>=2]
    out.update(top_words=top[:40],topics=tcnt.most_common(),topic_words=twords.most_common(30),sources=src.most_common(6),langs=langs.most_common(5),
        wordlist=[w for w,_ in top],rt_ratio=rts/n if n else 0,comment_ratio=len(comments)/n if n else 0)
    dup=duplicates(items) if n else {"rate":0,"groups":[],"near_pairs":0,"phrases":[]}; out["dups"]=dup
    # timing
    span=max(1.0,(items[-1]["_t"]-items[0]["_t"]).total_seconds()/86400) if n>1 else 1.0
    per_day=n/span; gaps=[(b["_t"]-a["_t"]).total_seconds() for a,b in zip(items,items[1:])]
    cv=(statistics.pstdev(gaps)/statistics.mean(gaps)) if len(gaps)>5 and statistics.mean(gaps)>0 else None
    win=[sum(hours[(s+k)%24] for k in range(6)) for s in range(24)]; ms=min(range(24),key=lambda s:win[s]) if n else 0
    sleep_share=win[ms]/n if n else 0.25
    off=None
    if n>=40 and sleep_share<0.14:
        off=(((3.5-(ms+3))+12)%24)-12; off=round(off*2)/2
    out.update(per_day=round(per_day,1),interval_cv=cv and round(cv,2),sleep_share=round(sleep_share,3),quiet_start_utc=ms if n else None,
               tz_offset=off,tz_countries=tz_candidates(off) if off is not None else [],span_days=round(span,1))
    mismatch=False
    if off is not None and claimed:
        d=abs(((COUNTRIES[claimed]["off"]-off+12)%24)-12); mismatch=d>COUNTRIES[claimed]["tol"]; out["tz_diff"]=round(d,1)
    out["tz_mismatch"]=mismatch
    # relations
    uw=set(out["wordlist"][:80])
    out["followers"]=relations(followers or {},uw); out["following"]=relations(following or {},uw)
    comb=Counter()
    for r in (out["followers"],out["following"]):
        for c in r["countries"]: comb[c["iso"]]+=c["n"]
    tot=sum(comb.values())
    out["network_countries"]=[{"iso":k,"name":COUNTRIES[k]["name"],"pct":round(100*v/tot,1),"n":v} for k,v in comb.most_common(8)] if tot else []
    out["origin_guess"]=out["network_countries"][0] if out["network_countries"] else None
    if claimed and out["origin_guess"] and out["origin_guess"]["iso"]!=claimed and out["origin_guess"]["pct"]>=45:
        out["origin_note"]=f"Claimed {COUNTRIES[claimed]['name']} but network is mostly {out['origin_guess']['name']}"
    # scores
    fol,fing=prof.get("followers") or 0,prof.get("following") or 0
    auto_client=(sum(src[k] for k in src if any(a in k.lower() for a in AUTO_CLIENTS))/n>0.3) if n and src else False
    toth=sum(tcnt.values()); share=(tcnt.most_common(1)[0][1]/toth) if toth else 0
    sig={ # name: (value 0..1, detail)
     "duplicate content":(cl(dup["rate"]/0.4),f"{dup['rate']*100:.0f}% of items duplicated/near-duplicated"),
     "regular posting intervals":(cl((1.5-cv)/1.0) if cv is not None and n>=20 else 0,f"interval variation {cv:.2f}" if cv is not None else "n/a"),
     "no sleep gap (24/7 activity)":(cl((sleep_share-0.05)/0.15) if n>=30 else 0,f"quietest 6h window holds {sleep_share*100:.0f}% of activity"),
     "extreme volume":(cl((per_day-30)/70),f"{per_day:.0f} items/day"),
     "automation client":(1.0 if auto_client else 0,", ".join(k for k,_ in src.most_common(3)) or "n/a"),
     "link-heavy":(cl((urls/n-0.5)/0.4) if n else 0,f"{(urls/n*100 if n else 0):.0f}% contain links"),
     "timezone mismatch":(1.0 if mismatch else 0,f"activity pattern ~UTC{off:+g} vs claimed {claimed}" if mismatch else "consistent / unknown"),
     "single-agenda content":(cl((share-0.4)/0.5)*cl((toth/n if n else 0)/0.3)*cl(toth/15),f"top topic {tcnt.most_common(1)[0][0]} = {share*100:.0f}% of topic words" if toth else "n/a"),
     "bot vocabulary":(cl((botn/n if n else 0)/0.25),f"{botn} items with spam/engagement phrases"),
     "young high-output account":(1.0 if (out["age_days"] is not None and out["age_days"]<90 and per_day>20) else 0,f"age {out['age_days']}d"),
     "follow ratio abuse":(1.0 if fing>1000 and fing>5*max(fol,1) else 0,f"{fing} following / {fol} followers"),
     "retweet-only behaviour":(cl((out["rt_ratio"]-0.8)/0.2) if n>=20 else 0,f"{out['rt_ratio']*100:.0f}% retweets"),
    }
    W_M={"duplicate content":.2,"regular posting intervals":.2,"no sleep gap (24/7 activity)":.2,"extreme volume":.12,"automation client":.15,"link-heavy":.05,"retweet-only behaviour":.08}
    W_F={"timezone mismatch":.4,"single-agenda content":.25,"bot vocabulary":.15,"young high-output account":.1,"follow ratio abuse":.1}
    m=sum(sig[k][0]*w for k,w in W_M.items()); f=sum(sig[k][0]*w for k,w in W_F.items()); h=1-max(m,f); tot=m+f+h
    out["scores"]={"machine":round(100*m/tot),"foreign":round(100*f/tot),"human":round(100*h/tot)}
    out["scores"]["human"]=100-out["scores"]["machine"]-out["scores"]["foreign"]
    out["signals"]=[{"name":k,"value":round(v,2),"detail":d} for k,(v,d) in sorted(sig.items(),key=lambda x:-x[1][0])]
    out["verdict"]=max(out["scores"],key=out["scores"].get) if n>=20 else "insufficient data"
    eng={}
    for k in ("likes","replies","reposts","views"):
        v=[i[k] for i in items if isinstance(i.get(k),(int,float))]
        eng[k]=statistics.median(v) if v else None
    out["engagement"]=eng
    cf=min(1.0,n/200)*0.7+(0.15 if created else 0)+(0.15 if prof.get("followers") is not None else 0)
    out["confidence"]={"pct":round(cf*100),"label":"high" if cf>=0.7 else "medium" if cf>=0.4 else "low"}
    return out
