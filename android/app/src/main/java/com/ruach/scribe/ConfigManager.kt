package com.ruach.scribe

import android.content.Context
import android.content.SharedPreferences

class ConfigManager(context: Context) {
    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences("ruach_scribe_prefs", Context.MODE_PRIVATE)

    var apiKey: String
        get() = prefs.getString("api_key", "") ?: ""
        set(value) = prefs.edit().putString("api_key", value.trim()).apply()

    var modelName: String
        get() = prefs.getString("model_name", "gemini-flash-lite-latest") ?: "gemini-flash-lite-latest"
        set(value) = prefs.edit().putString("model_name", value).apply()

    var overlayPosition: String
        get() = prefs.getString("overlay_position", "bottom_right") ?: "bottom_right"
        set(value) = prefs.edit().putString("overlay_position", value).apply()

    var startOnBoot: Boolean
        get() = prefs.getBoolean("start_on_boot", true)
        set(value) = prefs.edit().putBoolean("start_on_boot", value).apply()

    var systemPrompt: String
        get() = prefs.getString("system_prompt", DEFAULT_PROMPT) ?: DEFAULT_PROMPT
        set(value) = prefs.edit().putString(
            "system_prompt",
            value.ifBlank { DEFAULT_PROMPT }
        ).apply()

    companion object {
        const val DEFAULT_PROMPT =
            "You are an intelligent voice dictation editor (like Wispr Flow). " +
                "Transform the user's spoken audio into clean, polished written text by following these strict rules:\n" +
                "1. REMOVE ALL FILLERS & STUTTERS: Completely strip filler words (um, uh, ah, er, hmm, like, you know), " +
                "stutters, and accidental word repetitions.\n" +
                "2. APPLY SPOKEN SELF-CORRECTIONS: If the speaker corrects themselves or backtracks using phrases like " +
                "'scratch that', 'delete that', 'no wait', 'actually', or 'I mean', DO NOT transcribe the mistake or the " +
                "correction phrase—output ONLY the final corrected thought. " +
                "(Example: 'Um, send the file to Bob, scratch that, send it to Alice at 3 PM' -> 'Send the file to Alice at 3:00 PM.')\n" +
                "3. PUNCTUATION & OUTPUT: Apply natural punctuation and capitalization. " +
                "Output ONLY the final cleaned text without any quotes, markdown, or introductory commentary."

        val POSITION_OPTIONS = listOf(
            "Bottom Center" to "bottom_center",
            "Bottom Right" to "bottom_right",
            "Bottom Left" to "bottom_left",
            "Left Center" to "left_center",
            "Right Center" to "right_center",
            "Top Center" to "top_center",
            "Top Right" to "top_right",
            "Top Left" to "top_left"
        )

        val MODEL_OPTIONS = listOf(
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-pro-latest"
        )
    }
}
