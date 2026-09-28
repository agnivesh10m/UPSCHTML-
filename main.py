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

# Render पर Environment Variable से टोकन लेगा, या सीधे स्ट्रिंग डाल सकते हैं
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_LINK = "https://t.me/UPSCHTML"

WAITING_FOR_TOPIC = 1


# 1. HTML लेआउट तैयार करना
def build_final_html(topic: str, extracted_text: str) -> str:
    lines = [l.strip() for l in extracted_text.split("\n") if l.strip()]
    content_markup = ""

    for line in lines:
        if line.startswith(("|", "•", "-", "*")):
            content_markup += f"<p style='margin: 4px 0;'>{line}</p>\n"
        elif re.match(r"^[0-9]+\.", line):
            content_markup += f"<h3 style='color: #0369a1; margin-top: 16px; margin-bottom: 6px;'>{line}</h3>\n"
        else:
            content_markup += (
                f"<p style='margin: 6px 0; line-height: 1.6;'>{line}</p>\n"
            )

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #f1f5f9;
            color: #0f172a;
            padding: 24px 14px;
            display: flex;
            justify-content: center;
        }}
        .card {{
            background: #ffffff;
            max-width: 800px;
            width: 100%;
            padding: 26px;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        }}
        .header {{
            border-bottom: 2px solid #0284c7;
            padding-bottom: 12px;
            margin-bottom: 16px;
        }}
        .header h2 {{
            color: #0369a1;
            margin: 0 0 6px 0;
            font-size: 1.4rem;
        }}
        .meta {{
            font-size: 13px;
            color: #64748b;
        }}
        .footer {{
            margin-top: 26px;
            padding: 12px;
            border-top: 1px dashed #cbd5e1;
            font-size: 13px;
            text-align: center;
            background: #f8fafc;
            border-radius: 8px;
            color: #475569;
        }}
        .footer a, .meta a {{
            color: #0284c7;
            font-weight: 600;
            text-decoration: none;
        }}
    </style>
</head>
<body>
<div class="card">
    <div class="header">
        <h2>{topic}</h2>
        <div class="meta">
            ✍️ <strong>सचिन शर्मा</strong> | 🔗 <a href="{CHANNEL_LINK}">@UPSCHTML</a>
        </div>
    </div>
    <div class="content">
        {content_markup}
    </div>
    <div class="footer">
        🌟 <strong>सचिन शर्मा</strong> | <a href="{CHANNEL_LINK}">टेलीग्राम ग्रुप से जुड़ें</a>
    </div>
</div>
</body>
</html>"""


# 2. फ़ाइल रिसीव और टेक्स्ट साफ़ करना
async def receive_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    doc = update.message.document
    if not (doc.file_name.endswith(".html") or doc.file_name.endswith(".htm")):
        await update.message.reply_text(
            "कृपया केवल .html या .htm फ़ाइल ही भेजें।"
        )
        return ConversationHandler.END

    msg_wait = await update.message.reply_text("⏳ फ़ाइल प्रोसेस हो रही है...")

    tg_file = await doc.get_file()
    temp_in = f"temp_{doc.file_name}"
    await tg_file.download_to_drive(temp_in)

    with open(temp_in, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    for tag in soup(["script", "style", "header", "footer", "nav"]):
        tag.decompose()

    extracted_text = soup.get_text(separator="\n").strip()

    if os.path.exists(temp_in):
        os.remove(temp_in)

    lines = [l.strip() for l in extracted_text.split("\n") if l.strip()]
    suggested_topic = "UPSC Study Notes"
    if lines:
        cleaned = re.sub(r"[📌💡⚡✨🔥📖🎯📝🌪️|━─—_-]", "", lines[0]).strip()
        if "—" in cleaned:
            cleaned = cleaned.split("—")[0].strip()
        suggested_topic = cleaned[:40] if cleaned else "Study Notes"

    context.user_data["raw_text"] = extracted_text
    context.user_data["suggested_topic"] = suggested_topic

    await msg_wait.delete()
    reply_msg = f"""✅ टेक्स्ट निकाल लिया गया है!

📌 **सुझाया गया विषय:** `{suggested_topic}`

• अगर यही नाम रखना है, तो सिर्फ **1** भेजें।
• या फिर अपना **नया नाम** लिखकर भेजें।"""

    await update.message.reply_text(reply_msg, parse_mode=ParseMode.MARKDOWN)
    return WAITING_FOR_TOPIC


# 3. फ़ाइल बनाना और भेजना
async def set_topic_and_generate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user_choice = update.message.text.strip()
    suggested = context.user_data.get("suggested_topic", "Study_Notes")
    extracted_text = context.user_data.get("raw_text", "")

    final_topic = suggested if user_choice == "1" else user_choice
    clean_filename = (
        re.sub(r"[^a-zA-Z0-9\u0900-\u097F]", "_", final_topic)[:30] + ".html"
    )

    final_html = build_final_html(final_topic, extracted_text)
    with open(clean_filename, "w", encoding="utf-8") as f:
        f.write(final_html)

    preview_snippet = "\n".join(
        [l for l in extracted_text.split("\n") if l.strip()][:10]
    )
    branded_caption = f"""📌 **{final_topic}**

{preview_snippet}
...

━━━━━━━━━━━━━━━━━━━━━
👤 **सचिन शर्मा**
📢 **ग्रुप लिंक:** [यहाँ क्लिक करें]({CHANNEL_LINK})
"""

    await update.message.reply_text(
        branded_caption,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )

    with open(clean_filename, "rb") as f:
        await msg_doc = update.message.reply_document(
            document=f,
            filename=clean_filename,
            caption=f"📄 **HTML:** `{final_topic}`\n👤 **सचिन शर्मा**",
            parse_mode=ParseMode.MARKDOWN,
        )

    if os.path.exists(clean_filename):
        os.remove(clean_filename)

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("प्रक्रिया रद्द कर दी गई।")
    return ConversationHandler.END


# 4. Render के लिए वेब सर्वर (ताकि पिंग काम करे)
async def web_home(request):
    return web.Response(text="Bot is running alive 24/7!")


async def run_web_server():
    app = web.Application()
    app.router.add_get("/", web_home)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    # वेब सर्वर स्टार्ट (पिंग के लिए)
    await run_web_server()

    # टेलीग्राम बॉट स्टार्ट
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Document.ALL, receive_file)],
        states={
            WAITING_FOR_TOPIC: [
                MessageHandler(
                    filters.TEXT & (~filters.COMMAND), set_topic_and_generate
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    bot_app.add_handler(conv_handler)
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    # लूप को चालू रखना
    import asyncio

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
  
