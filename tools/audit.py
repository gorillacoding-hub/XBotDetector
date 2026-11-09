# Author: gorcoding
# Static privacy audit: fails if the companion/collector/bridge code reads credentials or session data,
# opens network paths other than the local backend, or requests extra Android permissions.
import re, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent
BAD = {
 "reads cookies": r"document\.cookie|\.getCookie\(",
 "reads web storage": r"localStorage|sessionStorage|indexedDB",
 "collector makes network calls": r"\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon|new Image\(",
 "touches password fields": r"type=.?password|input\[type",
 "injects/handles auth tokens": r"auth_token|\bct0\b(?!=)",
 "evaluates remote code": r"\beval\(|new Function\(",
}
files = [R/"android/app/src/main/assets/collector.js", *(R/"android/app/src/main/java/com/gorcoding/xbotscope").glob("*.kt")]
fail = 0
for f in files:
    t = f.read_text()
    for k, rx in BAD.items():
        for m in re.finditer(rx, t):
            line = t.count("\n", 0, m.start())+1
            if t.splitlines()[line-1].lstrip().startswith(("//", "*", "/*")): continue
            print(f"FAIL {f.name}:{line} {k}: {m.group(0)}"); fail += 1
for f in (R/"android/app/src/main/java/com/gorcoding/xbotscope").glob("*.kt"):
    for u in re.findall(r'"(https?://[^"$]+)', f.read_text()):
        if not u.startswith(("https://x.com", "https://pbs.twimg.com", "http://127.0.0.1")): print("FAIL", f.name, "unexpected URL", u); fail += 1
    if "127.0.0.1" not in f.read_text() and f.name == "BridgeClient.kt": print("FAIL BridgeClient not loopback"); fail += 1
man = (R/"android/app/src/main/AndroidManifest.xml").read_text()
perms = re.findall(r'uses-permission android:name="([^"]+)"', man)
if perms != ["android.permission.INTERNET"]: print("FAIL permissions:", perms); fail += 1
if 'allowBackup="false"' not in man: print("FAIL allowBackup"); fail += 1
nsc = (R/"android/app/src/main/res/xml/network_security_config.xml").read_text()
if re.findall(r"<domain\s[^>]*>([^<]+)<", nsc) != ["127.0.0.1", "localhost"]: print("FAIL cleartext domains"); fail += 1
srv = (R/"app.py").read_text()
if 'app.run("127.0.0.1"' not in srv: print("FAIL backend not bound to loopback"); fail += 1
print("AUDIT", "FAILED" if fail else "PASSED", f"({len(files)} source files)"); sys.exit(1 if fail else 0)
