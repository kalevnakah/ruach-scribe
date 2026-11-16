import concurrent.futures
import json
import re
import threading
import warnings
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore", category=FutureWarning)
import google.generativeai as genai


FALLBACK_MODELS: List[str] = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-pro-latest",
]


class GeminiTranscriber:
    _lock = threading.Lock()
    _configured_key: Optional[str] = None
    _cached_models: Dict[str, genai.GenerativeModel] = {}
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    @classmethod
    def _ensure_configured(cls, api_key: str) -> None:
        clean_key = api_key.strip()
        with cls._lock:
            if cls._configured_key != clean_key:
                genai.configure(api_key=clean_key)
                cls._configured_key = clean_key
                cls._cached_models.clear()

    @classmethod
    def _get_model(cls, model_name: str, system_prompt: str) -> genai.GenerativeModel:
        cache_key = f"{model_name}::json::{hash(system_prompt)}"
        with cls._lock:
            model = cls._cached_models.get(cache_key)
            if model is None:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.0,
                        candidate_count=1,
                        response_mime_type="application/json",
                    ),
                )
                cls._cached_models[cache_key] = model
            return model

    @classmethod
    def prewarm(cls, api_key: str, model_name: str, system_prompt: str) -> None:
        """Pre-initialize client & model object while the user is speaking."""
        if not api_key or not api_key.strip():
            return
        try:
            cls._ensure_configured(api_key)
            cls._get_model(model_name, system_prompt)
        except Exception:
            pass

    @staticmethod
    def _extract_response_text(response) -> str:
        """
        Safely extract text from GenerateContentResponse without triggering
        ValueError when finish_reason is 1 (STOP) and 0 parts were returned.
        """
        if not response:
            return ""
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return ""
        chunks: List[str] = []
        for cand in candidates:
            content = getattr(cand, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None)
            if not parts:
                continue
            for part in parts:
                t = getattr(part, "text", None)
                if t:
                    chunks.append(t)
        return "".join(chunks).strip()

    @staticmethod
    def _parse_raw_and_cleaned(response_text: str) -> Tuple[str, str]:
        if not response_text:
            return ("", "")

        cleaned_json_str = response_text.strip()
        # Strip accidental markdown code fences if present
        cleaned_json_str = re.sub(r"^```(?:json)?\s*", "", cleaned_json_str)
        cleaned_json_str = re.sub(r"\s*```$", "", cleaned_json_str)

        try:
            parsed = json.loads(cleaned_json_str)
            if isinstance(parsed, dict):
                raw = str(parsed.get("raw", "") or "").strip()
                cleaned = str(parsed.get("cleaned", "") or "").strip()
                return (raw, cleaned)
        except Exception:
            pass

        return (response_text.strip(), response_text.strip())

    @classmethod
    def _call_model(
        cls, model_name: str, system_prompt: str, audio_part: dict
    ) -> Tuple[str, str]:
        model = cls._get_model(model_name, system_prompt)
        user_instruction = (
            f"{system_prompt}\n\n"
            "Process the attached audio and return a JSON object with exactly two string keys:\n"
            "1. \"raw\": The exact verbatim transcription of everything spoken in the audio, "
            "including all filler words ('um', 'uh'), stutters, false starts, and self-correction phrases ('scratch that').\n"
            "2. \"cleaned\": The final edited text following the editing rules above (all fillers removed, "
            "all 'scratch that' / 'no wait' self-corrections applied so retracted mistakes are deleted, and proper punctuation).\n"
            "If the audio is completely silent or has no speech, return {\"raw\": \"\", \"cleaned\": \"\"}."
        )
        response = model.generate_content(
            [audio_part, user_instruction],
            request_options={"timeout": 14},
        )
        raw_response = cls._extract_response_text(response)
        return cls._parse_raw_and_cleaned(raw_response)

    @classmethod
    def transcribe_bytes(
        cls,
        wav_bytes: bytes,
        api_key: str,
        system_prompt: str,
        model_name: str = "gemini-flash-lite-latest",
    ) -> Tuple[str, str]:
        """Returns (raw_text, cleaned_text)."""
        if not api_key or not api_key.strip():
            raise ValueError(
                "Google Gemini API Key is missing. Please configure it in Settings."
            )

        if not wav_bytes or len(wav_bytes) < 100:
            return ("", "")

        cls._ensure_configured(api_key)

        audio_part = {
            "mime_type": "audio/wav",
            "data": wav_bytes,
        }

        candidates: List[str] = [model_name] + [
            m for m in FALLBACK_MODELS if m != model_name
        ]

        last_error = None
        for candidate in candidates:
            future = cls._executor.submit(
                cls._call_model,
                candidate,
                system_prompt,
                audio_part,
            )
            try:
                return future.result(timeout=15.0)
            except concurrent.futures.TimeoutError:
                last_error = TimeoutError(
                    f"Model '{candidate}' timed out after 15 seconds."
                )
                print(f"[Ruach Scribe] {last_error} Trying next model...")
                continue
            except Exception as e:
                last_error = e
                err_lower = str(e).lower()
                if (
                    "404" in err_lower
                    or "not found" in err_lower
                    or "no longer available" in err_lower
                    or "not supported" in err_lower
                    or "deadline" in err_lower
                    or "timeout" in err_lower
                ):
                    print(
                        f"[Ruach Scribe] Model '{candidate}' unavailable ({e}), trying fallback..."
                    )
                    continue
                raise

        if last_error is not None:
            raise last_error
        return ("", "")
