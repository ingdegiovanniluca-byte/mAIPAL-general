package it.maipal.watch

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/** Records a voice message to an .m4a file (AAC), sent to the server to be transcribed. */
class Recorder(private val ctx: Context) {
    private var rec: MediaRecorder? = null
    private val file = File(ctx.cacheDir, "voce.m4a")

    fun start() {
        cancel()
        val r = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(ctx) else @Suppress("DEPRECATION") MediaRecorder()
        try {
            r.setAudioSource(MediaRecorder.AudioSource.MIC)
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            r.setAudioChannels(1)
            r.setAudioSamplingRate(16000)
            r.setAudioEncodingBitRate(48000)
            r.setOutputFile(file.absolutePath)
            r.prepare()
            r.start()
        } catch (e: Exception) {
            r.release()
            throw e
        }
        rec = r
    }

    /** Stops and returns the recording, or null if nothing usable was recorded. */
    fun stop(): File? {
        val r = rec ?: return null
        rec = null
        return try {
            r.stop()
            file
        } catch (e: RuntimeException) {   // stopped right after starting: no audio at all
            null
        } finally {
            r.release()
        }
    }

    fun cancel() {
        rec?.let { r ->
            rec = null
            try { r.stop() } catch (_: RuntimeException) {}
            r.release()
        }
        file.delete()
    }
}
