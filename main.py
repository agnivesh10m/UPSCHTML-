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
AUTHOR_NAME = "सचिन शर्मा"

# भारतीय मानक समय (IST)
IST = ZoneInfo("Asia/Kolkata")

def get_ist_now():
    return datetime.now(IST)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

WAITING_FOR_NAME = 1
WAITING_CONTACT_MSG = 2
WAITING_BROADCAST_MSG = 3

USER_BUFFERS = {}
CONTACT_SESSIONS = {}

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

# ================= ASYNC ENGINE (3.8 FLASH PRIORITY) =================
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

# ================= CLEAN & ACCURATE HTML BUILDER =================
def clean_stars_and_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'(\*{2,}|_{2,})', '', text)
    return text.strip()

def format_nav_title(title: str, idx: int) -> str:
    # बिना किसी शब्द को काटे सटीक नाम निकालना
    clean = re.sub(r'^[\d\.\-\s📌🎯⚡📖💡🗳️⚖️🔍📝🛣️❄️🌏📰🌍🌱🔬💰🔑📚🔸]+', '', title).strip()
    clean = re.sub(r'[*#_~`]', '', clean).strip()
    
    if '/' in clean:
        parts = [p.strip() for p in clean.split('/') if len(p.strip()) > 2]
        clean = parts[-1] if parts else clean
        
    clean = clean.replace(':', '').replace('-', '').strip()
    
    if not clean or len(clean) < 2 or clean in ['.', '/', '-', '_']:
        names = ["चर्चा में क्यों", "संवैधानिक ढांचा", "मुख्य विश्लेषण", "प्रमुख आयाम", "आगे की राह", "प्रीलिम्स फैक्ट्स", "मेन्स प्रश्न"]
        clean = names[(idx - 1) % len(names)]
        
    return clean

def build_interactive_dashboard_html(topic: str, raw_text: str, image_list: list = None) -> str:
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

    nav_links_html = ""
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
            formatted = re.sub(r'(The Hindu|Indian Express|PIB|योजना|डाउन टू अर्थ)', r'<span class="badge-src">📰 स्रोत: \1</span>', formatted)
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

    img_markup = ""
    if image_list:
        for b64 in image_list:
            img_markup += f"<div class='img-container'><img src='data:image/jpeg;base64,{b64}' class='post-img'/></div>"

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} | संकलन: {AUTHOR_NAME}</title>
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
  .controls, nav.dashboard, #telegramBtn, .print-btn {{ display: none !important; }}
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
.img-container {{ text-align:center; margin:16px 0; }}
.post-img {{ max-width:100%; border-radius:10px; }}
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
  {img_markup}
  {content_html}
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
        "• <code>/daily</code> — दैनिक नोट्स (IST कैलेंडर चयन)\n"
        "• <code>/trending</code> — चर्चा में चल रहे स्थान, व्यक्ति व मुद्दे\n"
        "• <code>/weekly</code> — साप्ताहिक क्विक रिवीजन\n"
        "• <code>/monthly</code> — सम्पूर्ण मासिक संकलन\n"
        "• <code>/yearly</code> — वार्षिक कंपाइलेशन\n"
        "• <code>/ask &lt;सवाल&gt;</code> — डाउट पूछें\n\n"
        "🛠️ <b>प्रशासनिक व निर्माण कमांड्स:</b>\n"
        "• <code>/generate &lt;तारीख/विषय&gt;</code> — नोट्स निर्माण\n"
        "• <code>/html</code> — सामग्री संग्रह सत्र चालू करें\n"
        "• <code>/sachin</code> — संयुक्त HTML फ़ाइल बनाएं\n"
        "• <code>/broadcast</code> — सभी को मैसेज भेजें\n"
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
        "📖 <b>UPSC HTML BOT — सहायता केंद्र</b>\n\n"
        "1️⃣ <b>दैनिक नोट्स (`/daily`):</b> भारतीय मानक समय (IST) के अनुसार आज, पिछली 5 और अगली 3 तारीखों के बटन मिलेंगे।\n\n"
        "2️⃣ <b>ट्रेंडिंग रडार (`/trending`):</b> चर्चा में चल रहे स्थान (Places in News), व्यक्ति, और कल-आज-कल का घटनाक्रम देखें।\n\n"
        "3️⃣ <b>मासिक पत्रिका (`/monthly`):</b> पूरे माह का विषयवार सार और अंत में सभी अभ्यास प्रश्न एक साथ मिलेंगे।\n\n"
        "4️⃣ <b>प्रिंट व पीडीएफ वॉटरमार्क:</b> किसी भी फ़ाइल को खोलकर <b>'🖨️ प्रिंट / PDF'</b> दबाएं। सभी पन्नों पर <b>SACHIN SHARMA</b> का 50% दृश्यता वाला वॉटरमार्क स्वतः प्रिंट होगा।\n\n"
        "5️⃣ <b>सीधे एडमिन से संपर्क:</b> <code>/owner</code> दबाएं और 2 मिनट में अपनी बात लिखें।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# /daily: भारतीय मानक समय (IST) के आधार पर आज, -5 दिन, +3 दिन
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

# /trending: समसामयिक स्थान, व्यक्ति व 1 दिन आगे-पीछे का घटनाक्रम
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now().strftime("%Y-%m-%d")
    
    wait_msg = await update.message.reply_text("🛰 <b>UPSC रडार:</b> समसामयिक स्थानों, व्यक्तियों व ट्रेंडिंग मुद्दों का संकलन हो रहा है...", parse_mode=ParseMode.HTML)
    
    prompt = f"""
आज की तारीख {today} (भारतीय समय) के संदर्भ में UPSC CSE परीक्षा के लिए ट्रेंडिंग रडार तैयार करें:
1. 📍 Places in News (चर्चा में रहे 2-3 राष्ट्रीय व अंतर्राष्ट्रीय स्थान और उनका भौगोलिक/रणनीतिक महत्व)
2. 👤 Persons/Institutions in News (चर्चा में रहे व्यक्तित्व या संस्थाएं)
3. ⏪ कल का मुख्य घटनाक्रम (Yesterday Recap)
4. ⚡ आज के शीर्ष 3 मुद्दे (Today's Core Issues)
5. ⏩ कल का संभावित विमर्श / आने वाली बैठकें (Tomorrow's Outlook)

प्रत्येक बिंदु के आगे The Hindu / PIB / IE का संदर्भ दें। भाषा शुद्ध और परीक्षा-उन्मुख हिंदी रखें।
अनावश्यक मार्कडाउन स्टार्स का प्रयोग न करें।
"""
    try:
        trend_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', trend_text)
        await wait_msg.edit_text(f"🧭 <b>UPSC TRENDING RADAR ({today})</b>\n\n{clean_text}\n\n💡 <i>किसी भी मुद्दे के विस्तृत 360° नोट्स हेतु लिखें: <code>/generate &lt;मुद्दे का नाम&gt;</code></i>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ ट्रेंडिंग डेटा संकलन में त्रुटि: {e}")

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

# डायनामिक बटन क्लिक हैंडलर
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
            wait_m = await context.bot.send_message(
                chat_id=user_id, 
                text=(
                    f"╔════════════════════════╗\n"
                    f"   🏛 <b>UPSC STUDY DESK</b>\n"
                    f"╚════════════════════════╝\n\n"
                    f"📅 <b>दिनांक:</b> <code>{target_date}</code>\n"
                    f"📊 <b>स्थिति:</b> The Hindu, PIB, Yojana विश्लेषण जारी...\n\n"
                    f"<i>2-कॉलम सारणी, स्रोत एवं मेन्स आंसर फ्रेमवर्क संकलित किए जा रहे हैं...</i>"
                ), 
                parse_mode=ParseMode.HTML
            )
            prompt = f"""
तारीख: "{target_date}" के लिए 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित, पूर्ण और समृद्ध UPSC दैनिक करेंट अफेयर्स नोट्स तैयार करें।
शीर्षक: "दैनिक करेंट अफेयर्स — {target_date}"

प्रत्येक विषय में स्पष्ट स्रोत टैग (The Hindu / Indian Express / PIB) अनिवार्य रूप से दें।

संरचना:
1. संदर्भ / चर्चा में क्यों
2. संवैधानिक एवं वैधानिक स्थिति (अनुच्छेद व कानून)
3. मुख्य विश्लेषण (2-कॉलम टेबल प्रारूप: 'चरण' और 'विवरण')
4. प्रमुख तकनीकें / चुनौतियाँ (बुलेट पॉइंट्स, मुख्य शब्दों के आगे :)
5. आगे की राह (Way Forward)
6. 📌 Prelims Facts & Key Concepts (फ्लो हेतु → का प्रयोग)
7. 📝 Mains Answer Writing Framework:
   - प्रश्न
   - 📌 भूमिका (Intro): क्या डेटा, रिपोर्ट या अनुच्छेद कोट करें
   - 📌 मुख्य भाग (Body Dimensions): 3 मुख्य विश्लेषणात्मक बिंदु (समिति अनुशंसा सहित)
   - 📌 निष्कर्ष (Way Forward): संतुलित प्रशासनिक समाधान
8. अंत में 4 Practice MCQs (व्याख्या सहित)।

मार्कडाउन स्टार्स (**) का अनावश्यक प्रयोग न करें। भाषा सहज व उच्च-स्तरीय हिंदी रखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"दैनिक करेंट अफेयर्स — {target_date}"
                filename = f"Current_Affairs_{target_date}.html"
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
                f"📄 <b>नोट्स फ़ाइल:</b> <code>{topic}</code>\n"
                f"👤 <b>संकलन:</b> {AUTHOR_NAME}\n"
                f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
            ),
            parse_mode=ParseMode.HTML,
        )

    if os.path.exists(filename):
        os.remove(filename)

# ================= RESPECTFUL FAITH FILTER & TOPPER DOUBT SOLVER =================
async def ask_doubt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            "⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल अधिकृत छात्रों के लिए उपलब्ध है।\n"
            "एडमिन से एक्सेस हेतु <code>/owner</code> पर संपर्क करें।",
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
            f"व्यक्तिगत सवाल या अन्य बातचीत के लिए सचिन शर्मा ({AUTHOR_NAME}) से संपर्क करने हेतु <code>/owner</code> का उपयोग करें।",
            parse_mode=ParseMode.HTML
        )
        return

    wait_msg = await update.message.reply_text("🤔 UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")
    asyncio.create_task(process_ask_doubt(update.message, wait_msg, user_query))

async def process_ask_doubt(message, wait_msg, user_query):
    try:
        prompt = f"""
आप UPSC CSE में शीर्ष रैंक प्राप्त अनुभवी छात्र व मेंटर हैं।
छात्र के निम्नलिखित विषय/प्रश्न का विश्लेषण एक गंभीर एस्पिरेंट के व्यावहारिक दृष्टिकोण (75-80% अंक प्राप्त करने वाले स्तर) से दें।

विषय: "{user_query}"

सख्त नियम:
1. अपनी पहचान केवल UPSC साथी/मेंटर के रूप में रखें। कभी भी AI, रोबोट, या लैंग्वेज मॉडल का उल्लेख न करें।
2. विश्लेषण बिंदुवार, टू-द-पॉइंट और संतुलित हो (प्रमुख प्रावधान/मुद्दे, चुनौतियाँ, और 1-2 सरकारी समिति/आयोग का नाम)।
3. यदि प्रश्न मेन्स से जुड़ा है, तो भूमिका, मुख्य भाग और निष्कर्ष का व्यावहारिक ढांचा दें।
4. अभी बहुविकल्पीय प्रश्न (MCQs) न जोड़ें।
5. अनावश्यक मार्कडाउन स्टार्स (**) का प्रयोग न करें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', reply_text)
        clean_reply = re.sub(r'#+\s*', '', clean_reply)

        context_key = f"mcq_{int(time.time())}"
        USER_BUFFERS[context_key] = user_query

        keyboard = [[InlineKeyboardButton("🎯 इस टॉपिक पर 4 अभ्यास प्रश्न (MCQs) देखें", callback_data=context_key)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if len(clean_reply) > 3800:
            parts = [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]
            await wait_msg.delete()
            for idx, p in enumerate(parts):
                if idx == len(parts) - 1:
                    await message.reply_text(p, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                else:
                    await message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await wait_msg.edit_text(clean_reply, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    except Exception as e:
        await wait_msg.edit_text(f"❌ उत्तर संकलित करने में समस्या आई: {e}")

async def handle_mcq_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context_key = query.data
    original_topic = USER_BUFFERS.get(context_key, "UPSC समसामयिकी")

    wait_m = await context.bot.send_message(chat_id=query.from_user.id, text=f"🎯 <b>'{original_topic}'</b> पर 4 अभ्यास प्रश्न तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
    prompt = f"विषय: '{original_topic}' पर UPSC Prelims स्तर के 4 मानक बहुविकल्पीय अभ्यास प्रश्न (MCQs) 4 विकल्पों, सही उत्तर और 1 पंक्ति की व्याख्या सहित बनाएं। मार्कडाउन स्टार्स का अनावश्यक प्रयोग न करें।"
    try:
        mcq_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_mcq = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', mcq_text)
        await wait_m.edit_text(f"📚 <b>अभ्यास प्रश्न बैंक (Prelims Focus):</b>\n\n{clean_mcq}", parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

# ================= PROTECTED ADMIN GENERATE COMMAND =================
async def ai_generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            "⛔ <b>अनुमति नहीं है:</b> यह निर्माणकारी सुविधा केवल एडमिन (सचिन शर्मा) व अधिकृत मेंबर्स के लिए आरक्षित है।\n"
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
        f"⚙️ <b>स्थिति:</b> The Hindu, PIB स्रोत, 2-कॉलम सारणी व मेन्स आंसर फ्रेमवर्क तैयार चालू...",
        parse_mode=ParseMode.HTML
    )

    try:
        prompt = f"""
निम्नलिखित विषय/तारीख पर 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित, पूर्ण और समृद्ध UPSC नोट्स तैयार करें:
विषय: "{query}"

शीर्षक: "दैनिक करेंट अफेयर्स — {query}" (स्रोत अनिवार्य रूप से लिखें)

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
   - 7. 📝 Mains Answer Writing Framework:
        - प्रश्न
        - 📌 भूमिका (Intro): क्या डेटा, रिपोर्ट या अनुच्छेद कोट करें
        - 📌 मुख्य भाग (Body Dimensions): 3 मुख्य विश्लेषणात्मक बिंदु
        - 📌 निष्कर्ष (Way Forward): संतुलित राय
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
                caption=(
                    f"✨ <b>{clean_topic}</b>\n"
                    f"👤 <b>संकलन:</b> {AUTHOR_NAME}\n"
                    f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                ),
                parse_mode=ParseMode.HTML,
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
        await update.message.reply_text("⚠️️ <b>समय समाप्त!</b> पुनः प्रयास हेतु <code>/owner</code> भेजें।", parse_mode=ParseMode.HTML)
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

# ================= BROADCAST SYSTEM =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END
    all_users = get_all_users()
    await update.message.reply_text(f"📢 <b>ब्रॉडकास्ट:</b> संदेश भेजें (कुल छात्र: {len(all_users)})", parse_mode=ParseMode.HTML)
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

    await status_msg.edit_text(f"✅ सफल: {success_count} | ❌ असफल: {fail_count}", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# ================= ROBUST FORWARDED / PDF / TEXT INGESTION =================
async def start_html_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ यह केवल अधिकृत मेंबर्स के लिए है।")
        return

    USER_BUFFERS[user_id] = {
        "active": True,
        "texts": [],
        "images": [],
        "html_soups": [],
        "suggested_topic": "UPSC_Notes",
    }
    await update.message.reply_text(
        "🟢 <b>सत्र चालू!</b> जितनी चाहें PDF, HTML या लंबे फॉरवर्डेड मैसेज भेजें।\n"
        "जब सब भेज लें, तब <code>/sachin</code> भेजें।",
        parse_mode=ParseMode.HTML
    )

async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    if user_id not in USER_BUFFERS:
        USER_BUFFERS[user_id] = {
            "active": True,
            "texts": [],
            "images": [],
            "html_soups": [],
            "suggested_topic": "UPSC_Notes",
        }

    session = USER_BUFFERS[user_id]
    msg = update.message
    raw_text = msg.text or msg.caption or ""

    if msg.photo:
        photo = msg.photo[-1]
        f_obj = await photo.get_file()
        t_img = f"img_{photo.file_unique_id}.jpg"
        await f_obj.download_to_drive(t_img)
        with open(t_img, "rb") as f:
            session["images"].append(base64.b64encode(f.read()).decode("utf-8"))
        if os.path.exists(t_img):
            os.remove(t_img)
        await msg.reply_text("📸 इमेज बफ़र में सुरक्षित जोड़ ली गई है!")

    elif msg.document:
        doc_f = await msg.document.get_file()
        fname = msg.document.file_name.lower()
        
        if fname.endswith(".pdf"):
            t_pdf = f"doc_{msg.document.file_name}"
            try:
                await doc_f.download_to_drive(t_pdf)
                reader = PdfReader(t_pdf)
                pdf_text = ""
                for page in reader.pages:
                    txt = page.extract_text()
                    if txt:
                        pdf_text += txt + "\n"
                if pdf_text.strip():
                    session["texts"].append(pdf_text)
                    if session["suggested_topic"] == "UPSC_Notes":
                        session["suggested_topic"] = fname.replace(".pdf", "")[:35]
                    await msg.reply_text(f"✅ <b>PDF सामग्री जोड़ ली गई!</b> (कुल पृष्ठ: {len(reader.pages)})\nअब <code>/sachin</code> दबाकर HTML बनाएं।", parse_mode=ParseMode.HTML)
                else:
                    await msg.reply_text("⚠ यह PDF केवल इमेज जैसी है। कृपया इसका टेक्स्ट कॉपी करके भेजें।")
            except Exception as e:
                print(f"Error reading PDF: {e}")
                await msg.reply_text("⚠️ PDF पढ़ने में समस्या आई।")
            if os.path.exists(t_pdf):
                os.remove(t_pdf)

        elif fname.endswith(".html") or fname.endswith(".htm"):
            t_doc = f"doc_{msg.document.file_name}"
            await doc_f.download_to_drive(t_doc)
            with open(t_doc, "r", encoding="utf-8", errors="ignore") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
                session["html_soups"].append(soup)
                title_node = soup.find('title')
                h1_node = soup.find('h1')
                if title_node and title_node.text.strip():
                    session["suggested_topic"] = re.sub(r'(\||-|—).*$', '', title_node.text).strip()[:45]
                elif h1_node and h1_node.text.strip():
                    session["suggested_topic"] = re.sub(r'(\||-|—).*$', '', h1_node.text).strip()[:45]
                else:
                    session["suggested_topic"] = fname.replace(".html", "").replace(".htm", "")
            if os.path.exists(t_doc):
                os.remove(t_doc)
            await msg.reply_text("✅ HTML दस्तावेज़ जोड़ लिया गया! अब <code>/sachin</code> भेजें।", parse_mode=ParseMode.HTML)

    if raw_text:
        session["texts"].append(raw_text)
        lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
        if lines and session["suggested_topic"] == "UPSC_Notes":
            first_l = re.sub(r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍🔑|━─—_#*-]", "", lines[0]).strip()
            first_l = first_l.split("—")[0].split("-")[0].strip()
            session["suggested_topic"] = first_l[:40] if first_l else "UPSC_Notes"
        await msg.reply_text("✅ <b>संदेश बफ़र में जुड़ गया!</b>\nसभी सामग्री भेजने के बाद <code>/sachin</code> भेजें।", parse_mode=ParseMode.HTML)

async def ask_for_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ यह कमांड केवल अधिकृत मेंबर्स के लिए है।")
        return ConversationHandler.END

    session = USER_BUFFERS.get(user_id)
    if not session or (not session.get("texts") and not session.get("html_soups")):
        await update.message.reply_text("❌ कोई सामग्री नहीं मिली। पहले कोई टेक्स्ट या फॉरवर्डेड मैसेज भेजें, फिर <code>/sachin</code> दबाएं।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    suggested = session.get("suggested_topic", "UPSC_Notes")
    if session.get("texts") and suggested == "UPSC_Notes":
        try:
            head_sample = session["texts"][0][:400]
            auto_title = await asyncio.to_thread(
                call_gemini_safely,
                f"इस यूपीएससी सामग्री के लिए केवल 4 से 6 शब्दों का उपयुक्त और साफ़ हिंदी शीर्षक दें: '{head_sample}'"
            )
            suggested = re.sub(r'[^\w\s-]', '', auto_title).strip()[:35]
        except Exception:
            pass

    prompt_msg = (
        "📝 <b>फ़ाइल नाम की पुष्टि:</b>\n\n"
        "📌 <b>सुझाया गया नाम (एक टैप में कॉपी करें):</b>\n"
        f"<code>{suggested}</code>\n\n"
        "👉 <b>विकल्प:</b>\n"
        "1. यदि <b>यही नाम</b> रखना है, तो <b>1</b> भेजें।\n"
        "2. यदि <b>बदलना है</b>, तो नाम कॉपी करके एडिट करें और भेजें!"
    )
    await update.message.reply_text(prompt_msg, parse_mode=ParseMode.HTML)
    return WAITING_FOR_NAME

async def generate_final_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    session = USER_BUFFERS.get(user_id)
    if not session:
        return ConversationHandler.END

    user_reply = update.message.text.strip()
    suggested = session.get("suggested_topic", "UPSC_Notes")

    final_topic = suggested if user_reply == "1" else user_reply
    safe_topic = re.sub(r'[^a-zA-Z0-9\u0900-\u097F]', '_', final_topic)[:30]
    clean_filename = f"{safe_topic}.html"

    wait_msg = await update.message.reply_text("⏳ सामग्री का गहन विश्लेषण व 2-कॉलम सारणी तैयार की जा रही है...")

    final_output_html = ""
    if session["html_soups"]:
        main_soup = session["html_soups"][0]
        for a in main_soup.find_all('a'):
            href = a.get('href', '')
            if 't.me' in href or 'cserunners' in href.lower():
                a['href'] = CHANNEL_LINK
            if a.string and re.search(r'cse\s*runners', a.string, re.IGNORECASE):
                a.string = f"{AUTHOR_NAME} ({CHANNEL_NAME})"
        final_output_html = str(main_soup)
    else:
        combined_text = "\n\n".join(session["texts"])
        try:
            ai_struct_prompt = f"""
नीचे दिए गए यूपीएससी अध्ययन टेक्स्ट को सुव्यवस्थित, परीक्षा-उपयोगी और आकर्षक रूप दें:
"{combined_text[:3500]}"

नियम:
1. मुख्य हेडिंग्स बनाएं (1. संदर्भ, 2. मुख्य बिंदु, 3. चुनौतियाँ, 4. आगे की राह, 5. Prelims Facts)।
2. जहाँ भी तुलना, चरण या वर्गीकरण हो, 2-कॉलम टेबल प्रारूप में लिखें (पहली पंक्ति हेडर 'चरण' और 'विवरण')।
3. प्रत्येक मुद्दे का समाचार स्रोत अवश्य लिखें।
4. अनावश्यक स्टार्स (**) का प्रयोग न करें। भाषा शुद्ध हिंदी रखें।
"""
            enhanced_text = await asyncio.to_thread(call_gemini_safely, ai_struct_prompt)
        except Exception:
            enhanced_text = combined_text

        final_output_html = build_interactive_dashboard_html(final_topic, enhanced_text, session["images"])

    save_to_archive("daily", final_topic, clean_filename, final_output_html)

    with open(clean_filename, "w", encoding="utf-8") as f:
        f.write(final_output_html)

    with open(clean_filename, "rb") as send_doc:
        await update.message.reply_document(
            document=send_doc,
            filename=clean_filename,
            caption=(
                f"📄 <b>नोट्स फ़ाइल तैयार!</b>\n"
                f"📌 <b>विषय:</b> <code>{final_topic}</code>\n"
                f"👤 <b>निर्माता:</b> {AUTHOR_NAME}\n"
                f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
            ),
            parse_mode=ParseMode.HTML,
        )

    await wait_msg.delete()
    if os.path.exists(clean_filename):
        os.remove(clean_filename)

    USER_BUFFERS.pop(user_id, None)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    USER_BUFFERS.pop(user_id, None)
    CONTACT_SESSIONS.pop(user_id, None)
    await update.message.reply_text("प्रक्रिया रद्द कर दी गई।")
    return ConversationHandler.END

# ================= RENDER KEEP-ALIVE SERVER =================
async def run_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="UPSC Smart Bot Active 24/7 with IST Clock & Trending Radar"))
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
    bot_app.add_handler(CommandHandler("trending", trending_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    bot_app.add_handler(CommandHandler("generate", ai_generate_cmd))
    bot_app.add_handler(CommandHandler("ask", ask_doubt_cmd))
    bot_app.add_handler(CommandHandler("adduser", add_user_cmd))
    bot_app.add_handler(CommandHandler("removeuser", remove_user_cmd))
    bot_app.add_handler(CommandHandler("listusers", list_users_cmd))

    bot_app.add_handler(CallbackQueryHandler(handle_mcq_button_click, pattern=r"^mcq_\d+$"))
    bot_app.add_handler(CallbackQueryHandler(handle_dynamic_generation_click, pattern=r"^(gendate|genmonth|genyear|genweek)_"))

    contact_conv = ConversationHandler(
        entry_points=[
            CommandHandler("owner", contact_cmd),
            CommandHandler("contact", contact_cmd),
        ],
        states={
            WAITING_CONTACT_MSG: [
                MessageHandler(filters.TEXT & (~filters.COMMAND), forward_contact_msg)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(contact_conv)

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={
            WAITING_BROADCAST_MSG: [
                MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), execute_broadcast)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(broadcast_conv)

    html_conv = ConversationHandler(
        entry_points=[CommandHandler("sachin", ask_for_name)],
        states={
            WAITING_FOR_NAME: [
                MessageHandler(filters.TEXT & (~filters.COMMAND), generate_final_file)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(html_conv)

    bot_app.add_handler(CommandHandler("html", start_html_session))
    bot_app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_admin_reply_to_user))
    bot_app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), collect_messages))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
