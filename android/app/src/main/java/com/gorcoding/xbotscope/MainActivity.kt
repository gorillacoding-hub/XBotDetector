// Author: gorcoding
package com.gorcoding.xbotscope

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONArray
import org.json.JSONObject

/**
 * XBotScope Browser (V2): a plain WebView on https://x.com with its own persistent session.
 * - The user logs in manually; this app never reads passwords, codes, cookies or tokens.
 * - A page script (assets/collector.js, injected for https://x.com only) reports PUBLIC search-result fields.
 * - Only structured records go to the local backend (127.0.0.1), authorised by a local pairing token.
 */
class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var web: WebView
    private lateinit var statusView: TextView
    private lateinit var client: BridgeClient
    private var ready = false

    // state mirrored from the backend / page
    private var backendState = "idle"
    private var query = ""
    private var autoscroll = false
    private var connected = false
    private var auth = "unknown"
    private var page = "other"
    private var pageChallenge: String? = null
    private var endOfResults = false
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
        setupWebView()
        handleIntent(intent)
        web.loadUrl("https://x.com/home")
        if (!client.configured()) showPairDialog()
        ui.post(beat)
    }

    private fun btn(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; textSize = 12f; setOnClickListener { onClick() }
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.BLACK) }
        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        bar.addView(btn("← XBotScope") { backToDashboard() })
        bar.addView(btn("Reload") { web.reload() })
        bar.addView(btn("X home") { web.loadUrl("https://x.com/home") })
        bar.addView(btn("Pair") { showPairDialog() })
        bar.addView(btn("Clear session") { confirmClear() })
        bar.addView(btn("Close") { finish() })
        root.addView(HorizontalScrollView(this).apply { addView(bar) })
        statusView = TextView(this).apply { setTextColor(Color.LTGRAY); textSize = 11f; setPadding(12, 4, 12, 4) }
        root.addView(statusView)
        web = WebView(this)
        root.addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
        updateStatus()
    }

    private fun setupWebView() {
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

    // ---------- page -> app
    private fun onPageMessage(data: String) {
        if (data.length > 400_000) return
        val o = try { JSONObject(data) } catch (e: Exception) { return }
        when (o.optString("t")) {
            "state" -> {
                auth = o.optString("auth", "unknown"); page = o.optString("page", "other")
                pageChallenge = o.optString("challenge", "").ifEmpty { null }
                endOfResults = o.optBoolean("end", false)
                updateStatus()
            }
            "records" -> if (backendState == "running" && !enriching) {
                val body = JSONObject().put("query", query).put("records", o.optJSONArray("records") ?: JSONArray())
                client.post("/api/bridge/in/records", body) { r ->
                    if (r != null) {
                        backendState = r.optString("state", backendState)
                        collected += r.optInt("accepted", 0)
                        pushControl(); updateStatus()
                    }
                }
            }
            "profile" -> {
                val body = JSONObject().put("profile", o.optJSONObject("profile") ?: JSONObject())
                client.post("/api/bridge/in/profile", body) { }
            }
        }
    }

    // ---------- app <-> backend
    private fun heartbeat() {
        val body = JSONObject().put("app", "2.0.0").put("auth", auth).put("page", page)
            .put("challenge", pageChallenge ?: JSONObject.NULL).put("end", endOfResults)
        client.post("/api/bridge/in/heartbeat", body) { r ->
            connected = r != null
            if (r != null) {
                backendState = r.optString("state", "idle")
                query = r.optString("query", "")
                autoscroll = r.optJSONObject("opts")?.optBoolean("autoscroll", false) == true
                r.optJSONArray("commands")?.let { arr -> for (i in 0 until arr.length()) handleCommand(arr.getJSONObject(i)) }
                pushControl()
            }
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

    private fun pushControl() {
        val active = backendState == "running" && !enriching
        web.evaluateJavascript("window.__xbs&&window.__xbs.ctl({active:$active,autoscroll:${active && autoscroll}})", null)
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
        statusView.text = "backend: ${if (connected) "connected" else if (client.configured()) "NOT reachable" else "not paired"} · X: $auth · " +
            "collection: $backendState · page: $page · sent: $collected" +
            (if (enriching) " · enriching ${enrichQueue.size} left" else "") +
            (pageChallenge?.let { " · CHALLENGE: $it - solve it here, then press Resume in XBotScope" } ?: "")
    }

    private fun backToDashboard() {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("http://127.0.0.1:${client.port()}")))
    }

    private fun showPairDialog() {
        val tok = EditText(this).apply { hint = "pairing token (from dashboard)"; setText(client.token()); inputType = InputType.TYPE_CLASS_TEXT }
        val port = EditText(this).apply { hint = "port"; setText(client.port()); inputType = InputType.TYPE_CLASS_NUMBER }
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 16, 32, 0); addView(tok); addView(port) }
        AlertDialog.Builder(this).setTitle("Pair with XBotScope").setView(box)
            .setPositiveButton("Save") { _, _ ->
                val ok = client.savePairing(tok.text.toString().trim(), port.text.toString().trim())
                Toast.makeText(this, if (ok) "Paired" else "Invalid token or port", Toast.LENGTH_SHORT).show()
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

    private fun handleIntent(i: Intent?) {
        val d = i?.data ?: return
        if (d.scheme == "xbotscope" && d.host == "pair") {
            val ok = client.savePairing(d.getQueryParameter("token") ?: "", d.getQueryParameter("port") ?: "8080")
            Toast.makeText(this, if (ok) "Paired with XBotScope" else "Invalid pairing link", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onNewIntent(intent: Intent?) { super.onNewIntent(intent); if (ready) handleIntent(intent) }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() { if (ready && web.canGoBack()) web.goBack() else @Suppress("DEPRECATION") super.onBackPressed() }

    override fun onDestroy() {
        ui.removeCallbacksAndMessages(null)
        if (ready) web.destroy()
        super.onDestroy()
    }
}
