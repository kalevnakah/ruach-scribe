package com.ruach.scribe

import android.accessibilityservice.AccessibilityService
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class RuachAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // No passive scraping needed; only used on-demand when pasting dictation
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        if (instance === this) {
            instance = null
        }
        super.onDestroy()
    }

    /**
     * Injects [text] directly into the currently focused editable field in any app,
     * falling back to clipboard paste action if direct text insertion is unsupported.
     */
    fun injectTextIntoFocusedField(text: String): Boolean {
        if (text.isBlank()) return false

        val root = rootInActiveWindow
        val focused = root?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: findEditableNode(root)

        if (focused != null) {
            // Try standard paste action first (preserves cursor offset & existing text in editors)
            if (focused.performAction(AccessibilityNodeInfo.ACTION_PASTE)) {
                return true
            }
            // Fallback: append/set text via ACTION_SET_TEXT
            val existing = focused.text?.toString() ?: ""
            val separator = if (existing.isNotEmpty() && !existing.endsWith(" ")) " " else ""
            val combined = existing + separator + text
            val args = Bundle().apply {
                putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    combined
                )
            }
            if (focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                return true
            }
        }
        return false
    }

    private fun findEditableNode(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.isEditable && node.isFocused) return node
        for (i in 0 until node.childCount) {
            val found = findEditableNode(node.getChild(i))
            if (found != null) return found
        }
        return null
    }

    companion object {
        @Volatile
        var instance: RuachAccessibilityService? = null
            private set

        fun copyAndAutoPaste(context: Context, text: String): Boolean {
            if (text.isBlank()) return false
            val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("Ruach Scribe Dictation", text))
            return instance?.injectTextIntoFocusedField(text) ?: false
        }
    }
}
