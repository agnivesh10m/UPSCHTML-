import os
import re
import time
import asyncio
import base64
import sqlite3
from datetime import datetime
from aiohttp import web
from bs4 import BeautifulSoup
import google.generativeai as genai
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
ADMIN_IDS = [1745425595, 7850454902]
CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "सचिन शर्मा"

# AI Configuration
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE":
    genai.configure(api_key=GEMINI_API_KEY)

WAITING_FOR_NAME = 1
WAITING_CONTACT_MSG = 2
WAITING_BROADCAST_MSG = 3

USER_BUFFERS = {}
CONTACT_SESSIONS = {}

DB_PATH = "upsc_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
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

def save_to_archive(period, topic, filename, html_content):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%B %Y")
        year_str = now.strftime("%Y")
        c.execute("""
            INSERT INTO archive (period, date_str, month_str, year_str, topic, filename, html_content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (period, today_str, month_str, year_str, topic, filename, html_content))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error archiving: {e}")

def get_archive_list(period, limit=8):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if period == "daily":
            c.execute("""
                SELECT id, date_str, topic FROM archive 
                WHERE period = 'daily' ORDER BY id DESC LIMIT ?
            """, (limit,))
        elif period == "monthly":
            c.execute("""
                SELECT id, month_str, topic FROM archive 
                WHERE period = 'monthly' OR period = 'daily' 
                GROUP BY month_str ORDER BY id DESC LIMIT ?
            """, (limit,))
        elif period == "yearly":
            c.execute("""
                SELECT id, year_str, topic FROM archive 
                GROUP BY year_str ORDER BY id DESC LIMIT ?
            """, (limit,))
        elif period == "weekly":
            c.execute("""
                SELECT id, date_str, topic FROM archive 
                WHERE period = 'weekly' OR period = 'daily' ORDER BY id DESC LIMIT ?
            """, (limit,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Error fetching archive list: {e}")
        return []

def get_archive_by_id(archive_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT topic, filename, html_content FROM archive WHERE id = ?
        """, (archive_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        print(f"Error fetching archive by id: {e}")
        return None

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ================= HTML BUILDER & SANITIZER =================
def sanitize_and_rebrand_html(soup: BeautifulSoup, custom_title: str = None) -> None:
    for a in soup.find_all('a'):
        href = a.get('href', '')
        if 't.me' in href or 'cserunners' in href.lower():
            a['href'] = CHANNEL_LINK
        if a.string and re.search(r'cse\s*runners', a.string, re.IGNORECASE):
            a.string = f"{AUTHOR_NAME} ({CHANNEL_NAME})"
            
    tg_btn = soup.find('button', id='telegramBtn')
    if tg_btn:
        tg_btn['onclick'] = f"window.open('{CHANNEL_LINK}','_blank')"
        span = tg_btn.find('span')
        if span:
            span.string = f"TELEGRAM — {CHANNEL_NAME}"
        else:
            tg_btn.string = f"📲 TELEGRAM — {CHANNEL_NAME}"
            
    footer = soup.find('footer')
    if footer:
        for fl in footer.find_all('a'):
            fl['href'] = CHANNEL_LINK
            if 'cserunners' in fl.text.lower() or 'telegram' in fl.text.lower():
                fl.string = f"{AUTHOR_NAME} | {CHANNEL_NAME}"

    for text_node in soup.find_all(text=True):
        if text_node.parent.name in ['script', 'style']:
            continue
        if re.search(r'cse\s*runners', text_node, re.IGNORECASE):
            new_text = re.sub(r'cse\s*runners', f"{AUTHOR_NAME} ({CHANNEL_NAME})", text_node, flags=re.IGNORECASE)
            text_node.replace_with(new_text)

    if custom_title:
        title_tag = soup.find('title')
        if title_tag:
            title_tag.string = f"{custom_title} | {AUTHOR_NAME}"
        h1_tag = soup.find('h1')
        if h1_tag:
            h1_tag.string = f"🇮🇳 {custom_title}"

def build_interactive_dashboard_html(topic: str, raw_text: str, image_list: list = None) -> str:
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    sections = []
    current_sec_title = "भूमिका एवं सामान्य अवलोकन"
    current_sec_lines = []

    for line in lines:
        is_heading = (
            re.match(r'^[0-9]+\.\s*', line) 
            or any(line.startswith(x) for x in ["📌", "🎯", "⚡", "📖", "💡", "🗳️", "⚖️", "🔍", "📝", "🛣️", "❄️", "🌏", "📰", "🌍", "🌱", "🔬", "💰", "🔑", "🔸"])
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
        clean_nav_name = re.sub(r'[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍🔑|━─—_:-🔸]', '', clean_nav_name).strip()
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

            # 2-कॉलम टेबल पहचानना (जैसे: "चरण" और अगली पंक्ति "AI का उपयोग")
            is_table_header = (
                (line in ["चरण", "विषय", "क्षेत्र", "तकनीक", "प्रावधान", "Article", "घटक", "आयाम", "क्रम"]) 
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
                        or any(c1.startswith(x) for x in ["📌", "🎯", "⚡", "📖", "💡", "📝", "🔑"])
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

# ================= AI GENERATOR COMMAND (/generate) =================
async def ai_generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह AI जनरेशन फीचर केवल एडमिन के लिए है।")
        return

    if not context.args:
        await update.message.reply_text(
            "💡 <b>उपयोग का तरीका:</b>\n"
            "<code>/generate [तारीख या विषय]</code>\n\n"
            "<b>उदाहरण:</b>\n"
            "• <code>/generate 29 September 2026 Daily Current Affairs</code>\n"
            "• <code>/generate AI in Disaster Management</code>\n"
            "• <code>/generate September 2026 Monthly Compilation</code>",
            parse_mode=ParseMode.HTML
        )
        return

    query = " ".join(context.args).strip()
    status_msg = await update.message.reply_text(
        f"🤖 <b>AI रिसर्च जारी है...</b>\n\n"
        f"विषय: <code>{query}</code>\n"
        "The Hindu, PIB, और UPSC सिलेबस के अनुसार नोट्स व सारणी तैयार की जा रही है...",
        parse_mode=ParseMode.HTML
    )

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
आप UPSC CSE परीक्षा के मुख्य कंटेंट विश्लेषक और मेंटर हैं।
निम्नलिखित विषय पर बिल्कुल 'Zero to Hero' स्तर के गहन, परीक्षा-केंद्रित और समृद्ध नोट्स तैयार करें:
विषय: "{query}"

सख्त संरचना नियम:
1. पहली लाइन में स्पष्ट शीर्षक दें।
2. GS पेपर का उल्लेख करें (उदा: GS-II: Polity / GS-III: Economy आदि)।
3. मुख्य हेडिंग्स को क्रम से रखें:
   - 1. संदर्भ / चर्चा में क्यों
   - 2. संवैधानिक / वैधानिक स्थिति (संबद्ध अनुच्छेद, कानून व केस लॉ)
   - 3. मुख्य विश्लेषण (जहाँ भी चरण, वर्गीकरण या पक्ष-विपक्ष हो, अनिवार्य रूप से 2-कॉलम टेबल प्रारूप में लिखें: पहली पंक्ति हेडर जैसे 'चरण' और 'विवरण' या 'घटक' और 'भूमिका')
   - 4. प्रमुख तकनीकें / चुनौतियाँ (बुलेट पॉइंट्स में, मुख्य शब्दों के आगे कोलन : लगाएं)
   - 5. आगे की राह (Way Forward)
   - 6. 📌 Prelims Facts & Key Concepts (फ्लो दिखाने के लिए → का प्रयोग करें)
   - 7. 📝 Mains Question & Answer Framework (भूमिका, मुख्य भाग के 3 बिंदु, संतुलित निष्कर्ष)
4. भाषा हिंदी (आवश्यक तकनीकी शब्द कोष्ठक में अंग्रेजी) में रखें।
5. कोई मार्कडाउन पाइप (|) न बनाएं, सीधे हेडर के नीचे मान लिखें जैसे:
चरण
AI का उपयोग
Preparedness
बाढ़ की पूर्व चेतावनी
Risk Assessment
सैटेलाइट मैपिंग
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        ai_text = response.text

        clean_topic = query[:40]
        html_output = build_interactive_dashboard_html(clean_topic, ai_text)

        period = "daily"
        if "month" in query.lower() or "माह" in query or "मासिक" in query:
            period = "monthly"
        elif "week" in query.lower() or "सप्ताह" in query:
            period = "weekly"
        elif "year" in query.lower() or "वार्षिक" in query:
            period = "yearly"

        filename = f"{re.sub(r'[^a-zA-Z0-9\u0900-\u097F]', '_', clean_topic)[:25]}.html"
        save_to_archive(period, clean_topic, filename, html_output)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_output)

        with open(filename, "rb") as send_doc:
            await update.message.reply_document(
                document=send_doc,
                filename=filename,
                caption=(
                    f"✨ <b>AI द्वारा स्वतः तैयार यूपीएससी नोट्स!</b>\n"
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

# ================= PUBLIC MENU & INLINE BUTTONS =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    is_admin = user.id in ADMIN_IDS

    if is_admin:
        msg = (
            f"👋 <b>नमस्ते एडमिन {AUTHOR_NAME}!</b>\n\n"
            "👑 <b>एडमिन कंट्रोल सक्रिय है:</b>\n"
            "• <code>/generate [विषय/तारीख]</code> — AI से स्वतः सम्पूर्ण HTML नोट्स तैयार कराएं\n"
            "• <code>/html</code> — मैन्युअल फॉरवर्डेड नोट्स संकलन शुरू करें\n"
            "• <code>/sachin</code> — HTML फ़ाइल तैयार करें\n"
            "• <code>/broadcast</code> — सभी को मैसेज भेजें\n\n"
            "📚 <b>छात्रों के लिए आर्काइव कमांड्स:</b>\n"
            "• <code>/daily</code> — तारीख चुनकर नोट्स डाउनलोड करें\n"
            "• <code>/weekly</code> — सप्ताह चुनकर नोट्स देखें\n"
            "• <code>/monthly</code> — महीना चुनकर पत्रिका देखें\n"
            "• <code>/yearly</code> — साल चुनकर नोट्स देखें\n"
            "• <code>/owner</code> — छात्रों के सीधे संदेश प्राप्त करें"
        )
    else:
        msg = (
            f"👋 <b>नमस्ते {user.first_name}!</b>\n\n"
            f"📚 <b>UPSC HTML Notes Portal में आपका स्वागत है!</b>\n\n"
            "दैनिक, साप्ताहिक और मासिक नोट्स के लिए नीचे दिए कमांड चलाएं:\n\n"
            "📅 <b>दैनिक नोट्स:</b> <code>/daily</code>\n"
            "🗓️ <b>साप्ताहिक नोट्स:</b> <code>/weekly</code>\n"
            "📁 <b>मासिक पत्रिका:</b> <code>/monthly</code>\n"
            "🏛️ <b>वार्षिक कंपाइलेशन:</b> <code>/yearly</code>\n\n"
            f"👤 <b>निर्माता:</b> {AUTHOR_NAME}\n"
            f"📢 <b>ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    help_text = (
        "📖 <b>UPSC HTML BOT — सहायता केंद्र</b>\n\n"
        "1️⃣ <b>पुरानी तारीख के नोट्स कैसे देखें?</b>\n"
        "• <code>/daily</code> दबाएं — आपको पिछली तारीखों के बटन मिलेंगे। मनपसंद तारीख पर क्लिक करते ही उस दिन की HTML फ़ाइल मिल जाएगी।\n\n"
        "2️⃣ <b>मासिक या वार्षिक नोट्स:</b>\n"
        "• <code>/monthly</code> — महीनों के नाम के बटन दिखेंगे।\n"
        "• <code>/yearly</code> — वर्षों के बटन दिखेंगे।\n\n"
        "3️⃣ <b>सीधे एडमिन से संपर्क:</b>\n"
        "• <code>/owner</code> दबाएं और 2 मिनट में अपनी बात लिखें।\n\n"
        f"📢 <b>ऑफिशियल ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    rows = get_archive_list("daily", limit=6)

    if not rows:
        await update.message.reply_text("ℹ️ अभी कोई दैनिक नोट्स उपलब्ध नहीं हैं।")
        return

    keyboard = []
    for arch_id, d_str, topic in rows:
        btn_text = f"📅 {d_str} — {topic[:22]}.."
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📅 <b>जिस तारीख के नोट्स चाहिए, उस बटन पर क्लिक करें:</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def monthly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    rows = get_archive_list("monthly", limit=6)

    if not rows:
        await update.message.reply_text("ℹ️ अभी कोई मासिक नोट्स उपलब्ध नहीं हैं।")
        return

    keyboard = []
    for arch_id, m_str, topic in rows:
        btn_text = f"📁 {m_str} पत्रिका"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📁 <b>जिस महीने के नोट्स चाहिए, उस पर क्लिक करें:</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    rows = get_archive_list("yearly", limit=5)

    if not rows:
        await update.message.reply_text("ℹ️ अभी कोई वार्षिक नोट्स उपलब्ध नहीं हैं।")
        return

    keyboard = []
    for arch_id, y_str, topic in rows:
        btn_text = f"📚 वर्ष {y_str} वार्षिक संकलन"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🏛️ <b>जिस वर्ष का कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    rows = get_archive_list("weekly", limit=6)

    if not rows:
        await update.message.reply_text("ℹ️ अभी कोई साप्ताहिक नोट्स उपलब्ध नहीं हैं।")
        return

    keyboard = []
    for arch_id, w_str, topic in rows:
        btn_text = f"🗓️ {w_str} का सप्ताह"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🗓️ <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def archive_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    arch_id = int(query.data.split("_")[1])
    data = get_archive_by_id(arch_id)

    try:
        await query.message.delete()
    except Exception:
        pass

    if not data:
        await context.bot.send_message(chat_id=query.from_user.id, text="❌ यह फ़ाइल उपलब्ध नहीं है।")
        return

    topic, filename, html_content = data
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open(filename, "rb") as send_doc:
        await context.bot.send_document(
            chat_id=query.from_user.id,
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
        await update.message.reply_text(
            "⚠️ <b>समय समाप्त!</b> 2 मिनट पूरे हो चुके हैं। पुनः प्रयास के लिए <code>/owner</code> भेजें।",
            parse_mode=ParseMode.HTML
        )
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

    await update.message.reply_text(
        "✅ <b>आपका संदेश ओनर को भेज दिया गया है!</b> जैसे ही वे देखेंगे, आपको यहीं उत्तर मिल जाएगा।",
        parse_mode=ParseMode.HTML
    )
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
            await context.bot.send_message(
                chat_id=target_user_id,
                text=user_notification,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
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
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"📢 <b>UPSC HTML सूचना:</b>\n\n{b_msg.text}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
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

# ================= ADMIN-ONLY MANUAL HTML GENERATION =================
async def start_html_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल एडमिन के लिए है।")
        return

    USER_BUFFERS[user_id] = {
        "active": True,
        "texts": [],
        "images": [],
        "html_soups": [],
        "suggested_topic": "UPSC_Notes",
    }
    await update.message.reply_text(
        "🟢 <b>एडमिन सत्र चालू!</b> सामग्री फॉरवर्ड करें, फिर <code>/sachin</code> भेजें।",
        parse_mode=ParseMode.HTML
    )

async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
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

    elif msg.document and (msg.document.file_name.endswith(".html") or msg.document.file_name.endswith(".htm")):
        doc_f = await msg.document.get_file()
        t_doc = f"doc_{msg.document.file_name}"
        await doc_f.download_to_drive(t_doc)
        with open(t_doc, "r", encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            session["html_soups"].append(soup)

            title_node = soup.find('title')
            h1_node = soup.find('h1')
            if title_node and title_node.text.strip():
                clean_t = re.sub(r'(\||-|—).*$', '', title_node.text).strip()
                session["suggested_topic"] = clean_t[:45]
            elif h1_node and h1_node.text.strip():
                clean_t = re.sub(r'(\||-|—).*$', '', h1_node.text).strip()
                session["suggested_topic"] = clean_t[:45]
            else:
                session["suggested_topic"] = doc_f.file_name.replace(".html", "").replace(".htm", "")

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
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल एडमिन के लिए है।")
        return ConversationHandler.END

    session = USER_BUFFERS.get(user_id)
    if not session or (not session.get("texts") and not session.get("html_soups")):
        await update.message.reply_text("❌ कोई सामग्री नहीं मिली। पहले <code>/html</code> भेजें।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    suggested = session.get("suggested_topic", "UPSC_Notes")

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

    wait_msg = await update.message.reply_text("⏳ आपकी रंगीन व इंटरैक्टिव HTML फ़ाइल तैयार हो रही है...")

    final_output_html = ""
    if session["html_soups"]:
        main_soup = session["html_soups"][0]
        sanitize_and_rebrand_html(main_soup, custom_title=final_topic)
        final_output_html = str(main_soup)
    else:
        combined_text = "\n\n".join(session["texts"])
        final_output_html = build_interactive_dashboard_html(final_topic, combined_text, session["images"])

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
    app.router.add_get("/", lambda r: web.Response(text="Bot Active 24/7 with Integrated AI Engine"))
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

    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CommandHandler("help", help_handler))
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    bot_app.add_handler(CallbackQueryHandler(archive_button_click, pattern=r"^arch_\d+$"))

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
