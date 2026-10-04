package it.maipal.watch

import android.app.Application
import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.IOException

sealed interface Voice {
    data object Idle : Voice
    data class Recording(val startedAt: Long) : Voice
    data class Working(val label: String) : Voice
}

sealed interface Loadable<out T> {
    data object Loading : Loadable<Nothing>
    data class Ready<T>(val data: T) : Loadable<T>
    data class Failed(val message: String) : Loadable<Nothing>
}

data class Answer(
    val agent: String, val transcript: String, val reply: String, val kind: String,
    val draft: JSONObject?, val convId: String?, val activated: Boolean = false,
)

/** Where the app should go: emitted here, followed by the navigation host. */
enum class Go { PAIR, HOME, ANSWER }

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val store = Store(app)
    private val api = Api { store.token }
    private val recorder = Recorder(app)

    val linked get() = store.token != null
    val events = MutableSharedFlow<Go>(extraBufferCapacity = 4)

    var agent by mutableStateOf(store.agent); private set
    var voice by mutableStateOf<Voice>(Voice.Idle); private set
    var answer by mutableStateOf<Answer?>(null); private set
    var message by mutableStateOf<String?>(null); private set

    var pairCode by mutableStateOf<String?>(null); private set
    var pairError by mutableStateOf<String?>(null); private set
    var userName by mutableStateOf(store.name); private set

    var tasks by mutableStateOf<Loadable<TasksData>>(Loadable.Loading); private set
    var todos by mutableStateOf<Loadable<List<TodoItem>>>(Loadable.Loading); private set
    var lists by mutableStateOf<Loadable<List<ListSummary>>>(Loadable.Loading); private set
    var openList by mutableStateOf<Loadable<ListDetail>>(Loadable.Loading); private set

    private var pairJob: Job? = null
    private var messageJob: Job? = null
    private var autoStop: Job? = null
    private var recAgent = agent
    private var recConv: String? = null

    private fun errorText(e: Exception) = when (e) {
        is ApiException -> e.message ?: "Errore"
        is IOException -> "Nessuna connessione con mAIPAL"
        else -> e.message ?: "Errore"
    }

    /** Runs a server call; a 401 (watch unlinked from the phone) sends back to the pairing. */
    private suspend fun <T> guarded(onError: (String) -> Unit, block: suspend () -> T): T? = try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        if (e is ApiException && e.code == 401) logout() else onError(errorText(e))
        null
    }

    private fun flash(text: String) {
        message = text
        messageJob?.cancel()
        messageJob = viewModelScope.launch { delay(4000); message = null }
    }

    fun logout() {
        store.token = null
        answer = null
        events.tryEmit(Go.PAIR)
    }

    // ---- pairing: show a code, wait for the phone to confirm it ----
    fun startPairing() {
        if (pairJob?.isActive == true) return
        pairJob = viewModelScope.launch {
            while (isActive) {
                val start = try {
                    api.pairStart()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    pairCode = null
                    pairError = errorText(e)
                    delay(5000)
                    continue
                }
                pairError = null
                pairCode = start.code
                val until = SystemClock.elapsedRealtime() + start.expiresIn * 1000L
                while (isActive && SystemClock.elapsedRealtime() < until) {
                    delay(3000)
                    val st = try {
                        api.pairStatus(start.pairId)
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        pairError = errorText(e)
                        continue
                    }
                    pairError = null
                    when (st.optString("status")) {
                        "linked" -> {
                            store.token = st.getString("token")
                            store.name = st.optString("name")
                            userName = store.name
                            pairCode = null
                            events.emit(Go.HOME)
                            return@launch
                        }
                        "expired" -> break
                    }
                }
            }
        }
    }

    fun stopPairing() { pairJob?.cancel() }

    // ---- agents and voice ----
    fun selectAgent(id: String) {
        agent = id
        store.agent = id
    }

    fun stepAgent(step: Int) {
        val i = AGENTS.indexOfFirst { it.id == agent }
        selectAgent(AGENTS[(i + step).mod(AGENTS.size)].id)
    }

    /** The mic: first tap records, the second sends. From the home a new conversation with the
     *  selected agent; from an answer, the same conversation goes on. */
    fun micTapped(continueAnswer: Boolean) {
        when (voice) {
            is Voice.Idle -> startRecording(continueAnswer)
            is Voice.Recording -> finishRecording()
            is Voice.Working -> Unit
        }
    }

    fun permissionDenied() = flash("Serve il permesso del microfono")

    private fun startRecording(continueAnswer: Boolean) {
        val a = answer
        recAgent = if (continueAnswer && a != null) a.agent else agent
        recConv = if (continueAnswer && a != null) a.convId else null
        try {
            recorder.start()
        } catch (e: Exception) {
            flash("Microfono non disponibile")
            return
        }
        message = null
        voice = Voice.Recording(SystemClock.elapsedRealtime())
        autoStop = viewModelScope.launch {
            delay(60_000)
            if (voice is Voice.Recording) finishRecording()
        }
    }

    fun cancelRecording() {
        autoStop?.cancel()
        recorder.cancel()
        voice = Voice.Idle
    }

    private fun finishRecording() {
        autoStop?.cancel()
        val file = recorder.stop()
        if (file == null || file.length() < 2000) {
            voice = Voice.Idle
            flash("Non ho sentito nulla")
            return
        }
        val ag = recAgent
        val conv = recConv
        viewModelScope.launch {
            voice = Voice.Working("Trascrivo…")
            val text = guarded(::flash) { api.transcribe(file, ag) }
            file.delete()
            if (text == null) { voice = Voice.Idle; return@launch }
            if (text.isBlank()) { voice = Voice.Idle; flash("Non ho capito, riprova"); return@launch }
            voice = Voice.Working("Ci penso…")
            val res = guarded(::flash) { api.ask(ag, text, conv) }
            voice = Voice.Idle
            if (res != null) {
                answer = Answer(ag, text, cleanReply(res.reply), res.kind, res.draft, res.convId ?: conv)
                events.emit(Go.ANSWER)
            }
        }
    }

    fun activateAction() {
        val a = answer ?: return
        val draft = a.draft ?: return
        viewModelScope.launch {
            voice = Voice.Working("Attivo…")
            val ok = guarded(::flash) { api.activateAction(draft) } != null
            voice = Voice.Idle
            if (ok) answer = a.copy(activated = true)
        }
    }

    // ---- sections ----
    fun loadTasks() = viewModelScope.launch {
        if (tasks !is Loadable.Ready) tasks = Loadable.Loading
        guarded({ tasks = Loadable.Failed(it) }) { api.tasks() }?.let { tasks = Loadable.Ready(it) }
    }

    fun completeTask(id: String) {
        val cur = (tasks as? Loadable.Ready)?.data ?: return
        tasks = Loadable.Ready(cur.copy(tasks = cur.tasks.map { if (it.id == id) it.copy(status = "done") else it }))
        viewModelScope.launch { guarded({ flash(it); loadTasks() }) { api.taskDone(id) } }
    }

    fun loadTodos() = viewModelScope.launch {
        if (todos !is Loadable.Ready) todos = Loadable.Loading
        guarded({ todos = Loadable.Failed(it) }) { api.todos() }?.let { todos = Loadable.Ready(it) }
    }

    fun completeTodo(id: String) {
        val cur = (todos as? Loadable.Ready)?.data ?: return
        todos = Loadable.Ready(cur.filterNot { it.id == id })
        viewModelScope.launch { guarded({ flash(it); loadTodos() }) { api.todoDone(id) } }
    }

    fun loadLists() = viewModelScope.launch {
        if (lists !is Loadable.Ready) lists = Loadable.Loading
        guarded({ lists = Loadable.Failed(it) }) { api.lists() }?.let { lists = Loadable.Ready(it) }
    }

    fun loadList(id: String) = viewModelScope.launch {
        if ((openList as? Loadable.Ready)?.data?.id != id) openList = Loadable.Loading
        guarded({ openList = Loadable.Failed(it) }) { api.list(id) }?.let { openList = Loadable.Ready(it) }
    }

    override fun onCleared() {
        recorder.cancel()
    }
}

/** The agents answer in Markdown for the phone; on the watch it's plain text. */
fun cleanReply(text: String): String = text
    .replace(Regex("\\*\\*(.+?)\\*\\*"), "$1")
    .replace(Regex("(?m)^#{1,6}\\s*"), "")
    .replace(Regex("(?m)^\\s*[-*]\\s+"), "• ")
    .replace(Regex("\\[(.+?)]\\((.+?)\\)"), "$1")
    .trim()
