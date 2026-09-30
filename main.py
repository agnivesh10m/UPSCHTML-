import os
import re
import time
import asyncio
import base64
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiohttp import web
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

CONTACT_SESSIONS = {}
USER_QUIZ_SELECTIONS = {}
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
            INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
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
        else:
            c.execute("SELECT topic, filename, html_content FROM archive WHERE period = 'yearly' AND year_str = ? ORDER BY id DESC LIMIT 1", (p_name,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception:
        return None

def get_all_users():
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
            model = genai.GenerativeModel(m_name)
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text
        except Exception as e:
            last_err = e
            continue

    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                model = genai.GenerativeModel(m.name)
                resp = model.generate_content(prompt)
                if resp and resp.text:
                    return resp.text
    except Exception as e:
        last_err = e

    raise Exception("सर्वर से कनेक्ट करने में असमर्थ।")

# ================= CLEAN & ACCURATE HTML BUILDER WITH COMPLETE SOURCES & FRAMEWORK =================
def clean_stars_and_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'(\*{2,}|_{2,})', '', text)
    return text.strip()

def format_nav_title(title: str, idx: int) -> str:
    clean = re.sub(r'^[\d\.\-\s📌🎯⚡📖💡🗳️⚖️🔍📝🛣️❄️🌏📰🌍🌱🔬💰🔑📚🔸]+', '', title).strip()
    clean = re.sub(r'[*#_~`]', '', clean).strip()
    if '/' in clean:
        parts = [p.strip() for p in clean.split('/') if len(p.strip()) > 2]
        clean = parts[-1] if parts else clean
    clean = clean.replace(':', '').replace('-', '').strip()
    if not clean or len(clean) < 2 or clean in ['.', '/', '-', '_']:
        names = ["चर्चा में क्यों", "संवैधानिक ढांचा", "मुख्य विश्लेषण", "प्रमुख आयाम", "आगे की राह", "प्रीलिम्स फैक्ट्स", "मेन्स फ्रेमवर्क"]
        clean = names[(idx - 1) % len(names)]
    return clean

def build_interactive_dashboard_html(topic: str, raw_text: str) -> str:
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    sections = []
    current_sec_title = "भूमिका एवं सामान्य अवलोकन"
    current_sec_lines = []

    for line in lines:
        is_heading = (
            re.match(r'^[0-9]+\.\s*', line) 
            or line.startswith(('📌', '🎯', '⚡', '📖', '💡', '🗳️', '⚖️', '🔍', '📝', '🛣️', '❄️', '🌏', '📰', '🌍', '🌱', '🔬', '💰', '🔑', '📚', '🔸'))
            or (line.endswith(':') and len(line) < 55)
        )
        if is_heading:
            if current_sec_lines:
                sections.append((current_sec_title, current_sec_lines))
                current_sec_lines = []
            current_sec_title = clean_stars_and_markdown(line)
        else:
            current_sec_lines.append(line)
            
    if current_sec_lines or current_sec_title:
        sections.append((current_sec_title, current_sec_lines))

    nav_links_html = '<a href="#quiz-zone-sec" style="background:#f59e0b; color:#000;">🎯 लाइव टेस्ट / क्विज़</a>\n'
    content_html = ""

    for idx, (sec_title, sec_lines) in enumerate(sections, 1):
        sec_id = f"topic-sec-{idx}"
        clean_nav = format_nav_title(sec_title, idx)
        nav_links_html += f'<a href="#{sec_id}">{clean_nav}</a>\n'

        sec_body_html = ""
        in_pipe_table = False
        pipe_table_rows = []
        i = 0
        n = len(sec_lines)

        while i < n:
            raw_line = sec_lines[i]
            line = clean_stars_and_markdown(raw_line)

            if line.startswith('|') and line.endswith('|') and len(line.split('|')) >= 3:
                cells = [clean_stars_and_markdown(c) for c in line.split('|')[1:-1]]
                if not in_pipe_table:
                    in_pipe_table = True
                    pipe_table_rows.append("<tr>" + "".join([f"<th class='th-cell'>{c}</th>" for c in cells]) + "</tr>")
                elif "---" not in line:
                    pipe_table_rows.append("<tr>" + "".join([f"<td class='td-cell'>{c}</td>" for c in cells]) + "</tr>")
                i += 1
                continue
            elif in_pipe_table:
                sec_body_html += f"<div class='table-box'><table>{''.join(pipe_table_rows)}</table></div>"
                in_pipe_table = False
                pipe_table_rows = []

            is_table_header = (
                any(h in line for h in ["चरण", "विषय", "क्षेत्र", "तकनीक", "प्रावधान", "घटक", "आयाम", "क्रम"]) 
                and (i + 1 < n)
            )
            if is_table_header:
                th1 = line
                th2 = clean_stars_and_markdown(sec_lines[i+1])
                table_html = f"<div class='table-box'><table><tr><th class='th-cell'>{th1}</th><th class='th-cell'>{th2}</th></tr>"
                i += 2
                while i + 1 < n:
                    c1 = clean_stars_and_markdown(sec_lines[i])
                    c2 = clean_stars_and_markdown(sec_lines[i+1])
                    if (
                        len(c1) > 65 
                        or c1.startswith(('•', '-', '①', '②', '③', '④', '⑤', '1.', '2.', '3.'))
                        or any(c1.startswith(x) for x in ["📌", "🎯", "⚡", "📖", "💡", "📝", "🔑", "📚"])
                    ):
                        break
                    table_html += f"<tr><td class='td-cell'><strong>{c1}</strong></td><td class='td-cell'>{c2}</td></tr>"
                    i += 2
                table_html += "</table></div>"
                sec_body_html += table_html
                continue

            # मेन्स प्रश्न व फ्रेमवर्क का विशेष डिज़ाइन
            if "Mains Question" in line or "मेन्स प्रश्न" in line:
                sec_body_html += f"<div class='mains-card'><h4 style='color:#b45309;'>📝 मुख्य परीक्षा प्रश्न</h4><p class='para'><strong>{line}</strong></p>"
                i += 1
                while i < n and not any(sec_lines[i].startswith(x) for x in ["📌", "🎯", "⚡", "📖", "1.", "2.", "3.", "4."]):
                    sec_body_html += f"<p class='para'>{clean_stars_and_markdown(sec_lines[i])}</p>"
                    i += 1
                sec_body_html += "</div>"
                continue

            if line.startswith('>') or line.startswith('“') or line.startswith('"'):
                sec_body_html += f"<blockquote>{line.strip('“\"')}</blockquote>"
                i += 1
                continue

            if '→' in line:
                steps = [s.strip() for s in line.split('→') if s.strip()]
                if len(steps) > 1:
                    step_tags = "".join([f"<span class='flow-step'>{s}</span>" for s in steps])
                    sec_body_html += f"<div class='flow-container'>{step_tags}</div>"
                    i += 1
                    continue

            numbered_match = re.match(r'^([①②③④⑤⑥⑦⑧⑨⑩]|\d+\.)\s*(.*)', line)
            if numbered_match:
                point_sym = numbered_match.group(1)
                point_text = numbered_match.group(2)
                sec_body_html += f"<p class='para'><span class='num-badge'>{point_sym}</span> <strong>{point_text}</strong></p>"
                i += 1
                continue

            if line.startswith(('•', '-', '▪', '▫', '*')):
                clean_bullet = re.sub(r'^[•\-▪▫\*]\s*', '', line)
                if ':' in clean_bullet and len(clean_bullet.split(':')[0]) < 30:
                    b_parts = clean_bullet.split(':', 1)
                    clean_bullet = f"<strong class='hl-bold'>{b_parts[0]}:</strong> {b_parts[1]}"
                sec_body_html += f"<li class='list-item'>{clean_bullet}</li>"
                i += 1
                continue

            formatted = line
            if ':' in formatted and len(formatted.split(':')[0]) < 28:
                parts = formatted.split(':', 1)
                formatted = f"<strong class='hl-blue'>{parts[0]}:</strong>{parts[1]}"

            formatted = re.sub(r'(GS-[I|II|III|IV]+|GS-\d)', r'<span class="badge-gs">\1</span>', formatted)
            formatted = re.sub(r'(Article\s+\d+[A-Za-z]?|अनुच्छेद\s+\d+[A-Za-z]?)', r'<span class="badge-art">\1</span>', formatted, flags=re.IGNORECASE)
            formatted = re.sub(r'(The Hindu|Indian Express|PIB|योजना|Vision IAS|Drishti IAS|Sanskriti IAS)', r'<span class="badge-src">📰 \1</span>', formatted, flags=re.IGNORECASE)
            formatted = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" class="text-link">\1</a>', formatted)
            sec_body_html += f"<p class='para'>{formatted}</p>"
            i += 1

        if in_pipe_table:
            sec_body_html += f"<div class='table-box'><table>{''.join(pipe_table_rows)}</table></div>"

        content_html += f"""
        <section id="{sec_id}" class="news-card">
            <h3 class="section-title">{sec_title}</h3>
            {sec_body_html}
        </section>
        """

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} | {AUTHOR_NAME}</title>
<link href="https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#f4f6f9; --card:#ffffff; --text:#1c2430; --muted:#5b6675; --border:#e2e8f0;
  --accent:#0284c7; --accent-dark:#0369a1; --saffron:#f59e0b; --green:#10b981;
  --tag-bg:#e0f2fe; --tag-text:#0369a1; --shadow:0 4px 16px rgba(15,23,42,.07);
}}
[data-theme="dark"] {{
  --bg:#0b1120; --card:#1e293b; --text:#f1f5f9; --muted:#94a3b8; --border:#334155;
  --accent:#38bdf8; --accent-dark:#0284c7; --tag-bg:#0f2e4a; --tag-text:#7dd3fc;
  --shadow:0 4px 20px rgba(0,0,0,.4);
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ scroll-behavior: smooth; }}
body {{
  background:var(--bg); color:var(--text); font-family:'Hind','Noto Sans Devanagari',sans-serif;
  line-height:1.75; transition:background .3s,color .3s; padding-bottom:75px;
}}
@media print {{
  body::before {{
    content: "SACHIN SHARMA";
    position: fixed;
    top: 40%;
    left: 10%;
    width: 80%;
    text-align: center;
    font-size: 5rem;
    font-weight: 900;
    color: rgba(0, 0, 0, 0.50);
    transform: rotate(-35deg);
    z-index: 9999;
    pointer-events: none;
    letter-spacing: 12px;
  }}
  .controls, nav.dashboard, #telegramBtn, .print-btn, #quiz-trigger-btn {{ display: none !important; }}
  .news-card {{ box-shadow: none !important; border: 1px solid #ccc !important; page-break-inside: avoid; }}
}}
.top-header {{
  background:linear-gradient(135deg,#071529,#0284c7 65%,#0369a1);
  color:#fff; padding:28px 16px 20px; text-align:center;
  border-bottom:4px solid var(--saffron);
}}
.top-header h1 {{ font-size:1.65rem; margin-bottom:6px; font-weight:700; letter-spacing:0.5px; }}
.author-pill {{
  display:inline-block; margin-top:4px; background:rgba(255,255,255,.16);
  border:1px solid rgba(255,255,255,.35); padding:5px 18px; border-radius:30px; font-weight:600; font-size:0.92rem;
}}
.controls {{ display:flex; justify-content:center; gap:10px; margin-top:14px; flex-wrap:wrap; }}
.controls input {{ width:min(340px,85vw); padding:9px 15px; border-radius:20px; border:none; outline:none; font-size:0.9rem; }}
.controls button {{ padding:9px 18px; border-radius:20px; border:1px solid rgba(255,255,255,.4); background:rgba(255,255,255,.2); color:#fff; font-weight:600; cursor:pointer; }}
nav.dashboard {{
  position:sticky; top:0; z-index:50; background:var(--card); border-bottom:1px solid var(--border);
  box-shadow:var(--shadow); overflow-x:auto; white-space:nowrap; padding:9px 14px;
}}
nav.dashboard .nav-wrap {{ display:flex; gap:8px; max-width:920px; margin:0 auto; }}
nav.dashboard a {{
  display:inline-block; padding:7px 15px; background:var(--tag-bg); color:var(--tag-text);
  border-radius:16px; font-size:0.86rem; font-weight:600; text-decoration:none; flex:none;
  transition:all 0.2s ease;
}}
nav.dashboard a:hover {{ background:var(--accent); color:#fff; }}
.wrap {{ max-width:920px; margin:22px auto; padding:0 14px; width:100%; }}
.news-card {{
  background:var(--card); border:1px solid var(--border); border-radius:14px;
  padding:24px; margin-bottom:22px; box-shadow:var(--shadow); width:100%;
  scroll-margin-top: 65px;
}}
.mains-card {{
  background: #fef3c7; border-left: 5px solid var(--saffron); border-radius: 8px;
  padding: 16px; margin: 16px 0; color: #78350f;
}}
[data-theme="dark"] .mains-card {{ background: #451a03; color: #fde68a; }}
.section-title {{
  color:var(--accent); font-size:1.24rem; margin-bottom:14px;
  border-left:5px solid var(--saffron); padding-left:12px;
}}
.para {{ margin:8px 0; font-size:1rem; word-break:break-word; }}
.list-item {{ margin:6px 0 6px 24px; color:var(--text); font-size:0.98rem; }}
.hl-bold {{ color:var(--accent); font-weight:700; }}
.hl-blue {{ color:#0284c7; font-weight:700; }}
.num-badge {{
  display:inline-flex; align-items:center; justify-content:center;
  background:var(--tag-bg); color:var(--accent); font-weight:bold;
  border-radius:50%; width:22px; height:22px; margin-right:4px; font-size:0.95rem;
}}
.badge-gs {{ background:#0284c7; color:#fff; padding:2px 8px; border-radius:6px; font-size:0.82rem; font-weight:bold; margin:0 4px; }}
.badge-art {{ background:#10b981; color:#fff; padding:2px 8px; border-radius:6px; font-size:0.82rem; font-weight:bold; margin:0 4px; }}
.badge-src {{ background:#f59e0b; color:#000; padding:2px 8px; border-radius:6px; font-size:0.80rem; font-weight:bold; margin:0 4px; }}
.text-link {{ color:#0284c7; text-decoration:underline; font-weight:600; }}
.flow-container {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; align-items:center; }}
.flow-step {{ background:var(--tag-bg); color:var(--tag-text); border:1px solid var(--border); padding:5px 12px; border-radius:8px; font-size:0.88rem; font-weight:600; display:inline-flex; align-items:center; }}
.flow-step:not(:last-child)::after {{ content:"→"; margin-left:8px; color:var(--muted); font-weight:bold; }}
blockquote {{ border-left:4px solid var(--accent); background:var(--tag-bg); padding:12px 16px; border-radius:0 8px 8px 0; margin:15px 0; font-weight:500; font-style:italic; }}
.table-box {{ overflow-x:auto; margin:16px 0; width:100%; border-radius:8px; border:1px solid var(--border); }}
table {{ width:100%; border-collapse:collapse; text-align:left; }}
th.th-cell {{ background:var(--accent); color:#fff; padding:10px 14px; font-size:0.95rem; font-weight:600; }}
td.td-cell {{ padding:10px 14px; border-bottom:1px solid var(--border); font-size:0.94rem; }}
tr:nth-child(even) td.td-cell {{ background:rgba(128,128,128,0.04); }}

/* क्विज़ बॉक्स डिज़ाइन */
.quiz-box {{
  background: var(--card); border: 2px solid var(--saffron); border-radius: 14px;
  padding: 24px; margin: 24px 0; box-shadow: var(--shadow);
}}
.opt-label {{
  display: block; padding: 10px 14px; margin: 8px 0; border: 1px solid var(--border);
  border-radius: 8px; cursor: pointer; transition: background 0.2s; font-size: 0.96rem;
}}
.opt-label:hover {{ background: var(--tag-bg); }}
.timer-pill {{
  background: #ef4444; color: #fff; padding: 4px 12px; border-radius: 20px;
  font-weight: 700; font-size: 0.88rem; display: inline-block; margin-bottom: 12px;
}}

#telegramBtn {{
  position:fixed; bottom:18px; right:18px; z-index:90;
  background:#229ED9; color:#fff; border:none; border-radius:30px;
  padding:12px 20px; font-weight:700; cursor:pointer; box-shadow:0 4px 15px rgba(0,0,0,0.25);
  font-size:0.88rem;
}}
footer {{ background:#071529; color:#dbe6f2; text-align:center; padding:26px 16px; margin-top:35px; font-size:0.88rem; }}
footer a {{ color:#8bc4ef; font-weight:700; text-decoration:none; }}
</style>
</head>
<body data-theme="light">
<header class="top-header">
  <h1>🇮🇳 {topic}</h1>
  <div class="author-pill">✍️ संकलन: {AUTHOR_NAME} | {CHANNEL_NAME}</div>
  <div class="controls">
    <input type="text" id="searchBox" placeholder="🔍 खोजें: विषय, अनुच्छेद, कीवर्ड...">
    <button onclick="toggleTheme()">🌗 Dark / Light</button>
    <button onclick="window.print()" class="print-btn">🖨️ प्रिंट / PDF</button>
  </div>
</header>
<nav class="dashboard">
  <div class="nav-wrap">
    {nav_links_html}
  </div>
</nav>
<main class="wrap" id="mainContent">
  {content_html}
  
  <section id="quiz-zone-sec" class="news-card" style="border: 2px solid var(--saffron);">
    <h3 class="section-title">🎯 UPSC CSE अभ्यास क्विज़ (Interactive Test)</h3>
    <p class="para">दैनिक नोट्स पर आधारित लाइव मॉक टेस्ट। प्रत्येक सही उत्तर पर +2 अंक, गलत उत्तर पर -0.66 अंक।</p>
    <div style="text-align:center; margin: 18px 0;">
      <button id="quiz-trigger-btn" onclick="startUPSCQuiz()" style="background:var(--saffron); color:#000; font-weight:bold; font-size:1.05rem; padding:12px 26px; border:none; border-radius:30px; cursor:pointer;">📝 टेस्ट शुरू करें (Start Quiz)</button>
    </div>
    <div id="quiz-engine-area" style="display:none;"></div>
  </section>
</main>
<button id="telegramBtn" onclick="window.open('{CHANNEL_LINK}','_blank')">📲 TELEGRAM — {CHANNEL_NAME}</button>
<footer>
  <div><b>UPSC CSE NOTES | SPECIAL COMPILATION</b></div>
  <div style="margin-top:8px;">निर्माता: <b>{AUTHOR_NAME}</b> | ग्रुप लिंक: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
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

let testTimer = null;
let secondsLeft = 360;

function startUPSCQuiz() {{
  document.getElementById('quiz-trigger-btn').style.display = 'none';
  const area = document.getElementById('quiz-engine-area');
  area.style.display = 'block';

  area.innerHTML = `
    <div style="text-align:right;"><span class="timer-pill" id="timeDisplay">⏱ शेष समय: 06:00</span></div>
    <form id="upscTestForm">
      <div class="quiz-box">
        <p><strong>प्रश्न 1: राजकोषीय घाटा (Fiscal Deficit) और बाह्य ऋण के संदर्भ में कौन सा कथन सही है?</strong></p>
        <label class="opt-label"><input type="radio" name="q1" value="a"> (a) यह केवल सरकारी निवेश पर ब्याज अदायगी को प्रदर्शित करता है।</label>
        <label class="opt-label"><input type="radio" name="q1" value="b"> (b) यह कुल व्यय और उधारियों को छोड़कर कुल प्राप्तियों के बीच का अंतर है।</label>
        <label class="opt-label"><input type="radio" name="q1" value="c"> (c) भारत का बाह्य ऋण इसके आंतरिक ऋण से काफी अधिक है।</label>
        <label class="opt-label"><input type="radio" name="q1" value="d"> (d) उपर्युक्त में से कोई नहीं।</label>
      </div>
      <div class="quiz-box">
        <p><strong>प्रश्न 2: 'आर्टिकल 356' के अंतर्गत राष्ट्रपति शासन लागू करने के संदर्भ में एस.आर. बोम्मई वाद (1994) का मुख्य निष्कर्ष क्या था?</strong></p>
        <label class="opt-label"><input type="radio" name="q2" value="a"> (a) यह पूरी तरह से न्यायिक समीक्षा से परे है।</label>
        <label class="opt-label"><input type="radio" name="q2" value="b"> (b) राष्ट्रपति शासन की उद्घोषणा न्यायिक समीक्षा के अधीन है।</label>
        <label class="opt-label"><input type="radio" name="q2" value="c"> (c) राज्यपाल की रिपोर्ट को सार्वजनिक करना अनिवार्य नहीं है।</label>
        <label class="opt-label"><input type="radio" name="q2" value="d"> (d) विधानसभा स्वतः भंग मानी जाएगी।</label>
      </div>
      <div class="quiz-box">
        <p><strong>प्रश्न 3: 'राष्ट्रीय हरित अधिकरण' (NGT) के संदर्भ में निम्नलिखित कथनों पर विचार करें:</strong></p>
        <label class="opt-label"><input type="radio" name="q3" value="a"> (a) यह सिविल प्रक्रिया संहिता (CPC) 1908 से बाध्य है।</label>
        <label class="opt-label"><input type="radio" name="q3" value="b"> (b) यह प्राकृतिक न्याय के सिद्धांतों द्वारा निर्देशित है।</label>
        <label class="opt-label"><input type="radio" name="q3" value="c"> (c) यह केवल वन्यजीव संरक्षण अधिनियम के तहत मामलों की सुनवाई करता है।</label>
        <label class="opt-label"><input type="radio" name="q3" value="d"> (d) इसके फैसलों को सुप्रीम कोर्ट में चुनौती नहीं दी जा सकती।</label>
      </div>
      <div style="text-align:center; margin-top:20px;">
        <button type="button" onclick="submitUPSCTest()" style="background:#10b981; color:#fff; font-weight:bold; font-size:1.05rem; padding:12px 30px; border:none; border-radius:30px; cursor:pointer;">📊 टेस्ट सबमिट करें</button>
      </div>
    </form>
    <div id="testResultZone" style="margin-top:24px;"></div>
  `;

  testTimer = setInterval(() => {{
    secondsLeft--;
    let m = Math.floor(secondsLeft / 60);
    let s = secondsLeft % 60;
    document.getElementById('timeDisplay').innerText = `⏱ शेष समय: ${{m < 10 ? '0' : ''}}${{m}}:${{s < 10 ? '0' : ''}}${{s}}`;
    if (secondsLeft <= 0) {{
      clearInterval(testTimer);
      submitUPSCTest();
    }}
  }}, 1000);
}}

function submitUPSCTest() {{
  clearInterval(testTimer);
  const answers = {{ q1: 'b', q2: 'b', q3: 'b' }};
  let score = 0;
  let correct = 0;
  let wrong = 0;
  let unattempted = 0;

  for (let key in answers) {{
    const sel = document.querySelector(`input[name="${{key}}"]:checked`);
    if (sel) {{
      if (sel.value === answers[key]) {{
        score += 2.0;
        correct++;
      }} else {{
        score -= 0.66;
        wrong++;
      }}
    }} else {{
      unattempted++;
    }}
  }}

  const resultZone = document.getElementById('testResultZone');
  resultZone.innerHTML = `
    <div style="background:var(--tag-bg); border:2px solid var(--accent); border-radius:12px; padding:20px; text-align:center;">
      <h3 style="color:var(--accent); font-size:1.3rem;">🏆 आपका UPSC CSE टेस्ट परिणाम</h3>
      <p style="font-size:1.15rem; margin:10px 0;"><strong>कुल प्राप्तांक:</strong> <span style="color:#ef4444; font-weight:bold;">${{score.toFixed(2)}} / 6.00</span></p>
      <p>✅ सही: <b>${{correct}}</b> | ❌ गलत: <b>${{wrong}}</b> | ⚪ अनुत्तरित: <b>${{unattempted}}</b></p>
      <div style="margin-top:15px;">
        <button onclick="window.print()" style="background:#0284c7; color:#fff; padding:8px 18px; border:none; border-radius:20px; cursor:pointer; font-weight:bold;">🖨️️ स्कोरकार्ड प्रिंट करें (PDF)</button>
      </div>
    </div>
  `;
}}
</script>
</body>
</html>"""

# ================= PUBLIC MENU & PERMISSION ENFORCEMENT =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    is_admin = user.id in ADMIN_IDS

    admin_badge = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if is_admin else "📚 <b>UPSC CSE स्मार्ट अध्ययन पोर्टल</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user.first_name}!</b>\n\n"
        f"{admin_badge}"
        "नीचे सभी मुख्य कमांड्स उपलब्ध हैं:\n\n"
        "📖 <b>अध्ययन एवं नोट्स:</b>\n"
        "• <code>/daily</code> — दैनिक नोट्स (IST लाइव कैलेंडर)\n"
        "• <code>/quiz</code> — विषयवार लाइव टेस्ट शुरू करें\n"
        "• <code>/trending</code> — चर्चा में चल रहे स्थान, व्यक्ति व मुद्दे\n"
        "• <code>/weekly</code> — साप्ताहिक क्विक रिवीजन\n"
        "• <code>/monthly</code> — सम्पूर्ण मासिक संकलन\n"
        "• <code>/yearly</code> — वार्षिक कंपाइलेशन\n"
        "• <code>/ask &lt;सवाल&gt;</code> — डाउट पूछें\n\n"
        "🛠 <b>प्रशासनिक व निर्माण कमांड्स:</b>\n"
        "• <code>/generate &lt;तारीख/विषय&gt;</code> — नोट्स निर्माण\n"
        "• <code>/broadcast</code> — सभी पंजीकृत छात्रों को संदेश भेजें\n"
        "• <code>/adduser</code> | <code>/removeuser</code> | <code>/listusers</code> — मेंबर्स संभालें\n\n"
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
        "1️⃣ <b>दैनिक नोट्स (`/daily`):</b> भारतीय समय (IST) के अनुसार तारीख चुनें। The Hindu, PIB, Vision, Sanskriti व Drishti IAS के समन्वय से तैयार नोट्स पाएं।\n\n"
        "2️⃣ <b>सीधे PDF भेजें:</b> कोई भी UPSC मैगज़ीन या न्यूज़पेपर PDF सीधे बॉट को भेजें, यह स्वतः उसका 360° HTML नोट्स बनाकर लौटा देगा।\n\n"
        "3️⃣ <b>लाइव टेस्ट (`/quiz`):</b> प्रश्नों की संख्या (5, 10, 15) व विषय चुनकर अपनी पसंद का टेस्ट शुरू करें।\n\n"
        "4️⃣ <b>प्रिंट व वॉटरमार्क:</b> सभी फाइलों पर <b>SACHIN SHARMA</b> का 50% विजिबिलिटी वाला वॉटरमार्क प्रिंट होगा।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# /daily: IST कैलेंडर
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

# /quiz: दो-चरणीय क्विज़ विज़ार्ड (Step 1: विषय का चयन)
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    keyboard = [
        [InlineKeyboardButton("🏛 राजव्यवस्था (Polity)", callback_data="qsubj_polity"), InlineKeyboardButton("💰 अर्थव्यवस्था (Economy)", callback_data="qsubj_economy")],
        [InlineKeyboardButton("🌿 पर्यावरण (Environment)", callback_data="qsubj_env"), InlineKeyboardButton("🔬 विज्ञान एवं टेक (Sci & Tech)", callback_data="qsubj_scitech")],
        [InlineKeyboardButton("🧭 इतिहास एवं भूगोल", callback_data="qsubj_histgeo"), InlineKeyboardButton("⚡ केवल आज के करंट अफेयर्स", callback_data="qsubj_todayca")]
    ]
    await update.message.reply_text("🎯 <b>चरण 1/2:</b> किस विषय का टेस्ट लगाना चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# /trending
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now().strftime("%Y-%m-%d")
    wait_msg = await update.message.reply_text("🛰 <b>UPSC रडार:</b> समसामयिक स्थानों, व्यक्तियों व ट्रेंडिंग मुद्दों का संकलन हो रहा है...", parse_mode=ParseMode.HTML)
    
    prompt = f"""
आज की तारीख {today} के संदर्भ में UPSC CSE परीक्षा हेतु ट्रेंडिंग रडार तैयार करें:
1. 📍 Places in News (चर्चा में रहे 2-3 राष्ट्रीय व अंतर्राष्ट्रीय स्थान और उनका भौगोलिक/रणनीतिक महत्व)
2. 👤 Persons/Institutions in News (चर्चा में रहे व्यक्तित्व या संस्थाएं)
3. ⏪ कल का मुख्य घटनाक्रम (Yesterday Recap)
4. ⚡ आज के शीर्ष मुद्दे (The Hindu, PIB, Vision IAS संदर्भ)
5. ⏩ कल का संभावित विमर्श / आने वाली बैठकें
भाषा शुद्ध व उच्च-स्तरीय हिंदी रखें। अनावश्यक मार्कडाउन स्टार्स का प्रयोग न करें।
"""
    try:
        trend_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', trend_text)
        await wait_msg.edit_text(f"🧭 <b>UPSC TRENDING RADAR ({today})</b>\n\n{clean_text}\n\n💡 <i>विस्तृत नोट्स हेतु लिखें: <code>/generate &lt;विषय&gt;</code></i>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ त्रुटि: {e}")

async def monthly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    months = ["September 2026", "August 2026", "July 2026", "June 2026", "May 2026", "April 2026"]
    keyboard = [[InlineKeyboardButton(f"📁 {m} पत्रिका", callback_data=f"genmonth_{m}")] for m in months]
    await update.message.reply_text("📁 <b>जिस महीने का UPSC कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    years = ["2026", "2025", "2024"]
    keyboard = [[InlineKeyboardButton(f"📚 वर्ष {y} वार्षिक संकलन", callback_data=f"genyear_{y}")] for y in years]
    await update.message.reply_text("🏛️ <b>जिस वर्ष का वार्षिक कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now()
    d_str = today.strftime("%Y-%m-%d")
    keyboard = [
        [InlineKeyboardButton("🗓️ इस सप्ताह का क्विक रिवीजन", callback_data=f"genweek_{d_str}")],
        [InlineKeyboardButton("🗓️ पिछले सप्ताह का रिवीजन", callback_data=f"genweek_{(today - timedelta(days=7)).strftime('%Y-%m-%d')}")]
    ]
    await update.message.reply_text("🗓️ <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# डायनामिक बटन क्लिक और लाइव प्रोग्रेस इंजन
async def handle_dynamic_generation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    try:
        await query.message.delete()
    except Exception:
        pass

    # क्विज़ स्टेप 1: विषय चुना -> प्रश्नों की संख्या पूछना
    if data.startswith("qsubj_"):
        subj_code = data.replace("qsubj_", "")
        USER_QUIZ_SELECTIONS[user_id] = {"subj": subj_code}
        
        keyboard = [
            [InlineKeyboardButton("⚡ 5 प्रश्न (क्विक टेस्ट - 6 मिनट)", callback_data=f"qcount_{subj_code}_5")],
            [InlineKeyboardButton("🎯 10 प्रश्न (मानक टेस्ट - 12 मिनट)", callback_data=f"qcount_{subj_code}_10")],
            [InlineKeyboardButton("🏆 15 प्रश्न (मेगा टेस्ट - 18 मिनट)", callback_data=f"qcount_{subj_code}_15")]
        ]
        await context.bot.send_message(chat_id=user_id, text="🎯 <b>चरण 2/2:</b> आप कितने प्रश्नों का टेस्ट देना चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return

    # क्विज़ स्टेप 2: संख्या चुनी -> टेस्ट जनरेट करना
    if data.startswith("qcount_"):
        parts = data.split("_")
        subj_code = parts[1]
        count = int(parts[2])
        
        subj_map = {
            "polity": "भारतीय राजव्यवस्था एवं संविधान",
            "economy": "भारतीय अर्थव्यवस्था एवं बजट",
            "env": "पर्यावरण, पारिस्थितिकी एवं जैव विविधता",
            "scitech": "विज्ञान एवं प्रौद्योगिकी (Science & Tech)",
            "histgeo": "इतिहास, कला-संस्कृति एवं भूगोल",
            "todayca": f"दैनिक करेंट अफेयर्स ({get_ist_now().strftime('%Y-%m-%d')})"
        }
        subj = subj_map.get(subj_code, "सामान्य अध्ययन")

        wait_m = await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"╔════════════════════════╗\n"
                f"   📝 <b>UPSC MOCK TEST BUILDER</b>\n"
                f"╚════════════════════════╝\n\n"
                f"📚 <b>विषय:</b> <code>{subj}</code>\n"
                f"🎯 <b>प्रश्नों की संख्या:</b> <code>{count} प्रश्न</code>\n"
                f"⏱ <b>समय सीमा:</b> <code>{count * 72 // 60} मिनट</code>\n\n"
                f"<i>स्टेटस: The Hindu, PIB व NCERT से प्रश्न संकलित किए जा रहे हैं...</i>"
            ),
            parse_mode=ParseMode.HTML
        )

        prompt = f"""
विषय: "{subj}" पर UPSC Prelims स्तर के {count} उच्च-स्तरीय प्रश्न (Statement Based - 1 and 2, Both, None) बनाएं।
प्रत्येक प्रश्न में:
- 4 विकल्प (a, b, c, d)
- सही उत्तर
- 2 पंक्ति का स्पष्ट और आधिकारिक व्याख्या (NCERT/Standard Reference)
मार्कडाउन स्टार्स (**) का अनावश्यक प्रयोग न करें। भाषा शुद्ध हिंदी रखें।
"""
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Mock Test — {subj} ({count} प्रश्न)"
            filename = f"UPSC_Test_{subj_code}_{count}Q.html"
            html_content = build_interactive_dashboard_html(topic, ai_text)
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(filename, "rb") as send_doc:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=send_doc,
                    filename=filename,
                    caption=f"📝 <b>UPSC लाइव टेस्ट मॉड्यूल:</b> <code>{topic}</code>\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ टेस्ट बनाने में त्रुटि: {e}")
        return

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
            
            # लाइव प्रोग्रेस स्टेटस (चरणबद्ध)
            wait_m = await context.bot.send_message(
                chat_id=user_id, 
                text=(
                    f"╔════════════════════════╗\n"
                    f"   🏛 <b>UPSC STUDY DESK</b>\n"
                    f"╚════════════════════════╝\n\n"
                    f"📅 <b>दिनांक:</b> <code>{target_date}</code>\n"
                    f"🔄 <b>प्रगति:</b> [1/3] आधिकारिक स्रोतों (The Hindu, PIB, Vision, Drishti, Sanskriti IAS) से डेटा निकाला जा रहा है..."
                ), 
                parse_mode=ParseMode.HTML
            )
            
            await asyncio.sleep(1.2)
            try:
                await wait_m.edit_text(
                    f"╔════════════════════════╗\n"
                    f"   🏛 <b>UPSC STUDY DESK</b>\n"
                    f"╚════════════════════════╝\n\n"
                    f"📅 <b>दिनांक:</b> <code>{target_date}</code>\n"
                    f"🔄 <b>प्रगति:</b> [2/3] GS 1-4 विषयवार सारणी, स्रोत बैज व मेन्स फ्रेमवर्क संकलित हो रहे हैं...",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

            future_note = "यह अग्रिम तिथि है। इसमें उस दिन के ऐतिहासिक महत्व, आगामी अंतरराष्ट्रीय शिखर सम्मेलनों, विधायी एजेंडा और संबंधित PYQs का विश्लेषण शामिल करें।" if is_future else ""

            prompt = f"""
तारीख: "{target_date}" के लिए 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित, पूर्ण और समृद्ध UPSC दैनिक करेंट अफेयर्स नोट्स तैयार करें।
शीर्षक: "दैनिक करेंट अफेयर्स — {target_date}"
{future_note}

अनिवार्य स्रोत कवरेज: The Hindu, Indian Express, PIB, Yojana, Vision IAS, Sanskriti IAS, Drishti IAS.

सभी विषयों का अलग-अलग व्यापक खंड बनाएं:
- GS-1: इतिहास, कला-संस्कृति एवं भूगोल
- GS-2: राजव्यवस्था, संविधान, शासन एवं IR
- GS-3: अर्थव्यवस्था, पर्यावरण, सुरक्षा एवं साइंस-टेक
- GS-4: नीतिशास्त्र व प्रशासनिक दुविधाएं

प्रत्येक विषय में:
1. संदर्भ व स्रोत
2. संवैधानिक/वैधानिक स्थिति
3. मुख्य विश्लेषण (2-कॉलम टेबल प्रारूप: 'चरण' और 'विवरण')
4. 📌 Prelims Facts & Key Concepts (फ्लो हेतु → का प्रयोग)
5. 📝 Mains Question & Answer Writing Framework (प्रश्न के ठीक नीचे भूमिका, 3 मुख्य बिंदु, निष्कर्ष)
6. 4 Practice MCQs (व्याख्या सहित)

मार्कडाउन स्टार्स (**) का अनावश्यक प्रयोग न करें। भाषा सहज हिंदी रखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                
                try:
                    await wait_m.edit_text(
                        f"╔════════════════════════╗\n"
                        f"   🏛 <b>UPSC STUDY DESK</b>\n"
                        f"╚════════════════════════╝\n\n"
                        f"📅 <b>दिनांक:</b> <code>{target_date}</code>\n"
                        f"🔄 <b>प्रगति:</b> [3/3] HTML डैशबोर्ड व SACHIN SHARMA वॉटरमार्क फ़ाइल तैयार हो रही है...",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

                topic = f"दैनिक करेंट अफेयर्स — {target_date}"
                filename = f"UPSC_Dainik_Current_Affairs_{target_date.replace('-', '_')}.html"
                html_content = build_interactive_dashboard_html(topic, ai_text)
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
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"📁 <b>{m_name}</b> का मासिक कंपाइलेशन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
            prompt = f"माह: '{m_name}' का सम्पूर्ण UPSC Monthly Current Affairs Digest स्रोत, 2-कॉलम टेबल्स और अंत में 15 MCQs बैंक के साथ हिंदी में तैयार करें।"
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Monthly Digest — {m_name}"
                filename = f"UPSC_Monthly_{m_name.replace(' ', '_')}.html"
                html_content = build_interactive_dashboard_html(topic, ai_text)
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
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ वर्ष <b>{y_name}</b> का वार्षिक संकलन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
            prompt = f"वर्ष {y_name} का UPSC Annual Compendium (PT-365 Style) 2-कॉलम टेबल्स के साथ हिंदी में तैयार करें।"
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Annual Compendium — {y_name}"
                filename = f"UPSC_Annual_{y_name}.html"
                html_content = build_interactive_dashboard_html(topic, ai_text)
                save_to_archive("yearly", topic, filename, html_content)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}")
                return

    elif data.startswith("genweek_"):
        w_date = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text="⏳ साप्ताहिक रिवीजन डाइजेस्ट तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"सप्ताह ({w_date}) के मुख्य UPSC घटनाक्रमों का 7-दिवसीय रिवीजन डाइजेस्ट 2-कॉलम टेबल्स के साथ हिंदी में तैयार करें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Weekly Revision — {w_date}"
            filename = f"UPSC_Weekly_{w_date}.html"
            html_content = build_interactive_dashboard_html(topic, ai_text)
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

# ================= DIRECT PDF TO HTML ENGINE =================
async def handle_direct_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = msg.document
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        return

    wait_m = await msg.reply_text("📥 <b>PDF प्राप्त हुआ!</b>\nसामग्री निकाली जा रही है व UPSC 360° HTML नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
    temp_pdf = f"temp_{user_id}_{doc.file_name}"
    
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

सामग्री सारांश:
"{pdf_text[:4000]}"

संरचना नियम:
1. मुख्य संदर्भ व स्रोत
2. संवैधानिक/नीतिगत प्रावधान
3. 2-कॉलम सारणी (चरण/घटक और विवरण)
4. मुख्य चुनौतियाँ और आगे की राह (Way Forward)
5. 📌 Prelims Facts & Key Concepts (फ्लो हेतु → का प्रयोग)
6. 📝 Mains Question & Answer Writing Framework (प्रश्न के ठीक नीचे भूमिका, 3 मुख्य बिंदु, निष्कर्ष)
7. 4 Practice MCQs (व्याख्या सहित)
मार्कडाउन स्टार्स (**) का अनावश्यक प्रयोग न करें। भाषा शुद्ध हिंदी रखें।
"""
        ai_notes = await asyncio.to_thread(call_gemini_safely, prompt)
        html_out = build_interactive_dashboard_html(clean_title, ai_notes)

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

# ================= RESPECTFUL FAITH FILTER & TOPPER DOUBT SOLVER =================
async def ask_doubt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल अधिकृत छात्रों के लिए उपलब्ध है।\n"
            f"एडमिन ({AUTHOR_NAME}) से एक्सेस हेतु <code>/owner</code> पर संपर्क करें।",
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        await update.message.reply_text(
            "💡 पूछने के लिए लिखें: <code>/ask आपका सवाल या टॉपिक</code>\n"
            "उदा: <code>/ask 73वां संविधान संशोधन और पंचायती राज चुनौतियाँ</code>", 
            parse_mode=ParseMode.HTML
        )
        return

    user_query = " ".join(context.args).strip()

    faith_greetings = [
        "जय सियाराम", "जय श्री राम", "जय श्रीराम", "राधे राधे", "जय श्री कृष्णा",
        "हर हर महादेव", "नमस्ते", "प्रणाम", "चरण स्पर्श", "जय बजरंगबली"
    ]
    if any(fg in user_query for fg in faith_greetings):
        await update.message.reply_text(
            "🙏 <b>जय सियाराम! प्रभु श्री राम का आशीर्वाद आप पर सदैव बना रहे।</b>\n\n"
            "यह UPSC स्मार्ट डेस्क सिविल सेवा अध्ययन हेतु समर्पित है। अपनी तैयारी, करेंट अफेयर्स या किसी विषय से संबंधित सवाल पूछें!",
            parse_mode=ParseMode.HTML
        )
        return

    blocked_patterns = [
        r"मेरा नाम", r"तुम्हारा नाम", r"आपका नाम", r"तुम कौन", r"आप कौन",
        r"हेलो", r"हाय", r"hello", r"hi", r"hey", r"कैसे हो", r"क्या कर रहे",
        r"शायरी", r"मजाक", r"मौसम", r"गाना", r"लव", r"प्यार", r"गर्लफ्रेंड",
        r"बॉयफ्रेंड", r"joke", r"time pass", r"who are you", r"what is your name",
        r"my name", r"bot", r"robot"
    ]
    if any(re.search(pat, user_query, re.IGNORECASE) for pat in blocked_patterns) or len(user_query) < 5:
        await update.message.reply_text(
            f"⚠️ <b>कृपया केवल UPSC पाठ्यक्रम (GS-1, 2, 3, 4) से जुड़े गंभीर विषय ही पूछें।</b>\n\n"
            f"व्यक्तिगत सवाल या अन्य बातचीत के लिए {AUTHOR_NAME} से संपर्क करने हेतु <code>/owner</code> का उपयोग करें।",
            parse_mode=ParseMode.HTML
        )
        return

    wait_msg = await update.message.reply_text("🤔 UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")
    asyncio.create_task(process_ask_doubt(update.message, wait_msg, user_query))

async def process_ask_doubt(message, wait_msg, user_query):
    try:
        prompt = f"""
आप UPSC CSE में शीर्ष रैंक प्राप्त अनुभवी छात्र व मेंटर हैं।
छात्र के निम्नलिखित विषय/प्रश्न का विश्लेषण एक गंभीर एस्पिरेंट के व्यावहारिक दृष्टिकोण से दें।

विषय: "{user_query}"

सख्त नियम:
1. अपनी पहचान केवल UPSC साथी/मेंटर के रूप में रखें। कभी भी AI, रोबोट, या लैंग्वेज मॉडल का उल्लेख न करें।
2. विश्लेषण बिंदुवार, टू-द-पॉइंट और संतुलित हो (प्रमुख प्रावधान/मुद्दे, चुनौतियाँ, और 1-2 सरकारी समिति/आयोग का नाम)।
3. यदि प्रश्न मेन्स से जुड़ा है, तो भूमिका, मुख्य भाग और निष्कर्ष का व्यावहारिक ढांचा दें।
4. अनावश्यक मार्कडाउन स्टार्स (**) का प्रयोग न करें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', reply_text)
        clean_reply = re.sub(r'#+\s*', '', clean_reply)

        if len(clean_reply) > 3800:
            parts = [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]
            await wait_msg.delete()
            for p in parts:
                await message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await wait_msg.edit_text(clean_reply, parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ उत्तर संकलित करने में समस्या आई: {e}")

# ================= PROTECTED ADMIN GENERATE COMMAND =================
async def ai_generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह निर्माणकारी सुविधा केवल एडमिन ({AUTHOR_NAME}) व अधिकृत मेंबर्स के लिए आरक्षित है।\n"
            "कृपया अध्ययन सामग्री डाउनलोड करने के लिए <code>/daily</code> या <code>/monthly</code> का प्रयोग करें।",
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/generate 30 September 2026</code>", parse_mode=ParseMode.HTML)
        return

    query = " ".join(context.args).replace("[", "").replace("]", "").strip()
    status_msg = await update.message.reply_text(
        f"╔════════════════════════╗\n"
        f"   🏛 <b>UPSC NOTE BUILDER</b>\n"
        f"╚════════════════════════╝\n\n"
        f"📌 <b>विषय:</b> <code>{query}</code>\n"
        f"⚙️ <b>स्थिति:</b> The Hindu, PIB, Vision, Sanskriti व Drishti IAS समन्वय चालू...",
        parse_mode=ParseMode.HTML
    )

    try:
        prompt = f"""
निम्नलिखित विषय/तारीख पर 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित, पूर्ण और समृद्ध UPSC नोट्स तैयार करें:
विषय: "{query}"
शीर्षक: "दैनिक करेंट अफेयर्स — {query}"

सख्त संरचना नियम:
1. पहली पंक्ति में मुख्य शीर्षक दें।
2. सभी संबंधित विषयों को अनिवार्य रूप से शामिल करें (GS-1, GS-2, GS-3, GS-4)।
3. मुख्य हेडिंग्स:
   - 1. संदर्भ / चर्चा में क्यों (स्रोत टैग सहित)
   - 2. संवैधानिक एवं वैधानिक स्थिति (संबद्ध अनुच्छेद, कानून व केस लॉ)
   - 3. मुख्य विश्लेषण (2-कॉलम टेबल प्रारूप: पहली पंक्ति हेडर 'चरण' और 'विवरण')
   - 4. प्रमुख आयाम / चुनौतियाँ (बुलेट पॉइंट्स, मुख्य शब्दों के आगे :)
   - 5. आगे की राह (Way Forward)
   - 6. 📌 Prelims Facts & Key Concepts (फ्लो दिखाने के लिए → का प्रयोग)
   - 7. 📝 Mains Answer Writing Framework (प्रश्न के ठीक नीचे भूमिका, 3 मुख्य बिंदु, निष्कर्ष)
   - 8. 4 Practice MCQs (व्याख्या सहित)
मार्कडाउन स्टार्स (**) का अनावश्यक प्रयोग न करें। भाषा हिंदी रखें।
"""
        ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_topic = f"दैनिक करेंट अफेयर्स — {query}"[:40]
        html_output = build_interactive_dashboard_html(clean_topic, ai_text)

        safe_fname = re.sub(r'[^a-zA-Z0-9\u0900-\u097F]', '_', query)[:25]
        filename = f"Current_Affairs_{safe_fname}.html"
        save_to_archive("daily", clean_topic, filename, html_output)

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
        await update.message.reply_text("⛔ यह केवल मुख्य एडमिन के लिए है।")
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
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, vip_expiry FROM users WHERE is_vip = 1")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("ℹ️ अभी कोई अतिरिक्त अधिकृत सदस्य नहीं हैं।")
        return
    text = "👥 <b>अधिकृत मेंबर्स की सूची:</b>\n\n"
    for uid, un, fn, exp in rows:
        un_str = f"@{un}" if un else "कोई यूज़रनेम नहीं"
        text += f"• <b>{fn}</b> (<code>{uid}</code>) | {un_str}\n  वैधता: <code>{exp}</code>\n\n"
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
    start_time = CONTACT_SESSIONS.get(user_id, 0)
    if time.time() - start_time > 120:
        CONTACT_SESSIONS.pop(user_id, None)
        await update.message.reply_text("⚠ <b>समय समाप्त!</b> पुनः प्रयास हेतु <code>/owner</code> भेजें।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    msg = update.message
    content_text = msg.text or msg.caption or "[फ़ाइल / मीडिया]"
    username_str = f"@{user.username}" if user.username else "कोई यूज़रनेम नहीं"

    owner_alert = (
        "📩 <b>नया छात्र संदेश!</b>\n\n"
        f"👤 <b>नाम:</b> {user.first_name}\n"
        f"🆔 <b>यूज़र ID:</b> <code>{user.id}</code>\n"
        f"🔗 <b>यूज़रनेम:</b> {username_str}\n\n"
        f"💬 <b>संदेश:</b>\n{content_text}\n\n"
        "👉 <i>(छात्र को उत्तर देने हेतु इस मैसेज पर सीधे <b>Reply</b> करें)</i>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=owner_alert, parse_mode=ParseMode.HTML)
        except Exception as e:
            print(f"Error notifying admin {admin_id}: {e}")

    await update.message.reply_text("✅ <b>आपका संदेश ओनर को भेज दिया गया है!</b>", parse_mode=ParseMode.HTML)
    CONTACT_SESSIONS.pop(user_id, None)
    return ConversationHandler.END

async def handle_admin_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        return
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return

    reply_to_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
    match = re.search(r"यूज़र ID:\s*(\d+)", reply_to_text) or re.search(r"<code>(\d+)</code>", reply_to_text)
    if match:
        target_user_id = int(match.group(1))
        reply_body = msg.text or msg.caption or ""
        user_notification = f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n{reply_body}\n\n📢 <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
        try:
            await context.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            await msg.reply_text("✅ जवाब छात्र को सफलतापूर्वक भेज दिया गया!")
        except Exception as e:
            await msg.reply_text(f"❌ त्रुटि: {e}")

# ================= UNIVERSAL BROADCAST SYSTEM (ALL USERS) =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END
    all_users = get_all_users()
    await update.message.reply_text(f"📢 <b>सार्वजनिक ब्रॉडकास्ट प्रणाली:</b>\n\nकुल पंजीकृत छात्र: <b>{len(all_users)}</b>\n\nसभी को भेजा जाने वाला संदेश लिखें:\n<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>", parse_mode=ParseMode.HTML)
    return WAITING_BROADCAST_MSG

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END
    b_msg = update.message
    all_users = get_all_users()
    status_msg = await update.message.reply_text(f"⏳ ब्रॉडकास्ट जारी है... (कुल: {len(all_users)})")
    success_count = 0
    fail_count = 0

    for uid in all_users:
        try:
            if b_msg.text:
                await context.bot.send_message(chat_id=uid, text=f"📢 <b>UPSC HTML सूचना:</b>\n\n{b_msg.text}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            else:
                await context.bot.copy_message(chat_id=uid, from_chat_id=admin_id, message_id=b_msg.message_id)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    await status_msg.edit_text(f"✅ सफल: {success_count} छात्र | ❌ असफल: {fail_count}", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    CONTACT_SESSIONS.pop(user_id, None)
    await update.message.reply_text("प्रक्रिया रद्द कर दी गई।")
    return ConversationHandler.END

# ================= RENDER KEEP-ALIVE SERVER =================
async def run_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="UPSC Smart Bot Active 24/7 with Live Test & IST Engine"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ================= MAIN APPLICATION =================
async def main():
    init_db()
    await run_server()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CommandHandler("help", help_handler))
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("quiz", quiz_cmd))
    bot_app.add_handler(CommandHandler("trending", trending_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    bot_app.add_handler(CommandHandler("generate", ai_generate_cmd))
    bot_app.add_handler(CommandHandler("ask", ask_doubt_cmd))
    bot_app.add_handler(CommandHandler("adduser", add_user_cmd))
    bot_app.add_handler(CommandHandler("removeuser", remove_user_cmd))
    bot_app.add_handler(CommandHandler("listusers", list_users_cmd))

    bot_app.add_handler(CallbackQueryHandler(handle_dynamic_generation_click))

    # डायरेक्ट PDF अपलोड हैंडलर
    bot_app.add_handler(MessageHandler(filters.Document.PDF, handle_direct_pdf_upload))

    # ओनर संपर्क सिस्टम
    contact_conv = ConversationHandler(
        entry_points=[CommandHandler("owner", contact_cmd), CommandHandler("contact", contact_cmd)],
        states={WAITING_CONTACT_MSG: [MessageHandler(filters.TEXT & (~filters.COMMAND), forward_contact_msg)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(contact_conv)

    # यूनिवर्सल ब्रॉडकास्ट सिस्टम
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={WAITING_BROADCAST_MSG: [MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(broadcast_conv)

    bot_app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_admin_reply_to_user))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
