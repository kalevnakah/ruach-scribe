package com.ruach.scribe

import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class TranscriptionResult(
    val rawText: String,
    val cleanedText: String
)

object GeminiTranscriber {
    private val FALLBACK_MODELS = listOf(
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-pro-latest"
    )

    fun transcribeBytes(
        wavBytes: ByteArray,
        apiKey: String,
        systemPrompt: String,
        modelName: String = "gemini-flash-lite-latest"
    ): TranscriptionResult {
        val cleanKey = apiKey.trim()
        if (cleanKey.isEmpty()) {
            throw IllegalArgumentException("Google Gemini API Key is missing. Please add it in Settings.")
        }
        if (wavBytes.size < 100) {
            return TranscriptionResult("", "")
        }

        val base64Audio = Base64.encodeToString(wavBytes, Base64.NO_WRAP)
        val candidates = (listOf(modelName) + FALLBACK_MODELS).distinct()

        var lastException: Exception? = null
        for (candidate in candidates) {
            try {
                return callModelRest(candidate, cleanKey, systemPrompt, base64Audio)
            } catch (e: Exception) {
                lastException = e
                val msg = (e.message ?: "").lowercase()
                if (msg.contains("404") || msg.contains("not found") || msg.contains("no longer available")) {
                    continue
                }
                throw e
            }
        }
        throw lastException ?: RuntimeException("Transcription failed.")
    }

    private fun callModelRest(
        modelName: String,
        apiKey: String,
        systemPrompt: String,
        base64Audio: String
    ): TranscriptionResult {
        val endpoint =
            "https://generativelanguage.googleapis.com/v1beta/models/$modelName:generateContent?key=$apiKey"
        val userInstruction =
            "$systemPrompt\n\n" +
                "Process the attached audio and return a JSON object with exactly two string keys:\n" +
                "1. \"raw\": The exact verbatim transcription of everything spoken in the audio, " +
                "including all filler words ('um', 'uh'), stutters, false starts, and self-correction phrases ('scratch that').\n" +
                "2. \"cleaned\": The final edited text following the editing rules above (all fillers removed, " +
                "all 'scratch that' / 'no wait' self-corrections applied so retracted mistakes are deleted, and proper punctuation).\n" +
                "If the audio is completely silent or has no speech, return {\"raw\": \"\", \"cleaned\": \"\"}."

        val payload = JSONObject().apply {
            put(
                "systemInstruction",
                JSONObject().put(
                    "parts",
                    JSONArray().put(JSONObject().put("text", systemPrompt))
                )
            )
            put(
                "contents",
                JSONArray().put(
                    JSONObject().put(
                        "parts",
                        JSONArray()
                            .put(
                                JSONObject().put(
                                    "inlineData",
                                    JSONObject()
                                        .put("mimeType", "audio/wav")
                                        .put("data", base64Audio)
                                )
                            )
                            .put(JSONObject().put("text", userInstruction))
                    )
                )
            )
            put(
                "generationConfig",
                JSONObject()
                    .put("temperature", 0.0)
                    .put("candidateCount", 1)
                    .put("responseMimeType", "application/json")
            )
        }

        val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10000
            readTimeout = 15000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }

        conn.outputStream.use { os ->
            os.write(payload.toString().toByteArray(Charsets.UTF_8))
        }

        val status = conn.responseCode
        val body = if (status in 200..299) {
            conn.inputStream.bufferedReader().use { it.readText() }
        } else {
            val errBody = conn.errorStream?.bufferedReader()?.use { it.readText() } ?: "HTTP $status"
            throw RuntimeException("Gemini API Error ($status): $errBody")
        }

        val root = JSONObject(body)
        val candidatesArr = root.optJSONArray("candidates") ?: return TranscriptionResult("", "")
        if (candidatesArr.length() == 0) return TranscriptionResult("", "")

        val contentObj = candidatesArr.getJSONObject(0).optJSONObject("content")
            ?: return TranscriptionResult("", "")
        val partsArr = contentObj.optJSONArray("parts") ?: return TranscriptionResult("", "")
        val sb = StringBuilder()
        for (i in 0 until partsArr.length()) {
            sb.append(partsArr.getJSONObject(i).optString("text", ""))
        }

        return parseRawAndCleaned(sb.toString())
    }

    private fun parseRawAndCleaned(responseText: String): TranscriptionResult {
        val trimmed = responseText.trim()
            .removePrefix("```json")
            .removePrefix("```")
            .removeSuffix("```")
            .trim()
        if (trimmed.isEmpty()) return TranscriptionResult("", "")

        return try {
            val obj = JSONObject(trimmed)
            TranscriptionResult(
                rawText = obj.optString("raw", "").trim(),
                cleanedText = obj.optString("cleaned", "").trim()
            )
        } catch (_: Exception) {
            TranscriptionResult(trimmed, trimmed)
        }
    }
}
