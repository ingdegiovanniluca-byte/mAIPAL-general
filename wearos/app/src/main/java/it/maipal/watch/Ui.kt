package it.maipal.watch

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Typography
import kotlin.math.min

val Poppins = FontFamily(
    Font(R.font.poppins_light, FontWeight.Light),
    Font(R.font.poppins_regular, FontWeight.Normal),
    Font(R.font.poppins_medium, FontWeight.Medium),
    Font(R.font.poppins_semibold, FontWeight.SemiBold),
    Font(R.font.poppins_bold, FontWeight.Bold),
)

val Wine = Color(0xFF8E2F6B)
val LateRed = Color(0xFFFF5A64)

@Composable
fun MaipalTheme(content: @Composable () -> Unit) {
    MaterialTheme(typography = Typography(defaultFontFamily = Poppins), content = content)
}

/** The frosted glass of the phone chat's voice circle: a whitish veil, no rim. */
val GlassBrush = Brush.verticalGradient(listOf(Color.White.copy(alpha = .20f), Color.White.copy(alpha = .10f)))

private class Blob(val x: Float, val y: Float, val r: Float, val color: Long, val alpha: Float)

// positions on the 450x450 mockup of the watch
private val UNDER = listOf(
    Blob(280f, 170f, 130f, 0xFF8E2F6B, .9f),
    Blob(60f, 390f, 140f, 0xFFF2701E, .95f),
    Blob(125f, 185f, 90f, 0xFFC2457F, .8f),
    Blob(50f, 40f, 105f, 0xFFCBDFE4, .9f),
    Blob(370f, 410f, 110f, 0xFFCBDFE4, .9f),
)
private val OVER = listOf(
    Blob(35f, 25f, 100f, 0xFFCBDFE4, .45f),
    Blob(375f, 415f, 105f, 0xFFCBDFE4, .5f),
)

/** "Vinaccia": a pale warm base, very soft colour shapes seen through a wine glass, powder
 *  blue in the top-left and bottom-right corners - the app's background, drawn once. */
@Composable
fun AppBackground(modifier: Modifier = Modifier) {
    Canvas(modifier.fillMaxSize()) {
        val k = min(size.width, size.height) / 450f
        val ox = (size.width - 450f * k) / 2
        val oy = (size.height - 450f * k) / 2
        drawRect(Brush.radialGradient(listOf(Color(0xFFE6E1DC), Color(0xFFD6D0CA), Color(0xFFCFC9C3)),
            center = Offset(size.width / 2, size.height * .4f), radius = size.maxDimension * .8f))
        fun blobs(list: List<Blob>) = list.forEach { b ->
            val c = Color(b.color)
            val center = Offset(ox + b.x * k, oy + b.y * k)
            val radius = b.r * k * 1.45f        // the CSS shapes are blurred by 46px
            drawCircle(
                Brush.radialGradient(
                    0f to c.copy(alpha = b.alpha), .45f to c.copy(alpha = b.alpha * .8f), 1f to c.copy(alpha = 0f),
                    center = center, radius = radius,
                ),
                radius = radius, center = center,
            )
        }
        blobs(UNDER)
        drawRect(Brush.verticalGradient(
            0f to Color(150, 40, 95).copy(alpha = .46f), .55f to Color(120, 28, 80).copy(alpha = .40f),
            1f to Color(150, 50, 90).copy(alpha = .34f),
        ))
        blobs(OVER)
    }
}

/** A whole screen: the background and the content on top. */
@Composable
fun Screen(content: @Composable BoxScope.() -> Unit) {
    Box(Modifier.fillMaxSize()) {
        AppBackground()
        content()
    }
}

/** A soft shadow ring under a round glass button (an elevation shadow would show through the glass). */
fun Modifier.softShadow(): Modifier = drawBehind {
    val r = size.minDimension / 2
    val c = Offset(size.width / 2, size.height / 2 + r * .14f)
    drawCircle(
        Brush.radialGradient(
            0f to Color.Transparent, .62f to Color.Transparent, .78f to Color(60, 10, 40).copy(alpha = .16f),
            1f to Color.Transparent, center = c, radius = r * 1.3f,
        ),
        radius = r * 1.3f, center = c,
    )
}

@Composable
fun GlassCard(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, content: @Composable BoxScope.() -> Unit) {
    Box(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(22.dp))
            .background(GlassBrush)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        content = content,
    )
}

/** A round icon button; `active` gives it the lighter bubble of the selected item. */
@Composable
fun RoundIcon(icon: ImageVector, label: String, size: Dp, active: Boolean = false, glass: Boolean = false,
              bg: Color? = null, tint: Color = Color.White, onClick: () -> Unit) {
    Box(
        Modifier
            .size(size)
            .clip(CircleShape)
            .then(
                when {
                    bg != null -> Modifier.background(bg)
                    active -> Modifier.background(Color.White.copy(alpha = .34f))
                    glass -> Modifier.background(GlassBrush)
                    else -> Modifier
                }
            )
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = label, modifier = Modifier.size(size * .5f),
            tint = if (active || glass || bg != null) tint else tint.copy(alpha = .82f))
    }
}
