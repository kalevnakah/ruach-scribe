# Ruach Scribe

<p align="center">
  <img src="linux/assets/ruach-scribe-256.png" alt="Ruach Scribe Logo" width="140" />
</p>

**Ruach Scribe** is an ethereal, low-latency voice dictation and AI transcription utility powered by **Google Gemini**—available for both **Linux Desktop (`linux/`)** and **Android Phones (`android/`)**.

---

## Repository Structure

* **[`linux/`](linux/)** — **Linux Desktop App (Debian / Ubuntu / Zorin OS, Wayland & X11)**
  * Python + PyQt6 + `evdev`/`uinput` global hotkeys and auto-paste.
  * Hold-to-Talk & Double-Tap to Lock global shortcut (`Ctrl + Alt`, `Right Ctrl`, etc.).
  * Multi-monitor support with 8 anchor positions, login autostart, and Before & After transcription history.
* **[`android/`](android/)** — **Android Phone App (Kotlin + Jetpack Compose)**
  * Floating Ruach Aura Bubble (`SYSTEM_ALERT_WINDOW`) with **Tap-to-Dictate** and **Check Mark** to finish.
  * Automatic text injection into any focused Android input box via `RuachAccessibilityService`.
  * Same dark ethereal UI, custom System Prompt, 8 anchor positions, Boot Autostart, and Before & After Transcription History tab.
  * Includes a GitHub Actions workflow ([`.github/workflows/build-android-apk.yml`](.github/workflows/build-android-apk.yml)) that automatically builds an installable `.apk` in the cloud on every push.

---

## Quick Start (Linux Desktop)

```bash
./linux/install.sh
./linux/run.sh
```

## Quick Start (Android Phone)
See [`android/README.md`](android/README.md) to download the pre-built APK from your GitHub **Actions** tab or build locally in Android Studio.
