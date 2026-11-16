# Ruach Scribe

**Ruach Scribe** is an ethereal, low-latency voice dictation and AI transcription utility for Debian/Ubuntu Linux (Wayland & X11). Hold your global shortcut key to summon a calm, pulsing cyan/white breath aura, speak naturally (even changing your mind mid-sentence with *"scratch that"*), and release to let **Google Gemini** strip filler words and auto-paste polished text directly into your focused window.

---

## Features

* **Hold-to-Talk & Double-Tap to Lock:**
  * **Hold-to-Talk:** Press and hold your shortcut (default: `Ctrl + Alt` or `Right Ctrl`) while speaking; release to transcribe and auto-paste immediately.
  * **Double-Tap to Lock:** Double-tap your shortcut quickly to lock hands-free recording; double-tap again to finish.
* **Intelligent Speech Editing:**
  * Automatically strips filler words (*"um"*, *"uh"*, *"ah"*, *"like"*, *"you know"*), stutters, and false starts.
  * Understands spoken self-corrections (*"scratch that"*, *"no wait"*, *"actually"*) and outputs only your final intended sentence.
* **Transcription History (Before & After Editing):**
  * View both the **Raw Verbatim Speech (Before Editing)** and **Cleaned Output (After Editing)** side-by-side in the **Transcription History** tab with one-click copy buttons.
* **Multi-Monitor & 8 Anchor Positions:**
  * Choose which display monitor the floating aura appears on and anchor it to `Bottom Center`, `Bottom Right`, `Bottom Left`, `Left Center`, `Right Center`, `Top Center`, `Top Right`, or `Top Left`.
* **Privacy & Security by Design:**
  * Your API key (`config.json`), saved transcriptions (`history.json`), and logs are stored outside the repository in `~/.config/ruach-scribe/` with `0600` (owner-only) permissions so they can never be committed to Git.

---

## Quick Install & Run (Debian / Ubuntu / Zorin OS)

```bash
./install.sh
./run.sh
```

On first launch, click **Enable Wayland Global Hotkey & Paste** in the Settings window (if on Wayland) and paste your Google Gemini API key.
