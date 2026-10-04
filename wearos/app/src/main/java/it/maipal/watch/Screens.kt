package it.maipal.watch

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListScope
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

/** A scrolling page (crown / bezel scroll it) on the app background. */
@Composable
fun Page(content: ScalingLazyListScope.() -> Unit) {
    val state = rememberScalingLazyListState()
    Screen {
        Scaffold(positionIndicator = { PositionIndicator(scalingLazyListState = state) }) {
            ScalingLazyColumn(
                state = state,
                modifier = Modifier.fillMaxWidth(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp, vertical = 28.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
                content = content,
            )
        }
    }
}

fun ScalingLazyListScope.title(text: String) = item {
    Text(text, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
        textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(bottom = 2.dp))
}

fun ScalingLazyListScope.note(text: String, onClick: (() -> Unit)? = null) = item {
    Text(text, fontSize = 12.sp, color = Color.White.copy(alpha = .8f), textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(6.dp))
}

fun ScalingLazyListScope.spinner() = item {
    Box(Modifier.fillMaxWidth().padding(10.dp), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(Modifier.size(26.dp), indicatorColor = Color.White, trackColor = Color.White.copy(alpha = .15f), strokeWidth = 2.5.dp)
    }
}

/** Loading / error (tap to retry) / content, the same for every section. */
fun <T> ScalingLazyListScope.loadable(state: Loadable<T>, retry: () -> Unit, content: ScalingLazyListScope.(T) -> Unit) {
    when (state) {
        is Loadable.Loading -> spinner()
        is Loadable.Failed -> note("${state.message}\nTocca per riprovare", retry)
        is Loadable.Ready -> content(state.data)
    }
}

@Composable
private fun CheckCircle(done: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.size(30.dp).clip(CircleShape)
            .background(if (done) Color.White.copy(alpha = .9f) else Color.White.copy(alpha = .22f))
            .clickable(enabled = !done, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        if (done) Icon(Lucide.Check, "Fatto", Modifier.size(16.dp), tint = Wine)
    }
}

@Composable
private fun Row2(title: String, sub: String?, done: Boolean = false, badge: String? = null, end: @Composable () -> Unit) {
    GlassCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, fontSize = 13.sp, color = Color.White.copy(alpha = if (done) .6f else 1f), maxLines = 2,
                    overflow = TextOverflow.Ellipsis, textDecoration = if (done) TextDecoration.LineThrough else null)
                if (!sub.isNullOrBlank() || badge != null) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (badge != null) {
                            Box(Modifier.size(6.dp).background(LateRed, CircleShape))
                            Spacer(Modifier.width(4.dp))
                            Text(badge, fontSize = 10.sp, color = Color.White.copy(alpha = .85f))
                            if (!sub.isNullOrBlank()) Spacer(Modifier.width(6.dp))
                        }
                        if (!sub.isNullOrBlank()) Text(sub, fontSize = 10.sp, color = Color.White.copy(alpha = .7f), maxLines = 1)
                    }
                }
            }
            Spacer(Modifier.width(8.dp))
            end()
        }
    }
}

// ---------------- pairing ----------------
@Composable
fun PairScreen(vm: MainViewModel) {
    DisposableEffect(Unit) {
        vm.startPairing()
        onDispose { vm.stopPairing() }
    }
    Page {
        item {
            Box(Modifier.size(40.dp).clip(CircleShape).background(GlassBrush), contentAlignment = Alignment.Center) {
                Text("m", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Color.White)
            }
        }
        title("Collega mAIPAL")
        item {
            val code = vm.pairCode
            if (code == null) {
                Box(Modifier.padding(8.dp)) {
                    CircularProgressIndicator(Modifier.size(24.dp), indicatorColor = Color.White, trackColor = Color.White.copy(alpha = .15f), strokeWidth = 2.5.dp)
                }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    code.forEach { c ->
                        Box(Modifier.width(24.dp).height(34.dp).clip(RoundedCornerShape(9.dp)).background(GlassBrush),
                            contentAlignment = Alignment.Center) {
                            Text(c.toString(), fontSize = 19.sp, fontWeight = FontWeight.Medium, color = Color.White)
                        }
                    }
                }
            }
        }
        note("Sul telefono apri mAIPAL › Impostazioni › Collegamenti › Orologio e scrivi questo codice")
        vm.pairError?.let { note(it) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Lucide.Phone, null, Modifier.size(13.dp), tint = Color.White.copy(alpha = .7f))
                Spacer(Modifier.width(5.dp))
                Text("in attesa del telefono…", fontSize = 11.sp, color = Color.White.copy(alpha = .7f))
            }
        }
    }
}

// ---------------- an agent's answer ----------------
@Composable
fun AnswerScreen(vm: MainViewModel, onClose: () -> Unit) {
    val a = vm.answer ?: run { LaunchedEffect(Unit) { onClose() }; return }
    val onMic = rememberMicAction(vm, continueAnswer = true)
    KeepScreenOn(vm.voice !is Voice.Idle)
    val agent = agentOf(a.agent)
    Page {
        item {
            Row(
                Modifier.clip(RoundedCornerShape(13.dp)).background(GlassBrush).padding(horizontal = 10.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(agent.icon, null, Modifier.size(13.dp), tint = Color.White)
                Spacer(Modifier.width(5.dp))
                Text(agent.name, fontSize = 11.sp, color = Color.White)
            }
        }
        item {
            Text("«${a.transcript}»", fontSize = 11.sp, fontStyle = FontStyle.Italic, color = Color.White.copy(alpha = .75f),
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
        item {
            GlassCard {
                Text(a.reply.ifBlank { "Fatto" }, fontSize = 14.sp, color = Color.White, lineHeight = 19.sp)
            }
        }
        if (a.kind == "confirm_action") {
            item {
                if (a.activated) {
                    Text("Azione attivata", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Color.White)
                } else {
                    Box(
                        Modifier.clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = .9f))
                            .clickable(enabled = vm.voice is Voice.Idle) { vm.activateAction() }
                            .padding(horizontal = 22.dp, vertical = 9.dp),
                    ) {
                        Text("Attiva", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Wine)
                    }
                }
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                RoundIcon(Lucide.X, "Chiudi", 40.dp, glass = true) {
                    vm.cancelRecording()
                    onClose()
                }
                MicButton(52.dp, vm.voice, onMic)
            }
        }
        item { MicCaption(vm, "continua a parlare") }
        vm.message?.let { m -> item { Flash(m) } }
    }
}

// ---------------- sections ----------------
private val DAY = DateTimeFormatter.ofPattern("EEE d", Locale.ITALIAN)

@Composable
fun TasksScreen(vm: MainViewModel) {
    LaunchedEffect(Unit) { vm.loadTasks() }
    Page {
        title("Task")
        loadable(vm.tasks, { vm.loadTasks() }) { data ->
            if (data.tasks.isEmpty()) note("Niente in programma per i prossimi giorni")
            val groups = listOf(
                "Scaduti" to data.tasks.filter { it.status == "late" },
                "Oggi" to data.tasks.filter { it.status == "today" || it.status == "done" },
                "Prossimi giorni" to data.tasks.filter { it.status == "upcoming" },
            )
            for ((label, list) in groups) {
                if (list.isEmpty()) continue
                item {
                    Text(label, fontSize = 11.sp, color = Color.White.copy(alpha = .75f), modifier = Modifier.fillMaxWidth().padding(start = 6.dp, top = 4.dp))
                }
                list.forEach { t ->
                    item(key = t.id) {
                        val day = runCatching { LocalDate.parse(t.date).format(DAY) }.getOrDefault(t.date)
                        val sub = when (t.status) {
                            "today", "done" -> t.time
                            else -> listOf(day, t.time).filter { it.isNotBlank() }.joinToString(" · ")
                        }
                        Row2(t.title, sub, done = t.status == "done", badge = if (t.status == "late") "scaduto" else null) {
                            CheckCircle(t.status == "done") { vm.completeTask(t.id) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun TodosScreen(vm: MainViewModel) {
    LaunchedEffect(Unit) { vm.loadTodos() }
    Page {
        title("To-Do")
        loadable(vm.todos, { vm.loadTodos() }) { list ->
            if (list.isEmpty()) note("Nessun to-do aperto")
            list.forEach { t ->
                item(key = t.id) {
                    Row2(t.title, if (t.percent > 0) "${t.percent}%" else null) {
                        CheckCircle(false) { vm.completeTodo(t.id) }
                    }
                }
            }
        }
    }
}

@Composable
fun ListsScreen(vm: MainViewModel, onOpen: (String) -> Unit) {
    LaunchedEffect(Unit) { vm.loadLists() }
    Page {
        title("Liste")
        loadable(vm.lists, { vm.loadLists() }) { list ->
            if (list.isEmpty()) note("Nessuna lista: creala dal telefono o con l'agente Salva")
            list.forEach { l ->
                item(key = l.id) {
                    GlassCard(onClick = { onOpen(l.id) }) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(l.name, fontSize = 13.sp, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f))
                            Text("${l.count}", fontSize = 12.sp, color = Color.White.copy(alpha = .75f))
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ListScreen(vm: MainViewModel, id: String) {
    LaunchedEffect(id) { vm.loadList(id) }
    Page {
        loadable(vm.openList, { vm.loadList(id) }) { l ->
            title(l.name)
            if (l.items.isEmpty()) note("La lista è vuota")
            l.items.forEach { e ->
                item(key = e.id) {
                    GlassCard {
                        Column {
                            Text(e.label, fontSize = 13.sp, color = Color.White, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            if (e.detail.isNotBlank()) Text(e.detail, fontSize = 10.sp, color = Color.White.copy(alpha = .7f), maxLines = 1)
                        }
                    }
                }
            }
        }
    }
}
