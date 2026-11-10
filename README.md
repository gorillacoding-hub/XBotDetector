# XBotDetector (XBotScope) v2.1.0 — by gorcoding
Local dashboard (Termux + Flask) that scores X accounts as **human / machine / foreign-service** from public signals, using
**your own logged-in x.com session** inside a small Android WebView app.

```
Android app "XBotScope Browser"                              Termux
 ├ X view  (WebView on https://x.com, you log in)  ──records (127.0.0.1 only, pairing token)──▶ Flask backend ─▶ data/<user>/*.json ─▶ analyze()
 └ Dashboard view (the dashboard, stacked on top) ◀──────────────────────────────────────────────────────────┘
```
Cookies, passwords and session data stay inside the WebView. The backend only receives post/profile fields visible on the page.

## 1. Install the backend (Termux)
```
pkg install -y unzip && unzip XBotDetector-v2.1.zip && cd XBotDetector
bash install.sh && bash run.sh        # dashboard on http://127.0.0.1:8080
```
Upgrade from V1/V2.0: unzip over the old folder; keep `data/` and `settings.json` (format unchanged).

## 2. Install the browser app (`android/`)
- **A. GitHub Actions (phone only):** upload this whole project to a GitHub repo → *Actions → Build APK → Run workflow* → download the `xbotscope-browser-debug` artifact → install the APK. If the build fails, open the failed step and send me the log (it runs with `--stacktrace`).
- **B. Android Studio:** open `android/` → *Build APK(s)*.
Needs Android 8+ and an up-to-date *Android System WebView*.

## 3. Use it
1. Keep Termux running `bash run.sh`. Open the **XBotScope Browser** app: it opens on the dashboard. In *Pair / launch → Show pairing (2 min)* tap **Pair this app**. Status must say **Browser: connected**.
2. Tap **X** (top bar), log in to X manually (your own account). Tap **Dashboard** to come back — switching views keeps X running underneath.
3. **Auto plan:** enter one or more profiles (`@name`, links) and limits — posts 100, replies 50, followers/following 0 = skip — optionally searches (one per line), keep *Auto-scroll* ticked, **Start plan**. Per profile it runs header → posts → replies → followers → following; each time a limit is reached the browser moves to the next page on its own, then the next profile. When a profile's steps finish it is analysed automatically (open it from *Saved profiles*). **Profile-only analysis** = a plan with just a profile.
4. **Manual search** (top card) still works exactly as in V2.0 (single query, you scroll or enable auto-scroll).
5. **Saved profiles:** filter, open, export (JSON in `data/exports/`), delete selected, delete everything (type DELETE). A profile used by a running plan can't be deleted.
6. **Pause / Resume / Skip / Stop** at any time. **Clear browser session** logs the app out of X and wipes its cookies/cache.

### CAPTCHA & security challenges
CAPTCHA / verification / rate-limit / lock detected → everything **pauses**, notice in dashboard and app. Solve it in the X view, then press **Resume** yourself. Nothing is bypassed or automated.

## 4. Optional AI second opinion
Settings → *AI*: choose provider (Anthropic, or any OpenAI-compatible incl. local Ollama at `http://127.0.0.1:11434/v1`), model, key, tick **consent**. Then **Ask AI** on a profile.
- Default sends **only numeric features** (no posts, bio, username, display name). Optionally also N sample posts + bio. Nothing is sent without consent and a button press.
- The key is stored only in `settings.json` on the phone and never returned to the browser UI. With a cloud provider, data leaves the device — use a local model if that is not acceptable.
- The AI opinion is shown separately, labelled "not evidence", and never changes the scores.

## 5. Scores
Engine in `core/analyze.py` (v2.1: single-agenda false-positive fix, adds confidence + engagement). Dashboard label: *automated* (machine ≥ 60 and ≥ 3 strong signals), *suspicious*, *unusual activity*, *no strong indicators*. Heuristics, not proof; a profile with < 20 items reports "insufficient data".

## 6. Privacy
Never collected: passwords, codes, cookies, tokens, DMs, protected accounts (skipped), reposts (skipped). Backend binds 127.0.0.1; Host check + `X-XBS` header block cross-site requests; bridge needs a token; only the INTERNET permission; cleartext only to 127.0.0.1; the dashboard view can only open the local backend; the page script is injected for `https://x.com` only.

## 7. Tests (`tools/`)
`selftest.py` (bridge, security, V1 parity) · `selftest_plan.py` (plan engine, limits & page switching, stall/end/skip, relations, manager, AI with mocked provider, secrets, pairing) · `collector_test.py`, `collector_modes_test.py` (page script in headless Chromium against mock X markup; needs `pip install playwright`) · `audit.py` (privacy/permission audit).

## 8. Known limitations — read this
- **Not verified on a real device or real x.com.** The Kotlin app was never compiled here (no Android SDK offline); the page script was tested only against mock X markup. X can change its markup, restrict, rate-limit or suspend accounts, and its Terms restrict automated collection — use an account you can afford to lose.
- Reply detection: "Replying to" text (English) or the parent tweet shown above on the replies tab; thread-self-replies count as posts.
- Followers/following lists show name + bio only (no location); X may cap how deep they load. Protected profiles can't be read; their steps time out after 25–60 s and the plan moves on.
- Auto-scroll is slow on purpose (4–9 s per step), so 100 posts takes a few minutes.

## 9. Troubleshooting
| Problem | Fix |
|---|---|
| Browser *disconnected* | `bash run.sh` first; re-pair (*Show pairing*); same port; exempt the app from battery optimisation. |
| Dashboard in the app says "backend not reachable" | Start Termux `run.sh`, press **Reload** in the app. |
| Plan sits on a step, status shows "0 posts visible" | Not logged in, page still loading, or X changed markup — check the Diagnostics row and the app status line; send me those. |
| "WebView too old" | Update *Android System WebView* / Chrome. |
| X login loops | Use username + password (not Google/Apple; non-X sites are blocked), solve prompts, retry later. |
| 403 on dashboard | Use `http://127.0.0.1:8080`, not another hostname. |
