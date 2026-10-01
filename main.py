import os
import re
import time
import json
import asyncio
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
JSON_BACKUP_PATH = "persistent_users.json"

# ================= DATABASE & PERSISTENCE =================
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

    # स्थायी JSON बैकअप से रिस्टोर (ताकि रीडिप्लॉय होने पर डेटा कभी न मिटे)
    if os.path.exists(JSON_BACKUP_PATH):
        try:
            with open(JSON_BACKUP_PATH, "r", encoding="utf-8") as f:
                saved_users = json.load(f)
            for u in saved_users:
                c.execute("""
                    INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, is_vip, vip_expiry)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (u["user_id"], u.get("username", ""), u.get("first_name", ""), u.get("joined_at", ""), u.get("is_vip", 0), u.get("vip_expiry", None)))
            conn.commit()
        except Exception as e:
            print(f"Error restoring backup: {e}")
    conn.close()

init_db()

def save_users_to_json_backup():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, joined_at, is_vip, vip_expiry FROM users")
        rows = c.fetchall()
        conn.close()
        user_list = [
            {"user_id": r[0], "username": r[1], "first_name": r[2], "joined_at": r[3], "is_vip": r[4], "vip_expiry": r[5]}
            for r in rows
        ]
        with open(JSON_BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(user_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"JSON backup error: {e}")

def register_user(user_id, username, first_name):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            INSERT INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                username = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username or "", first_name or "", now_str))
        conn.commit()
        conn.close()
        save_users_to_json_backup()
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
    except Exception:
        pass
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

# ================= 3.8 FLASH PRIORITY (NO 404) =================
def call_gemini_safely(prompt: str) -> str:
    api_k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_k:
        raise Exception("API Key सर्वर पर सेट नहीं है।")

    genai.configure(api_key=api_k)
    generation_config = {
        "temperature": 0.35,
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

def clean_stars_and_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'(\*{2,}|_{2,})', '', text)
    return text.strip()

# ================= DYNAMIC QUIZ & FULL HTML DASHBOARD =================
def build_standalone_master_html(topic: str, raw_content: str, quiz_questions: list = None) -> str:
    clean_html = raw_content.strip()
    if clean_html.startswith("```html"):
        clean_html = clean_html[7:]
    elif clean_html.startswith("```"):
        clean_html = clean_html[3:]
    if clean_html.endswith("```"):
        clean_html = clean_html[:-3]
    clean_html = clean_html.strip()

    if not quiz_questions:
        quiz_questions = [
            {"question": f"{topic} के संदर्भ में प्राथमिक विधिक ढांचा क्या है?", "a": "संविधान की 7वीं अनुसूची", "b": "मूल अधिकार (भाग III)", "c": "राज्य के नीति निर्देशक तत्व", "d": "संसदीय अधिनियम", "ans": "a", "explain": "यह विषय भारतीय प्रशासनिक व विधिक व्यवस्था से प्रत्यक्ष रूप से संबंधित है।"}
        ]

    quiz_inputs_html = ""
    js_answers_obj = {}
    for idx, q in enumerate(quiz_questions, 1):
        q_key = f"q{idx}"
        js_answers_obj[q_key] = q.get("ans", "a").lower()
        quiz_inputs_html += f"""
        <div class="mcq-box">
          <p><strong>प्रश्न {idx}: {q.get('question', '')}</strong></p>
          <label class="opt-label"><input type="radio" name="{q_key}" value="a"> (a) {q.get('a', '')}</label>
          <label class="opt-label"><input type="radio" name="{q_key}" value="b"> (b) {q.get('b', '')}</label>
          <label class="opt-label"><input type="radio" name="{q_key}" value="c"> (c) {q.get('c', '')}</label>
          <label class="opt-label"><input type="radio" name="{q_key}" value="d"> (d) {q.get('d', '')}</label>
          <div class="mcq-ans" style="display:none;" id="ans-explain-{idx}">
            <strong>सही उत्तर: ({q.get('ans', '').upper()})</strong> — {q.get('explain', '')}
          </div>
        </div>
        """

    answers_json_str = json.dumps(js_answers_obj)

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} | {AUTHOR_NAME}</title>
<link href="[https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap](https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap)" rel="stylesheet">
<style>
:root {{
  --bg: #f4f6f9; --card: #ffffff; --text: #1c2430; --muted: #5b6675; --border: #e2e8f0;
  --accent: #0284c7; --accent-dark: #0369a1; --saffron: #f59e0b; --green: #10b981;
  --tag-bg: #e0f2fe; --tag-text: #0369a1; --shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
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
  .controls, nav.dashboard, #telegramBtn, .print-btn, #quiz-trigger-btn, .theme-btn {{ display: none !important; }}
  .news-card {{ box-shadow: none !important; border: 1px solid #ccc !important; page-break-inside: avoid; margin-bottom: 25px !important; }}
}}
.top-header {{
  background: linear-gradient(135deg, #071529, #0284c7 65%, #0369a1);
  color: #fff; padding: 30px 16px 22px; text-align: center; border-bottom: 4px solid var(--saffron);
}}
.top-header h1 {{ font-size: 1.75rem; margin-bottom: 8px; font-weight: 700; }}
.author-pill {{
  display: inline-block; margin-top: 6px; background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.35); padding: 6px 20px; border-radius: 30px;
  font-weight: 600; font-size: 0.95rem; letter-spacing: 0.5px;
}}
.controls {{ display: flex; justify-content: center; gap: 12px; margin-top: 16px; flex-wrap: wrap; }}
.controls input {{ width: min(360px, 85vw); padding: 10px 16px; border-radius: 20px; border: none; outline: none; font-size: 0.92rem; }}
.controls button {{
  padding: 9px 20px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.2); color: #fff; font-weight: 600; cursor: pointer; transition: all 0.2s ease;
}}
.controls button:hover {{ background: rgba(255, 255, 255, 0.35); }}
nav.dashboard {{
  position: sticky; top: 0; z-index: 50; background: var(--card); border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow); overflow-x: auto; white-space: nowrap; padding: 10px 14px;
}}
nav.dashboard .nav-wrap {{ display: flex; gap: 10px; max-width: 1000px; margin: 0 auto; }}
nav.dashboard a {{
  display: inline-block; padding: 8px 16px; background: var(--tag-bg); color: var(--tag-text);
  border-radius: 18px; font-size: 0.88rem; font-weight: 600; text-decoration: none; flex: none; transition: all 0.2s ease;
}}
nav.dashboard a:hover {{ background: var(--accent); color: #fff; }}
.wrap {{ max-width: 1000px; margin: 26px auto; padding: 0 16px; width: 100%; }}
.news-card {{
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 26px; margin-bottom: 26px; box-shadow: var(--shadow); width: 100%; scroll-margin-top: 70px;
}}
.section-title {{
  color: var(--accent); font-size: 1.35rem; margin-bottom: 16px;
  border-left: 5px solid var(--saffron); padding-left: 14px; font-weight: 700;
}}
.para {{ margin: 10px 0; font-size: 1.02rem; word-break: break-word; text-align: justify; }}
.badge-src {{
  background: #fef3c7; color: #92400e; border: 1px solid #fde68a; padding: 4px 10px;
  border-radius: 6px; font-size: 0.82rem; font-weight: 700; display: inline-block; margin-bottom: 12px;
}}
[data-theme="dark"] .badge-src {{ background: #451a03; color: #fde68a; border-color: #78350f; }}
.badge-art {{
  background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; padding: 3px 8px;
  border-radius: 6px; font-size: 0.84rem; font-weight: 700; display: inline-block; margin-right: 6px;
}}
[data-theme="dark"] .badge-art {{ background: #064e3b; color: #6ee7b7; border-color: #047857; }}
.table-box {{ overflow-x: auto; margin: 18px 0; width: 100%; border-radius: 8px; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ background: var(--accent); color: #fff; padding: 12px 14px; font-size: 0.95rem; font-weight: 600; }}
td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); font-size: 0.95rem; vertical-align: top; }}
tr:nth-child(even) td {{ background: rgba(128, 128, 128, 0.04); }}
.mcq-box {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 14px 0; }}
.opt-label {{ display: block; padding: 10px 14px; margin: 8px 0; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; transition: background 0.2s; }}
.opt-label:hover {{ background: var(--tag-bg); }}
.mcq-ans {{
  background: var(--tag-bg); border-left: 4px solid var(--green); padding: 10px 14px;
  margin-top: 10px; border-radius: 0 6px 6px 0; font-size: 0.92rem;
}}
.quiz-engine-card {{ background: var(--card); border: 2px solid var(--saffron); border-radius: 14px; padding: 26px; margin-top: 30px; }}
.timer-pill {{ background: #ef4444; color: #fff; padding: 5px 14px; border-radius: 20px; font-weight: 700; font-size: 0.9rem; display: inline-block; margin-bottom: 12px; }}
#telegramBtn {{
  position: fixed; bottom: 18px; right: 18px; z-index: 90; background: #229ED9; color: #fff;
  border: none; border-radius: 30px; padding: 12px 22px; font-weight: 700; cursor: pointer; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25); font-size: 0.9rem;
}}
footer {{ background: #071529; color: #dbe6f2; text-align: center; padding: 30px 16px; margin-top: 40px; font-size: 0.9rem; }}
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

<main class="wrap" id="mainContent">
  {clean_html}
  
  <section id="sec-quiz" class="quiz-engine-card">
    <h3 class="section-title" style="color:var(--accent); border-left-color:var(--saffron);">🎯 विषय आधारित लाइव मॉक टेस्ट</h3>
    <p class="para">इस टॉपिक पर आधारित लाइव टेस्ट। प्रत्येक सही उत्तर पर +2.0 अंक, गलत उत्तर पर -0.66 अंक।</p>
    
    <div style="text-align:center; margin: 20px 0;">
      <button id="quiz-trigger-btn" onclick="startDailyQuiz()" style="background:var(--saffron); color:#000; font-weight:700; font-size:1.08rem; padding:12px 28px; border:none; border-radius:30px; cursor:pointer;">📝 टेस्ट प्रारंभ करें (Start Test)</button>
    </div>

    <div id="quiz-area" style="display:none;">
      <div style="text-align:right;"><span class="timer-pill" id="timeRemaining">⏱ शेष समय: 05:00</span></div>
      <form id="dailyUPSCForm">
        {quiz_inputs_html}
        <div style="text-align:center; margin-top:22px;">
          <button type="button" onclick="evaluateQuiz()" style="background:#10b981; color:#fff; font-weight:700; font-size:1.05rem; padding:12px 32px; border:none; border-radius:30px; cursor:pointer;">📊 टेस्ट सबमिट करें</button>
        </div>
      </form>

      <div id="quizScoreZone" style="margin-top:24px;"></div>
    </div>
  </section>
</main>

<button id="telegramBtn" onclick="window.open('{CHANNEL_LINK}','_blank')">📲 TELEGRAM — {CHANNEL_NAME}</button>

<footer>
  <div><b>UPSC CIVIL SERVICES EXAMINATION COMPREHENSIVE STUDY DESK</b></div>
  <div style="margin-top:8px;">संकलन एवं प्रस्तुति: <b>{AUTHOR_NAME}</b> | टेलीग्राम: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
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

let timer = null;
let seconds = 300;
const ANSWER_KEY = {answers_json_str};

function startDailyQuiz() {{
  document.getElementById('quiz-trigger-btn').style.display = 'none';
  document.getElementById('quiz-area').style.display = 'block';

  timer = setInterval(() => {{
    seconds--;
    let m = Math.floor(seconds / 60);
    let s = seconds % 60;
    document.getElementById('timeRemaining').innerText = `⏱ शेष समय: ${{m < 10 ? '0' : ''}}${{m}}:${{s < 10 ? '0' : ''}}${{s}}`;
    if (seconds <= 0) {{
      clearInterval(timer);
      evaluateQuiz();
    }}
  }}, 1000);
}}

function evaluateQuiz() {{
  clearInterval(timer);
  let score = 0;
  let correct = 0;
  let wrong = 0;
  let unattempted = 0;
  let totalQ = Object.keys(ANSWER_KEY).length;

  for (let q in ANSWER_KEY) {{
    const sel = document.querySelector(`input[name="${{q}}"]:checked`);
    const qNum = q.replace('q', '');
    const explainDiv = document.getElementById(`ans-explain-${{qNum}}`);
    if (explainDiv) explainDiv.style.display = 'block';

    if (sel) {{
      if (sel.value.toLowerCase() === ANSWER_KEY[q].toLowerCase()) {{
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

  const maxMarks = totalQ * 2.0;
  const scoreDiv = document.getElementById('quizScoreZone');
  scoreDiv.innerHTML = `
    <div style="background:var(--tag-bg); border:2px solid var(--accent); border-radius:12px; padding:22px; text-align:center;">
      <h3 style="color:var(--accent); font-size:1.3rem;">🏆 आपका आधिकारिक UPSC CSE स्कोरकार्ड</h3>
      <p style="font-size:1.2rem; margin:12px 0;"><strong>प्राप्तांक:</strong> <span style="color:#ef4444; font-weight:700;">${{score.toFixed(2)}} / ${{maxMarks.toFixed(2)}}</span></p>
      <p style="font-size:0.98rem;">✅ सही: <b>${{correct}}</b> | ❌ गलत: <b>${{wrong}}</b> | ⚪ अनुत्तरित: <b>${{unattempted}}</b></p>
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

    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    admin_badge = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if is_admin else "📚 <b>UPSC CSE स्मार्ट अध्ययन पोर्टल</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user_link}!</b>\n\n"
        f"{admin_badge}"
        "नीचे सभी मुख्य कमांड्स उपलब्ध हैं:\n\n"
        "📖 <b>अध्ययन एवं नोट्स:</b>\n"
        "• <code>/daily</code> — दैनिक नोट्स (IST लाइव कैलेंडर)\n"
        "• <code>/quiz</code> — विषयवार लाइव टेस्ट शुरू करें\n"
        "• <code>/trending</code> — चर्चा में चल रहे स्थान व मुद्दे (ID 1, 2, 3...)\n"
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
        "1️⃣ <b>दैनिक नोट्स (`/daily`):</b> भारतीय समय (IST) के अनुसार तारीख चुनें। The Hindu, PIB, Vision IAS, Sanskriti व Drishti IAS के समन्वय से तैयार नोट्स पाएं।\n\n"
        "2️⃣ <b>सीधे PDF भेजें:</b> कोई भी 20 MB तक की PDF भेजें, यह स्वतः उसका 360° HTML नोट्स बनाकर लौटा देगा।\n\n"
        "3️⃣ <b>लाइव टेस्ट (`/quiz`):</b> प्रश्नों की संख्या व विषय चुनकर टेस्ट दें।\n\n"
        "4️⃣ <b>प्रिंट व वॉटरमार्क:</b> सभी फाइलों पर <b>SACHIN SHARMA</b> का 50% विजिबिलिटी वाला वॉटरमार्क प्रिंट होगा।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# /daily: IST कैलेंडर
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now()
    keyboard = []
    
    for i in range(-5, 3):
        target_dt = today + timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        label = f"🌟 आज ({d_str})" if i == 0 else f"📅 {d_str}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 <b>जिस तारीख के UPSC दैनिक नोट्स चाहिए, उस बटन पर क्लिक करें:</b>", reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# /trending: आईडी आधारित सूची
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now().strftime("%Y-%m-%d")
    wait_msg = await update.message.reply_text("🛰 <b>UPSC रडार:</b> समसामयिक स्थानों व मुद्दों का संकलन हो रहा है...", parse_mode=ParseMode.HTML)
    
    prompt = f"""
आज की तारीख {today} के संदर्भ में UPSC CSE परीक्षा हेतु 5 सबसे महत्वपूर्ण स्थानों व मुद्दों की क्रमांकित सूची दें:
प्रारूप:
[ID 1] मुद्दे/स्थान का नाम — संबंधित GS पेपर (जैसे GS-1 या GS-2) व संक्षिप्त कारण (2 पंक्ति)
[ID 2] ...
[ID 3] ...
[ID 4] ...
[ID 5] ...
भाषा शुद्ध हिंदी रखें।
"""
    try:
        trend_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_text = clean_stars_and_markdown(trend_text)
        await wait_msg.edit_text(
            f"🧭 <b>UPSC TRENDING RADAR ({today})</b>\n\n{clean_text}\n\n"
            f"💡 <i>विस्तृत नोट्स पाने हेतु लिखें: <code>/generate &lt;विषय&gt;</code></i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ त्रुटि: {e}")

# /quiz: दो-चरणीय क्विज़ विज़ार्ड
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    keyboard = [
        [InlineKeyboardButton("🏛 राजव्यवस्था (Polity)", callback_data="qsubj_polity"), InlineKeyboardButton("💰 अर्थव्यवस्था (Economy)", callback_data="qsubj_economy")],
        [InlineKeyboardButton("🌿 पर्यावरण (Environment)", callback_data="qsubj_env"), InlineKeyboardButton("🔬 विज्ञान एवं टेक (Sci & Tech)", callback_data="qsubj_scitech")],
        [InlineKeyboardButton("🧭 इतिहास एवं भूगोल", callback_data="qsubj_histgeo"), InlineKeyboardButton("⚡ केवल आज के करंट अफेयर्स", callback_data="qsubj_todayca")]
    ]
    await update.message.reply_text("🎯 <b>चरण 1/2:</b> किस विषय का टेस्ट लगाना चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

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
    await update.message.reply_text("🗓️️ <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# डायनामिक बटन क्लिक और जेनरेशन
async def handle_dynamic_generation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    try:
        await query.message.delete()
    except Exception:
        pass

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
            text=f"📝 <b>UPSC MOCK TEST BUILDER:</b> {subj} के {count} प्रश्नों का संकलन हो रहा है...",
            parse_mode=ParseMode.HTML
        )

        prompt = f"""
विषय: "{subj}" पर UPSC Prelims स्तर के {count} प्रश्न JSON फॉर्मेट में तैयार करें:
###QUIZ_JSON_START###
[
  {{"question": "प्रश्न...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "a", "explain": "..."}}
]
###QUIZ_JSON_END###
भाषा शुद्ध हिंदी रखें।
"""
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            quiz_list = []
            if "###QUIZ_JSON_START###" in ai_text and "###QUIZ_JSON_END###" in ai_text:
                json_part = ai_text.split("###QUIZ_JSON_START###")[1].split("###QUIZ_JSON_END###")[0].strip()
                quiz_list = json.loads(json_part)

            topic = f"UPSC Mock Test — {subj} ({count} प्रश्न)"
            filename = f"UPSC_Test_{subj_code}_{count}Q.html"
            html_content = build_standalone_master_html(topic, f"<div class='news-card'><h3 class='section-title'>{topic}</h3><p class='para'>इस विषय के विस्तृत मॉक टेस्ट को नीचे दिए गए टेस्ट इंजन से हल करें।</p></div>", quiz_list)

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

    if data.startswith("gendate_"):
        target_date = data.split("_")[1]
        asyncio.create_task(generate_and_send_notes(user_id, f"दैनिक समसामयिक महा-संकलन — {target_date}", target_date, context))

# मुख्य अध्ययन सामग्री व टेस्ट जेनरेशन इंजन (स्मार्ट विषय निर्धारण सहित)
async def generate_and_send_notes(user_id, query_topic, date_str, context):
    wait_m = await context.bot.send_message(
        chat_id=user_id, 
        text=(
            f"╔════════════════════════╗\n"
            f"   🏛 <b>UPSC STUDY DESK</b>\n"
            f"╚════════════════════════╝\n\n"
            f"📅 <b>दिनांक/विषय:</b> <code>{query_topic}</code>\n"
            f"🔄 <b>प्रगति:</b> The Hindu, PIB, Vision, Sanskriti व Drishti IAS समन्वय चालू..."
        ), 
        parse_mode=ParseMode.HTML
    )

    prompt = f"""
आप UPSC CSE परीक्षा विशेषज्ञ हैं।
विषय: "{query_topic}"
तारीख: "{date_str}"

निर्देश:
1. **सटीक विषय वर्गीकरण (Do Not Force All GS Papers):**
   - यदि इनपुट किसी विशिष्ट विषय (जैसे केवल 'स्थान', 'पर्यावरण' या 'अर्थव्यवस्था') से संबंधित है, तो उसे जबरन सभी GS पेपर्स में न बाँटें। केवल उसी GS पेपर के तहत विश्लेषण करें जिससे वह वास्तव में संबंधित है।
   - यदि इनपुट 'दैनिक करेंट अफेयर्स' है, तो उस दिन के वास्तविक महत्वपूर्ण मुद्दों को उनके वास्तविक GS पेपर (GS 1-4) में रखें।
2. प्रत्येक विषय के तहत:
   - <section class="news-card">
   - स्रोत बैज (<span class="badge-src">📰 The Hindu, PIB, Vision IAS...</span>)
   - संवैधानिक / वैधानिक प्रावधान (<span class="badge-art">अनुच्छेद...</span>)
   - 2-कॉलम मुख्य विश्लेषणात्मक सारणी (<div class="table-box"><table><thead><tr><th>आयाम</th><th>विवरण</th></tr></thead><tbody><tr><td>...</td><td>...</td></tr></tbody></table></div>)
   - 📌 Prelims Facts & Mapping (नदियाँ, सीमावर्ती देश, सूचकांक)
   - 📝 Mains Framework: प्रश्न + भूमिका + 3 मुख्य विश्लेषणात्मक बिंदु + आगे की राह (Way Forward) + संतुलित निष्कर्ष।
   - </section>
3. अंत में, विशेष रूप से इसी पढ़े गए विषय पर आधारित 4 MCQs को JSON फॉर्मेट में दें:
###QUIZ_JSON_START###
[
  {{"question": "प्रश्न 1...", "a": "विकल्प...", "b": "विकल्प...", "c": "विकल्प...", "d": "विकल्प...", "ans": "b", "explain": "व्याख्या..."}},
  {{"question": "प्रश्न 2...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "a", "explain": "..."}},
  {{"question": "प्रश्न 3...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "c", "explain": "..."}},
  {{"question": "प्रश्न 4...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "d", "explain": "..."}}
]
###QUIZ_JSON_END###
भाषा शुद्ध हिंदी रखें।
"""
    try:
        ai_resp = await asyncio.to_thread(call_gemini_safely, prompt)
        
        quiz_list = []
        html_body = ai_resp
        if "###QUIZ_JSON_START###" in ai_resp and "###QUIZ_JSON_END###" in ai_resp:
            parts = ai_resp.split("###QUIZ_JSON_START###")
            html_body = parts[0]
            json_part = parts[1].split("###QUIZ_JSON_END###")[0].strip()
            try:
                quiz_list = json.loads(json_part)
            except Exception:
                pass

        html_content = build_standalone_master_html(query_topic, html_body, quiz_list)

        clean_slug = re.sub(r'[^a-zA-Z0-9]', '_', query_topic)[:15].strip('_')
        if not clean_slug:
            clean_slug = "UPSC_Notes"
        filename = f"{clean_slug}_{get_ist_now().strftime('%Y%m%d_%H%M')}.html"

        save_to_archive("daily", query_topic, filename, html_content, date_str=date_str)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        caption_text = (
            f"🏛️ <b>UPSC विशेष अध्ययन सामग्री</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>विषय:</b> <code>{query_topic}</code>\n"
            f"📅 <b>दिनांक:</b> <code>{date_str}</code>\n"
            f"🎯 <b>शामिल:</b> प्रीलिम्स फैक्ट्स, मेन्स फ्रेमवर्क, केस लॉ एवं लाइव टेस्ट\n"
            f"✍️ <b>संकलनकर्ता:</b> {AUTHOR_NAME}\n"
            f"📢 <b>चैनल:</b> {CHANNEL_NAME}"
        )

        with open(filename, "rb") as send_doc:
            await context.bot.send_document(
                chat_id=user_id,
                document=send_doc,
                filename=filename,
                caption=caption_text,
                parse_mode=ParseMode.HTML
            )
        await wait_m.delete()
        if os.path.exists(filename):
            os.remove(filename)

    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

# /generate कमांड
async def ai_generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"⛔ <b>अनुमति नहीं है:</b> यह सुविधा केवल अधिकृत सदस्यों के लिए है। एक्सेस हेतु <code>/owner</code> पर संपर्क करें।",
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/generate अयोध्या राम मंदिर वास्तुकला</code>", parse_mode=ParseMode.HTML)
        return

    query = " ".join(context.args).strip()
    today_str = get_ist_now().strftime("%Y-%m-%d")
    await generate_and_send_notes(user_id, query, today_str, context)

# ================= DIRECT PDF TO HTML ENGINE (20 MB GUARD) =================
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
        await msg.reply_text(f"⚠️ फ़ाइल का आकार बहुत बड़ा है ({size_mb:.1f} MB)! केवल 20 MB तक की PDF समर्थित है।", parse_mode=ParseMode.HTML)
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
नीचे दी गई PDF सामग्री का UPSC स्तर पर संपूर्ण और व्यवस्थित 360° अध्ययन नोट्स तैयार करें:
शीर्षक: "{clean_title}"
सामग्री: "{pdf_text[:4000]}"
संरचना: संदर्भ, संवैधानिक प्रावधान, 2-कॉलम HTML सारणी, मुख्य चुनौतियाँ, आगे की राह, Prelims Facts, Mains Framework।
अंत में 4 MCQs JSON फॉर्मेट में दें:
###QUIZ_JSON_START###
[{{"question": "...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "a", "explain": "..."}}]
###QUIZ_JSON_END###
भाषा शुद्ध हिंदी रखें।
"""
        ai_resp = await asyncio.to_thread(call_gemini_safely, prompt)
        quiz_list = []
        html_body = ai_resp
        if "###QUIZ_JSON_START###" in ai_resp and "###QUIZ_JSON_END###" in ai_resp:
            parts = ai_resp.split("###QUIZ_JSON_START###")
            html_body = parts[0]
            json_part = parts[1].split("###QUIZ_JSON_END###")[0].strip()
            try:
                quiz_list = json.loads(json_part)
            except Exception:
                pass

        html_out = build_standalone_master_html(clean_title, html_body, quiz_list)
        out_fname = f"UPSC_{re.sub(r'[^a-zA-Z0-9]', '_', clean_title)[:15]}.html"
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

# ================= TOPPER DOUBT SOLVER (/ask) =================
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
        await update.message.reply_text("💡 उपयोग: <code>/ask 73वां संविधान संशोधन और चुनौतियाँ</code>", parse_mode=ParseMode.HTML)
        return

    user_query = " ".join(context.args).strip()
    wait_msg = await update.message.reply_text("🤔 UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")

    try:
        prompt = f"""
आप UPSC CSE में शीर्ष रैंक प्राप्त अनुभवी मेंटर हैं।
विषय: "{user_query}"
विश्लेषण बिंदुवार और संतुलित दें (प्रमुख प्रावधान, चुनौतियाँ, सरकारी समिति, भूमिका, मुख्य भाग और निष्कर्ष)।
मार्कडाउन स्टार्स का अनावश्यक प्रयोग न करें। भाषा शुद्ध हिंदी रखें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = clean_stars_and_markdown(reply_text)

        if len(clean_reply) > 3800:
            parts = [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]
            await wait_msg.delete()
            for p in parts:
                await update.message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await wait_msg.edit_text(clean_reply, parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ त्रुटि: {e}")

# ================= ADMIN USER MANAGEMENT =================
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
        save_users_to_json_backup()
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
        save_users_to_json_backup()
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
        user_link = f'<a href="tg://user?id={uid}">{fn}</a>'
        un_str = f"@{un}" if un else "कोई यूज़रनेम नहीं"
        text += f"• <b>{user_link}</b> (<code>{uid}</code>) | {un_str}\n  वैधता: <code>{exp}</code>\n\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ================= CONTACT / OWNER FEEDBACK =================
async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    CONTACT_SESSIONS[user.id] = time.time()
    await update.message.reply_text("⏱ अपनी समस्या या सवाल लिखकर भेजें। यह सीधे सचिन शर्मा के पास पहुँचा दिया जाएगा।\n(रद्द करने हेतु <code>/cancel</code> भेजें)", parse_mode=ParseMode.HTML)
    return WAITING_CONTACT_MSG

async def forward_contact_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if time.time() - CONTACT_SESSIONS.get(user.id, 0) > 120:
        CONTACT_SESSIONS.pop(user.id, None)
        await update.message.reply_text("⚠️ समय समाप्त! पुनः प्रयास हेतु <code>/owner</code> भेजें।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    content_text = update.message.text or update.message.caption or "[फ़ाइल/मीडिया]"
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    owner_alert = (
        "📩 <b>नया छात्र संदेश!</b>\n\n"
        f"👤 <b>नाम:</b> {user_link}\n"
        f"🆔 <b>यूज़र ID:</b> <code>{user.id}</code>\n\n"
        f"💬 <b>संदेश:</b>\n{content_text}\n\n"
        "👉 <i>(उत्तर देने हेतु इस मैसेज पर <b>Reply</b> करें)</i>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=owner_alert, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    await update.message.reply_text("✅ आपका संदेश ओनर को भेज दिया गया है!")
    CONTACT_SESSIONS.pop(user.id, None)
    return ConversationHandler.END

async def handle_admin_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message or update.effective_user.id not in ADMIN_IDS:
        return
    reply_to_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
    match = re.search(r"यूज़र ID:\s*(\d+)", reply_to_text) or re.search(r"<code>(\d+)</code>", reply_to_text)
    if match:
        target_uid = int(match.group(1))
        user_notification = f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n{msg.text or ''}\n\n📢 {CHANNEL_NAME}"
        try:
            await context.bot.send_message(chat_id=target_uid, text=user_notification, parse_mode=ParseMode.HTML)
            await msg.reply_text("✅ जवाब छात्र को भेज दिया गया!")
        except Exception as e:
            await msg.reply_text(f"❌ त्रुटि: {e}")

# ================= BROADCAST SYSTEM =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in ADMIN_IDS:
        return ConversationHandler.END
    all_users = get_all_users()
    await update.message.reply_text(f"📢 <b>सार्वजनिक ब्रॉडकास्ट प्रणाली:</b>\n\nकुल पंजीकृत छात्र: <b>{len(all_users)}</b>\n\nसंदेश लिखें (या <code>/cancel</code>):", parse_mode=ParseMode.HTML)
    return WAITING_BROADCAST_MSG

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in ADMIN_IDS:
        return ConversationHandler.END
    b_msg = update.message
    all_users = get_all_users()
    status_msg = await update.message.reply_text(f"⏳ ब्रॉडकास्ट जारी है... (कुल: {len(all_users)})")
    success_count = 0
    fail_count = 0

    for uid in all_users:
        try:
            if b_msg.text:
                await context.bot.send_message(chat_id=uid, text=f"📢 <b>UPSC सूचना:</b>\n\n{b_msg.text}", parse_mode=ParseMode.HTML)
            else:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.effective_user.id, message_id=b_msg.message_id)
            success_count += 1
            await asyncio.sleep(0.04)
        except Exception:
            fail_count += 1

    await status_msg.edit_text(f"✅ सफल: {success_count} छात्र | ❌ असफल: {fail_count}", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    CONTACT_SESSIONS.pop(update.effective_user.id, None)
    await update.message.reply_text("प्रक्रिया रद्द कर दी गई।")
    return ConversationHandler.END

# ================= KEEP-ALIVE SERVER =================
async def run_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="UPSC Smart Bot Running 24/7 with 3.8-Flash Engine"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ================= MAIN =================
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
    bot_app.add_handler(MessageHandler(filters.Document.PDF, handle_direct_pdf_upload))

    contact_conv = ConversationHandler(
        entry_points=[CommandHandler("owner", contact_cmd), CommandHandler("contact", contact_cmd)],
        states={WAITING_CONTACT_MSG: [MessageHandler(filters.TEXT & (~filters.COMMAND), forward_contact_msg)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(contact_conv)

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
