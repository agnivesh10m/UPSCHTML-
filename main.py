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
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "सचिन शर्मा"

USER_BUFFERS = {}


def sanitize_and_rebrand_html(soup: BeautifulSoup) -> None:
  """पुराने चैनलों के लिंक व नाम हटाना"""
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


def build_interactive_dashboard_html(
    topic: str, raw_text: str, image_list: list = None
) -> str:
  lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
  content_html = ""
  card_open = False
  in_table = False
  table_rows = []

  for line in lines:
    # 1. टेबल पार्सिंग (सख्त नियम ताकि साधारण टेक्स्ट टेबल न बने)
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
      content_html += (
          f"<div class='table-box'><table>{''.join(table_rows)}</table></div>"
      )
      in_table = False
      table_rows = []

    # 2. हेडिंग्स (नया कार्ड बनाना)
    is_heading = (
        re.match(r"^[0-9]+\.", line)
        or any(
            line.startswith(x)
            for x in ["📌", "🎯", "⚡", "📖", "💡", "🗳️", "⚖️", "🔍", "📝", "🛣️"]
        )
        or line.endswith(":")
    )

    if is_heading:
      if card_open:
        content_html += "</div>"  # पुराना कार्ड बंद
      content_html += (
          f"<div class='news-card'><h3 class='section-title'>{line}</h3>"
      )
      card_open = True
      continue

    # अगर अभी तक कोई कार्ड शुरू नहीं हुआ तो डिफ़ॉल्ट कार्ड खोलें
    if not card_open:
      content_html += "<div class='news-card'>"
      card_open = True

    # 3. कोट्स
    if line.startswith(">"):
      content_html += f"<blockquote>{line[1:].strip()}</blockquote>"
      continue

    # 4. तीर वाले फ्लो (Flow Arrow Layout)
    if "→" in line:
      steps = [s.strip() for s in line.split("→") if s.strip()]
      if len(steps) > 1:
        step_tags = "".join([f"<span class='flow-step'>{s}</span>" for s in steps])
        content_html += f"<div class='flow-container'>{step_tags}</div>"
        continue

    # 5. बुलेट पॉइंट्स
    if line.startswith(("•", "-", "▪", "▫", "*", "🔸")):
      clean_bullet = re.sub(r"^[•\-▪▫\*🔸]\s*", "", line)
      content_html += f"<li class='list-item'>{clean_bullet}</li>"
      continue

    # 6. सामान्य पैराग्राफ
    formatted = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
    content_html += f"<p class='para'>{formatted}</p>"

  if in_table:
    content_html += (
        f"<div class='table-box'><table>{''.join(table_rows)}</table></div>"
    )

  if card_open:
    content_html += "</div>"  # अंतिम कार्ड बंद

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
  --tag-bg:#eef3fb; --shadow:0 4px 15px rgba(20,30,50,.08);
}}
[data-theme="dark"] {{
  --bg:#0f1620; --card:#161f2b; --text:#e7edf5; --muted:#9aa7b8; --border:#26313f;
  --accent:#5fa8e0; --accent2:#4fce9a; --tag-bg:#1c2b3d;
  --shadow:0 4px 18px rgba(0,0,0,.4);
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  background:var(--bg); color:var(--text); font-family:'Hind','Noto Sans Devanagari',sans-serif;
  line-height:1.7; transition:background .3s,color .3s; padding-bottom:70px;
}}
.top-header {{
  background:linear-gradient(135deg,#0b1f3a,#0b5fa5 60%,#083a63);
  color:#fff; padding:28px 16px 22px; text-align:center;
  border-bottom:4px solid var(--saffron);
}}
.top-header h1 {{ font-size:1.6rem; margin-bottom:8px; font-weight:700; }}
.author-pill {{
  display:inline-block; margin-top:6px; background:rgba(255,255,255,.15);
  border:1px solid rgba(255,255,255,.35); padding:5px 18px; border-radius:30px; font-weight:600; font-size:0.9rem;
}}
.controls {{
  display:flex; justify-content:center; gap:10px; margin-top:14px; flex-wrap:wrap;
}}
.controls input {{
  width:min(380px,85vw); padding:9px 14px; border-radius:20px; border:none; outline:none; font-size:0.9rem;
}}
.controls button {{
  padding:9px 16px; border-radius:20px; border:1px solid rgba(255,255,255,.4);
  background:rgba(255,255,255,.2); color:#fff; font-weight:600; cursor:pointer;
}}
.wrap {{ max-width:900px; margin:20px auto; padding:0 14px; width:100%; }}
.news-card {{
  background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:20px; margin-bottom:18px; box-shadow:var(--shadow); width:100%;
}}
.section-title {{
  color:var(--accent); font-size:1.2rem; margin-bottom:12px;
  border-left:4px solid var(--saffron); padding-left:10px;
}}
.para {{ margin:8px 0; font-size:0.98rem; word-break:break-word; }}
.list-item {{ margin:6px 0 6px 20px; color:var(--text); font-size:0.96rem; }}
.flow-container {{
  display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; align-items:center;
}}
.flow-step {{
  background:var(--tag-bg); color:var(--accent); border:1px solid var(--border);
  padding:4px 10px; border-radius:6px; font-size:0.88rem; font-weight:600;
  display:inline-flex; align-items:center;
}}
.flow-step:not(:last-child)::after {{
  content:"→"; margin-left:8px; color:var(--muted); font-weight:bold;
}}
blockquote {{
  border-left:4px solid var(--accent); background:var(--tag-bg);
  padding:10px 14px; border-radius:0 8px 8px 0; margin:14px 0; font-weight:500;
}}
.table-box {{ overflow-x:auto; margin:16px 0; width:100%; }}
table {{ width:100%; border-collapse:collapse; border-radius:8px; }}
th {{ background:var(--accent); color:#fff; padding:9px 12px; text-align:left; }}
td {{ padding:8px 12px; border:1px solid var(--border); }}
tr:nth-child(even) {{ background:rgba(128,128,128,0.05); }}
.img-container {{ text-align:center; margin:16px 0; }}
.post-img {{ max-width:100%; border-radius:8px; }}
#telegramBtn {{
  position:fixed; bottom:16px; right:16px; z-index:90;
  background:#229ED9; color:#fff; border:none; border-radius:30px;
  padding:10px 18px; font-weight:700; cursor:pointer; box-shadow:0 4px 14px rgba(0,0,0,0.25);
  font-size:0.85rem;
}}
footer {{
  background:#0b1f3a; color:#dbe6f2; text-align:center; padding:24px 16px; margin-top:35px; font-size:0.85rem;
}}
footer a {{ color:#8bc4ef; font-weight:700; text-decoration:none; }}
</style>
</head>
<body data-theme="light">
<header class="top-header">
  <h1>🇮🇳 {topic}</h1>
  <div class="author-pill">✍️ संकलन: {AUTHOR_NAME} | {CHANNEL_NAME}</div>
  <div class="controls">
    <input type="text" id="searchBox" placeholder="🔍 खोजें: विषय, कीवर्ड...">
    <button onclick="toggleTheme()">🌗 Dark / Light</button>
  </div>
</header>
<main class="wrap" id="mainContent">
  {img_markup}
  {content_html}
</main>
<button id="telegramBtn" onclick="window.open('{CHANNEL_LINK}','_blank')">📲 TELEGRAM — {CHANNEL_NAME}</button>
<footer>
  <div><b>UPSC CSE NOTES</b></div>
  <div style="margin-top:8px;">निर्माता: <b>{AUTHOR_NAME}</b> | ग्रुप: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
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


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await update.message.reply_text(
      f"👋 **नमस्ते {AUTHOR_NAME}!**\n\n"
      "1. पहले **/html** भेजें।\n"
      "2. नोट्स या HTML फ़ाइल भेजें।\n"
      "3. अंत में **/sachin** भेजें — बिल्कुल साफ़ और सुंदर डैशबोर्ड फ़ाइल बन"
      " जाएगी।"
  )


async def start_html_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user_id = update.effective_user.id
  USER_BUFFERS[user_id] = {
      "active": True,
      "texts": [],
      "images": [],
      "html_soups": [],
  }
  await update.message.reply_text(
      "🟢 **सत्र शुरू!** अब सामग्री भेजें और अंत में **/sachin** भेजें।"
  )


async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  session = USER_BUFFERS.get(user_id)
  if not session or not session.get("active"):
    await update.message.reply_text("💡 पहले **/html** भेजें।")
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
    if os.path.exists(t_doc):
      os.remove(t_doc)

  if raw_text:
    session["texts"].append(raw_text)


async def finalize_and_generate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user_id = update.effective_user.id
  session = USER_BUFFERS.get(user_id)

  if not session or (
      not session.get("texts") and not session.get("html_soups")
  ):
    await update.message.reply_text("❌ पहले सामग्री भेजें।")
    return

  wait_msg = await update.message.reply_text(
      "⏳ नोट्स प्रोसेस हो रहे हैं, थोड़ा इंतज़ार करें..."
  )

  clean_filename = "UPSC_Notes_SachinSharma.html"
  final_output_html = ""

  if session["html_soups"]:
    main_soup = session["html_soups"][0]
    sanitize_and_rebrand_html(main_soup)
    final_output_html = str(main_soup)
  else:
    combined_text = "\n\n".join(session["texts"])
    lines = [l.strip() for l in combined_text.split("\n") if l.strip()]
    topic = "Kashmir Eurasian Gateway"
    if lines:
      cleaned = re.sub(
          r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍|━─—_-]", "", lines[0]
      ).strip()
      if "—" in cleaned:
        cleaned = cleaned.split("—")[0].strip()
      topic = cleaned[:35] if cleaned else "UPSC Notes"
    clean_filename = f"{re.sub(r'[^a-zA-Z0-9]', '_', topic)[:25]}_Notes.html"
    final_output_html = build_interactive_dashboard_html(
        topic, combined_text, session["images"]
    )

  with open(clean_filename, "w", encoding="utf-8") as f:
    f.write(final_output_html)

  with open(clean_filename, "rb") as send_doc:
    await update.message.reply_document(
        document=send_doc,
        filename=clean_filename,
        caption=(
            f"📄 <b>नोट्स फ़ाइल तैयार!</b>\n"
            f"👤 <b>निर्माता:</b> {AUTHOR_NAME}\n"
            f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
        ),
        parse_mode=ParseMode.HTML,
    )

  await wait_msg.delete()
  if os.path.exists(clean_filename):
    os.remove(clean_filename)

  USER_BUFFERS.pop(user_id, None)


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
  bot_app.add_handler(CommandHandler("sachin", finalize_and_generate))
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
