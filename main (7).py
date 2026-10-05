import os
import re
import time
import asyncio
import io
from datetime import timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
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

from config import BOT_TOKEN, ADMIN_IDS, ADMIN_NAMES, CHANNEL_LINK, CHANNEL_NAME, AUTHOR_NAME, get_ist_now
from database import (
    get_db_connection, register_user, is_authorized, get_user_daf, save_user_daf,
    add_vip_user, remove_vip_user, get_user_full_info, save_to_archive,
    get_archive_by_date, get_all_user_ids, get_all_users_detailed
)
from ai_engine import (
    call_gemini_safely, call_gemini_multimodal_inline,
    call_gemini_audio_transcribe, download_audio_stream
)
from html_builder import (
    build_standalone_master_html, build_vision_ias_interactive_portal,
    clean_all_markdown_and_fix_content
)

WAITING_CONTACT_MSG = 1
WAITING_BROADCAST_MSG = 2
WAITING_ASK_SESSION = 3

DAF_NAME = 4
DAF_STATE = 5
DAF_COLLEGE = 6
DAF_STATUS = 7
DAF_OPTIONAL_STEP = 8
DAF_ATTEMPT_STEP = 9
DAF_QCOUNT = 10
WAITING_INTERVIEW_VOICE = 11
WAITING_INTERVIEW_DECISION = 12

CA_CHOOSE_TYPE = 13
CA_QUESTION_TEXT = 14
CA_CUSTOM_MARKS = 15
CA_ANSWER_COPY = 16

CONTACT_SESSIONS = {}
USER_QUIZ_SELECTIONS = {}
MAINS_SELECTIONS = {}
CHECK_ANSWER_CACHE = {}
TRENDING_CACHE = {}
INTERVIEW_SESSION = {}
LAST_BROADCAST_DATA = {}

def ensure_auth(handler_func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
        register_user(user.id, user.username, user.first_name)
        if not is_authorized(user.id):
            user_link = f'<a href="tg://user?id={user.id}">{user.id}</a>'
            msg = (
                f"👋 <b>नमस्ते {user.first_name}!</b>\n\n"
                "📚 <b>UPSC SMART DESK में आपका स्वागत है।</b>\n\n"
                "⚠️ <b>सत्र अनधिकृत:</b> यह बॉट केवल <b>UPSC Civil Services Examination</b> के समर्पित अभ्यर्थियों के लिए सुरक्षित है ताकि उच्च-स्तरीय AI टूल्स का दुरुपयोग न हो।\n\n"
                f"🆔 <b>आपकी टेलीग्राम ID:</b> {user_link}\n\n"
                f"👉 इस अध्ययन डेस्क का पूर्ण एक्सेस प्राप्त करने के लिए ओनर <b>{AUTHOR_NAME}</b> से संपर्क करें:\n"
                f"• संपर्क कमांड: <code>/owner</code>\n"
                f"• आधिकारिक चैनल: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
            )
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return
        return await handler_func(update, context, *args, **kwargs)
    return wrapper

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a> (<code>{user.id}</code>)'
    
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"👋 <b>नमस्ते {user_link}!</b>\n\n"
            "📚 <b>UPSC CIVIL SERVICES PORTAL</b>\n\n"
            "आपका पंजीकरण सुरक्षित हो गया है (स्थिति: <b>निःशुल्क सदस्य</b>)।\n\n"
            "इस पोर्टल पर UPSC CSE के 360° दैनिक नोट्स, लाइव DAF साक्षात्कार, उत्तर-पुस्तिका मूल्यांकन और विगत वर्षों के प्रश्नों (PYQs) का संग्रह उपलब्ध है।\n\n"
            f"⚠️️ <b>नोट:</b> वर्तमान में प्रीमियम AI टूल्स आपके खाते पर सक्रिय नहीं हैं। एक्सेस सक्रिय करवाने हेतु <code>/owner</code> पर संपर्क करें।\n\n"
            f"📢 <b>आधिकारिक चैनल:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>",
            parse_mode=ParseMode.HTML
        )
        return

    admin_tag = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if user.id in ADMIN_IDS else "📚 <b>UPSC CSE स्मार्ट अध्ययन डेस्क</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user_link}!</b>\n\n"
        f"{admin_tag}"
        "मुख्य कमांड्स:\n\n"
        "📖 <b>अध्ययन एवं नोट्स:</b>\n"
        "• <code>/daily</code> — दैनिक 360° समसामयिक संकलन\n"
        "• <code>/trending</code> — राष्ट्रीय व वैश्विक ट्रेंडिंग रडार\n"
        "• <code>/quiz</code> — विजन IAS स्टाइल लाइव मॉक टेस्ट पोर्टल\n"
        "• <code>/mains</code> — मुख्य परीक्षा अभ्यास (PYQs 2013-2026 व मॉडल प्रश्न)\n"
        "• <code>/checkanswer</code> — उत्तर पुस्तिका मूल्यांकन (PYQ व मॉडल)\n"
        "• <code>/interview</code> — 1-on-1 साक्षात्कार (DAF व वॉयस)\n"
        "• <code>/weekly</code> — साप्ताहिक क्विक रिवीजन\n"
        "• <code>/monthly</code> — संपूर्ण मासिक संकलन\n"
        "• <code>/yearly</code> — वार्षिक महा-संकलन (PT-365)\n"
        "• <code>/ask</code> — 24/7 यूपीएससी मेंटरशिप सत्र\n\n"
        "💬 <b>सहायता व संपर्क:</b>\n"
        "• <code>/help</code> — संपूर्ण उपयोग मार्गदर्शिका\n"
        "• <code>/owner</code> — सचिन शर्मा से संपर्क करें\n"
        "• <code>/cancel</code> — प्रक्रिया तुरंत रद्द करें\n\n"
        f"📢 <b>ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    help_text = (
        f"📖 <b>UPSC SMART DESK — संपूर्ण गाइड ({AUTHOR_NAME})</b>\n\n"
        "1️⃣ <b>लाइव साक्षात्कार (`/interview`):</b> DAF भरने के बाद बोर्ड आपकी पृष्ठभूमि के आधार पर प्रशासनिक प्रश्न ऑडियो में पूछेगा। आप बोलकर उत्तर रिकॉर्ड करें, बोर्ड सुनकर मूल्यांकन व रिपोर्ट देगा।\n\n"
        "2️⃣ <b>ऑनलाइन क्विज़ पोर्टल (`/quiz`):</b> GS-1, GS-2 व GS-3 के विषयों में से 50, 100 या 200 प्रश्नों का लाइव टेस्ट पोर्टल प्राप्त करें।\n\n"
        "3️⃣ <b>उत्तर-पुस्तिका मूल्यांकन (`/checkanswer`):</b> PYQ या अपने मॉडल प्रश्न का चयन करें, अंक चुनें और कॉपी की फोटो/PDF भेजें।\n\n"
        "4️⃣ <b>मुख्य परीक्षा अभ्यास (`/mains`):</b> PYQs (2013-2026 संपूर्ण आर्काइव) या नए संभावित प्रश्नों का चयन करें।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@ensure_auth
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = get_ist_now()
    keyboard = []
    for i in range(-5, 4):
        target_dt = today + timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        label = f"🌟 आज ({d_str})" if i == 0 else (f"📅 {d_str} (-{-i} दिन)" if i < 0 else f"🔮 {d_str} (+{i} दिन)")
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")])
    await update.message.reply_text("📅 <b>जिस तारीख के UPSC दैनिक नोट्स चाहिए, उसका चयन करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏛 GS पेपर 1 (इतिहास, भूगोल, समाज)", callback_data="quizgs_1")],
        [InlineKeyboardButton("⚖ GS पेपर 2 (राजव्यवस्था, शासन, IR)", callback_data="quizgs_2")],
        [InlineKeyboardButton("💰 GS पेपर 3 (अर्थव्यवस्था, पर्यावरण, Sci-Tech)", callback_data="quizgs_3")],
        [InlineKeyboardButton("⚡ संपूर्ण समसामयिकी (Current Affairs)", callback_data="quizgs_ca")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🎯 <b>चरण 1/3:</b> किस GS पेपर का लाइव टेस्ट देना चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_quiz_gs_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "quizgs_1":
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "GS-1"}
        keyboard = [
            [InlineKeyboardButton("📜 प्राचीन व मध्यकालीन इतिहास", callback_data="quizsub_ancient_med")],
            [InlineKeyboardButton("🇮🇳 आधुनिक भारत व राष्ट्रीय आंदोलन", callback_data="quizsub_modern")],
            [InlineKeyboardButton("🎨 भारतीय कला एवं संस्कृति", callback_data="quizsub_art")],
            [InlineKeyboardButton("🌍 भारत एवं विश्व का भूगोल", callback_data="quizsub_geography")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 1):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    elif data == "quizgs_2":
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "GS-2"}
        keyboard = [
            [InlineKeyboardButton("🏛️ संविधान एवं राजव्यवस्था (Polity)", callback_data="quizsub_polity")],
            [InlineKeyboardButton("⚖️ शासन प्रणाली व सामाजिक न्याय", callback_data="quizsub_gov")],
            [InlineKeyboardButton("🌐 अंतर्राष्ट्रीय संबंध (IR)", callback_data="quizsub_ir")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 2):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    elif data == "quizgs_3":
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "GS-3"}
        keyboard = [
            [InlineKeyboardButton("💰 भारतीय अर्थव्यवस्था व कृषि", callback_data="quizsub_economy")],
            [InlineKeyboardButton("🌿 पर्यावरण, पारिस्थितिकी व जैव विविधता", callback_data="quizsub_env")],
            [InlineKeyboardButton("🔬 विज्ञान, प्रौद्योगिकी व अंतरिक्ष", callback_data="quizsub_scitech")],
            [InlineKeyboardButton("🛡️️ आंतरिक सुरक्षा व आपदा प्रबंधन", callback_data="quizsub_security")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 3):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "CA", "sub": "दैनिक व मासिक करेंट अफेयर्स"}
        keyboard = [
            [InlineKeyboardButton("⚡ 50 प्रश्न (मानक अभ्यास सेट)", callback_data="quizcnt_50")],
            [InlineKeyboardButton("🎯 100 प्रश्न (पूर्ण विजन IAS स्टाइल मॉक)", callback_data="quizcnt_100")],
            [InlineKeyboardButton("🏆 200 प्रश्न (महा-अभ्यास मैराथन)", callback_data="quizcnt_200")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 3/3:</b> प्रश्नों की संख्या चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_quiz_sub_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "quiz_back_gs":
        await quiz_cmd(update, context)
        return

    sub_map = {
        "quizsub_ancient_med": "प्राचीन व मध्यकालीन भारतीय इतिहास",
        "quizsub_modern": "आधुनिक भारत का इतिहास व स्वतंत्रता संग्राम",
        "quizsub_art": "भारतीय कला, साहित्य एवं संस्कृति",
        "quizsub_geography": "भारत एवं विश्व का भौतिक व आर्थिक भूगोल",
        "quizsub_polity": "भारतीय संविधान, राजव्यवस्था व न्यायपालिका",
        "quizsub_gov": "शासन प्रणाली, नीतियां व सामाजिक न्याय",
        "quizsub_ir": "अंतर्राष्ट्रीय संबंध व वैश्विक संस्थाएं",
        "quizsub_economy": "भारतीय अर्थव्यवस्था, बजट व कृषि सुधार",
        "quizsub_env": "पर्यावरण, पारिस्थितिकी व जलवायु परिवर्तन",
        "quizsub_scitech": "विज्ञान एवं प्रौद्योगिकी, रक्षा व अंतरिक्ष",
        "quizsub_security": "आंतरिक सुरक्षा व आपदा प्रबंधन"
    }
    USER_QUIZ_SELECTIONS[user_id]["sub"] = sub_map.get(data, "सामान्य अध्ययन")

    keyboard = [
        [InlineKeyboardButton("⚡ 50 प्रश्न (मानक अभ्यास सेट)", callback_data="quizcnt_50")],
        [InlineKeyboardButton("🎯 100 प्रश्न (पूर्ण विजन IAS स्टाइल मॉक)", callback_data="quizcnt_100")],
        [InlineKeyboardButton("🏆 200 प्रश्न (महा-अभ्यास मैराथन)", callback_data="quizcnt_200")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quizgs_1")]
    ]
    await query.message.edit_text(f"🎯 <b>चरण 3/3:</b> विषय <b>{USER_QUIZ_SELECTIONS[user_id]['sub']}</b> के कितने प्रश्न चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_quiz_cnt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cnt = int(query.data.replace("quizcnt_", ""))
    user_id = query.from_user.id
    subj = USER_QUIZ_SELECTIONS.get(user_id, {}).get("sub", "सामान्य अध्ययन")

    status_msg = await query.message.reply_text("⏳ [■□□□□□□□□□] 15% UPSC प्रश्न बैंक संकलित हो रहा है...")

    prompt = f"""
आप UPSC सिविल सेवा प्रारंभिक परीक्षा के मुख्य परीक्षक हैं।
विषय: '{subj}' पर ठीक {cnt} कठिन, मानक और कथन-आधारित बहुविकल्पीय प्रश्न तैयार करें।
अनिवार्य रूप से शुद्ध JSON Array (बिना किसी अतिरिक्त मार्कडाउन कोड या व्याख्या के) इस प्रारूप में दें:
[
  {{
    "topic": "{subj}",
    "text": "1. प्रश्न का पूर्ण विवरण और कथन...",
    "options": ["(a) केवल 1", "(b) केवल 2", "(c) 1 और 2 दोनों", "(d) न तो 1, न ही 2"],
    "correctAnswer": 2,
    "solution": "<b>व्याख्या:</b> प्रामाणिक स्रोत सहित संपूर्ण 2-3 पंक्तियों की व्याख्या।"
  }}
]
नोट: correctAnswer शून्य-आधारित इंडेक्स (0=a, 1=b, 2=c, 3=d) होना चाहिए। केवल शुद्ध हिंदी भाषा रखें।
"""
    try:
        await status_msg.edit_text("⏳ [■■■■□□□□□□] 45% कथन व विकल्पों का संश्लेषण जारी...")
        raw_resp = await asyncio.to_thread(call_gemini_safely, prompt)
        
        await status_msg.edit_text("⏳ [■■■■■■■□□□] 75% विजन IAS ऑनलाइन टेस्ट पोर्टल असेंबल हो रहा है...")
        clean_json_str = re.sub(r'^```json\s*', '', raw_resp.strip(), flags=re.IGNORECASE)
        clean_json_str = re.sub(r'```$', '', clean_json_str.strip()).strip()

        test_id = f"{int(time.time()) % 100000}"
        portal_html = build_vision_ias_interactive_portal(subj, test_id, cnt, clean_json_str)

        filename = f"UPSC_Mock_{cnt}Q_{test_id}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(portal_html)

        await status_msg.edit_text("⏳ [■■■■■■■■■■] 100% ऑनलाइन टेस्ट पोर्टल तैयार!")

        with open(filename, "rb") as doc:
            await context.bot.send_document(
                chat_id=user_id,
                document=doc,
                filename=filename,
                caption=(
                    f"🎯 <b>UPSC CSE ऑनलाइन टेस्ट पोर्टल तैयार!</b>\n\n"
                    f"📚 <b>विषय:</b> <code>{subj}</code>\n"
                    f"📝 <b>कुल प्रश्न:</b> <code>{cnt} MCQs</code>\n"
                    f"⏱ <b>सुविधाएं:</b> लाइव टाइमर, OMR पैलेट ग्रिड, तत्काल प्राप्तांक व 50% वाटरमार्क PDF\n\n"
                    f"👤 <b>संरक्षक:</b> {AUTHOR_NAME}\n"
                    f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                ),
                parse_mode=ParseMode.HTML
            )
        if os.path.exists(filename):
            os.remove(filename)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ पोर्टल बनाने में त्रुटि: {e}। कृपया पुनः प्रयास करें।")

@ensure_auth
async def interview_flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id

    daf = get_user_daf(user_id)
    if not daf or not daf[0]:
        await update.message.reply_text(
            f"🏛 <b>UPSC साक्षात्कार बोर्ड (Personality Test)</b>\n\n"
            f"नमस्ते <b>{user.first_name} जी</b>! बोर्ड कक्ष में प्रवेश से पहले हमें आपकी पृष्ठभूमि का संक्षिप्त विवरण चाहिए ताकि मूल्यांकन आपकी वास्तविक स्थिति के अनुसार हो सके।\n\n"
            "👉 <b>चरण 1/6:</b> कृपया अपना <b>पूरा नाम</b> लिखकर भेजें:",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        return DAF_NAME

    name, home_state, college, status, opt_sub, attempt = daf
    reply_kb = [["✅ इसी प्रोफाइल से साक्षात्कार दें"], ["✏️ प्रोफाइल अपडेट करें (Edit DAF)"]]
    await update.message.reply_text(
        f"🏛 <b>आपकी पूर्व दर्ज साक्षात्कार प्रोफाइल:</b>\n\n"
        f"👤 <b>नाम:</b> {name}\n"
        f"📍 <b>गृह राज्य:</b> {home_state}\n"
        f"🏫 <b>कॉलेज:</b> {college}\n"
        f"🎓 <b>स्थिति:</b> {status}\n"
        f"📚 <b>वैकल्पिक विषय:</b> {opt_sub}\n"
        f"🎯 <b>प्रयास संख्या:</b> {attempt}\n\n"
        "👉 कृपया विकल्प चुनें:",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_NAME

async def handle_daf_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip() if update.message.text else update.effective_user.first_name

    if txt == "✅ इसी प्रोफाइल से साक्षात्कार दें":
        reply_kb = [["⚡ 1 प्रश्न (क्विक स्थितिजन्य)"], ["🎯 3 प्रश्न (मानक बोर्ड)"], ["🏆 5 प्रश्न (गहन साक्षात्कार)"]]
        await update.message.reply_text(
            "👉 <b>आप कितने प्रश्नों का साक्षात्कार सेट देना चाहते हैं?</b>",
            reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
            parse_mode=ParseMode.HTML
        )
        return DAF_QCOUNT

    if txt == "✏️️ प्रोफाइल अपडेट करें (Edit DAF)":
        await update.message.reply_text("👉 <b>चरण 1/6:</b> अपना <b>पूरा नाम</b> लिखकर भेजें:", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return DAF_NAME

    context.user_data["daf_name"] = txt
    await update.message.reply_text("👉 <b>चरण 2/6:</b> अपना <b>गृह राज्य</b> दर्ज करें (उदा. राजस्थान, उत्तर प्रदेश):", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return DAF_STATE

async def handle_daf_state_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_state"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 3/6:</b> अपने <b>कॉलेज / विश्वविद्यालय</b> का नाम लिखें:", parse_mode=ParseMode.HTML)
    return DAF_COLLEGE

async def handle_daf_college_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_college"] = update.message.text.strip()
    reply_kb = [["🎓 स्नातक पूर्ण (Completed)"], ["⏳ अध्ययनरत (Running / Final Year)"]]
    await update.message.reply_text("👉 <b>चरण 4/6:</b> कॉलेज की वर्तमान स्थिति क्या है?", reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True), parse_mode=ParseMode.HTML)
    return DAF_STATUS

async def handle_daf_status_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_status"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 5/6:</b> अपना <b>वैकल्पिक विषय (Optional Subject)</b> लिखें (उदा. भूगोल, इतिहास):", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return DAF_OPTIONAL_STEP

async def handle_daf_optional_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_optional"] = update.message.text.strip()
    reply_kb = [["1st Attempt (पहला)"], ["2nd Attempt (दूसरा)"], ["3rd+ Attempt (तीसरा या अधिक)"]]
    await update.message.reply_text("👉 <b>चरण 6/6:</b> यह आपका कौन सा <b>प्रयास (Attempt)</b> है?", reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True), parse_mode=ParseMode.HTML)
    return DAF_ATTEMPT_STEP

async def handle_daf_attempt_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    attempt_txt = update.message.text.strip()

    name = context.user_data.get("daf_name", update.effective_user.first_name)
    state = context.user_data.get("daf_state", "राजस्थान")
    college = context.user_data.get("daf_college", "विश्वविद्यालय")
    status = context.user_data.get("daf_status", "पूर्ण")
    opt = context.user_data.get("daf_optional", "सामान्य अध्ययन")

    save_user_daf(user_id, name, state, college, status, opt, attempt_txt)

    reply_kb = [["⚡ 1 प्रश्न (क्विक स्थितिजन्य)"], ["🎯 3 प्रश्न (मानक बोर्ड)"], ["🏆 5 प्रश्न (गहन साक्षात्कार)"]]
    await update.message.reply_text(
        "✅ <b>आपकी DAF प्रोफाइल सुरक्षित कर ली गई है!</b>\n\n"
        "👉 <b>आप कितने प्रश्नों का साक्षात्कार सेट देना चाहते हैं?</b>",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_QCOUNT

async def handle_daf_qcount_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    txt = update.message.text.strip()
    cnt = 1
    if "3" in txt:
        cnt = 3
    elif "5" in txt:
        cnt = 5

    daf = get_user_daf(user_id)
    INTERVIEW_SESSION[user_id] = {"total": cnt, "current": 1, "daf": daf, "history": []}

    status_m = await update.message.reply_text("🏛 <b>बोर्ड कक्ष में स्वागत है।</b> प्रश्न तैयार किया जा रहा है...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return await ask_interview_question(update, context, user_id, status_m)

async def ask_interview_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, status_m = None) -> int:
    sess = INTERVIEW_SESSION.get(user_id)
    curr = sess["current"]
    tot = sess["total"]
    name, state, college, status, opt_sub, attempt = sess["daf"]

    prompt = f"""
आप UPSC साक्षात्कार बोर्ड के अध्यक्ष हैं।
उम्मीदवार विवरण:
- नाम: {name}
- गृह राज्य: {state}
- कॉलेज: {college} ({status})
- वैकल्पिक विषय: {opt_sub}
- प्रयास: {attempt}
- राउंड: {curr}/{tot} (कठिनाई स्तर: {curr * 2}/10)

सख्त निर्देश:
- सीधे '{name} जी' कहकर संबोधित करें।
- शुद्ध हिंदी में 3-4 पंक्तियों का गंभीर, प्रशासनिक स्थितिजन्य प्रश्न पूछें जिसमें निर्णय-क्षमता की परीक्षा हो।
- कोई अंग्रेजी शब्द या सिस्टम निर्देश न लिखें।
"""
    try:
        q_text = await asyncio.to_thread(call_gemini_safely, prompt)
        if status_m:
            try:
                await status_m.delete()
            except Exception:
                pass

        await update.effective_message.reply_text(
            f"🏛 <b>UPSC साक्षात्कार बोर्ड अध्यक्ष (प्रश्न {curr}/{tot}):</b>\n\n{q_text}\n\n"
            "👉 <b>कृपया अपना उत्तर वॉयस नोट (Voice Message) में रिकॉर्ड करके भेजें:</b>\n"
            "<i>(प्रक्रिया रोकने के लिए <code>/cancel</code> भेजें)</i>",
            parse_mode=ParseMode.HTML
        )

        # बोर्ड अध्यक्ष की गंभीर पुरुष (Male) आवाज भेजना
        asyncio.create_task(send_async_voice_question(update, context, q_text, curr, tot))

    except Exception as e:
        await update.effective_message.reply_text(f"❌ साक्षात्कार प्रश्न बनाने में समस्या: {e}")

    return WAITING_INTERVIEW_VOICE

async def send_async_voice_question(update, context, text, curr, tot):
    try:
        audio_bytes = await download_audio_stream(text)
        if audio_bytes:
            audio_io = io.BytesIO(audio_bytes)
            audio_io.name = f"Board_Question_{curr}.mp3"
            await context.bot.send_voice(
                chat_id=update.effective_chat.id,
                voice=audio_io,
                caption=f"🎙️ साक्षात्कार प्रश्न {curr}/{tot} (बोर्ड अध्यक्ष - पुरुष आवाज़) | {AUTHOR_NAME}"
            )
    except Exception as e:
        print(f"Async voice skip: {e}")

async def handle_interview_candidate_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    sess = INTERVIEW_SESSION.get(user_id)
    if not sess:
        await update.message.reply_text("सत्र समाप्त हो चुका है। पुनः <code>/interview</code> चलाएं।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    wait_m = await update.message.reply_text("🎧 बोर्ड आपके मौखिक उत्तर का विश्लेषण कर रहा है...", parse_mode=ParseMode.HTML)

    try:
        msg = update.message
        voice_obj = msg.voice or msg.audio
        f_obj = await voice_obj.get_file()
        f_bytes = await f_obj.download_as_bytearray()

        transcribed_text = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
        sess["history"].append({"round": sess["current"], "answer": transcribed_text})

        is_last = (sess["current"] >= sess["total"])
        name = sess["daf"][0]

        eval_prompt = f"""
उम्मीदवार {name} ने मौखिक उत्तर दिया है: "{transcribed_text}"
राउंड: {sess['current']}/{sess['total']}
कार्य:
उम्मीदवार को {name} जी कहकर संबोधित करते हुए 2-3 पंक्तियों में प्रशासनिक भाषा में संतुलित मौखिक फीडबैक दें। केवल शुद्ध हिंदी लिखें।
"""
        eval_resp = await asyncio.to_thread(call_gemini_safely, eval_prompt)
        await wait_m.delete()

        await update.message.reply_text(f"🏛 <b>बोर्ड का अवलोकन ({sess['current']}/{sess['total']}):</b>\n\n{eval_resp}", parse_mode=ParseMode.HTML)

        # बोर्ड का मौखिक पुरुष फीडबैक भेजना
        asyncio.create_task(send_async_voice_feedback(update, context, eval_resp))

        if not is_last:
            sess["current"] += 1
            INTERVIEW_SESSION[user_id] = sess
            await asyncio.sleep(1)
            status_m = await update.message.reply_text("⏳ अगले प्रश्न की तैयारी जारी है...")
            return await ask_interview_question(update, context, user_id, status_m)
        else:
            reply_kb = [["➕ 1 और स्थितिजन्य प्रश्न दें"], ["📊 संपूर्ण परिणाम व रिपोर्ट कार्ड देखें"]]
            await update.message.reply_text(
                "🎯 <b>निर्धारित साक्षात्कार राउंड पूर्ण हुआ!</b>\n\n"
                "क्या आप अपनी तैयारी को और परखने के लिए 1 अतिरिक्त प्रश्न देना चाहते हैं या अंतिम रिपोर्ट देखना चाहते हैं?",
                reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
                parse_mode=ParseMode.HTML
            )
            return WAITING_INTERVIEW_DECISION

    except Exception as e:
        await wait_m.edit_text(f"❌ वॉयस प्रोसेसिंग में त्रुटि: {e}। कृपया पुनः वॉयस भेजें।")
        return WAITING_INTERVIEW_VOICE

async def send_async_voice_feedback(update, context, text):
    try:
        audio_bytes = await download_audio_stream(text[:350])
        if audio_bytes:
            audio_io = io.BytesIO(audio_bytes)
            audio_io.name = "Board_Feedback.mp3"
            await context.bot.send_voice(
                chat_id=update.effective_chat.id,
                voice=audio_io,
                caption=f"🎙️ बोर्ड अवलोकन एवं फीडबैक (अध्यक्ष) | {AUTHOR_NAME}"
            )
    except Exception as e:
        print(f"Async feedback skip: {e}")

async def handle_interview_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    txt = update.message.text.strip()
    sess = INTERVIEW_SESSION.get(user_id)

    if not sess:
        await update.message.reply_text("सत्र समाप्त। पुनः <code>/interview</code> करें।", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if "1 और" in txt:
        sess["total"] += 1
        sess["current"] += 1
        INTERVIEW_SESSION[user_id] = sess
        status_m = await update.message.reply_text("अगला उन्नत स्तर का प्रश्न तैयार हो रहा है...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return await ask_interview_question(update, context, user_id, status_m)

    wait_m = await update.message.reply_text("⏳ बोर्ड मेंबर अंतिम मूल्यांकन पत्रक तैयार कर रहे हैं...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    name = sess["daf"][0]
    final_prompt = f"""
उम्मीदवार {name} का UPSC साक्षात्कार पूर्ण हो चुका है। कुल {len(sess['history'])} प्रश्नों के उत्तर दिए गए।
एक आधिकारिक, उच्च-स्तरीय यूपीएससी साक्षात्कार मूल्यांकन पत्रक तैयार करें:
1. 🏆 प्राप्तांक: (275 में से अंक)
2. 🌟 मुख्य प्रशासनिक खूबियाँ (Strengths)
3. ⚠️ सुधार योग्य क्षेत्र (Areas of Improvement)
4. 🚀 बोर्ड की अंतिम अनुशंसा (Final Board Recommendation)
केवल शुद्ध हिंदी में लिखें।
"""
    try:
        final_report = await asyncio.to_thread(call_gemini_safely, final_prompt)
        await wait_m.delete()
        await update.message.reply_text(f"📜 <b>UPSC साक्षात्कार अंतिम परिणाम पत्रक</b>\n\n{final_report}\n\n👤 <b>बोर्ड संरक्षक:</b> {AUTHOR_NAME}", parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_m.edit_text(f"त्रुटि: {e}")

    INTERVIEW_SESSION.pop(user_id, None)
    return ConversationHandler.END

# ================= UPSC MAINS SPECIAL (PYQs 2013-2026 WITH BOLD STYLING) =================
@ensure_auth
async def mains_special_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📜 विगत वर्षों के प्रश्न (PYQs 2013-2026 Complete)", callback_data="mq_type_pyq")],
        [InlineKeyboardButton("✨ नए संभावित मॉडल प्रश्न (New Expected)", callback_data="mq_type_new")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("✍️ <b>UPSC मुख्य परीक्षा (Mains) अभ्यास:</b>\nआप पुराने सभी प्रश्न देखना चाहते हैं या नए संभावित मॉडल प्रश्न?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_mains_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_type = query.data.replace("mq_type_", "")
    user_id = query.from_user.id
    MAINS_SELECTIONS[user_id] = {"q_type": q_type}

    keyboard = [
        [InlineKeyboardButton("🏛 GS 1 (इतिहास, भूगोल, समाज)", callback_data="mq_gs_1")],
        [InlineKeyboardButton("⚖ GS 2 (राजव्यवस्था, शासन, IR)", callback_data="mq_gs_2")],
        [InlineKeyboardButton("💰 GS 3 (अर्थव्यवस्था, पर्यावरण, सुरक्षा)", callback_data="mq_gs_3")],
        [InlineKeyboardButton("🧭 GS 4 (नीतिशास्त्र, केस स्टडी)", callback_data="mq_gs_4")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="mains_back_root")]
    ]
    await query.message.edit_text("🎯 <b>विषय / GS पेपर का चयन करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_mains_gs_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "mains_back_root":
        await mains_special_cmd(update, context)
        return

    gs_num = data.replace("mq_gs_", "")
    user_id = query.from_user.id
    MAINS_SELECTIONS[user_id]["gs"] = gs_num
    is_pyq = (MAINS_SELECTIONS[user_id].get("q_type") == "pyq")

    keyboard = [
        [InlineKeyboardButton("⚡ 1 प्रश्न", callback_data="mq_cnt_1")],
        [InlineKeyboardButton("🎯 3 प्रश्न", callback_data="mq_cnt_3")],
        [InlineKeyboardButton("🏆 5 प्रश्न", callback_data="mq_cnt_5")]
    ]
    if is_pyq:
        keyboard.append([InlineKeyboardButton("📚 2013-2026 तक के सभी मुख्य PYQs (Complete Set)", callback_data="mq_cnt_all")])
    else:
        keyboard.append([InlineKeyboardButton("📚 10 प्रश्नों का संभावित मेगा सेट", callback_data="mq_cnt_10")])

    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="mq_type_" + MAINS_SELECTIONS[user_id].get("q_type", "new"))])
    await query.message.edit_text(f"📝 <b>GS {gs_num} के कितने प्रश्नों का अभ्यास करना चाहते हैं?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_mains_cnt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    cnt_raw = data.replace("mq_cnt_", "")
    cnt_desc = "2013 से 2026 तक के सभी मुख्य PYQs" if cnt_raw == "all" else f"{cnt_raw} प्रश्न"
    
    sel = MAINS_SELECTIONS.get(user_id, {"q_type": "new", "gs": "2"})
    is_pyq = (sel.get("q_type") == "pyq")
    gs_paper = f"सामान्य अध्ययन - {sel.get('gs')}"

    wait_m = await query.message.reply_text(f"⏳ <b>{gs_paper}</b> के {cnt_desc} उत्तर-लेखन मॉड्यूल तैयार हो रहे हैं...", parse_mode=ParseMode.HTML)

    tag_instruction = "2013 से 2026 तक इस विषय में पूछे गए प्रश्नों को शामिल करें। प्रत्येक प्रश्न पर उसका वर्ष, पेपर और अंक स्पष्ट लिखें (उदा. [UPSC CSE 2023 / GS " + sel.get('gs') + " / 15 अंक])." if is_pyq else "प्रत्येक प्रश्न पर लिखें: [मॉडल प्रश्न / GS " + sel.get('gs') + " / 15 अंक]."

    prompt = f"""
आप UPSC मुख्य परीक्षा के शीर्ष विशेषज्ञ हैं।
विषय: {gs_paper} के {cnt_desc} उत्तर-लेखन मॉड्यूल तैयार करें।
{tag_instruction}

सख्त नियम:
1. प्रत्येक प्रश्न को स्पष्ट शीर्षक में रखें।
2. विस्तृत उत्तर-लेखन ढांचा दें:
   - प्रश्न का पूरा विवरण व [वर्ष / पेपर टैग]
   - 📌 भूमिका (Introduction)
   - 📊 मुख्य विश्लेषणात्मक आयाम (Body): 3 स्पष्ट उप-शीर्षक और उदाहरण
   - 🚀 आगे की राह (Way Forward)
   - ⚖️ संतुलित प्रशासनिक निष्कर्ष
भाषा केवल शुद्ध हिंदी रखें। मार्कडाउन स्टार्स का प्रयोग न करें।
"""
    try:
        resp = await asyncio.to_thread(call_gemini_safely, prompt)
        topic = f"UPSC Mains Module — GS {sel.get('gs')} ({cnt_desc})"
        filename = f"UPSC_Mains_GS{sel.get('gs')}_{cnt_raw}.html"
        html_out = build_standalone_master_html(topic, resp)

        with open(filename, "wb") as f:
            f.write(html_out.encode("utf-8"))

        with open(filename, "rb") as send_doc:
            await context.bot.send_document(
                chat_id=user_id,
                document=send_doc,
                filename=filename,
                caption=f"📝 <b>UPSC मुख्य परीक्षा संग्रह:</b> <code>{topic}</code>\n👤 <b>संचालक:</b> {AUTHOR_NAME}\n📢 <b>ग्रुप:</b> {CHANNEL_NAME}",
                parse_mode=ParseMode.HTML
            )
        if os.path.exists(filename):
            os.remove(filename)
        await wait_m.delete()
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

# ================= ADVANCED CHECK ANSWER WITH PYQ / CUSTOM MARKS SELECTION =================
@ensure_auth
async def check_answer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("📜 विगत वर्ष का प्रश्न (PYQ 2013-2026)", callback_data="ca_type_pyq")],
        [InlineKeyboardButton("✍️ नया / मॉडल प्रश्न (New Expected)", callback_data="ca_type_custom")]
    ]
    await update.message.reply_text(
        "📝 <b>UPSC मुख्य परीक्षा उत्तर पुस्तिका मूल्यांकन</b>\n\n"
        "👉 <b>चरण 1/3:</b> आप किस प्रकार का प्रश्न जांच करवाना चाहते हैं?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return CA_CHOOSE_TYPE

async def handle_ca_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    is_pyq = (data == "ca_type_pyq")
    CHECK_ANSWER_CACHE[user_id] = {"is_pyq": is_pyq}

    if is_pyq:
        await query.message.edit_text(
            "📜 <b>विगत वर्ष का प्रश्न (PYQ):</b>\n\n"
            "कृपया अपना <b>PYQ प्रश्न</b> लिखकर या वॉयस मैसेज में भेजें।\n"
            "<i>(AI परीक्षक स्वतः पहचान लेगा कि यह किस वर्ष और कितने अंक [10 या 15 अंक] का प्रश्न था)</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await query.message.edit_text(
            "✍️ <b>नया / मॉडल प्रश्न:</b>\n\n"
            "कृपया अपना <b>प्रश्न</b> लिखकर या वॉयस मैसेज में भेजें:",
            parse_mode=ParseMode.HTML
        )
    return CA_QUESTION_TEXT

async def handle_ca_question_text_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message

    if msg.text and msg.text.strip().lower() == "/cancel":
        await msg.reply_text("मूल्यांकन प्रक्रिया रद्द कर दी गई।")
        return ConversationHandler.END

    q_content = ""
    if msg.text:
        q_content = msg.text.strip()
    elif msg.voice or msg.audio:
        wait_m = await msg.reply_text("🎧 प्रश्न का ऑडियो सुना जा रहा है...")
        try:
            f_obj = await (msg.voice or msg.audio).get_file()
            f_bytes = await f_obj.download_as_bytearray()
            q_content = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ ऑडियो पढ़ने में त्रुटि: {e}। कृपया टेक्स्ट में लिखें।")
            return CA_QUESTION_TEXT
    elif msg.photo:
        wait_m = await msg.reply_text("🖼️ प्रश्न की फ़ोटो पढ़ी जा रही है...")
        try:
            f_obj = await msg.photo[-1].get_file()
            f_bytes = await f_obj.download_as_bytearray()
            q_content = await asyncio.to_thread(call_gemini_multimodal_inline, "इस फ़ोटो में लिखे UPSC प्रश्न को निकालें।", bytes(f_bytes), "image/jpeg")
            await wait_m.delete()
        except Exception:
            q_content = "संलग्न फ़ोटो में दिया गया प्रश्न"

    non_upsc_patterns = [
        r"मेरा नाम", r"तुम्हारा नाम", r"आपका नाम", r"तुम कौन", r"आप कौन",
        r"हेलो", r"हाय", r"hello", r"hi", r"hey", r"कैसे हो", r"क्या कर रहे",
        r"क्या कर सकता", r"शायरी", r"मजाक", r"मौसम", r"गाना", r"लव", r"प्यार"
    ]
    if any(re.search(pat, q_content, re.IGNORECASE) for pat in non_upsc_patterns) or len(q_content) < 15:
        await msg.reply_text(
            "⚠️ <b>अमान्य प्रश्न:</b> आपने सामान्य बातचीत या गैर-UPSC वाक्य भेजा है।\n\n"
            "कृपया <b>UPSC मुख्य परीक्षा (GS 1, 2, 3, 4, निबंध या वैकल्पिक)</b> का वास्तविक प्रश्न भेजें।",
            parse_mode=ParseMode.HTML
        )
        return CA_QUESTION_TEXT

    sess = CHECK_ANSWER_CACHE.get(user_id, {"is_pyq": False})
    sess["question"] = q_content
    CHECK_ANSWER_CACHE[user_id] = sess

    if sess.get("is_pyq"):
        await msg.reply_text(
            f"✅ <b>PYQ प्रश्न दर्ज हुआ:</b>\n<i>\"{q_content[:180]}...\"</i>\n\n"
            "👉 <b>चरण 3/3:</b> अब अपनी लिखी हुई <b>उत्तर पुस्तिका की साफ़ फ़ोटो या PDF</b> भेजें:",
            parse_mode=ParseMode.HTML
        )
        return CA_ANSWER_COPY
    else:
        keyboard = [
            [InlineKeyboardButton("🔟 10 अंक (150 शब्द)", callback_data="camarks_10")],
            [InlineKeyboardButton("1️⃣5️⃣ 15 अंक (250 शब्द)", callback_data="camarks_15")],
            [InlineKeyboardButton("🤖 AI स्वतः अनुमान लगाए (Auto)", callback_data="camarks_auto")]
        ]
        await msg.reply_text(
            f"✅ <b>प्रश्न दर्ज हुआ:</b>\n<i>\"{q_content[:180]}...\"</i>\n\n"
            "👉 <b>चरण 2/3:</b> यह प्रश्न कितने अंक का माना जाए?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return CA_CUSTOM_MARKS

async def handle_ca_marks_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    marks_str = "10 अंक" if data == "camarks_10" else ("15 अंक" if data == "camarks_15" else "स्वतः निर्धारित")
    sess = CHECK_ANSWER_CACHE.get(user_id, {})
    sess["marks"] = marks_str
    CHECK_ANSWER_CACHE[user_id] = sess

    await query.message.edit_text(
        f"🎯 <b>मूल्यांकन मानदंड:</b> {marks_str}\n\n"
        "👉 <b>चरण 3/3:</b> अब अपनी लिखी हुई <b>उत्तर पुस्तिका की साफ़ फ़ोटो या PDF</b> भेजें:",
        parse_mode=ParseMode.HTML
    )
    return CA_ANSWER_COPY

async def handle_ca_answer_copy_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message
    sess = CHECK_ANSWER_CACHE.get(user_id, {})
    q_text = sess.get("question", "UPSC मुख्य परीक्षा प्रश्न")
    is_pyq = sess.get("is_pyq", False)
    target_marks = sess.get("marks", "10/15 अंक")

    wait_m = await msg.reply_text("🔍 उत्तर पुस्तिका का UPSC परीक्षक द्वारा गहन मूल्यांकन जारी है...", parse_mode=ParseMode.HTML)

    if is_pyq:
        marks_instruction = "यह UPSC विगत वर्षों (2013-2026) का प्रश्न है। प्रश्न को पहचानकर उसके वास्तविक वर्ष और आधिकारिक अंकों (10 अंक या 15 अंक) के आधार पर ही सटीक अंक दें।"
    else:
        marks_instruction = f"उम्मीदवार द्वारा निर्धारित अंक मानदंड: {target_marks}। इसी आधार पर अंक प्रदान करें।"

    prompt = f"""
आप संघ लोक सेवा आयोग (UPSC CSE Mains) के वरिष्ठ परीक्षक (Copy Evaluator) हैं।
प्रश्न: "{q_text}"
{marks_instruction}

प्रस्तुत उत्तर पुस्तिका का निष्पक्ष, गहन और मानक मूल्यांकन करें।

प्रारूप:
1. 📊 प्राप्तांक (Marks Awarded): (उदा. 6/10 या 9.5/15 अंक)
2. 🌟 सकारात्मक पक्ष (Strengths): (भूमिका, तार्किकता, मुख्य बिंदु)
3. ⚠️ संरचनात्मक कमियाँ (Areas of Improvement): (डेटा, आरेख, अनुच्छेदों की कमी)
4. 🚀 परीक्षक की मूल्य संवर्धन सलाह (Value Addition): (आगे की राह व निष्कर्ष को बेहतर बनाने के सुझाव)

केवल और केवल शुद्ध एवं गरिमापूर्ण हिंदी में उत्तर दें।
"""
    m_type = "application/pdf" if (msg.document and msg.document.file_name.lower().endswith('.pdf')) else "image/jpeg"

    try:
        doc_obj = msg.document or (msg.photo[-1] if msg.photo else None)
        f_obj = await doc_obj.get_file()
        f_bytes = await f_obj.download_as_bytearray()

        eval_result = await asyncio.to_thread(call_gemini_multimodal_inline, prompt, bytes(f_bytes), m_type)
        clean_eval = clean_all_markdown_and_fix_content(eval_result)
        await wait_m.delete()

        if len(clean_eval) > 3800:
            for p in [clean_eval[i:i+3800] for i in range(0, len(clean_eval), 3800)]:
                await msg.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text(clean_eval, parse_mode=ParseMode.HTML)

    except Exception as e:
        await wait_m.edit_text(f"❌ मूल्यांकन में त्रुटि: {e}। कृपया साफ़ फ़ोटो या PDF भेजें।")

    CHECK_ANSWER_CACHE.pop(user_id, None)
    return ConversationHandler.END

# ================= CONTINUOUS ASK MENTORSHIP SESSION (/ask) =================
@ensure_auth
async def start_ask_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🎓 <b>UPSC 1-on-1 मेंटरशिप सत्र सक्रिय हो गया है!</b>\n\n"
        "आप UPSC सिविल सेवा परीक्षा (GS 1-4, करेंट अफेयर्स, वैकल्पिक विषय व निबंध) से जुड़ा कोई भी सवाल लगातार पूछते रह सकते हैं।\n\n"
        "👉 <i>सत्र समाप्त करने के लिए कभी भी <code>/cancel</code> या <code>/stop</code> भेजें।</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_ASK_SESSION

async def handle_ask_continuous_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_query = update.message.text.strip()

    if user_query.lower() in ["/cancel", "/stop", "/exit", "cancel", "stop", "exit", "रद्द", "बंद"]:
        await update.message.reply_text("✅ <b>मेंटरशिप सत्र समाप्त हुआ।</b> अध्ययन जारी रखें और शुभकामनाएं!", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    blocked_non_upsc = [
        r"मेरा नाम", r"तुम्हारा नाम", r"आपका नाम", r"तुम कौन", r"आप कौन",
        r"हेलो", r"हाय", r"hello", r"hi", r"hey", r"कैसे हो", r"क्या कर रहे",
        r"शायरी", r"मजाक", r"मौसम", r"गाना", r"लव", r"प्यार", r"गर्लफ्रेंड",
        r"बॉयफ्रेंड", r"joke", r"time pass"
    ]
    if any(re.search(pat, user_query, re.IGNORECASE) for pat in blocked_non_upsc) or len(user_query) < 5:
        await update.message.reply_text(
            "⚠️ <b>अमान्य प्रश्न:</b> इस संबंध में हम कोई जानकारी नहीं रखते हैं।\n\n"
            "यह डेस्क केवल <b>संघ लोक सेवा आयोग (UPSC CSE)</b> पाठ्यक्रम के गंभीर अकादमिक विमर्श हेतु समर्पित है। कृपया परीक्षा संबंधी विषय ही पूछें।",
            parse_mode=ParseMode.HTML
        )
        return WAITING_ASK_SESSION

    wait_msg = await update.message.reply_text("🤔 UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")
    try:
        prompt = f"""
आप UPSC मेंटर हैं। निम्नलिखित विषय का बिंदुवार, सटीक एवं संतुलित प्रशासनिक विश्लेषण दें:
विषय: '{user_query}'
सख्त नियम: मार्कडाउन स्टार्स का प्रयोग न करें। भाषा केवल शुद्ध हिंदी रखें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = clean_all_markdown_and_fix_content(reply_text)

        if len(clean_reply) > 3800:
            await wait_msg.delete()
            for p in [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]:
                await update.message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await wait_msg.edit_text(clean_reply, parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ उत्तर संकलित करने में समस्या: {e}")
        
    return WAITING_ASK_SESSION

# ================= TRENDING RADAR =================
@ensure_auth
async def trending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚡ आज के मुख्य ट्रेंडिंग मुद्दे (Daily)", callback_data="trtype_daily")],
        [InlineKeyboardButton("📁 इस महीने के शीर्ष ट्रेंडिंग मुद्दे (Monthly)", callback_data="trtype_monthly")],
        [InlineKeyboardButton("📚 वर्ष भर के सबसे बड़े ट्रेंडिंग मुद्दे (Yearly)", callback_data="trtype_yearly")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🧭 <b>UPSC TRENDING RADAR: आप किस समयावधि के ट्रेंडिंग मुद्दे देखना चाहते हैं?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_trending_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "tr_back_root":
        await trending_cmd(update, context)
        return

    user_id = query.from_user.id
    tr_type = data.replace("trtype_", "")
    
    today = get_ist_now().strftime("%d %B %Y")
    current_month = get_ist_now().strftime("%B %Y")
    current_year = get_ist_now().strftime("%Y")

    if tr_type == "daily":
        scope_str = f"आज ({today})"
        prompt = f"आज {today} के संदर्भ में UPSC CSE परीक्षा हेतु 9 सबसे महत्वपूर्ण ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"
    elif tr_type == "monthly":
        scope_str = f"माह ({current_month})"
        prompt = f"माह {current_month} के 9 सबसे महत्वपूर्ण नीतिगत, अंतर्राष्ट्रीय एवं पर्यावरणीय ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"
    else:
        scope_str = f"वर्ष {current_year}"
        prompt = f"वर्ष {current_year} के 9 सबसे बड़े राष्ट्रीय व वैश्विक ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"

    wait_m = await query.message.reply_text(f"🛰 <b>{scope_str}</b> के ट्रेंडिंग मुद्दों का रडार संकलन जारी...", parse_mode=ParseMode.HTML)
    try:
        raw_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_lines = [re.sub(r'^\*+\s*', '', l.strip()) for l in raw_text.split('\n') if l.strip() and len(l.strip()) > 5 and not l.startswith('#')]
        
        TRENDING_CACHE[user_id] = clean_lines

        p_text = f"🧭 <b>UPSC TRENDING RADAR — {scope_str} (पेज 1/3)</b>\n\n" + "\n\n".join(clean_lines[:3])
        p_text += "\n\n━━━━━━━━━━━━━━━━━━━━\n👉 <b>विकल्प:</b>\n• किसी मुद्दे के पूर्ण नोट्स हेतु नंबर भेजें (उदा. <code>1, 2</code>)\n• सभी मुद्दों के 360° नोट्स हेतु लिखें: <code>all</code>"

        keyboard = [
            [InlineKeyboardButton("अगला पेज (पेज 2/3) ▶", callback_data="trpage_1")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="tr_back_root")]
        ]
        await wait_m.edit_text(p_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}")

async def handle_trending_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    target_page = int(query.data.replace("trpage_", ""))
    
    lines = TRENDING_CACHE.get(user_id, [])
    if not lines:
        await query.message.reply_text("⚠️ सत्र समाप्त हो गया है। पुनः <code>/trending</code> चलाएं।", parse_mode=ParseMode.HTML)
        return

    start_idx = target_page * 3
    end_idx = start_idx + 3
    sub_lines = lines[start_idx:end_idx]

    p_text = f"🧭 <b>UPSC TRENDING RADAR (पेज {target_page + 1}/3)</b>\n\n" + "\n\n".join(sub_lines)
    p_text += "\n\n━━━━━━━━━━━━━━━━━━━━\n👉 <b>विकल्प:</b>\n• किसी मुद्दे के पूर्ण नोट्स हेतु नंबर भेजें (उदा. <code>1, 2</code>)\n• सभी मुद्दों के 360° नोट्स हेतु लिखें: <code>all</code>"

    nav_btns = []
    if target_page > 0:
        nav_btns.append(InlineKeyboardButton(f"◀️ पेज {target_page}/3", callback_data=f"trpage_{target_page - 1}"))
    if end_idx < len(lines):
        nav_btns.append(InlineKeyboardButton(f"पेज {target_page + 2}/3 ▶️", callback_data=f"trpage_{target_page + 1}"))

    keyboard = [nav_btns] if nav_btns else []
    keyboard.append([InlineKeyboardButton("🔙 मुख्य मेनू (Back)", callback_data="tr_back_root")])

    await query.message.edit_text(p_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ================= MONTHLY, YEARLY, WEEKLY =================
@ensure_auth
async def monthly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    months = ["October 2026", "September 2026", "August 2026", "July 2026", "June 2026", "May 2026"]
    keyboard = [[InlineKeyboardButton(f"📁 {m} संपूर्ण मासिक डाइजेस्ट", callback_data=f"genmonth_{m}")] for m in months]
    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")] )
    await update.message.reply_text("📁 <b>जिस महीने का संपूर्ण UPSC मंथली कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    years = ["2026", "2025", "2024"]
    keyboard = [[InlineKeyboardButton(f"📚 वर्ष {y} वार्षिक महा-संकलन (PT-365)", callback_data=f"genyear_{y}")] for y in years]
    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")] )
    await update.message.reply_text("🏛️ <b>जिस वर्ष का संपूर्ण UPSC वार्षिक कंपाइलेशन (PT-365 Style) चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = get_ist_now()
    days_since_monday = today.weekday()
    start_of_current_week = today - timedelta(days=days_since_monday)
    current_week_str = f"{start_of_current_week.strftime('%d %b')} से {today.strftime('%d %b %Y')}"

    keyboard = [
        [InlineKeyboardButton(f"🗓 चालू सप्ताह ({current_week_str}) - आज तक", callback_data=f"genweek_current_{today.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🗓 <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ================= DYNAMIC GENERATION PROCESSOR =================
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
            topic, html_content = arch_data
            filename = f"UPSC_Notes_{target_date.replace('-', '')}.html"
        else:
            wait_m = await context.bot.send_message(
                chat_id=user_id, 
                text=f"🏛 <b>UPSC STUDY DESK</b>\n\n📅 <b>दिनांक:</b> <code>{target_date}</code>\n🔄 The Hindu, PIB, Vision IAS व Drishti से 360° संकलन जारी...",
                parse_mode=ParseMode.HTML
            )
            prompt = f"""
तारीख: "{target_date}" के लिए संपूर्ण, 360° और अत्यंत विस्तृत UPSC समसामयिक महा-संकलन तैयार करें।
अनिवार्य स्रोत: The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS.
नियम:
1. सभी GS-1 से GS-4 के मुख्य घटनाक्रमों का समग्र विश्लेषण दें।
2. सभी तालिकाओं को केवल शुद्ध HTML (<div class="table-box"><table>...</table></div>) में लिखें।
3. मैपिंग सेक्शन में स्थान का नाम स्पष्ट लिखें।
4. अंत में 5 मानक अभ्यास MCQs जोड़ें। केवल शुद्ध हिंदी भाषा का प्रयोग करें।
"""
            try:
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                topic = f"दैनिक समसामयिक महा-संकलन — {target_date}"
                filename = f"UPSC_Notes_{target_date.replace('-', '')}.html"
                html_content = build_standalone_master_html(topic, ai_text, date_str=target_date)
                save_to_archive("daily", topic, html_content, target_date)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}")
                return

    elif data.startswith("genmonth_"):
        m_name = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"📁 <b>{m_name}</b> का संपूर्ण विस्तृत मासिक कंपाइलेशन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"माह: '{m_name}' का सम्पूर्ण और अत्यंत विस्तृत UPSC Monthly Digest तैयार करें। GS 1-4, चर्चित स्थल एवं अभ्यास प्रश्नों सहित केवल शुद्ध हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Monthly Digest — {m_name}"
            filename = f"UPSC_Monthly_{m_name.replace(' ', '_')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=m_name)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
            return

    elif data.startswith("genyear_"):
        y_name = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ वर्ष <b>{y_name}</b> का संपूर्ण वार्षिक महा-संकलन (PT-365 Style) तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"वर्ष {y_name} का UPSC हेतु अत्यंत विस्तृत और संपूर्ण Annual Compendium (PT-365 Style) तैयार करें। केवल हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Annual Compendium — {y_name}"
            filename = f"UPSC_Annual_{y_name}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=y_name)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
            return

    elif data.startswith("genweek_"):
        w_date = data.split("_")[2]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ साप्ताहिक संकलन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"सप्ताह के महत्वपूर्ण UPSC घटनाक्रमों का संपूर्ण विस्तृत रिवीजन तैयार करें। केवल हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Weekly Revision — {w_date}"
            filename = f"UPSC_Weekly_{w_date.replace('-', '')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=w_date)
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
                f"📰 <b>अधिकृत स्रोत:</b> The Hindu | Indian Express | PIB | Yojana | Vision IAS | Drishti IAS\n"
                f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
            ),
            parse_mode=ParseMode.HTML,
        )

    if os.path.exists(filename):
        os.remove(filename)

# ================= TEXT / NUMBER / 'ALL' TRENDING HANDLER =================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)
    user_input = msg.text.strip().lower()
    today = get_ist_now().strftime("%d %B %Y")

    cached_list = TRENDING_CACHE.get(user_id, [])

    if user_input == "all" and cached_list:
        raw_trend = "\n".join(cached_list)
        wait_m = await msg.reply_text("⏳ <b>सभी ट्रेंडिंग मुद्दों</b> के विस्तृत 360° नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
        prompt = f"नीचे दिए गए सभी ट्रेंडिंग मुद्दों पर UPSC स्तर के गहन और 360° संपूर्ण नोट्स तैयार करें:\n{raw_trend}\nकेवल शुद्ध हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Trending Radar All Topics — {today}"
            filename = f"UPSC_Trending_Radar_{get_ist_now().strftime('%Y%m%d')}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=today, is_trending=True)
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(filename, "rb") as send_doc:
                await msg.reply_document(
                    document=send_doc,
                    filename=filename,
                    caption=(
                        f"📄 <b>ट्रेंडिंग संपूर्ण संकलन:</b> <code>{today}</code>\n"
                        f"📰 <b>स्रोत:</b> The Hindu | Indian Express | PIB | Vision IAS\n"
                        f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                        f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
        return

    if re.match(r'^(\d+)(\s*,\s*\d+)*$', user_input) and cached_list:
        nums = [n.strip() for n in user_input.split(',')]
        wait_m = await msg.reply_text(f"⏳ चुने गए ट्रेंडिंग मुद्दे ({', '.join(nums)}) का 360° विस्तृत विश्लेषण तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        raw_trend = "\n".join(cached_list)
        prompt = f"सूची में से क्रमांक {', '.join(nums)} पर मौजूद मुद्दों का UPSC हेतु 360° विश्लेषण तैयार करें:\n{raw_trend}\nकेवल हिंदी में लिखें।"
        try:
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Trending Topics {', '.join(nums)} — {today}"
            filename = f"UPSC_Trending_Selected_{get_ist_now().strftime('%Y%m%d')}_{'_'.join(nums)}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=today, is_trending=True)
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(filename, "rb") as send_doc:
                await msg.reply_document(
                    document=send_doc,
                    filename=filename,
                    caption=(
                        f"📄 <b>ट्रेंडिंग चयनित मुद्दे:</b> {', '.join(nums)} ({today})\n"
                        f"📰 <b>स्रोत:</b> The Hindu | Indian Express | PIB\n"
                        f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                        f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            if os.path.exists(filename):
                os.remove(filename)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
        return

# ================= DIRECT PDF TO UPSC 360° HTML =================
async def handle_direct_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = msg.document
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username, update.effective_user.first_name)

    if not is_authorized(user_id):
        await msg.reply_text("⛔ <b>एक्सेस अस्वीकृत:</b> PDF प्रोसेसिंग केवल अधिकृत छात्रों के लिए है। <code>/owner</code> पर संपर्क करें।", parse_mode=ParseMode.HTML)
        return

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        return

    wait_m = await msg.reply_text("📥 PDF सामग्री निकाली जा रही है व UPSC 360° HTML नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
    try:
        f_obj = await doc.get_file()
        f_bytes = await f_obj.download_as_bytearray()
        pdf_io = io.BytesIO(f_bytes)
        reader = PdfReader(pdf_io)
        pdf_text = ""
        for page in reader.pages[:18]:
            t = page.extract_text()
            if t:
                pdf_text += t + "\n"

        clean_title = doc.file_name.replace(".pdf", "")[:35]
        prompt = f"नीचे दी गई PDF सामग्री का UPSC सिविल सेवा स्तर पर 360° अध्ययन नोट्स शुद्ध HTML सारणी व मेन्स फ्रेमवर्क सहित तैयार करें:\n{pdf_text[:4500]}\nकेवल हिंदी भाषा का प्रयोग करें।"
        ai_notes = await asyncio.to_thread(call_gemini_safely, prompt)
        html_out = build_standalone_master_html(clean_title, ai_notes)

        out_fname = f"UPSC_{re.sub(r'[^a-zA-Z0-9]', '_', clean_title)[:20]}.html"
        with open(out_fname, "wb") as f:
            f.write(html_out.encode("utf-8"))

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
        await wait_m.edit_text(f"❌ PDF प्रोसेसिंग में त्रुटि: {e}")

# ================= BROADCAST SYSTEM WITH AUTO-PIN =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END

    await update.message.reply_text(
        f"📢 <b>ब्रॉडकास्ट कंट्रोल रूम ({AUTHOR_NAME}):</b>\n\n"
        "सभी छात्रों को भेजा जाने वाला संदेश, इमेज या पीडीएफ भेजें:\n"
        "<i>(रद्द करने के लिए <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_BROADCAST_MSG

async def execute_broadcast_step1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return ConversationHandler.END

    b_msg = update.message
    all_uids = get_all_user_ids()
    status_m = await update.message.reply_text(f"⏳ ब्रॉडकास्ट भेजा जा रहा है (कुल: {len(all_uids)} छात्र)...")

    succ = 0
    sent_map = {}
    for uid in all_uids:
        try:
            sent_obj = await context.bot.copy_message(chat_id=uid, from_chat_id=admin_id, message_id=b_msg.message_id)
            sent_map[uid] = sent_obj.message_id
            succ += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    LAST_BROADCAST_DATA[admin_id] = sent_map
    await status_m.delete()

    keyboard = [
        [InlineKeyboardButton("📌 हाँ, सभी चैट में पिन करें", callback_data="pin_broadcast_yes")],
        [InlineKeyboardButton("❌ नहीं, सामान्य रहने दें", callback_data="pin_broadcast_no")]
    ]
    await update.message.reply_text(
        f"✅ ब्रॉडकास्ट सफल: <b>{succ} / {len(all_uids)}</b> छात्रों को संदेश प्राप्त हुआ।\n\n"
        "👉 <b>क्या आप इस संदेश को सभी छात्रों के चैट में पिन (Pin) करना चाहते हैं?</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def handle_broadcast_pin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id
    data = query.data

    if data == "pin_broadcast_yes":
        sent_map = LAST_BROADCAST_DATA.get(admin_id, {})
        pinned_cnt = 0
        for uid, mid in sent_map.items():
            try:
                await context.bot.pin_chat_message(chat_id=uid, message_id=mid, disable_notification=True)
                pinned_cnt += 1
                await asyncio.sleep(0.04)
            except Exception:
                pass
        await query.message.edit_text(f"📌 <b>सफल:</b> संदेश को कुल <b>{pinned_cnt}</b> छात्रों के चैट में पिन कर दिया गया है।", parse_mode=ParseMode.HTML)
    else:
        await query.message.edit_text("👌 ठीक है, संदेश को पिन नहीं किया गया।", parse_mode=ParseMode.HTML)

    LAST_BROADCAST_DATA.pop(admin_id, None)

# ================= ADMIN USER MANAGEMENT & /info COMMAND =================
async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("💡 उपयोग: <code>/adduser &lt;user_id&gt; &lt;दिन&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        t_uid = int(context.args[0])
        days = int(context.args[1])
        add_vip_user(t_uid, days)
        user_link = f'<a href="tg://user?id={t_uid}">{t_uid}</a>'
        await update.message.reply_text(f"✅ छात्र {user_link} को <b>{days} दिन</b> के लिए अधिकृत कर दिया गया है।", parse_mode=ParseMode.HTML)
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
        t_uid = int(context.args[0])
        remove_vip_user(t_uid)
        user_link = f'<a href="tg://user?id={t_uid}">{t_uid}</a>'
        await update.message.reply_text(f"🚫 छात्र {user_link} का एक्सेस रद्द कर दिया गया है।", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def info_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/info &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return

    try:
        t_uid = int(context.args[0])
        user_row, daf_row = get_user_full_info(t_uid)
        
        if not user_row:
            await update.message.reply_text(f"❌ इस आईडी (<code>{t_uid}</code>) का कोई सदस्य बॉट में पंजीकृत नहीं है।", parse_mode=ParseMode.HTML)
            return

        uid, un, fn, is_vip, exp, joined = user_row
        user_link = f'<a href="tg://user?id={uid}">{fn or uid}</a>'
        un_str = f"@{un}" if un else "कोई नहीं"
        vip_tag = "👑 [VIP/प्रीमियम सदस्य]" if is_vip == 1 else "👤 [निःशुल्क छात्र]"
        exp_str = exp.strftime('%d-%b-%Y %I:%M %p') if (is_vip == 1 and exp) else "लागू नहीं"
        joined_str = joined.strftime('%d-%b-%Y') if joined else "अज्ञात"

        info_text = (
            f"📋 <b>छात्र प्रोफ़ाइल विवरण (Dossier)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>नाम:</b> {user_link}\n"
            f"🆔 <b>यूज़र ID:</b> <code>{uid}</code>\n"
            f"🔗 <b>यूज़रनेम:</b> {un_str}\n"
            f"🔰 <b>स्थिति:</b> {vip_tag}\n"
            f"⏳ <b>वैधता:</b> <code>{exp_str}</code>\n"
            f"📅 <b>जुड़ने की तिथि:</b> {joined_str}\n\n"
        )

        if daf_row and daf_row[0]:
            name, state, college, status, opt_sub, attempt, updated = daf_row
            info_text += (
                f"🏛 <b>दर्ज DAF (साक्षात्कार प्रोफाइल):</b>\n"
                f"• <b>पूरा नाम:</b> {name}\n"
                f"• <b>गृह राज्य:</b> {state}\n"
                f"• <b>कॉलेज/यूनिवर्सिटी:</b> {college}\n"
                f"• <b>ग्रेजुएशन स्थिति:</b> {status}\n"
                f"• <b>वैकल्पिक विषय:</b> {opt_sub}\n"
                f"• <b>प्रयास संख्या:</b> {attempt}\n"
                f"• <b>अंतिम अपडेट:</b> {updated.strftime('%d-%b-%Y') if updated else 'N/A'}"
            )
        else:
            info_text += "🏛 <b>दर्ज DAF:</b> इस छात्र ने अभी तक <code>/interview</code> कमांड नहीं चलाई है या अपनी DAF प्रोफाइल सेव नहीं की है।"

        await update.message.reply_text(info_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ विवरण निकालने में त्रुटि: {e}")

async def list_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    rows = get_all_users_detailed()
    text = f"👥 <b>पंजीकृत सदस्य (कुल: {len(rows)})</b>\n\n"
    
    text += "👑 <b>प्रशासनिक संरक्षक (Owners):</b>\n"
    for aid in ADMIN_IDS:
        text += f"• <b>{ADMIN_NAMES.get(aid, 'व्यवस्थापक')}</b>: <code>{aid}</code>\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for uid, un, fn, is_vip, exp in rows:
        user_link = f'<a href="tg://user?id={uid}">{fn or uid}</a>'
        vip_tag = "👑 [VIP/प्रीमियम]" if is_vip == 1 else "👤 [निःशुल्क छात्र]"
        exp_str = f" | वैधता: {exp.strftime('%d-%b-%Y')}" if (is_vip == 1 and exp) else ""
        text += f"• {vip_tag} {user_link} (<code>{uid}</code>){exp_str}\n"

    for part in [text[i:i+3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)

# ================= ADMIN DIRECT REPLIES =================
async def handle_admin_reply_or_direct_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return

    if msg.reply_to_message:
        reply_to_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
        match = re.search(r'(?:यूज़र\s*ID|ID)[:\s]*([0-9]{8,11})', reply_to_text) or re.search(r'([0-9]{8,11})', reply_to_text)
        if match:
            target_user_id = int(match.group(1))
            reply_body = msg.text or msg.caption or ""
            user_notification = f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n{reply_body}\n\n📢 <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
            try:
                if msg.text:
                    await context.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                else:
                    await context.bot.copy_message(chat_id=target_user_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
                await msg.reply_text(f"✅ जवाब छात्र (<code>{target_user_id}</code>) को सफलतापूर्वक भेज दिया गया!", parse_mode=ParseMode.HTML)
                return
            except Exception as e:
                await msg.reply_text(f"❌ भेजने में त्रुटि: {e}")
                return

    if msg.text:
        direct_match = re.match(r'^([0-9]{8,11})\s+(.*)$', msg.text.strip(), flags=re.DOTALL)
        if direct_match:
            target_user_id = int(direct_match.group(1))
            reply_body = direct_match.group(2).strip()
            user_notification = f"🔔 <b>ओनर ({AUTHOR_NAME}) का जवाब:</b>\n\n{reply_body}\n\n📢 <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
            try:
                await context.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                await msg.reply_text(f"✅ जवाब छात्र (<code>{target_user_id}</code>) को सफलतापूर्वक भेज दिया गया!", parse_mode=ParseMode.HTML)
                return
            except Exception as e:
                await msg.reply_text(f"❌ भेजने में त्रुटि: {e}")
                return

# ================= OWNER FEEDBACK & GLOBAL CANCEL =================
async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    CONTACT_SESSIONS[user.id] = time.time()
    await update.message.reply_text(
        "⏱ <b>2 मिनट का समय सक्रिय है!</b>\n\n"
        f"अपनी समस्या या एक्सेस अनुरोध लिखकर भेजें। यह संदेश सीधे <b>{AUTHOR_NAME}</b> के पास पहुँचेगा।\n\n"
        "<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_CONTACT_MSG

async def forward_contact_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    msg = update.message

    if msg.text and msg.text.strip().lower() == "/cancel":
        CONTACT_SESSIONS.pop(user_id, None)
        await msg.reply_text("प्रक्रिया रद्द कर दी गई।")
        return ConversationHandler.END

    start_t = CONTACT_SESSIONS.get(user_id, 0)
    if time.time() - start_t > 120:
        CONTACT_SESSIONS.pop(user_id, None)
        await msg.reply_text("⚠️ समय समाप्त हो गया। पुनः <code>/owner</code> चलाएं।", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a> (<code>{user.id}</code>)'
    alert_text = f"📩 <b>छात्र संदेश ({AUTHOR_NAME}):</b>\n\nप्रेषक: {user_link}\nसंदेश: {msg.text or '[मीडिया]'}"

    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=alert_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    await msg.reply_text(f"✅ <b>संदेश {AUTHOR_NAME} को अग्रेषित कर दिया गया है!</b>", parse_mode=ParseMode.HTML)
    CONTACT_SESSIONS.pop(user_id, None)
    return ConversationHandler.END

async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    INTERVIEW_SESSION.pop(uid, None)
    CONTACT_SESSIONS.pop(uid, None)
    CHECK_ANSWER_CACHE.pop(uid, None)
    context.user_data.clear()
    await update.message.reply_text("🛑 प्रक्रिया निरस्त कर दी गई।", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# ================= BACKGROUND SERVER (RENDER KEEP-ALIVE) =================
async def run_server():
    server = await asyncio.start_server(
        lambda r, w: (w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nUPSC Study Desk Live 24/7"), w.close()),
        "0.0.0.0",
        int(os.environ.get("PORT", 8080))
    )
    asyncio.create_task(server.serve_forever())

# ================= MAIN DISPATCHER =================
async def main():
    await run_server()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True).build()

    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CommandHandler("help", help_handler))
    bot_app.add_handler(CommandHandler("daily", daily_cmd))
    bot_app.add_handler(CommandHandler("quiz", quiz_cmd))
    bot_app.add_handler(CommandHandler("mains", mains_special_cmd))
    bot_app.add_handler(CommandHandler("trending", trending_cmd))
    bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
    bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
    bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

    bot_app.add_handler(CommandHandler("adduser", add_user_cmd))
    bot_app.add_handler(CommandHandler("removeuser", remove_user_cmd))
    bot_app.add_handler(CommandHandler("info", info_user_cmd))
    bot_app.add_handler(CommandHandler("listusers", list_users_cmd))

    bot_app.add_handler(CallbackQueryHandler(handle_quiz_gs_choice, pattern=r"^quizgs_"))
    bot_app.add_handler(CallbackQueryHandler(handle_quiz_sub_choice, pattern=r"^quizsub_|^quiz_back_gs"))
    bot_app.add_handler(CallbackQueryHandler(handle_quiz_cnt_choice, pattern=r"^quizcnt_"))

    bot_app.add_handler(CallbackQueryHandler(handle_mains_type_choice, pattern=r"^mq_type_"))
    bot_app.add_handler(CallbackQueryHandler(handle_mains_gs_choice, pattern=r"^mq_gs_|^mains_back_root"))
    bot_app.add_handler(CallbackQueryHandler(handle_mains_cnt_choice, pattern=r"^mq_cnt_"))

    bot_app.add_handler(CallbackQueryHandler(handle_trending_type_selection, pattern=r"^trtype_|^tr_back_root"))
    bot_app.add_handler(CallbackQueryHandler(handle_trending_pages, pattern=r"^trpage_"))
    bot_app.add_handler(CallbackQueryHandler(handle_broadcast_pin_choice, pattern=r"^pin_broadcast_"))
    bot_app.add_handler(CallbackQueryHandler(handle_dynamic_generation_click))

    interview_conv = ConversationHandler(
        entry_points=[CommandHandler("interview", interview_flow_start)],
        states={
            DAF_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_name_step)],
            DAF_STATE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_state_step)],
            DAF_COLLEGE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_college_step)],
            DAF_STATUS: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_status_step)],
            DAF_OPTIONAL_STEP: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_optional_step)],
            DAF_ATTEMPT_STEP: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_attempt_step)],
            DAF_QCOUNT: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_qcount_step)],
            WAITING_INTERVIEW_VOICE: [MessageHandler((filters.VOICE | filters.AUDIO) & (~filters.COMMAND), handle_interview_candidate_voice)],
            WAITING_INTERVIEW_DECISION: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_interview_decision)]
        },
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(interview_conv)

    answer_check_conv = ConversationHandler(
        entry_points=[CommandHandler("checkanswer", check_answer_cmd)],
        states={
            CA_CHOOSE_TYPE: [CallbackQueryHandler(handle_ca_type_choice, pattern=r"^ca_type_")],
            CA_QUESTION_TEXT: [MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO) & (~filters.COMMAND), handle_ca_question_text_step)],
            CA_CUSTOM_MARKS: [CallbackQueryHandler(handle_ca_marks_choice, pattern=r"^camarks_")],
            CA_ANSWER_COPY: [MessageHandler((filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), handle_ca_answer_copy_submission)]
        },
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(answer_check_conv)

    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", start_ask_session)],
        states={WAITING_ASK_SESSION: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ask_continuous_message)]},
        fallbacks=[CommandHandler("cancel", global_cancel), CommandHandler("stop", global_cancel), CommandHandler("exit", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(ask_conv)

    contact_conv = ConversationHandler(
        entry_points=[CommandHandler("owner", contact_cmd)],
        states={WAITING_CONTACT_MSG: [MessageHandler(filters.ALL & (~filters.COMMAND), forward_contact_msg)]},
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(contact_conv)

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={WAITING_BROADCAST_MSG: [MessageHandler(filters.ALL & (~filters.COMMAND), execute_broadcast_step1)]},
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(broadcast_conv)

    bot_app.add_handler(MessageHandler(filters.User(ADMIN_IDS) & (filters.REPLY | filters.Regex(r'^[0-9]{8,11}')), handle_admin_reply_or_direct_send))
    bot_app.add_handler(MessageHandler(filters.Document.PDF, handle_direct_pdf_upload))
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_messages))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
