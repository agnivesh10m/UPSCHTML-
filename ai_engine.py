import os
import io
import edge_tts
from google import genai
from google.genai import types
from config import API_KEYS

# 2 API Keys में से उपलब्ध कीज़ को लोड करें और रोटेशन/फॉलबैक लॉजिक लगाएं
KEYS_LIST = API_KEYS if API_KEYS else [os.environ.get("GEMINI_API_KEY", "").strip()]
current_key_idx = 0

def get_genai_client():
    """सक्रिय API Key के साथ क्लाइंट रिटर्न करता है"""
    global current_key_idx
    if not KEYS_LIST or not any(KEYS_LIST):
        raise ValueError("कोई भी वैध GEMINI_API_KEY नहीं मिली!")
    active_key = KEYS_LIST[current_key_idx % len(KEYS_LIST)]
    return genai.Client(api_key=active_key)

MODEL_NAME = "gemini-2.5-flash"

def switch_key():
    """अगर कोटा या एरर आए तो दूसरी Key पर स्विच करें"""
    global current_key_idx
    if len(KEYS_LIST) > 1:
        current_key_idx = (current_key_idx + 1) % len(KEYS_LIST)

def call_gemini_safely(prompt: str) -> str:
    """main.py के लिए टेक्स्ट जेनरेशन (ऑटो फॉलबैक के साथ)"""
    for _ in range(len(KEYS_LIST) if len(KEYS_LIST) > 0 else 1):
        try:
            client = get_genai_client()
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt
            )
            return resp.text or ""
        except Exception as e:
            switch_key()
            last_err = e
    return f"त्रुटि: {last_err}"

def call_gemini_multimodal_inline(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """main.py के लिए फ़ोटो/पीडीएफ आधारित उत्तर मूल्यांकन"""
    for _ in range(len(KEYS_LIST) if len(KEYS_LIST) > 0 else 1):
        try:
            client = get_genai_client()
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt
                ]
            )
            return resp.text or ""
        except Exception as e:
            switch_key()
            last_err = e
    return f"विज़न मूल्यांकन त्रुटि: {last_err}"

def call_gemini_audio_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """main.py के लिए छात्र के वॉयस मैसेज का ट्रांसक्रिप्शन"""
    prompt = "यह छात्र का बोला हुआ ऑडियो है। इसे सुनकर केवल शुद्ध हिंदी में पूरा ट्रांसक्रिप्ट (लिखा हुआ रूप) निकालें। कोई अतिरिक्त टिप्पणी न दें।"
    for _ in range(len(KEYS_LIST) if len(KEYS_LIST) > 0 else 1):
        try:
            client = get_genai_client()
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    prompt
                ]
            )
            return resp.text or ""
        except Exception as e:
            switch_key()
            last_err = e
    return "ऑडियो पढ़ा नहीं जा सका।"

async def download_audio_stream(text: str) -> bytes:
    """main.py के लिए Edge TTS द्वारा पुरुष आवाज़ में ऑडियो बाइट्स तैयार करना"""
    output_path = f"temp_stream_{os.getpid()}_{int(os.times().system)}.mp3"
    try:
        communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate="-2%")
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
    """सीधे फ़ाइल में ऑडियो सेव करने हेतु फ़ंक्शन"""
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate="-2%")
    await communicate.save(output_path)
    return output_path

def evaluate_interview_response(candidate_daf: str, question: str, user_answer_text: str, total_q: int, attempt_mode: str) -> str:
    """1 प्रश्न होने पर 25 अंक और अधिक होने पर 275 में से वास्तविक व सख्त मार्किंग"""
    if total_q == 1:
        prompt = f"""
        आप UPSC सिविल सेवा व्यक्तित्व परीक्षण बोर्ड के आदरणीय अध्यक्ष हैं।
        अभ्यर्थी मोड: {attempt_mode}
        DAF विवरण: {candidate_daf}
        
        पूछा गया प्रश्न: {question}
        अभ्यर्थी का उत्तर (ट्रांसक्रिप्ट): {user_answer_text}
        
        सख्त नियम:
        यह केवल 1 स्थितिजन्य प्रश्न का परीक्षण है। कुल अंक 25 हैं।
        - सामान्य उत्तर: 10-13 अंक
        - अच्छे प्रशासनिक उत्तर: 14-17 अंक
        - 19 से अधिक अंक न दें।
        
        प्रारूप:
        🎯 <b>प्राप्त अंक:</b> [X] / 25
        🗣 <b>आत्मविश्वास व अभिव्यक्ति:</b>
        ⚖️ <b>प्रशासनिक दृष्टिकोण:</b>
        💡 <b>सुधार के प्रमुख बिंदु:</b>
        """
    else:
        prompt = f"""
        आप UPSC सिविल सेवा व्यक्तित्व परीक्षण बोर्ड के आदरणीय अध्यक्ष हैं।
        अभ्यर्थी मोड: {attempt_mode}
        DAF विवरण: {candidate_daf}
        पूछा गया प्रश्न: {question}
        अभ्यर्थी का उत्तर: {user_answer_text}
        
        सख्त नियम: कुल अंक 275 हैं।
        औसत: 110-135, अच्छे: 145-165, उत्कृष्ट: 170-190 अंक दें।
        
        प्रारूप:
        🎯 <b>प्राप्त अंक:</b> [X] / 275
        🗣️ <b>वाकपटुता व शिष्टाचार:</b>
        ⚖️ <b>प्रशासनिक उपयुक्तता:</b>
        💡 <b>बोर्ड की अंतिम टिप्पणी:</b>
        """
    return call_gemini_safely(prompt)

def evaluate_mains_written_copy(image_bytes: bytes, mode: str, user_caption: str = "") -> str:
    """विज़न आधारित सख्त मेन्स उत्तर मूल्यांकन"""
    prompt = f"""
    आप संघ लोक सेवा आयोग (UPSC) के 20 वर्षों के अनुभवी वरिष्ठ मुख्य परीक्षा परीक्षक हैं।
    मोड: {mode}
    छात्र का संदर्भ: {user_caption}

    सख्त मूल्यांकन नियम:
    1. मार्किंग मानक: 15 अंकों के प्रश्न में:
       - औसत उत्तर: 4.5 से 5.5 अंक
       - अच्छा उत्तर: 6 से 7 अंक
       - उत्कृष्ट उत्तर: अधिकतम 7.5 से 8.5 अंक (10 कभी न दें)
    2. दृश्य विश्लेषण: लिखावट की पठनीयता और बने हुए नक्शे/फ्लोचार्ट की जांच करें। प्रासंगिक होने पर 0.5 से 1 बोनस अंक दें।
    3. अनिवार्य मूल्य संवर्धन: सुप्रीम कोर्ट केस लॉ, नीति आयोग/समिति रिपोर्ट या आर्थिक डेटा अनिवार्य रूप से जोड़ें।

    प्रारूप:
    🎯 <b>प्राप्त अंक:</b> [X] / 15 अंक
    ✍️ <b>प्रस्तुति व लिखावट:</b>
    📊 <b>डायग्राम/मैप विश्लेषण:</b>
    🔍 <b>सकारात्मक पक्ष:</b>
    ⚠️ <b>गंभीर कमियां (Lacunae):</b>
    📚 <b>अनिवार्य वैल्यू-एडिशन:</b>
    """
    return call_gemini_multimodal_inline(prompt, image_bytes, "image/jpeg")

def ask_mentor_ai(query_text: str) -> str:
    """मेंटर से पूछें (/ask) के लिए संक्षिप्त उत्तर"""
    prompt = f"आप UPSC मेंटर हैं। इस प्रश्न का अत्यंत सटीक, प्रामाणिक और प्रशासनिक भाषा में संक्षिप्त (अधिकतम 80-100 शब्द) उत्तर दें: {query_text}"
    return call_gemini_safely(prompt)
