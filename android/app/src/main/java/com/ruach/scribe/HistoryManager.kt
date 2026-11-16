package com.ruach.scribe

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class HistoryEntry(
    val timestamp: String,
    val rawText: String,
    val cleanedText: String,
    val latencySec: Double,
    val modelName: String
)

object HistoryManager {
    private const val MAX_ITEMS = 200
    private const val FILE_NAME = "history.json"

    private val _entries = MutableStateFlow<List<HistoryEntry>>(emptyList())
    val entries: StateFlow<List<HistoryEntry>> = _entries.asStateFlow()

    private val _lastError = MutableStateFlow("")
    val lastError: StateFlow<String> = _lastError.asStateFlow()

    fun setLastError(msg: String) {
        _lastError.value = msg
    }

    @Synchronized
    fun load(context: Context): List<HistoryEntry> {
        val file = File(context.applicationContext.filesDir, FILE_NAME)
        if (!file.exists()) {
            _entries.value = emptyList()
            return emptyList()
        }
        return try {
            val arr = JSONArray(file.readText())
            val loaded = mutableListOf<HistoryEntry>()
            for (i in 0 until arr.length()) {
                val obj = arr.getJSONObject(i)
                loaded.add(
                    HistoryEntry(
                        timestamp = obj.optString("timestamp", ""),
                        rawText = obj.optString("raw_text", ""),
                        cleanedText = obj.optString("cleaned_text", ""),
                        latencySec = obj.optDouble("latency_sec", 0.0),
                        modelName = obj.optString("model_name", "")
                    )
                )
            }
            _entries.value = loaded
            loaded
        } catch (e: Exception) {
            emptyList()
        }
    }

    @Synchronized
    fun addEntry(
        context: Context,
        rawText: String,
        cleanedText: String,
        latencySec: Double,
        modelName: String
    ) {
        if (_entries.value.isEmpty()) {
            load(context)
        }
        val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
        val entry = HistoryEntry(
            timestamp = sdf.format(Date()),
            rawText = rawText.trim(),
            cleanedText = cleanedText.trim(),
            latencySec = Math.round(latencySec * 100.0) / 100.0,
            modelName = modelName
        )
        val updated = (listOf(entry) + _entries.value).take(MAX_ITEMS)
        _entries.value = updated
        save(context, updated)
    }

    @Synchronized
    fun clear(context: Context) {
        _entries.value = emptyList()
        save(context, emptyList())
    }

    private fun save(context: Context, list: List<HistoryEntry>) {
        try {
            val arr = JSONArray()
            for (item in list) {
                val obj = JSONObject().apply {
                    put("timestamp", item.timestamp)
                    put("raw_text", item.rawText)
                    put("cleaned_text", item.cleanedText)
                    put("latency_sec", item.latencySec)
                    put("model_name", item.modelName)
                }
                arr.put(obj)
            }
            val file = File(context.applicationContext.filesDir, FILE_NAME)
            file.writeText(arr.toString(2))
        } catch (_: Exception) {
        }
    }
}
