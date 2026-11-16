import json
import os
import shutil
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
LEGACY_CONFIG_PATH = REPO_DIR / "config.json"
PRIVATE_BACKUP_CONFIG_PATH = REPO_DIR / ".private_local" / "config.json"


def get_user_config_path() -> Path:
    """
    Store config.json (including the Gemini API key) in ~/.config/ruach-scribe/config.json,
    completely outside the Git repository so it can never be committed to GitHub.
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    user_dir = base_dir / "ruach-scribe"
    target_path = user_dir / "config.json"

    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        for old_path in (LEGACY_CONFIG_PATH, PRIVATE_BACKUP_CONFIG_PATH):
            if old_path.exists():
                if not target_path.exists():
                    shutil.copy2(old_path, target_path)
                    os.chmod(target_path, 0o600)
                old_path.unlink()
        return target_path
    except OSError:
        PRIVATE_BACKUP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        return PRIVATE_BACKUP_CONFIG_PATH


def sync_autostart_desktop_entry(enabled: bool = True) -> bool:
    """Create or remove ~/.config/autostart/ruach-scribe.desktop for login autostart."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    autostart_dir = base_dir / "autostart"
    desktop_file = autostart_dir / "ruach-scribe.desktop"

    try:
        if enabled:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            run_script = REPO_DIR / "run.sh"
            icon_path = REPO_DIR / "assets" / "ruach-scribe.png"
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Ruach Scribe\n"
                "Comment=Ethereal Voice Dictation & AI Transcription\n"
                f'Exec="{run_script}" --foreground\n'
                f"Icon={icon_path}\n"
                f"Path={REPO_DIR}\n"
                "Terminal=false\n"
                "Hidden=false\n"
                "NoDisplay=false\n"
                "X-GNOME-Autostart-enabled=true\n"
                "X-GNOME-Autostart-Delay=3\n"
                "StartupNotify=false\n"
            )
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(desktop_file, 0o755)
        else:
            if desktop_file.exists():
                desktop_file.unlink()
        return True
    except OSError:
        return False


DEFAULT_PROMPT = (
    "You are an intelligent voice dictation editor (like Wispr Flow). "
    "Transform the user's spoken audio into clean, polished written text by following these strict rules:\n"
    "1. REMOVE ALL FILLERS & STUTTERS: Completely strip filler words (um, uh, ah, er, hmm, like, you know), "
    "stutters, and accidental word repetitions.\n"
    "2. APPLY SPOKEN SELF-CORRECTIONS: If the speaker corrects themselves or backtracks using phrases like "
    "'scratch that', 'delete that', 'no wait', 'actually', or 'I mean', DO NOT transcribe the mistake or the "
    "correction phrase—output ONLY the final corrected thought. "
    "(Example: 'Um, send the file to Bob, scratch that, send it to Alice at 3 PM' -> 'Send the file to Alice at 3:00 PM.')\n"
    "3. PUNCTUATION & OUTPUT: Apply natural punctuation and capitalization. "
    "Output ONLY the final cleaned text without any quotes, markdown, or introductory commentary."
)

LEGACY_PROMPTS = {
    (
        "You are a professional transcription assistant. Transcribe the following audio "
        "exactly. Remove all filler words (um, uh, ah), false starts, and stutters. Apply "
        "perfect punctuation and capitalization. Output ONLY the finalized text without "
        "any markdown formatting, conversational filler, or introductory text."
    )
}

VALID_POSITIONS = {
    "bottom_center",
    "bottom_right",
    "bottom_left",
    "left_center",
    "right_center",
    "top_center",
    "top_right",
    "top_left",
}

DEFAULT_CONFIG = {
    "api_key": "",
    "model_name": "gemini-flash-lite-latest",
    "device_index": None,  # None uses system default input device
    "hotkey": "<ctrl>+<alt>",
    "overlay_position": "bottom_center",
    "monitor_index": 0,  # 0 = Monitor 1, 1 = Monitor 2, etc.
    "paste_shortcut": "ctrl+v",  # "ctrl+v" or "shift+insert"
    "autostart": True,  # Launch automatically on login
    "system_prompt": DEFAULT_PROMPT,
}

AUTO_UPGRADE_MODELS = {
    "gemini-1.5-flash": "gemini-flash-lite-latest",
    "gemini-1.5-flash-latest": "gemini-flash-lite-latest",
    "gemini-1.5-pro": "gemini-pro-latest",
    "gemini-1.5-pro-latest": "gemini-pro-latest",
    "gemini-2.0-flash": "gemini-flash-lite-latest",
    "gemini-2.5-flash": "gemini-flash-lite-latest",
    "gemini-2.5-pro": "gemini-pro-latest",
    "gemini-3.8-flash": "gemini-flash-lite-latest",
}


class ConfigManager:
    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or get_user_config_path()
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> dict:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data.update(loaded)

                changed = False
                current_model = self.data.get("model_name", "")
                if current_model in AUTO_UPGRADE_MODELS:
                    self.data["model_name"] = AUTO_UPGRADE_MODELS[current_model]
                    changed = True

                if self.data.get("hotkey") == "<alt>+<space>":
                    self.data["hotkey"] = "<ctrl>+<alt>"
                    changed = True

                if self.data.get("overlay_position") not in VALID_POSITIONS:
                    self.data["overlay_position"] = "bottom_center"
                    changed = True

                if "monitor_index" not in self.data or not isinstance(
                    self.data.get("monitor_index"), int
                ):
                    self.data["monitor_index"] = 0
                    changed = True

                if "autostart" not in self.data:
                    self.data["autostart"] = True
                    changed = True

                if self.data.get("system_prompt", "").strip() in LEGACY_PROMPTS:
                    self.data["system_prompt"] = DEFAULT_PROMPT
                    changed = True

                if changed:
                    self.save()
            except Exception as e:
                print(
                    f"[Ruach Scribe] Warning: Failed to load config.json ({e}). Using defaults."
                )
        else:
            self.save()

        sync_autostart_desktop_entry(bool(self.data.get("autostart", True)))
        return self.data

    def save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
            try:
                os.chmod(self.config_path, 0o600)
            except OSError:
                pass
            sync_autostart_desktop_entry(bool(self.data.get("autostart", True)))
        except Exception as e:
            print(f"[Ruach Scribe] Error saving config.json: {e}")

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()
