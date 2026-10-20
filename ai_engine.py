import os
import re
import tempfile
import asyncio
import edge_tts
from google import genai
from google.genai import types
from config import API_KEYS

MODELS_TEXT = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro"]

def call_gemini_safely(prompt: str) -> str:
    if not API_KEYS:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    last_err = None
    for api_k in API_KEYS:
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
                continue

    raise Exception(f"सभी API Keys और मॉडल्स का कोटा समाप्त है: {last_err}")

def call_gemini_multimodal_inline(prompt: str, file_bytes: bytes, mime_type: str) -> str:
    if not API_KEYS:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    last_err = None
    for api_k in API_KEYS:
        client = genai.Client(api_key=api_k)
        for m_name in ["gemini-3.5-flash-lite", "gemini-3.8-flash"]:
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
