import getpass
import math
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QClipboard,
    QColor,
    QConicalGradient,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QScreen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from audio import AudioRecorder
from config import ConfigManager, DEFAULT_PROMPT
from history import HistoryManager
from hotkey_manager import HotkeyManager


HOTKEY_PRESETS = [
    ("Ctrl + Alt (Hold or Double-Tap)", "<ctrl>+<alt>"),
    ("Right Ctrl (Wispr Flow Style)", "ctrl_r"),
    ("Right Alt", "alt_r"),
    ("Ctrl + Super (Windows Key)", "<ctrl>+<cmd>"),
    ("Ctrl + Shift + Space", "<ctrl>+<shift>+<space>"),
    ("F8 Key", "f8"),
    ("F9 Key", "f9"),
]

POSITION_OPTIONS = [
    ("Bottom Center", "bottom_center"),
    ("Bottom Right", "bottom_right"),
    ("Bottom Left", "bottom_left"),
    ("Left Center", "left_center"),
    ("Right Center", "right_center"),
    ("Top Center", "top_center"),
    ("Top Right", "top_right"),
    ("Top Left", "top_left"),
]


ICON_PATH = Path(__file__).resolve().parent / "assets" / "ruach-scribe.png"


def create_ruach_icon(size: int = 64) -> QIcon:
    """Load the Ruach Scribe app icon from assets/ruach-scribe.png (with programmatic fallback)."""
    if ICON_PATH.exists():
        return QIcon(str(ICON_PATH))

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center = QPointF(size / 2, size / 2)
    grad = QRadialGradient(center, size * 0.45)
    grad.setColorAt(0.0, QColor(245, 255, 255, 255))
    grad.setColorAt(0.45, QColor(110, 235, 245, 220))
    grad.setColorAt(0.8, QColor(56, 189, 248, 110))
    grad.setColorAt(1.0, QColor(56, 189, 248, 0))

    painter.setBrush(grad)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(center, size * 0.45, size * 0.45)
    painter.end()

    return QIcon(pixmap)


class RuachOverlay(QWidget):
    """
    Borderless, click-through, focus-preserving overlay that appears at the chosen
    anchor position on the user's selected monitor.
    """

    STATE_IDLE = "idle"
    STATE_LISTENING = "listening"
    STATE_LOCKED = "locked"
    STATE_PROCESSING = "processing"

    PILL_W = 290
    PILL_H = 96
    MARGIN_X = 28
    MARGIN_Y = 28

    def __init__(self, config: ConfigManager):
        super().__init__(None)
        self.config = config
        self.state = self.STATE_IDLE
        self.phase = 0.0
        self.swirl_angle = 0.0
        self.audio_level = 0.0
        self.smoothed_level = 0.0

        self.setFixedSize(self.PILL_W, self.PILL_H)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.timer = QTimer(self)
        self.timer.setInterval(16)  # ~60 FPS
        self.timer.timeout.connect(self._tick)

    def set_audio_level(self, level: float) -> None:
        self.audio_level = max(0.0, min(1.0, level))

    def _get_target_screen(self) -> Tuple[int, Optional[QScreen]]:
        screens = QGuiApplication.screens()
        if not screens:
            return (0, QGuiApplication.primaryScreen())
        idx = int(self.config.get("monitor_index", 0) or 0)
        if idx < 0 or idx >= len(screens):
            idx = 0
        return (idx, screens[idx])

    def _compute_global_pill_pos(self, avail: QRect) -> Tuple[int, int]:
        pos = self.config.get("overlay_position", "bottom_center")
        pw = self.PILL_W
        ph = self.PILL_H
        mx = self.MARGIN_X
        my = self.MARGIN_Y

        s_left = avail.left()
        s_top = avail.top()
        area_w = avail.width()
        area_h = avail.height()

        if pos == "bottom_right":
            return (s_left + area_w - pw - mx, s_top + area_h - ph - my)
        if pos == "bottom_left":
            return (s_left + mx, s_top + area_h - ph - my)
        if pos == "left_center":
            return (s_left + mx, s_top + (area_h - ph) // 2)
        if pos == "right_center":
            return (s_left + area_w - pw - mx, s_top + (area_h - ph) // 2)
        if pos == "top_center":
            return (s_left + (area_w - pw) // 2, s_top + my)
        if pos == "top_right":
            return (s_left + area_w - pw - mx, s_top + my)
        if pos == "top_left":
            return (s_left + mx, s_top + my)
        # Default: bottom_center
        return (s_left + (area_w - pw) // 2, s_top + area_h - ph - my)

    def _position_overlay(self) -> None:
        _screen_idx, target_screen = self._get_target_screen()
        if target_screen is None:
            return

        avail = target_screen.availableGeometry()
        gx, gy = self._compute_global_pill_pos(avail)
        self.setGeometry(gx, gy, self.PILL_W, self.PILL_H)
        self.move(gx, gy)

    def show_listening(self, locked: bool = False) -> None:
        self.state = self.STATE_LOCKED if locked else self.STATE_LISTENING
        self.phase = 0.0
        self.audio_level = 0.0
        self.smoothed_level = 0.0
        self._position_overlay()
        self.show()
        self._position_overlay()
        self.raise_()
        self.timer.start()
        self.update()

    def set_locked_mode(self) -> None:
        if self.state in (self.STATE_LISTENING, self.STATE_LOCKED):
            self.state = self.STATE_LOCKED
            self.update()

    def show_processing(self) -> None:
        self.state = self.STATE_PROCESSING
        self.audio_level = 0.0
        if not self.isVisible():
            self._position_overlay()
            self.show()
            self._position_overlay()
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def hide_overlay(self) -> None:
        self.state = self.STATE_IDLE
        self.timer.stop()
        self.hide()

    def _tick(self) -> None:
        self.phase += 0.06
        self.swirl_angle = (self.swirl_angle + 4.8) % 360.0
        self.smoothed_level = self.smoothed_level * 0.55 + self.audio_level * 0.45
        self.update()

    def paintEvent(self, event) -> None:
        if self.state == self.STATE_IDLE:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.PILL_W
        h = self.PILL_H

        pill_rect = QRectF(12, 12, w - 24, h - 24)
        border_color = (
            QColor(128, 255, 219, 120)
            if self.state == self.STATE_LOCKED
            else QColor(130, 235, 255, 65)
        )
        painter.setPen(QPen(border_color, 1.3))
        painter.setBrush(QColor(9, 16, 26, 215))
        painter.drawRoundedRect(pill_rect, 26, 26)

        orb_center = QPointF(48.0, h / 2.0)

        if self.state in (self.STATE_LISTENING, self.STATE_LOCKED):
            self._draw_listening_aura(
                painter, orb_center, locked=(self.state == self.STATE_LOCKED)
            )
            if self.state == self.STATE_LOCKED:
                title_text = "Listening (Locked)"
                sub_text = "Double-tap shortcut to finish"
            else:
                title_text = "Listening to your breath..."
                sub_text = "Release to paste • Double-tap to lock"
        else:
            self._draw_processing_swirl(painter, orb_center)
            title_text = "Distilling voice..."
            sub_text = "Transcribing with Gemini AI"

        title_font = QFont("Sans Serif", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(230, 252, 255, 240))
        painter.drawText(
            QRectF(82, 24, w - 98, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_text,
        )

        sub_font = QFont("Sans Serif", 8)
        painter.setFont(sub_font)
        painter.setPen(QColor(145, 205, 225, 195))
        painter.drawText(
            QRectF(82, 46, w - 98, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            sub_text,
        )

    def _draw_listening_aura(
        self, painter: QPainter, center: QPointF, locked: bool = False
    ) -> None:
        breath = (math.sin(self.phase) + 1.0) * 0.5
        expansion = breath * 4.5 + self.smoothed_level * 18.0

        outer_radius = 18.0 + expansion
        mid_radius = 12.5 + expansion * 0.60
        core_radius = 6.5 + breath * 1.4 + self.smoothed_level * 6.5

        outer_grad = QRadialGradient(center, outer_radius)
        if locked:
            outer_grad.setColorAt(0.0, QColor(128, 255, 219, 175))
            outer_grad.setColorAt(0.6, QColor(72, 191, 227, 105))
            outer_grad.setColorAt(1.0, QColor(72, 191, 227, 0))
        else:
            outer_grad.setColorAt(0.0, QColor(128, 255, 219, 145))
            outer_grad.setColorAt(0.55, QColor(86, 207, 225, 85))
            outer_grad.setColorAt(1.0, QColor(86, 207, 225, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(outer_grad)
        painter.drawEllipse(center, outer_radius, outer_radius)

        mid_grad = QRadialGradient(center, mid_radius)
        mid_grad.setColorAt(0.0, QColor(220, 255, 255, 215))
        mid_grad.setColorAt(0.7, QColor(100, 223, 223, 145))
        mid_grad.setColorAt(1.0, QColor(100, 223, 223, 0))
        painter.setBrush(mid_grad)
        painter.drawEllipse(center, mid_radius, mid_radius)

        core_grad = QRadialGradient(center, core_radius)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        core_grad.setColorAt(0.8, QColor(215, 252, 255, 210))
        core_grad.setColorAt(1.0, QColor(160, 240, 255, 0))
        painter.setBrush(core_grad)
        painter.drawEllipse(center, core_radius, core_radius)

    def _draw_processing_swirl(self, painter: QPainter, center: QPointF) -> None:
        glow_pulse = (math.sin(self.phase * 1.6) + 1.0) * 0.5
        ambient_radius = 22.0 + glow_pulse * 4.5

        ambient_grad = QRadialGradient(center, ambient_radius)
        ambient_grad.setColorAt(0.0, QColor(235, 250, 255, 190))
        ambient_grad.setColorAt(0.5, QColor(114, 239, 221, 110))
        ambient_grad.setColorAt(0.8, QColor(128, 195, 255, 50))
        ambient_grad.setColorAt(1.0, QColor(128, 195, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ambient_grad)
        painter.drawEllipse(center, ambient_radius, ambient_radius)

        swirl_radius = 14.5
        conical = QConicalGradient(center, -self.swirl_angle)
        conical.setColorAt(0.0, QColor(255, 255, 255, 245))
        conical.setColorAt(0.25, QColor(100, 223, 223, 200))
        conical.setColorAt(0.5, QColor(116, 185, 255, 40))
        conical.setColorAt(0.75, QColor(128, 255, 219, 190))
        conical.setColorAt(1.0, QColor(255, 255, 255, 245))

        pen = QPen()
        pen.setWidthF(3.0)
        pen.setBrush(conical)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, swirl_radius, swirl_radius)

        inner_rect = QRectF(center.x() - 9.0, center.y() - 9.0, 18.0, 18.0)
        inner_pen = QPen(QColor(235, 255, 255, 190), 1.8)
        inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(inner_pen)
        painter.drawArc(inner_rect, int(self.swirl_angle * 1.4 * 16), 120 * 16)
        painter.drawArc(inner_rect, int((self.swirl_angle * 1.4 + 180) * 16), 120 * 16)


class SettingsWindow(QDialog):
    shortcut_recorded = pyqtSignal(str)

    def __init__(
        self,
        config: ConfigManager,
        history: HistoryManager,
        on_settings_saved: Optional[Callable[[], None]] = None,
        last_error: str = "",
        initial_tab: int = 0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.history = history
        self.on_settings_saved = on_settings_saved
        self.last_error = last_error
        self._is_recording_shortcut = False
        self._recorded_tokens: list[str] = []

        self.setWindowTitle("Ruach Scribe — Settings & Transcription History")
        self.setWindowIcon(create_ruach_icon())
        self.setMinimumSize(660, 640)
        self.resize(700, 700)
        self.shortcut_recorded.connect(self._on_shortcut_recorded)

        self._apply_theme()
        self._build_ui()
        self._load_current_values()
        self.refresh_history()
        self.tabs.setCurrentIndex(initial_tab)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0d1520;
                color: #e2f1f8;
            }
            QTabWidget::pane {
                border: 1px solid #284660;
                border-radius: 6px;
                background-color: #0d1520;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #132030;
                color: #8ecae6;
                border: 1px solid #284660;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 18px;
                margin-right: 4px;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                background-color: #197278;
                color: #ffffff;
                border-color: #64dfdf;
                font-weight: bold;
            }
            QLabel {
                color: #bce4f5;
                font-size: 13px;
            }
            QLineEdit, QComboBox {
                background-color: #142232;
                color: #f0faff;
                border: 1px solid #284660;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 13px;
            }
            QPlainTextEdit, QListWidget {
                background-color: #142232;
                color: #f0faff;
                border: 1px solid #284660;
                border-radius: 6px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QListWidget:focus {
                border: 1px solid #64dfdf;
            }
            QListWidget::item {
                padding: 7px 6px;
                border-bottom: 1px solid #1c3147;
            }
            QListWidget::item:selected {
                background-color: #197278;
                color: #ffffff;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #1b3348;
                color: #e6f9ff;
                border: 1px solid #356080;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #244662;
                border-color: #64dfdf;
            }
            QPushButton#primaryButton {
                background-color: #197278;
                border-color: #64dfdf;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton#primaryButton:hover {
                background-color: #229299;
            }
            """
        )

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(10)

        header = QLabel("Ruach Scribe")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #80ffdb;")
        subtitle = QLabel(
            "Hold shortcut to talk & release to paste • Double-tap shortcut to lock hands-free"
        )
        subtitle.setStyleSheet("font-size: 12px; color: #8ecae6; margin-bottom: 2px;")
        root_layout.addWidget(header)
        root_layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.settings_tab = QWidget()
        self.history_tab = QWidget()
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.history_tab, "Transcription History (Before & After)")

        self._build_settings_tab()
        self._build_history_tab()

        root_layout.addWidget(self.tabs, 1)

    def _build_settings_tab(self) -> None:
        tab_layout = QVBoxLayout(self.settings_tab)
        tab_layout.setContentsMargins(14, 14, 14, 14)
        tab_layout.setSpacing(10)

        self.error_banner = QPlainTextEdit()
        self.error_banner.setReadOnly(True)
        self.error_banner.setFixedHeight(64)
        self.error_banner.setStyleSheet(
            "background-color: #2b141c; color: #ffb3c1; border: 1px solid #ff4d6d; font-size: 12px;"
        )
        if self.last_error:
            self.error_banner.setPlainText(f"Last Error:\n{self.last_error}")
            self.error_banner.show()
        else:
            self.error_banner.hide()
        tab_layout.addWidget(self.error_banner)

        wayland_row = QHBoxLayout()
        self.wayland_status_lbl = QLabel()
        self.enable_wayland_btn = QPushButton("Enable Wayland Global Hotkey & Paste")
        self.enable_wayland_btn.clicked.connect(self._grant_linux_input_permissions)
        wayland_row.addWidget(self.wayland_status_lbl, 1)
        wayland_row.addWidget(self.enable_wayland_btn)
        tab_layout.addLayout(wayland_row)
        self._refresh_wayland_permission_status()

        form = QFormLayout()
        form.setSpacing(10)

        # 1. Gemini API Key
        api_layout = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Enter your Google Gemini API Key (AIza...)")
        self.toggle_key_btn = QPushButton("Show")
        self.toggle_key_btn.setFixedWidth(64)
        self.toggle_key_btn.clicked.connect(self._toggle_api_key_visibility)
        api_layout.addWidget(self.api_key_input)
        api_layout.addWidget(self.toggle_key_btn)
        form.addRow("Gemini API Key:", api_layout)

        # 2. Gemini Model
        self.model_combo = QComboBox()
        self.model_combo.addItems(
            [
                "gemini-flash-lite-latest",
                "gemini-flash-latest",
                "gemini-pro-latest",
            ]
        )
        form.addRow("Gemini Model:", self.model_combo)

        # 3. Microphone Input Device
        mic_layout = QHBoxLayout()
        self.mic_combo = QComboBox()
        self.refresh_mic_btn = QPushButton("Refresh")
        self.refresh_mic_btn.setFixedWidth(80)
        self.refresh_mic_btn.clicked.connect(self._populate_microphones)
        mic_layout.addWidget(self.mic_combo)
        mic_layout.addWidget(self.refresh_mic_btn)
        form.addRow("Microphone:", mic_layout)

        # 4. Global Hotkey Preset + Custom / Record
        preset_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Custom / Select Preset...", "")
        for label, val in HOTKEY_PRESETS:
            self.preset_combo.addItem(label, val)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.preset_combo)
        form.addRow("Shortcut Preset:", preset_layout)

        hotkey_layout = QHBoxLayout()
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("e.g., <ctrl>+<alt> or ctrl_r")
        self.record_hotkey_btn = QPushButton("Record Shortcut")
        self.record_hotkey_btn.setFixedWidth(140)
        self.record_hotkey_btn.clicked.connect(self._start_recording_shortcut)
        hotkey_layout.addWidget(self.hotkey_input)
        hotkey_layout.addWidget(self.record_hotkey_btn)
        form.addRow("Active Shortcut:", hotkey_layout)

        # 5. Overlay Position (8 Anchor Positions)
        self.position_combo = QComboBox()
        for label, key in POSITION_OPTIONS:
            self.position_combo.addItem(label, key)
        form.addRow("Overlay Position:", self.position_combo)

        # 6. Monitor / Display Selection
        self.monitor_combo = QComboBox()
        self._populate_monitors()
        form.addRow("Display Monitor:", self.monitor_combo)

        # 7. Paste Keystroke Mode
        self.paste_combo = QComboBox()
        self.paste_combo.addItem("Ctrl + V (Standard Apps)", "ctrl+v")
        self.paste_combo.addItem("Shift + Insert (Terminals & Universal)", "shift+insert")
        form.addRow("Paste Method:", self.paste_combo)

        # 8. Autostart on Login
        self.autostart_checkbox = QCheckBox("Start Ruach Scribe automatically in background on login")
        self.autostart_checkbox.setStyleSheet("color: #e2f1f8; font-size: 13px;")
        form.addRow("Startup:", self.autostart_checkbox)

        # 9. System Prompt
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setFixedHeight(85)
        form.addRow("System Prompt:", self.prompt_edit)

        tab_layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.reset_prompt_btn = QPushButton("Reset Default Prompt")
        self.reset_prompt_btn.clicked.connect(
            lambda: self.prompt_edit.setPlainText(DEFAULT_PROMPT)
        )
        btn_row.addWidget(self.reset_prompt_btn)
        btn_row.addStretch()

        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_settings)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        tab_layout.addLayout(btn_row)

    def _build_history_tab(self) -> None:
        tab_layout = QVBoxLayout(self.history_tab)
        tab_layout.setContentsMargins(16, 16, 16, 16)
        tab_layout.setSpacing(14)

        # --- Section 1: Saved Transcriptions List ---
        sec1_widget = QWidget()
        sec1_layout = QVBoxLayout(sec1_widget)
        sec1_layout.setContentsMargins(0, 0, 0, 0)
        sec1_layout.setSpacing(6)

        top_bar = QHBoxLayout()
        self.history_count_lbl = QLabel("Saved Transcriptions: 0")
        self.history_count_lbl.setStyleSheet("font-weight: bold; color: #80ffdb;")
        self.clear_history_btn = QPushButton("Clear All History")
        self.clear_history_btn.clicked.connect(self._on_clear_history)
        top_bar.addWidget(self.history_count_lbl)
        top_bar.addStretch()
        top_bar.addWidget(self.clear_history_btn)
        sec1_layout.addLayout(top_bar)

        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(110)
        self.history_list.currentRowChanged.connect(self._on_history_row_selected)
        sec1_layout.addWidget(self.history_list, 1)
        tab_layout.addWidget(sec1_widget, 2)

        # --- Section 2: Before Editing (Raw Speech) ---
        sec2_widget = QWidget()
        sec2_layout = QVBoxLayout(sec2_widget)
        sec2_layout.setContentsMargins(0, 4, 0, 0)
        sec2_layout.setSpacing(6)

        before_header = QHBoxLayout()
        before_lbl = QLabel("Before Editing (Raw Verbatim Speech):")
        before_lbl.setStyleSheet("color: #ffd166; font-weight: bold;")
        self.copy_raw_btn = QPushButton("Copy Before Text")
        self.copy_raw_btn.clicked.connect(
            lambda: self._copy_to_clipboard(self.raw_text_view.toPlainText())
        )
        before_header.addWidget(before_lbl)
        before_header.addStretch()
        before_header.addWidget(self.copy_raw_btn)
        sec2_layout.addLayout(before_header)

        self.raw_text_view = QPlainTextEdit()
        self.raw_text_view.setReadOnly(True)
        self.raw_text_view.setMinimumHeight(90)
        self.raw_text_view.setPlaceholderText(
            "Select a transcription above to view the raw speech before editing..."
        )
        self.raw_text_view.setStyleSheet(
            "background-color: #1b1e2b; color: #ffe8a3; border: 1px solid #5c4d26;"
        )
        sec2_layout.addWidget(self.raw_text_view, 1)
        tab_layout.addWidget(sec2_widget, 2)

        # --- Section 3: After Editing (Cleaned Output) ---
        sec3_widget = QWidget()
        sec3_layout = QVBoxLayout(sec3_widget)
        sec3_layout.setContentsMargins(0, 4, 0, 0)
        sec3_layout.setSpacing(6)

        after_header = QHBoxLayout()
        after_lbl = QLabel("After Editing (Cleaned Output Pasted):")
        after_lbl.setStyleSheet("color: #80ffdb; font-weight: bold;")
        self.copy_cleaned_btn = QPushButton("Copy After Text")
        self.copy_cleaned_btn.setObjectName("primaryButton")
        self.copy_cleaned_btn.clicked.connect(
            lambda: self._copy_to_clipboard(self.cleaned_text_view.toPlainText())
        )
        after_header.addWidget(after_lbl)
        after_header.addStretch()
        after_header.addWidget(self.copy_cleaned_btn)
        sec3_layout.addLayout(after_header)

        self.cleaned_text_view = QPlainTextEdit()
        self.cleaned_text_view.setReadOnly(True)
        self.cleaned_text_view.setMinimumHeight(90)
        self.cleaned_text_view.setPlaceholderText(
            "Select a transcription above to view the cleaned text after editing..."
        )
        self.cleaned_text_view.setStyleSheet(
            "background-color: #112630; color: #e0fbfc; border: 1px solid #2ec4b6;"
        )
        sec3_layout.addWidget(self.cleaned_text_view, 1)
        tab_layout.addWidget(sec3_widget, 2)

    def refresh_history(self) -> None:
        entries = self.history.get_entries()
        self.history_count_lbl.setText(f"Saved Transcriptions: {len(entries)}")
        self.history_list.clear()

        for entry in entries:
            ts = entry.get("timestamp", "")
            lat = entry.get("latency_sec", 0.0)
            cleaned = entry.get("cleaned_text", "").replace("\n", " ")
            preview = cleaned[:68] + ("..." if len(cleaned) > 68 else "")
            item = QListWidgetItem(f"[{ts}] ({lat:.2f}s) — {preview}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.history_list.addItem(item)

        if entries:
            self.history_list.setCurrentRow(0)
        else:
            self.raw_text_view.clear()
            self.cleaned_text_view.clear()

    def _on_history_row_selected(self, row: int) -> None:
        if row < 0:
            self.raw_text_view.clear()
            self.cleaned_text_view.clear()
            return
        item = self.history_list.item(row)
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        self.raw_text_view.setPlainText(entry.get("raw_text", ""))
        self.cleaned_text_view.setPlainText(entry.get("cleaned_text", ""))

    def _on_clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear Transcription History",
            "Are you sure you want to clear all saved transcription history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh_history()

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        if not text:
            return
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(text, QClipboard.Mode.Clipboard)
            cb.setText(text, QClipboard.Mode.Selection)

    def _populate_monitors(self) -> None:
        self.monitor_combo.clear()
        screens = QGuiApplication.screens()
        if not screens:
            self.monitor_combo.addItem("Primary Monitor", 0)
            return
        for idx, s in enumerate(screens):
            g = s.geometry()
            name = s.name() or f"Display {idx + 1}"
            self.monitor_combo.addItem(
                f"Monitor {idx + 1}: {name} ({g.width()}x{g.height()})", idx
            )

    def set_last_error(self, error_msg: str) -> None:
        self.last_error = error_msg
        if error_msg:
            self.error_banner.setPlainText(f"Last Error:\n{error_msg}")
            self.error_banner.show()
        else:
            self.error_banner.hide()

    def _refresh_wayland_permission_status(self) -> None:
        evdev_ok = HotkeyManager.can_use_evdev()
        uinput_ok = os.access("/dev/uinput", os.W_OK)
        if evdev_ok and uinput_ok:
            self.wayland_status_lbl.setText(
                "Global Hotkey & Auto-Paste: Active across all Wayland & X11 windows"
            )
            self.wayland_status_lbl.setStyleSheet("color: #80ffdb; font-size: 12px;")
            self.enable_wayland_btn.hide()
        else:
            self.wayland_status_lbl.setText(
                "Wayland Input Access: Limited (Click button to enable global shortcut & auto-paste in all apps)"
            )
            self.wayland_status_lbl.setStyleSheet("color: #ffd166; font-size: 12px;")
            self.enable_wayland_btn.show()

    def _grant_linux_input_permissions(self) -> None:
        user = getpass.getuser()
        cmd = (
            f"setfacl -m u:{user}:rw /dev/input/event* /dev/uinput && "
            f"usermod -aG input {user} && "
            f"printf 'KERNEL==\"event*\", SUBSYSTEM==\"input\", MODE=\"0660\", GROUP=\"input\", TAG+=\"uaccess\"\\n"
            f"KERNEL==\"uinput\", SUBSYSTEM==\"misc\", MODE=\"0660\", GROUP=\"input\", TAG+=\"uaccess\"\\n' "
            f"> /etc/udev/rules.d/99-ruach-scribe.rules"
        )
        try:
            subprocess.run(["pkexec", "sh", "-c", cmd], check=True)
            self._refresh_wayland_permission_status()
            if self.on_settings_saved:
                self.on_settings_saved()
            QMessageBox.information(
                self,
                "Wayland Permissions Enabled",
                "Global hotkeys (Hold-to-Talk & Double-Tap) and Auto-Paste are now enabled across all windows!",
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Permission Setup Cancelled",
                f"Could not grant input device permissions automatically ({e}).\n\n"
                f"You can also run ./install.sh in a terminal.",
            )

    def _on_preset_selected(self, index: int) -> None:
        val = self.preset_combo.itemData(index)
        if val:
            self.hotkey_input.setText(val)

    def _start_recording_shortcut(self) -> None:
        self._is_recording_shortcut = True
        self._recorded_tokens = []
        self.record_hotkey_btn.setText("Press keys...")
        self.record_hotkey_btn.setStyleSheet("background-color: #9b2226; color: white;")
        self.setFocus()
        self.grabKeyboard()

    def keyPressEvent(self, event) -> None:
        if self._is_recording_shortcut and not event.isAutoRepeat():
            token = self._qt_key_to_token(event)
            if token and token not in self._recorded_tokens:
                self._recorded_tokens.append(token)
                self.hotkey_input.setText("+".join(self._recorded_tokens))
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if self._is_recording_shortcut and not event.isAutoRepeat():
            if self._recorded_tokens:
                combo = "+".join(self._recorded_tokens)
                self._is_recording_shortcut = False
                self.releaseKeyboard()
                self._on_shortcut_recorded(combo)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _on_shortcut_recorded(self, combo: str) -> None:
        self._is_recording_shortcut = False
        self.hotkey_input.setText(combo)
        self.record_hotkey_btn.setText("Record Shortcut")
        self.record_hotkey_btn.setStyleSheet("")

    @staticmethod
    def _qt_key_to_token(event) -> str:
        key = event.key()
        if key == Qt.Key.Key_Control:
            return "<ctrl>"
        if key == Qt.Key.Key_Alt or key == Qt.Key.Key_AltGr:
            return "<alt>"
        if key == Qt.Key.Key_Shift:
            return "<shift>"
        if key in (Qt.Key.Key_Meta, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R):
            return "<cmd>"
        if key == Qt.Key.Key_Space:
            return "<space>"
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            return f"f{key - Qt.Key.Key_F1 + 1}"
        text = event.text().strip().lower()
        if text and text.isprintable():
            return text
        return ""

    def _toggle_api_key_visibility(self) -> None:
        if self.api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_key_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_key_btn.setText("Show")

    def _populate_microphones(self) -> None:
        current_dev = self.config.get("device_index", None)
        self.mic_combo.clear()
        self.mic_combo.addItem("System Default Microphone", None)

        for idx, label in AudioRecorder.list_input_devices():
            self.mic_combo.addItem(label, idx)

        for i in range(self.mic_combo.count()):
            if self.mic_combo.itemData(i) == current_dev:
                self.mic_combo.setCurrentIndex(i)
                break

    def _load_current_values(self) -> None:
        self.api_key_input.setText(self.config.get("api_key", ""))

        model_name = self.config.get("model_name", "gemini-flash-lite-latest")
        idx = self.model_combo.findText(model_name)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

        self._populate_microphones()
        hotkey_val = self.config.get("hotkey", "<ctrl>+<alt>")
        self.hotkey_input.setText(hotkey_val)
        preset_idx = self.preset_combo.findData(hotkey_val)
        if preset_idx >= 0:
            self.preset_combo.setCurrentIndex(preset_idx)

        pos_idx = self.position_combo.findData(
            self.config.get("overlay_position", "bottom_center")
        )
        if pos_idx >= 0:
            self.position_combo.setCurrentIndex(pos_idx)

        mon_idx = self.monitor_combo.findData(self.config.get("monitor_index", 0))
        if mon_idx >= 0:
            self.monitor_combo.setCurrentIndex(mon_idx)

        paste_idx = self.paste_combo.findData(
            self.config.get("paste_shortcut", "ctrl+v")
        )
        if paste_idx >= 0:
            self.paste_combo.setCurrentIndex(paste_idx)

        self.autostart_checkbox.setChecked(bool(self.config.get("autostart", True)))

        self.prompt_edit.setPlainText(self.config.get("system_prompt", DEFAULT_PROMPT))

    def _save_settings(self) -> None:
        hotkey_str = self.hotkey_input.text().strip() or "<ctrl>+<alt>"
        prompt_str = self.prompt_edit.toPlainText().strip() or DEFAULT_PROMPT

        self.config.data["api_key"] = self.api_key_input.text().strip()
        self.config.data["model_name"] = self.model_combo.currentText()
        self.config.data["device_index"] = self.mic_combo.currentData()
        self.config.data["hotkey"] = hotkey_str
        self.config.data["overlay_position"] = self.position_combo.currentData()
        self.config.data["monitor_index"] = int(self.monitor_combo.currentData() or 0)
        self.config.data["paste_shortcut"] = self.paste_combo.currentData()
        self.config.data["autostart"] = bool(self.autostart_checkbox.isChecked())
        self.config.data["system_prompt"] = prompt_str
        self.config.save()

        if self.on_settings_saved:
            try:
                self.on_settings_saved()
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Hotkey Registration Error",
                    f"Settings saved, but could not bind hotkey '{hotkey_str}':\n{e}",
                )
                return

        self.accept()
