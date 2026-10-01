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

# ================= PERSISTENT DATABASE & RECOVERY =================
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

    # स्थायी JSON बैकअप से पुराने यूज़र्स को पुनः लोड करें (डिप्लॉयमेंट रिसेट से सुरक्षा)
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
            print(f"Error restoring users from JSON backup: {e}")
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
        print(f"Error saving to JSON backup: {e}")

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
    generation_config = {
        "temperature": 0.35,
        "max_output_tokens": 8192,
    }

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ]

    for m_name in models_to_try:
        try:
            model = genai.GenerativeModel(m_name, generation_config=generation_config)
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text
        except Exception:
            continue

    raise Exception("AI सर्वर से उत्तर प्राप्त करने में असमर्थ।")

def clean_stars_and_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'(\*{2,}|_{2,})', '', text)
    return text.strip()

# ================= DYNAMIC QUIZ & FULL HTML BUILDER =================
def build_dynamic_dashboard_html(topic: str, raw_content: str, quiz_questions: list) -> str:
    clean_html = raw_content.strip()
    if clean_html.startswith("```html"):
        clean_html = clean_html[7:]
    elif clean_html.startswith("```"):
        clean_html = clean_html[3:]
    if clean_html.endswith("```"):
        clean_html = clean_html[:-3]
    clean_html = clean_html.strip()

    # डायनामिक क्विज़ जावास्क्रिप्ट और फॉर्म बनाना
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
    <input type="text" id="searchBox" placeholder="🔍 खोजें: GS पेपर, संवैधानिक प्रावधान, कीवर्ड...">
    <button onclick="toggleTheme()" class="theme-btn">🌗 डार्क / लाइट</button>
    <button onclick="window.print()" class="print-btn">🖨️ प्रिंट / सेव PDF</button>
  </div>
</header>

<main class="wrap" id="mainContent">
  {clean_html}
  
  <section id="sec-quiz" class="quiz-engine-card">
    <h3 class="section-title" style="color:var(--accent); border-left-color:var(--saffron);">🎯 विषय आधारित लाइव इंटरएक्टिव टेस्ट</h3>
    <p class="para">उपर्युक्त नोट्स पर आधारित वास्तविक टेस्ट। प्रत्येक सही उत्तर पर +2.0 अंक, गलत उत्तर पर -0.66 अंक।</p>
    
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
  <div style="margin-top:8px;">संकलन एवं प्रस्तुति: <b>{AUTHOR_NAME}</b> | टेलीग्राम ग्रुप: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
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

# ================= PUBLIC MENU =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    is_admin = user.id in ADMIN_IDS

    # यूज़र की आईडी पर क्लिक करने योग्य लिंक
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    admin_badge = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if is_admin else "📚 <b>UPSC CSE स्मार्ट अध्ययन पोर्टल</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user_link}!</b>\n\n"
        f"{admin_badge}"
        "नीचे सभी मुख्य कमांड्स उपलब्ध हैं:\n\n"
        "📖 <b>अध्ययन एवं नोट्स:</b>\n"
        "• <code>/daily</code> — दैनिक नोट्स (IST लाइव कैलेंडर)\n"
        "• <code>/trending</code> — चर्चा में चल रहे स्थान व मुद्दे (ID 1, 2, 3...)\n"
        "• <code>/generate &lt;विषय या तारीख&gt;</code> — सटीक UPSC 360° नोट्स\n\n"
        "🛠 <b>एडमिन व ब्रॉडकास्ट:</b>\n"
        "• <code>/broadcast</code> — सभी पंजीकृत छात्रों को संदेश भेजें\n"
        "• <code>/listusers</code> — पंजीकृत छात्र देखें\n\n"
        "💬 <b>संपर्क:</b> <code>/owner</code> (सचिन शर्मा से सीधे बात करें)\n"
        f"📢 <b>चैनल:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# /trending: आईडी आधारित सूची
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now().strftime("%Y-%m-%d")
    wait_msg = await update.message.reply_text("🛰 <b>UPSC रडार:</b> समसामयिक स्थानों व मुद्दों का संकलन हो रहा है...", parse_mode=ParseMode.HTML)

    prompt = f"""
आज की तारीख {today} के संदर्भ में UPSC CSE हेतु सबसे महत्वपूर्ण 5 स्थानों और समसामयिक मुद्दों की क्रमांकित सूची दें:
प्रारूप:
[ID 1] मुद्दे/स्थान का नाम — संबंधित GS पेपर (जैसे GS-1 या GS-2) व संक्षिप्त 2 पंक्ति कारण
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
            f"💡 <i>किसी भी विषय पर नोट्स पाने हेतु लिखें: <code>/generate &lt;विषय का नाम&gt;</code></i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ त्रुटि: {e}")

# /daily: IST कैलेंडर
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    today = get_ist_now()
    keyboard = []
    
    for i in range(-4, 2):
        target_dt = today + timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        label = f"🌟 आज ({d_str})" if i == 0 else f"📅 {d_str}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 <b>जिस तारीख के दैनिक नोट्स चाहिए, उस पर क्लिक करें:</b>", reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# डायनामिक बटन और जेनरेशन
async def handle_dynamic_generation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    try:
        await query.message.delete()
    except Exception:
        pass

    if data.startswith("gendate_"):
        target_date = data.split("_")[1]
        asyncio.create_task(generate_and_send_notes(user_id, f"दैनिक करेंट अफेयर्स — {target_date}", target_date, context))

# मुख्य अध्ययन सामग्री व टेस्ट जेनरेशन इंजन (स्मार्ट वर्गीकरण + डायनामिक क्विज़)
async def generate_and_send_notes(user_id, query_topic, date_str, context):
    wait_m = await context.bot.send_message(
        chat_id=user_id,
        text=f"⏳ <b>'{query_topic}'</b> के प्रामाणिक नोट्स व लाइव टेस्ट संकलित किए जा रहे हैं...",
        parse_mode=ParseMode.HTML
    )

    prompt = f"""
आप UPSC CSE परीक्षा विशेषज्ञ हैं।
विषय: "{query_topic}"
तारीख: "{date_str}"

निर्देश:
1. **सटीक विषय वर्गीकरण (Do Not Force Unrelated GS Papers):**
   - यदि इनपुट किसी विशिष्ट विषय (जैसे केवल 'स्थान', 'पर्यावरण' या 'अर्थव्यवस्था') से संबंधित है, तो उसे जबरन सभी चारों GS पेपर्स में न खींचें। केवल उसी GS पेपर के तहत विश्लेषण करें जिससे वह वास्तव में संबंधित है।
   - यदि इनपुट 'दैनिक करेंट अफेयर्स' है, तो उस दिन के वास्तविक महत्वपूर्ण मुद्दों को उनके वास्तविक GS पेपर (GS 1-4) में रखें।
2. प्रत्येक विषय के तहत:
   - स्रोत बैज (The Hindu, PIB, Indian Express आदि)
   - संवैधानिक / वैधानिक प्रावधान (अनुच्छेद, कानून, सुप्रीम कोर्ट के वाद)
   - मुख्य विश्लेषणात्मक सारणी (<div class="table-box"><table><thead><tr><th>आयाम</th><th>विवरण</th></tr></thead><tbody><tr><td>...</td><td>...</td></tr></tbody></table></div>)
   - 📌 Prelims Facts & Mapping (नदियाँ, सीमावर्ती देश, सूचकांक)
   - 📝 Mains Framework: प्रश्न + भूमिका + 3 मुख्य विश्लेषणात्मक बिंदु + आगे की राह (Way Forward) + संतुलित निष्कर्ष।
3. अंत में, विशेष रूप से इसी पढ़े गए विषय पर आधारित 4 MCQs को JSON फॉर्मेट में दें:
###QUIZ_JSON_START###
[
  {{"question": "प्रश्न 1...", "a": "विकल्प...", "b": "विकल्प...", "c": "विकल्प...", "d": "विकल्प...", "ans": "b", "explain": "व्याख्या..."}},
  {{"question": "प्रश्न 2...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "a", "explain": "..."}},
  {{"question": "प्रश्न 3...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "c", "explain": "..."}},
  {{"question": "प्रश्न 4...", "a": "...", "b": "...", "c": "...", "d": "...", "ans": "d", "explain": "..."}}
]
###QUIZ_JSON_END###
"""
    try:
        ai_resp = await asyncio.to_thread(call_gemini_safely, prompt)
        
        # क्विज़ JSON अलग निकालना
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

        if not quiz_list:
            quiz_list = [
                {"question": f"{query_topic} से संबंधित मुख्य प्रावधान क्या है?", "a": "संविधान का भाग III", "b": "नीति निर्देशक तत्व", "c": "समवर्ती सूची", "d": "उपर्युक्त सभी", "ans": "d", "explain": "यह विषय समग्र प्रशासनिक ढांचे से जुड़ा है।"}
            ]

        html_content = build_dynamic_dashboard_html(query_topic, html_body, quiz_list)

        # साफ़ और सुरक्षित अंग्रेजी फाइल नाम (बिना किसी टूटे अक्षर के)
        clean_slug = re.sub(r'[^a-zA-Z0-9]', '_', query_topic)[:20].strip('_')
        if not clean_slug:
            clean_slug = "UPSC_Notes"
        timestamp_str = get_ist_now().strftime("%Y%m%d_%H%M")
        filename = f"{clean_slug}_{timestamp_str}.html"

        save_to_archive("daily", query_topic, filename, html_content, date_str=date_str)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        user_link = f'<a href="tg://user?id={user_id}">छात्र</a>'
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

# ================= UNIVERSAL BROADCAST (PERMANENT USERS) =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END
    all_users = get_all_users()
    await update.message.reply_text(
        f"📢 <b>सार्वजनिक ब्रॉडकास्ट प्रणाली:</b>\n\n"
        f"कुल पंजीकृत छात्र (स्थायी मेमोरी): <b>{len(all_users)}</b>\n\n"
        f"सभी को भेजा जाने वाला संदेश लिखें:\n<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>",
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
            await asyncio.sleep(0.04)
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
    app.router.add_get("/", lambda r: web.Response(text="UPSC Smart Bot Active with Persistent Storage & Dynamic Test Engine"))
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
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("trending", trending_cmd))
    bot_app.add_handler(CommandHandler("generate", ai_generate_cmd))
    bot_app.add_handler(CallbackQueryHandler(handle_dynamic_generation_click))

    # ब्रॉडकास्ट हैंडलर
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={WAITING_BROADCAST_MSG: [MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    bot_app.add_handler(broadcast_conv)

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
