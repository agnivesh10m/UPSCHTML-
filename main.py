import asyncio
import base64
import os
import re
from aiohttp import web
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "सचिन शर्मा"

USER_BUFFERS = {}
WAITING_FOR_NAME = 1


def sanitize_and_rebrand_html(
    soup: BeautifulSoup, custom_title: str = None
) -> None:
  """पुराने चैनलों के लिंक, नाम हटाना और अपनी ब्रांडिंग लगाना"""
  for a in soup.find_all("a"):
    href = a.get("href", "")
    if "t.me" in href or "cserunners" in href.lower():
      a["href"] = CHANNEL_LINK
    if a.string and re.search(r"cse\s*runners", a.string, re.IGNORECASE):
      a.string = f"{AUTHOR_NAME} ({CHANNEL_NAME})"

  tg_btn = soup.find("button", id="telegramBtn")
  if tg_btn:
    tg_btn["onclick"] = f"window.open('{CHANNEL_LINK}','_blank')"
    span = tg_btn.find("span")
    if span:
      span.string = f"TELEGRAM — {CHANNEL_NAME}"
    else:
      tg_btn.string = f"📲 TELEGRAM — {CHANNEL_NAME}"

  footer = soup.find("footer")
  if footer:
    for fl in footer.find_all("a"):
      fl["href"] = CHANNEL_LINK
      if "cserunners" in fl.text.lower() or "telegram" in fl.text.lower():
        fl.string = f"{AUTHOR_NAME} | {CHANNEL_NAME}"

  for text_node in soup.find_all(text=True):
    if text_node.parent.name in ["script", "style"]:
      continue
    if re.search(r"cse\s*runners", text_node, re.IGNORECASE):
      new_text = re.sub(
          r"cse\s*runners",
          f"{AUTHOR_NAME} ({CHANNEL_NAME})",
          text_node,
          flags=re.IGNORECASE,
      )
      text_node.replace_with(new_text)

  if custom_title:
    title_tag = soup.find("title")
    if title_tag:
      title_tag.string = f"{custom_title} | {AUTHOR_NAME}"
    h1_tag = soup.find("h1")
    if h1_tag:
      h1_tag.string = f"🇮🇳 {custom_title}"


def build_interactive_dashboard_html(
    topic: str, raw_text: str, image_list: list = None
) -> str:
  """डायनामिक नेविगेशन बार (Clickable Index Bar) के साथ HTML बनाना"""
  lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

  sections = []
  current_sec_title = "भूमिका / सामान्य परिचय"
  current_sec_lines = []

  # 1. टेक्स्ट को अलग-अलग टॉपिक्स / सेक्शन्स में पहचानना
  for line in lines:
    is_heading = (
        re.match(r"^[0-9]+\.", line)
        or any(
            line.startswith(x)
            for x in [
                "📌",
                "🎯",
                "⚡",
                "📖",
                "💡",
                "🗳️",
                "⚖️",
                "🔍",
                "📝",
                "🛣️",
                "❄️",
                "🌏",
                "📰",
                "🌍",
                "🌱",
                "🔬",
                "💰",
            ]
        )
        or (line.endswith(":") and len(line) < 60)
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

  # 2. ऊपर की स्टिकी नेविगेशन बार (Clickable Buttons) तैयार करना
  nav_links_html = ""
  content_html = ""

  for idx, (sec_title, sec_lines) in enumerate(sections, 1):
    sec_id = f"topic-{idx}"

    # बटन के लिए छोटा और साफ़ नाम
    short_name = re.sub(r"^[0-9]+\.\s*", "", sec_title)
    short_name = re.sub(
        r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍|━─—_:-]", "", short_name
    ).strip()
    if len(short_name) > 22:
      short_name = short_name[:20] + ".."
    if not short_name:
      short_name = f"भाग {idx}"

    nav_links_html += f'<a href="#{sec_id}">{short_name}</a>\n'

    # सेक्शन का अंदरूनी कंटेंट पार्स करना
    sec_body_html = ""
    in_table = False
    table_rows = []

    for line in sec_lines:
      if (
          line.startswith("|")
          and line.endswith("|")
          and len(line.split("|")) >= 3
      ):
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not in_table:
          in_table = True
          table_rows.append(
              "<tr>"
              + "".join([f"<th class='th-cell'>{c}</th>" for c in cells])
              + "</tr>"
          )
        elif "---" not in line:
          table_rows.append(
              "<tr>"
              + "".join([f"<td class='td-cell'>{c}</td>" for c in cells])
              + "</tr>"
          )
        continue
      elif in_table:
        sec_body_html += f"<div class='table-box'><table>{''.join(table_rows)}</table></div>"
        in_table = False
        table_rows = []

      if line.startswith(">"):
        sec_body_html += f"<blockquote>{line[1:].strip()}</blockquote>"
        continue

      # तीर (Flow Layout)
      if "→" in line:
        steps = [s.strip() for s in line.split("→") if s.strip()]
        if len(steps) > 1:
          step_tags = "".join(
              [f"<span class='flow-step'>{s}</span>" for s in steps]
          )
          sec_body_html += f"<div class='flow-container'>{step_tags}</div>"
          continue

      # बुलेट पॉइंट्स
      if line.startswith(("•", "-", "▪", "▫", "*", "🔸")):
        clean_bullet = re.sub(r"^[•\-▪▫\*🔸]\s*", "", line)
        sec_body_html += f"<li class='list-item'>{clean_bullet}</li>"
        continue

      # रंगीन हाइलाइट्स
      formatted = re.sub(
          r"\*\*(.*?)\*\*", r"<strong class='hl-blue'>\1</strong>", line
      )
      formatted = re.sub(
          r"(GS-[I|II|III|IV]+)", r"<span class='badge-gs'>\1</span>", formatted
      )
      formatted = re.sub(
          r"(Article\s+\d+[A-Za-z]?|अनुच्छेद\s+\d+[A-Za-z]?)",
          r"<span class='badge-art'>\1</span>",
          formatted,
          flags=re.IGNORECASE,
      )
      formatted = re.sub(
          r"(https?://[^\s]+)",
          r"<a href='\1' target='_blank' class='text-link'>\1</a>",
          formatted,
      )
      sec_body_html += f"<p class='para'>{formatted}</p>"

    if in_table:
      sec_body_html += (
          f"<div class='table-box'><table>{''.join(table_rows)}</table></div>"
      )

    # सेक्शन कार्ड
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
  --bg:#f4f6f9; --card:#ffffff; --text:#1c2430; --muted:#5b6675; --border:#e3e7ee;
  --accent:#0b5fa5; --accent2:#0a8f5b; --saffron:#ff9933; --green:#138808;
  --tag-bg:#eef3fb; --tag-text:#0b5fa5; --shadow:0 4px 15px rgba(20,30,50,.08);
}}
[data-theme="dark"] {{
  --bg:#0f1620; --card:#161f2b; --text:#e7edf5; --muted:#9aa7b8; --border:#26313f;
  --accent:#5fa8e0; --accent2:#4fce9a; --tag-bg:#1c2b3d; --tag-text:#8bc4ef;
  --shadow:0 4px 18px rgba(0,0,0,.4);
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ scroll-behavior: smooth; }}
body {{
  background:var(--bg); color:var(--text); font-family:'Hind','Noto Sans Devanagari',sans-serif;
  line-height:1.75; transition:background .3s,color .3s; padding-bottom:75px;
}}
.top-header {{
  background:linear-gradient(135deg,#0b1f3a,#0b5fa5 60%,#083a63);
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

/* स्टिकी नेविगेशन बार (Clickable Topics) */
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
  scroll-margin-top: 65px; /* हेडर के नीचे न छुपे */
}}
.section-title {{
  color:var(--accent); font-size:1.24rem; margin-bottom:14px;
  border-left:5px solid var(--saffron); padding-left:12px;
}}
.para {{ margin:8px 0; font-size:1rem; word-break:break-word; }}
.list-item {{ margin:6px 0 6px 24px; color:var(--text); font-size:0.98rem; }}
.hl-blue {{ color:#0284c7; font-weight:700; }}
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
  background:var(--tag-bg); color:var(--accent); border:1px solid var(--border);
  padding:5px 12px; border-radius:8px; font-size:0.88rem; font-weight:600;
  display:inline-flex; align-items:center;
}}
.flow-step:not(:last-child)::after {{
  content:"→"; margin-left:8px; color:var(--muted); font-weight:bold;
}}
blockquote {{
  border-left:4px solid var(--accent); background:var(--tag-bg);
  padding:12px 16px; border-radius:0 8px 8px 0; margin:15px 0; font-weight:500;
}}
.table-box {{ overflow-x:auto; margin:16px 0; width:100%; }}
table {{ width:100%; border-collapse:collapse; border-radius:8px; }}
th {{ background:var(--accent); color:#fff; padding:10px 12px; text-align:left; }}
td {{ padding:9px 12px; border:1px solid var(--border); }}
tr:nth-child(even) {{ background:rgba(128,128,128,0.05); }}
.img-container {{ text-align:center; margin:16px 0; }}
.post-img {{ max-width:100%; border-radius:10px; }}
#telegramBtn {{
  position:fixed; bottom:18px; right:18px; z-index:90;
  background:#229ED9; color:#fff; border:none; border-radius:30px;
  padding:12px 20px; font-weight:700; cursor:pointer; box-shadow:0 4px 15px rgba(0,0,0,0.25);
  font-size:0.88rem;
}}
footer {{
  background:#0b1f3a; color:#dbe6f2; text-align:center; padding:26px 16px; margin-top:35px; font-size:0.88rem;
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

<!-- ऑटोमैटिक डायनामिक नेविगेशन बार -->
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


# /start कमांड
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await update.message.reply_text(
      f"👋 **नमस्ते {AUTHOR_NAME}!**\n\n"
      "👉 **कैसे उपयोग करें:**\n"
      "1. पहले **/html** भेजें (सत्र शुरू होगा)।\n"
      "2. इसके बाद अपनी सामग्री (HTML फ़ाइल या नोट्स) फॉरवर्ड करें।\n"
      "3. फिर **/sachin** भेजें — बॉट आपसे नाम की पुष्टि पूछेगा और कॉपी करने"
      " लायक नाम भी सजेस्ट करेगा!\n"
      "4. अगर वही नाम रखना है तो सिर्फ `1` भेजें, वरना नया नाम भेजें।"
  )


# 1. /html कमांड - नया सत्र शुरू
async def start_html_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user_id = update.effective_user.id
  USER_BUFFERS[user_id] = {
      "active": True,
      "texts": [],
      "images": [],
      "html_soups": [],
      "suggested_topic": "UPSC_Notes",
  }
  await update.message.reply_text(
      "🟢 **सत्र शुरू हो गया है!**\n\n"
      "अब अपनी HTML फ़ाइल, फ़ोटो या टेक्स्ट फॉरवर्ड करें।\n"
      "जब सारा मटेरियल भेज लें, तब **/sachin** भेजें।"
  )


# 2. बीच की सामग्री इकट्ठा करना
async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  session = USER_BUFFERS.get(user_id)
  if not session or not session.get("active"):
    await update.message.reply_text(
        "💡 नए नोट्स बनाने के लिए पहले **/html** भेजें।"
    )
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

  elif msg.document and (
      msg.document.file_name.endswith(".html")
      or msg.document.file_name.endswith(".htm")
  ):
    doc_f = await msg.document.get_file()
    t_doc = f"doc_{msg.document.file_name}"
    await doc_f.download_to_drive(t_doc)
    with open(t_doc, "r", encoding="utf-8", errors="ignore") as f:
      soup = BeautifulSoup(f.read(), "html.parser")
      session["html_soups"].append(soup)

      title_node = soup.find("title")
      h1_node = soup.find("h1")
      if title_node and title_node.text.strip():
        clean_t = re.sub(r"(\||-|—).*$", "", title_node.text).strip()
        session["suggested_topic"] = clean_t[:45]
      elif h1_node and h1_node.text.strip():
        clean_t = re.sub(r"(\||-|—).*$", "", h1_node.text).strip()
        session["suggested_topic"] = clean_t[:45]
      else:
        session["suggested_topic"] = (
            doc_f.file_name.replace(".html", "").replace(".htm", "")
        )

    if os.path.exists(t_doc):
      os.remove(t_doc)

  if raw_text:
    session["texts"].append(raw_text)
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    if lines and session["suggested_topic"] == "UPSC_Notes":
      first_l = re.sub(
          r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍|━─—_-]", "", lines[0]
      ).strip()
      if "—" in first_l:
        first_l = first_l.split("—")[0].strip()
      elif "-" in first_l:
        first_l = first_l.split("-")[0].strip()
      session["suggested_topic"] = first_l[:40] if first_l else "UPSC_Notes"


# 3. /sachin कमांड - नाम पूछना और सुझाव देना
async def ask_for_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  user_id = update.effective_user.id
  session = USER_BUFFERS.get(user_id)

  if not session or (
      not session.get("texts") and not session.get("html_soups")
  ):
    await update.message.reply_text(
        "❌ कोई सामग्री नहीं मिली। कृपया पहले **/html** भेजकर कुछ नोट्स या"
        " फ़ाइलें भेजें।"
    )
    return ConversationHandler.END

  suggested = session.get("suggested_topic", "UPSC_Notes")

  prompt_msg = f"""📝 **फ़ाइल नाम की पुष्टि:**

📌 **सुझाया गया नाम:**
`{suggested}`

👉 **विकल्प:**
1. यदि **यही नाम** रखना है, तो सिर्फ **1** लिखकर भेजें।
2. यदि **नाम बदलना है**, तो ऊपर दिए गए नाम पर एक बार टैप करके कॉपी करें, एडिट करें और नया नाम भेज दें!"""

  await update.message.reply_text(prompt_msg, parse_mode=ParseMode.MARKDOWN)
  return WAITING_FOR_NAME


# 4. यूज़र का नाम रिसीव करके फ़ाइनल HTML जनरेट करना
async def generate_final_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  user_id = update.effective_user.id
  session = USER_BUFFERS.get(user_id)

  if not session:
    await update.message.reply_text(
        "सत्र समाप्त हो चुका है। कृपया दोबारा **/html** से शुरू करें।"
    )
    return ConversationHandler.END

  user_reply = update.message.text.strip()
  suggested = session.get("suggested_topic", "UPSC_Notes")

  final_topic = suggested if user_reply == "1" else user_reply
  safe_topic = re.sub(r"[^a-zA-Z0-9\u0900-\u097F]", "_", final_topic)[:30]
  clean_filename = f"{safe_topic}.html"

  wait_msg = await update.message.reply_text(
      "⏳ आपकी रंगीन व इंटरैक्टिव HTML फ़ाइल तैयार हो रही है..."
  )

  final_output_html = ""
  if session["html_soups"]:
    main_soup = session["html_soups"][0]
    sanitize_and_rebrand_html(main_soup, custom_title=final_topic)
    final_output_html = str(main_soup)
  else:
    combined_text = "\n\n".join(session["texts"])
    final_output_html = build_interactive_dashboard_html(
        final_topic, combined_text, session["images"]
    )

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
  await update.message.reply_text("प्रक्रिया रद्द कर दी गई।")
  return ConversationHandler.END


async def run_server():
  app = web.Application()
  app.router.add_get("/", lambda r: web.Response(text="Bot Alive 24/7"))
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.environ.get("PORT", 8080))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


async def main():
  await run_server()
  bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

  bot_app.add_handler(CommandHandler("start", start_handler))
  bot_app.add_handler(CommandHandler("html", start_html_session))

  conv_handler = ConversationHandler(
      entry_points=[CommandHandler("sachin", ask_for_name)],
      states={
          WAITING_FOR_NAME: [
              MessageHandler(
                  filters.TEXT & (~filters.COMMAND), generate_final_file
              )
          ]
      },
      fallbacks=[CommandHandler("cancel", cancel)],
  )

  bot_app.add_handler(conv_handler)
  bot_app.add_handler(
      MessageHandler(filters.ALL & (~filters.COMMAND), collect_messages)
  )

  await bot_app.initialize()
  await bot_app.start()
  await bot_app.updater.start_polling()

  while True:
    await asyncio.sleep(3600)


if __name__ == "__main__":
  asyncio.run(main())
