package it.maipal.watch

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** The app's line icons (Lucide, like the web app), drawn from their SVG paths. */
object Lucide {
    private fun icon(name: String, vararg paths: String, stroke: Float = 1.8f): ImageVector {
        val b = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f)
        for (d in paths) {
            b.addPath(
                pathData = addPathNodes(d), fill = null, stroke = SolidColor(Color.White),
                strokeLineWidth = stroke, strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
            )
        }
        return b.build()
    }

    val Mic = icon("mic", "M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0Z", "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v3", stroke = 1.6f)
    val Chat = icon("chat", "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z")
    val SquareCheck = icon("square-check", "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "m9 12 2 2 4-4")
    val ListChecks = icon("list-checks", "m3 17 2 2 4-4", "m3 7 2 2 4-4", "M13 6h8", "M13 12h8", "M13 18h8")
    val List = icon("list", "M3 12h.01", "M3 18h.01", "M3 6h.01", "M8 12h13", "M8 18h13", "M8 6h13")
    val Search = icon("search", "M19 11a8 8 0 1 1-16 0a8 8 0 1 1 16 0z", "m21 21-4.3-4.3")
    val CloudUpload = icon("cloud-upload", "M12 13v8", "M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242", "m8 17 4-4 4 4")
    val Book = icon("book-open", "M12 7v14", "M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z")
    val Repeat = icon("repeat", "m17 2 4 4-4 4", "M3 11v-1a4 4 0 0 1 4-4h14", "m7 22-4-4 4-4", "M21 13v1a4 4 0 0 1-4 4H3")
    val X = icon("x", "M18 6 6 18", "m6 6 12 12", stroke = 2f)
    val Check = icon("check", "M20 6 9 17l-5-5", stroke = 2.4f)
    val Refresh = icon("refresh", "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", "M8 16H3v5")
    val Phone = icon("phone", "M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z", "M12 18h.01")
}

data class Agent(val id: String, val name: String, val icon: ImageVector)

/** The chat's agents, in the order of the lower half-ring (left to right). */
val AGENTS = listOf(
    Agent("info_request", "Cerca", Lucide.Search),
    Agent("info_upload", "Salva", Lucide.CloudUpload),
    Agent("task_todo", "Task", Lucide.SquareCheck),
    Agent("journal", "Diario", Lucide.Book),
    Agent("scheduled_action", "Azioni", Lucide.Repeat),
)

fun agentOf(id: String) = AGENTS.firstOrNull { it.id == id } ?: AGENTS.first()
