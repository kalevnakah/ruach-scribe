# Ruach Scribe for Android (`android/`)

Native Kotlin & Jetpack Compose edition of **Ruach Scribe** for Android phones (Android 8.0+ / API 26+).

## Features on Android
* **Floating Ethereal Ruach Bubble (`RuachOverlayService`):**
  * Floats over any app (Messages, WhatsApp, Gmail, Chrome, Notes, Slack, etc.) with the same 60 FPS pulsing cyan/mint/white breath aura and swirling processing state.
  * **Hold-to-Talk:** Press and hold the floating Ruach bubble while speaking; lift your finger to transcribe and auto-paste into the active text box.
  * **Double-Tap to Lock:** Double-tap the floating bubble quickly to lock hands-free recording; double-tap again to finish.
  * **Draggable + 8 Screen Anchor Positions:** Anchor to `Bottom Center`, `Bottom Right`, `Bottom Left`, `Left Center`, `Right Center`, `Top Center`, `Top Right`, or `Top Left`, or drag it with your finger.
* **Auto-Paste into Any Focused Text Box (`RuachAccessibilityService`):**
  * Automatically injects the cleaned transcription directly into whatever text field is focused on your screen (and copies to your clipboard).
* **Before & After Transcription History Tab:**
  * Inspect both **Before Editing (Raw Verbatim Speech)** and **After Editing (Cleaned Output Pasted)** with one-tap copy buttons.
* **Autostart on Phone Boot (`BootCompletedReceiver`):**
  * Automatically starts the floating Ruach bubble in the background when your phone turns on.

---

## How to Build / Install the APK

### Option 1: Automatic GitHub Cloud Build (Zero Local Setup)
Every push to `main` automatically triggers the [`.github/workflows/build-android-apk.yml`](../.github/workflows/build-android-apk.yml) workflow on GitHub:
1. Open your repository on GitHub and click the **Actions** tab.
2. Click the latest **Build Android APK** run and download **`RuachScribe-Android-APK`** (`app-debug.apk`) onto your Android phone.

### Option 2: Android Studio
1. Open **Android Studio** and select **Open** -> choose the `android/` folder.
2. Plug in your Android phone (with USB Debugging enabled) and click **Run (`▶`)**.
