// Author: gorcoding
package com.gorcoding.xbotscope

import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/** Talks ONLY to the local XBotScope backend (127.0.0.1). Sends structured public records, never cookies or credentials. */
class BridgeClient(private val prefs: SharedPreferences) {
    private val exec = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())

    fun token(): String = prefs.getString("token", "") ?: ""
    fun port(): String = prefs.getString("port", "8080") ?: "8080"
    fun configured(): Boolean = token().isNotEmpty()

    fun savePairing(token: String, port: String): Boolean {
        if (!Regex("[A-Za-z0-9_-]{16,64}").matches(token)) return false
        val p = port.toIntOrNull() ?: return false
        if (p !in 1024..65535) return false
        prefs.edit().putString("token", token).putString("port", p.toString()).apply()
        return true
    }

    /** POST JSON to the backend; callback runs on the main thread with the parsed response or null on failure. */
    fun post(path: String, body: JSONObject, cb: (JSONObject?) -> Unit) {
        if (!configured()) { cb(null); return }
        val url = "http://127.0.0.1:${port()}$path"
        val tok = token()
        exec.execute {
            var res: JSONObject? = null
            try {
                val c = URL(url).openConnection() as HttpURLConnection
                c.requestMethod = "POST"
                c.connectTimeout = 2500
                c.readTimeout = 6000
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.setRequestProperty("X-Bridge-Token", tok)
                c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                if (c.responseCode == 200) res = JSONObject(c.inputStream.bufferedReader().readText())
                c.disconnect()
            } catch (e: Exception) {
                res = null
            }
            main.post { cb(res) }
        }
    }
}
