# Author: gorcoding
import time, random, requests

class Blocked(Exception): pass

class Http:
    """requests wrapper: custom UA/proxy/cookies, randomized delay, X rate-limit headers, captcha pause (live mode)."""
    def __init__(s,ctl,delay_key="delay_min"):
        s.ctl=ctl; s.s=requests.Session(); s.last=0; s.dk=delay_key
    def get(s,url,params=None,headers=None,retries=5):
        for attempt in range(retries):
            if s.ctl.stop: raise RuntimeError("stopped")
            cfg=s.ctl.cfg()
            h={"User-Agent":cfg["user_agent"],"Accept-Language":"en-US,en;q=0.9"}
            if cfg.get("cookies"): h["Cookie"]=cfg["cookies"]
            h.update(headers or {})
            px={"http":cfg["proxy"],"https":cfg["proxy"]} if cfg.get("proxy") else None
            wait=float(cfg[s.dk])+random.uniform(0,float(cfg["jitter"]))-(time.time()-s.last)
            if wait>0: s.ctl.sleep(wait)
            try:
                r=s.s.get(url,params=params,headers=h,proxies=px,timeout=int(cfg["timeout"]))
            except requests.RequestException as e:
                s.ctl.log(f"network error: {e}"); s.ctl.sleep(5*(attempt+1)); continue
            s.last=time.time()
            reset=r.headers.get("x-rate-limit-reset","")
            if r.status_code==429 or (r.headers.get("x-rate-limit-remaining")=="0" and reset.isdigit()):
                w=max(5,int(reset)-int(time.time())+2) if reset.isdigit() else 60*(attempt+1)
                w=min(w,960); s.ctl.log(f"rate limit reached - waiting {w}s (respecting X limits)")
                s.ctl.sleep(w)
                if r.status_code==429: continue
            head=r.text[:20000].lower()
            if r.status_code in (401,403,202) or "anomaly-modal" in head or (r.status_code!=200 and "captcha" in head):
                if r.status_code==401 and "api.twitter.com" in url: raise Blocked("API token rejected (401)")
                if not cfg.get("live"): raise Blocked(f"blocked/captcha (HTTP {r.status_code}) at {url} - enable Live mode, change provider, proxy or cookies")
                s.ctl.pause(url)
                if s.ctl.stop: raise RuntimeError("stopped")
                continue
            if r.status_code==404: raise Blocked(f"404 for {url}")
            return r
        raise Blocked(f"giving up on {url}")
