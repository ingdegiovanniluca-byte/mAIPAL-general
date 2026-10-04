package it.maipal.watch

import android.Manifest
import android.content.pm.PackageManager
import android.os.SystemClock
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/** Angles of the icons, clockwise from 12 o'clock: the sections on top, the agents below. */
private val SECTION_ANGLES = listOf(-54f, -18f, 18f, 54f)
private val AGENT_ANGLES = listOf(248f, 214f, 180f, 146f, 112f)
private const val RING = .68f       // centre line of the two half-rings, as a share of the screen's radius
private const val RING_W = .36f     // their width

class Section(val route: String, val name: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

val SECTIONS = listOf(
    Section("chat", "Chat", Lucide.Chat),
    Section("tasks", "Task", Lucide.SquareCheck),
    Section("todos", "To-Do", Lucide.ListChecks),
    Section("lists", "Liste", Lucide.List),
)

/** Asks for the microphone the first time, then hands the tap to the view model. */
@Composable
fun rememberMicAction(vm: MainViewModel, continueAnswer: Boolean): () -> Unit {
    val ctx = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) vm.micTapped(continueAnswer) else vm.permissionDenied()
    }
    return {
        val granted = ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        if (granted || vm.voice !is Voice.Idle) vm.micTapped(continueAnswer) else launcher.launch(Manifest.permission.RECORD_AUDIO)
    }
}

/** Keeps the screen on while recording or waiting for the answer. */
@Composable
fun KeepScreenOn(on: Boolean) {
    val view = LocalView.current
    DisposableEffect(on) {
        view.keepScreenOn = on
        onDispose { view.keepScreenOn = false }
    }
}

@Composable
fun HomeScreen(vm: MainViewModel, onSection: (String) -> Unit) {
    val onMic = rememberMicAction(vm, continueAnswer = false)
    val focus = remember { FocusRequester() }
    var rotary by remember { mutableFloatStateOf(0f) }
    KeepScreenOn(vm.voice !is Voice.Idle)

    Screen {
        BoxWithConstraints(
            Modifier
                .fillMaxSize()
                // the bezel / crown changes agent
                .onRotaryScrollEvent { e ->
                    rotary += e.verticalScrollPixels
                    if (abs(rotary) > 70f) {
                        vm.stepAgent(if (rotary > 0) 1 else -1)
                        rotary = 0f
                    }
                    true
                }
                .focusRequester(focus)
                .focusable(),
        ) {
            val radius = min(maxWidth.value, maxHeight.value) / 2
            val cx = maxWidth / 2
            val cy = maxHeight / 2
            val btn = (radius * .34f).coerceIn(30f, 44f).dp
            val mic = (radius * .58f).dp

            HalfRings()

            fun polar(phi: Float, size: Dp): Modifier {
                val a = Math.toRadians(phi.toDouble())
                val r = radius * RING
                return Modifier.offset(
                    x = cx + (r * sin(a)).toFloat().dp - size / 2,
                    y = cy - (r * cos(a)).toFloat().dp - size / 2,
                )
            }

            SECTIONS.forEachIndexed { i, s ->
                Box(polar(SECTION_ANGLES[i], btn)) {
                    RoundIcon(s.icon, s.name, btn, active = s.route == "chat") { onSection(s.route) }
                }
            }
            AGENTS.forEachIndexed { i, a ->
                Box(polar(AGENT_ANGLES[i], btn)) {
                    RoundIcon(a.icon, a.name, btn, active = a.id == vm.agent) { vm.selectAgent(a.id) }
                }
            }

            Clock(Modifier.align(Alignment.TopCenter).padding(top = (radius * .05f).dp))
            // the agent's name (or what is happening) sits above the mic: below it, the agents' icons
            Box(Modifier.align(Alignment.Center).offset(y = -(mic / 2) - 10.dp)) {
                MicCaption(vm, agentOf(vm.agent).name)
            }
            Box(Modifier.align(Alignment.Center)) {
                MicButton(mic, vm.voice, onMic)
            }
            Flash(vm.message, Modifier.align(Alignment.Center).offset(y = mic / 2 + 18.dp))
        }
    }
    LaunchedEffect(Unit) { focus.requestFocus() }
}

/** The two very transparent half-rings the icons sit on. */
@Composable
private fun HalfRings() {
    Canvas(Modifier.fillMaxSize()) {
        val r = size.minDimension / 2 * RING
        val w = size.minDimension / 2 * RING_W
        val tl = Offset(center.x - r, center.y - r)
        val brush = Brush.verticalGradient(listOf(Color.White.copy(alpha = .07f), Color.White.copy(alpha = .035f)))
        fun band(from: Float, to: Float) = drawArc(
            brush, startAngle = from - 90f, sweepAngle = to - from, useCenter = false,
            topLeft = tl, size = Size(2 * r, 2 * r), style = Stroke(width = w, cap = StrokeCap.Round),
        )
        band(SECTION_ANGLES.first(), SECTION_ANGLES.last())
        band(AGENT_ANGLES.last(), AGENT_ANGLES.first())
    }
}

@Composable
private fun Clock(modifier: Modifier) {
    var now by remember { mutableStateOf(Date()) }
    LaunchedEffect(Unit) {
        while (true) {
            now = Date()
            delay(60_000L - System.currentTimeMillis() % 60_000L)
        }
    }
    Text(SimpleDateFormat("HH:mm", Locale.ITALY).format(now), fontSize = 12.sp, fontWeight = FontWeight.Medium,
        color = Color.White.copy(alpha = .9f), modifier = modifier)
}

/** A short notice (no connection, nothing heard...) on a wine pill, over everything else. */
@Composable
fun Flash(text: String?, modifier: Modifier = Modifier) {
    if (text == null) return
    Text(
        text, fontSize = 11.sp, lineHeight = 14.sp, color = Color.White, textAlign = TextAlign.Center, maxLines = 3,
        modifier = modifier
            .width(150.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(Wine.copy(alpha = .92f))
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

/** The agent's name by the mic, or what is happening: recording time, working. */
@Composable
fun MicCaption(vm: MainViewModel, idle: String) {
    val v = vm.voice
    var tick by remember { mutableLongStateOf(0L) }
    if (v is Voice.Recording) {
        LaunchedEffect(v) {
            while (true) {
                tick = (SystemClock.elapsedRealtime() - v.startedAt) / 1000
                delay(250)
            }
        }
    }
    val (text, size, weight) = when {
        v is Voice.Recording -> Triple("%d:%02d".format(tick / 60, tick % 60), 13.sp, FontWeight.Medium)
        v is Voice.Working -> Triple(v.label, 12.sp, FontWeight.Normal)
        else -> Triple(idle, 13.sp, FontWeight.SemiBold)
    }
    Text(text, fontSize = size, lineHeight = size * 1.15f, fontWeight = weight, color = Color.White, textAlign = TextAlign.Center,
        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.width(110.dp))
}

/** The round voice button in frosted glass; red with a pulse while recording. */
@Composable
fun MicButton(size: Dp, voice: Voice, onClick: () -> Unit) {
    val recording = voice is Voice.Recording
    Box(Modifier.size(size), contentAlignment = Alignment.Center) {
        if (recording) {
            val t = rememberInfiniteTransition(label = "pulse")
            val p by t.animateFloat(0f, 1f, infiniteRepeatable(tween(1400, easing = LinearEasing), RepeatMode.Restart), label = "p")
            Box(
                Modifier
                    .size(size)
                    .graphicsLayer { scaleX = 1f + .35f * p; scaleY = 1f + .35f * p; alpha = .5f * (1 - p) }
                    .background(Color(0xFFFF3B5C), CircleShape)
            )
        }
        Box(
            Modifier
                .size(size)
                .then(if (recording) Modifier else Modifier.softShadow())
                .clip(CircleShape)
                .background(
                    if (recording) Brush.linearGradient(listOf(Color(0xFFFF6A88), Color(0xFFE8164F)))
                    else GlassBrush
                )
                .clickable(onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            if (recording) {
                Box(Modifier.size(size * .26f).background(Color.White, RoundedCornerShape(size * .06f)))
            } else {
                Icon(Lucide.Mic, contentDescription = "Parla", modifier = Modifier.size(size * .42f), tint = Color.White)
            }
        }
        if (voice is Voice.Working) {
            CircularProgressIndicator(
                modifier = Modifier.size(size + 6.dp), indicatorColor = Color.White,
                trackColor = Color.Transparent, strokeWidth = 2.5.dp,
            )
        }
    }
}
