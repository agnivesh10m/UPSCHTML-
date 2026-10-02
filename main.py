import os
import re
import time
import asyncio
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import google.generativeai as genai
from pypdf import PdfReader
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# ================= CONFIGURATION =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ADMIN_IDS = [1745425595, 7850454902]
CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "SACHIN SHARMA"

IST = ZoneInfo("Asia/Kolkata")

def get_ist_now():
    return datetime.now(IST)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

WAITING_CONTACT_MSG = 1
WAITING_BROADCAST_MSG = 2
WAITING_ASK_SESSION = 3

CONTACT_SESSIONS = {}
USER_QUIZ_SELECTIONS = {}
TRENDING_CACHE = {}
DB_PATH = "upsc_bot.db"

# ================= DATABASE SETUP =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT,
            is_vip INTEGER DEFAULT 0,
            vip_expiry TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT,
            date_str TEXT,
            month_str TEXT,
            year_str TEXT,
            topic TEXT,
            filename TEXT,
            html_content TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def register_user(user_id, username, first_name):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                username = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username or "", first_name or "", get_ist_now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registering user: {e}")

def is_authorized(user_id):
    if user_id in ADMIN_IDS:
        return True
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT is_vip, vip_expiry FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0] == 1:
            if row[1]:
                expiry = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                if get_ist_now() <= expiry:
                    return True
            else:
                return True
    except Exception as e:
        print(f"Auth error: {e}")
    return False

def save_to_archive(period, topic, filename, html_content, date_str=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = get_ist_now()
        t_str = date_str if date_str else now.strftime("%Y-%m-%d")
        month_str = now.strftime("%B %Y")
        year_str = now.strftime("%Y")
        c.execute("""
            INSERT INTO archive (period, date_str, month_str, year_str, topic, filename, html_content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (period, t_str, month_str, year_str, topic, filename, html_content))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error archiving: {e}")

def get_archive_by_date(date_str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT topic, filename, html_content FROM archive WHERE date_str = ? ORDER BY id DESC LIMIT 1", (date_str,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception:
        return None

def get_archive_by_period_name(period, p_name):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if period == "monthly":
            c.execute("SELECT topic, filename, html_content FROM archive WHERE period = 'monthly' AND month_str = ? ORDER BY id DESC LIMIT 1", (p_name,))
        elif period == "yearly":
            c.execute("SELECT topic, filename, html_content FROM archive WHERE period = 'yearly' AND year_str = ? ORDER BY id DESC LIMIT 1", (p_name,))
        else:
            c.execute("SELECT topic, filename, html_content FROM archive WHERE period = 'weekly' AND topic LIKE ? ORDER BY id DESC LIMIT 1", (f"%{p_name}%",))
        row = c.fetchone()
        conn.close()
        return row
    except Exception:
        return None

def get_all_users_detailed():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry FROM users ORDER BY joined_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ================= ASYNC ENGINE =================
def call_gemini_safely(prompt: str) -> str:
    api_k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_k:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    genai.configure(api_key=api_k)
    generation_config = {
        "temperature": 0.25,
        "max_output_tokens": 8192,
    }

    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro",
        "gemini-2.5-flash",
        "gemini-1.5-flash"
    ]

    last_err = None
    for m_name in models_to_try:
        try:
            model = genai.GenerativeModel(m_name, generation_config=generation_config)
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text
        except Exception as e:
            last_err = e
            continue

    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                model = genai.GenerativeModel(m.name, generation_config=generation_config)
                resp = model.generate_content(prompt)
                if resp and resp.text:
                    return resp.text
    except Exception as e:
        last_err = e

    raise Exception(f"AI सर्वर कनेक्ट नहीं हो सका: {last_err}")

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

    key_locations = ["कूनो", "गांधी सागर", "मन्नार की खाड़ी", "कच्छ का रण", "होर्मुज़", "लाल सागर", "अंडमान", "पश्चिमी घाट", "लद्दाख", "ताइवान", "रामसर स्थल"]
    for loc in key_locations:
        if loc in text:
            vector_card = create_standalone_vector_map(loc)
            text = re.sub(rf'({loc}[^<\n]*)', r'\1' + vector_card, text, count=1)
            break

    return text

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
            clean_tab_name = re.sub(r'^[0-9]+\s*[:\.\-]?\s*', '', clean_tab_name).strip()
            clean_tab_name = re.sub(r'[📌🎯⚡📖💡🗳⚖️🔍📝🛣️❄️🌏📰🌍🌱🔬💰🔑📚🔸|━─—_:-]', '', clean_tab_name).strip()
            
            if not clean_tab_name:
                clean_tab_name = f"विषय {sec_idx}"
            if len(clean_tab_name) > 22:
                clean_tab_name = clean_tab_name[:20] + ".."
            
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
[data-theme="dark"] {{
  --bg: #0b1120; --card: #1e293b; --text: #f1f5f9; --muted: #94a3b8; --border: #334155;
  --accent: #38bdf8; --accent-dark: #0284c7; --tag-bg: #0f2e4a; --tag-text: #7dd3fc;
  --shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  background: var(--bg); color: var(--text); font-family: 'Hind', 'Noto Sans Devanagari', sans-serif;
  line-height: 1.8; transition: background 0.3s, color 0.3s; padding-bottom: 80px;
}}
@media print {{
  body::before {{
    content: "SACHIN SHARMA | @UPSCHTML";
    position: fixed; top: 40%; left: 5%; width: 90%; text-align: center;
    font-size: 4.5rem; font-weight: 900; color: rgba(0, 0, 0, 0.50);
    transform: rotate(-35deg); z-index: 9999; pointer-events: none; letter-spacing: 8px;
  }}
  .controls, nav.dashboard, #telegramBtn, .print-btn, .theme-btn {{ display: none !important; }}
  .news-card {{ box-shadow: none !important; border: 1px solid #ccc !important; page-break-inside: avoid; margin-bottom: 25px !important; }}
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
.sub-title {{ font-size: 1.1rem; color: var(--accent-dark); margin: 16px 0 8px; font-weight: 700; }}
.para {{ margin: 8px 0; font-size: 1rem; word-break: break-word; text-align: justify; }}
.table-box {{ overflow-x: auto; margin: 16px 0; width: 100%; border-radius: 8px; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ background: var(--accent); color: #fff; padding: 11px 13px; font-size: 0.92rem; font-weight: 600; }}
td {{ padding: 11px 13px; border-bottom: 1px solid var(--border); font-size: 0.92rem; vertical-align: top; }}
tr:nth-child(even) td {{ background: rgba(128, 128, 128, 0.04); }}
.mains-point {{ margin: 10px 0; padding-left: 8px; border-left: 3px solid #cbd5e1; }}
.point-badge-intro {{ background: #0284c7; color: #fff; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }}
.point-badge-body {{ color: var(--accent-dark); font-weight: 700; font-size: 1rem; margin: 8px 0 4px; }}
.point-badge-wf {{ background: #10b981; color: #fff; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }}
.point-badge-conc {{ background: #f59e0b; color: #000; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }}
.img-figure {{
  margin: 18px 0; text-align: center; background: #ffffff; padding: 10px;
  border-radius: 10px; border: 1px solid #bae6fd; box-shadow: var(--shadow);
}}
[data-theme="dark"] .img-figure {{ background: #1e293b; border-color: #0369a1; }}
.img-figure figcaption {{ font-size: 0.88rem; color: #0369a1; margin-top: 8px; font-weight: 700; }}
[data-theme="dark"] .img-figure figcaption {{ color: #7dd3fc; }}
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
  <div class="controls">
    <input type="text" id="searchBox" placeholder="🔍 खोजें: GS विषय, अनुच्छेद, कीवर्ड...">
    <button onclick="toggleTheme()" class="theme-btn">🌗 डार्क / लाइट</button>
    <button onclick="window.print()" class="print-btn">🖨️ प्रिंट / सेव PDF</button>
  </div>
</header>

<nav class="dashboard">
  <div class="nav-wrap">
    {nav_links}
  </div>
</nav>

<main class="wrap" id="mainContent">

  <section id="sec-overview" class="overview-box">
    <div class="overview-title">📌 {overview_title}</div>
    <p class="para"><strong>📅 दिनांक:</strong> {display_date} (IST)</p>
    <p class="para"><strong>🎯 संकलन आयाम:</strong> 360° समग्र विश्लेषण, 2-कॉलम सारणी, मानक भौगोलिक मानचित्र एवं मुख्य परीक्षा उत्तर-लेखन फ्रेमवर्क।</p>
    <p class="para"><strong>📰 अधिकृत स्रोत:</strong> The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS, Sanskriti IAS।</p>
  </section>

  {final_body}

</main>

<button id="telegramBtn" onclick="window.open('{CHANNEL_LINK}','_blank')">📲 TELEGRAM — {CHANNEL_NAME}</button>

<footer>
  <div><b>UPSC CIVIL SERVICES EXAMINATION COMPREHENSIVE STUDY DESK</b></div>
  <div style="margin-top:6px;">संकलन एवं प्रस्तुति: <b>{AUTHOR_NAME}</b> | टेलीग्राम: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
  <div style="margin-top:4px; font-size:0.8rem; color:#94a3b8;">कॉपीराइट सुरक्षित © {get_ist_now().strftime('%Y')} | केवल शैक्षणिक एवं स्व-अध्ययन हेतु</div>
</footer>

<script>
function toggleTheme() {{
  const b = document.body;
  b.setAttribute('data-theme', b.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
}}

document.getElementById('searchBox').addEventListener('input', function() {{
  const q = this.value.trim().toLowerCase();
  document.querySelectorAll('.news-card').forEach(card => {{
    card.style.display = card.innerText.toLowerCase().includes(q) ? 'block' : 'none';
  }});
}});
</script>
</body>
</html>"""

# ================= PUBLIC MENU & PERMISSION ENFORCEMENT =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    is_admin = user.id in ADMIN_IDS

    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    admin_badge = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if is_admin else "📚 <b>UPSC CSE स्मार्ट अध्ययन पोर्टल</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user_link}!</b>\n\n"
        f"{admin_badge}"
        "नीचे सभी मुख्य कमांड्स उपलब्ध हैं:\n\n"
        "📖 <b>अध्ययन एवं नोट्स:</b>\n"
        "• <code>/daily</code> — दैनिक नोट्स (IST कैलेंडर)\n"
        "• <code>/trending</code> — दैनिक, मासिक व वार्षिक ट्रेंडिंग रडार\n"
        "• <code>/quiz</code> — लाइव इंटरएक्टिव टेलीग्राम पोल क्विज़\n"
        "• <code>/mains</code> — मुख्य परीक्षा विशेष उत्तर लेखन प्रश्न\n"
        "• <code>/interview</code> — मॉक साक्षात्कार प्रश्न व वॉयस उत्तर\n"
        "• <code>/weekly</code> — साप्ताहिक क्विक रिवीजन (केवल आज तक)\n"
        "• <code>/monthly</code> — संपूर्ण मासिक संकलन डाइजेस्ट\n"
        "• <code>/yearly</code> — वार्षिक महा-संकलन (PT-365 Style)\n"
        "• <code>/ask</code> — निरंतर यूपीएससी मेंटरशिप सत्र (Continuous Session)\n\n"
        "🛠 <b>प्रशासनिक व निर्माण कमांड्स:</b>\n"
        "• <code>/generate &lt;तारीख/विषय&gt;</code> — नोट्स निर्माण\n"
        "• <code>/broadcast</code> — सभी छात्रों को वीडियो/फ़ोटो/टेक्स्ट संदेश भेजें\n"
        "• <code>/listusers</code> — सभी पंजीकृत छात्रों की प्रीमियम सूची देखें\n"
        "• <code>/adduser</code> | <code>/removeuser</code> — मेंबरशिप संभालें\n\n"
        "💬 <b>सहायता व संपर्क:</b>\n"
        "• <code>/owner</code> — सचिन शर्मा से सीधे संपर्क करें\n"
        "• <code>/help</code> — संपूर्ण उपयोग मार्गदर्शिका\n\n"
        f"📢 <b>ऑफिशियल ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    help_text = (
        f"📖 <b>UPSC SMART DESK — सहायता केंद्र ({AUTHOR_NAME})</b>\n\n"
        "1️⃣ <b>दैनिक, मासिक व वार्षिक नोट्स:</b> The Hindu, PIB, Vision IAS, Sanskriti IAS व Drishti IAS के समन्वय से तैयार संपूर्ण 360° नोट्स।\n\n"
        "2️⃣ <b>लाइव क्विज़ (`/quiz`):</b> सीधे टेलीग्राम पर इंटरएक्टिव पोल के रूप में प्रश्न हल करें।\n\n"
        "3️⃣ <b>निरंतर मेंटरशिप (`/ask`):</b> सत्र शुरू होने के बाद सीधे सवाल पूछते रहें। बाहर निकलने के लिए <code>/exit</code> भेजें।\n\n"
        "4️⃣ <b>इंटरव्यू व मेन्स (`/interview`, `/mains`):</b> साक्षात्कार प्रश्नों के साथ वॉयस ऑडियो उत्तर प्राप्त करें।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# /daily
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now()
    keyboard = []
    
    for i in range(-5, 4):
        target_dt = today + timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        label = f"🌟 आज ({d_str})" if i == 0 else (f"📅 {d_str} (-{-i} दिन)" if i < 0 else f"🔮 {d_str} (+{i} दिन)")
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 <b>जिस तारीख के UPSC दैनिक नोट्स चाहिए, उस बटन पर क्लिक करें:</b>", reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# ================= TELEGRAM NATIVE POLL QUIZ =================
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    keyboard = [
        [InlineKeyboardButton("🏛 राजव्यवस्था (Polity)", callback_data="tpoll_polity"), InlineKeyboardButton("💰 अर्थव्यवस्था (Economy)", callback_data="tpoll_economy")],
        [InlineKeyboardButton("🌿 पर्यावरण (Environment)", callback_data="tpoll_env"), InlineKeyboardButton("🔬 विज्ञान एवं टेक (Sci & Tech)", callback_data="tpoll_scitech")],
        [InlineKeyboardButton("🧭 इतिहास एवं भूगोल", callback_data="tpoll_histgeo"), InlineKeyboardButton("⚡ आज के करेंट अफेयर्स", callback_data="tpoll_todayca")]
    ]
    await update.message.reply_text("🎯 <b>किस विषय का लाइव टेलीग्राम पोल टेस्ट लगाना चाहते हैं?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_native_poll_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subj_code = query.data.replace("tpoll_", "")
    user_id = query.from_user.id
    
    subj_map = {
        "polity": "भारतीय राजव्यवस्था एवं संविधान", "economy": "भारतीय अर्थव्यवस्था एवं बजट",
        "env": "पर्यावरण, पारिस्थितिकी एवं जैव विविधता", "scitech": "विज्ञान एवं प्रौद्योगिकी",
        "histgeo": "इतिहास, कला-संस्कृति एवं भूगोल", "todayca": f"दैनिक करेंट अफेयर्स ({get_ist_now().strftime('%d %B %Y')})"
    }
    subj = subj_map.get(subj_code, "सामान्य अध्ययन")

    wait_m = await query.message.reply_text(f"⏳ <b>{subj}</b> के उच्च-स्तरीय UPSC प्रश्न पोल तैयार हो रहे हैं...", parse_mode=ParseMode.HTML)
    
    prompt = f"""
विषय: '{subj}' पर UPSC Prelims स्तर के 3 उच्च-स्तरीय प्रश्न JSON प्रारूप में तैयार करें।
प्रारूप:
[
  {{
    "question": "प्रश्न का पूरा पाठ (कथनों सहित)?",
    "options": ["विकल्प A", "विकल्प B", "विकल्प C", "विकल्प D"],
    "correct_option_id": 0,
    "explanation": "2 पंक्ति की आधिकारिक व्याख्या।"
  }}
]
केवल वैध JSON दें। कोई मार्कडाउन बाड़ या अतिरिक्त शब्द न लिखें।
"""
    try:
        raw_resp = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_json = re.sub(r'^```json\s*', '', raw_resp.strip(), flags=re.IGNORECASE)
        clean_json = re.sub(r'^```\s*', '', clean_json)
        clean_json = re.sub(r'\s*```$', '', clean_json)
        
        q_data = json.loads(clean_json)
        await wait_m.delete()

        for item in q_data[:3]:
            q_text = item["question"][:290]
            opts = [o[:95] for o in item["options"][:4]]
            corr_id = int(item["correct_option_id"])
            exp = item.get("explanation", "UPSC आधिकारिक संदर्भ")[:190]
            
            await context.bot.send_poll(
                chat_id=user_id,
                question=f"📚 [{subj[:20]}]\n{q_text}",
                options=opts,
                type="quiz",
                correct_option_id=corr_id,
                explanation=exp,
                is_anonymous=False
            )
            await asyncio.sleep(0.5)
            
    except Exception as e:
        await wait_m.edit_text(f"❌ पोल बनाने में त्रुटि: {e}। कृपया पुनः प्रयास करें।")

# ================= UPSC MAINS SPECIAL =================
async def mains_special_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today_str = get_ist_now().strftime("%d %B %Y")
    
    wait_m = await update.message.reply_text("✍️ <b>UPSC मुख्य परीक्षा (Mains) दैनिक उत्तर लेखन प्रश्न संकलित हो रहा है...</b>", parse_mode=ParseMode.HTML)
    prompt = f"""
आज {today_str} के ज्वलंत समसामयिक मुद्दों के आधार पर UPSC मुख्य परीक्षा (GS-1, 2, 3) के लिए 2 अत्यंत मानक प्रश्न और उनका व्यापक उत्तर-लेखन फ्रेमवर्क तैयार करें।
प्रारूप:
- प्रश्न (250 शब्द, 15 अंक)
- भूमिका (Introduction: डेटा/अनुच्छेद/संदर्भ)
- मुख्य भाग (Body: 3 बहुआयामी बिंदु)
- आगे की राह (Way Forward)
- संतुलित निष्कर्ष
मार्कडाउन स्टार्स का प्रयोग न करें।
"""
    try:
        resp = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_text = clean_all_markdown_and_fix_content(resp)
        topic = f"UPSC Mains Practice — {today_str}"
        filename = f"UPSC_Mains_{get_ist_now().strftime('%Y%m%d')}.html"
        html_out = build_standalone_master_html(topic, clean_text, date_str=today_str)
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_out)
        with open(filename, "rb") as send_doc:
            await update.message.reply_document(
                document=send_doc,
                filename=filename,
                caption=f"📝 <b>UPSC मुख्य परीक्षा उत्तर-लेखन मॉड्यूल:</b> <code>{today_str}</code>\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                parse_mode=ParseMode.HTML
            )
        if os.path.exists(filename):
            os.remove(filename)
        await wait_m.delete()
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

# ================= UPSC INTERVIEW & VOICE (TTS) ENGINE =================
async def interview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    wait_m = await update.message.reply_text("🎙️ <b>UPSC साक्षात्कार बोर्ड कक्ष से सिमुलेशन प्रश्न तैयार हो रहा है...</b>", parse_mode=ParseMode.HTML)
    
    prompt = """
UPSC व्यक्तित्व परीक्षण (Interview / Personality Test) के लिए एक गंभीर, प्रशासनिक एवं नीतिगत स्थितिजन्य प्रश्न (Situational Question) तैयार करें।
साथ ही उसका 2 पंक्ति का संतुलित प्रशासनिक उत्तर दें। 
मार्कडाउन स्टार्स का प्रयोग न करें।
"""
    try:
        resp = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_text = resp.strip()
        
        encoded_text = urllib.parse.quote(clean_text[:250])
        tts_url = f"https://all-api-free-text-to-speech-v1-five.vercel.app/api/tts?text={encoded_text}&lang=hi"
        
        await wait_m.delete()
        await update.message.reply_text(
            f"🏛 <b>UPSC साक्षात्कार बोर्ड सिमुलेशन:</b>\n\n{clean_text}\n\n📢 <i>नीचे बोर्ड मेंटर का ऑडियो उत्तर सुनें:</i>",
            parse_mode=ParseMode.HTML
        )
        try:
            await update.message.reply_voice(voice=tts_url, caption=f"🎙️ साक्षात्कार मार्गदर्शन | {AUTHOR_NAME}")
        except Exception:
            pass
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

# ================= CONTINUOUS ASK MENTORSHIP SESSION =================
async def start_ask_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल अधिकृत छात्रों के लिए उपलब्ध है।\n"
            f"एडमिन ({AUTHOR_NAME}) से एक्सेस हेतु <code>/owner</code> पर संपर्क करें।",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎓 <b>UPSC 1-on-1 मेंटरशिप सत्र सक्रिय हो गया है!</b>\n\n"
        "आप UPSC सिविल सेवा परीक्षा (GS 1-4, करेंट अफेयर्स, वैकल्पिक विषय व निबंध) से जुड़ा कोई भी सवाल लगातार पूछते रह सकते हैं।\n\n"
        "👉 <i>सत्र समाप्त करने के लिए कभी भी <code>/exit</code> या <code>/stop</code> भेजें।</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_ASK_SESSION

async def handle_ask_continuous_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_query = update.message.text.strip()

    if user_query.lower() in ["/exit", "/stop", "exit", "stop", "रद्द", "बंद"]:
        await update.message.reply_text("✅ <b>मेंटरशिप सत्र समाप्त हुआ।</b> अध्ययन जारी रखें और शुभकामनाएं!", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    blocked_non_upsc = [
        r"मेरा नाम", r"तुम्हारा नाम", r"आपका नाम", r"तुम कौन", r"आप कौन",
        r"हेलो", r"हाय", r"hello", r"hi", r"hey", r"कैसे हो", r"क्या कर रहे",
        r"शायरी", r"मजाक", r"मौसम", r"गाना", r"लव", r"प्यार", r"गर्लफ्रेंड",
        r"बॉयफ्रेंड", r"joke", r"time pass", r"who are you", r"what is your name",
        r"my name", r"bot", r"robot"
    ]
    if any(re.search(pat, user_query, re.IGNORECASE) for pat in blocked_non_upsc) or len(user_query) < 5:
        await update.message.reply_text(
            "⚠️ <b>अमान्य प्रश्न:</b> इस संबंध में हम कोई जानकारी नहीं रखते हैं।\n\n"
            "यह डेस्क केवल <b>संघ लोक सेवा आयोग (UPSC CSE)</b> पाठ्यक्रम (GS 1-4, करेंट अफेयर्स व समसामयिक व्यक्तित्व) के गंभीर अकादमिक विमर्श हेतु समर्पित है। कृपया परीक्षा संबंधी विषय ही पूछें।",
            parse_mode=ParseMode.HTML
        )
        return WAITING_ASK_SESSION

    wait_msg = await update.message.reply_text("🤔 UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")
    try:
        prompt = f"""
आप UPSC मेंटर हैं। निम्नलिखित विषय का बिंदुवार, सटीक एवं संतुलित प्रशासनिक विश्लेषण दें।
विषय: '{user_query}'
सख्त नियम: मार्कडाउन स्टार्स का प्रयोग न करें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = clean_all_markdown_and_fix_content(reply_text)

        if len(clean_reply) > 3800:
            parts = [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]
            await wait_msg.delete()
            for p in parts:
                await update.message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await wait_msg.edit_text(clean_reply, parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ उत्तर संकलित करने में समस्या आई: {e}")
        
    return WAITING_ASK_SESSION

# ================= TRENDING RADAR WITH ROBUST FALLBACK =================
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("⚡ आज के मुख्य ट्रेंडिंग मुद्दे (Daily)", callback_data="trtype_daily")],
        [InlineKeyboardButton("📁 इस महीने के शीर्ष ट्रेंडिंग मुद्दे (Monthly)", callback_data="trtype_monthly")],
        [InlineKeyboardButton("📚 वर्ष भर के सबसे बड़े ट्रेंडिंग मुद्दे (Yearly)", callback_data="trtype_yearly")]
    ]
    await update.message.reply_text("🧭 <b>UPSC TRENDING RADAR: आप किस समयावधि के ट्रेंडिंग मुद्दे देखना चाहते हैं?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_trending_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    tr_type = query.data.replace("trtype_", "")
    
    today = get_ist_now().strftime("%d %B %Y")
    current_month = get_ist_now().strftime("%B %Y")
    current_year = get_ist_now().strftime("%Y")

    if tr_type == "daily":
        scope_str = f"आज ({today})"
        prompt = f"आज {today} के संदर्भ में UPSC CSE परीक्षा हेतु 9 सबसे महत्वपूर्ण ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें।"
    elif tr_type == "monthly":
        scope_str = f"माह ({current_month})"
        prompt = f"माह {current_month} के 9 सबसे महत्वपूर्ण नीतिगत, अंतर्राष्ट्रीय एवं पर्यावरणीय ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें।"
    else:
        scope_str = f"वर्ष {current_year}"
        prompt = f"वर्ष {current_year} के 9 सबसे बड़े राष्ट्रीय व वैश्विक ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें।"

    wait_m = await query.message.reply_text(f"🛰 <b>{scope_str}</b> के ट्रेंडिंग मुद्दों का रडार संकलन हो रहा है...", parse_mode=ParseMode.HTML)
    try:
        raw_text = await asyncio.to_thread(call_gemini_safely, prompt)
        
        # सुरक्षित पार्सिंग जो कभी खाली नहीं जाएगी
        clean_lines = []
        for l in raw_text.split('\n'):
            line = l.strip()
            if line and len(line) > 5 and not line.startswith('#'):
                clean_lines.append(re.sub(r'^\*+\s*', '', line))
                
        if len(clean_lines) < 3:
            clean_lines = [
                "1. वैश्विक जलवायु वित्त एवं COP शिखर सम्मेलन रणनीति",
                "2. भारत-यूरोपीय संघ व्यापक मुक्त व्यापार समझौता (FTA) विमर्श",
                "3. राष्ट्रीय आर्टिफिशियल इंटेलिजेंस (AI) सुरक्षा व डेटा संप्रभुता",
                "4. वैश्विक ऊर्जा संकट और भारत का हरित हाइड्रोजन कॉरिडोर",
                "5. अंतरराष्ट्रीय समुद्री जैव विविधता संधि (BBNJ) का क्रियान्वयन",
                "6. राष्ट्रीय सेमीकंडक्टर मिशन 2.0 और आपूर्ति श्रृंखला लचीलापन",
                "7. वैश्विक खाद्य सुरक्षा एवं जलवायु-अनुकूल कृषि पद्धतियां",
                "8. महत्वपूर्ण खनिज साझेदारी (Mineral Security Partnership)",
                "9. कार्बन बॉर्डर एडजस्टमेंट मैकेनिज्म (CBAM) एवं भारतीय विनिर्माण"
            ]

        TRENDING_CACHE[user_id] = clean_lines

        p_text = f"🧭 <b>UPSC TRENDING RADAR — {scope_str} (पेज 1/3)</b>\n\n" + "\n\n".join(clean_lines[:3])
        p_text += "\n\n━━━━━━━━━━━━━━━━━━━━\n👉 <b>विकल्प:</b>\n• किसी मुद्दे के पूर्ण नोट्स हेतु नंबर भेजें (उदा. <code>1, 2</code>)\n• सभी मुद्दों के 360° नोट्स हेतु लिखें: <code>all</code>"

        keyboard = [[InlineKeyboardButton("अगला पेज (4-6) ▶", callback_data="trpage_1")]]
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
        nav_btns.append(InlineKeyboardButton("◀️ पिछला पेज", callback_data=f"trpage_{target_page - 1}"))
    if end_idx < len(lines):
        nav_btns.append(InlineKeyboardButton("अगला पेज ▶️", callback_data=f"trpage_{target_page + 1}"))

    await query.message.edit_text(p_text, reply_markup=InlineKeyboardMarkup([nav_btns]), parse_mode=ParseMode.HTML)

# /monthly
async def monthly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    months = ["October 2026", "September 2026", "August 2026", "July 2026", "June 2026", "May 2026"]
    keyboard = [[InlineKeyboardButton(f"📁 {m} संपूर्ण मासिक डाइजेस्ट", callback_data=f"genmonth_{m}")] for m in months]
    await update.message.reply_text("📁 <b>जिस महीने का संपूर्ण UPSC मंथली कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# /yearly
async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    years = ["2026", "2025", "2024"]
    keyboard = [[InlineKeyboardButton(f"📚 वर्ष {y} वार्षिक महा-संकलन (PT-365)", callback_data=f"genyear_{y}")] for y in years]
    await update.message.reply_text("🏛️ <b>जिस वर्ष का संपूर्ण UPSC वार्षिक कंपाइलेशन (PT-365 Style) चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# /weekly
async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now()
    
    days_since_monday = today.weekday()
    start_of_current_week = today - timedelta(days=days_since_monday)
    current_week_str = f"{start_of_current_week.strftime('%d %b')} से {today.strftime('%d %b %Y')}"

    last_week_end = start_of_current_week - timedelta(days=1)
    last_week_start = last_week_end - timedelta(days=6)
    last_week_str = f"{last_week_start.strftime('%d %b')} से {last_week_end.strftime('%d %b %Y')}"

    keyboard = [
        [InlineKeyboardButton(f"🗓️ चालू सप्ताह ({current_week_str}) - आज तक", callback_data=f"genweek_current_{today.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton(f"🗓️ पिछला पूर्ण सप्ताह ({last_week_str})", callback_data=f"genweek_last_{last_week_end.strftime('%Y-%m-%d')}")]
    ]
    await update.message.reply_text("🗓️ <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें (केवल आज तक का वास्तविक कवरेज):</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# डायनामिक बटन क्लिक और केंद्रीय कैशिंग
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
            topic, filename, html_content = arch_data
        else:
            today_str = get_ist_now().strftime("%Y-%m-%d")
            is_future = target_date > today_str
            
            wait_m = await context.bot.send_message(
                chat_id=user_id, 
                text=f"╔════════════════════════╗\n   🏛 <b>UPSC STUDY DESK</b>\n╚════════════════════════╝\n\n📅 <b>दिनांक:</b> <code>{target_date}</code>\n🔄 <b>प्रगति:</b> [1/3] The Hindu, PIB, Vision IAS, Drishti, Sanskriti IAS से संकलन जारी...",
                parse_mode=ParseMode.HTML
            )
            
            future_note = "यह अग्रिम तिथि है। इसमें उस दिन के ऐतिहासिक महत्व, आगामी अंतरराष्ट्रीय शिखर सम्मेलनों, विधायी एजेंडा और संबंधित PYQs का विश्लेषण शामिल करें।" if is_future else ""

            prompt = f"""
आप UPSC सिविल सेवा परीक्षा के शीर्ष विषय विशेषज्ञ हैं।
तारीख: "{target_date}" के लिए 'Zero to Hero' स्तर का, संपूर्ण, 360° आत्मनिर्भर और अत्यंत विस्तृत UPSC करेंट अफेयर्स संकलन तैयार करें।
शीर्षक: "दैनिक समसामयिक महा-संकलन — {target_date}"
{future_note}

अनिवार्य स्रोत: The Hindu, Indian Express, PIB, Yojana, Vision IAS, Sanskriti IAS, Drishti IAS.

सख्त तकनीकी नियम:
1. किसी भी स्थिति में संक्षिप्त या अधूरा उत्तर न छोड़ें। सभी GS-1, GS-2, GS-3, GS-4 के मुख्य घटनाक्रमों का संपूर्ण विश्लेषण दें।
2. सभी तालिकाओं को केवल शुद्ध HTML (<div class="table-box"><table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table></div>) में लिखें।
3. मैपिंग सेक्शन में स्थान का नाम स्पष्ट लिखें (जैसे मन्नार की खाड़ी, कच्छ का रण, होर्मुज़ आदि)।
4. मेन्स फ्रेमवर्क के प्रत्येक बिंदु को पूरा लिखें।
5. अंत में संकलन के मुख्य बिंदुओं पर आधारित 5 मानक अभ्यास MCQs जोड़ें (प्रश्न 1:, प्रश्न 2:... प्रारूप में)।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"दैनिक समसामयिक महा-संकलन — {target_date}"
                filename = f"UPSC_Notes_{target_date.replace('-', '')}.html"
                html_content = build_standalone_master_html(topic, ai_text, date_str=target_date)
                save_to_archive("daily", topic, filename, html_content, date_str=target_date)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}")
                return

    elif data.startswith("genmonth_"):
        m_name = data.split("_")[1]
        arch_data = get_archive_by_period_name("monthly", m_name)
        if arch_data:
            topic, filename, html_content = arch_data
        else:
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"📁 <b>{m_name}</b> का संपूर्ण विस्तृत मासिक कंपाइलेशन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
            prompt = f"""
माह: '{m_name}' का सम्पूर्ण और अत्यंत विस्तृत UPSC Monthly Current Affairs Digest तैयार करें।
यह किसी दैनिक नोट्स से कई गुना बड़ा, गहन और सभी मुख्य विषयों को समेटे हुए होना चाहिए।
शामिल करें:
1. राजव्यवस्था एवं संविधान (GS-2): मुख्य सुप्रीम कोर्ट निर्णय, विधायी अधिनियम, योजना मैट्रिक्स।
2. अर्थव्यवस्था एवं बजट (GS-3): मौद्रिक नीतियां, व्यापार डेटा, अवसंरचना, औद्योगिक सुधार।
3. पर्यावरण, पारिस्थितिकी एवं जैव विविधता (GS-3): वन्यजीव संरक्षण, रामसर स्थल, जलवायु रिपोर्ट।
4. विज्ञान एवं प्रौद्योगिकी (GS-3): अंतरिक्ष मिशन, रक्षा सौदे, क्वांटम व AI।
5. चर्चित स्थल एवं मैपिंग (Places in News)।
6. इस पूरे महीने पर आधारित अभ्यास MCQs (प्रश्न 1:, प्रश्न 2:... प्रारूप में व्याख्या सहित)।
सभी तालिकाओं को शुद्ध HTML में लिखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Monthly Digest — {m_name}"
                filename = f"UPSC_Monthly_{m_name.replace(' ', '_')}.html"
                html_content = build_standalone_master_html(topic, ai_text, date_str=m_name)
                save_to_archive("monthly", topic, filename, html_content)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}")
                return

    elif data.startswith("genyear_"):
        y_name = data.split("_")[1]
        arch_data = get_archive_by_period_name("yearly", y_name)
        if arch_data:
            topic, filename, html_content = arch_data
        else:
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ वर्ष <b>{y_name}</b> का संपूर्ण वार्षिक महा-संकलन (PT-365 Style) तैयार हो रहा है...", parse_mode=ParseMode.HTML)
            prompt = f"""
वर्ष {y_name} का UPSC Civil Services Examination हेतु अत्यंत विस्तृत और संपूर्ण Annual Compendium (PT-365 Style) तैयार करें।
यह पूरे वर्ष की सबसे प्रामाणिक अध्ययन सामग्री होनी चाहिए। इसे संक्षिप्त न करें।
अनिवार्य खंड:
1. संपूर्ण राजव्यवस्था एवं शासन (Polity & Governance): सभी ऐतिहासिक निर्णय, संवैधानिक संशोधन, केंद्र-राज्य संबंध।
2. आर्थिक विकास (Economic Development): जीडीपी, बैंकिंग सुधार, डिजिटल मुद्रा, उत्पादन से जुड़े प्रोत्साहन (PLI)।
3. पर्यावरण एवं जलवायु परिवर्तन (Environment & Ecology): चीता प्रोजेक्ट, राष्ट्रीय उद्यान, रामसर स्थलों का संपूर्ण मैट्रिक्स।
4. विज्ञान, अंतरिक्ष एवं रक्षा (Sci & Tech, Defense): गगनयान, स्वदेशी रक्षा प्रणालियां, क्वांटम मिशन।
5. चर्चित स्थल एवं मैपिंग (Places in News): पूरे वर्ष चर्चा में रहे 5-6 राष्ट्रीय व वैश्विक स्थल।
6. पूरे वर्ष के घटनाक्रमों पर आधारित अभ्यास MCQs (प्रश्न 1:, प्रश्न 2:... प्रारूप में व्याख्या सहित)।
सभी तालिकाओं को मानक HTML में ही लिखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Annual Compendium — {y_name}"
                filename = f"UPSC_Annual_{y_name}.html"
                html_content = build_standalone_master_html(topic, ai_text, date_str=y_name)
                save_to_archive("yearly", topic, filename, html_content)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}")
                return

    elif data.startswith("genweek_"):
        parts = data.split("_")
        mode = parts[1]
        w_date = parts[2]
        
        today = get_ist_now()
        if mode == "current":
            days_since_mon = today.weekday()
            mon_dt = today - timedelta(days=days_since_mon)
            period_label = f"{mon_dt.strftime('%d %B')} से {today.strftime('%d %B %Y')} (चालू सप्ताह, आज तक)"
            prompt = f"सप्ताह की शुरुआत ({mon_dt.strftime('%Y-%m-%d')}) से लेकर आज ({today.strftime('%Y-%m-%d')}) तक के {days_since_mon + 1} दिनों के महत्वपूर्ण UPSC घटनाक्रमों का संपूर्ण विस्तृत रिवीजन तैयार करें। आगे की किसी भी काल्पनिक तारीख का उल्लेख न करें। अंत में अभ्यास प्रश्न (प्रश्न 1:, प्रश्न 2:... प्रारूप में) अवश्य दें।"
        else:
            period_label = f"विगत पूर्ण सप्ताह (7 दिवसीय रिवीजन)"
            prompt = f"विगत पूर्ण सप्ताह के मुख्य UPSC घटनाक्रमों का संपूर्ण 7-दिवसीय रिवीजन डाइजेस्ट HTML टेबल्स और अभ्यास प्रश्नों के साथ विस्तृत रूप में तैयार करें।"

        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ <b>{period_label}</b> का संपूर्ण रिवीजन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Weekly Revision — {period_label}"
            filename = f"UPSC_Weekly_{w_date.replace('-', '')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=period_label)
            save_to_archive("weekly", topic, filename, html_content)
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
            caption=(
                f"📄 <b>दस्तावेज़:</b> <code>{topic}</code>\n"
                f"📰 <b>कवरेज:</b> The Hindu | PIB | Vision | Drishti | Sanskriti IAS\n"
                f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
            ),
            parse_mode=ParseMode.HTML,
        )

    if os.path.exists(filename):
        os.remove(filename)

# ================= ROBUST ADMIN REPLY & DIRECT ID HANDLER =================
async def handle_admin_reply_or_direct_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    admin_id = update.effective_user.id

    if admin_id not in ADMIN_IDS:
        return

    # 1. यदि एडमिन किसी मैसेज पर रिप्लाई कर रहा है
    if msg.reply_to_message:
        if msg.text and msg.text.strip().lower() == "/broadcast":
            all_uids = get_all_user_ids()
            target_msg = msg.reply_to_message
            status_m = await msg.reply_text(f"⏳ मीडिया ब्रॉडकास्ट प्रारंभ हो रहा है (कुल: {len(all_uids)} छात्र)...")
            succ = 0
            for uid in all_uids:
                try:
                    await context.bot.copy_message(chat_id=uid, from_chat_id=msg.chat_id, message_id=target_msg.message_id)
                    succ += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            await status_m.edit_text(f"✅ सफल ब्रॉडकास्ट: <b>{succ} / {len(all_uids)}</b> छात्रों को मीडिया प्राप्त हुआ!", parse_mode=ParseMode.HTML)
            return

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

    # 2. यदि एडमिन सीधे 'आईडी संदेश' लिखकर भेजता है (जैसे: 6748003505 yes)
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

# ================= TEXT / NUMBER / 'ALL' TRENDING HANDLER =================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)
    user_input = msg.text.strip().lower()
    today = get_ist_now().strftime("%d %B %Y")

    cached_list = TRENDING_CACHE.get(user_id, [])

    if user_input == "all":
        if not cached_list:
            await msg.reply_text("⚠️ पहले <code>/trending</code> चलाकर मुद्दे देखें, फिर 'all' भेजें।", parse_mode=ParseMode.HTML)
            return

        raw_trend = "\n".join(cached_list)
        wait_m = await msg.reply_text("⏳ <b>सभी ट्रेंडिंग मुद्दों</b> के विस्तृत 360° नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
        prompt = f"""
नीचे दिए गए सभी समसामयिक ट्रेंडिंग मुद्दों पर UPSC स्तर के गहन और 360° संपूर्ण नोट्स तैयार करें:
"{raw_trend}"
सख्त नियम:
1. सभी मुद्दों में संदर्भ, चर्चा में क्यों, 2-कॉलम HTML सारणी, मेन्स फ्रेमवर्क अनिवार्य रूप से दें।
2. प्रत्येक विषय के अंत में अभ्यास प्रश्न (प्रश्न 1:, प्रश्न 2:... प्रारूप में) व्याख्या सहित दें।
3. कोई भी कच्चा कोड या पाइप टेबल न लिखें।
"""
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
                    caption=(
                        f"📄 <b>ट्रेंडिंग संपूर्ण संकलन:</b> <code>{today}</code>\n"
                        f"📰 <b>कवरेज:</b> The Hindu | PIB | Indian Express\n"
                        f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                        f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
        return

    if re.match(r'^(\d+)(\s*,\s*\d+)*$', user_input):
        if not cached_list:
            await msg.reply_text("⚠️ कृपया पहले <code>/trending</code> चलाएं, फिर नंबर चुनें।", parse_mode=ParseMode.HTML)
            return

        nums = [n.strip() for n in user_input.split(',')]
        wait_m = await msg.reply_text(f"⏳ चुने गए ट्रेंडिंग मुद्दे ({', '.join(nums)}) का 360° विस्तृत विश्लेषण तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        
        raw_trend = "\n".join(cached_list)
        prompt = f"""
सूची में से क्रमांक {', '.join(nums)} पर मौजूद मुद्दों का UPSC सिविल सेवा परीक्षा हेतु अत्यंत विस्तृत 360° विश्लेषण तैयार करें।
सूची:
"{raw_trend}"
नियम: संदर्भ, 2-कॉलम HTML सारणी, मेन्स फ्रेमवर्क, और अभ्यास प्रश्न (प्रश्न 1:, प्रश्न 2:... प्रारूप में) दें। कोई भी कच्चा कोड न लिखें।
"""
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
                    caption=(
                        f"📄 <b>ट्रेंडिंग चयनित मुद्दे:</b> {', '.join(nums)} ({today})\n"
                        f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                        f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
        return

# ================= DIRECT PDF TO HTML ENGINE =================
async def handle_direct_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = msg.document
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        return

    MAX_FILE_SIZE = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        await msg.reply_text(
            f"⚠️ <b>फ़ाइल का आकार बहुत बड़ा है ({size_mb:.1f} MB)!</b>\n\n"
            "टेलीग्राम केवल <b>20 MB</b> तक की PDF फ़ाइलों को प्रोसेस करने की अनुमति देता है।\n\n"
            "💡 <b>विकल्प:</b>\n"
            "1. मुख्य संपादकीय का टेक्स्ट कॉपी करके सीधे भेजें।\n"
            "2. या इस तारीख के संपूर्ण नोट्स हेतु लिखें: <code>/generate 01 October 2026</code>",
            parse_mode=ParseMode.HTML
        )
        return

    wait_m = await msg.reply_text("📥 <b>PDF प्राप्त हुआ!</b>\nसामग्री निकाली जा रही है व UPSC 360° HTML नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
    temp_pdf = f"temp_{user_id}_{int(time.time())}.pdf"
    
    try:
        f_obj = await doc.get_file()
        await f_obj.download_to_drive(temp_pdf)

        reader = PdfReader(temp_pdf)
        pdf_text = ""
        for page in reader.pages[:15]:
            t = page.extract_text()
            if t:
                pdf_text += t + "\n"

        if not pdf_text.strip():
            await wait_m.edit_text("⚠️ यह PDF स्कैन की गई इमेज जैसी है। कृपया टेक्स्ट-आधारित PDF भेजें।")
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)
            return

        clean_title = doc.file_name.replace(".pdf", "")[:35]
        prompt = f"""
नीचे दी गई PDF सामग्री का UPSC सिविल सेवा परीक्षा के स्तर पर संपूर्ण और व्यवस्थित 360° अध्ययन नोट्स तैयार करें:
शीर्षक: "{clean_title}"
सामग्री:
"{pdf_text[:4000]}"
नियम: 2-कॉलम HTML सारणी, मेन्स फ्रेमवर्क, प्रीलिम्स फैक्ट्स और अभ्यास प्रश्न (प्रश्न 1:, प्रश्न 2:... प्रारूप में) शामिल करें।
"""
        ai_notes = await asyncio.to_thread(call_gemini_safely, prompt)
        html_out = build_standalone_master_html(clean_title, ai_notes)

        out_fname = f"UPSC_{re.sub(r'[^a-zA-Z0-9]', '_', clean_title)[:20]}.html"
        with open(out_fname, "w", encoding="utf-8") as f:
            f.write(html_out)

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
        await wait_m.edit_text(f"❌ PDF प्रोसेसिंग में त्रुटि आई: {e}")
    finally:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)

# ================= ADMIN GENERATE COMMAND =================
async def ai_generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह निर्माणकारी सुविधा केवल एडमिन ({AUTHOR_NAME}) के लिए आरक्षित है।",
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/generate 01 October 2026</code>", parse_mode=ParseMode.HTML)
        return

    query = " ".join(context.args).replace("[", "").replace("]", "").strip()
    status_msg = await update.message.reply_text(
        f"╔════════════════════════╗\n   🏛 <b>UPSC NOTE BUILDER</b>\n╚════════════════════════╝\n\n📌 <b>विषय:</b> <code>{query}</code>\n⚙️ <b>स्थिति:</b> The Hindu, PIB, Vision, Sanskriti व Drishti IAS समन्वय चालू...",
        parse_mode=ParseMode.HTML
    )

    try:
        prompt = f"""
विषय: "{query}" पर 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित UPSC नोट्स तैयार करें।
सख्त नियम:
1. 2-कॉलम HTML सारणी (<div class="table-box"><table>...</table></div>), मेन्स फ्रेमवर्क शुद्ध HTML में लिखें।
2. अंत में अभ्यास प्रश्न (प्रश्न 1:, प्रश्न 2:... प्रारूप में) व्याख्या सहित अवश्य दें।
3. कोई कच्चा कोड न लिखें। मार्कडाउन स्टार्स का प्रयोग न करें।
"""
        ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_topic = f"दैनिक समसामयिक महा-संकलन — {query}"[:40]
        html_output = build_standalone_master_html(clean_topic, ai_text, date_str=query)

        safe_fname = re.sub(r'[^a-zA-Z0-9\u0900-\u097F]', '_', query)[:25]
        filename = f"Current_Affairs_{safe_fname}.html"
        save_to_archive("daily", clean_topic, filename, html_output, date_str=query)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_output)

        with open(filename, "rb") as send_doc:
            await update.message.reply_document(
                document=send_doc,
                filename=filename,
                caption=f"✨ <b>{clean_topic}</b>\n👤 <b>संकलन:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                parse_mode=ParseMode.HTML
            )
        await status_msg.delete()
        if os.path.exists(filename):
            os.remove(filename)
    except Exception as e:
        await status_msg.edit_text(f"❌ त्रुटि: {e}")

# ================= USER MEMBERSHIP MANAGEMENT (ADMIN) =================
async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल एडमिन ({AUTHOR_NAME}) के लिए आरक्षित है।",
            parse_mode=ParseMode.HTML
        )
        return
    if len(context.args) < 2:
        await update.message.reply_text("💡 उपयोग: <code>/adduser &lt;user_id&gt; &lt;days&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        target_uid = int(context.args[0])
        days = int(context.args[1])
        expiry_date = (get_ist_now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, is_vip, vip_expiry, joined_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET is_vip = 1, vip_expiry = ?
        """, (target_uid, expiry_date, get_ist_now().strftime("%Y-%m-%d %H:%M:%S"), expiry_date))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ यूज़र <code>{target_uid}</code> को <b>{days} दिन</b> के लिए अधिकृत कर दिया गया है।", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def remove_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल एडमिन ({AUTHOR_NAME}) के लिए आरक्षित है।",
            parse_mode=ParseMode.HTML
        )
        return
    if not context.args:
        return
    try:
        target_uid = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = ?", (target_uid,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🚫 यूज़र <code>{target_uid}</code> का एक्सेस समाप्त कर दिया गया।", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def list_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल एडमिन ({AUTHOR_NAME}) के लिए आरक्षित है।",
            parse_mode=ParseMode.HTML
        )
        return
    
    rows = get_all_users_detailed()
    if not rows:
        await update.message.reply_text("ℹ️ अभी कोई पंजीकृत सदस्य नहीं हैं।")
        return

    text = f"👥 <b>पंजीकृत छात्रों की संपूर्ण सूची (कुल: {len(rows)})</b>\n\n"
    for uid, un, fn, is_vip, exp in rows:
        user_link = f'<a href="tg://user?id={uid}">{fn}</a>'
        un_str = f"@{un}" if un else "बिना यूज़रनेम"
        vip_tag = "👑 <b>[PREMIUM]</b>" if is_vip == 1 else "👤 [निःशुल्क]"
        exp_str = f" | वैधता: <code>{exp}</code>" if (is_vip == 1 and exp) else ""
        text += f"• {vip_tag} <b>{user_link}</b> (<code>{uid}</code>)\n   {un_str}{exp_str}\n\n"

    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for p in parts:
            await update.message.reply_text(p, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ================= CONTACT / OWNER FEEDBACK =================
async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    user_id = user.id
    CONTACT_SESSIONS[user_id] = time.time()
    await update.message.reply_text(
        "⏱ <b>2 मिनट का समय सक्रिय है!</b>\n\n"
        "अपनी समस्या या सवाल लिखकर भेजें।\n"
        f"यह सीधे <b>{AUTHOR_NAME}</b> के पास पहुँचा दिया जाएगा।\n\n"
        "<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_CONTACT_MSG

async def forward_contact_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    msg = update.message

    if msg.text and msg.text.startswith("/"):
        if msg.text.strip().lower() == "/cancel":
            CONTACT_SESSIONS.pop(user_id, None)
            await msg.reply_text("प्रक्रिया रद्द कर दी गई।")
            return ConversationHandler.END
        else:
            CONTACT_SESSIONS.pop(user_id, None)
            await msg.reply_text("⚠️ <b>सत्र रद्द:</b> आपने कमांड भेज दी थी। ओनर से संपर्क करने हेतु कृपया पुनः <code>/owner</code> चलाएं।", parse_mode=ParseMode.HTML)
            return ConversationHandler.END

    start_time = CONTACT_SESSIONS.get(user_id, 0)
    if time.time() - start_time > 120:
        CONTACT_SESSIONS.pop(user_id, None)
        await msg.reply_text("⚠️ <b>समय समाप्त!</b> पुनः प्रयास हेतु <code>/owner</code> भेजें।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    content_text = msg.text or msg.caption or "[फ़ाइल / मीडिया]"
    username_str = f"@{user.username}" if user.username else "कोई यूज़रनेम नहीं"
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    owner_alert = (
        "📩 <b>नया छात्र संदेश!</b>\n\n"
        f"👤 <b>नाम:</b> {user_link}\n"
        f"🆔 <b>यूज़र ID:</b> <code>{user.id}</code>\n"
        f"🔗 <b>यूज़रनेम:</b> {username_str}\n\n"
        f"💬 <b>संदेश:</b>\n{content_text}\n\n"
        "👉 <i>(छात्र को उत्तर देने हेतु इस मैसेज पर सीधे <b>Reply</b> करें या 'ID संदेश' लिखकर भेजें)</i>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=owner_alert, parse_mode=ParseMode.HTML)
        except Exception as e:
            print(f"Error notifying admin {admin_id}: {e}")

    await msg.reply_text("✅ <b>आपका संदेश ओनर को भेज दिया गया है!</b>", parse_mode=ParseMode.HTML)
    CONTACT_SESSIONS.pop(user_id, None)
    return ConversationHandler.END

# ================= UNIVERSAL BROADCAST SYSTEM =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल एडमिन ({AUTHOR_NAME}) के लिए आरक्षित है।",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    if update.message.reply_to_message:
        target_msg = update.message.reply_to_message
        all_uids = get_all_user_ids()
        status_m = await update.message.reply_text(f"⏳ चयनित मीडिया ब्रॉडकास्ट हो रहा है (कुल: {len(all_uids)} छात्र)...")
        succ = 0
        for uid in all_uids:
            try:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=target_msg.message_id)
                succ += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await status_m.edit_text(f"✅ सफल ब्रॉडकास्ट: <b>{succ} / {len(all_uids)}</b> छात्रों को संदेश प्राप्त हुआ!", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    all_uids = get_all_user_ids()
    await update.message.reply_text(
        f"📢 <b>सार्वजनिक ब्रॉडकास्ट प्रणाली:</b>\n\nकुल पंजीकृत छात्र: <b>{len(all_uids)}</b>\n\n"
        "सभी को भेजा जाने वाला संदेश भेजें (टेक्स्ट, वीडियो, फ़ोटो या दस्तावेज़):\n"
        "<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>", 
        parse_mode=ParseMode.HTML
    )
    return WAITING_BROADCAST_MSG

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END
    b_msg = update.message
    all_uids = get_all_user_ids()
    status_msg = await update.message.reply_text(f"⏳ ब्रॉडकास्ट जारी है... (कुल: {len(all_uids)})")
    success_count = 0
    fail_count = 0

    for uid in all_uids:
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=admin_id, message_id=b_msg.message_id)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    await status_msg.edit_text(f"✅ सफल ब्रॉडकास्ट: <b>{success_count}</b> छात्र | ❌ असफल: {fail_count}", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    CONTACT_SESSIONS.pop(user_id, None)
    await update.message.reply_text("प्रक्रिया रद्द कर दी गई।")
    return ConversationHandler.END

# ================= ZERO-DEPENDENCY KEEP-ALIVE SERVER =================
async def run_server():
    server = await asyncio.start_server(
        lambda r, w: (w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nUPSC Smart Desk Live 24/7"), w.close()),
        "0.0.0.0",
        int(os.environ.get("PORT", 8080))
    )
    asyncio.create_task(server.serve_forever())

# ================= MAIN APPLICATION =================
async def main():
    init_db()
    await run_server()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CommandHandler("help", help_handler))
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("quiz", quiz_cmd))
    bot_app.add_handler(CommandHandler("mains", mains_special_cmd))
    bot_app.add_handler(CommandHandler("interview", interview_cmd))
    bot_app.add_handler(CommandHandler("trending", trending_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    bot_app.add_handler(CommandHandler("generate", ai_generate_cmd))
    bot_app.add_handler(CommandHandler("adduser", add_user_cmd))
    bot_app.add_handler(CommandHandler("removeuser", remove_user_cmd))
    bot_app.add_handler(CommandHandler("listusers", list_users_cmd))

    bot_app.add_handler(CallbackQueryHandler(handle_native_poll_quiz, pattern=r"^tpoll_"))
    bot_app.add_handler(CallbackQueryHandler(handle_trending_type_selection, pattern=r"^trtype_"))
    bot_app.add_handler(CallbackQueryHandler(handle_trending_pages, pattern=r"^trpage_"))
    bot_app.add_handler(CallbackQueryHandler(handle_dynamic_generation_click))

    bot_app.add_handler(MessageHandler(filters.Document.PDF, handle_direct_pdf_upload))

    # निरंतर आस्क मेंटरशिप सत्र (Continuous Ask Session)
    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", start_ask_session)],
        states={WAITING_ASK_SESSION: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ask_continuous_message)]},
        fallbacks=[CommandHandler("exit", cancel), CommandHandler("stop", cancel), CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(ask_conv)

    # ओनर संपर्क सिस्टम
    contact_conv = ConversationHandler(
        entry_points=[CommandHandler("owner", contact_cmd), CommandHandler("contact", contact_cmd)],
        states={WAITING_CONTACT_MSG: [MessageHandler(filters.ALL & (~filters.COMMAND), forward_contact_msg)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(contact_conv)

    # यूनिवर्सल ब्रॉडकास्ट सिस्टम
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={WAITING_BROADCAST_MSG: [MessageHandler(filters.ALL & (~filters.COMMAND), execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(broadcast_conv)

    # एडमिन रिप्लाई हैंडलर
    bot_app.add_handler(MessageHandler(filters.User(ADMIN_IDS) & (filters.REPLY | filters.Regex(r'^[0-9]{8,11}')), handle_admin_reply_or_direct_send))

    # सामान्य टेक्स्ट हैंडलर
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_messages))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
