import glob
import os
import select
import threading
import time
from typing import Callable, Dict, Optional, Set

# Ensure DISPLAY is populated if an X11/XWayland socket exists
if not os.environ.get("DISPLAY"):
    _xsocks = sorted(glob.glob("/tmp/.X11-unix/X*"))
    if _xsocks:
        os.environ["DISPLAY"] = f":{os.path.basename(_xsocks[0]).lstrip('X')}"

try:
    from pynput import keyboard

    HAS_PYNPUT = True
except Exception:
    keyboard = None  # type: ignore
    HAS_PYNPUT = False

try:
    import evdev
    from evdev import ecodes

    HAS_EVDEV = True
except Exception:
    HAS_EVDEV = False


# Mapping normalized token names to evdev keycode sets
EVDEV_TOKEN_MAP = {
    "<ctrl>": {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"},
    "ctrl": {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"},
    "ctrl_l": {"KEY_LEFTCTRL"},
    "ctrl_r": {"KEY_RIGHTCTRL"},
    "<alt>": {"KEY_LEFTALT", "KEY_RIGHTALT"},
    "alt": {"KEY_LEFTALT", "KEY_RIGHTALT"},
    "alt_l": {"KEY_LEFTALT"},
    "alt_r": {"KEY_RIGHTALT"},
    "<shift>": {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"},
    "shift": {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"},
    "shift_l": {"KEY_LEFTSHIFT"},
    "shift_r": {"KEY_RIGHTSHIFT"},
    "<cmd>": {"KEY_LEFTMETA", "KEY_RIGHTMETA"},
    "<super>": {"KEY_LEFTMETA", "KEY_RIGHTMETA"},
    "super": {"KEY_LEFTMETA", "KEY_RIGHTMETA"},
    "<space>": {"KEY_SPACE"},
    "space": {"KEY_SPACE"},
    "f7": {"KEY_F7"},
    "f8": {"KEY_F8"},
    "f9": {"KEY_F9"},
    "f10": {"KEY_F10"},
    "f12": {"KEY_F12"},
    "scroll_lock": {"KEY_SCROLLLOCK"},
    "pause": {"KEY_PAUSE"},
    "insert": {"KEY_INSERT"},
    "capslock": {"KEY_CAPSLOCK"},
}


def parse_hotkey_tokens(hotkey_str: str) -> list[str]:
    """Parse a hotkey string like '<ctrl>+<alt>' or 'ctrl_r' into normalized tokens."""
    raw = (hotkey_str or "<ctrl>+<alt>").strip().lower()
    tokens = [t.strip() for t in raw.split("+") if t.strip()]
    return tokens if tokens else ["<ctrl>", "<alt>"]


class HotkeyGestureController:
    """
    Implements the Hold-to-Talk and Double-Tap-to-Lock state machine:
      - Hold key(s) down (>= 0.30s) -> activates while pressed, stops & transcribes on release.
      - Double-tap key(s) quickly -> locks activation (hands-free mode).
      - Double-tap key(s) while locked -> stops activation & transcribes.
      - Single accidental brief tap (< 0.30s) without a second tap -> cancels cleanly.
    """

    MODE_IDLE = "idle"
    MODE_HOLDING = "holding"
    MODE_WAIT_SECOND_TAP = "wait_second_tap"
    MODE_LOCKED = "locked"

    HOLD_THRESHOLD_SEC = 0.30
    DOUBLE_TAP_WINDOW_SEC = 0.45

    def __init__(
        self,
        on_start: Callable[[], None],
        on_lock: Callable[[], None],
        on_stop_and_transcribe: Callable[[], None],
        on_cancel: Callable[[], None],
    ):
        self.on_start = on_start
        self.on_lock = on_lock
        self.on_stop_and_transcribe = on_stop_and_transcribe
        self.on_cancel = on_cancel

        self._lock = threading.Lock()
        self.mode = self.MODE_IDLE
        self._press_time = 0.0
        self._locked_first_tap_time = 0.0
        self._cancel_timer: Optional[threading.Timer] = None
        self._just_locked_on_this_press = False

    def reset(self) -> None:
        with self._lock:
            if self._cancel_timer is not None:
                self._cancel_timer.cancel()
                self._cancel_timer = None
            self.mode = self.MODE_IDLE
            self._just_locked_on_this_press = False
            self._locked_first_tap_time = 0.0

    def handle_combo_press(self) -> None:
        now = time.monotonic()
        action = None

        with self._lock:
            if self.mode == self.MODE_IDLE:
                self.mode = self.MODE_HOLDING
                self._press_time = now
                self._just_locked_on_this_press = False
                action = "start"

            elif self.mode == self.MODE_WAIT_SECOND_TAP:
                # 2nd tap arrived within DOUBLE_TAP_WINDOW_SEC -> Lock recording on!
                if self._cancel_timer is not None:
                    self._cancel_timer.cancel()
                    self._cancel_timer = None
                self.mode = self.MODE_LOCKED
                self._just_locked_on_this_press = True
                self._locked_first_tap_time = 0.0
                action = "lock"

            elif self.mode == self.MODE_LOCKED:
                self._press_time = now
                self._just_locked_on_this_press = False
                if (now - self._locked_first_tap_time) <= self.DOUBLE_TAP_WINDOW_SEC:
                    # 2nd tap while locked -> Stop and transcribe!
                    self.mode = self.MODE_IDLE
                    self._locked_first_tap_time = 0.0
                    action = "stop"
                else:
                    # 1st tap while locked
                    self._locked_first_tap_time = now

        if action == "start":
            self.on_start()
        elif action == "lock":
            self.on_lock()
        elif action == "stop":
            self.on_stop_and_transcribe()

    def handle_combo_release(self) -> None:
        now = time.monotonic()
        action = None

        with self._lock:
            if self.mode == self.MODE_HOLDING:
                held_for = now - self._press_time
                if held_for >= self.HOLD_THRESHOLD_SEC:
                    # Held while speaking -> stop & transcribe on release
                    self.mode = self.MODE_IDLE
                    action = "stop"
                else:
                    # Short tap #1 -> wait briefly for tap #2 to lock
                    self.mode = self.MODE_WAIT_SECOND_TAP
                    if self._cancel_timer is not None:
                        self._cancel_timer.cancel()
                    self._cancel_timer = threading.Timer(
                        self.DOUBLE_TAP_WINDOW_SEC, self._on_single_tap_timeout
                    )
                    self._cancel_timer.daemon = True
                    self._cancel_timer.start()

            elif self.mode == self.MODE_LOCKED:
                if self._just_locked_on_this_press:
                    # Releasing the 2nd tap that engaged lock mode -> stay locked
                    self._just_locked_on_this_press = False
                else:
                    # If user held the key down for > 0.6s while locked, also allow stopping
                    if (now - self._press_time) >= 0.60:
                        self.mode = self.MODE_IDLE
                        self._locked_first_tap_time = 0.0
                        action = "stop"

        if action == "stop":
            self.on_stop_and_transcribe()

    def _on_single_tap_timeout(self) -> None:
        should_cancel = False
        with self._lock:
            if self.mode == self.MODE_WAIT_SECOND_TAP:
                self.mode = self.MODE_IDLE
                self._cancel_timer = None
                should_cancel = True
        if should_cancel:
            self.on_cancel()


class HotkeyManager:
    """
    Listens globally for key press and release events using:
      1. Linux kernel evdev (/dev/input/event*) if accessible (works across all Wayland & X11 windows).
      2. pynput.keyboard.Listener with X11 auto-repeat debouncing as an automatic fallback.
    """

    def __init__(
        self,
        hotkey_str: str,
        gesture_controller: HotkeyGestureController,
    ):
        self.hotkey_str = hotkey_str
        self.tokens = parse_hotkey_tokens(hotkey_str)
        self.gesture = gesture_controller

        self._stop_event = threading.Event()
        self._evdev_thread: Optional[threading.Thread] = None
        self._pynput_listener: Optional[keyboard.Listener] = None
        self.backend_name = "none"

        # State tracking
        self._combo_active = False
        self._pressed_pynput: Set[str] = set()
        self._release_timers: Dict[str, threading.Timer] = {}
        self._state_lock = threading.Lock()

    @staticmethod
    def can_use_evdev() -> bool:
        if not HAS_EVDEV:
            return False
        try:
            for path in glob.glob("/dev/input/event*"):
                if os.access(path, os.R_OK):
                    dev = evdev.InputDevice(path)
                    caps = dev.capabilities()
                    if ecodes.EV_KEY in caps:
                        keys = caps[ecodes.EV_KEY]
                        if ecodes.KEY_SPACE in keys and ecodes.KEY_A in keys:
                            dev.close()
                            return True
                    dev.close()
        except Exception:
            pass
        return False

    def start(self) -> str:
        self._stop_event.clear()
        if self.can_use_evdev():
            self.backend_name = "evdev (Wayland + X11 Global)"
            self._evdev_thread = threading.Thread(
                target=self._run_evdev_loop, daemon=True
            )
            self._evdev_thread.start()
        else:
            if HAS_PYNPUT and keyboard is not None:
                self.backend_name = "pynput (X11 / XWayland)"
                self._pynput_listener = keyboard.Listener(
                    on_press=self._on_pynput_press,
                    on_release=self._on_pynput_release,
                )
                self._pynput_listener.daemon = True
                self._pynput_listener.start()
            else:
                self.backend_name = "unavailable (Enable Wayland Input Access in Settings)"
        return self.backend_name

    def stop(self) -> None:
        self._stop_event.set()
        if self._pynput_listener is not None:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None
        for t in list(self._release_timers.values()):
            t.cancel()
        self._release_timers.clear()

    # -------------------- EVDEV BACKEND --------------------
    def _token_matches_evdev(self, token: str, pressed_key_names: Set[str]) -> bool:
        if token in EVDEV_TOKEN_MAP:
            return bool(EVDEV_TOKEN_MAP[token] & pressed_key_names)
        clean = token.strip("<>").upper()
        return f"KEY_{clean}" in pressed_key_names

    def _run_evdev_loop(self) -> None:
        devices = []
        try:
            for path in glob.glob("/dev/input/event*"):
                if os.access(path, os.R_OK):
                    try:
                        dev = evdev.InputDevice(path)
                        caps = dev.capabilities()
                        if ecodes.EV_KEY in caps:
                            keys = caps[ecodes.EV_KEY]
                            if ecodes.KEY_SPACE in keys or ecodes.KEY_LEFTCTRL in keys:
                                devices.append(dev)
                            else:
                                dev.close()
                        else:
                            dev.close()
                    except Exception:
                        pass

            pressed_codes: Set[str] = set()
            fd_map = {dev.fd: dev for dev in devices}

            while not self._stop_event.is_set() and fd_map:
                r, _, _ = select.select(list(fd_map.keys()), [], [], 0.2)
                for fd in r:
                    dev = fd_map.get(fd)
                    if dev is None:
                        continue
                    try:
                        for event in dev.read():
                            if event.type != ecodes.EV_KEY:
                                continue
                            key_name = ecodes.KEY.get(event.code)
                            if isinstance(key_name, list):
                                key_name = key_name[0]
                            if not key_name:
                                continue

                            # event.value: 1 = press, 0 = release, 2 = autorepeat hold (ignore 2!)
                            if event.value == 1:
                                pressed_codes.add(key_name)
                                self._check_evdev_combo(pressed_codes)
                            elif event.value == 0:
                                pressed_codes.discard(key_name)
                                self._check_evdev_combo(pressed_codes)
                    except OSError:
                        fd_map.pop(fd, None)
        finally:
            for dev in devices:
                try:
                    dev.close()
                except Exception:
                    pass

    def _check_evdev_combo(self, pressed_codes: Set[str]) -> None:
        all_matched = all(
            self._token_matches_evdev(tok, pressed_codes) for tok in self.tokens
        )
        if all_matched and not self._combo_active:
            self._combo_active = True
            self.gesture.handle_combo_press()
        elif not all_matched and self._combo_active:
            self._combo_active = False
            self.gesture.handle_combo_release()

    # -------------------- PYNPUT FALLBACK BACKEND --------------------
    @staticmethod
    def _normalize_pynput_key(key) -> Set[str]:
        """Return all matching normalized token names for a pynput key."""
        names: Set[str] = set()
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l):
            names.update({"<ctrl>", "ctrl", "ctrl_l"})
        elif key == keyboard.Key.ctrl_r:
            names.update({"<ctrl>", "ctrl", "ctrl_r"})
        elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_gr):
            names.update({"<alt>", "alt", "alt_l"})
        elif key == keyboard.Key.alt_r:
            names.update({"<alt>", "alt", "alt_r"})
        elif key in (keyboard.Key.shift, keyboard.Key.shift_l):
            names.update({"<shift>", "shift", "shift_l"})
        elif key == keyboard.Key.shift_r:
            names.update({"<shift>", "shift", "shift_r"})
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            names.update({"<cmd>", "<super>", "super"})
        elif key == keyboard.Key.space:
            names.update({"<space>", "space"})
        elif hasattr(key, "name") and key.name:
            n = key.name.lower()
            names.add(n)
            names.add(f"<{n}>")
        elif hasattr(key, "char") and key.char:
            c = key.char.lower()
            names.add(c)
        return names

    def _on_pynput_press(self, key) -> None:
        matched_names = self._normalize_pynput_key(key)
        if not matched_names:
            return

        with self._state_lock:
            # Cancel any pending debounced release for these tokens (filters out X11 auto-repeat!)
            for name in matched_names:
                timer = self._release_timers.pop(name, None)
                if timer is not None:
                    timer.cancel()
                self._pressed_pynput.add(name)

            all_matched = all(tok in self._pressed_pynput for tok in self.tokens)
            if all_matched and not self._combo_active:
                self._combo_active = True
                threading.Thread(
                    target=self.gesture.handle_combo_press, daemon=True
                ).start()

    def _on_pynput_release(self, key) -> None:
        matched_names = self._normalize_pynput_key(key)
        if not matched_names:
            return

        # Debounce release by 65ms so X11 key auto-repeat while holding doesn't false-trigger release
        with self._state_lock:
            for name in matched_names:
                old_timer = self._release_timers.pop(name, None)
                if old_timer is not None:
                    old_timer.cancel()
                t = threading.Timer(0.065, self._commit_pynput_release, args=(name,))
                t.daemon = True
                self._release_timers[name] = t
                t.start()

    def _commit_pynput_release(self, name: str) -> None:
        with self._state_lock:
            self._release_timers.pop(name, None)
            self._pressed_pynput.discard(name)
            all_matched = all(tok in self._pressed_pynput for tok in self.tokens)
            if not all_matched and self._combo_active:
                self._combo_active = False
                threading.Thread(
                    target=self.gesture.handle_combo_release, daemon=True
                ).start()
