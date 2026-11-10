// Author: gorcoding
// XBotScope V2 page collector. Injected at document start for https://x.com ONLY.
// Reads publicly visible search-result fields from the page DOM and sends them to the app.
// It never touches credentials, cookies, storage or forms. It never clicks anything.
(function () {
  "use strict";
  if (window.__xbs || location.origin !== "https://x.com") return;
  var S = { active: false, autoscroll: false, seen: new Set(), lastScroll: 0, nextDelay: 4000, stuck: 0, lastH: 0, end: false, timer: null };

  function send(o) { try { XBSBridge.postMessage(JSON.stringify(o)); } catch (e) {} }
  function num(s) {
    if (s == null) return null;
    var m = String(s).replace(/,/g, "").trim().match(/^([\d.]+)\s*([KMB])?/i);
    if (!m) return null;
    var mult = { K: 1e3, M: 1e6, B: 1e9 }[(m[2] || "").toUpperCase()] || 1;
    return Math.round(parseFloat(m[1]) * mult);
  }
  function metric(a, id) {
    var el = a.querySelector('[data-testid="' + id + '"]');
    if (!el) return null;
    var t = (el.innerText || "").trim();
    return t === "" ? 0 : num(t);
  }
  function onSearch() { return location.pathname.indexOf("/search") === 0; }
  function tweets() { return document.querySelectorAll('article[data-testid="tweet"]'); }

  // ---- challenge / security-state detection (never bypassed: we only report it, the app pauses collection)
  function challenge() {
    var p = location.pathname;
    if (p.indexOf("/account/access") === 0) return "captcha";
    if (document.querySelector('iframe[src*="arkoselabs"],iframe[src*="funcaptcha"],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]')) return "captcha";
    // text checks are skipped on result pages that show tweets (tweets may quote such phrases)
    if (onSearch() && tweets().length) return null;
    var txt = ((document.body && document.body.innerText) || "").slice(0, 3000).toLowerCase();
    if (/verify you are human|are you a robot|confirm you.re (a )?human|complete the (captcha|challenge)/.test(txt)) return "captcha";
    if (/confirm your identity|verify your identity|suspicious login|unusual login activity/.test(txt)) return "verification";
    if (/rate limit exceeded|you.re rate limited|exceeded the rate limit/.test(txt)) return "rate_limit";
    if (/account is (temporarily )?locked|account (has been )?suspended|temporarily restricted/.test(txt)) return "locked";
    return null;
  }
  function authState() {
    var p = location.pathname;
    if (p.indexOf("/i/flow/login") === 0 || p === "/login" || p.indexOf("/i/flow/signup") === 0) return "logged_out";
    if (document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"],[data-testid="AppTabBar_Profile_Link"]')) return "logged_in";
    return "unknown";
  }
  function pageKind() {
    if (onSearch()) return "search";
    return /^\/\w{1,15}\/?$/.test(location.pathname) ? "profile" : "other";
  }
  function reportState() {
    send({ t: "state", auth: authState(), page: pageKind(), challenge: challenge(), end: S.end });
  }

  // ---- search-result extraction (only on /search, only while the app says collection is running)
  function scan() {
    if (!S.active || !onSearch() || challenge()) return;
    var out = [];
    tweets().forEach(function (a) {
      if (a.parentElement && a.parentElement.closest("article")) return;
      var t = a.querySelector("time"); if (!t) return;
      var link = t.closest("a"); if (!link) return;
      var m = (link.getAttribute("href") || "").match(/^\/(\w{1,15})\/status\/(\d+)/); if (!m) return;
      var id = m[2]; if (S.seen.has(id)) return;
      S.seen.add(id);
      if (a.querySelector('[data-testid="icon-lock"]')) return;                       // protected account: skip
      var sc = a.querySelector('[data-testid="socialContext"]');
      if (sc && /repost|retweet/i.test(sc.innerText || "")) return;                   // reposts are attributed to the original author: skip
      var txt = a.querySelector('[data-testid="tweetText"]');
      var nm = a.querySelector('[data-testid="User-Name"]');
      var av = a.querySelector('[data-testid="Tweet-User-Avatar"] img');
      var views = a.querySelector('a[href$="/analytics"]');
      out.push({
        id: id, username: m[1],
        name: nm ? ((nm.innerText || "").split("\n")[0] || "").slice(0, 80) : "",
        text: txt ? txt.innerText : "",
        ts: t.getAttribute("datetime"),
        kind: /^\s*Replying to\b/m.test((a.innerText || "").slice(0, 400)) ? "comment" : "post",
        verified: !!a.querySelector('[data-testid="icon-verified"]'),
        avatar: av ? av.src : "",
        lang: txt ? txt.getAttribute("lang") : null,
        replies: metric(a, "reply"), reposts: metric(a, "retweet"), likes: metric(a, "like"),
        views: views ? num(views.innerText) : null
      });
    });
    for (var i = 0; i < out.length; i += 50) send({ t: "records", records: out.slice(i, i + 50) });
  }

  // ---- optional, human-paced auto-scroll (off unless the user enables it in the dashboard)
  function tick() {
    if (!S.active || !S.autoscroll || !onSearch() || S.end || challenge()) return;
    var now = Date.now();
    if (now - S.lastScroll < S.nextDelay) return;
    S.lastScroll = now; S.nextDelay = 4000 + Math.random() * 5000;
    var h = document.documentElement.scrollHeight;
    S.stuck = (h === S.lastH) ? S.stuck + 1 : 0; S.lastH = h;
    if (S.stuck >= 4) { S.end = true; S.autoscroll = false; reportState(); return; }
    window.scrollBy({ top: Math.round(window.innerHeight * 0.8), behavior: "smooth" });
  }

  // ---- optional profile read (called by the app, one profile at a time, slowly)
  function profile() {
    var m = location.pathname.match(/^\/(\w{1,15})\/?$/); if (!m) return;
    var un = document.querySelector('[data-testid="UserName"]');
    if (!un || un.querySelector('[data-testid="icon-lock"]')) return;                 // protected: skip
    function q(sel) { var e = document.querySelector(sel); return e ? (e.innerText || "") : ""; }
    function fol(suffix) { var a = document.querySelector('a[href$="/' + suffix + '"]'); return a ? num(a.innerText) : null; }
    var f = fol("verified_followers"); if (f == null) f = fol("followers");
    send({ t: "profile", profile: {
      username: m[1], name: ((un.innerText || "").split("\n")[0] || "").slice(0, 80),
      bio: q('[data-testid="UserDescription"]'), location: q('[data-testid="UserLocation"]'),
      joined: q('[data-testid="UserJoinDate"]'), followers: f, following: fol("following") } });
  }

  // ---- full profile collection: public, rendered X page DOM only
  var FULL = null;
  function fullProfile() {
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
  function fullSendProgress(msg) {
    send({t:"full_progress",stage:FULL?FULL.kind:"",message:msg||""});
  }
  function fullScan() {
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
  function fullFinish(reason) {
    if(!FULL) return;
    var kind=FULL.kind;
    clearTimeout(FULL.timer);
    FULL=null;
    send({t:"full_done",kind:kind,message:reason||"complete"});
  }
  function startFull(kind,username,limit) {
    clearTimeout(FULL&&FULL.timer);
    FULL={kind:kind,username:username,limit:Math.max(0,Number(limit)||0),
      seen:new Set(),stuck:0,lastH:0,timer:null};
    if(kind==="profile") {
      var p=fullProfile();
      if(p) send({t:"full_profile",profile:p});
      fullFinish(p?"profile collected":"profile not available (protected or page not loaded)");
      return;
    }
    if(FULL.limit===0) { fullFinish("limit set to zero"); return; }
    fullScan();
  }

  function ctl(o) {
    if (o.reset) { S.seen = new Set(); S.end = false; S.stuck = 0; }
    if (typeof o.active === "boolean") { var was = S.active; S.active = o.active; if (S.active && !was) setTimeout(scan, 300); }
    if (typeof o.autoscroll === "boolean") S.autoscroll = o.autoscroll;
  }

  window.__xbs = { ctl: ctl, profile: profile, startFull: startFull, stopFull: function(){fullFinish("stopped");} };
  var deb = null;
  function arm() {
    if (!document.documentElement) return setTimeout(arm, 50);
    new MutationObserver(function () { clearTimeout(deb); deb = setTimeout(scan, 700); }).observe(document.documentElement, { childList: true, subtree: true });
  }
  arm();
  setInterval(reportState, 3000);
  setInterval(tick, 1000);
})();
