// Author: gorcoding
// XBotScope page collector (v2.1.1). Injected at document start for https://x.com ONLY.
// Reads publicly visible fields from the page DOM for the CURRENT step set by the app
// (search | posts | replies | followers | following | profile) and sends them to the app.
// It never touches credentials, cookies, storage or forms. It never clicks anything.
(function () {
  "use strict";
  if (window.__xbs || location.origin !== "https://x.com") return;
  var S = { active: false, autoscroll: false, mode: { kind: "search", target: "" }, seq: 0, seen: new Set(),
            lastScroll: 0, nextDelay: 4000, stuck: 0, lastH: 0, end: false, pSeen: 0, pSent: -1 };

  function send(o) { o.seq = S.seq; try { XBSBridge.postMessage(JSON.stringify(o)); } catch (e) {} }
  function lc(s) { return String(s || "").toLowerCase(); }
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
    // Prefer the innermost transition container when present (X layout 2025+)
    var span = el.querySelector('[data-testid="app-text-transition-container"] span') || el;
    var t = (span.innerText || el.innerText || "").trim();
    return t === "" ? 0 : num(t);
  }
  function tweets() { return document.querySelectorAll('article[data-testid="tweet"]'); }
  function cells() { return document.querySelectorAll('[data-testid="UserCell"]'); }
  function path() { return lc(location.pathname).replace(/\/+$/, ""); }
  // Accept relative, absolute, and query-string status links
  function statusMatch(href) {
    if (!href) return null;
    var m = String(href).match(/(?:https?:\/\/(?:www\.)?(?:x|twitter)\.com)?\/(\w{1,15})\/status\/(\d+)/i);
    if (m) return { user: m[1], id: m[2] };
    m = String(href).match(/\/status\/(\d+)/);
    return m ? { user: null, id: m[1] } : null;
  }
  function authorOf(a) {
    var t = a && a.querySelector("time"), l = t && t.closest("a");
    var sm = statusMatch(l && l.getAttribute("href"));
    if (sm && sm.user) return sm.user;
    // Fallback: first profile link inside the User-Name block
    var nm = a && a.querySelector('[data-testid="User-Name"] a[href^="/"]');
    if (nm) {
      var hm = (nm.getAttribute("href") || "").match(/^\/(\w{1,15})(?:\/|$)/);
      if (hm) return hm[1];
    }
    return null;
  }
  // is the page we are on the right page for the current step?
  function inScope() {
    var k = S.mode.kind, p = path(), t = "/" + lc(S.mode.target);
    if (k === "search") return location.pathname.indexOf("/search") === 0;
    if (k === "posts" || k === "profile") return p === t;
    if (k === "replies") return p === t + "/with_replies";
    if (k === "followers") return p === t + "/followers";
    if (k === "following") return p === t + "/following";
    return false;
  }
  function pageKind() {
    if (location.pathname.indexOf("/search") === 0) return "search";
    return /^\/\w{1,15}\/?$/.test(location.pathname) ? "profile" : "other";
  }

  // ---- challenge / security-state detection (never bypassed: only reported; the app pauses and the user solves it)
  function challenge() {
    if (location.pathname.indexOf("/account/access") === 0) return "captcha";
    if (document.querySelector('iframe[src*="arkoselabs"],iframe[src*="funcaptcha"],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]')) return "captcha";
    if (tweets().length || cells().length) return null;   // content is showing; skip text checks (tweets may quote such phrases)
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
  function reportState() {
    send({ t: "state", auth: authState(), page: pageKind(), challenge: challenge(), end: S.end,
           diag: { articles: tweets().length, cells: cells().length, seen: S.seen.size, scope: inScope(), path: location.pathname.slice(0, 60) } });
  }

  // ---- tweets (search / posts / replies)
  function extract(a, replyCtx) {
    var t = a.querySelector("time"); if (!t) return null;
    var link = t.closest("a");
    var sm = statusMatch(link && link.getAttribute("href"));
    // Also try any status link inside the article when the time link is missing or non-standard
    if (!sm) {
      var any = a.querySelector('a[href*="/status/"]');
      sm = statusMatch(any && any.getAttribute("href"));
    }
    if (!sm || !sm.id) return null;
    var id = sm.id; if (S.seen.has(id)) return null;
    S.seen.add(id);
    if (a.querySelector('[data-testid="icon-lock"]')) return null;                       // protected account: skip
    var sc = a.querySelector('[data-testid="socialContext"]');
    if (sc && /repost|retweet/i.test(sc.innerText || "")) return null;                   // reposts belong to the original author: skip
    var txt = a.querySelector('[data-testid="tweetText"]'), nm = a.querySelector('[data-testid="User-Name"]');
    var av = a.querySelector('[data-testid="Tweet-User-Avatar"] img'), views = a.querySelector('a[href$="/analytics"]');
    // Resolve username: prefer status link, else User-Name profile link
    var username = sm.user;
    if (!username) {
      var nmLink = nm && nm.querySelector('a[href^="/"]');
      var hm = nmLink && (nmLink.getAttribute("href") || "").match(/^\/(\w{1,15})(?:\/|$)/);
      username = hm ? hm[1] : null;
    }
    if (!username) return null;
    var isReply = /^\s*Replying to\b/m.test((a.innerText || "").slice(0, 400));
    if (!isReply && replyCtx) {                                  // on a user's replies tab a reply is shown under its parent (another author)
      var cell = a.closest('[data-testid="cellInnerDiv"]'), prev = cell && cell.previousElementSibling;
      var pa = prev && authorOf(prev.querySelector('article[data-testid="tweet"]'));
      if (pa && lc(pa) !== lc(username)) isReply = true;
    }
    return { id: id, username: username, name: nm ? ((nm.innerText || "").split("\n")[0] || "").slice(0, 80) : "",
      text: txt ? txt.innerText : "", ts: t.getAttribute("datetime"), kind: isReply ? "comment" : "post",
      verified: !!a.querySelector('[data-testid="icon-verified"]'), avatar: av ? av.src : "", lang: txt ? txt.getAttribute("lang") : null,
      replies: metric(a, "reply"), reposts: metric(a, "retweet"), likes: metric(a, "like"), views: views ? num(views.innerText) : null };
  }
  function scanTweets() {
    var k = S.mode.kind, target = lc(S.mode.target), out = [];
    tweets().forEach(function (a) {
      if (a.parentElement && a.parentElement.closest("article")) return;
      if (k !== "search") { var au = authorOf(a); if (!au || lc(au) !== target) return; }   // timeline pages also show other people's context tweets
      var r = extract(a, k === "replies"); if (r) out.push(r);
    });
    for (var i = 0; i < out.length; i += 50) send({ t: "records", records: out.slice(i, i + 50) });
  }

  // ---- followers / following lists
  function scanUsers() {
    var out = [];
    cells().forEach(function (c) {
      var a = c.querySelector('a[href^="/"][role="link"]'); if (!a) return;
      var m = (a.getAttribute("href") || "").match(/^\/(\w{1,15})$/); if (!m) return;
      var key = "u:" + lc(m[1]); if (S.seen.has(key)) return; S.seen.add(key);
      if (c.querySelector('[data-testid="icon-lock"]')) return;
      var lines = (c.innerText || "").split("\n").map(function (l) { return l.trim(); }).filter(Boolean);
      var rest = lines.slice(1).filter(function (l) { return l.charAt(0) !== "@" && !/^(Follow|Following|Follows you|Pending|Unfollow|Click to Follow.*)$/i.test(l); });
      out.push({ username: m[1], name: (lines[0] || "").slice(0, 80), bio: rest.join(" ").slice(0, 500) });
    });
    for (var i = 0; i < out.length; i += 50) send({ t: "relations", kind: S.mode.kind, users: out.slice(i, i + 50) });
  }

  // ---- profile header (waits for the page to render, sends once per step)
  function readProfile(force) {
    var un = document.querySelector('[data-testid="UserName"]');
    if (!un || un.querySelector('[data-testid="icon-lock"]')) return;                     // not loaded yet, or protected: skip
    var hasJoin = !!document.querySelector('[data-testid="UserJoinDate"]');
    if (!S.pSeen) S.pSeen = Date.now();
    if (!force && !hasJoin && Date.now() - S.pSeen < 6000) return;                        // give bio/join date time to render
    function q(sel) { var e = document.querySelector(sel); return e ? (e.innerText || "") : ""; }
    function fol(suffix) { var a = document.querySelector('a[href$="/' + suffix + '"]'); return a ? num(a.innerText) : null; }
    var f = fol("verified_followers"); if (f == null) f = fol("followers");
    var m = location.pathname.match(/^\/(\w{1,15})\/?$/); if (!m) return;
    S.pSent = S.seq;
    send({ t: "profile", profile: { username: m[1], name: ((un.innerText || "").split("\n")[0] || "").slice(0, 80),
      bio: q('[data-testid="UserDescription"]'), location: q('[data-testid="UserLocation"]'),
      joined: q('[data-testid="UserJoinDate"]'), followers: f, following: fol("following") } });
  }

  function scan() {
    if (!S.active || !inScope() || challenge()) return;
    var k = S.mode.kind;
    if (k === "followers" || k === "following") scanUsers();
    else if (k === "profile") { if (S.pSent !== S.seq) readProfile(false); }
    else scanTweets();
  }

  // ---- human-paced auto-scroll (only when the plan / the user enabled it)
  function tick() {
    if (!S.active) return;
    if (S.mode.kind === "profile") { scan(); return; }
    if (!S.autoscroll || !inScope() || S.end || challenge()) return;
    var now = Date.now();
    if (now - S.lastScroll < S.nextDelay) return;
    S.lastScroll = now; S.nextDelay = 4000 + Math.random() * 5000;
    var h = document.documentElement.scrollHeight;
    S.stuck = (h === S.lastH) ? S.stuck + 1 : 0; S.lastH = h;
    if (S.stuck >= 4) { S.end = true; S.autoscroll = false; reportState(); return; }
    window.scrollBy({ top: Math.round(window.innerHeight * 0.8), behavior: "smooth" });
  }

  function ctl(o) {
    var changed = false;
    if (typeof o.seq === "number" && o.seq !== S.seq) { S.seq = o.seq; changed = true; }
    if (o.mode && (o.mode.kind !== S.mode.kind || lc(o.mode.target) !== lc(S.mode.target))) { S.mode = { kind: o.mode.kind, target: o.mode.target || "" }; changed = true; }
    if (o.reset || changed) { S.seen = new Set(); S.end = false; S.stuck = 0; S.lastH = 0; S.pSeen = 0; S.pSent = -1; }
    if (typeof o.active === "boolean") { var was = S.active; S.active = o.active; if (S.active && !was) setTimeout(scan, 300); }
    if (typeof o.autoscroll === "boolean") S.autoscroll = o.autoscroll;
  }

  window.__xbs = { ctl: ctl, profile: function () { S.pSeen = Date.now(); readProfile(true); } };
  var deb = null;
  function arm() {
    if (!document.documentElement) return setTimeout(arm, 50);
    new MutationObserver(function () { clearTimeout(deb); deb = setTimeout(scan, 700); }).observe(document.documentElement, { childList: true, subtree: true });
  }
  arm();
  setInterval(reportState, 3000);
  setInterval(tick, 1000);
})();
