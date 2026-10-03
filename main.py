import os
import re
import time
import asyncio
import io
import json
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import aiohttp
import edge_tts
import psycopg2
from psycopg2.extras import RealDictCursor
from google import genai
from google.genai import types
from pypdf import PdfReader
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ================= CONFIGURATION & CONSTANTS =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")
API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", "")
    ] if k.strip()
]

ADMIN_IDS = [1745425595, 7850454902]
ADMIN_NAMES = {
    1745425595: "SACHIN SHARMA (मुख्य व्यवस्थापक)",
    7850454902: "सह-व्यवस्थापक (Co-Admin)"
}

CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "SACHIN SHARMA"

IST = ZoneInfo("Asia/Kolkata")

def get_ist_now():
    return datetime.now(IST)

# कन्वर्सेशन स्टेट्स
WAITING_CONTACT_MSG = 1
WAITING_BROADCAST_MSG = 2
WAITING_ASK_SESSION = 3

# DAF स्टेप-बाय-स्टेप स्टेट्स
DAF_NAME = 4
DAF_STATE = 5
DAF_COLLEGE = 6
DAF_STATUS = 7
DAF_OPTIONAL_STEP = 8
DAF_ATTEMPT_STEP = 9
DAF_QCOUNT = 10
WAITING_INTERVIEW_VOICE = 11
WAITING_INTERVIEW_DECISION = 12

# उत्तर पुस्तिका 2-स्टेप स्टेट्स
WAITING_QUESTION_TEXT = 13
WAITING_ANSWER_COPY = 14

CONTACT_SESSIONS = {}
USER_QUIZ_SELECTIONS = {}
MAINS_SELECTIONS = {}
CHECK_ANSWER_CACHE = {}
TRENDING_CACHE = {}
INTERVIEW_SESSION = {}
LAST_BROADCAST_DATA = {}

# ================= POSTGRESQL (SUPABASE) DATABASE LAYER =================
def get_db_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL एनवायरनमेंट वैरिएबल में सेट नहीं है।")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_vip INT DEFAULT 0,
            vip_expiry TIMESTAMPTZ,
            joined_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS user_daf (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            name TEXT,
            home_state TEXT,
            college_name TEXT,
            graduation_status TEXT,
            optional_subject TEXT,
            attempt_number TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS daily_archive (
            id BIGSERIAL PRIMARY KEY,
            period_type TEXT,
            reference_date DATE UNIQUE,
            topic TEXT,
            html_content TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()
    c.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database Init Error: {e}")

def register_user(user_id, username, first_name):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, username, first_name, joined_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name;
        """, (user_id, username or "", first_name or ""))
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        print(f"Error registering user: {e}")

def is_authorized(user_id):
    if user_id in ADMIN_IDS:
        return True
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT is_vip, vip_expiry FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row and row[0] == 1:
            if row[1]:
                if get_ist_now() <= row[1].astimezone(IST):
                    return True
            else:
                return True
    except Exception as e:
        print(f"Auth error: {e}")
    return False

def get_user_daf(user_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT name, home_state, college_name, graduation_status, optional_subject, attempt_number FROM user_daf WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        return row
    except Exception:
        return None

def save_user_daf(user_id, name, home_state, college, status, opt_sub, attempt):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO user_daf (user_id, name, home_state, college_name, graduation_status, optional_subject, attempt_number, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                home_state = EXCLUDED.home_state,
                college_name = EXCLUDED.college_name,
                graduation_status = EXCLUDED.graduation_status,
                optional_subject = EXCLUDED.optional_subject,
                attempt_number = EXCLUDED.attempt_number,
                updated_at = NOW();
        """, (user_id, name, home_state, college, status, opt_sub, attempt))
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        print(f"Error saving DAF: {e}")

def get_user_full_info(user_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry, joined_at FROM users WHERE user_id = %s", (user_id,))
        user_row = c.fetchone()
        if not user_row:
            c.close()
            conn.close()
            return None, None
        c.execute("SELECT name, home_state, college_name, graduation_status, optional_subject, attempt_number, updated_at FROM user_daf WHERE user_id = %s", (user_id,))
        daf_row = c.fetchone()
        c.close()
        conn.close()
        return user_row, daf_row
    except Exception:
        return None, None

def save_to_archive(period, topic, html_content, ref_date=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        d_val = ref_date if ref_date else get_ist_now().date()
        c.execute("""
            INSERT INTO daily_archive (period_type, reference_date, topic, html_content, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (reference_date) DO UPDATE SET
                topic = EXCLUDED.topic,
                html_content = EXCLUDED.html_content,
                created_at = NOW();
        """, (period, d_val, topic, html_content))
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        print(f"Error archiving: {e}")

def get_archive_by_date(date_str):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT topic, html_content FROM daily_archive WHERE reference_date = %s LIMIT 1", (date_str,))
        row = c.fetchone()
        c.close()
        conn.close()
        return row
    except Exception:
        return None

def get_all_user_ids():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        rows = c.fetchall()
        c.close()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def get_all_users_detailed():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry FROM users ORDER BY joined_at DESC")
        rows = c.fetchall()
        c.close()
        conn.close()
        return rows
    except Exception:
        return []

# ================= AI ENGINES (GEMINI 3.8 / 3.5 / 3.1) =================
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
    clean_text = re.sub(r'[\*\_#`]', '', text).strip().replace("\n", " ")
    communicate = edge_tts.Communicate(clean_text, "hi-IN-SwaraNeural")
    audio_stream = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_stream.extend(chunk["data"])
    return bytes(audio_stream)

# ================= ROBUST TABLE & VISUAL BUILDER =================
def create_standalone_vector_map(place_name: str) -> str:
    return f"""
    <figure class="img-figure">
      <svg width="100%" height="220" viewBox="0 0 800 220" xmlns="http://www.w3.org/2000/svg" style="background: linear-gradient(135deg, #f8fafc, #f1f5f9); border-radius: 8px;">
        <rect width="100%" height="100%" fill="none" stroke="#0284c7" stroke-width="1.5" rx="8"/>
        <g opacity="0.15">
          <line x1="0" y1="55" x2="800" y2="55" stroke="#0284c7" stroke-width="1"/>
          <line x1="0" y1="110" x2="800" y2="110" stroke="#0284c7" stroke-width="1"/>
          <line x1="0" y1="165" x2="800" y2="165" stroke="#0284c7" stroke-width="1"/>
          <line x1="200" y1="0" x2="200" y2="220" stroke="#0284c7" stroke-width="1"/>
          <line x1="400" y1="0" x2="400" y2="220" stroke="#0284c7" stroke-width="1"/>
          <line x1="600" y1="0" x2="600" y2="220" stroke="#0284c7" stroke-width="1"/>
        </g>
        <circle cx="740" cy="45" r="22" fill="#ffffff" stroke="#0284c7" stroke-width="1.5"/>
        <path d="M 740 27 L 745 45 L 740 42 L 735 45 Z" fill="#ef4444"/>
        <text x="740" y="24" font-size="10" font-weight="bold" fill="#ef4444" text-anchor="middle">N</text>
        <rect x="50" y="35" width="300" height="150" rx="8" fill="#ffffff" stroke="#e2e8f0" stroke-width="1.5"/>
        <text x="70" y="70" font-family="'Hind', sans-serif" font-size="16" font-weight="bold" fill="#0369a1">📍 {place_name}</text>
        <text x="70" y="102" font-family="'Hind', sans-serif" font-size="13" fill="#475569">• रणनीतिक अवस्थिति एवं जलग्रहण क्षेत्र</text>
        <text x="70" y="128" font-family="'Hind', sans-serif" font-size="13" fill="#475569">• पारिस्थितिकी एवं संरक्षित हॉटस्पॉट</text>
        <text x="70" y="154" font-family="'Hind', sans-serif" font-size="12" font-weight="bold" fill="#059669">✓ UPSC मैपिंग एवं प्रीलिम्स संदर्भ</text>
        <circle cx="560" cy="110" r="50" fill="#e0f2fe" stroke="#0284c7" stroke-width="2"/>
        <circle cx="560" cy="110" r="8" fill="#ef4444"/>
        <text x="560" y="175" font-family="'Hind', sans-serif" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">प्रमुख स्थल नोड</text>
      </svg>
      <figcaption>🗺️ भौगोलिक एवं रणनीतिक मानचित्र: {place_name}</figcaption>
    </figure>
    """

def markdown_tables_to_html(text: str) -> str:
    lines = text.split("\n")
    in_table = False
    html_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r'^:?-+:?$', c) for c in cells):
                continue
            
            if not in_table:
                in_table = True
                html_lines.append('<div class="table-box"><table><thead><tr>')
                for h in cells:
                    html_lines.append(f'<th>{h}</th>')
                html_lines.append('</tr></thead><tbody>')
            else:
                html_lines.append('<tr>')
                for c in cells:
                    html_lines.append(f'<td>{c}</td>')
                html_lines.append('</tr>')
        else:
            if in_table:
                html_lines.append('</tbody></table></div>')
                in_table = False
            html_lines.append(line)
            
    if in_table:
        html_lines.append('</tbody></table></div>')
    return "\n".join(html_lines)

def clean_all_markdown_and_fix_content(raw_text: str) -> str:
    text = raw_text.strip()
    text = markdown_tables_to_html(text)

    text = re.sub(r'```(?:xml|svg|html)?[\s\S]*?```', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```', '', text)
    text = re.sub(r'<figure[^>]*>[\s\S]*?<\/figure>', '', text, flags=re.IGNORECASE)

    text = re.sub(r'###\s*(.*)', r'<h4 class="sub-title">\1</h4>', text)
    text = re.sub(r'##\s*(.*)', r'<h3 class="section-title">\1</h3>', text)
    text = re.sub(r'#\s*(.*)', r'<h2 class="section-title">\1</h2>', text)

    text = re.sub(r'\*\*भूमिका\s*[:\-]?\*\*\s*(.*)', r'<div class="mains-point"><span class="point-badge-intro">📌 भूमिका:</span> <p class="para">\1</p></div>', text)
    text = re.sub(r'\*\*मुख्य\s*विश्लेषणात्मक\s*बिंदु\s*[:\-]?\*\*', r'<div class="point-badge-body">📊 मुख्य विश्लेषणात्मक आयाम:</div>', text)
    text = re.sub(r'\*\*आगे\s*की\s*राह\s*\(Way\s*Forward\)\s*[:\-]?\*\*\s*(.*)', r'<div class="mains-point"><span class="point-badge-wf">🚀 आगे की राह (Way Forward):</span> <p class="para">\1</p></div>', text)
    text = re.sub(r'\*\*संतुलित\s*निष्कर्ष\s*[:\-]?\*\*\s*(.*)', r'<div class="mains-point"><span class="point-badge-conc">⚖️ संतुलित प्रशासनिक निष्कर्ष:</span> <p class="para">\1</p></div>', text)

    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'^[•\-\*]\s*(.*)', r'<li class="list-item">\1</li>', text, flags=re.MULTILINE)

    key_locations = ["कूनो", "गांधी सागर", "मन्नार की खाड़ी", "कच्छ का रण", "होर्मुज़", "लाल सागर", "अंडमान", "पश्चिमी घाट", "लद्दाख", "ताइवान", "चाबहार"]
    for loc in key_locations:
        if loc in text:
            vector_card = create_standalone_vector_map(loc)
            text += f"\n<div class='map-section'><h4>🗺️ भौगोलिक एवं रणनीतिक मैपिंग</h4><p><i>(नोट: संबंधित विषय का भौगोलिक परिदृश्य नीचे प्रदर्शित है)</i></p>{vector_card}</div>"
            break

    return text

# ================= MASTER STANDALONE COMPILATION HTML (50% WATERMARK) =================
def build_standalone_master_html(topic: str, raw_content: str, date_str: str = "", is_trending: bool = False) -> str:
    cleaned_body = clean_all_markdown_and_fix_content(raw_content)
    display_date = date_str if date_str else get_ist_now().strftime("%d %B %Y")

    nav_links = '<a href="#sec-overview">📋 सत्र सार</a>\n'
    soup = BeautifulSoup(cleaned_body, 'html.parser')
    sec_idx = 1

    for tag in soup.find_all(['h2', 'h3']):
        title_text = tag.get_text().strip()
        if len(title_text) > 3 and not tag.get('id'):
            sec_id = f"custom-sec-{sec_idx}"
            tag['id'] = sec_id
            clean_tab_name = re.sub(r'^(?:खंड|खण्ड|भाग|\d+|[:\.\-\s])+', '', title_text).strip()
            clean_tab_name = re.sub(r'[📌🎯⚡📖💡🗳⚖️🔍📝🛣️❄🌏📰🌍🌱🔬💰🔑📚🔸|━─—_:-]', '', clean_tab_name).strip()
            if not clean_tab_name:
                clean_tab_name = f"विषय {sec_idx}"
            if len(clean_tab_name) > 20:
                clean_tab_name = clean_tab_name[:18] + ".."
            nav_links += f'<a href="#{sec_id}">{clean_tab_name}</a>\n'
            sec_idx += 1

    final_body = str(soup)
    overview_title = "🧭 ट्रेंडिंग समसामयिक विश्लेषण" if is_trending else "📌 सत्र विहंगावलोकन"

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} | {AUTHOR_NAME}</title>
<link href="[https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap](https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap)" rel="stylesheet">
<style>
:root {{
  --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0;
  --accent: #0284c7; --accent-dark: #0369a1; --saffron: #f59e0b; --green: #10b981;
  --tag-bg: #e0f2fe; --tag-text: #0369a1; --shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg); color: var(--text); font-family: 'Hind', 'Noto Sans Devanagari', sans-serif;
  line-height: 1.8; padding-bottom: 80px;
}}
@media print {{
  body::before {{
    content: "SACHIN SHARMA | @UPSCHTML";
    position: fixed; top: 40%; left: 5%; width: 90%; text-align: center;
    font-size: 5rem; font-weight: 900; color: rgba(0, 0, 0, 0.50) !important;
    opacity: 0.50 !important; transform: rotate(-35deg); z-index: 9999; pointer-events: none; letter-spacing: 8px;
  }}
  .controls, nav.dashboard, #telegramBtn, .print-btn, .theme-btn {{ display: none !important; }}
  .news-card {{ box-shadow: none !important; border: 1px solid #ccc !important; page-break-inside: avoid; }}
}}
.top-header {{
  background: linear-gradient(135deg, #071529, #0284c7 65%, #0369a1);
  color: #fff; padding: 26px 16px 20px; text-align: center; border-bottom: 4px solid var(--saffron);
}}
.top-header h1 {{ font-size: 1.65rem; margin-bottom: 6px; font-weight: 700; }}
.author-pill {{
  display: inline-block; margin-top: 4px; background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.35); padding: 5px 18px; border-radius: 30px;
  font-weight: 600; font-size: 0.92rem;
}}
.controls {{ display: flex; justify-content: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
.controls input {{ width: min(340px, 85vw); padding: 9px 14px; border-radius: 20px; border: none; outline: none; font-size: 0.9rem; }}
.controls button {{
  padding: 8px 18px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.2); color: #fff; font-weight: 600; cursor: pointer;
}}
nav.dashboard {{
  position: sticky; top: 0; z-index: 50; background: var(--card); border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow); overflow-x: auto; white-space: nowrap; padding: 10px 14px;
}}
nav.dashboard .nav-wrap {{ display: flex; gap: 8px; max-width: 1000px; margin: 0 auto; }}
nav.dashboard a {{
  display: inline-block; padding: 7px 14px; background: var(--tag-bg); color: var(--tag-text);
  border-radius: 16px; font-size: 0.86rem; font-weight: 600; text-decoration: none; flex: none;
}}
nav.dashboard a:hover {{ background: var(--accent); color: #fff; }}
.wrap {{ max-width: 1000px; margin: 22px auto; padding: 0 16px; width: 100%; }}
.overview-box {{
  background: var(--tag-bg); border: 2px solid var(--accent); border-radius: 12px;
  padding: 18px; margin-bottom: 22px; box-shadow: var(--shadow);
}}
.overview-title {{ color: var(--accent-dark); font-size: 1.2rem; font-weight: 700; margin-bottom: 8px; }}
.news-card {{
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px; margin-bottom: 24px; box-shadow: var(--shadow); width: 100%; scroll-margin-top: 70px;
}}
.section-title {{
  color: var(--accent); font-size: 1.3rem; margin-bottom: 14px;
  border-left: 5px solid var(--saffron); padding-left: 12px; font-weight: 700;
}}
.table-box {{ overflow-x: auto; margin: 16px 0; width: 100%; border-radius: 8px; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ background: var(--accent); color: #fff; padding: 11px 13px; font-size: 0.92rem; font-weight: 600; }}
td {{ padding: 11px 13px; border-bottom: 1px solid var(--border); font-size: 0.92rem; vertical-align: top; }}
.img-figure {{
  margin: 18px 0; text-align: center; background: #ffffff; padding: 10px;
  border-radius: 10px; border: 1px solid #bae6fd; box-shadow: var(--shadow);
}}
#telegramBtn {{
  position: fixed; bottom: 18px; right: 18px; z-index: 90; background: #229ED9; color: #fff;
  border: none; border-radius: 30px; padding: 11px 20px; font-weight: 700; cursor: pointer; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25); font-size: 0.88rem;
}}
footer {{ background: #071529; color: #dbe6f2; text-align: center; padding: 26px 16px; margin-top: 36px; font-size: 0.88rem; }}
footer a {{ color: #8bc4ef; font-weight: 700; text-decoration: none; }}
</style>
</head>
<body data-theme="light">
<header class="top-header">
  <h1>🇮🇳 {topic}</h1>
  <div class="author-pill">✍️ संकलन: {AUTHOR_NAME} | {CHANNEL_NAME}</div>
</header>
<nav class="dashboard"><div class="nav-wrap">{nav_links}</div></nav>
<main class="wrap" id="mainContent">
  <section id="sec-overview" class="overview-box">
    <div class="overview-title">📌 {overview_title}</div>
    <p class="para"><strong>📅 संदर्भ काल:</strong> {display_date} (IST)</p>
    <p class="para"><strong>🎯 संकलन आयाम:</strong> 360° समग्र विश्लेषण, 2-कॉलम सारणी, मानक भौगोलिक मानचित्र एवं मुख्य परीक्षा उत्तर-लेखन फ्रेमवर्क।</p>
    <p class="para"><strong>📰 अधिकृत स्रोत:</strong> The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS, Sanskriti IAS।</p>
  </section>
  <div class="news-card">{final_body}</div>
</main>
<button id="telegramBtn" onclick="window.open('{CHANNEL_LINK}','_blank')">📲 TELEGRAM — {CHANNEL_NAME}</button>
<footer>
  <div><b>UPSC CIVIL SERVICES EXAMINATION COMPREHENSIVE STUDY DESK</b></div>
  <div style="margin-top:6px;">संकलन एवं प्रस्तुति: <b>{AUTHOR_NAME}</b> | टेलीग्राम: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
  <div style="margin-top:4px; font-size:0.8rem; color:#94a3b8;">कॉपीराइट सुरक्षित © {get_ist_now().strftime('%Y')} | केवल शैक्षणिक एवं स्व-अध्ययन हेतु</div>
</footer>
</body>
</html>"""

# ================= VISION IAS STYLE INTERACTIVE TEST ENGINE =================
def build_vision_ias_interactive_portal(subject_title: str, test_id: str, q_count: int, questions_json: str) -> str:
    duration_min = 60 if q_count == 50 else (120 if q_count == 100 else 180)
    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>UPSC CSE - {subject_title} | {AUTHOR_NAME}</title>
<style>
:root {{
    --home-bg-top: #0f172a; --home-bg-bot: #020617; --home-card: #1e293b; --home-box: #334155;      
    --home-text-accent: #facc15; --home-btn: #facc15; --bg-dark: #0b0f19; --card-dark: #151b2b;     
    --primary: #facc15; --secondary: #3b82f6; --text-main: #f8fafc; --text-muted: #94a3b8;
    --border-color: #1e293b; --option-bg: #0b0f19; --correct: #10b981; --wrong: #ef4444; --skipped: #3b82f6; --current: #facc15;       
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; -webkit-tap-highlight-color: transparent; }}
body {{ background-color: var(--bg-dark); color: var(--text-main); display: flex; justify-content: center; height: 100vh; height: 100dvh; overflow: hidden; }}
.app-container {{ width: 100%; max-width: 520px; background-color: var(--bg-dark); display: flex; flex-direction: column; position: relative; height: 100%; border: none; }}
.hidden {{ display: none !important; }}
#print-container {{ display: none; }}
#home-screen {{ background: linear-gradient(180deg, var(--home-bg-top) 0%, var(--home-bg-bot) 100%); padding: 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100%; overflow-y: auto; }}
.brand-header {{ text-align: center; margin-bottom: 20px; width: 100%; }}
.brand-header h1 {{ color: var(--home-text-accent); font-size: 26px; font-weight: 900; letter-spacing: 1px; margin-bottom: 4px; text-shadow: 0 2px 10px rgba(250, 204, 21, 0.4); }}
.brand-header p {{ color: #e2e8f0; font-size: 11px; letter-spacing: 3px; font-weight: 600; text-transform: uppercase; }}
.test-info-card {{ background: var(--home-card); padding: 22px 18px; border-radius: 16px; width: 100%; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid rgba(250, 204, 21, 0.2); }}
.test-title {{ font-size: 17px; font-weight: bold; text-align: center; margin-bottom: 4px; color: white; }}
.test-subtitle {{ font-size: 12px; color: #cbd5e1; text-align: center; margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px dashed rgba(255,255,255,0.3); }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 18px; }}
.info-box {{ background: var(--home-box); padding: 10px 8px; border-radius: 10px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }}
.info-val {{ font-size: 18px; font-weight: 800; color: var(--home-text-accent); margin-bottom: 2px; }}
.info-lbl {{ font-size: 10px; color: white; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }}
.name-input-container {{ margin-bottom: 18px; }}
.name-input {{ width: 100%; padding: 13px 15px; border-radius: 10px; border: 2px solid var(--home-text-accent); background: #0b0f19; color: white; font-size: 15px; font-weight: bold; text-align: center; outline: none; }}
.start-btn {{ width: 100%; padding: 15px; border-radius: 12px; background: var(--home-btn); color: #0f172a; font-size: 16px; font-weight: bold; border: none; cursor: pointer; box-shadow: 0 4px 15px rgba(250, 204, 21, 0.4); text-transform: uppercase; letter-spacing: 1px; }}
#test-screen {{ display: flex; flex-direction: column; height: 100%; background: var(--bg-dark); }}
.test-header {{ flex-shrink: 0; background: var(--card-dark); border-bottom: 1px solid var(--border-color); padding: 10px 15px; }}
.header-row {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.head-left h2 {{ font-size: 12px; color: var(--primary); font-weight: 800; text-transform: uppercase; }}
.head-left p {{ font-size: 11px; color: var(--text-muted); font-weight: 600; }}
.timer-box {{ font-size: 13px; font-weight: bold; color: #0b0f19; background: var(--primary); padding: 2px 8px; border-radius: 4px; display: inline-block; }}
.progress-bar-container {{ height: 3px; background: var(--border-color); width: 100%; }}
.progress-bar {{ height: 100%; background: var(--primary); width: 0%; transition: width 0.3s ease; }}
.sub-header {{ display: flex; justify-content: space-between; padding: 8px 15px; font-size: 12px; font-weight: 600; background: var(--bg-dark); color: var(--text-muted); border-bottom: 1px solid var(--border-color); }}
.question-area {{ flex: 1; padding: 12px 15px; overflow-y: auto; background: var(--bg-dark); padding-bottom: 20px; }}
.q-card {{ background: var(--card-dark); padding: 15px 12px; border-radius: 10px; border: 1px solid var(--border-color); margin-bottom: 10px; }}
.q-header-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
.q-tag {{ background: rgba(250, 204, 21, 0.15); color: var(--primary); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
.q-topic-tag {{ background: var(--primary); color: #000; padding: 4px 10px; border-radius: 15px; font-size: 11px; font-weight: 800; }}
.q-text {{ font-size: 14.5px; line-height: 1.5; font-weight: 500; margin-bottom: 15px; color: #fff; }}
.options-list {{ display: flex; flex-direction: column; gap: 8px; }}
.option {{ display: flex; align-items: center; padding: 10px 12px; background: var(--option-bg); border: 1px solid var(--border-color); border-radius: 8px; cursor: pointer; }}
.option.selected {{ border-color: var(--primary); background: rgba(250, 204, 21, 0.12); }}
.opt-letter {{ width: 22px; height: 22px; border-radius: 4px; background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 10px; color: var(--text-muted); flex-shrink: 0; }}
.option.selected .opt-letter {{ background: var(--primary); color: #000; }}
.opt-text {{ font-size: 13.5px; line-height: 1.3; color: #f1f5f9; }}
.bottom-actions-container {{ flex-shrink: 0; background: var(--card-dark); padding: 8px 12px; border-top: 1px solid var(--border-color); }}
.nav-buttons-row {{ display: flex; justify-content: space-between; gap: 6px; margin-bottom: 6px; }}
.nav-btn {{ flex: 1; height: 36px; padding: 0; border-radius: 6px; font-size: 12px; font-weight: 700; border: none; background: var(--bg-dark); color: var(--text-main); cursor: pointer; display: flex; align-items: center; justify-content: center; }}
.nav-btn.icon-btn {{ flex: 0.4; font-size: 16px; }}
.big-green-btn {{ width: 100% !important; height: 40px !important; background: #10b981 !important; color: white !important; border-radius: 8px !important; font-weight: bold !important; font-size: 14px !important; border: none !important; cursor: pointer !important; text-transform: uppercase !important; display: flex; align-items: center; justify-content: center; }}
.palette-modal {{ position: absolute; bottom: 0; left: 0; width: 100%; max-height: 80vh; background: var(--card-dark); border-top-left-radius: 20px; border-top-right-radius: 20px; padding: 18px; transform: translateY(100%); transition: transform 0.3s ease; z-index: 100; display: flex; flex-direction: column; border-top: 1px solid var(--primary); }}
.palette-modal.open {{ transform: translateY(0); }}
.palette-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }}
.q-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; overflow-y: auto; padding-bottom: 12px; flex: 1; }}
.q-grid-btn {{ width: 100%; aspect-ratio: 1; border-radius: 8px; border: none; background: var(--bg-dark); color: var(--text-main); font-weight: bold; font-size: 13px; cursor: pointer; }}
.status-answered {{ background: var(--correct) !important; color: white !important; }}
.status-current {{ background: var(--current) !important; color: #000 !important; }}
#result-screen {{ background: var(--bg-dark); color: var(--text-main); height: 100%; overflow-y: auto; padding: 20px 15px; flex: 1; }}
.res-header {{ text-align: center; margin-bottom: 15px; }}
.res-header h2 {{ font-size: 19px; color: var(--primary); }}
.score-card-compact {{ background: linear-gradient(135deg, var(--card-dark), var(--bg-dark)); border: 1px solid var(--primary); padding: 18px; border-radius: 12px; text-align: center; margin-bottom: 15px; }}
.score-card-compact h1 {{ font-size: 36px; color: #fff; }}
.res-grid-compact {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 18px; }}
.res-box-compact {{ background: var(--card-dark); padding: 10px 5px; border-radius: 8px; text-align: center; border: 1px solid var(--border-color); }}
.res-box-compact .val {{ font-size: 16px; font-weight: 900; margin-bottom: 2px; color: #fff; }}
.res-box-compact .lbl {{ font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
.btn-row {{ display: flex; gap: 10px; margin-bottom: 20px; }}
.r-btn-small {{ flex: 1; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: bold; cursor: pointer; border: none; text-align: center; }}
.r-btn-small.print-btn {{ background: var(--secondary); color: #fff; }}
.review-box {{ background: var(--card-dark); padding: 14px; border-radius: 10px; margin-bottom: 12px; border: 1px solid var(--border-color); }}
.review-q {{ font-size: 13.5px; font-weight: 600; margin-bottom: 10px; color: #fff; line-height: 1.4; }}
.ans-row {{ display: flex; gap: 8px; font-size: 12.5px; margin-bottom: 4px; }}
.ans-lbl {{ color: var(--text-muted); width: 85px; flex-shrink: 0; font-weight: bold; }}
.solution-box {{ background: rgba(250, 204, 21, 0.05); border-left: 4px solid var(--primary); border-radius: 4px; padding: 10px; margin-top: 10px; font-size: 12.5px; color: #e2e8f0; line-height: 1.5; }}
.solution-title {{ font-weight: bold; margin-bottom: 4px; color: var(--primary); font-size: 11px; text-transform: uppercase; }}
@media print {{
    @page {{ size: A4 portrait; margin: 12mm; }}
    body {{ background: white !important; color: black !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .app-container {{ display: none !important; }} 
    #print-container {{ display: block !important; width: 100%; position: relative; }}
    .watermark-print {{
        position: fixed; top: 40%; left: 5%; width: 90%; text-align: center;
        font-size: 5rem; font-weight: 900; color: rgba(0, 0, 0, 0.50) !important;
        opacity: 0.50 !important; transform: rotate(-35deg); z-index: 9999; pointer-events: none;
    }}
    .print-header-box {{ border: 2px solid #000; padding: 14px 18px; border-radius: 8px; margin-bottom: 18px; text-align: center; }}
    .print-q-box {{ margin-bottom: 15px !important; padding-bottom: 10px; border-bottom: 1px solid #cbd5e1; page-break-inside: avoid !important; }}
    .print-q-head {{ display: flex; justify-content: space-between; margin-bottom: 5px; font-weight: bold; }}
    .print-q-topic {{ background: #facc15 !important; color: #000 !important; padding: 2px 6px; font-size: 10px; border-radius: 12px; font-weight: 800; }}
    .print-q-text {{ font-size: 13px; margin-bottom: 6px; font-weight: 600; color: #000 !important; }}
    .print-ans-row {{ font-size: 11.5px; margin-bottom: 3px; }}
    .print-sol-box {{ background: #f8fafc !important; border-left: 4px solid #facc15 !important; padding: 8px !important; margin-top: 5px; font-size: 11.5px; color: #1e293b !important; }}
}}
</style>
</head>
<body>
    <div id="print-container">
        <div class="watermark-print">SACHIN SHARMA | @UPSCHTML</div>
        <div id="print-content"></div>
    </div>
    <div class="app-container" id="main-app">
        <div id="home-screen">
            <div class="brand-header">
                <h1>UPSC ONLINE TEST DESK</h1>
                <p>PORTAL — {AUTHOR_NAME}</p>
            </div>
            <div class="test-info-card">
                <div class="test-title">{subject_title}</div>
                <div class="test-subtitle">Test Series ID: {test_id}</div>
                <div class="grid-2">
                    <div class="info-box"><div class="info-val">{q_count}</div><div class="info-lbl">Questions</div></div>
                    <div class="info-box"><div class="info-val">{duration_min} Min</div><div class="info-lbl">Duration</div></div>
                    <div class="info-box"><div class="info-val" style="color: var(--correct);">+2.00</div><div class="info-lbl">Marks/Qn</div></div>
                    <div class="info-box"><div class="info-val" style="color: var(--wrong);">-0.66</div><div class="info-lbl">Negative</div></div>
                </div>
                <div class="name-input-container">
                    <input type="text" id="candidate-name" class="name-input" placeholder="यहाँ अपना नाम लिखें..." autocomplete="off">
                </div>
                <button class="start-btn" onclick="startTest()">▶|| परीक्षा शुरू करें (Start Test)</button>
            </div>
            <div style="text-align:center; font-size:11px; color:var(--text-muted); margin-top:20px;">© {AUTHOR_NAME} - ALL RIGHTS RESERVED.</div>
        </div>

        <div id="test-screen" class="hidden">
            <div class="test-header">
                <div class="header-row">
                    <div class="head-left">
                        <h2>UPSC TEST — {test_id}</h2>
                        <p>+2.00/Qn | -0.66 Neg</p>
                    </div>
                    <div class="head-right">
                        <div class="timer-box" id="timer-display">{duration_min}:00</div>
                    </div>
                </div>
            </div>
            <div class="progress-bar-container"><div class="progress-bar" id="progress-bar"></div></div>
            <div class="sub-header">
                <span id="q-counter">प्रश्न 1 / {q_count}</span>
                <span id="answered-counter">उत्तर दिए: 0</span>
            </div>
            <div class="question-area">
                <div class="q-card">
                    <div class="q-header-row">
                        <div class="q-tag" id="q-num-display">Q. 1 / {q_count}</div>
                        <div class="q-topic-tag" id="q-topic-display">{subject_title}</div>
                    </div>
                    <div class="q-text" id="q-text">लोड हो रहा है...</div>
                    <div class="options-list" id="options-container"></div>
                </div>
            </div>
            <div class="bottom-actions-container">
                <div class="nav-buttons-row">
                    <button class="nav-btn" onclick="prevQuestion()">◀ Prev</button>
                    <button class="nav-btn" onclick="markSkipped()">Skip</button>
                    <button class="nav-btn icon-btn" onclick="togglePalette()">▦</button>
                    <button class="nav-btn" id="next-btn" onclick="nextQuestion()" style="background: var(--primary); color: #000;">Next ▶</button>
                </div>
                <button class="big-green-btn" onclick="submitTest()">✅ Submit Exam</button>
            </div>
        </div>

        <div class="overlay" id="overlay" onclick="togglePalette()" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); display:none; z-index:50;"></div>
        <div class="palette-modal" id="palette-modal">
            <div class="palette-header">
                <h3 style="color:#fff; font-size:15px;">Question Palette</h3>
                <button onclick="togglePalette()" style="background:transparent; border:none; color:#fff; font-size:18px;">✕</button>
            </div>
            <div class="q-grid" id="palette-grid"></div>
            <div style="margin-top:10px;"><button class="big-green-btn" onclick="submitTest()">✅ Final Submit</button></div>
        </div>

        <div id="result-screen" class="hidden">
            <div class="res-header">
                <h2>UPSC EXAM RESULT SUMMARY</h2>
                <p><span id="res-display-name"></span> | {subject_title}</p>
            </div>
            <div class="score-card-compact">
                <h1 id="final-score">0.00</h1>
                <p>Total Marks</p>
            </div>
            <div class="res-grid-compact">
                <div class="res-box-compact"><div class="val" id="stat-correct" style="color: var(--correct);">0</div><div class="lbl">सही</div></div>
                <div class="res-box-compact"><div class="val" id="stat-wrong" style="color: var(--wrong);">0</div><div class="lbl">गलत</div></div>
                <div class="res-box-compact"><div class="val" id="stat-skipped" style="color: var(--skipped);">0</div><div class="lbl">छूटे</div></div>
                <div class="res-box-compact"><div class="val" id="stat-accuracy" style="color: var(--primary);">0%</div><div class="lbl">सटीकता</div></div>
                <div class="res-box-compact"><div class="val" id="stat-time" style="color: var(--primary);">0m 0s</div><div class="lbl">समय</div></div>
                <div class="res-box-compact"><div class="val" id="stat-avg-time" style="color: var(--primary);">0s</div><div class="lbl">औसत/प्रश्न</div></div>
            </div>
            <div class="btn-row">
                <button class="r-btn-small print-btn" onclick="window.print()">🖨️ Print PDF Result (50% Watermark)</button>
            </div>
            <h3 style="font-size: 14px; margin-bottom: 12px; color: var(--primary);">📝 विस्तृत व्याख्या एवं समाधान</h3>
            <div id="review-container"></div>
        </div>
    </div>

    <script>
        const questions = {questions_json};
        const TOTAL_Q = questions.length;
        const MARKS_PER_CORRECT = 2.00;
        const NEGATIVE_MARK = 0.66;
        const TIME_MINUTES = {duration_min};

        let totalSeconds = TIME_MINUTES * 60;
        let timerInterval;
        let currentQIndex = 0;
        let userAnswers = new Array(TOTAL_Q).fill(null);
        let studentName = "";

        function startTest() {{
            studentName = document.getElementById('candidate-name').value.trim();
            if(!studentName) {{ alert("कृपया अपना नाम दर्ज करें!"); return; }}
            document.getElementById('res-display-name').innerText = studentName;
            document.getElementById('home-screen').classList.add('hidden');
            document.getElementById('test-screen').classList.remove('hidden');
            initPalette();
            loadQuestion(0);
            timerInterval = setInterval(() => {{
                totalSeconds--;
                let mins = Math.floor(totalSeconds / 60);
                let secs = totalSeconds % 60;
                document.getElementById('timer-display').innerText = `${{String(mins).padStart(2, '0')}}:${{String(secs).padStart(2, '0')}}`;
                if(totalSeconds <= 0) {{ clearInterval(timerInterval); submitTest(); }}
            }}, 1000);
        }}

        function loadQuestion(index) {{
            currentQIndex = index;
            document.getElementById('q-counter').innerText = `प्रश्न ${{index + 1}} / ${{TOTAL_Q}}`;
            document.getElementById('q-num-display').innerText = `Q. ${{index + 1}} / ${{TOTAL_Q}}`;
            const q = questions[index];
            document.getElementById('progress-bar').style.width = `${{((index + 1) / TOTAL_Q) * 100}}%`;
            document.getElementById('q-text').innerHTML = q.text;
            const optsContainer = document.getElementById('options-container');
            optsContainer.innerHTML = '';
            const letters = ['A', 'B', 'C', 'D'];
            q.options.forEach((optText, i) => {{
                const optDiv = document.createElement('div');
                optDiv.className = `option ${{userAnswers[index] === i ? 'selected' : ''}}`;
                optDiv.onclick = () => {{ userAnswers[currentQIndex] = i; loadQuestion(currentQIndex); }};
                optDiv.innerHTML = `<div class="opt-letter">${{letters[i]}}</div><div class="opt-text">${{optText}}</div>`;
                optsContainer.appendChild(optDiv);
            }});
            document.getElementById('next-btn').innerText = (index === TOTAL_Q - 1) ? 'Submit' : 'Next ▶';
            document.getElementById('answered-counter').innerText = `उत्तर दिए: ${{userAnswers.filter(ans => ans !== null).length}}`;
            updatePaletteUI();
        }}

        function markSkipped() {{ nextQuestion(); }}
        function nextQuestion() {{ if (currentQIndex < TOTAL_Q - 1) loadQuestion(currentQIndex + 1); else submitTest(); }}
        function prevQuestion() {{ if (currentQIndex > 0) loadQuestion(currentQIndex - 1); }}

        function initPalette() {{
            const grid = document.getElementById('palette-grid');
            grid.innerHTML = '';
            for(let i=0; i<TOTAL_Q; + 1; ; btn="document.createElement('button');" btn.className="q-grid-btn" btn.id="`pal-btn-${{i}}`;" btn.innerText="i" btn.onclick="()" const i++) {{> {{ loadQuestion(i); togglePalette(); }};
                grid.appendChild(btn);
            }}
        }}

        function updatePaletteUI() {{
            for(let i=0; i<TOTAL_Q; !="=" (i="==" (userAnswers[i] ; btn="document.getElementById(`pal-btn-${{i}}`);" btn.classList.add('status-answered'); btn.classList.add('status-current'); btn.className="q-grid-btn" const continue; currentQIndex) else function i++) if if(!btn) if(modal.classList.contains('open')){{ if(totalSeconds modal="document.getElementById('palette-modal');" modal.classList.add('open'); modal.classList.remove('open'); null) overlay="document.getElementById('overlay');" overlay.style.display="block" submitTest() togglePalette() updatePaletteUI(); {{ }}> 0 && !confirm("क्या आप परीक्षा सबमिट करना चाहते हैं?")) return;
            clearInterval(timerInterval);
            document.getElementById('test-screen').classList.add('hidden');
            document.getElementById('result-screen').classList.remove('hidden');
            document.getElementById('palette-modal').classList.remove('open');
            document.getElementById('overlay').style.display = 'none';

            let correct = 0, wrong = 0, skipped = 0;
            const reviewContainer = document.getElementById('review-container');
            reviewContainer.innerHTML = '';
            const letters = ['A', 'B', 'C', 'D'];

            let printHTML = `
                <div class="print-header-box">
                    <h2>UPSC CSE PRELIMS MOCK TEST</h2>
                    <h3>${{questions[0].topic || "{subject_title}"}}</h3>
                    <p>Candidate: ${{studentName}} | Marking: +2.00, -0.66</p>
                </div>
            `;

            questions.forEach((q, idx) => {{
                const uAns = userAnswers[idx];
                let statusColor = '', statusText = '';
                if (uAns === null) {{ skipped++; statusColor = 'var(--skipped)'; statusText = 'अनुत्तरित'; }}
                else if (uAns === q.correctAnswer) {{ correct++; statusColor = 'var(--correct)'; statusText = 'सही (CORRECT)'; }}
                else {{ wrong++; statusColor = 'var(--wrong)'; statusText = 'गलत (INCORRECT)'; }}

                const uAnsText = uAns !== null ? `(${{letters[uAns]}}) ${{q.options[uAns]}}` : "कोई नहीं";
                const cAnsText = `(${{letters[q.correctAnswer]}}) ${{q.options[q.correctAnswer]}}`;

                reviewContainer.innerHTML += `
                    <div class="review-box">
                        <div class="q-header-row"><span style="color:var(--primary); font-weight:bold;">Q${{idx + 1}}.</span><span class="q-topic-tag">${{q.topic}}</span></div>
                        <div class="review-q">${{q.text}}</div>
                        <div class="ans-row"><div class="ans-lbl">आपका उत्तर:</div><div style="color:${{statusColor}}">${{uAnsText}}</div></div>
                        <div class="ans-row"><div class="ans-lbl">सही उत्तर:</div><div style="color:var(--correct)">${{cAnsText}}</div></div>
                        <div class="solution-box"><div class="solution-title">💡 आधिकारिक व्याख्या:</div>${{q.solution}}</div>
                    </div>
                `;

                printHTML += `
                    <div class="print-q-box">
                        <div class="print-q-head"><span>Q${{idx + 1}}.</span><span class="print-q-topic">${{q.topic}}</span></div>
                        <div class="print-q-text">${{q.text}}</div>
                        <div class="print-ans-row"><strong>आपका उत्तर:</strong> ${{uAnsText}} | <strong>सही:</strong> ${{cAnsText}}</div>
                        <div class="print-sol-box"><b>व्याख्या:</b> ${{q.solution}}</div>
                    </div>
                `;
            }});

            document.getElementById('print-content').innerHTML = printHTML;
            let marks = Math.max(0, (correct * MARKS_PER_CORRECT) - (wrong * NEGATIVE_MARK));
            document.getElementById('final-score').innerHTML = marks.toFixed(2) + ` <span style="font-size:16px; color:var(--text-muted);">/ ${{(TOTAL_Q * MARKS_PER_CORRECT).toFixed(2)}}</span>`;
            document.getElementById('stat-correct').innerText = correct;
            document.getElementById('stat-wrong').innerText = wrong;
            document.getElementById('stat-skipped').innerText = skipped;
            let acc = (correct + wrong) > 0 ? Math.round((correct / (correct + wrong)) * 100) : 0;
            document.getElementById('stat-accuracy').innerText = `${{acc}}%`;
            let timeTaken = (TIME_MINUTES * 60) - totalSeconds;
            document.getElementById('stat-time').innerText = `${{Math.floor(timeTaken/60)}}m ${{timeTaken%60}}s`;
            document.getElementById('stat-avg-time').innerText = `${{Math.round(timeTaken/TOTAL_Q)}}s`;
            window.scrollTo(0,0);
        }}
    </script>
</body>
</html>"""

# ================= AUTHENTICATION DECORATOR =================
def ensure_auth(handler_func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
        register_user(user.id, user.username, user.first_name)
        if not is_authorized(user.id):
            user_link = f'<a href="tg://user?id={user.id}">{user.id}</a>'
            msg = (
                f"👋 <b>नमस्ते {user.first_name}!</b>\n\n"
                "📚 <b>UPSC SMART DESK में आपका स्वागत है।</b>\n\n"
                "⚠️️ <b>सत्र अनधिकृत:</b> यह बॉट केवल <b>UPSC Civil Services Examination</b> के समर्पित अभ्यर्थियों के लिए सुरक्षित है ताकि उच्च-स्तरीय AI टूल्स का दुरुपयोग न हो।\n\n"
                f"🆔 <b>आपकी टेलीग्राम ID:</b> {user_link}\n\n"
                f"👉 इस अध्ययन डेस्क का पूर्ण एक्सेस प्राप्त करने के लिए ओनर <b>{AUTHOR_NAME}</b> से संपर्क करें:\n"
                f"• संपर्क कमांड: <code>/owner</code>\n"
                f"• आधिकारिक चैनल: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
            )
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return
        return await handler_func(update, context, *args, **kwargs)
    return wrapper

# ================= PUBLIC MENU & PERMISSIONS =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a> (<code>{user.id}</code>)'
    
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"👋 <b>नमस्ते {user_link}!</b>\n\n"
            "📚 <b>UPSC CIVIL SERVICES PORTAL</b>\n\n"
            "आपका पंजीकरण सुरक्षित हो गया है (स्थिति: <b>निःशुल्क सदस्य</b>)।\n\n"
            "इस पोर्टल पर UPSC CSE के 360° दैनिक नोट्स, लाइव DAF साक्षात्कार, उत्तर-पुस्तिका मूल्यांकन और विगत वर्षों के प्रश्नों (PYQs) का संग्रह उपलब्ध है।\n\n"
            f"⚠️ <b>नोट:</b> वर्तमान में प्रीमियम AI टूल्स आपके खाते पर सक्रिय नहीं हैं। एक्सेस सक्रिय करवाने हेतु <code>/owner</code> पर संपर्क करें।\n\n"
            f"📢 <b>आधिकारिक चैनल:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>",
            parse_mode=ParseMode.HTML
        )
        return

    admin_tag = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if user.id in ADMIN_IDS else "📚 <b>UPSC CSE स्मार्ट अध्ययन डेस्क</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user_link}!</b>\n\n"
        f"{admin_tag}"
        "मुख्य कमांड्स:\n\n"
        "📖 <b>अध्ययन एवं नोट्स:</b>\n"
        "• <code>/daily</code> — दैनिक 360° समसामयिक संकलन\n"
        "• <code>/trending</code> — राष्ट्रीय व वैश्विक ट्रेंडिंग रडार\n"
        "• <code>/quiz</code> — विजन IAS स्टाइल लाइव मॉक टेस्ट पोर्टल\n"
        "• <code>/mains</code> — मुख्य परीक्षा अभ्यास (PYQs 2013-2026 व मॉडल प्रश्न)\n"
        "• <code>/checkanswer</code> — 2-स्टेप उत्तर पुस्तिका मूल्यांकन\n"
        "• <code>/interview</code> — 1-on-1 साक्षात्कार (DAF व वॉयस)\n"
        "• <code>/weekly</code> — साप्ताहिक क्विक रिवीजन\n"
        "• <code>/monthly</code> — संपूर्ण मासिक संकलन\n"
        "• <code>/yearly</code> — वार्षिक महा-संकलन (PT-365)\n"
        "• <code>/ask</code> — 24/7 यूपीएससी मेंटरशिप सत्र\n\n"
        "💬 <b>सहायता व संपर्क:</b>\n"
        "• <code>/help</code> — संपूर्ण उपयोग मार्गदर्शिका\n"
        "• <code>/owner</code> — सचिन शर्मा से संपर्क करें\n"
        "• <code>/cancel</code> — प्रक्रिया तुरंत रद्द करें\n\n"
        f"📢 <b>ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    help_text = (
        f"📖 <b>UPSC SMART DESK — संपूर्ण गाइड ({AUTHOR_NAME})</b>\n\n"
        "1️⃣ <b>लाइव साक्षात्कार (`/interview`):</b> DAF भरने के बाद बोर्ड आपकी पृष्ठभूमि के आधार पर प्रशासनिक प्रश्न ऑडियो में पूछेगा। आप बोलकर उत्तर रिकॉर्ड करें, बोर्ड सुनकर मूल्यांकन व रिपोर्ट देगा।\n\n"
        "2️⃣ <b>ऑनलाइन क्विज़ पोर्टल (`/quiz`):</b> GS-1, GS-2 व GS-3 के विषयों में से 50, 100 या 200 प्रश्नों का लाइव टेस्ट पोर्टल (टाइमर, ओएमआर पैलेट व डिटेल्ड सॉल्यूशन सहित) प्राप्त करें।\n\n"
        "3️⃣ <b>कॉपी चेकिंग (`/checkanswer`):</b> पहले प्रश्न टाइप/बोलें, फिर अपनी उत्तर पुस्तिका की फोटो या PDF भेजें।\n\n"
        "4️⃣ <b>मुख्य परीक्षा (`/mains`):</b> PYQs (2013-2026 संपूर्ण आर्काइव) या नए संभावित प्रश्नों का चयन करें।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ================= DAILY COMPILATION =================
@ensure_auth
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = get_ist_now()
    keyboard = []
    for i in range(-5, 4):
        target_dt = today + timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        label = f"🌟 आज ({d_str})" if i == 0 else (f"📅 {d_str} (-{-i} दिन)" if i < 0 else f"🔮 {d_str} (+{i} दिन)")
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")])
    await update.message.reply_text("📅 <b>जिस तारीख के UPSC दैनिक नोट्स चाहिए, उसका चयन करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ================= ADVANCED QUIZ PORTAL GENERATOR (GS-1 / GS-2 / GS-3) =================
@ensure_auth
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏛 GS पेपर 1 (इतिहास, भूगोल, समाज)", callback_data="quizgs_1")],
        [InlineKeyboardButton("⚖️ GS पेपर 2 (राजव्यवस्था, शासन, IR)", callback_data="quizgs_2")],
        [InlineKeyboardButton("💰 GS पेपर 3 (अर्थव्यवस्था, पर्यावरण, Sci-Tech)", callback_data="quizgs_3")],
        [InlineKeyboardButton("⚡ संपूर्ण समसामयिकी (Current Affairs)", callback_data="quizgs_ca")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🎯 <b>चरण 1/3:</b> किस GS पेपर का लाइव टेस्ट देना चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_quiz_gs_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "quizgs_1":
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "GS-1"}
        keyboard = [
            [InlineKeyboardButton("📜 प्राचीन व मध्यकालीन इतिहास", callback_data="quizsub_ancient_med")],
            [InlineKeyboardButton("🇮🇳 आधुनिक भारत व राष्ट्रीय आंदोलन", callback_data="quizsub_modern")],
            [InlineKeyboardButton("🎨 भारतीय कला एवं संस्कृति", callback_data="quizsub_art")],
            [InlineKeyboardButton("🌍 भारत एवं विश्व का भूगोल", callback_data="quizsub_geography")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 1):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    elif data == "quizgs_2":
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "GS-2"}
        keyboard = [
            [InlineKeyboardButton("🏛️ संविधान एवं राजव्यवस्था (Polity)", callback_data="quizsub_polity")],
            [InlineKeyboardButton("⚖️ शासन प्रणाली व सामाजिक न्याय", callback_data="quizsub_gov")],
            [InlineKeyboardButton("🌐 अंतर्राष्ट्रीय संबंध (IR)", callback_data="quizsub_ir")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 2):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    elif data == "quizgs_3":
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "GS-3"}
        keyboard = [
            [InlineKeyboardButton("💰 भारतीय अर्थव्यवस्था व कृषि", callback_data="quizsub_economy")],
            [InlineKeyboardButton("🌿 पर्यावरण, पारिस्थितिकी व जैव विविधता", callback_data="quizsub_env")],
            [InlineKeyboardButton("🔬 विज्ञान, प्रौद्योगिकी व अंतरिक्ष", callback_data="quizsub_scitech")],
            [InlineKeyboardButton("🛡️ आंतरिक सुरक्षा व आपदा प्रबंधन", callback_data="quizsub_security")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 3):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "CA", "sub": "दैनिक व मासिक करेंट अफेयर्स"}
        keyboard = [
            [InlineKeyboardButton("⚡ 50 प्रश्न (मानक अभ्यास सेट)", callback_data="quizcnt_50")],
            [InlineKeyboardButton("🎯 100 प्रश्न (पूर्ण विजन IAS स्टाइल मॉक)", callback_data="quizcnt_100")],
            [InlineKeyboardButton("🏆 200 प्रश्न (महा-अभ्यास मैराथन)", callback_data="quizcnt_200")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 3/3:</b> प्रश्नों की संख्या चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_quiz_sub_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "quiz_back_gs":
        await quiz_cmd(update, context)
        return

    sub_map = {
        "quizsub_ancient_med": "प्राचीन व मध्यकालीन भारतीय इतिहास",
        "quizsub_modern": "आधुनिक भारत का इतिहास व स्वतंत्रता संग्राम",
        "quizsub_art": "भारतीय कला, साहित्य एवं संस्कृति",
        "quizsub_geography": "भारत एवं विश्व का भौतिक व आर्थिक भूगोल",
        "quizsub_polity": "भारतीय संविधान, राजव्यवस्था व न्यायपालिका",
        "quizsub_gov": "शासन प्रणाली, नीतियां व सामाजिक न्याय",
        "quizsub_ir": "अंतर्राष्ट्रीय संबंध व वैश्विक संस्थाएं",
        "quizsub_economy": "भारतीय अर्थव्यवस्था, बजट व कृषि सुधार",
        "quizsub_env": "पर्यावरण, पारिस्थितिकी व जलवायु परिवर्तन",
        "quizsub_scitech": "विज्ञान एवं प्रौद्योगिकी, रक्षा व अंतरिक्ष",
        "quizsub_security": "आंतरिक सुरक्षा व आपदा प्रबंधन"
    }
    USER_QUIZ_SELECTIONS[user_id]["sub"] = sub_map.get(data, "सामान्य अध्ययन")

    keyboard = [
        [InlineKeyboardButton("⚡ 50 प्रश्न (मानक अभ्यास सेट)", callback_data="quizcnt_50")],
        [InlineKeyboardButton("🎯 100 प्रश्न (पूर्ण विजन IAS स्टाइल मॉक)", callback_data="quizcnt_100")],
        [InlineKeyboardButton("🏆 200 प्रश्न (महा-अभ्यास मैराथन)", callback_data="quizcnt_200")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data=f"quizgs_{USER_QUIZ_SELECTIONS[user_id].get('gs', '1').lower().replace('gs-', '')}")]
    ]
    await query.message.edit_text(f"🎯 <b>चरण 3/3:</b> विषय <b>{USER_QUIZ_SELECTIONS[user_id]['sub']}</b> के कितने प्रश्न चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_quiz_cnt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cnt = int(query.data.replace("quizcnt_", ""))
    user_id = query.from_user.id
    subj = USER_QUIZ_SELECTIONS.get(user_id, {}).get("sub", "सामान्य अध्ययन")

    status_msg = await query.message.reply_text("⏳ [■□□□□□□□□□] 10% UPSC प्रश्न बैंक संकलित हो रहा है...")

    prompt = f"""
आप UPSC सिविल सेवा प्रारंभिक परीक्षा के मुख्य परीक्षक हैं।
विषय: '{subj}' पर ठीक {cnt} कठिन, मानक और कथन-आधारित बहुविकल्पीय प्रश्न तैयार करें।
अनिवार्य रूप से शुद्ध JSON Array (बिना किसी अतिरिक्त मार्कडाउन कोड या व्याख्या के) इस प्रारूप में दें:
[
  {{
    "topic": "{subj}",
    "text": "1. प्रश्न का पूर्ण विवरण और कथन...",
    "options": ["(a) केवल 1", "(b) केवल 2", "(c) 1 और 2 दोनों", "(d) न तो 1, न ही 2"],
    "correctAnswer": 2,
    "solution": "<b>व्याख्या:</b> प्रामाणिक स्रोत सहित संपूर्ण 2-3 पंक्तियों की व्याख्या।"
  }}
]
नोट: correctAnswer शून्य-आधारित इंडेक्स (0=a, 1=b, 2=c, 3=d) होना चाहिए। केवल शुद्ध हिंदी भाषा रखें।
"""
    try:
        await status_msg.edit_text("⏳ [■■■■□□□□□□] 40% कथन व विकल्पों का संश्लेषण जारी...")
        raw_resp = await asyncio.to_thread(call_gemini_safely, prompt)
        
        await status_msg.edit_text("⏳ [■■■■■■■□□□] 70% विजन IAS ऑनलाइन टेस्ट पोर्टल असेंबल हो रहा है...")
        clean_json_str = re.sub(r'^```json\s*', '', raw_resp.strip(), flags=re.IGNORECASE)
        clean_json_str = re.sub(r'```$', '', clean_json_str.strip()).strip()

        test_id = f"{int(time.time()) % 100000}"
        portal_html = build_vision_ias_interactive_portal(subj, test_id, cnt, clean_json_str)

        filename = f"UPSC_Mock_{cnt}Q_{test_id}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(portal_html)

        await status_msg.edit_text("⏳ [■■■■■■■■■■] 100% ऑनलाइन टेस्ट पोर्टल तैयार!")

        with open(filename, "rb") as doc:
            await context.bot.send_document(
                chat_id=user_id,
                document=doc,
                filename=filename,
                caption=(
                    f"🎯 <b>UPSC CSE ऑनलाइन टेस्ट पोर्टल तैयार!</b>\n\n"
                    f"📚 <b>विषय:</b> <code>{subj}</code>\n"
                    f"📝 <b>कुल प्रश्न:</b> <code>{cnt} MCQs</code>\n"
                    f"⏱️ <b>सुविधाएं:</b> लाइव टाइमर, OMR पैलेट ग्रिड, तत्काल प्राप्तांक व 50% वाटरमार्क PDF\n\n"
                    f"👤 <b>संरक्षक:</b> {AUTHOR_NAME}\n"
                    f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                ),
                parse_mode=ParseMode.HTML
            )
        if os.path.exists(filename):
            os.remove(filename)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ पोर्टल बनाने में त्रुटि: {e}। कृपया पुनः प्रयास करें।")

# ================= 1-on-1 UPSC INTERVIEW WITH FIXED DAF RECALL & LIVE STATUS =================
@ensure_auth
async def interview_flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id

    daf = get_user_daf(user_id)
    if not daf or not daf[0]:
        await update.message.reply_text(
            f"🏛 <b>UPSC साक्षात्कार बोर्ड (Personality Test)</b>\n\n"
            f"नमस्ते <b>{user.first_name} जी</b>! बोर्ड कक्ष में प्रवेश से पहले हमें आपकी पृष्ठभूमि का संक्षिप्त विवरण चाहिए ताकि मूल्यांकन आपकी वास्तविक स्थिति के अनुसार हो सके।\n\n"
            "👉 <b>चरण 1/6:</b> कृपया अपना <b>पूरा नाम</b> लिखकर भेजें:",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        return DAF_NAME

    name, home_state, college, status, opt_sub, attempt = daf
    reply_kb = [["✅ इसी प्रोफाइल से साक्षात्कार दें"], ["✏️ प्रोफाइल अपडेट करें (Edit DAF)"]]
    await update.message.reply_text(
        f"🏛 <b>आपकी पूर्व दर्ज साक्षात्कार प्रोफाइल:</b>\n\n"
        f"👤 <b>नाम:</b> {name}\n"
        f"📍 <b>गृह राज्य:</b> {home_state}\n"
        f"🏫 <b>कॉलेज:</b> {college}\n"
        f"🎓 <b>स्थिति:</b> {status}\n"
        f"📚 <b>वैकल्पिक विषय:</b> {opt_sub}\n"
        f"🎯 <b>प्रयास संख्या:</b> {attempt}\n\n"
        "👉 कृपया विकल्प चुनें:",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_NAME

async def handle_daf_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip() if update.message.text else update.effective_user.first_name

    if txt == "✅ इसी प्रोफाइल से साक्षात्कार दें":
        reply_kb = [["⚡ 1 प्रश्न (क्विक स्थितिजन्य)"], ["🎯 3 प्रश्न (मानक बोर्ड)"], ["🏆 5 प्रश्न (गहन साक्षात्कार)"]]
        await update.message.reply_text(
            "👉 <b>आप कितने प्रश्नों का साक्षात्कार सेट देना चाहते हैं?</b>",
            reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
            parse_mode=ParseMode.HTML
        )
        return DAF_QCOUNT

    if txt == "✏️ प्रोफाइल अपडेट करें (Edit DAF)":
        await update.message.reply_text("👉 <b>चरण 1/6:</b> अपना <b>पूरा नाम</b> लिखकर भेजें:", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return DAF_NAME

    context.user_data["daf_name"] = txt
    await update.message.reply_text("👉 <b>चरण 2/6:</b> अपना <b>गृह राज्य</b> दर्ज करें (उदा. राजस्थान, उत्तर प्रदेश):", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return DAF_STATE

async def handle_daf_state_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_state"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 3/6:</b> अपने <b>कॉलेज / विश्वविद्यालय</b> का नाम लिखें:", parse_mode=ParseMode.HTML)
    return DAF_COLLEGE

async def handle_daf_college_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_college"] = update.message.text.strip()
    reply_kb = [["🎓 स्नातक पूर्ण (Completed)"], ["⏳ अध्ययनरत (Running / Final Year)"]]
    await update.message.reply_text("👉 <b>चरण 4/6:</b> कॉलेज की वर्तमान स्थिति क्या है?", reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True), parse_mode=ParseMode.HTML)
    return DAF_STATUS

async def handle_daf_status_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_status"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 5/6:</b> अपना <b>वैकल्पिक विषय (Optional Subject)</b> लिखें (उदा. भूगोल, इतिहास):", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return DAF_OPTIONAL_STEP

async def handle_daf_optional_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_optional"] = update.message.text.strip()
    reply_kb = [["1st Attempt (पहला)"], ["2nd Attempt (दूसरा)"], ["3rd+ Attempt (तीसरा या अधिक)"]]
    await update.message.reply_text("👉 <b>चरण 6/6:</b> यह आपका कौन सा <b>प्रयास (Attempt)</b> है?", reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True), parse_mode=ParseMode.HTML)
    return DAF_ATTEMPT_STEP

async def handle_daf_attempt_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    attempt_txt = update.message.text.strip()

    name = context.user_data.get("daf_name", update.effective_user.first_name)
    state = context.user_data.get("daf_state", "राजस्थान")
    college = context.user_data.get("daf_college", "विश्वविद्यालय")
    status = context.user_data.get("daf_status", "पूर्ण")
    opt = context.user_data.get("daf_optional", "सामान्य अध्ययन")

    save_user_daf(user_id, name, state, college, status, opt, attempt_txt)

    reply_kb = [["⚡ 1 प्रश्न (क्विक स्थितिजन्य)"], ["🎯 3 प्रश्न (मानक बोर्ड)"], ["🏆 5 प्रश्न (गहन साक्षात्कार)"]]
    await update.message.reply_text(
        "✅ <b>आपकी DAF प्रोफाइल सुरक्षित कर ली गई है!</b>\n\n"
        "👉 <b>आप कितने प्रश्नों का साक्षात्कार सेट देना चाहते हैं?</b>",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_QCOUNT

async def handle_daf_qcount_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    txt = update.message.text.strip()
    cnt = 1
    if "3" in txt:
        cnt = 3
    elif "5" in txt:
        cnt = 5

    daf = get_user_daf(user_id)
    INTERVIEW_SESSION[user_id] = {"total": cnt, "current": 1, "daf": daf, "history": []}

    status_m = await update.message.reply_text("🏛 <b>बोर्ड कक्ष में स्वागत है।</b>\n⏳ [■■□□□□□□□□] 20% DAF और पृष्ठभूमि का विश्लेषण...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return await ask_interview_question(update, context, user_id, status_m)

async def ask_interview_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, status_m = None) -> int:
    sess = INTERVIEW_SESSION.get(user_id)
    curr = sess["current"]
    tot = sess["total"]
    name, state, college, status, opt_sub, attempt = sess["daf"]

    if status_m:
        await status_m.edit_text(f"🏛 <b>बोर्ड कक्ष (राउंड {curr}/{tot})</b>\n⏳ [■■■■■□□□□□] 50% प्रशासनिक स्थितिजन्य प्रश्न तैयार...")

    prompt = f"""
आप UPSC साक्षात्कार बोर्ड के अध्यक्ष हैं।
उम्मीदवार विवरण:
- नाम: {name}
- गृह राज्य: {state}
- कॉलेज: {college} ({status})
- वैकल्पिक विषय: {opt_sub}
- प्रयास: {attempt}
- राउंड: {curr}/{tot} (कठिनाई स्तर: {curr * 2}/10)

सख्त निर्देश:
- सीधे '{name} जी' कहकर संबोधित करें।
- शुद्ध हिंदी में 3-4 पंक्तियों का गंभीर, प्रशासनिक स्थितिजन्य प्रश्न पूछें जिसमें निर्णय-क्षमता की परीक्षा हो।
- कोई अंग्रेजी शब्द या सिस्टम निर्देश न लिखें।
"""
    try:
        q_text = await asyncio.to_thread(call_gemini_safely, prompt)
        if status_m:
            await status_m.edit_text(f"🏛 <b>बोर्ड कक्ष (राउंड {curr}/{tot})</b>\n⏳ [■■■■■■■■□□] 80% बोर्ड अध्यक्ष की ऑडियो रिकॉर्डिंग...")

        audio_bytes = await download_audio_stream(q_text)
        if status_m:
            await status_m.delete()

        await update.effective_message.reply_text(
            f"🏛 <b>UPSC साक्षात्कार बोर्ड अध्यक्ष (प्रश्न {curr}/{tot}):</b>\n\n{q_text}\n\n"
            "👉 <b>कृपया अपना उत्तर वॉयस नोट (Voice Message) में रिकॉर्ड करके भेजें:</b>\n"
            "<i>(प्रक्रिया रोकने के लिए <code>/cancel</code> भेजें)</i>",
            parse_mode=ParseMode.HTML
        )
        if audio_bytes:
            audio_io = io.BytesIO(audio_bytes)
            audio_io.name = f"Interview_Q_{curr}.mp3"
            await update.effective_message.reply_voice(voice=audio_io, caption=f"🎙️ साक्षात्कार प्रश्न {curr}/{tot} | {AUTHOR_NAME}")

    except Exception as e:
        await update.effective_message.reply_text(f"❌ त्रुटि: {e}")

    return WAITING_INTERVIEW_VOICE

async def handle_interview_candidate_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    sess = INTERVIEW_SESSION.get(user_id)
    if not sess:
        await update.message.reply_text("सत्र समाप्त हो चुका है। पुनः <code>/interview</code> चलाएं।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    wait_m = await update.message.reply_text("🎧 [■■■■□□□□□□] 40% बोर्ड आपके मौखिक उत्तर का विश्लेषण कर रहा है...", parse_mode=ParseMode.HTML)

    try:
        msg = update.message
        voice_obj = msg.voice or msg.audio
        f_obj = await voice_obj.get_file()
        f_bytes = await f_obj.download_as_bytearray()

        transcribed_text = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
        sess["history"].append({"round": sess["current"], "answer": transcribed_text})

        await wait_m.edit_text("🎧 [■■■■■■■□□□] 75% बोर्ड मूल्यांकन तैयार...")
        is_last = (sess["current"] >= sess["total"])
        name = sess["daf"][0]

        eval_prompt = f"""
उम्मीदवार {name} ने मौखिक उत्तर दिया है: "{transcribed_text}"
राउंड: {sess['current']}/{sess['total']}
कार्य:
उम्मीदवार को {name} जी कहकर संबोधित करते हुए 2-3 पंक्तियों में प्रशासनिक भाषा में संतुलित मौखिक फीडबैक दें। केवल शुद्ध हिंदी लिखें।
"""
        eval_resp = await asyncio.to_thread(call_gemini_safely, eval_prompt)
        audio_bytes = await download_audio_stream(eval_resp)
        await wait_m.delete()

        await update.message.reply_text(f"🏛 <b>बोर्ड का अवलोकन ({sess['current']}/{sess['total']}):</b>\n\n{eval_resp}", parse_mode=ParseMode.HTML)
        if audio_bytes:
            audio_io = io.BytesIO(audio_bytes)
            audio_io.name = "Board_Feedback.mp3"
            await update.message.reply_voice(voice=audio_io, caption=f"🎙️ बोर्ड फीडबैक | {AUTHOR_NAME}")

        if not is_last:
            sess["current"] += 1
            INTERVIEW_SESSION[user_id] = sess
            await asyncio.sleep(1)
            status_m = await update.message.reply_text("⏳ अगले प्रश्न की तैयारी जारी है...")
            return await ask_interview_question(update, context, user_id, status_m)
        else:
            reply_kb = [["➕ 1 और स्थितिजन्य प्रश्न दें"], ["📊 संपूर्ण परिणाम व रिपोर्ट कार्ड देखें"]]
            await update.message.reply_text(
                "🎯 <b>निर्धारित साक्षात्कार राउंड पूर्ण हुआ!</b>\n\n"
                "क्या आप अपनी तैयारी को और परखने के लिए 1 अतिरिक्त प्रश्न देना चाहते हैं या अंतिम रिपोर्ट देखना चाहते हैं?",
                reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
                parse_mode=ParseMode.HTML
            )
            return WAITING_INTERVIEW_DECISION

    except Exception as e:
        await wait_m.edit_text(f"❌ वॉयस प्रोसेसिंग में त्रुटि: {e}। कृपया पुनः वॉयस भेजें।")
        return WAITING_INTERVIEW_VOICE

async def handle_interview_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    txt = update.message.text.strip()
    sess = INTERVIEW_SESSION.get(user_id)

    if not sess:
        await update.message.reply_text("सत्र समाप्त। पुनः <code>/interview</code> करें।", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if "1 और" in txt:
        sess["total"] += 1
        sess["current"] += 1
        INTERVIEW_SESSION[user_id] = sess
        status_m = await update.message.reply_text("अगला उन्नत स्तर का प्रश्न तैयार हो रहा है...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return await ask_interview_question(update, context, user_id, status_m)

    wait_m = await update.message.reply_text("⏳ [■■■■■■■■□□] 85% बोर्ड मेंबर अंतिम मूल्यांकन पत्रक तैयार कर रहे हैं...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    name = sess["daf"][0]
    final_prompt = f"""
उम्मीदवार {name} का UPSC साक्षात्कार पूर्ण हो चुका है। कुल {len(sess['history'])} प्रश्नों के उत्तर दिए गए।
एक आधिकारिक, उच्च-स्तरीय यूपीएससी साक्षात्कार मूल्यांकन पत्रक तैयार करें:
1. 🏆 प्राप्तांक: (275 में से अंक)
2. 🌟 मुख्य प्रशासनिक खूबियाँ (Strengths)
3. ⚠️ सुधार योग्य क्षेत्र (Areas of Improvement)
4. 🚀 बोर्ड की अंतिम अनुशंसा (Final Board Recommendation)
केवल शुद्ध हिंदी में लिखें।
"""
    try:
        final_report = await asyncio.to_thread(call_gemini_safely, final_prompt)
        await wait_m.delete()
        await update.message.reply_text(f"📜 <b>UPSC साक्षात्कार अंतिम परिणाम पत्रक</b>\n\n{final_report}\n\n👤 <b>बोर्ड संरक्षक:</b> {AUTHOR_NAME}", parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_m.edit_text(f"त्रुटि: {e}")

    INTERVIEW_SESSION.pop(user_id, None)
    return ConversationHandler.END

# ================= UPSC MAINS SPECIAL (PYQs 2013-2026) =================
@ensure_auth
async def mains_special_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📜 विगत वर्षों के प्रश्न (PYQs 2013-2026 Complete)", callback_data="mq_type_pyq")],
        [InlineKeyboardButton("✨ नए संभावित मॉडल प्रश्न (New Expected)", callback_data="mq_type_new")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("✍️ <b>UPSC मुख्य परीक्षा (Mains) अभ्यास:</b>\nआप पुराने सभी प्रश्न देखना चाहते हैं या नए संभावित मॉडल प्रश्न?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_mains_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_type = query.data.replace("mq_type_", "")
    user_id = query.from_user.id
    MAINS_SELECTIONS[user_id] = {"q_type": q_type}

    keyboard = [
        [InlineKeyboardButton("🏛 GS 1 (इतिहास, भूगोल, समाज)", callback_data="mq_gs_1")],
        [InlineKeyboardButton("⚖ GS 2 (राजव्यवस्था, शासन, IR)", callback_data="mq_gs_2")],
        [InlineKeyboardButton("💰 GS 3 (अर्थव्यवस्था, पर्यावरण, सुरक्षा)", callback_data="mq_gs_3")],
        [InlineKeyboardButton("🧭 GS 4 (नीतिशास्त्र, केस स्टडी)", callback_data="mq_gs_4")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="mains_back_root")]
    ]
    await query.message.edit_text("🎯 <b>विषय / GS पेपर का चयन करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_mains_gs_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "mains_back_root":
        await mains_special_cmd(update, context)
        return

    gs_num = data.replace("mq_gs_", "")
    user_id = query.from_user.id
    MAINS_SELECTIONS[user_id]["gs"] = gs_num
    is_pyq = (MAINS_SELECTIONS[user_id].get("q_type") == "pyq")

    keyboard = [
        [InlineKeyboardButton("⚡ 1 प्रश्न", callback_data="mq_cnt_1")],
        [InlineKeyboardButton("🎯 3 प्रश्न", callback_data="mq_cnt_3")],
        [InlineKeyboardButton("🏆 5 प्रश्न", callback_data="mq_cnt_5")]
    ]
    if is_pyq:
        keyboard.append([InlineKeyboardButton("📚 2013-2026 तक के सभी मुख्य PYQs (Complete Set)", callback_data="mq_cnt_all")])
    else:
        keyboard.append([InlineKeyboardButton("📚 10 प्रश्नों का संभावित मेगा सेट", callback_data="mq_cnt_10")])

    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="mq_type_" + MAINS_SELECTIONS[user_id].get("q_type", "new"))])
    await query.message.edit_text(f"📝 <b>GS {gs_num} के कितने प्रश्नों का अभ्यास करना चाहते हैं?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_mains_cnt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    cnt_raw = data.replace("mq_cnt_", "")
    cnt_desc = "2013 से 2026 तक के सभी मुख्य PYQs" if cnt_raw == "all" else f"{cnt_raw} प्रश्न"
    
    sel = MAINS_SELECTIONS.get(user_id, {"q_type": "new", "gs": "2"})
    is_pyq = (sel.get("q_type") == "pyq")
    gs_paper = f"सामान्य अध्ययन - {sel.get('gs')}"

    wait_m = await query.message.reply_text(f"⏳ <b>{gs_paper}</b> के {cnt_desc} उत्तर-लेखन मॉड्यूल तैयार हो रहे हैं...", parse_mode=ParseMode.HTML)

    tag_instruction = "2013 से 2026 तक इस विषय में पूछे गए प्रश्नों को शामिल करें। प्रत्येक प्रश्न पर उसका वर्ष, पेपर और अंक स्पष्ट लिखें (उदा. [UPSC CSE 2023 / GS " + sel.get('gs') + " / 15 अंक])." if is_pyq else "प्रत्येक प्रश्न पर लिखें: [मॉडल प्रश्न / GS " + sel.get('gs') + " / 15 अंक]."

    prompt = f"""
आप UPSC मुख्य परीक्षा के शीर्ष विशेषज्ञ हैं।
विषय: {gs_paper} के {cnt_desc} उत्तर-लेखन मॉड्यूल तैयार करें।
{tag_instruction}

सख्त नियम:
1. प्रत्येक प्रश्न को स्पष्ट शीर्षक में रखें।
2. विस्तृत उत्तर-लेखन ढांचा दें:
   - प्रश्न का पूरा विवरण व [वर्ष / पेपर टैग]
   - 📌 भूमिका (Introduction)
   - 📊 मुख्य विश्लेषणात्मक आयाम (Body): 3 स्पष्ट उप-शीर्षक और उदाहरण
   - 🚀 आगे की राह (Way Forward)
   - ⚖️ संतुलित प्रशासनिक निष्कर्ष
भाषा केवल शुद्ध हिंदी रखें। मार्कडाउन स्टार्स का प्रयोग न करें।
"""
    try:
        resp = await asyncio.to_thread(call_gemini_safely, prompt)
        topic = f"UPSC Mains Module — GS {sel.get('gs')} ({cnt_desc})"
        filename = f"UPSC_Mains_GS{sel.get('gs')}_{cnt_raw}.html"
        html_out = build_standalone_master_html(topic, resp)

        with open(filename, "wb") as f:
            f.write(html_out.encode("utf-8"))

        with open(filename, "rb") as send_doc:
            await context.bot.send_document(
                chat_id=user_id,
                document=send_doc,
                filename=filename,
                caption=f"📝 <b>UPSC मुख्य परीक्षा संग्रह:</b> <code>{topic}</code>\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                parse_mode=ParseMode.HTML
            )
        if os.path.exists(filename):
            os.remove(filename)
        await wait_m.delete()
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

# ================= 2-STEP ANSWER COPY EVALUATION (/checkanswer) =================
@ensure_auth
async def check_answer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 <b>UPSC मुख्य परीक्षा उत्तर पुस्तिका मूल्यांकन (चरण 1/2):</b>\n\n"
        "कृपया सबसे पहले अपना <b>प्रश्न</b> लिखकर भेजें। आप प्रश्न टाइप कर सकते हैं, उसकी फ़ोटो भेज सकते हैं या वॉयस मैसेज भी रिकॉर्ड कर सकते हैं।\n\n"
        "<i>(रद्द करने के लिए <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_QUESTION_TEXT

async def handle_question_text_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message

    if msg.text and msg.text.strip().lower() == "/cancel":
        await msg.reply_text("मूल्यांकन प्रक्रिया रद्द कर दी गई।")
        return ConversationHandler.END

    q_content = ""
    if msg.text:
        q_content = msg.text.strip()
    elif msg.voice or msg.audio:
        wait_m = await msg.reply_text("🎧 प्रश्न का ऑडियो सुना जा रहा है...")
        try:
            f_obj = await (msg.voice or msg.audio).get_file()
            f_bytes = await f_obj.download_as_bytearray()
            q_content = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ ऑडियो पढ़ने में त्रुटि: {e}। कृपया टेक्स्ट में लिखें।")
            return WAITING_QUESTION_TEXT
    elif msg.photo:
        wait_m = await msg.reply_text("🖼️ प्रश्न की फ़ोटो पढ़ी जा रही है...")
        try:
            f_obj = await msg.photo[-1].get_file()
            f_bytes = await f_obj.download_as_bytearray()
            q_content = await asyncio.to_thread(call_gemini_multimodal_inline, "इस फ़ोटो में लिखे UPSC प्रश्न को निकालें।", bytes(f_bytes), "image/jpeg")
            await wait_m.delete()
        except Exception:
            q_content = "संलग्न फ़ोटो में दिया गया प्रश्न"

    CHECK_ANSWER_CACHE[user_id] = q_content
    await msg.reply_text(
        f"✅ <b>प्रश्न दर्ज हो गया:</b>\n<i>\"{q_content[:150]}...\"</i>\n\n"
        "👉 <b>चरण 2/2:</b> अब अपनी लिखी हुई <b>उत्तर पुस्तिका की साफ़ फ़ोटो या PDF</b> भेजें:",
        parse_mode=ParseMode.HTML
    )
    return WAITING_ANSWER_COPY

async def handle_answer_copy_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message
    q_text = CHECK_ANSWER_CACHE.get(user_id, "UPSC मुख्य परीक्षा मानक प्रश्न")
    
    wait_m = await msg.reply_text("🔍 [■■■■□□□□□□] 40% उत्तर पुस्तिका की संरचना व तर्कों की जांच जारी...", parse_mode=ParseMode.HTML)

    prompt = f"""
आप UPSC मुख्य परीक्षा के वरिष्ठ परीक्षक (Copy Evaluator) हैं।
प्रश्न: "{q_text}"
प्रस्तुत उत्तर पुस्तिका का निष्पक्ष, गहन और सटीक मूल्यांकन करें।
प्रारूप:
1. 📊 प्राप्तांक (Marks Awarded): (उदा. 6.5/10 या 9/15)
2. 🌟 सकारात्मक पक्ष (Strengths): (भूमिका, स्पष्टता, मुख्य बिंदु)
3. ⚠️ संरचनात्मक कमियाँ (Areas of Improvement): (प्रमाणिक डेटा, आरेख, अनुच्छेदों की कमी)
4. 🚀 परीक्षक की मूल्य संवर्धन सलाह (Value Addition)
केवल और केवल शुद्ध एवं गरिमापूर्ण हिंदी में उत्तर दें।
"""
    m_type = "application/pdf" if (msg.document and msg.document.file_name.lower().endswith('.pdf')) else "image/jpeg"

    try:
        doc_obj = msg.document or (msg.photo[-1] if msg.photo else None)
        f_obj = await doc_obj.get_file()
        f_bytes = await f_obj.download_as_bytearray()

        eval_result = await asyncio.to_thread(call_gemini_multimodal_inline, prompt, bytes(f_bytes), m_type)
        clean_eval = clean_all_markdown_and_fix_content(eval_result)
        await wait_m.delete()

        if len(clean_eval) > 3800:
            for p in [clean_eval[i:i+3800] for i in range(0, len(clean_eval), 3800)]:
                await msg.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text(clean_eval, parse_mode=ParseMode.HTML)

    except Exception as e:
        await wait_m.edit_text(f"❌ मूल्यांकन में त्रुटि: {e}। कृपया साफ़ फ़ोटो या PDF भेजें।")

    CHECK_ANSWER_CACHE.pop(user_id, None)
    return ConversationHandler.END

# ================= CONTINUOUS ASK MENTORSHIP SESSION (/ask) =================
@ensure_auth
async def start_ask_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🎓 <b>UPSC 1-on-1 मेंटरशिप सत्र सक्रिय हो गया है!</b>\n\n"
        "आप UPSC सिविल सेवा परीक्षा (GS 1-4, करेंट अफेयर्स, वैकल्पिक विषय व निबंध) से जुड़ा कोई भी सवाल लगातार पूछते रह सकते हैं।\n\n"
        "👉 <i>सत्र समाप्त करने के लिए कभी भी <code>/cancel</code> या <code>/stop</code> भेजें।</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_ASK_SESSION

async def handle_ask_continuous_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_query = update.message.text.strip()

    if user_query.lower() in ["/cancel", "/stop", "/exit", "cancel", "stop", "exit", "रद्द", "बंद"]:
        await update.message.reply_text("✅ <b>मेंटरशिप सत्र समाप्त हुआ।</b> अध्ययन जारी रखें और शुभकामनाएं!", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    blocked_non_upsc = [
        r"मेरा नाम", r"तुम्हारा नाम", r"आपका नाम", r"तुम कौन", r"आप कौन",
        r"हेलो", r"हाय", r"hello", r"hi", r"hey", r"कैसे हो", r"क्या कर रहे",
        r"शायरी", r"मजाक", r"मौसम", r"गाना", r"लव", r"प्यार", r"गर्लफ्रेंड",
        r"बॉयफ्रेंड", r"joke", r"time pass"
    ]
    if any(re.search(pat, user_query, re.IGNORECASE) for pat in blocked_non_upsc) or len(user_query) < 5:
        await update.message.reply_text(
            "⚠️ <b>अमान्य प्रश्न:</b> इस संबंध में हम कोई जानकारी नहीं रखते हैं।\n\n"
            "यह डेस्क केवल <b>संघ लोक सेवा आयोग (UPSC CSE)</b> पाठ्यक्रम के गंभीर अकादमिक विमर्श हेतु समर्पित है। कृपया परीक्षा संबंधी विषय ही पूछें।",
            parse_mode=ParseMode.HTML
        )
        return WAITING_ASK_SESSION

    wait_msg = await update.message.reply_text("🤔 [■■■■□□□□□□] 40% UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")
    try:
        prompt = f"""
आप UPSC मेंटर हैं। निम्नलिखित विषय का बिंदुवार, सटीक एवं संतुलित प्रशासनिक विश्लेषण दें:
विषय: '{user_query}'
सख्त नियम: मार्कडाउन स्टार्स का प्रयोग न करें। भाषा केवल शुद्ध हिंदी रखें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = clean_all_markdown_and_fix_content(reply_text)

        if len(clean_reply) > 3800:
            await wait_msg.delete()
            for p in [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]:
                await update.message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await wait_msg.edit_text(clean_reply, parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ उत्तर संकलित करने में समस्या: {e}")
        
    return WAITING_ASK_SESSION

# ================= TRENDING RADAR =================
@ensure_auth
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚡ आज के मुख्य ट्रेंडिंग मुद्दे (Daily)", callback_data="trtype_daily")],
        [InlineKeyboardButton("📁 इस महीने के शीर्ष ट्रेंडिंग मुद्दे (Monthly)", callback_data="trtype_monthly")],
        [InlineKeyboardButton("📚 वर्ष भर के सबसे बड़े ट्रेंडिंग मुद्दे (Yearly)", callback_data="trtype_yearly")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🧭 <b>UPSC TRENDING RADAR: आप किस समयावधि के ट्रेंडिंग मुद्दे देखना चाहते हैं?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_trending_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "tr_back_root":
        await trending_cmd(update, context)
        return

    user_id = query.from_user.id
    tr_type = data.replace("trtype_", "")
    
    today = get_ist_now().strftime("%d %B %Y")
    current_month = get_ist_now().strftime("%B %Y")
    current_year = get_ist_now().strftime("%Y")

    if tr_type == "daily":
        scope_str = f"आज ({today})"
        prompt = f"आज {today} के संदर्भ में UPSC CSE परीक्षा हेतु 9 सबसे महत्वपूर्ण ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"
    elif tr_type == "monthly":
        scope_str = f"माह ({current_month})"
        prompt = f"माह {current_month} के 9 सबसे महत्वपूर्ण नीतिगत, अंतर्राष्ट्रीय एवं पर्यावरणीय ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"
    else:
        scope_str = f"वर्ष {current_year}"
        prompt = f"वर्ष {current_year} के 9 सबसे बड़े राष्ट्रीय व वैश्विक ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"

    wait_m = await query.message.reply_text(f"🛰 <b>{scope_str}</b> के ट्रेंडिंग मुद्दों का रडार संकलन हो रहा है...", parse_mode=ParseMode.HTML)
    try:
        raw_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_lines = [re.sub(r'^\*+\s*', '', l.strip()) for l in raw_text.split('\n') if l.strip() and len(l.strip()) > 5 and not l.startswith('#')]
        
        TRENDING_CACHE[user_id] = clean_lines

        p_text = f"🧭 <b>UPSC TRENDING RADAR — {scope_str} (पेज 1/3)</b>\n\n" + "\n\n".join(clean_lines[:3])
        p_text += "\n\n━━━━━━━━━━━━━━━━━━━━\n👉 <b>विकल्प:</b>\n• किसी मुद्दे के पूर्ण नोट्स हेतु नंबर भेजें (उदा. <code>1, 2</code>)\n• सभी मुद्दों के 360° नोट्स हेतु लिखें: <code>all</code>"

        keyboard = [
            [InlineKeyboardButton("अगला पेज (पेज 2/3) ▶", callback_data="trpage_1")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="tr_back_root")]
        ]
        await wait_m.edit_text(p_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

async def handle_trending_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    target_page = int(query.data.replace("trpage_", ""))
    
    lines = TRENDING_CACHE.get(user_id, [])
    if not lines:
        await query.message.reply_text("⚠️ सत्र समाप्त हो गया है। पुनः <code>/trending</code> चलाएं।", parse_mode=ParseMode.HTML)
        return

    start_idx = target_page * 3
    end_idx = start_idx + 3
    sub_lines = lines[start_idx:end_idx]

    p_text = f"🧭 <b>UPSC TRENDING RADAR (पेज {target_page + 1}/3)</b>\n\n" + "\n\n".join(sub_lines)
    p_text += "\n\n━━━━━━━━━━━━━━━━━━━━\n👉 <b>विकल्प:</b>\n• किसी मुद्दे के पूर्ण नोट्स हेतु नंबर भेजें (उदा. <code>1, 2</code>)\n• सभी मुद्दों के 360° नोट्स हेतु लिखें: <code>all</code>"

    nav_btns = []
    if target_page > 0:
        nav_btns.append(InlineKeyboardButton(f"◀️ पेज {target_page}/3", callback_data=f"trpage_{target_page - 1}"))
    if end_idx < len(lines):
        nav_btns.append(InlineKeyboardButton(f"पेज {target_page + 2}/3 ▶️", callback_data=f"trpage_{target_page + 1}"))

    keyboard = [nav_btns] if nav_btns else []
    keyboard.append([InlineKeyboardButton("🔙 मुख्य मेनू (Back)", callback_data="tr_back_root")])

    await query.message.edit_text(p_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ================= MONTHLY, YEARLY, WEEKLY =================
@ensure_auth
async def monthly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    months = ["October 2026", "September 2026", "August 2026", "July 2026", "June 2026", "May 2026"]
    keyboard = [[InlineKeyboardButton(f"📁 {m} संपूर्ण मासिक डाइजेस्ट", callback_data=f"genmonth_{m}")] for m in months]
    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")])
    await update.message.reply_text("📁 <b>जिस महीने का संपूर्ण UPSC मंथली कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    years = ["2026", "2025", "2024"]
    keyboard = [[InlineKeyboardButton(f"📚 वर्ष {y} वार्षिक महा-संकलन (PT-365)", callback_data=f"genyear_{y}")] for y in years]
    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")])
    await update.message.reply_text("🏛️ <b>जिस वर्ष का संपूर्ण UPSC वार्षिक कंपाइलेशन (PT-365 Style) चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = get_ist_now()
    days_since_monday = today.weekday()
    start_of_current_week = today - timedelta(days=days_since_monday)
    current_week_str = f"{start_of_current_week.strftime('%d %b')} से {today.strftime('%d %b %Y')}"

    keyboard = [
        [InlineKeyboardButton(f"🗓 चालू सप्ताह ({current_week_str}) - आज तक", callback_data=f"genweek_current_{today.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🗓 <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ================= DYNAMIC GENERATION PROCESSOR (NOTES) =================
async def handle_dynamic_generation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    try:
        await query.message.delete()
    except Exception:
        pass

    asyncio.create_task(process_dynamic_generation(user_id, data, context))

async def process_dynamic_generation(user_id, data, context):
    if data.startswith("gendate_"):
        target_date = data.split("_")[1]
        arch_data = get_archive_by_date(target_date)
        if arch_data:
            topic, html_content = arch_data
            filename = f"UPSC_Notes_{target_date.replace('-', '')}.html"
        else:
            wait_m = await context.bot.send_message(
                chat_id=user_id, 
                text=f"🏛 <b>UPSC STUDY DESK</b>\n\n📅 <b>दिनांक:</b> <code>{target_date}</code>\n🔄 The Hindu, PIB, Vision IAS व Drishti से 360° संकलन जारी...",
                parse_mode=ParseMode.HTML
            )
            prompt = f"""
तारीख: "{target_date}" के लिए संपूर्ण, 360° और अत्यंत विस्तृत UPSC समसामयिक महा-संकलन तैयार करें।
अनिवार्य स्रोत: The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS.
नियम:
1. सभी GS-1 से GS-4 के मुख्य घटनाक्रमों का समग्र विश्लेषण दें।
2. सभी तालिकाओं को केवल शुद्ध HTML (<div class="table-box"><table>...</table></div>) में लिखें।
3. मैपिंग सेक्शन में स्थान का नाम स्पष्ट लिखें।
4. अंत में 5 मानक अभ्यास MCQs जोड़ें। केवल शुद्ध हिंदी भाषा का प्रयोग करें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"दैनिक समसामयिक महा-संकलन — {target_date}"
                filename = f"UPSC_Notes_{target_date.replace('-', '')}.html"
                html_content = build_standalone_master_html(topic, ai_text, date_str=target_date)
                save_to_archive("daily", topic, html_content, target_date)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}")
                return

    elif data.startswith("genmonth_"):
        m_name = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"📁 <b>{m_name}</b> का संपूर्ण विस्तृत मासिक कंपाइलेशन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"माह: '{m_name}' का सम्पूर्ण और अत्यंत विस्तृत UPSC Monthly Digest तैयार करें। GS 1-4, चर्चित स्थल एवं अभ्यास प्रश्नों सहित केवल शुद्ध हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Monthly Digest — {m_name}"
            filename = f"UPSC_Monthly_{m_name.replace(' ', '_')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=m_name)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
            return

    elif data.startswith("genyear_"):
        y_name = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ वर्ष <b>{y_name}</b> का संपूर्ण वार्षिक महा-संकलन (PT-365 Style) तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"वर्ष {y_name} का UPSC हेतु अत्यंत विस्तृत और संपूर्ण Annual Compendium (PT-365 Style) तैयार करें। केवल हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Annual Compendium — {y_name}"
            filename = f"UPSC_Annual_{y_name}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=y_name)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
            return

    elif data.startswith("genweek_"):
        w_date = data.split("_")[2]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ साप्ताहिक संकलन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"सप्ताह के महत्वपूर्ण UPSC घटनाक्रमों का संपूर्ण विस्तृत रिवीजन तैयार करें। केवल हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Weekly Revision — {w_date}"
            filename = f"UPSC_Weekly_{w_date.replace('-', '')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=w_date)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
            return

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open(filename, "rb") as send_doc:
        await context.bot.send_document(
            chat_id=user_id,
            document=send_doc,
            filename=filename,
            caption=f"📄 <b>दस्तावेज़:</b> <code>{topic}</code>\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
            parse_mode=ParseMode.HTML,
        )

    if os.path.exists(filename):
        os.remove(filename)

# ================= TEXT / NUMBER / 'ALL' TRENDING HANDLER =================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)
    user_input = msg.text.strip().lower()
    today = get_ist_now().strftime("%d %B %Y")

    cached_list = TRENDING_CACHE.get(user_id, [])

    if user_input == "all" and cached_list:
        raw_trend = "\n".join(cached_list)
        wait_m = await msg.reply_text("⏳ <b>सभी ट्रेंडिंग मुद्दों</b> के विस्तृत 360° नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
        prompt = f"नीचे दिए गए सभी ट्रेंडिंग मुद्दों पर UPSC स्तर के गहन और 360° संपूर्ण नोट्स तैयार करें:\n{raw_trend}\nकेवल शुद्ध हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Trending Radar All Topics — {today}"
            filename = f"UPSC_Trending_Radar_{get_ist_now().strftime('%Y%m%d')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=today, is_trending=True)
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(filename, "rb") as send_doc:
                await msg.reply_document(
                    document=send_doc,
                    filename=filename,
                    caption=f"📄 <b>ट्रेंडिंग संपूर्ण संकलन:</b> <code>{today}</code>\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
        return

    if re.match(r'^(\d+)(\s*,\s*\d+)*$', user_input) and cached_list:
        nums = [n.strip() for n in user_input.split(',')]
        wait_m = await msg.reply_text(f"⏳ चुने गए ट्रेंडिंग मुद्दे ({', '.join(nums)}) का 360° विस्तृत विश्लेषण तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        raw_trend = "\n".join(cached_list)
        prompt = f"सूची में से क्रमांक {', '.join(nums)} पर मौजूद मुद्दों का UPSC हेतु 360° विश्लेषण तैयार करें:\n{raw_trend}\nकेवल हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Trending Topics {', '.join(nums)} — {today}"
            filename = f"UPSC_Trending_Selected_{get_ist_now().strftime('%Y%m%d')}_{'_'.join(nums)}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=today, is_trending=True)
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(filename, "rb") as send_doc:
                await msg.reply_document(
                    document=send_doc,
                    filename=filename,
                    caption=f"📄 <b>ट्रेंडिंग चयनित मुद्दे:</b> {', '.join(nums)} ({today})\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
        return

# ================= DIRECT PDF TO UPSC 360° HTML =================
async def handle_direct_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = msg.document
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)

    if not is_authorized(user_id):
        await msg.reply_text("⛔ <b>एक्सेस अस्वीकृत:</b> PDF प्रोसेसिंग केवल अधिकृत छात्रों के लिए है। <code>/owner</code> पर संपर्क करें।", parse_mode=ParseMode.HTML)
        return

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        return

    wait_m = await msg.reply_text("📥 <b>PDF प्राप्त हुआ!</b> UPSC 360° HTML नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
    try:
        f_obj = await doc.get_file()
        f_bytes = await f_obj.download_as_bytearray()
        pdf_io = io.BytesIO(f_bytes)
        reader = PdfReader(pdf_io)
        pdf_text = ""
        for page in reader.pages[:18]:
            t = page.extract_text()
            if t:
                pdf_text += t + "\n"

        clean_title = doc.file_name.replace(".pdf", "")[:35]
        prompt = f"नीचे दी गई PDF सामग्री का UPSC सिविल सेवा स्तर पर 360° अध्ययन नोट्स शुद्ध HTML सारणी व मेन्स फ्रेमवर्क सहित तैयार करें:\n{pdf_text[:4500]}\nकेवल हिंदी भाषा का प्रयोग करें।"
        ai_notes = await asyncio.to_thread(call_gemini_safely, prompt)
        html_out = build_standalone_master_html(clean_title, ai_notes)

        out_fname = f"UPSC_{re.sub(r'[^a-zA-Z0-9]', '_', clean_title)[:20]}.html"
        with open(out_fname, "wb") as f:
            f.write(html_out.encode("utf-8"))

        with open(out_fname, "rb") as send_doc:
            await msg.reply_document(
                document=send_doc,
                filename=out_fname,
                caption=f"📄 <b>PDF से जनरेटेड HTML नोट्स:</b> <code>{clean_title}</code>\n👤 <b>संकलनकर्ता:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                parse_mode=ParseMode.HTML
            )
        await wait_m.delete()
        if os.path.exists(out_fname):
            os.remove(out_fname)
    except Exception as e:
        await wait_m.edit_text(f"❌ PDF प्रोसेसिंग में त्रुटि: {e}")

# ================= BROADCAST SYSTEM WITH AUTO-PIN =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END

    await update.message.reply_text(
        f"📢 <b>ब्रॉडकास्ट कंट्रोल रूम ({AUTHOR_NAME}):</b>\n\n"
        "सभी छात्रों को भेजा जाने वाला संदेश, इमेज या पीडीएफ भेजें:\n"
        "<i>(रद्द करने के लिए <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_BROADCAST_MSG

async def execute_broadcast_step1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END

    b_msg = update.message
    all_uids = get_all_user_ids()
    status_m = await update.message.reply_text(f"⏳ ब्रॉडकास्ट भेजा जा रहा है (कुल: {len(all_uids)} छात्र)...")

    succ = 0
    sent_map = {}
    for uid in all_uids:
        try:
            sent_obj = await context.bot.copy_message(chat_id=uid, from_chat_id=admin_id, message_id=b_msg.message_id)
            sent_map[uid] = sent_obj.message_id
            succ += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    LAST_BROADCAST_DATA[admin_id] = sent_map
    await status_m.delete()

    keyboard = [
        [InlineKeyboardButton("📌 हाँ, सभी चैट में पिन करें", callback_data="pin_broadcast_yes")],
        [InlineKeyboardButton("❌ नहीं, सामान्य रहने दें", callback_data="pin_broadcast_no")]
    ]
    await update.message.reply_text(
        f"✅ ब्रॉडकास्ट सफल: <b>{succ} / {len(all_uids)}</b> छात्रों को संदेश प्राप्त हुआ।\n\n"
        "👉 <b>क्या आप इस संदेश को सभी छात्रों के चैट में पिन (Pin) करना चाहते हैं?</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def handle_broadcast_pin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id
    data = query.data

    if data == "pin_broadcast_yes":
        sent_map = LAST_BROADCAST_DATA.get(admin_id, {})
        pinned_cnt = 0
        for uid, mid in sent_map.items():
            try:
                await context.bot.pin_chat_message(chat_id=uid, message_id=mid, disable_notification=True)
                pinned_cnt += 1
                await asyncio.sleep(0.04)
            except Exception:
                pass
        await query.message.edit_text(f"📌 <b>सफल:</b> संदेश को कुल <b>{pinned_cnt}</b> छात्रों के चैट में पिन कर दिया गया है।", parse_mode=ParseMode.HTML)
    else:
        await query.message.edit_text("👌 ठीक है, संदेश को पिन नहीं किया गया।", parse_mode=ParseMode.HTML)

    LAST_BROADCAST_DATA.pop(admin_id, None)

# ================= ADMIN USER MANAGEMENT & /info COMMAND =================
async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("💡 उपयोग: <code>/adduser &lt;user_id&gt; &lt;दिन&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        t_uid = int(context.args[0])
        days = int(context.args[1])
        expiry = get_ist_now() + timedelta(days=days)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, is_vip, vip_expiry, joined_at)
            VALUES (%s, 1, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET is_vip = 1, vip_expiry = %s;
        """, (t_uid, expiry, expiry))
        conn.commit()
        c.close()
        conn.close()
        user_link = f'<a href="tg://user?id={t_uid}">{t_uid}</a>'
        await update.message.reply_text(f"✅ छात्र {user_link} को <b>{days} दिन</b> के लिए अधिकृत कर दिया गया है।", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def remove_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/removeuser &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        t_uid = int(context.args[0])
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = %s", (t_uid,))
        conn.commit()
        c.close()
        conn.close()
        user_link = f'<a href="tg://user?id={t_uid}">{t_uid}</a>'
        await update.message.reply_text(f"🚫 छात्र {user_link} का एक्सेस रद्द कर दिया गया है।", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def info_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/info &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return

    try:
        t_uid = int(context.args[0])
        user_row, daf_row = get_user_full_info(t_uid)
        
        if not user_row:
            await update.message.reply_text(f"❌ इस आईडी (<code>{t_uid}</code>) का कोई सदस्य बॉट में पंजीकृत नहीं है।", parse_mode=ParseMode.HTML)
            return

        uid, un, fn, is_vip, exp, joined = user_row
        user_link = f'<a href="tg://user?id={uid}">{fn or uid}</a>'
        un_str = f"@{un}" if un else "कोई नहीं"
        vip_tag = "👑 [VIP/प्रीमियम सदस्य]" if is_vip == 1 else "👤 [निःशुल्क छात्र]"
        exp_str = exp.strftime('%d-%b-%Y %I:%M %p') if (is_vip == 1 and exp) else "लागू नहीं"
        joined_str = joined.strftime('%d-%b-%Y') if joined else "अज्ञात"

        info_text = (
            f"📋 <b>छात्र प्रोफ़ाइल विवरण (Dossier)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>नाम:</b> {user_link}\n"
            f"🆔 <b>यूज़र ID:</b> <code>{uid}</code>\n"
            f"🔗 <b>यूज़रनेम:</b> {un_str}\n"
            f"🔰 <b>स्थिति:</b> {vip_tag}\n"
            f"⏳ <b>वैधता:</b> <code>{exp_str}</code>\n"
            f"📅 <b>जुड़ने की तिथि:</b> {joined_str}\n\n"
        )

        if daf_row and daf_row[0]:
            name, state, college, status, opt_sub, attempt, updated = daf_row
            info_text += (
                f"🏛 <b>दर्ज DAF (साक्षात्कार प्रोफाइल):</b>\n"
                f"• <b>पूरा नाम:</b> {name}\n"
                f"• <b>गृह राज्य:</b> {state}\n"
                f"• <b>कॉलेज/यूनिवर्सिटी:</b> {college}\n"
                f"• <b>ग्रेजुएशन स्थिति:</b> {status}\n"
                f"• <b>वैकल्पिक विषय:</b> {opt_sub}\n"
                f"• <b>प्रयास संख्या:</b> {attempt}\n"
                f"• <b>अंतिम अपडेट:</b> {updated.strftime('%d-%b-%Y') if updated else 'N/A'}"
            )
        else:
            info_text += "🏛 <b>दर्ज DAF:</b> इस छात्र ने अभी तक <code>/interview</code> कमांड नहीं चलाई है या अपनी DAF प्रोफाइल सेव नहीं की है।"

        await update.message.reply_text(info_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ विवरण निकालने में त्रुटि: {e}")

async def list_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    rows = get_all_users_detailed()
    text = f"👥 <b>पंजीकृत सदस्य (कुल: {len(rows)})</b>\n\n"
    
    text += "👑 <b>प्रशासनिक संरक्षक (Owners):</b>\n"
    for aid in ADMIN_IDS:
        text += f"• <b>{ADMIN_NAMES.get(aid, 'व्यवस्थापक')}</b>: <code>{aid}</code>\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for uid, un, fn, is_vip, exp in rows:
        user_link = f'<a href="tg://user?id={uid}">{fn or uid}</a>'
        vip_tag = "👑 [VIP/प्रीमियम]" if is_vip == 1 else "👤 [निःशुल्क छात्र]"
        exp_str = f" | वैधता: {exp.strftime('%d-%b-%Y')}" if (is_vip == 1 and exp) else ""
        text += f"• {vip_tag} {user_link} (<code>{uid}</code>){exp_str}\n"

    for part in [text[i:i+3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)

# ================= ADMIN DIRECT REPLIES =================
async def handle_admin_reply_or_direct_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return

    if msg.reply_to_message:
        reply_to_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
        match = re.search(r'(?:यूज़र\s*ID|ID)[:\s]*([0-9]{8,11})', reply_to_text) or re.search(r'([0-9]{8,11})', reply_to_text)
        if match:
            target_user_id = int(match.group(1))
            reply_body = msg.text or msg.caption or ""
            user_notification = f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n{reply_body}\n\n📢 <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
            try:
                if msg.text:
                    await context.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                else:
                    await context.bot.copy_message(chat_id=target_user_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
                await msg.reply_text(f"✅ जवाब छात्र (<code>{target_user_id}</code>) को सफलतापूर्वक भेज दिया गया!", parse_mode=ParseMode.HTML)
                return
            except Exception as e:
                await msg.reply_text(f"❌ भेजने में त्रुटि: {e}")
                return

    if msg.text:
        direct_match = re.match(r'^([0-9]{8,11})\s+(.*)$', msg.text.strip(), flags=re.DOTALL)
        if direct_match:
            target_user_id = int(direct_match.group(1))
            reply_body = direct_match.group(2).strip()
            user_notification = f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n{reply_body}\n\n📢 <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
            try:
                await context.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                await msg.reply_text(f"✅ जवाब छात्र (<code>{target_user_id}</code>) को सफलतापूर्वक भेज दिया गया!", parse_mode=ParseMode.HTML)
                return
            except Exception as e:
                await msg.reply_text(f"❌ भेजने में त्रुटि: {e}")
                return

# ================= OWNER FEEDBACK & GLOBAL CANCEL =================
async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    CONTACT_SESSIONS[user.id] = time.time()
    await update.message.reply_text(
        "⏱ <b>2 मिनट का समय सक्रिय है!</b>\n\n"
        f"अपनी समस्या या एक्सेस अनुरोध लिखकर भेजें। यह संदेश सीधे <b>{AUTHOR_NAME}</b> के पास पहुँचेगा।\n\n"
        "<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_CONTACT_MSG

async def forward_contact_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    msg = update.message

    if msg.text and msg.text.strip().lower() == "/cancel":
        CONTACT_SESSIONS.pop(user_id, None)
        await msg.reply_text("प्रक्रिया रद्द कर दी गई।")
        return ConversationHandler.END

    start_t = CONTACT_SESSIONS.get(user_id, 0)
    if time.time() - start_t > 120:
        CONTACT_SESSIONS.pop(user_id, None)
        await msg.reply_text("⚠️ समय समाप्त हो गया। पुनः <code>/owner</code> चलाएं।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a> (<code>{user.id}</code>)'
    alert_text = f"📩 <b>छात्र संदेश ({AUTHOR_NAME}):</b>\n\nप्रेषक: {user_link}\nसंदेश: {msg.text or '[मीडिया]'}"

    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=alert_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    await msg.reply_text(f"✅ <b>संदेश {AUTHOR_NAME} को अग्रेषित कर दिया गया है!</b>", parse_mode=ParseMode.HTML)
    CONTACT_SESSIONS.pop(user_id, None)
    return ConversationHandler.END

async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    INTERVIEW_SESSION.pop(uid, None)
    CONTACT_SESSIONS.pop(uid, None)
    CHECK_ANSWER_CACHE.pop(uid, None)
    context.user_data.clear()
    await update.message.reply_text("🛑 प्रक्रिया निरस्त कर दी गई।", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# ================= BACKGROUND SERVER (RENDER KEEP-ALIVE) =================
async def run_server():
    server = await asyncio.start_server(
        lambda r, w: (w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nUPSC Study Desk Live 24/7"), w.close()),
        "0.0.0.0",
        int(os.environ.get("PORT", 8080))
    )
    asyncio.create_task(server.serve_forever())

# ================= MAIN APPLICATION DISPATCHER =================
async def main():
    await run_server()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CommandHandler("help", help_handler))
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("quiz", quiz_cmd))
    bot_app.add_handler(CommandHandler("mains", mains_special_cmd))
    bot_app.add_handler(CommandHandler("trending", trending_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    # एडमिन कमांड्स
    bot_app.add_handler(CommandHandler("adduser", add_user_cmd))
    bot_app.add_handler(CommandHandler("removeuser", remove_user_cmd))
    bot_app.add_handler(CommandHandler("info", info_user_cmd))
    bot_app.add_handler(CommandHandler("listusers", list_users_cmd))

    # क्विज़ कॉलबैक्स (GS और विषय फ़्लो)
    bot_app.add_handler(CallbackQueryHandler(handle_quiz_gs_choice, pattern=r"^quizgs_"))
    bot_app.add_handler(CallbackQueryHandler(handle_quiz_sub_choice, pattern=r"^quizsub_|^quiz_back_gs"))
    bot_app.add_handler(CallbackQueryHandler(handle_quiz_cnt_choice, pattern=r"^quizcnt_"))

    # मेन्स कॉलबैक्स
    bot_app.add_handler(CallbackQueryHandler(handle_mains_type_choice, pattern=r"^mq_type_"))
    bot_app.add_handler(CallbackQueryHandler(handle_mains_gs_choice, pattern=r"^mq_gs_|^mains_back_root"))
    bot_app.add_handler(CallbackQueryHandler(handle_mains_cnt_choice, pattern=r"^mq_cnt_"))

    # ट्रेंडिंग कॉलबैक्स
    bot_app.add_handler(CallbackQueryHandler(handle_trending_type_selection, pattern=r"^trtype_|^tr_back_root"))
    bot_app.add_handler(CallbackQueryHandler(handle_trending_pages, pattern=r"^trpage_"))
    bot_app.add_handler(CallbackQueryHandler(handle_broadcast_pin_choice, pattern=r"^pin_broadcast_"))
    bot_app.add_handler(CallbackQueryHandler(handle_dynamic_generation_click))

    # 1. साक्षात्कार DAF + वॉयस + अतिरिक्त प्रश्न फ़्लो
    interview_conv = ConversationHandler(
        entry_points=[CommandHandler("interview", interview_flow_start)],
        states={
            DAF_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_name_step)],
            DAF_STATE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_state_step)],
            DAF_COLLEGE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_college_step)],
            DAF_STATUS: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_status_step)],
            DAF_OPTIONAL_STEP: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_optional_step)],
            DAF_ATTEMPT_STEP: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_attempt_step)],
            DAF_QCOUNT: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_qcount_step)],
            WAITING_INTERVIEW_VOICE: [MessageHandler((filters.VOICE | filters.AUDIO) & (~filters.COMMAND), handle_interview_candidate_voice)],
            WAITING_INTERVIEW_DECISION: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_interview_decision)]
        },
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(interview_conv)

    # 2. उत्तर पुस्तिका 2-स्टेप चेकिंग फ़्लो
    answer_check_conv = ConversationHandler(
        entry_points=[CommandHandler("checkanswer", check_answer_cmd)],
        states={
            WAITING_QUESTION_TEXT: [MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO) & (~filters.COMMAND), handle_question_text_step)],
            WAITING_ANSWER_COPY: [MessageHandler((filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), handle_answer_copy_submission)]
        },
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(answer_check_conv)

    # 3. 1-on-1 मेंटरशिप सत्र (/ask)
    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", start_ask_session)],
        states={WAITING_ASK_SESSION: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ask_continuous_message)]},
        fallbacks=[CommandHandler("cancel", global_cancel), CommandHandler("stop", global_cancel), CommandHandler("exit", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(ask_conv)

    # 4. ओनर संपर्क फ़्लो (/owner)
    contact_conv = ConversationHandler(
        entry_points=[CommandHandler("owner", contact_cmd)],
        states={WAITING_CONTACT_MSG: [MessageHandler(filters.ALL & (~filters.COMMAND), forward_contact_msg)]},
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(contact_conv)

    # 5. ब्रॉडकास्ट फ़्लो (/broadcast)
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={WAITING_BROADCAST_MSG: [MessageHandler(filters.ALL & (~filters.COMMAND), execute_broadcast_step1)]},
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(broadcast_conv)

    # एडमिन रिप्लाई
    bot_app.add_handler(MessageHandler(filters.User(ADMIN_IDS) & (filters.REPLY | filters.Regex(r'^[0-9]{8,11}')), handle_admin_reply_or_direct_send))

    # सामान्य डॉक्यूमेंट (PDF से 360° UPSC HTML)
    bot_app.add_handler(MessageHandler(filters.Document.PDF, handle_direct_pdf_upload))

    # टेक्स्ट व ट्रेंडिंग इनपुट
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_messages))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
