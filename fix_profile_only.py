from pathlib import Path
import shutil
import sys

path = Path("android/app/src/main/assets/collector.js")

if not path.exists():
    sys.exit("ERROR: collector.js not found.")

src = path.read_text(encoding="utf-8")

start = src.find("  function startFull(")
end = src.find("\n\n  function ctl(", start)

if start < 0 or end < 0:
    sys.exit("ERROR: Could not locate startFull() safely. No changes made.")

backup = path.with_name("collector.js.profile-fix.bak")
shutil.copy2(path, backup)

replacement = r'''  function startFull(kind,username,limit) {
    clearTimeout(FULL && FULL.timer);

    FULL={
      kind:kind,
      username:username,
      limit:Math.max(0,Number(limit)||0),
      seen:new Set(),
      stuck:0,
      lastH:0,
      timer:null
    };

    if(kind==="profile") {
      var deadline = Date.now() + 25000;

      function retryProfile() {
        if(!FULL || FULL.kind !== "profile") return;

        var p = fullProfile();

        if(p && p.username &&
           p.username.toLowerCase() === username.toLowerCase()) {
          send({t:"full_profile",profile:p});
          fullSendProgress("Profile successfully collected");
          fullFinish("profile collected");
          return;
        }

        if(Date.now() >= deadline) {
          fullFinish("Profile unavailable after 25 seconds. Check that the X profile is public and fully loaded.");
          return;
        }

        fullSendProgress("Waiting for X profile to finish loading...");
        FULL.timer = setTimeout(retryProfile,700);
      }

      retryProfile();
      return;
    }

    if(FULL.limit===0) {
      fullFinish("limit set to zero");
      return;
    }

    fullScan();
  }'''

src = src[:start] + replacement + src[end:]
path.write_text(src, encoding="utf-8")

print("Profile-only retry correction applied.")
print("Backup:", backup)
