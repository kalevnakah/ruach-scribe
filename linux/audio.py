import io
import threading
from typing import Callable, List, Optional, Tuple

import numpy as np
import scipy.io.wavfile as wavfile
import sounddevice as sd


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        on_amplitude: Optional[Callable[[float], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.on_amplitude = on_amplitude

        self._frames: List[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self.is_recording = False

    @staticmethod
    def list_input_devices() -> List[Tuple[int, str]]:
        """Return a list of (device_index, device_name) for available input devices."""
        devices = []
        try:
            all_devs = sd.query_devices()
            for idx, dev in enumerate(all_devs):
                if dev.get("max_input_channels", 0) > 0:
                    devices.append((idx, f"{dev['name']} (ID: {idx})"))
        except Exception as e:
            print(f"[Ruach Scribe] Error querying audio devices: {e}")
        return devices

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        with self._lock:
            if self.is_recording:
                self._frames.append(indata.copy())
                if self.on_amplitude is not None:
                    rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2))) / 32768.0
                    level = min(1.0, rms * 8.0)
                    self.on_amplitude(level)

    def start(self, device_index: Optional[int] = None) -> None:
        with self._lock:
            if self.is_recording:
                return
            self._frames = []
            self.is_recording = True

        try:
            dev_info = sd.query_devices(device_index, "input")
            default_sr = int(dev_info.get("default_samplerate", 44100))
            attempts = [
                (self.sample_rate, self.channels),
                (default_sr, self.channels),
                (default_sr, 2),
                (48000, 1),
                (48000, 2),
                (44100, 1),
                (44100, 2),
            ]
            last_err = None
            for sr, ch in attempts:
                try:
                    self._stream = sd.InputStream(
                        samplerate=sr,
                        blocksize=1024,
                        latency="low",
                        channels=ch,
                        dtype="int16",
                        device=device_index,
                        callback=self._audio_callback,
                    )
                    self.sample_rate = sr
                    self.channels = ch
                    break
                except sd.PortAudioError as e:
                    last_err = e
            if self._stream is None:
                raise last_err or RuntimeError("No supported audio input configuration")
            self._stream.start()
        except Exception as e:
            with self._lock:
                self.is_recording = False
            raise RuntimeError(f"Could not start microphone recording: {e}") from e

    @staticmethod
    def _close_stream_async(stream: sd.InputStream) -> None:
        try:
            stream.abort()
            stream.close()
        except Exception:
            pass

    def _trim_silence(self, audio_data: np.ndarray) -> np.ndarray:
        """Trim leading and trailing silence to minimize upload size & Gemini processing time."""
        if len(audio_data) == 0:
            return audio_data
        flat = np.abs(audio_data.reshape(-1))
        # Threshold ~ 1.2% of max int16 amplitude (390 / 32768)
        voice_indices = np.where(flat > 390)[0]
        if len(voice_indices) == 0:
            return audio_data[:0]
        pad = int(self.sample_rate * 0.12)  # Keep 120ms natural breath padding
        start_idx = max(0, int(voice_indices[0]) - pad)
        end_idx = min(len(audio_data), int(voice_indices[-1]) + pad)
        return audio_data[start_idx:end_idx]

    def stop_bytes(self) -> Optional[bytes]:
        """
        Stop recording immediately, close the hardware stream asynchronously,
        trim dead silence, and return in-memory WAV bytes (zero disk I/O).
        """
        with self._lock:
            if not self.is_recording:
                return None
            self.is_recording = False
            frames = self._frames
            self._frames = []
            stream = self._stream
            self._stream = None

        if stream is not None:
            threading.Thread(
                target=self._close_stream_async, args=(stream,), daemon=True
            ).start()

        if not frames:
            return None

        audio_data = np.concatenate(frames, axis=0)

        # Ignore very short accidental triggers (< 0.22 seconds)
        if len(audio_data) < int(self.sample_rate * 0.22):
            return None

        trimmed = self._trim_silence(audio_data)
        if len(trimmed) < int(self.sample_rate * 0.15):
            return None

        # Guard against faint background hum / key clicks
        rms = float(np.sqrt(np.mean(trimmed.astype(np.float64) ** 2)))
        if rms < 120.0:
            return None

        buf = io.BytesIO()
        wavfile.write(buf, self.sample_rate, trimmed)
        return buf.getvalue()
