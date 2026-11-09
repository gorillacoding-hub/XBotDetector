# Author: gorcoding
import threading, time, subprocess, shutil
from . import store

class Job:
    def __init__(s): s.reset()
    def reset(s):
        s.status="idle"; s.kind=""; s.logs=[]; s.progress={}; s.stop=False; s.paused_url=""
        s.ev=threading.Event(); s.ev.set()
    def cfg(s): return store.get_settings()
    def log(s,m):
        s.logs.append(time.strftime("%H:%M:%S ")+str(m)); s.logs=s.logs[-300:]
    def sleep(s,sec):
        end=time.time()+sec
        while time.time()<end and not s.stop:
            s.progress["wait"]=int(end-time.time()); time.sleep(0.5)
        s.progress["wait"]=0
    def pause(s,url):
        s.status="paused"; s.paused_url=url
        s.log("BLOCKED / captcha. Open the link in your browser, solve it (paste fresh cookies in Settings if needed), then press Resume.")
        cmd=s.cfg().get("open_cmd") or ""
        if cmd and shutil.which(cmd):
            try: subprocess.Popen([cmd,url])
            except Exception: pass
        s.ev.clear(); s.ev.wait()
        if not s.stop: s.status="running"
    def resume(s): s.ev.set()
    def halt(s): s.stop=True; s.ev.set()

JOB=Job()

def start(kind,fn,*a):
    if JOB.status in ("running","paused"): return False
    JOB.reset(); JOB.status="running"; JOB.kind=kind
    def w():
        try:
            fn(JOB,*a); JOB.status="stopped" if JOB.stop else "done"
        except Exception as e:
            JOB.log("ERROR: "+str(e)); JOB.status="error"
    threading.Thread(target=w,daemon=True).start(); return True
