import os
import io
import re
import time
import edge_tts
from google import genai
from google.genai import types
from config import API_KEYS

KEYS_LIST = [k.strip() for k in API_KEYS if k.strip()] if API_KEYS else [os.environ.get("GEMINI_API_KEY", "").strip()]
current_key_idx = 0

# स्थिर एवं सक्रिय मॉडल
PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-1.5-flash"

def get_genai_client():
    global current_key_idx
    if not KEYS_LIST or not any(KEYS_LIST):
        raise ValueError("कोई भी वैध GEMINI_API_KEY नहीं मिली!")
    active_key = KEYS_LIST[current_key_idx % len(KEYS_LIST)]
    return genai.Client(api_key=active_key)

def switch_key():
    global current_key_idx
    if len(KEYS_LIST) > 1:
        current_key_idx = (current_key_idx + 1) % len(KEYS_LIST)

def call_gemini_safely(prompt: str) -> str:
    """main.py के लिए टेक्स्ट जेनरेशन (503/404 पर रोटेशन व रीट्राई के साथ)"""
    last_err = ""
    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]

    for model_name in models_to_try:
        for _ in range(max(1, len(KEYS_LIST))):
            try:
                client = get_genai_client()
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                last_err = str(e)
                switch_key()
                time.sleep(0.5)

    return f"त्रुटि: {last_err}"

def call_gemini_multimodal_inline(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """कॉपी मूल्यांकन हेतु विज़न मॉडल"""
    last_err = ""
    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]

    for model_name in models_to_try:
        for _ in range(max(1, len(KEYS_LIST))):
            try:
                client = get_genai_client()
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                        prompt
                    ]
                )
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                last_err = str(e)
                switch_key()
                time.sleep(0.5)

    return f"विज़न मूल्यांकन त्रुटि: {last_err}"

def call_gemini_audio_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """ऑडियो उत्तर का ट्रांसक्रिप्शन"""
    prompt = "यह छात्र का बोला हुआ ऑडियो है। इसे सुनकर केवल शुद्ध हिंदी में पूरा ट्रांसक्रिप्ट निकालें। कोई अतिरिक्त टिप्पणी न दें।"
    last_err = ""
    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]

    for model_name in models_to_try:
        for _ in range(max(1, len(KEYS_LIST))):
            try:
                client = get_genai_client()
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                        prompt
                    ]
                )
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                last_err = str(e)
                switch_key()
                time.sleep(0.5)

    return "ऑडियो पढ़ा नहीं जा सका।"

async def download_audio_stream(text: str) -> bytes:
    clean_text = re.sub(r'[*_`#<>]', '', text)[:350]
    output_path = f"temp_stream_{os.getpid()}_{int(time.time() * 1000)}.mp3"
    try:
        communicate = edge_tts.Communicate(clean_text, "hi-IN-MadhurNeural", rate="-2%")
        await communicate.save(output_path)
        with open(output_path, "rb") as f:
            data = f.read()
        return data
    except Exception as e:
        print(f"Edge TTS Error: {e}")
        return b""
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)

async def generate_voice_file(text: str, output_path: str):
    clean_text = re.sub(r'[*_`#<>]', '', text)[:350]
    communicate = edge_tts.Communicate(clean_text, "hi-IN-MadhurNeural", rate="-2%")
    await communicate.save(output_path)
    return output_path

def evaluate_interview_response(candidate_daf: str, question: str, user_answer_text: str, total_q: int, attempt_mode: str) -> str:
    if total_q == 1:
        prompt = f"""
        आप UPSC सिविल सेवा व्यक्तित्व परीक्षण बोर्ड के अध्यक्ष हैं।
        अभ्यर्थी: {attempt_mode} | DAF: {candidate_daf}
        प्रश्न: {question}
        उत्तर: {user_answer_text}
        
        सख्त नियम: कुल 25 अंक।
        - सामान्य: 10-13, अच्छा: 14-17 अंक दें।
        
        प्रारूप:
        🎯 प्राप्तांक: [X] / 25
        🗣 आत्मविश्वास व अभिव्यक्ति:
        ⚖️ प्रशासनिक दृष्टिकोण:
        💡 सुधार सुझाव:
        """
    else:
        prompt = f"""
        आप UPSC सिविल सेवा व्यक्तित्व परीक्षण बोर्ड के अध्यक्ष हैं।
        अभ्यर्थी: {attempt_mode} | DAF: {candidate_daf}
        प्रश्न: {question}
        उत्तर: {user_answer_text}
        
        सख्त नियम: कुल 275 अंक।
        औसत 110-135, अच्छे 145-165, उत्कृष्ट 170-190 अंक दें।
        
        प्रारूप:
        🎯 प्राप्तांक: [X] / 275
        🗣 वाकपटुता व शिष्टाचार:
        ⚖️ प्रशासनिक उपयुक्तता:
        💡 बोर्ड की अंतिम टिप्पणी:
        """
    return call_gemini_safely(prompt)

def evaluate_mains_written_copy(image_bytes: bytes, mode: str, user_caption: str = "") -> str:
    prompt = f"""
    आप संघ लोक सेवा आयोग (UPSC) के 20 वर्षों के वरिष्ठ मुख्य परीक्षक हैं।
    मोड: {mode} | संदर्भ: {user_caption}

    सख्त नियम: 15 अंकों में से औसत को 4.5-5.5, अच्छे को 6-7, उत्कृष्ट को अधिकतम 8 अंक दें।
    प्रारूप:
    🎯 प्राप्तांक: [X] / 15 अंक
    ✍️ प्रस्तुति व लिखावट:
    📊 डायग्राम/मैप विश्लेषण:
    🔍 सकारात्मक पक्ष:
    ⚠️ गंभीर कमियां:
    📚 अनिवार्य वैल्यू-एडिशन (केस लॉ / डेटा):
    """
    return call_gemini_multimodal_inline(prompt, image_bytes, "image/jpeg")

def ask_mentor_ai(query_text: str) -> str:
    prompt = f"आप UPSC मेंटर हैं। इस प्रश्न का सटीक व संक्षिप्त (80 शब्द) प्रशासनिक उत्तर दें: {query_text}"
    return call_gemini_safely(prompt)
