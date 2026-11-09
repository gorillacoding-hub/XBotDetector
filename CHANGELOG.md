# Changelog — by gorcoding

## 2.0.0
**Added**
- Authenticated X collection through the main site (https://x.com) in a dedicated Android WebView app (`android/`). Manual login, persistent isolated session, CAPTCHA/verification shown to the user.
- Local bridge (`core/bridge.py`): validated records (post id/url/text/author/name/timestamp/metrics/public profile fields) → existing storage (`data/<user>/`) → existing `analyze()` engine.
- Dashboard card: query, tab (Top/Latest), max posts, auto-scroll (off by default), start / pause / resume / stop / clear session, live status (browser connection, X login state, collection state, posts, accounts found/analysed/awaiting, errors, last record), discovered-accounts table, coordination clusters, pairing.
- Challenge handling: CAPTCHA / verification / rate-limit / lock detection pauses collection; only an explicit Resume continues. Nothing is bypassed or automated.
- Assessment labels (automated / suspicious / unusual activity / no strong indicators) as a presentation layer on top of the unchanged V1 scores; never from one indicator.
- Cross-account coordination clusters (same/near-same text from different accounts).
- Optional, slow, user-triggered profile enrichment (bio, location, join date, follower counts).
- Hardening: Host check (DNS-rebinding), `X-XBS` header on dashboard POSTs, token-protected bridge routes, 512 KB request cap, loopback-only bind.
- `tools/selftest.py`, `tools/collector_test.py`, `tools/audit.py`; GitHub Actions workflow to build the APK without a PC.

**Unchanged (byte-identical to V1):** `core/analyze.py` (scoring), `core/runner.py`, `core/providers.py`, `core/dorks.py`, `core/http.py`, `core/store.py`, `core/job.py`, data layout, live mode, username fetch.

**Changed**
- Nitter is deprecated (kept selectable, usually offline). `api` is the recommended username-fetch provider.
- `static/index.html`: V2 card + `X-XBS` header. `app.py`: bridge routes + guards.

## 1.0.0
Initial release: username fetch (nitter/api), analysis, dorks, dashboard.
