package it.maipal.watch

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/** An HTTP error answered by the server; `code` 401 means the watch was unlinked. */
class ApiException(val code: Int, message: String) : Exception(message)

data class PairStart(val pairId: String, val code: String, val expiresIn: Int)
data class TaskItem(val id: String, val title: String, val date: String, val time: String, val status: String)
data class TasksData(val today: String, val tasks: List<TaskItem>)
data class TodoItem(val id: String, val title: String, val percent: Int)
data class ListSummary(val id: String, val name: String, val count: Int)
data class ListEntry(val id: String, val label: String, val detail: String)
data class ListDetail(val id: String, val name: String, val items: List<ListEntry>)
data class AskResult(val kind: String, val reply: String, val convId: String?, val draft: JSONObject?)

/** The mAIPAL server's /api, called with the watch's own session token. */
class Api(private val token: () -> String?) {
    private val base = BuildConfig.MAIPAL_URL + "/api"
    private val json = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)      // an agent's answer can take a while
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    private suspend fun call(method: String, path: String, body: RequestBody? = null, auth: Boolean = true): String =
        withContext(Dispatchers.IO) {
            val b = Request.Builder().url(base + path)
                .header("Accept", "application/json")
                .header("User-Agent", "mAIPAL-Watch/${BuildConfig.VERSION_NAME} (Wear OS)")
            if (auth) token()?.let { b.header("Authorization", "Bearer $it") }
            b.method(method, body ?: if (method == "POST") ByteArray(0).toRequestBody(null) else null)
            client.newCall(b.build()).execute().use { r ->
                val text = r.body?.string().orEmpty()
                if (!r.isSuccessful) throw ApiException(r.code, detailOf(text) ?: "Errore del server (${r.code})")
                text
            }
        }

    private fun detailOf(text: String): String? =
        try { JSONObject(text).optString("detail").ifBlank { null } } catch (e: Exception) { null }

    private fun jsonBody(o: JSONObject) = o.toString().toRequestBody(json)

    suspend fun pairStart(): PairStart = JSONObject(call("POST", "/watch/pair/start", auth = false)).let {
        PairStart(it.getString("pair_id"), it.getString("code"), it.optInt("expires_in", 600))
    }

    suspend fun pairStatus(pairId: String): JSONObject =
        JSONObject(call("GET", "/watch/pair/status?pair_id=" + URLEncoder.encode(pairId, "UTF-8"), auth = false))

    suspend fun me(): JSONObject = JSONObject(call("GET", "/watch/me"))

    suspend fun tasks(): TasksData {
        val o = JSONObject(call("GET", "/watch/tasks"))
        val arr = o.getJSONArray("tasks")
        return TasksData(o.optString("today"), (0 until arr.length()).map { i ->
            val t = arr.getJSONObject(i)
            TaskItem(t.getString("id"), t.optString("title"), t.optString("date"), t.optString("time"), t.optString("status"))
        })
    }

    suspend fun taskDone(id: String) { call("POST", "/watch/tasks/$id/done") }

    suspend fun todos(): List<TodoItem> {
        val arr = JSONArray(call("GET", "/watch/todos"))
        return (0 until arr.length()).map { i ->
            val t = arr.getJSONObject(i)
            TodoItem(t.getString("id"), t.optString("title"), t.optInt("percent"))
        }
    }

    suspend fun todoDone(id: String) { call("POST", "/watch/todos/$id/done") }

    suspend fun lists(): List<ListSummary> {
        val arr = JSONArray(call("GET", "/watch/lists"))
        return (0 until arr.length()).map { i ->
            val l = arr.getJSONObject(i)
            ListSummary(l.getString("id"), l.optString("name"), l.optInt("count"))
        }
    }

    suspend fun list(id: String): ListDetail {
        val o = JSONObject(call("GET", "/watch/lists/$id"))
        val arr = o.getJSONArray("items")
        return ListDetail(o.getString("id"), o.optString("name"), (0 until arr.length()).map { i ->
            val e = arr.getJSONObject(i)
            ListEntry(e.getString("id"), e.optString("label"), e.optString("detail"))
        })
    }

    /** Speech to text on the server (Whisper), the same one the phone's voice notes use. */
    suspend fun transcribe(file: File, agent: String): String {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "voce.m4a", file.asRequestBody("audio/mp4".toMediaType()))
            .addFormDataPart("action", agent)
            .build()
        return JSONObject(call("POST", "/voice/transcribe", body)).optString("text").trim()
    }

    suspend fun ask(agent: String, text: String, convId: String?): AskResult {
        val payload = JSONObject().put("agent", agent).put("text", text)
        if (convId != null) payload.put("conv_id", convId)
        val o = JSONObject(call("POST", "/watch/ask", jsonBody(payload)))
        return AskResult(
            o.optString("kind", "answer"), o.optString("reply"),
            o.optString("conv_id").ifBlank { null }, o.optJSONObject("draft"),
        )
    }

    suspend fun activateAction(draft: JSONObject) {
        call("POST", "/scheduled-actions", jsonBody(JSONObject().put("draft", draft)))
    }
}
