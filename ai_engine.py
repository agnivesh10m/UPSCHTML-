import os
import re
import tempfile
import asyncio
import edge_tts
from google import genai
from google.genai import types
from config import API_KEYS

FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
]

_LIVE_MODEL_CACHE = {}


def _create_gemini_client(api_k: str):
    try:
        return genai.Client(api_key=api_k, http_options={"api_version": "v1beta"})
    except Exception:
        return genai.Client(api_key=api_k)


def _model_priority_rank(model_name: str) -> int:
    low = model_name.lower()
    if "flash" in low and "lite" not in low and "8b" not in low:
        return 0
    if "flash" in low:
        return 1
    if "pro" in low:
        return 2
    return 3


def _get_live_models_for_key(client, api_k: str) -> list:
    if api_k in _LIVE_MODEL_CACHE and _LIVE_MODEL_CACHE[api_k]:
        return _LIVE_MODEL_CACHE[api_k]

    discovered = []
    skip_keywords = (
        "embedding", "imagen", "veo", "aqa", "tts",
        "audio", "robotics", "computer-use", "learnlm"
    )
    try:
        for m in client.models.list():
            raw_name = getattr(m, "name", "") or ""
            m_id = raw_name.replace("models/", "").strip()
            low = m_id.lower()
            if "gemini" not in low:
                continue
            if any(k in low for k in skip_keywords):
                continue

            methods = (
                getattr(m, "supported_actions", None)
                or getattr(m, "supported_generation_methods", None)
            )
            if methods and "generateContent" not in methods:
                continue

            if m_id not in discovered:
                discovered.append(m_id)
    except Exception:
        pass

    discovered.sort(key=_model_priority_rank)

    for fb in FALLBACK_MODELS:
        if fb not in discovered:
            discovered.append(fb)

    _LIVE_MODEL_CACHE[api_k] = discovered
    return discovered


def _invalidate_dead_model(api_k: str, m_name: str, err_msg: str):
    if "404" in err_msg or "NOT_FOUND" in err_msg:
        cached = _LIVE_MODEL_CACHE.get(api_k, [])
        if m_name in cached:
            cached.remove(m_name)


def call_gemini_safely(prompt: str) -> str:
    if not API_KEYS:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    last_err = None
    for api_k in API_KEYS:
        client = _create_gemini_client(api_k)
        models_to_try = list(_get_live_models_for_key(client, api_k))
        for m_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m_name,
                    contents=prompt
                )
                if response and response.text:
                    clean_res = response.text.strip()
                    clean_res = re.sub(r'^(?:\*|\-|\#)?\s*(?:Role|Candidate|Home State|Requirement|Specific Constraint|Draft|Language)[\s\S]*?(?=सचिन|नमस्कार|मान लीजिए|प्रश्न|\n\n)', '', clean_res, flags=re.IGNORECASE)
                    return clean_res.strip()
            except Exception as e:
                last_err = e
                _invalidate_dead_model(api_k, m_name, str(e))
                continue

    raise Exception(f"सभी API Keys और मॉडल्स का कोटा समाप्त है: {last_err}")


def call_gemini_multimodal_inline(prompt: str, file_bytes: bytes, mime_type: str) -> str:
    if not API_KEYS:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    last_err = None
    for api_k in API_KEYS:
        client = _create_gemini_client(api_k)
        models_to_try = list(_get_live_models_for_key(client, api_k))
        for m_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m_name,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
                    ]
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                last_err = e
                _invalidate_dead_model(api_k, m_name, str(e))
                continue
    raise Exception(f"मल्टीमॉडल विश्लेषण में त्रुटि: {last_err}")


def call_gemini_audio_transcribe(file_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    prompt = "इस ऑडियो में बोले गए शब्दों को सुनकर केवल और केवल शुद्ध हिंदी टेक्स्ट में लिखें। कोई अतिरिक्त टिप्पणी या विश्लेषण न जोड़ें।"
    return call_gemini_multimodal_inline(prompt, file_bytes, mime_type)


async def download_audio_stream(text: str) -> bytes:
    temp_path = None
    try:
        clean_text = re.sub(r'[\*\_#`]', '', text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)
        if not clean_text:
            return b""

        communicate = edge_tts.Communicate(clean_text, "hi-IN-MadhurNeural", rate="+0%", pitch="+0Hz")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_path = fp.name

        await communicate.save(temp_path)

        with open(temp_path, "rb") as f:
            audio_bytes = f.read()

        return audio_bytes
    except Exception as e:
        print(f"TTS Audio Generation Error: {e}")
        return b""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
