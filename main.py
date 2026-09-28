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


def format_to_colorful_html(
    topic: str, raw_text: str, image_b64: str = None
) -> str:
  lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
  content_html = ""
  in_table = False
  table_rows = []

  for line in lines:
    # टेबल पार्सिंग
    if line.startswith("|") and line.endswith("|"):
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

    # कोट्स / महत्वपूर्ण लाइन
    if line.startswith(">"):
      content_html += f"<blockquote>{line[1:].strip()}</blockquote>"
      continue

    # हेडिंग्स और सब-हेडिंग्स (रंग और बॉर्डर के साथ)
    if re.match(r"^[0-9]+\.", line) or any(
        line.startswith(x)
        for x in ["📌", "🎯", "⚡", "📖", "💡", "🗳️", "⚖️", "🔍"]
    ):
      content_html += f"<h3 class='topic-heading'>{line}</h3>"
      continue

    # बुलेट पॉइंट्स
    if line.startswith(("•", "-", "▪", "▫", "*")):
      content_html += f"<li class='list-p'>{line[1:].strip()}</li>"
      continue

    # सामान्य पैराग्राफ और बोल्ड टेक्स्ट
    formatted_line = re.sub(
        r"\*\*(.*?)\*\*", r"<strong style='color:#0369a1;'>\1</strong>", line
    )
    content_html += f"<p class='para-text'>{formatted_line}</p>"

  if in_table:
    content_html += (
        f"<div class='table-box'><table>{''.join(table_rows)}</table></div>"
    )

  img_tag = (
      f"<div class='img-wrap'><img src='data:image/jpeg;base64,{image_b64}' class='note-img'/></div>"
      if image_b64
      else ""
  )

  return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} - सचिन शर्मा</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background-color: #0f172a;
        color: #1e293b;
        margin: 0;
        padding: 24px 12px;
        display: flex;
        justify-content: center;
    }}
    .sheet {{
        background: #ffffff;
        max-width: 820px;
        width: 100%;
        border-radius: 14px;
        padding: 28px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    }}
    .top-header {{
        border-bottom: 3px solid #0284c7;
        padding-bottom: 12px;
        margin-bottom: 20px;
    }}
    .top-header h2 {{
        color: #0369a1;
        margin: 0 0 6px 0;
        font-size: 1.45rem;
    }}
    .author-bar {{
        display: flex;
        justify-content: space-between;
        flex-wrap: wrap;
        font-size: 13.5px;
        color: #64748b;
    }}
    .author-bar a {{
        color: #0284c7;
        font-weight: bold;
        text-decoration: none;
    }}
    .img-wrap {{
        text-align: center;
        margin: 20px 0;
    }}
    .note-img {{
        max-width: 100%;
        height: auto;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }}
    .topic-heading {{
        color: #075985;
        border-left: 4px solid #f59e0b;
        background: #f8fafc;
        padding: 8px 12px;
        border-radius: 0 6px 6px 0;
        margin: 22px 0 10px 0;
        font-size: 1.15rem;
    }}
    .para-text {{
        line-height: 1.7;
        margin: 8px 0;
        font-size: 15.5px;
    }}
    .list-p {{
        margin: 6px 0 6px 20px;
        line-height: 1.6;
        color: #334155;
    }}
    blockquote {{
        border-left: 4px solid #0284c7;
        background: #f0f9ff;
        padding: 12px 14px;
        margin: 16px 0;
        border-radius: 0 8px 8px 0;
        color: #0369a1;
        font-weight: 500;
    }}
    .table-box {{
        overflow-x: auto;
        margin: 16px 0;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
    }}
    .th-cell {{
        background: #0284c7;
        color: #ffffff;
        padding: 10px 12px;
        text-align: left;
    }}
    .td-cell {{
        padding: 9px 12px;
        border: 1px solid #cbd5e1;
    }}
    tr:nth-child(even) {{
        background: #f8fafc;
    }}
    .bottom-bar {{
        margin-top: 30px;
        padding: 14px;
        border-top: 1px dashed #cbd5e1;
        background: #f8fafc;
        border-radius: 8px;
        text-align: center;
        font-size: 13px;
        color: #475569;
    }}
    .bottom-bar a {{
        color: #0284c7;
        font-weight: bold;
        text-decoration: none;
    }}
</style>
</head>
<body>
<div class="sheet">
    <div class="top-header">
        <h2>{topic}</h2>
        <div class="author-bar">
            <span>✍️ <strong>निर्माता:</strong> सचिन शर्मा</span>
            <span>📢 <strong>टेलीग्राम:</strong> <a href="{CHANNEL_LINK}">@UPSCHTML</a></span>
        </div>
    </div>
    {img_tag}
    <div class="main-body">
        {content_html}
    </div>
    <div class="bottom-bar">
        🌟 <strong>सचिन शर्मा</strong> द्वारा तैयार संकलन | <a href="{CHANNEL_LINK}">यहाँ क्लिक करके ग्रुप से जुड़ें</a>
    </div>
</div>
</body>
</html>"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await update.message.reply_text(
      "👋 नमस्ते सचिन भाई!\n\n"
      "आप कितना भी बड़ा मैसेज, फ़ोटो या HTML फ़ाइल फॉरवर्ड करें। मैं तुरंत एक सुंदर रंगीन HTML फ़ाइल बनाकर भेज दूँगा।"
  )


async def handle_any_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  msg = update.message
  if not msg:
    return

  raw_text = msg.text or msg.caption or ""
  image_b64 = None

  # प्रोसेस का मैसेज
  wait_msg = await msg.reply_text("⏳ नोट्स तैयार हो रहे हैं...")

  # 1. फोटो हैंडलिंग
  if msg.photo:
    photo = msg.photo[-1]
    file_obj = await photo.get_file()
    temp_img = f"img_{photo.file_unique_id}.jpg"
    await file_obj.download_to_drive(temp_img)
    with open(temp_img, "rb") as f:
      image_b64 = base64.b64encode(f.read()).decode("utf-8")
    if os.path.exists(temp_img):
      os.remove(temp_img)

  # 2. HTML डॉक्यूमेंट हैंडलिंग
  elif msg.document and (
      msg.document.file_name.endswith(".html")
      or msg.document.file_name.endswith(".htm")
  ):
    doc_file = await msg.document.get_file()
    temp_doc = f"doc_{msg.document.file_name}"
    await doc_file.download_to_drive(temp_doc)
    with open(temp_doc, "r", encoding="utf-8", errors="ignore") as f:
      soup = BeautifulSoup(f.read(), "html.parser")
      for t in soup(["script", "style", "nav", "footer", "header"]):
        t.decompose()
      raw_text = soup.get_text(separator="\n").strip()
    if os.path.exists(temp_doc):
      os.remove(temp_doc)

  if not raw_text.strip():
    await wait_msg.edit_text("कृपया कोई मान्य टेक्स्ट या फ़ाइल भेजें।")
    return

  # 3. विषय पहचानना
  lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
  topic = "UPSC Study Notes"
  if lines:
    topic_clean = re.sub(
        r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍|━─—_-]", "", lines[0]
    ).strip()
    if "—" in topic_clean:
      topic_clean = topic_clean.split("—")[0].strip()
    topic = topic_clean[:35] if topic_clean else "Study Notes"

  # 4. रंगीन HTML फ़ाइल तैयार करना
  html_doc = format_to_colorful_html(topic, raw_text, image_b64)
  clean_filename = (
      re.sub(r"[^a-zA-Z0-9\u0900-\u097F]", "_", topic)[:25] + ".html"
  )

  with open(clean_filename, "w", encoding="utf-8") as f:
    f.write(html_doc)

  # 5. सीधा HTML फ़ाइल डॉक्यूमेंट भेजना
  with open(clean_filename, "rb") as send_doc:
    await msg.reply_document(
        document=send_doc,
        filename=clean_filename,
        caption=(
            f"📄 <b>नोट्स तैयार:</b> <code>{topic}</code>\n"
            f"👤 <b>निर्माता:</b> सचिन शर्मा\n"
            f"📢 <b>ग्रुप:</b> @UPSCHTML"
        ),
        parse_mode=ParseMode.HTML,
    )

  await wait_msg.delete()

  if os.path.exists(clean_filename):
    os.remove(clean_filename)


# Render Web Server (24x7 Alive)
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
  bot_app.add_handler(
      MessageHandler(filters.ALL & (~filters.COMMAND), handle_any_message)
  )

  await bot_app.initialize()
  await bot_app.start()
  await bot_app.updater.start_polling()

  while True:
    await asyncio.sleep(3600)


if __name__ == "__main__":
  asyncio.run(main())
