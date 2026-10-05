import os
import edge_tts
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

# Google GenAI क्लाइंट इनिशियलाइज़ेशन
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-2.5-flash"

async def generate_voice_file(text: str, output_path: str):
    """गंभीर पुरुष आवाज़ (Madhur) में Edge-TTS जनरेटर"""
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
        अभ्यर्थी का ऑडियो उत्तर (ट्रांसक्रिप्ट): {user_answer_text}
        
        सख्त नियम:
        यह केवल 1 त्वरित स्थितिजन्य (Situational) प्रश्न का परीक्षण है। कुल अंक 25 हैं।
        - सामान्य उत्तर को 10-13 अंक दें।
        - अच्छे प्रशासनिक दृष्टिकोण वाले उत्तर को 14-17 अंक दें।
        - किसी भी स्थिति में 19 से अधिक अंक न दें।
        
        प्रारूप:
        🎯 <b>प्राप्त अंक:</b> [X] / 25
        🗣️️ <b>आत्मविश्वास व अभिव्यक्ति:</b> [विश्लेषण]
        ⚖️ <b>प्रशासनिक दृष्टिकोण:</b> [तर्कसंगतता]
        💡 <b>सुधार के प्रमुख बिंदु:</b> [सुझाव]
        """
    else:
        prompt = f"""
        आप UPSC सिविल सेवा व्यक्तित्व परीक्षण बोर्ड के आदरणीय अध्यक्ष हैं।
        अभ्यर्थी मोड: {attempt_mode}
        DAF विवरण: {candidate_daf}
        
        पूछा गया प्रश्न: {question}
        अभ्यर्थी का ऑडियो उत्तर (ट्रांसक्रिप्ट): {user_answer_text}
        
        सख्त नियम:
        यह संपूर्ण बोर्ड राउंड का साक्षात्कार है। कुल अंक 275 हैं।
        - औसत उत्तर: 110-135 अंक
        - अच्छा उत्तर: 145-165 अंक
        - असाधारण उत्तर: अधिकतम 170-190 अंक
        
        प्रारूप:
        🎯 <b>प्राप्त अंक:</b> [X] / 275
        🗣️ <b>वाकपटुता व शिष्टाचार:</b> [विश्लेषण]
        ⚖️ <b>प्रशासनिक उपयुक्तता:</b> [विश्लेषण]
        💡 <b>बोर्ड की अंतिम टिप्पणी:</b> [विस्तृत समीक्षा]
        """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )
    return response.text

def evaluate_mains_written_copy(image_bytes: bytes, mode: str, user_caption: str = "") -> str:
    """विज़न आधारित सख्त मेन्स उत्तर मूल्यांकन (मानचित्र, डेटा, सुप्रीम कोर्ट केस सहित)"""
    prompt = f"""
    आप संघ लोक सेवा आयोग (UPSC) के 20 वर्षों के अनुभवी वरिष्ठ मुख्य परीक्षा परीक्षक हैं।
    मोड: {mode} (विगत वर्ष या नया मॉडल प्रश्न)
    छात्र का संदर्भ/कैप्शन: {user_caption}

    सख्त मूल्यांकन नियम (Strict Rules):
    1. मार्किंग मानक: UPSC में 50-55% पर टॉपर्स बनते हैं। 15 अंकों के प्रश्न में:
       - औसत/सामान्य उत्तर: 4.5 से 5.5 अंक
       - अच्छा व संतुलित उत्तर: 6 से 7 अंक
       - उत्कृष्ट उत्तर: अधिकतम 7.5 से 8.5 अंक (10 अंक कभी न दें)
    2. दृश्य विश्लेषण (Vision Inspection):
       - छात्र की लिखावट की पठनीयता (Legibility) की स्पष्ट जांच करें।
       - यदि उत्तर में भारत का मानचित्र, फ्लोचार्ट, वेन आरेख या तालिका बनी है, तो उस पर विशेष टिप्पणी करें और 0.5 से 1 बोनस अंक दें।
    3. अनिवार्य मूल्य संवर्धन (Value-Addition):
       - उत्तर में छूट गए महत्वपूर्ण सुप्रीम कोर्ट केस लॉ, नीति आयोग/आयोग की रिपोर्ट, या आर्थिक सर्वेक्षण का सटीक डेटा अनिवार्य रूप से जोड़ें।

    प्रारूप:
    🎯 <b>प्राप्त अंक:</b> [X] / 15 अंक
    ✍️ <b>प्रस्तुति व लिखावट:</b> [पठनीयता विश्लेषण]
    📊 <b>डायग्राम/मैप विश्लेषण:</b> [उपस्थिति व अंक]
    🔍 <b>सकारात्मक पक्ष:</b> [मजबूत बिंदु]
    ⚠️ <b>गंभीर कमियां (Lacunae):</b> [कमजोरियां]
    📚 <b>अनिवार्य वैल्यू-एडिशन:</b> [सुप्रीम कोर्ट केस / डेटा / समितियां जो उत्तर में होनी चाहिए थीं]
    """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt
        ]
    )
    return response.text

def ask_mentor_ai(query_text: str) -> str:
    """मेंटर से पूछें (/ask) के लिए संक्षिप्त प्रशासनिक उत्तर"""
    prompt = f"आप UPSC मेंटर हैं। इस प्रश्न का अत्यंत सटीक, प्रामाणिक और प्रशासनिक भाषा में संक्षिप्त (अधिकतम 80-100 शब्द) उत्तर दें: {query_text}"
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )
    return response.text
