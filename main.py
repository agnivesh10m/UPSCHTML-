import os
import re
import time
import asyncio
import base64
import sqlite3
from datetime import datetime, timedelta
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
        """, (user_id, username or "", first_name or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
                expiry = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
                if datetime.now() <= expiry:
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
        now = datetime.now()
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

# ================= AI GENERATION (ROBUST NO-ERROR) =================
def call_gemini_safely(prompt: str) -> str:
    api_k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_k:
        raise Exception("GEMINI_API_KEY Render Environment में सेट नहीं है।")

    genai.configure(api_key=api_k)

    # 3.8 Flash और नए मॉडल्स की प्राथमिकता सूची
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
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

    raise Exception(f"AI मॉडल से कनेक्ट नहीं हो सका: {last_err}")

# ================= PREMIUM HTML BUILDER =================
def build_interactive_dashboard_html(topic: str, raw_text: str, image_list: list = None) -> str:
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    sections = []
    current_sec_title = "भूमिका एवं सामान्य अवलोकन"
    current_sec_lines = []

    for line in lines:
        is_heading = (
            re.match(r'^[0-9]+\.\s*', line) 
            or any(line.startswith(x) for x in ["📌", "🎯", "⚡", "📖", "💡", "🗳️", "⚖️", "🔍", "📝", "🛣️", "❄️", "🌏", "📰", "🌍", "🌱", "🔬", "💰", "🔑", "🔸", "📚"])
            or (line.endswith(':') and len(line) < 55)
        )
        if is_heading:
            if current_sec_lines:
                sections.append((current_sec_title, current_sec_lines))
                current_sec_lines = []
            current_sec_title = line
        else:
            current_sec_lines.append(line)
            
    if current_sec_lines or current_sec_title:
        sections.append((current_sec_title, current_sec_lines))

    nav_links_html = ""
    content_html = ""

    for idx, (sec_title, sec_lines) in enumerate(sections, 1):
        sec_id = f"topic-sec-{idx}"
        clean_nav_name = re.sub(r'^[0-9]+\.\s*', '', sec_title)
        clean_nav_name = re.sub(r'[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍🔑|━─—_:-🔸📚]', '', clean_nav_name).strip()
        if len(clean_nav_name) > 22:
            clean_nav_name = clean_nav_name[:20] + ".."
        if not clean_nav_name:
            clean_nav_name = f"विषय {idx}"

        nav_links_html += f'<a href="#{sec_id}">{clean_nav_name}</a>\n'

        sec_body_html = ""
        in_pipe_table = False
        pipe_table_rows = []
        i = 0
        n = len(sec_lines)

        while i < n:
            line = sec_lines[i]

            if line.startswith('|') and line.endswith('|') and len(line.split('|')) >= 3:
                cells = [c.strip() for c in line.split('|')[1:-1]]
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

            # 2-कॉलम टेबल पार्सर
            is_table_header = (
                (line in ["चरण", "विषय", "क्षेत्र", "तकनीक", "प्रावधान", "Article", "घटक", "आयाम", "क्रम", "आस्पेक्ट"]) 
                and (i + 1 < n)
            )
            if is_table_header:
                th1 = line
                th2 = sec_lines[i+1]
                table_html = f"<div class='table-box'><table><tr><th class='th-cell'>{th1}</th><th class='th-cell'>{th2}</th></tr>"
                i += 2
                while i + 1 < n:
                    c1 = sec_lines[i]
                    c2 = sec_lines[i+1]
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

            formatted = re.sub(r'\*\*(.*?)\*\*', r'<strong class="hl-bold">\1</strong>', formatted)
            formatted = re.sub(r'(GS-[I|II|III|IV]+|GS-\d)', r'<span class="badge-gs">\1</span>', formatted)
            formatted = re.sub(r'(Article\s+\d+[A-Za-z]?|अनुच्छेद\s+\d+[A-Za-z]?)', r'<span class="badge-art">\1</span>', formatted, flags=re.IGNORECASE)
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
.controls {{
  display:flex; justify-content:center; gap:10px; margin-top:14px; flex-wrap:wrap;
}}
.controls input {{
  width:min(380px,85vw); padding:9px 15px; border-radius:20px; border:none; outline:none; font-size:0.9rem;
}}
.controls button {{
  padding:9px 18px; border-radius:20px; border:1px solid rgba(255,255,255,.4);
  background:rgba(255,255,255,.2); color:#fff; font-weight:600; cursor:pointer;
}}
nav.dashboard {{
  position:sticky; top:0; z-index:50; background:var(--card); border-bottom:1px solid var(--border);
  box-shadow:var(--shadow); overflow-x:auto; white-space:nowrap; padding:9px 14px;
}}
nav.dashboard .nav-wrap {{ display:flex; gap:8px; max-width:920px; margin:0 auto; }}
nav.dashboard a {{
  display:inline-block; padding:6px 14px; background:var(--tag-bg); color:var(--tag-text);
  border-radius:16px; font-size:0.84rem; font-weight:600; text-decoration:none; flex:none;
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
.badge-gs {{
  background:#0284c7; color:#fff; padding:2px 8px; border-radius:6px; font-size:0.82rem; font-weight:bold; margin:0 4px;
}}
.badge-art {{
  background:#10b981; color:#fff; padding:2px 8px; border-radius:6px; font-size:0.82rem; font-weight:bold; margin:0 4px;
}}
.text-link {{ color:#0284c7; text-decoration:underline; font-weight:600; }}
.flow-container {{
  display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; align-items:center;
}}
.flow-step {{
  background:var(--tag-bg); color:var(--tag-text); border:1px solid var(--border);
  padding:5px 12px; border-radius:8px; font-size:0.88rem; font-weight:600;
  display:inline-flex; align-items:center;
}}
.flow-step:not(:last-child)::after {{
  content:"→"; margin-left:8px; color:var(--muted); font-weight:bold;
}}
blockquote {{
  border-left:4px solid var(--accent); background:var(--tag-bg);
  padding:12px 16px; border-radius:0 8px 8px 0; margin:15px 0; font-weight:500; font-style:italic;
}}
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
footer {{
  background:#071529; color:#dbe6f2; text-align:center; padding:26px 16px; margin-top:35px; font-size:0.88rem;
}}
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

# ================= PUBLIC MENU & DYNAMIC BUTTONS =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    is_admin = user.id in ADMIN_IDS
    authorized = is_authorized(user.id)

    if is_admin:
        msg = (
            f"👋 <b>नमस्ते एडमिन {AUTHOR_NAME}!</b>\n\n"
            "👑 <b>एडमिन कंट्रोल सक्रिय है:</b>\n"
            "• <code>/generate &lt;तारीख/विषय&gt;</code> — AI से नोट्स व सारणी बनवाएं\n"
            "• <code>/html</code> — PDF / टेक्स्ट संग्रह शुरू करें\n"
            "• <code>/sachin</code> — संयुक्त HTML फ़ाइल बनाएं\n"
            "• <code>/broadcast</code> — सभी को मैसेज भेजें\n"
            "• <code>/adduser</code> | <code>/removeuser</code> | <code>/listusers</code> — मेंबर्स संभालें\n\n"
            "📚 <b>आर्काइव कमांड्स:</b>\n"
            "• <code>/daily</code> | <code>/weekly</code> | <code>/monthly</code> | <code>/yearly</code>\n"
            "• <code>/ask &lt;सवाल&gt;</code> — डाउट पूछें व 4 MCQs पाएं"
        )
    elif authorized:
        msg = (
            f"👋 <b>नमस्ते अधिकृत सदस्य {user.first_name}!</b>\n\n"
            "🌟 <b>आपके पास विशेष अध्ययन एक्सेस है:</b>\n"
            "• <code>/generate &lt;तारीख/विषय&gt;</code> — AI नोट्स तैयार कराएं\n"
            "• <code>/ask &lt;सवाल&gt;</code> — सवाल पूछें व 4 अभ्यास MCQs पाएं\n"
            "• <code>/daily</code> | <code>/weekly</code> | <code>/monthly</code> | <code>/yearly</code> — नोट्स देखें"
        )
    else:
        msg = (
            f"👋 <b>नमस्ते {user.first_name}!</b>\n\n"
            f"📚 <b>UPSC HTML Notes Portal में आपका स्वागत है!</b>\n\n"
            "दैनिक, साप्ताहिक और मासिक नोट्स के लिए नीचे दिए कमांड चलाएं:\n\n"
            "📅 <b>दैनिक नोट्स:</b> <code>/daily</code>\n"
            "🗓️ <b>साप्ताहिक नोट्स:</b> <code>/weekly</code>\n"
            "📁 <b>मासिक पत्रिका:</b> <code>/monthly</code>\n"
            "🏛️ <b>वार्षिक कंपाइलेशन:</b> <code>/yearly</code>\n"
            "💬 <b>ओनर से संपर्क:</b> <code>/owner</code>\n\n"
            f"👤 <b>निर्माता:</b> {AUTHOR_NAME}\n"
            f"📢 <b>ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    help_text = (
        "📖 <b>UPSC HTML BOT — सहायता केंद्र</b>\n\n"
        "1️⃣ <b>दैनिक नोट्स:</b>\n"
        "• <code>/daily</code> दबाएं — आज की तारीख, पिछली 5 तारीखें और अगली 3 तारीखों के बटन मिलेंगे। जिस पर भी क्लिक करेंगे, उसका पूरा HTML नोट्स तुरंत तैयार होकर मिल जाएगा।\n\n"
        "2️⃣ <b>मासिक या वार्षिक नोट्स:</b>\n"
        "• <code>/monthly</code> — पूरे माह का कंपाइलेशन और सभी प्रश्न एक साथ।\n"
        "• <code>/yearly</code> — सम्पूर्ण वार्षिक डाइजेस्ट।\n\n"
        "3️⃣ <b>सीधे एडमिन से संपर्क:</b>\n"
        "• <code>/owner</code> दबाएं और 2 मिनट में अपनी बात लिखें।\n\n"
        f"📢 <b>ऑफिशियल ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# /daily: आज, पिछले 5 दिन और अगले 3 दिन के डायनामिक बटन
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    
    today = datetime.now()
    keyboard = []
    
    # 5 दिन पहले से लेकर 3 दिन आगे तक की तारीखें
    for i in range(-5, 4):
        target_dt = today + timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        
        if i == 0:
            label = f"🌟 आज ({d_str})"
        elif i < 0:
            label = f"📅 {d_str} (-{-i} दिन)"
        else:
            label = f"🔮 {d_str} (+{i} दिन)"
            
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📅 <b>जिस तारीख के UPSC नोट्स चाहिए, उस बटन पर क्लिक करें:</b>\n"
        "<i>(यदि डेटाबेस में नहीं होगा, तो AI तुरंत आपके लिए तैयार करेगा)</i>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

# /monthly: माह के बटन
async def monthly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    
    months = [
        "September 2026", "August 2026", "July 2026", 
        "June 2026", "May 2026", "April 2026"
    ]
    keyboard = []
    for m in months:
        keyboard.append([InlineKeyboardButton(f"📁 {m} पत्रिका", callback_data=f"genmonth_{m}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📁 <b>जिस महीने का UPSC कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

# /yearly: वर्ष के बटन
async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    
    years = ["2026", "2025", "2024"]
    keyboard = []
    for y in years:
        keyboard.append([InlineKeyboardButton(f"📚 वर्ष {y} वार्षिक संकलन", callback_data=f"genyear_{y}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🏛️ <b>जिस वर्ष का वार्षिक कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = datetime.now()
    d_str = today.strftime("%Y-%m-%d")
    
    keyboard = [
        [InlineKeyboardButton("🗓️ इस सप्ताह का क्विक रिवीजन", callback_data=f"genweek_{d_str}")],
        [InlineKeyboardButton("🗓️ पिछले सप्ताह का रिवीजन", callback_data=f"genweek_{(today - timedelta(days=7)).strftime('%Y-%m-%d')}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🗓️ <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>", reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# बटन क्लिक होने पर सीधे फ़ाइल भेजना या AI से ऑटो-जनरेट करना
async def handle_dynamic_generation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    try:
        await query.message.delete()
    except Exception:
        pass

    # 1. तारीख आधारित जनरेशन (gendate_YYYY-MM-DD)
    if data.startswith("gendate_"):
        target_date = data.split("_")[1]
        arch_data = get_archive_by_date(target_date)
        
        if arch_data:
            topic, filename, html_content = arch_data
        else:
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ <b>{target_date}</b> के लिए AI द्वारा सम्पूर्ण UPSC नोट्स व सारणी तैयार की जा रही है...", parse_mode=ParseMode.HTML)
            prompt = f"""
आप UPSC CSE परीक्षा के मुख्य कंटेंट विश्लेषक और मेंटर हैं।
तारीख: "{target_date}" के लिए 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित, पूर्ण और समृद्ध दैनिक नोट्स तैयार करें।
सभी जीएस पेपर्स (GS-1: इतिहास/भूगोल, GS-2: राजव्यवस्था/IR, GS-3: अर्थव्यवस्था/पर्यावरण/सुरक्षा) को शामिल करें।

नियम:
1. मुख्य शीर्षक स्पष्ट दें।
2. जहाँ भी चरण, तुलना या वर्गीकरण हो, 2-कॉलम टेबल प्रारूप में लिखें (पहली पंक्ति हेडर जैसे 'चरण' और 'विवरण')।
3. प्रमुख बिंदुओं को बुलेट और कोलन (:) के साथ लिखें।
4. 📌 Prelims Facts & Key Concepts (फ्लो दिखाने के लिए → का प्रयोग करें)।
5. 📝 Mains Question & 4 Practice MCQs अवश्य शामिल करें।
भाषा हिंदी रखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Daily Notes — {target_date}"
                filename = f"UPSC_Notes_{target_date}.html"
                html_content = build_interactive_dashboard_html(topic, ai_text)
                save_to_archive("daily", topic, filename, html_content, date_str=target_date)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ नोट्स तैयार करने में समस्या आई: {e}")
                return

    # 2. माह आधारित जनरेशन (genmonth_Month Year)
    elif data.startswith("genmonth_"):
        m_name = data.split("_")[1]
        arch_data = get_archive_by_period_name("monthly", m_name)
        
        if arch_data:
            topic, filename, html_content = arch_data
        else:
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ <b>{m_name}</b> का सम्पूर्ण मासिक कंपाइलेशन तैयार हो रहा है (सभी प्रश्न एक साथ)...", parse_mode=ParseMode.HTML)
            prompt = f"""
आप UPSC CSE परीक्षा के मुख्य कंटेंट विश्लेषक हैं।
माह: "{m_name}" का सम्पूर्ण UPSC Monthly Current Affairs Digest तैयार करें।
- GS-1, GS-2, GS-3 के सभी महत्वपूर्ण विषयवार घटनाक्रम।
- 2-कॉलम टेबल्स और फ्लोचार्ट्स।
- अंत में एक विशेष सेक्शन: "📚 सम्पूर्ण माह के 15-20 अभ्यास प्रश्न (MCQs) एवं मेन्स प्रश्न बैंक" जिसमें सभी प्रश्नों को एक साथ क्रमबद्ध किया गया हो।
भाषा हिंदी रखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Monthly Digest — {m_name}"
                filename = f"UPSC_Monthly_{m_name.replace(' ', '_')}.html"
                html_content = build_interactive_dashboard_html(topic, ai_text)
                save_to_archive("monthly", topic, filename, html_content)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ मासिक पत्रिका तैयार करने में त्रुटि: {e}")
                return

    # 3. वर्ष आधारित जनरेशन (genyear_YYYY)
    elif data.startswith("genyear_"):
        y_name = data.split("_")[1]
        arch_data = get_archive_by_period_name("yearly", y_name)
        
        if arch_data:
            topic, filename, html_content = arch_data
        else:
            wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ वर्ष <b>{y_name}</b> का वार्षिक कंपाइलेशन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
            prompt = f"""
वर्ष {y_name} का UPSC Civil Services Annual Compendium (PT-365 Style) तैयार करें।
- संविधान, राजव्यवस्था, अर्थव्यवस्था, पर्यावरण एवं वैश्विक संबंध के सभी मुख्य वार्षिक मुद्दे।
- 2-कॉलम टेबल्स और तुलनात्मक अध्ययन।
- वर्ष के प्रमुख अभ्यास प्रश्न।
भाषा हिंदी रखें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"UPSC Annual Compendium — {y_name}"
                filename = f"UPSC_Annual_{y_name}.html"
                html_content = build_interactive_dashboard_html(topic, ai_text)
                save_to_archive("yearly", topic, filename, html_content)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ वार्षिक कंपाइलेशन में त्रुटि: {e}")
                return

    # 4. साप्ताहिक जनरेशन
    elif data.startswith("genweek_"):
        w_date = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text="⏳ साप्ताहिक रिवीजन डाइजेस्ट तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"सप्ताह ({w_date}) के सभी मुख्य UPSC घटनाक्रमों का 7-दिवसीय रिवीजन डाइजेस्ट 2-कॉलम टेबल्स और 5 प्रश्नों के साथ हिंदी में तैयार करें।"
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

    # फ़ाइल भेजना
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open(filename, "rb") as send_doc:
        await context.bot.send_document(
            chat_id=user_id,
            document=send_doc,
            filename=filename,
            caption=(
                f"📄 <b>UPSC नोट्स डाउनलोड:</b> <code>{topic}</code>\n"
                f"👤 <b>संकलन:</b> {AUTHOR_NAME}\n"
                f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
            ),
            parse_mode=ParseMode.HTML,
        )

    if os.path.exists(filename):
        os.remove(filename)

# ================= AI GENERATE COMMAND & DOUBT SOLVER =================
async def ai_generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ यह फीचर केवल अधिकृत सदस्यों के लिए है।")
        return

    if not context.args:
        await update.message.reply_text(
            "💡 <b>उपयोग का तरीका:</b>\n"
            "<code>/generate 29 September 2026</code>\n"
            "<code>/generate AI in Disaster Management</code>",
            parse_mode=ParseMode.HTML
        )
        return

    query = " ".join(context.args).replace("[", "").replace("]", "").strip()
    status_msg = await update.message.reply_text(
        f"🤖 <b>AI रिसर्च जारी है...</b>\n\n"
        f"विषय: <code>{query}</code>\n"
        "GS-1, 2, 3, 4 के सभी आयाम व 2-कॉलम सारणी तैयार की जा रही है...",
        parse_mode=ParseMode.HTML
    )

    try:
        prompt = f"""
आप UPSC CSE परीक्षा के मुख्य कंटेंट विश्लेषक और वरिष्ठ मेंटर हैं।
निम्नलिखित विषय/तारीख पर 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित, पूर्ण और समृद्ध नोट्स तैयार करें:
विषय: "{query}"

सख्त संरचना नियम:
1. पहली पंक्ति में मुख्य शीर्षक दें।
2. सभी संबंधित विषयों को अनिवार्य रूप से शामिल करें (GS-1: इतिहास/भूगोल, GS-2: राजव्यवस्था/संविधान/IR, GS-3: अर्थव्यवस्था/पर्यावरण/सुरक्षा)।
3. मुख्य हेडिंग्स:
   - 1. संदर्भ / चर्चा में क्यों
   - 2. संवैधानिक एवं वैधानिक स्थिति (संबद्ध अनुच्छेद, कानून व केस लॉ)
   - 3. मुख्य विश्लेषण (जहाँ भी चरण, तुलना या वर्गीकरण हो, 2-कॉलम टेबल प्रारूप में लिखें: पहली पंक्ति हेडर जैसे 'चरण' और 'विवरण')
   - 4. प्रमुख तकनीकें / चुनौतियाँ (बुलेट पॉइंट्स में, मुख्य शब्दों के आगे कोलन : लगाएं)
   - 5. आगे की राह (Way Forward)
   - 6. 📌 Prelims Facts & Key Concepts (फ्लो दिखाने के लिए → का प्रयोग करें)
   - 7. 📝 Mains Question & 4 Practice MCQs (व्याख्या सहित)
भाषा हिंदी रखें।
"""
        ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_topic = re.sub(r'[^\w\s-]', '', query).strip()[:40]
        html_output = build_interactive_dashboard_html(clean_topic, ai_text)

        filename = f"{re.sub(r'[^a-zA-Z0-9\u0900-\u097F]', '_', clean_topic)[:25]}.html"
        save_to_archive("daily", clean_topic, filename, html_output)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_output)

        with open(filename, "rb") as send_doc:
            await update.message.reply_document(
                document=send_doc,
                filename=filename,
                caption=(
                    f"✨ <b>UPSC Master Notes (Zero to Hero)</b>\n"
                    f"📌 <b>विषय:</b> <code>{clean_topic}</code>\n"
                    f"👤 <b>संकलन:</b> {AUTHOR_NAME}\n"
                    f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                ),
                parse_mode=ParseMode.HTML,
            )

        await status_msg.delete()
        if os.path.exists(filename):
            os.remove(filename)

    except Exception as e:
        await status_msg.edit_text(f"❌ AI जनरेशन में त्रुटि आई: {e}")

async def ask_doubt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ यह सुविधा केवल अधिकृत छात्रों के लिए है।")
        return

    if not context.args:
        await update.message.reply_text("💡 पूछने के लिए लिखें: <code>/ask आपका सवाल या टॉपिक</code>", parse_mode=ParseMode.HTML)
        return

    user_query = " ".join(context.args).strip()
    wait_msg = await update.message.reply_text("🤔 UPSC परिप्रेक्ष्य में विश्लेषण और 4 अभ्यास प्रश्न तैयार हो रहे हैं...")

    non_upsc_triggers = ["मौसम कैसा है", "गाना सुनाओ", "तुम कौन हो", "मजाक", "शायरी", "लव", "गर्लफ्रेंड"]
    if any(t in user_query.lower() for t in non_upsc_triggers):
        await wait_msg.edit_text(
            f"⚠️ <b>कृपया सचिन भाई ({AUTHOR_NAME}) से संपर्क करें।</b>\n"
            "उन्होंने हमें केवल UPSC सिविल सेवा अध्ययन सामग्री एवं करेंट अफेयर्स विश्लेषण के लिए प्रशिक्षित किया है।",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        prompt = f"""
आप UPSC सिविल सेवा परीक्षा के विशेषज्ञ मेंटर हैं।
छात्र के इस सवाल का सटीक, परीक्षा-उन्मुख एवं बिंदुवार उत्तर हिंदी में दें:
सवाल: "{user_query}"

इसके तुरंत बाद, इसी टॉपिक से संबंधित UPSC Prelims स्तर के 4 बहुविकल्पीय अभ्यास प्रश्न (4 MCQs) बनाएं।
प्रत्येक प्रश्न के 4 विकल्प (a, b, c, d), सही उत्तर और 1 पंक्ति का स्पष्टीकरण अवश्य दें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        
        if len(reply_text) > 4000:
            parts = [reply_text[i:i+3900] for i in range(0, len(reply_text), 3900)]
            await wait_msg.delete()
            for p in parts:
                await update.message.reply_text(p)
        else:
            await wait_msg.edit_text(reply_text)
    except Exception as e:
        await wait_msg.edit_text(f"❌ उत्तर देने में समस्या आई: {e}")

# ================= USER MEMBERSHIP MANAGEMENT (ADMIN) =================
async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return

    if len(context.args) < 2:
        await update.message.reply_text("💡 उपयोग: <code>/adduser &lt;user_id&gt; &lt;days&gt;</code>", parse_mode=ParseMode.HTML)
        return

    try:
        target_uid = int(context.args[0])
        days = int(context.args[1])
        expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, is_vip, vip_expiry, joined_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET is_vip = 1, vip_expiry = ?
        """, (target_uid, expiry_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expiry_date))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ यूज़र <code>{target_uid}</code> को <b>{days} दिन</b> की वैधता के साथ अधिकृत कर दिया गया है।", parse_mode=ParseMode.HTML)
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
        target_uid = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = ?", (target_uid,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🚫 यूज़र <code>{target_uid}</code> का एक्सेस समाप्त कर दिया गया है।", parse_mode=ParseMode.HTML)
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

# ================= CONTACT / OWNER FEEDBACK (2 MIN TIMER) =================
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
        await update.message.reply_text("⚠️ <b>समय समाप्त!</b> 2 मिनट पूरे हो चुके हैं। पुनः प्रयास के लिए <code>/owner</code> भेजें।", parse_mode=ParseMode.HTML)
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

    await update.message.reply_text("✅ <b>आपका संदेश ओनर को भेज दिया गया है!</b> जैसे ही वे देखेंगे, आपको यहीं उत्तर मिल जाएगा।", parse_mode=ParseMode.HTML)
    CONTACT_SESSIONS.pop(user_id, None)
    return ConversationHandler.END

async def handle_admin_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        return

    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return

    reply_to_text = msg.reply_to_message.text or ""
    match = re.search(r"यूज़र ID:\s*<code>(\d+)</code>", reply_to_text)
    if match:
        target_user_id = int(match.group(1))
        reply_body = msg.text or msg.caption or ""

        user_notification = (
            f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n"
            f"{reply_body}\n\n"
            f"📢 <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
        )
        try:
            await context.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            await msg.reply_text("✅ जवाब छात्र को सफलतापूर्वक भेज दिया गया!")
        except Exception as e:
            await msg.reply_text(f"❌ छात्र तक मैसेज नहीं पहुँचा: {e}")

# ================= BROADCAST SYSTEM =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह केवल एडमिन के लिए है।")
        return ConversationHandler.END

    all_users = get_all_users()
    await update.message.reply_text(
        f"📢 <b>ब्रॉडकास्ट प्रणाली</b>\n\n"
        f"कुल पंजीकृत छात्र: <b>{len(all_users)}</b>\n\n"
        "वह संदेश भेजें जो सभी को पहुँचाना है:\n<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
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

    report = (
        "✅ <b>ब्रॉडकास्ट समाप्त!</b>\n\n"
        f"🎯 <b>सफल डिलीवरी:</b> {success_count} छात्र\n"
        f"❌ <b>असफल:</b> {fail_count} छात्र\n"
        f"📊 <b>कुल:</b> {len(all_users)}"
    )
    await status_msg.edit_text(report, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# ================= MANUAL PDF/TEXT SESSION (/html, /sachin) =================
async def start_html_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ यह कमांड केवल एडमिन एवं अधिकृत मेंबर्स के लिए है।")
        return

    USER_BUFFERS[user_id] = {
        "active": True,
        "texts": [],
        "images": [],
        "html_soups": [],
        "suggested_topic": "UPSC_Notes",
    }
    await update.message.reply_text("🟢 <b>सत्र चालू!</b> जितनी चाहें PDF, HTML या लंबे फॉरवर्डेड मैसेज भेजें, फिर <code>/sachin</code> भेजें।", parse_mode=ParseMode.HTML)

async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    session = USER_BUFFERS.get(user_id)
    if not session or not session.get("active"):
        return

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

    elif msg.document:
        doc_f = await msg.document.get_file()
        fname = msg.document.file_name.lower()
        
        if fname.endswith(".pdf"):
            t_pdf = f"doc_{msg.document.file_name}"
            await doc_f.download_to_drive(t_pdf)
            try:
                reader = PdfReader(t_pdf)
                pdf_text = ""
                for page in reader.pages:
                    txt = page.extract_text()
                    if txt:
                        pdf_text += txt + "\n"
                if pdf_text:
                    session["texts"].append(pdf_text)
                    if session["suggested_topic"] == "UPSC_Notes":
                        session["suggested_topic"] = fname.replace(".pdf", "")[:35]
            except Exception as e:
                print(f"Error reading PDF: {e}")
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

    if raw_text:
        session["texts"].append(raw_text)
        lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
        if lines and session["suggested_topic"] == "UPSC_Notes":
            first_l = re.sub(r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍🔑|━─—_-]", "", lines[0]).strip()
            if "—" in first_l:
                first_l = first_l.split("—")[0].strip()
            elif "-" in first_l:
                first_l = first_l.split("-")[0].strip()
            session["suggested_topic"] = first_l[:40] if first_l else "UPSC_Notes"

async def ask_for_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ यह कमांड केवल अधिकृत मेंबर्स के लिए है।")
        return ConversationHandler.END

    session = USER_BUFFERS.get(user_id)
    if not session or (not session.get("texts") and not session.get("html_soups")):
        await update.message.reply_text("❌ कोई सामग्री नहीं मिली। पहले <code>/html</code> भेजें।", parse_mode=ParseMode.HTML)
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

    wait_msg = await update.message.reply_text("⏳ AI सामग्री का गहन विश्लेषण कर रहा है व सारणी तैयार कर रहा है...")

    final_output_html = ""
    if session["html_soups"]:
        main_soup = session["html_soups"][0]
        sanitize_and_rebrand_html(main_soup, custom_title=final_topic)
        final_output_html = str(main_soup)
    else:
        combined_text = "\n\n".join(session["texts"])
        try:
            ai_struct_prompt = f"""
आप UPSC कंटेंट एक्सपर्ट हैं। नीचे दिए गए टेक्स्ट को व्यवस्थित, परीक्षा-उपयोगी और आकर्षक रूप दें:
"{combined_text[:3500]}"

नियम:
1. मुख्य हेडिंग्स बनाएं (1. संदर्भ, 2. मुख्य बिंदु, 3. चुनौतियाँ, 4. आगे की राह, 5. Prelims Facts)।
2. जहाँ भी तुलना, चरण या वर्गीकरण हो, 2-कॉलम टेबल प्रारूप में लिखें (पहली पंक्ति हेडर जैसे 'चरण' और 'विवरण')।
3. भाषा हिंदी रखें।
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
    app.router.add_get("/", lambda r: web.Response(text="UPSC Smart AI Bot Active 24/7"))
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

    bot_app.add_handler(CommandHandler("generate", ai_generate_cmd))
    bot_app.add_handler(CommandHandler("ask", ask_doubt_cmd))

    bot_app.add_handler(CommandHandler("adduser", add_user_cmd))
    bot_app.add_handler(CommandHandler("removeuser", remove_user_cmd))
    bot_app.add_handler(CommandHandler("listusers", list_users_cmd))

    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CommandHandler("help", help_handler))
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    # इनलाइन बटनों द्वारा डायनामिक जनरेशन हैंडलर
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

    bot_app.add_handler(CommandHandler("html", start_html_session))
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

    bot_app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_admin_reply_to_user))
    bot_app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), collect_messages))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
