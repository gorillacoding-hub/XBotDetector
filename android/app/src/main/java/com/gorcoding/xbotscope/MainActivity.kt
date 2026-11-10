// Author: gorcoding
package com.gorcoding.xbotscope

import android.app.Activity
import android.app.AlertDialog
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONArray
import org.json.JSONObject

/**
 * XBotScope Browser (v2.1).
 * - "X" view: a plain WebView on https://x.com with its own persistent session. The user logs in manually.
 * - "Dashboard" view: the local XBotScope dashboard (127.0.0.1) in a second WebView stacked on top, so you can start/monitor
 *   jobs without leaving this app (leaving it would let Android throttle the X page and stop collection).
 * - assets/collector.js is injected for https://x.com ONLY and reports PUBLIC fields for the current step.
 * - Only structured records go to the local backend, authorised by a local pairing token. Cookies are never read, only deleted.
 */
class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var root: LinearLayout
    private lateinit var web: WebView
    private lateinit var dash: WebView
    private lateinit var statusView: TextView
    private lateinit var client: BridgeClient
    private var ready = false

    // state mirrored from the backend / page
    private var backendState = "idle"
    private var query = ""
    private var autoscroll = false
    private var connected = false
    private var hold = false
    private var seq = 0
    private var modeKind = "search"
    private var modeTarget = ""
    private var auth = "unknown"
    private var page = "other"
    private var pageChallenge: String? = null
    private var pageSeq = -1
    private var endOfResults = false
    private var diag: JSONObject? = null
    private var collected = 0
    private val enrichQueue = ArrayDeque<String>()
    private var enriching = false

    private val beat = object : Runnable {
        override fun run() { heartbeat(); ui.postDelayed(this, 2000) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        client = BridgeClient(getSharedPreferences("xbs", MODE_PRIVATE))
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER) ||
            !WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            setContentView(TextView(this).apply {
                text = "This device's Android System WebView is too old.\nUpdate 'Android System WebView' (or Chrome) in Google Play, then reopen."
                setPadding(32, 64, 32, 32)
            })
            return
        }
        ready = true
        buildUi()
        setupXView()
        setupDashView()
        handleUri(intent?.data)
        web.loadUrl("https://x.com/home")
        loadDashboard()
        showDashboard(true)
        if (!client.configured()) Toast.makeText(this, "Open 'Show pairing' in the dashboard, then tap the pairing link", Toast.LENGTH_LONG).show()
        ui.post(beat)
    }

    private fun btn(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; textSize = 12f; setOnClickListener { onClick() }
    }

    private fun buildUi() {
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.BLACK) }
        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        bar.addView(btn("X") { showDashboard(false) })
        bar.addView(btn("Dashboard") { showDashboard(true) })
        bar.addView(btn("Reload") { if (dash.visibility == View.VISIBLE) loadDashboard() else web.reload() })
        bar.addView(btn("X home") { web.loadUrl("https://x.com/home") })
        bar.addView(btn("Pair") { showPairDialog() })
        bar.addView(btn("Clear session") { confirmClear() })
        bar.addView(btn("Close") { finish() })
        root.addView(HorizontalScrollView(this).apply { addView(bar) })
        statusView = TextView(this).apply { setTextColor(Color.LTGRAY); textSize = 11f; setPadding(12, 4, 12, 4) }
        root.addView(statusView)
        web = WebView(this)
        dash = WebView(this)
        // X stays laid out underneath at full size (so its feed keeps loading); the dashboard is stacked on top.
        val stack = FrameLayout(this)
        stack.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        stack.addView(dash, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        root.addView(stack, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
        updateStatus()
    }

    private fun showDashboard(show: Boolean) { dash.visibility = if (show) View.VISIBLE else View.GONE }

    private fun dashUrl() = "http://127.0.0.1:${client.port()}/"
    private fun loadDashboard() = dash.loadUrl(dashUrl())

    private fun setupXView() {
        WebView.setWebContentsDebuggingEnabled(false)
        web.settings.apply {
            javaScriptEnabled = true          // required by x.com
            domStorageEnabled = true          // required by x.com
            allowFileAccess = false
            allowContentAccess = false
            setSupportMultipleWindows(false)
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)   // challenge widgets may need it
        val script = assets.open("collector.js").bufferedReader().use { it.readText() }
        // Both restricted to https://x.com: other origins/frames (e.g. challenge iframes) can neither receive the script nor message us.
        WebViewCompat.addDocumentStartJavaScript(web, script, setOf("https://x.com"))
        WebViewCompat.addWebMessageListener(web, "XBSBridge", setOf("https://x.com")) { _, message, sourceOrigin, isMainFrame, _ ->
            if (isMainFrame && sourceOrigin.toString() == "https://x.com") message.data?.let { onPageMessage(it) }
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url
                val host = u.host ?: return true
                val ok = u.scheme == "https" && (host == "x.com" || host.endsWith(".x.com") ||
                        host == "twitter.com" || host.endsWith(".twitter.com"))
                if (!ok) Toast.makeText(this@MainActivity, "Blocked navigation outside X: $host", Toast.LENGTH_SHORT).show()
                return !ok
            }
        }
    }

    /** The dashboard WebView may only show the local backend. It gets NO bridge object and no collector script. */
    private fun setupDashView() {
        dash.settings.apply {
            javaScriptEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            domStorageEnabled = false
        }
        dash.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url
                if (u.scheme == "xbotscope") { handleUri(u); return true }                 // pairing link from the dashboard
                val local = u.scheme == "http" && u.host == "127.0.0.1"
                if (!local) Toast.makeText(this@MainActivity, "Blocked: dashboard may only open the local backend", Toast.LENGTH_SHORT).show()
                return !local
            }
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError) {
                if (request.isForMainFrame) view.loadDataWithBaseURL(null,
                    "<body style='background:#111;color:#eee;font-family:sans-serif;padding:20px'><h3>XBotScope backend not reachable</h3>" +
                    "<p>Start it in Termux: <code>bash run.sh</code>, then press Reload above.</p></body>", "text/html", "utf-8", null)
            }
        }
    }

    // ---------- page -> app
    private fun onPageMessage(data: String) {
        if (data.length > 400_000) return
        val o = try { JSONObject(data) } catch (e: Exception) { return }
        val s = o.optInt("seq", -1)
        when (o.optString("t")) {
            "state" -> {
                auth = o.optString("auth", "unknown"); page = o.optString("page", "other")
                pageChallenge = o.optString("challenge", "").ifEmpty { null }
                endOfResults = o.optBoolean("end", false); pageSeq = s; diag = o.optJSONObject("diag")
                updateStatus()
            }
            "records" -> if (backendState == "running" && !enriching && !hold) {
                val body = JSONObject().put("query", query).put("seq", s).put("records", o.optJSONArray("records") ?: JSONArray())
                client.post("/api/bridge/in/records", body) { r -> onAccepted(r) }
            }
            "relations" -> if (backendState == "running" && !enriching && !hold) {
                val body = JSONObject().put("kind", o.optString("kind")).put("seq", s).put("users", o.optJSONArray("users") ?: JSONArray())
                client.post("/api/bridge/in/relations", body) { r -> onAccepted(r) }
            }
            "profile" -> {
                val body = JSONObject().put("seq", s).put("profile", o.optJSONObject("profile") ?: JSONObject())
                client.post("/api/bridge/in/profile", body) { }
            }
        }
    }

    private fun onAccepted(r: JSONObject?) {
        if (r == null) return
        backendState = r.optString("state", backendState)
        collected += r.optInt("accepted", 0)
        pushControl(); updateStatus()
    }

    // ---------- app <-> backend
    private fun heartbeat() {
        val body = JSONObject().put("app", "2.1.1").put("auth", auth).put("page", page)
            .put("challenge", pageChallenge ?: JSONObject.NULL).put("end", endOfResults).put("seq", pageSeq)
            .put("diag", diag ?: JSONObject())
        client.post("/api/bridge/in/heartbeat", body) { r ->
            connected = r != null
            if (r != null) {
                backendState = r.optString("state", "idle")
                query = r.optString("query", "")
                seq = r.optInt("seq", 0)
                hold = r.optBoolean("hold", false)
                autoscroll = r.optJSONObject("opts")?.optBoolean("autoscroll", false) == true
                r.optJSONObject("mode")?.let { modeKind = it.optString("kind", "search"); modeTarget = it.optString("target", "") }
                r.optJSONArray("commands")?.let { arr -> for (i in 0 until arr.length()) handleCommand(arr.getJSONObject(i)) }
                pushControl()
            }
            root.keepScreenOn = connected && backendState == "running"     // a sleeping screen would pause the X page
            updateStatus()
        }
    }

    private fun handleCommand(o: JSONObject) {
        when (o.optString("action")) {
            "open" -> { val u = Uri.parse(o.optString("url")); if (u.scheme == "https" && u.host == "x.com") web.loadUrl(u.toString()) }
            "reset_seen" -> { collected = 0; web.evaluateJavascript("window.__xbs&&window.__xbs.ctl({reset:true})", null) }
            "enrich" -> {
                val a = o.optJSONArray("usernames") ?: return
                for (i in 0 until a.length()) { val n = a.optString(i); if (Regex("\\w{1,15}").matches(n)) enrichQueue.addLast(n) }
                if (!enriching && enrichQueue.isNotEmpty()) { enriching = true; nextProfile() }
            }
            "clear_browser" -> clearSession()
        }
    }

    /** Tells the page script what to do now: which step (mode), whether to collect, whether to auto-scroll. */
    private fun pushControl() {
        val active = backendState == "running" && !enriching && !hold
        val msg = JSONObject().put("active", active).put("autoscroll", active && autoscroll).put("seq", seq)
            .put("mode", JSONObject().put("kind", modeKind).put("target", modeTarget))
        web.evaluateJavascript("window.__xbs&&window.__xbs.ctl($msg)", null)
    }

    // ---------- optional slow profile enrichment (user-triggered from the dashboard)
    private fun nextProfile() {
        if (enrichQueue.isEmpty()) { enriching = false; pushControl(); updateStatus(); return }
        if (pageChallenge != null || backendState == "paused") { ui.postDelayed({ nextProfile() }, 3000); return }
        pushControl()
        val u = enrichQueue.removeFirst()
        web.loadUrl("https://x.com/$u")
        ui.postDelayed({ web.evaluateJavascript("window.__xbs&&window.__xbs.profile()", null) }, 6000)
        ui.postDelayed({ nextProfile() }, 6000L + (6000..11000).random())
        updateStatus()
    }

    // ---------- UI helpers
    private fun updateStatus() {
        if (!ready) return
        val d = diag
        statusView.text = "backend: ${if (connected) "connected" else if (client.configured()) "NOT reachable" else "not paired"} · X: $auth · " +
            "$backendState · step: $modeKind${if (modeTarget.isNotEmpty()) " $modeTarget" else ""}${if (hold) " (settling)" else ""} · page: $page · sent: $collected" +
            (if (d != null) " · on page: ${d.optInt("articles")} posts, ${d.optInt("cells")} users, in-scope=${d.optBoolean("scope")}" else "") +
            (if (enriching) " · enriching ${enrichQueue.size} left" else "") +
            (pageChallenge?.let { " · CHALLENGE: $it - solve it in X view, then Resume in dashboard" } ?: "")
    }

    private fun showPairDialog() {
        val tok = EditText(this).apply { hint = "pairing token (dashboard > Show pairing)"; setText(client.token()); inputType = InputType.TYPE_CLASS_TEXT }
        val port = EditText(this).apply { hint = "port"; setText(client.port()); inputType = InputType.TYPE_CLASS_NUMBER }
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 16, 32, 0); addView(tok); addView(port) }
        AlertDialog.Builder(this).setTitle("Pair with XBotScope").setView(box)
            .setPositiveButton("Save") { _, _ ->
                val ok = client.savePairing(tok.text.toString().trim(), port.text.toString().trim())
                Toast.makeText(this, if (ok) "Paired" else "Invalid token or port", Toast.LENGTH_SHORT).show()
                if (ok) loadDashboard()
            }.setNegativeButton("Cancel", null).show()
    }

    private fun confirmClear() {
        AlertDialog.Builder(this).setTitle("Clear browser session?")
            .setMessage("Logs you out of X and deletes this browser's cookies, cache and site data. Saved XBotScope results are not touched.")
            .setPositiveButton("Clear") { _, _ -> clearSession() }.setNegativeButton("Cancel", null).show()
    }

    /** Deletes the WebView's own website data. Cookies are only ever deleted here, never read. */
    private fun clearSession() {
        enrichQueue.clear(); enriching = false
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
        WebStorage.getInstance().deleteAllData()
        web.clearCache(true); web.clearHistory(); web.clearFormData()
        web.loadUrl("about:blank")
        Toast.makeText(this, "Browser session cleared", Toast.LENGTH_SHORT).show()
    }

    private fun handleUri(d: Uri?) {
        if (d == null) return
        if (d.scheme == "xbotscope" && d.host == "pair") {
            val ok = client.savePairing(d.getQueryParameter("token") ?: "", d.getQueryParameter("port") ?: "8080")
            Toast.makeText(this, if (ok) "Paired with XBotScope" else "Invalid pairing link", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onNewIntent(intent: android.content.Intent?) { super.onNewIntent(intent); if (ready) handleUri(intent?.data) }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (!ready) { super.onBackPressed(); return }
        if (dash.visibility == View.VISIBLE) { if (dash.canGoBack()) dash.goBack() else showDashboard(false) }
        else if (web.canGoBack()) web.goBack()
        else super.onBackPressed()
    }

    override fun onDestroy() {
        ui.removeCallbacksAndMessages(null)
        if (ready) { web.destroy(); dash.destroy() }
        super.onDestroy()
    }
}
