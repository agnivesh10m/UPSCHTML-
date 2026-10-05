import os
import re
import tempfile
import asyncio
import time
import edge_tts
from google import genai
from google.genai import types
from config import API_KEYS

# सक्रिय व सुरक्षित मॉडल प्राथमिकता
MODELS_TEXT = ["gemini-2.5-flash", "gemini-1.5-flash"]
current_key_idx = 0

def get_active_keys():
    keys = [k.strip() for k in API_KEYS if k.strip()]
    if not keys:
        env_k = os.environ.get("GEMINI_API_KEY", "").strip()
        if env_k:
            keys.append(env_k)
    return keys

def call_gemini_safely(prompt: str) -> str:
    global current_key_idx
    keys = get_active_keys()
    if not keys:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    last_err = None
    for _ in range(len(keys) * 2):
        api_k = keys[current_key_idx % len(keys)]
        client = genai.Client(api_key=api_k)
        for m_name in MODELS_TEXT:
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
                time.sleep(0.5)
                continue
        current_key_idx = (current_key_idx + 1) % len(keys)

    return ""

def call_gemini_multimodal_inline(prompt: str, file_bytes: bytes, mime_type: str) -> str:
    global current_key_idx
    keys = get_active_keys()
    if not keys:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    last_err = None
    for _ in range(len(keys) * 2):
        api_k = keys[current_key_idx % len(keys)]
        client = genai.Client(api_key=api_k)
        for m_name in MODELS_TEXT:
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
                time.sleep(0.5)
                continue
        current_key_idx = (current_key_idx + 1) % len(keys)

    return "मूल्यांकन करने में समस्या आई। कृपया पुनः प्रयास करें।"

def call_gemini_audio_transcribe(file_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    prompt = "इस ऑडियो में उम्मीदवार द्वारा बोले गए शब्दों को ध्यानपूर्वक सुनकर 100% शुद्ध हिंदी में लिखें। केवल बोले गए शब्द लिखें, कोई अन्य टिप्पणी न जोड़ें।"
    res = call_gemini_multimodal_inline(prompt, file_bytes, mime_type)
    return res if res else "ऑडियो पढ़ा नहीं जा सका।"

async def download_audio_stream(text: str) -> bytes:
    """UPSC साक्षात्कार बोर्ड अध्यक्ष एवं मेंटर की गंभीर पुरुष आवाज़ - MadhurNeural"""
    temp_path = None
    try:
        clean_text = re.sub(r'[\*\_#`<>]', '', text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)[:380]
        if not clean_text:
            return b""

        communicate = edge_tts.Communicate(clean_text, "hi-IN-MadhurNeural", rate="-2%", pitch="+0Hz")
        
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
