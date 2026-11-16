import datetime
import glob
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Suppress noisy Qt AT-SPI bridge warnings in terminal
os.environ.setdefault("QT_LOGGING_RULES", "qt.accessibility.atspi*=false")
os.environ.setdefault("NO_AT_BRIDGE", "1")

# Use XWayland (xcb) when DISPLAY is available so multi-monitor window coordinates
# (Monitor 1 vs Monitor 2) are honored rather than forced onto the Wayland primary display.
if os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from audio import AudioRecorder
from config import ConfigManager
from gemini_client import GeminiTranscriber
from gui import RuachOverlay, SettingsWindow, create_ruach_icon
from history import HistoryManager
from hotkey_manager import HotkeyGestureController, HotkeyManager
from injector import TextInjector

def _get_log_file() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    user_dir = base_dir / "ruach-scribe"
    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "ruach_scribe.log"
    except OSError:
        fallback = Path(__file__).resolve().parent / ".private_local" / "ruach_scribe.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback


LOG_FILE = _get_log_file()


def log_message(msg: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class AppSignals(QObject):
    gesture_start = pyqtSignal()
    gesture_lock = pyqtSignal()
    gesture_stop_and_transcribe = pyqtSignal()
    gesture_cancel = pyqtSignal()
    audio_amplitude = pyqtSignal(float)
    transcription_ready = pyqtSignal(str, str, float, str)
    transcription_error = pyqtSignal(str)


class RuachScribeApp:
    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.setApplicationName("Ruach Scribe")

        self.config = ConfigManager()
        self.history = HistoryManager()
        self.signals = AppSignals()
        self.last_error: str = ""

        self.overlay = RuachOverlay(self.config)
        self.injector = TextInjector()
        self.recorder = AudioRecorder(
            on_amplitude=lambda level: self.signals.audio_amplitude.emit(level)
        )

        self.gesture_controller = HotkeyGestureController(
            on_start=lambda: self.signals.gesture_start.emit(),
            on_lock=lambda: self.signals.gesture_lock.emit(),
            on_stop_and_transcribe=lambda: self.signals.gesture_stop_and_transcribe.emit(),
            on_cancel=lambda: self.signals.gesture_cancel.emit(),
        )
        self._hotkey_manager: Optional[HotkeyManager] = None
        self._is_processing = False
        self._settings_dialog: Optional[SettingsWindow] = None

        # Connect signals to main GUI thread slots
        self.signals.gesture_start.connect(self._on_gesture_start)
        self.signals.gesture_lock.connect(self._on_gesture_lock)
        self.signals.gesture_stop_and_transcribe.connect(
            self._on_gesture_stop_and_transcribe
        )
        self.signals.gesture_cancel.connect(self._on_gesture_cancel)
        self.signals.audio_amplitude.connect(self.overlay.set_audio_level)
        self.signals.transcription_ready.connect(self._on_transcription_ready)
        self.signals.transcription_error.connect(self._on_transcription_error)

        self._setup_tray()
        self.register_hotkey()

        # If no API key is configured on startup, notify and open settings
        if not self.config.get("api_key", "").strip():
            QTimer.singleShot(
                400,
                lambda: self._prompt_missing_api_key(
                    "Welcome to Ruach Scribe! Please enter your Google Gemini API key to begin."
                ),
            )

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(create_ruach_icon(), self.qt_app)
        self.tray.setToolTip("Ruach Scribe — Ethereal Voice Dictation")

        menu = QMenu()
        self.toggle_action = QAction("Start / Stop Dictation", menu)
        self.toggle_action.triggered.connect(self.manual_toggle_recording)
        menu.addAction(self.toggle_action)

        history_action = QAction("Transcription History...", menu)
        history_action.triggered.connect(lambda: self.open_settings(initial_tab=1))
        menu.addAction(history_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(lambda: self.open_settings(initial_tab=0))
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit Ruach Scribe", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings(initial_tab=0)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        log_message(f"{title}: {message}")
        if self.tray.isVisible() and self.tray.supportsMessages():
            icon = (
                QSystemTrayIcon.MessageIcon.Warning
                if error
                else QSystemTrayIcon.MessageIcon.Information
            )
            self.tray.showMessage(title, message, icon, 6000)
        else:
            try:
                subprocess.Popen(["notify-send", "-t", "6000", title, message])
            except Exception:
                pass

    def register_hotkey(self) -> None:
        if self._hotkey_manager is not None:
            self._hotkey_manager.stop()
            self._hotkey_manager = None

        self.gesture_controller.reset()
        hotkey_str = self.config.get("hotkey", "<ctrl>+<alt>").strip()
        self._hotkey_manager = HotkeyManager(hotkey_str, self.gesture_controller)
        backend = self._hotkey_manager.start()
        log_message(f"Listening for shortcut '{hotkey_str}' via {backend}")

    def _prompt_missing_api_key(self, message: str) -> None:
        self.last_error = message
        self.notify("Ruach Scribe — API Key Needed", message, error=True)
        self.open_settings(initial_tab=0)

    def open_settings(self, initial_tab: int = 0) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.set_last_error(self.last_error)
            self._settings_dialog.refresh_history()
            self._settings_dialog.tabs.setCurrentIndex(initial_tab)
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return

        self._settings_dialog = SettingsWindow(
            self.config,
            self.history,
            on_settings_saved=self.register_hotkey,
            last_error=self.last_error,
            initial_tab=initial_tab,
        )
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def manual_toggle_recording(self) -> None:
        """Triggered from the System Tray menu."""
        if self._is_processing:
            return
        if not self.recorder.is_recording:
            self.gesture_controller.mode = HotkeyGestureController.MODE_LOCKED
            self._on_gesture_start(locked=True)
        else:
            self.gesture_controller.reset()
            self._on_gesture_stop_and_transcribe()

    def _on_gesture_start(self, locked: bool = False) -> None:
        if self._is_processing or self.recorder.is_recording:
            return

        api_key = self.config.get("api_key", "").strip()
        if not api_key:
            self.gesture_controller.reset()
            self._prompt_missing_api_key(
                "Missing Google Gemini API Key. Please add your key in Settings."
            )
            return

        device_index = self.config.get("device_index", None)
        try:
            self.recorder.start(device_index=device_index)
            self.overlay.show_listening(locked=locked)
            threading.Thread(
                target=GeminiTranscriber.prewarm,
                args=(
                    api_key,
                    self.config.get("model_name", "gemini-flash-lite-latest"),
                    self.config.get("system_prompt", ""),
                ),
                daemon=True,
            ).start()
        except Exception as e:
            self.gesture_controller.reset()
            self.overlay.hide_overlay()
            self.last_error = f"Microphone Error: {e}"
            self.notify("Microphone Error", str(e), error=True)
            self.open_settings(initial_tab=0)

    def _on_gesture_lock(self) -> None:
        if self.recorder.is_recording:
            self.overlay.set_locked_mode()
        elif not self._is_processing:
            self._on_gesture_start(locked=True)

    def _on_gesture_cancel(self) -> None:
        """Discards a brief accidental single-tap without sending to Gemini."""
        if self.recorder.is_recording:
            try:
                self.recorder.stop_bytes()
            except Exception:
                pass
        self.overlay.hide_overlay()

    def _on_gesture_stop_and_transcribe(self) -> None:
        if self._is_processing:
            return

        try:
            wav_bytes = self.recorder.stop_bytes()
        except Exception as e:
            self.overlay.hide_overlay()
            self.last_error = f"Audio Capture Error: {e}"
            self.notify("Audio Capture Error", str(e), error=True)
            self.open_settings(initial_tab=0)
            return

        if not wav_bytes:
            self.overlay.hide_overlay()
            return

        self._is_processing = True
        self.overlay.show_processing()

        api_key = self.config.get("api_key", "")
        model_name = self.config.get("model_name", "gemini-flash-lite-latest")
        system_prompt = self.config.get("system_prompt", "")

        worker = threading.Thread(
            target=self._transcription_worker,
            args=(wav_bytes, api_key, system_prompt, model_name),
            daemon=True,
        )
        worker.start()

    def _transcription_worker(
        self, wav_bytes: bytes, api_key: str, system_prompt: str, model_name: str
    ) -> None:
        t0 = time.monotonic()
        try:
            raw_text, cleaned_text = GeminiTranscriber.transcribe_bytes(
                wav_bytes=wav_bytes,
                api_key=api_key,
                system_prompt=system_prompt,
                model_name=model_name,
            )
            elapsed = time.monotonic() - t0
            log_message(f"Gemini API latency: {elapsed:.2f}s (model={model_name})")
            self.signals.transcription_ready.emit(
                raw_text, cleaned_text, elapsed, model_name
            )
        except Exception as e:
            self.signals.transcription_error.emit(str(e))

    def _on_transcription_ready(
        self, raw_text: str, cleaned_text: str, elapsed: float, model_name: str
    ) -> None:
        self._is_processing = False
        self.last_error = ""
        self.overlay.hide_overlay()

        if not cleaned_text and not raw_text:
            log_message("Transcription returned empty text.")
            return

        # Save both raw (Before Editing) and cleaned (After Editing) to history.json
        self.history.add_entry(
            raw_text=raw_text or cleaned_text,
            cleaned_text=cleaned_text,
            latency_sec=elapsed,
            model_name=model_name,
        )
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.refresh_history()

        log_message(
            f"Transcription complete ({len(raw_text)} raw chars -> {len(cleaned_text)} cleaned chars)"
        )
        if not cleaned_text:
            return

        paste_shortcut = self.config.get("paste_shortcut", "ctrl+v")
        QTimer.singleShot(
            15,
            lambda: self.injector.inject_text(
                cleaned_text, paste_shortcut=paste_shortcut
            ),
        )

    def _on_transcription_error(self, error_msg: str) -> None:
        self._is_processing = False
        self.overlay.hide_overlay()
        self.last_error = error_msg
        self.notify("Ruach Scribe — Transcription Error", error_msg, error=True)
        self.open_settings(initial_tab=0)

    def quit(self) -> None:
        if self._hotkey_manager is not None:
            self._hotkey_manager.stop()
        if self.recorder.is_recording:
            try:
                self.recorder.stop_bytes()
            except Exception:
                pass
        self.overlay.hide_overlay()
        self.tray.hide()
        self.qt_app.quit()


def main() -> None:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    _ruach = RuachScribeApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
