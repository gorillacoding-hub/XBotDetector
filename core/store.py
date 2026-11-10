# Author: gorcoding
import json, os, re
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
ROOT = BASE / "data"
SET = BASE / "settings.json"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
DEFAULTS = {"provider":"nitter","bearer":"","nitter":"https://nitter.net","user_agent":UA,"proxy":"","cookies":"",
 "delay_min":3,"jitter":2,"timeout":25,"dork_delay":8,"dork_max":20,"dork_tlds":"","deep_relations":False,"live":False,"open_cmd":"termux-open-url",
 "ai_provider":"anthropic","ai_base_url":"","ai_model":"claude-haiku-5-5","ai_key":"","ai_consent":False,"ai_send_samples":False,"ai_n_samples":12,"ai_identity":False}

def _w(path, obj):
    tmp = str(path)+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False)
    os.replace(tmp,path)

def get_settings():
    s=dict(DEFAULTS)
    if SET.exists():
        try: s.update(json.load(open(SET,encoding="utf-8")))
        except Exception: pass
    return s

def save_settings(d):
    s=get_settings(); s.update({k:d[k] for k in d if k in DEFAULTS}); _w(SET,s); return s

class Store:
    def __init__(self,user):
        self.user=re.sub(r"[^\w]","",user)[:15]
        self.dir=ROOT/self.user; self.dir.mkdir(parents=True,exist_ok=True)
    def load(self,name,default=None):
        p=self.dir/f"{name}.json"
        if p.exists():
            try: return json.load(open(p,encoding="utf-8"))
            except Exception: pass
        return default
    def save(self,name,obj): _w(self.dir/f"{name}.json",obj)

def list_users():
    out=[]
    if ROOT.exists():
        for d in sorted(ROOT.iterdir()):
            if d.is_dir():
                st=Store(d.name); p=st.load("profile",{}) or {}
                out.append({"username":d.name,"name":p.get("name",""),"posts":len(st.load("posts",{}) or {}),
                            "comments":len(st.load("comments",{}) or {})})
    return out
