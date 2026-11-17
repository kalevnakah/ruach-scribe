package com.ruach.scribe

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sqrt

class AudioRecorder(
    private val sampleRate: Int = 16000,
    private val onAmplitude: ((Float) -> Unit)? = null
) {
    private val isRecordingAtom = AtomicBoolean(false)
    val isRecording: Boolean get() = isRecordingAtom.get()

    private var audioRecord: AudioRecord? = null
    private var recordingThread: Thread? = null
    private val pcmSamples = ArrayList<Short>(sampleRate * 15)
    private val samplesLock = Any()

    @SuppressLint("MissingPermission")
    fun start() {
        if (isRecordingAtom.getAndSet(true)) return

        synchronized(samplesLock) {
            pcmSamples.clear()
        }

        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        ).coerceAtLeast(2048)

        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minBuf * 2
        )

        if (record.state != AudioRecord.STATE_INITIALIZED) {
            isRecordingAtom.set(false)
            throw IllegalStateException("Microphone initialization failed. Please check Microphone permission.")
        }

        audioRecord = record
        record.startRecording()

        recordingThread = Thread {
            val buffer = ShortArray(1024)
            while (isRecordingAtom.get()) {
                val readCount = record.read(buffer, 0, buffer.size)
                if (readCount > 0) {
                    var sumSq = 0.0
                    synchronized(samplesLock) {
                        for (i in 0 until readCount) {
                            val s = buffer[i]
                            pcmSamples.add(s)
                            sumSq += (s.toDouble() * s.toDouble())
                        }
                    }
                    val rms = sqrt(sumSq / readCount) / 32768.0
                    val level = min(1.0f, (rms * 8.0).toFloat())
                    onAmplitude?.invoke(level)
                }
            }
        }.apply {
            isDaemon = true
            start()
        }
    }

    fun stopBytes(): ByteArray? {
        if (!isRecordingAtom.getAndSet(false)) return null

        val record = audioRecord
        audioRecord = null
        Thread {
            try {
                record?.stop()
                record?.release()
            } catch (_: Exception) {
            }
        }.start()

        try {
            recordingThread?.join(120)
        } catch (_: Exception) {
        }
        recordingThread = null

        val rawSamples: ShortArray
        synchronized(samplesLock) {
            if (pcmSamples.size < (sampleRate * 0.22).toInt()) {
                pcmSamples.clear()
                return null
            }
            rawSamples = pcmSamples.toShortArray()
            pcmSamples.clear()
        }

        val trimmed = trimSilence(rawSamples)
        if (trimmed.size < (sampleRate * 0.15).toInt()) {
            return null
        }

        // Guard against faint background hum / tap clicks that barely cross the peak threshold
        var sumSq = 0.0
        for (s in trimmed) {
            val d = s.toDouble()
            sumSq += d * d
        }
        val rms = kotlin.math.sqrt(sumSq / trimmed.size)
        if (rms < 120.0) {
            return null
        }

        return encodeWavBytes(trimmed, sampleRate)
    }

    private fun trimSilence(samples: ShortArray): ShortArray {
        val threshold = 390
        var firstIdx = -1
        var lastIdx = -1

        for (i in samples.indices) {
            if (abs(samples[i].toInt()) > threshold) {
                firstIdx = i
                break
            }
        }
        if (firstIdx == -1) return ShortArray(0)

        for (i in samples.indices.reversed()) {
            if (abs(samples[i].toInt()) > threshold) {
                lastIdx = i
                break
            }
        }

        val pad = (sampleRate * 0.12).toInt()
        val start = (firstIdx - pad).coerceAtLeast(0)
        val end = (lastIdx + pad).coerceAtMost(samples.size - 1)
        return samples.copyOfRange(start, end + 1)
    }

    private fun encodeWavBytes(samples: ShortArray, sampleRate: Int): ByteArray {
        val dataSize = samples.size * 2
        val totalSize = 36 + dataSize
        val out = ByteArrayOutputStream(44 + dataSize)
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)

        header.put("RIFF".toByteArray(Charsets.US_ASCII))
        header.putInt(totalSize)
        header.put("WAVE".toByteArray(Charsets.US_ASCII))
        header.put("fmt ".toByteArray(Charsets.US_ASCII))
        header.putInt(16) // PCM chunk size
        header.putShort(1) // AudioFormat = 1 (PCM)
        header.putShort(1) // Channels = 1 (Mono)
        header.putInt(sampleRate)
        header.putInt(sampleRate * 2) // ByteRate
        header.putShort(2) // BlockAlign
        header.putShort(16) // BitsPerSample
        header.put("data".toByteArray(Charsets.US_ASCII))
        header.putInt(dataSize)

        out.write(header.array())

        val pcmBuf = ByteBuffer.allocate(dataSize).order(ByteOrder.LITTLE_ENDIAN)
        for (s in samples) {
            pcmBuf.putShort(s)
        }
        out.write(pcmBuf.array())
        return out.toByteArray()
    }
}
