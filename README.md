# XBotScope v2.0.0 — by gorcoding
Local dashboard (Termux + Flask) that scores X accounts as **human / machine / foreign-service** from public signals, now fed by
**your own logged-in x.com session** inside a small Android WebView app.

```
 Android "XBotScope Browser" app ──(structured public records, 127.0.0.1 only, pairing token)──▶ Flask backend (Termux)
   WebView on https://x.com                                                                     └─▶ data/<user>/*.json ─▶ analyze() ─▶ dashboard
   you log in / solve captchas yourself
```
Cookies, passwords and session data stay inside the WebView. The backend only ever receives post/profile fields visible on the page.

## 1. Install the backend (Termux)
```
pkg install -y unzip && unzip xbotscope-v2.zip && cd xbotscope
bash install.sh          # python, termux-api, flask, requests
bash run.sh              # http://127.0.0.1:8080
```
**Upgrade from V1:** unzip V2 over/next to V1 and keep your `data/` and `settings.json` folders — the data format is unchanged.

## 2. Install the browser app (`android/`)
No PC needed (option A) — or use Android Studio (option B).
- **A. GitHub Actions (phone only):** create a free GitHub repo, upload this whole project, open *Actions → Build APK → Run workflow*, download the `xbotscope-browser-debug` artifact, unzip, install the APK (allow "install unknown apps").
- **B. Android Studio:** open the `android/` folder, *Build → Build APK(s)*.
Requires Android 8+ and an up-to-date *Android System WebView* (the app tells you if it is too old).

## 3. Use it
1. `bash run.sh`, open the dashboard. In *V2 · X browser collection → Pair / launch*, tap **Pair & launch browser app** (or press **Pair** in the app and enter port + token).
2. The status table must show **Browser: connected**. Log in to X in the app (your own account, manually).
3. Type a query, choose Top/Latest, set max posts, **Start collection**. The app opens `x.com/search?q=<your query>` exactly as typed (X operators like `lang:en`, `from:` work).
4. Scroll the results yourself, or enable **Auto-scroll** (slow, random 4–9 s steps, off by default).
5. Accounts appear in the table. With ≥ *Min items* collected they are analysed by the existing V1 engine; click one for the full profile. Optionally press **Enrich profiles** (slow) to read bio/location/join date.
6. **Pause / Resume / Stop / Clear session results** (saved history is never deleted). **Clear browser session** logs the app out of X and wipes its cookies/cache/site data (also available in the app).

### CAPTCHA & security challenges
Detected CAPTCHA / verification / rate-limit / lock → collection **pauses**, the dashboard and the app show a notice. Solve it in the app, then press **Resume** yourself. Nothing is bypassed or automated.

## 4. What is *not* collected
Passwords, codes, cookies, tokens, DMs, protected accounts (skipped), reposts (skipped – they belong to the original author). Records containing `auth_token`/`ct0=` strings are dropped. No analytics, no third-party servers; backend binds to 127.0.0.1; Android cleartext traffic is allowed to 127.0.0.1/localhost only; only the INTERNET permission.

## 5. Scores
Unchanged V1 model (see `core/analyze.py`). The dashboard adds a label — *automated* (machine ≥ 60 and ≥ 3 strong signals), *suspicious*, *unusual activity*, *no strong indicators* — and a coordination view. Search results usually give few posts per account, so many accounts stay "awaiting" until enough items are collected. Scores are heuristics, not proof.

## 6. Tests (`tools/`)
`python tools/selftest.py` (backend: validation, security, pause/resume/stop, challenge, disconnect, clear, V1 score parity, log scan) · `python tools/collector_test.py` (needs `pip install playwright` + Chromium; runs the page script against a mock X page) · `python tools/audit.py` (privacy/permission audit).

## 7. Known limitations (read this)
- **Not verified on a device or on real x.com.** The Kotlin app was not compiled or run by the author; the page script was tested only against a mock of X's markup. X changes its markup (`data-testid`s), may rate-limit, restrict or suspend accounts, and its Terms restrict automated collection — use at your own risk, ideally with an account you can afford to lose.
- Reply detection relies on English "Replying to" text; other UI languages are collected as posts.
- Auto-scroll stops when no new content loads; X may cap how deep search goes.
- The V1 username fetch (api/nitter) is unchanged; V1 had no keyword search, so the query is passed to x.com untouched.

## 8. Troubleshooting
| Problem | Fix |
|---|---|
| Browser stays *disconnected* | Start `run.sh` first; re-pair; the app and backend must use the same port; don't use battery-saver that kills the app. |
| "WebView too old" | Update *Android System WebView* / Chrome in Play Store. |
| X login refuses / loops | Try again later, use the X password flow (not Google/Apple sign-in; non-X sites are blocked in the app), solve any prompts. |
| State "running – waiting for results" | You are not on a search page, nothing new is loaded, or X shows an error: scroll, reload, or check for a challenge. |
| 403 on dashboard | Open it as `http://127.0.0.1:8080` (not another hostname). |
| Everything "awaiting" | Collect more posts per account or lower nothing — the engine needs ≥ 20 items. |

Version: `VERSION` file / `core/version.py` / `/api/version`.
