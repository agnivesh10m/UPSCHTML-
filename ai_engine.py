import re
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
        for m_name in ["gemini-3.8-flash", "gemini-3.5-flash-lite"]:
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
    prompt = "इस ऑडियो में उम्मीदवार द्वारा बोले गए शब्दों को ध्यानपूर्वक सुनकर 100% शुद्ध हिंदी में लिखें। केवल बोले गए शब्द लिखें, कोई अन्य टिप्पणी न जोड़ें।"
    return call_gemini_multimodal_inline(prompt, file_bytes, mime_type)

async def download_audio_stream(text: str) -> bytes:
    try:
        clean_text = re.sub(r'[\*\_#`]', '', text).strip().replace("\n", " ")
        communicate = edge_tts.Communicate(clean_text, "hi-IN-SwaraNeural")
        audio_stream = bytearray()
        async with asyncio.timeout(6):
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_stream.extend(chunk["data"])
        return bytes(audio_stream)
    except Exception as e:
        print(f"TTS Stream Handled/Skipped: {e}")
        return b""
      
