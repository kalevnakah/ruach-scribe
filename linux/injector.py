import glob
import os
import shutil
import subprocess
import time
from typing import Optional

if not os.environ.get("DISPLAY"):
    _xsocks = sorted(glob.glob("/tmp/.X11-unix/X*"))
    if _xsocks:
        os.environ["DISPLAY"] = f":{os.path.basename(_xsocks[0]).lstrip('X')}"

try:
    from pynput.keyboard import Controller, Key

    HAS_PYNPUT = True
except Exception:
    Controller = None  # type: ignore
    Key = None  # type: ignore
    HAS_PYNPUT = False

from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import QApplication

try:
    import evdev
    from evdev import UInput, ecodes

    HAS_EVDEV = True
except Exception:
    HAS_EVDEV = False


class TextInjector:
    """
    Copies transcribed text to the system clipboard (Wayland & X11) and immediately
    pastes it into the currently focused text box with minimal latency.
    """

    def __init__(self):
        self.keyboard = Controller() if HAS_PYNPUT else None
        self.has_xdotool = shutil.which("xdotool") is not None
        self.has_wl_copy = shutil.which("wl-copy") is not None
        self.has_xclip = shutil.which("xclip") is not None
        self._uinput: Optional["UInput"] = None
        self._init_uinput()

    def _init_uinput(self) -> None:
        if not HAS_EVDEV or not os.access("/dev/uinput", os.W_OK):
            self._uinput = None
            return
        try:
            cap = {
                ecodes.EV_KEY: [
                    ecodes.KEY_LEFTCTRL,
                    ecodes.KEY_LEFTSHIFT,
                    ecodes.KEY_V,
                    ecodes.KEY_INSERT,
                ]
            }
            self._uinput = UInput(cap, name="Ruach-Scribe-Virtual-Keyboard")
        except Exception as e:
            print(f"[Ruach Scribe] Could not initialize UInput virtual keyboard: {e}")
            self._uinput = None

    def inject_text(self, text: str, paste_shortcut: str = "ctrl+v") -> None:
        if not text:
            return

        # 1. Copy text to Qt Clipboard immediately
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text, QClipboard.Mode.Clipboard)
            clipboard.setText(text, QClipboard.Mode.Selection)
            QApplication.processEvents()

        # 2. Sync to Wayland/X11 clipboards in parallel without blocking
        encoded = text.encode("utf-8")
        if self.has_wl_copy:
            try:
                p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, close_fds=True)
                if p.stdin:
                    p.stdin.write(encoded)
                    p.stdin.close()
            except Exception:
                pass

        if self.has_xclip:
            try:
                p = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                    close_fds=True,
                )
                if p.stdin:
                    p.stdin.write(encoded)
                    p.stdin.close()
            except Exception:
                pass

        # Minimal 25ms pause for clipboard sync
        time.sleep(0.025)

        # 3. Priority 1: Kernel UInput virtual keyboard (works in 100% of Wayland & X11 apps)
        if self._uinput is None and HAS_EVDEV and os.access("/dev/uinput", os.W_OK):
            self._init_uinput()

        if self._uinput is not None:
            try:
                if paste_shortcut == "shift+insert":
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_INSERT, 1)
                    self._uinput.syn()
                    time.sleep(0.01)
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_INSERT, 0)
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
                    self._uinput.syn()
                else:
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
                    self._uinput.syn()
                    time.sleep(0.01)
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
                    self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
                    self._uinput.syn()
                return
            except Exception as e:
                print(f"[Ruach Scribe] UInput paste error, falling back: {e}")

        # 4. Priority 2: xdotool
        if self.has_xdotool:
            key_combo = "shift+Insert" if paste_shortcut == "shift+insert" else "ctrl+v"
            try:
                subprocess.run(
                    [
                        "xdotool",
                        "key",
                        "--clearmodifiers",
                        "--delay",
                        "10",
                        key_combo,
                    ],
                    check=True,
                    timeout=1.5,
                )
                return
            except Exception as e:
                print(f"[Ruach Scribe] xdotool fallback to pynput ({e})")

        # 5. Priority 3: pynput keyboard controller
        if self.keyboard is not None and HAS_PYNPUT:
            if paste_shortcut == "shift+insert":
                with self.keyboard.pressed(Key.shift):
                    self.keyboard.press(Key.insert)
                    self.keyboard.release(Key.insert)
            else:
                with self.keyboard.pressed(Key.ctrl):
                    self.keyboard.press("v")
                    self.keyboard.release("v")
