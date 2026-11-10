from pathlib import Path
import shutil

p = Path("android/app/src/main/assets/collector.js")
if not p.exists():
    raise SystemExit("ERROR: collector.js not found")

s = p.read_text()
backup = p.with_suffix(".js.before-fix.bak")
shutil.copy2(p, backup)

start = s.index("  function fullProfile() {")
end = s.index("  function fullSendProgress", start)

s = s[:start] + r'''  function fullProfile() {
    var m = location.pathname.match(/^\/(\w{1,15})(?:\/|$)/);
    if (!m) return null;

    var un = document.querySelector('[data-testid="UserName"]');
    if (!un || un.querySelector('[data-testid="icon-lock"]')) return null;

    function q(sel) {
      var e = document.querySelector(sel);
      return e ? (e.innerText || "").trim() : "";
    }

    function fol(suffix) {
      var a = document.querySelector('a[href$="/' + suffix + '"]');
      return a ? num(a.innerText) : null;
    }

    var av = document.querySelector(
      '[data-testid="UserAvatar-Container-unknown"] img, img[src*="profile_images"]'
    );

    var f = fol("verified_followers");
    if (f == null) f = fol("followers");

    return {
      username: m[1],
      name: ((un.innerText || "").split("\n")[0] || "").slice(0, 80),
      bio: q('[data-testid="UserDescription"]'),
      location: q('[data-testid="UserLocation"]'),
      joined: q('[data-testid="UserJoinDate"]'),
      followers: f,
      following: fol("following"),
      avatar: av ? av.src : ""
    };
  }
''' + s[end:]

start = s.index("  function fullScan() {")
end = s.index("  function fullFinish", start)

s = s[:start] + r'''  function fullScan() {
    if (!FULL || challenge()) return;

    var out = [];

    if (FULL.kind === "followers" || FULL.kind === "following") {
      document.querySelectorAll('[data-testid="UserCell"]').forEach(function(cell) {
        var a = cell.querySelector('a[href^="/"]');
        if (!a) return;

        var m = (a.getAttribute("href") || "").match(/^\/(\w{1,15})\/?$/);
        if (!m || m[1].toLowerCase() === FULL.username.toLowerCase()) return;
        if (FULL.seen.has(m[1].toLowerCase())) return;

        FULL.seen.add(m[1].toLowerCase());

        var nm = cell.querySelector('[data-testid="User-Name"]');
        var bio = cell.querySelector('[data-testid="UserDescription"]');
        var loc = cell.querySelector('[data-testid="UserLocation"]');

        out.push({
          username: m[1],
          name: nm ? ((nm.innerText || "").split("\n")[0] || "") : "",
          bio: bio ? bio.innerText : "",
          location: loc ? loc.innerText : ""
        });
      });

      if (out.length) {
        send({ t: "full_relations", kind: FULL.kind, users: out });
      }

    } else {
      // Same visible tweet extraction method and DOM selectors as search collection.
      tweets().forEach(function(a) {
        if (a.parentElement && a.parentElement.closest("article")) return;

        var t = a.querySelector("time");
        if (!t) return;

        var link = t.closest("a");
        if (!link) return;

        var m = (link.getAttribute("href") || "").match(/^\/(\w{1,15})\/status\/(\d+)/);
        if (!m) return;
        if (m[1].toLowerCase() !== FULL.username.toLowerCase()) return;

        var id = m[2];
        if (FULL.seen.has(id)) return;
        FULL.seen.add(id);

        if (a.querySelector('[data-testid="icon-lock"]')) return;

        var sc = a.querySelector('[data-testid="socialContext"]');
        if (sc && /repost|retweet/i.test(sc.innerText || "")) return;

        var txt = a.querySelector('[data-testid="tweetText"]');
        var nm = a.querySelector('[data-testid="User-Name"]');
        var av = a.querySelector('[data-testid="Tweet-User-Avatar"] img');
        var views = a.querySelector('a[href$="/analytics"]');

        out.push({
          id: id,
          username: m[1],
          name: nm ? ((nm.innerText || "").split("\n")[0] || "").slice(0, 80) : "",
          text: txt ? txt.innerText : "",
          ts: t.getAttribute("datetime"),
          kind: FULL.kind === "comments" ? "comment" : "post",
          verified: !!a.querySelector('[data-testid="icon-verified"]'),
          avatar: av ? av.src : "",
          lang: txt ? txt.getAttribute("lang") : null,
          replies: metric(a, "reply"),
          reposts: metric(a, "retweet"),
          likes: metric(a, "like"),
          views: views ? num(views.innerText) : null
        });
      });

      if (out.length) {
        send({ t: "full_records", kind: FULL.kind, records: out });
      }
    }

    var count = FULL.seen.size;
    fullSendProgress(FULL.kind + ": " + count + " collected");

    if (count >= FULL.limit) {
      fullFinish("limit reached");
      return;
    }

    var h = document.documentElement.scrollHeight;
    FULL.stuck = (h === FULL.lastH) ? FULL.stuck + 1 : 0;
    FULL.lastH = h;

    if (FULL.stuck >= 5) {
      fullFinish("end of available page results");
      return;
    }

    window.scrollBy({
      top: Math.round(window.innerHeight * 0.8),
      behavior: "smooth"
    });

    FULL.timer = setTimeout(fullScan, 3500 + Math.random() * 1800);
  }
''' + s[end:]

p.write_text(s)
print("Full-fetch collector corrected.")
print("Backup:", backup)
