import datetime
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Dict, List

REPO_DIR = Path(__file__).resolve().parent
LEGACY_HISTORY_PATH = REPO_DIR / "history.json"
PRIVATE_BACKUP_HISTORY_PATH = REPO_DIR / ".private_local" / "history.json"
MAX_HISTORY_ITEMS = 200


def get_user_history_path() -> Path:
    """
    Store history.json in ~/.config/ruach-scribe/history.json, completely outside
    the Git repository so personal transcriptions can never be committed to GitHub.
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    user_dir = base_dir / "ruach-scribe"
    target_path = user_dir / "history.json"

    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        for old_path in (LEGACY_HISTORY_PATH, PRIVATE_BACKUP_HISTORY_PATH):
            if old_path.exists():
                if not target_path.exists():
                    shutil.copy2(old_path, target_path)
                    os.chmod(target_path, 0o600)
                old_path.unlink()
        return target_path
    except OSError:
        PRIVATE_BACKUP_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        return PRIVATE_BACKUP_HISTORY_PATH


class HistoryManager:
    def __init__(self, history_path: Path | None = None):
        self.history_path = history_path or get_user_history_path()
        self._lock = threading.Lock()
        self.entries: List[Dict] = []
        self.load()

    def load(self) -> List[Dict]:
        with self._lock:
            if self.history_path.exists():
                try:
                    with open(self.history_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        self.entries = data
                except Exception as e:
                    print(f"[Ruach Scribe] Warning: Could not load history.json ({e})")
            return list(self.entries)

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.entries[:MAX_HISTORY_ITEMS], f, indent=2)
            try:
                os.chmod(self.history_path, 0o600)
            except OSError:
                pass
        except Exception as e:
            print(f"[Ruach Scribe] Error saving history.json: {e}")

    def add_entry(
        self,
        raw_text: str,
        cleaned_text: str,
        latency_sec: float = 0.0,
        model_name: str = "",
    ) -> Dict:
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw_text": raw_text.strip(),
            "cleaned_text": cleaned_text.strip(),
            "latency_sec": round(latency_sec, 2),
            "model_name": model_name,
        }
        with self._lock:
            self.entries.insert(0, entry)
            if len(self.entries) > MAX_HISTORY_ITEMS:
                self.entries = self.entries[:MAX_HISTORY_ITEMS]
            self._save_unlocked()
        return entry

    def get_entries(self) -> List[Dict]:
        with self._lock:
            return list(self.entries)

    def clear(self) -> None:
        with self._lock:
            self.entries = []
            self._save_unlocked()
