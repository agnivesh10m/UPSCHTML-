import os
import re
import time
import json
import asyncio
import io
import random
import html
from datetime import timedelta
from pypdf import PdfReader
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
DAF_DISTRICT = 6
DAF_VILLAGE = 7
DAF_COLLEGE = 8
DAF_STREAM = 9
DAF_STATUS = 10
DAF_OPTIONAL_STEP = 11
DAF_HOBBY = 12
DAF_ATTEMPT_STEP = 13
DAF_QCOUNT = 14
WAITING_INTERVIEW_VOICE = 15
WAITING_INTERVIEW_DECISION = 16

CA_CHOOSE_TYPE = 17
CA_QUESTION_INPUT = 18
CA_ANSWER_COPY = 19

CONTACT_SESSIONS = {}
USER_QUIZ_SELECTIONS = {}
MAINS_SELECTIONS = {}
CHECK_ANSWER_CACHE = {}
TRENDING_CACHE = {}
INTERVIEW_SESSION = {}
LAST_BROADCAST_DATA = {}

def get_tg_user_link(user_id: int, name: str = None) -> str:
    clean_name = html.escape(name) if name else str(user_id)
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

def get_free_user_access_markup(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📋 अपनी ID कॉपी करें ({user_id})", callback_data=f"copyid_{user_id}")],
        [InlineKeyboardButton("💬 ओनर से संपर्क करें", url=f"https://t.me/Avigat1210")],
        [InlineKeyboardButton("📢 आधिकारिक चैनल जॉइन करें", url=CHANNEL_LINK)]
    ])

def ensure_auth(handler_func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
        register_user(user.id, user.username, user.first_name)
        if not is_authorized(user.id):
            user_link = get_tg_user_link(user.id, user.first_name)
            msg = (
                f"👋 <b>नमस्ते {user_link}!</b>\n\n"
                "🔒 <b>प्रीमियम यूपीएससी डेस्क — एक्सेस प्रतिबंधित</b>\n\n"
                "⚠️ यह पोर्टल केवल <b>सत्यापित प्रीमियम सदस्यों</b> के लिए सुरक्षित है ताकि उच्च-स्तरीय AI एवं सर्वर संसाधनों का सदुपयोग सुनिश्चित हो सके।\n\n"
                f"🆔 <b>आपकी टेलीग्राम ID:</b> <code>{user.id}</code>\n"
                f"🔗 <b>प्रोफाइल लिंक:</b> {get_tg_user_link(user.id, f'यूज़र {user.id}')}\n\n"
                "👉 <b>एक्सेस प्राप्त करने के दिशा-निर्देश:</b>\n"
                "1. नीचे दिए गए बटन पर टैप करके अपनी ID कॉपी करें।\n"
                f"2. ओनर <b>{AUTHOR_NAME}</b> (@Avigat1210) को भेजकर सब्सक्रिप्शन सक्रिय करवाएं।"
            )
            await update.effective_message.reply_text(
                msg, 
                parse_mode=ParseMode.HTML, 
                disable_web_page_preview=True,
                reply_markup=get_free_user_access_markup(user.id)
            )
            return
        return await handler_func(update, context, *args, **kwargs)
    return wrapper

async def copy_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.data.replace("copyid_", "")
    await query.answer(f"आपकी टेलीग्राम ID: {uid} (कॉपी करने हेतु ऊपर कोड पर टैप करें)", show_alert=True)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    user_link = get_tg_user_link(user.id, user.first_name)
    
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"👋 <b>नमस्ते {user_link}!</b>\n\n"
            "📚 <b>UPSC CIVIL SERVICES PORTAL</b>\n\n"
            f"🆔 <b>आपकी टेलीग्राम ID:</b> <code>{user.id}</code>\n"
            "🔰 <b>खाता स्थिति:</b> ❌ निःशुल्क सदस्य (एक्सेस निष्क्रिय)\n\n"
            "⚠️ <b>महत्वपूर्ण सूचना:</b>\n"
            "वर्तमान में इस बोट के सभी अध्ययन फीचर्स (दैनिक 360° नोट्स, विजन क्विज़ पोर्टल, लाइव DAF इंटरव्यू, कॉपी चेकिंग) केवल प्रीमियम सदस्यों के लिए आरक्षित हैं।\n\n"
            f"👉 <b>सब्सक्रिप्शन सक्रिय करवाने हेतु नीचे दिए बटन से संपर्क करें:</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=get_free_user_access_markup(user.id)
        )
        return

    admin_tag = f"👑 <b>एडमिन कंट्रोल सक्रिय ({AUTHOR_NAME})</b>\n\n" if user.id in ADMIN_IDS else "⭐ <b>प्रीमियम यूपीएससी डेस्क सक्रिय</b>\n\n"

    msg = (
        f"👋 <b>नमस्ते {user_link}!</b>\n\n"
        f"{admin_tag}"
        f"🆔 <b>आपकी स्थायी प्रोफाइल:</b> {get_tg_user_link(user.id, f'प्रोफाइल लिंक ({user.id})')}\n\n"
        "📖 <b>अध्ययन एवं नोट्स (पाठ्यक्रम मैपिंग सहित):</b>\n"
        "• <code>/daily</code> — दैनिक 360° समसामयिक संकलन (सिलेबस टॉपिक टैग्स)\n"
        "• <code>/trending</code> — राष्ट्रीय व वैश्विक ट्रेंडिंग रडार (कठिन स्तर)\n"
        "• <code>/quiz</code> — विजन IAS स्टाइल लाइव मॉक टेस्ट पोर्टल (50 व 100 प्रश्न)\n"
        "• <code>/mains</code> — मुख्य परीक्षा अभ्यास (2013-2026 संपूर्ण PYQs व मॉडल प्रश्न)\n"
        "• <code>/checkanswer</code> — उत्तर पुस्तिका मूल्यांकन (मानचित्र व आरेख स्कैनिंग सहित)\n"
        "• <code>/interview</code> — 1-on-1 साक्षात्कार (DAF व वॉयस - 25 से 275 अंक तक)\n"
        "• <code>/weekly</code> — साप्ताहिक क्विक रिवीजन\n"
        "• <code>/monthly</code> — संपूर्ण मासिक संकलन\n"
        "• <code>/yearly</code> — वार्षिक महा-संकलन (PT-365)\n"
        "• <code>/ask</code> — 24/7 यूपीएससी मेंटरशिप सत्र (टेक्स्ट व वॉयस)\n\n"
        "💬 <b>सहायता व संपर्क:</b>\n"
        "• <code>/help</code> — संपूर्ण उपयोग मार्गदर्शिका\n"
        "• <code>/owner</code> — सचिन शर्मा से संपर्क करें\n"
        "• <code>/cancel</code> — प्रक्रिया तुरंत रद्द करें\n\n"
        f"📢 <b>ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name)
    user_link = get_tg_user_link(user.id, user.first_name)

    if not is_authorized(user.id):
        await update.message.reply_text(
            f"👋 <b>नमस्ते {user_link}!</b>\n\n"
            "⚠️ आप वर्तमान में निःशुल्क सदस्य हैं। किसी भी फीचर का उपयोग करने के लिए प्रीमियम सब्सक्रिप्शन अनिवार्य है।\n\n"
            f"🆔 <b>आपकी टेलीग्राम ID:</b> <code>{user.id}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=get_free_user_access_markup(user.id)
        )
        return

    help_text = (
        f"📖 <b>UPSC SMART DESK — संपूर्ण गाइड ({AUTHOR_NAME})</b>\n\n"
        f"👤 <b>सदस्य:</b> {user_link} (<code>{user.id}</code>)\n\n"
        "1️⃣ <b>दैनिक व आवधिक नोट्स (`/daily`, `/weekly`, `/monthly`):</b> प्रत्येक मुद्दे पर GS पेपर व सिलेबस टॉपिक का स्पष्ट उल्लेख।\n\n"
        "2️⃣ <b>ऑनलाइन क्विज़ पोर्टल (`/quiz`):</b> 1 लाख+ प्रश्नों के बैंक से 50 या 100 प्रश्नों का लाइव टेस्ट पोर्टल (शून्य दोहराव)।\n\n"
        "3️⃣ <b>मुख्य परीक्षा अभ्यास (`/mains`):</b> 2013 से 2026 तक के सभी मुख्य परीक्षा PYQs का संपूर्ण संग्रह एवं मॉडल उत्तर ढांचा।\n\n"
        "4️⃣ <b>उत्तर-पुस्तिका मूल्यांकन (`/checkanswer`):</b> PYQ या मॉडल प्रश्न चुनें। फ़ोटो/PDF या वॉयस उत्तर भेजें। मानचित्रों व आरेखों की भी सख्त जांच होगी।\n\n"
        "5️⃣ <b>लाइव साक्षात्कार (`/interview`):</b> DAF आधारित मौखिक साक्षात्कार (1, 3, 5 या पूरे 9 प्रश्न/275 अंक का मॉक बोर्ड)।\n\n"
        "6️⃣ <b>मेंटरशिप सत्र (`/ask`):</b> टेक्स्ट या वॉयस मैसेज भेजकर UPSC के किसी भी विषय पर सीधा प्रशासनिक विश्लेषण प्राप्त करें।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ================= 1 से 10 दिनों का डेली मेनू =================
@ensure_auth
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = get_ist_now()
    keyboard = []
    
    for i in range(10):
        target_dt = today - timedelta(days=i)
        d_str = target_dt.strftime("%Y-%m-%d")
        if i == 0:
            label = f"🌟 आज का संकलन ({d_str})"
        elif i == 1:
            label = f"📅 कल का संकलन ({d_str})"
        else:
            label = f"🗓️ {d_str} ({i} दिन पहले)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"gendate_{d_str}")])

    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")])
    await update.message.reply_text(
        "📅 <b>UPSC दैनिक 360° महा-संकलन (पाठ्यक्रम टैग्स सहित):</b>\nजिस तारीख का पूरा विश्लेषण चाहिए, उसका चयन करें (पिछले 10 दिन):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

# ================= ऑनलाइन टेस्ट पोर्टल (/quiz) =================
@ensure_auth
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quiz_intro = (
        "🎯 <b>UPSC CSE ऑनलाइन टेस्ट पोर्टल (1,00,000+ प्रश्न बैंक)</b>\n\n"
        "✨ <b>विशेष निर्देश:</b>\n"
        "• आप किसी भी विषय या टॉपिक में असीमित बार टेस्ट दे सकते हैं।\n"
        "• प्रत्येक टेस्ट में हमारे <b>1 लाख+ प्रश्नों के प्रश्न बैंक</b> से एकदम नए और कठिन प्रश्न शामिल किए जाते हैं (शून्य दोहराव)।\n"
        "• टेस्ट में लाइव टाइमर, OMR ग्रिड, प्राप्तांक और 50% वाटरमार्क प्रिंटेड PDF उपलब्ध रहती है।\n\n"
        "👉 <b>चरण 1/3: किस GS पेपर का लाइव टेस्ट देना चाहते हैं?</b>"
    )
    keyboard = [
        [InlineKeyboardButton("🏛 GS पेपर 1 (इतिहास, भूगोल, समाज)", callback_data="quizgs_1")],
        [InlineKeyboardButton("⚖ GS पेपर 2 (राजव्यवस्था, शासन, IR)", callback_data="quizgs_2")],
        [InlineKeyboardButton("💰 GS पेपर 3 (अर्थव्यवस्था, पर्यावरण, Sci-Tech)", callback_data="quizgs_3")],
        [InlineKeyboardButton("⚡ संपूर्ण समसामयिकी (Current Affairs)", callback_data="quizgs_ca")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    if update.callback_query:
        await update.callback_query.message.edit_text(quiz_intro, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(quiz_intro, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

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
            [InlineKeyboardButton("⚖ शासन प्रणाली व सामाजिक न्याय", callback_data="quizsub_gov")],
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
            [InlineKeyboardButton("🛡 आंतरिक सुरक्षा व आपदा प्रबंधन", callback_data="quizsub_security")],
            [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quiz_back_gs")]
        ]
        await query.message.edit_text("🎯 <b>चरण 2/3 (GS 3):</b> विशिष्ट विषय चुनें:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        USER_QUIZ_SELECTIONS[user_id] = {"gs": "CA", "sub": "दैनिक व मासिक करेंट अफेयर्स"}
        keyboard = [
            [InlineKeyboardButton("⚡ 50 प्रश्न (मानक अभ्यास सेट)", callback_data="quizcnt_50")],
            [InlineKeyboardButton("🎯 100 प्रश्न (पूर्ण विजन IAS स्टाइल मॉक)", callback_data="quizcnt_100")],
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
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="quizgs_1")]
    ]
    await query.message.edit_text(f"🎯 <b>चरण 3/3:</b> विषय <b>{USER_QUIZ_SELECTIONS[user_id]['sub']}</b> के कितने प्रश्न चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

def robust_json_cleaner(raw_text: str) -> list:
    clean = re.sub(r'```(?:json)?', '', raw_text, flags=re.IGNORECASE).strip()
    start = clean.find('[')
    end = clean.rfind(']')
    if start != -1 and end != -1 and end > start:
        clean = clean[start:end+1]
    
    clean = re.sub(r',\s*\]', ']', clean)
    clean = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', clean)
    
    try:
        data = json.loads(clean)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    
    items = []
    pattern = re.compile(r'\{[^{}]*"topic"[^{}]*"text"[^{}]*"options"[^{}]*"correctAnswer"[^{}]*"solution"[^{}]*\}', re.DOTALL)
    for m in pattern.finditer(clean):
        try:
            items.append(json.loads(m.group(0)))
        except Exception:
            continue
    return items

def generate_single_quiz_batch(subj: str, count: int, batch_index: int = 0) -> list:
    random_seed = random.randint(100000, 999999)
    prompt = f"""
आप UPSC CSE Prelims के मुख्य परीक्षक हैं।
विषय: '{subj}' (सीड: {random_seed}, बैच: {batch_index + 1})
कार्य: ठीक {count} अत्यंत कठिन, मानक एवं कथन-आधारित बहुविकल्पीय प्रश्न (MCQs) तैयार करें।

अनिवार्य नियम:
1. प्रश्न The Hindu, Indian Express, PIB व Vision IAS के पैटर्न पर हों।
2. शून्य पुनरावृत्ति।
3. केवल और केवल शुद्ध JSON Array आउटपुट दें:
[
  {{
    "topic": "{subj}",
    "text": "1. प्रश्न का विवरण व 2-3 विश्लेषणात्मक कथन...",
    "options": ["(a) केवल 1", "(b) केवल 2", "(c) 1 और 2 दोनों", "(d) न तो 1, न ही 2"],
    "correctAnswer": 2,
    "solution": "<b>व्याख्या:</b> स्रोत सहित प्रामाणिक 2-3 पंक्तियों की आधिकारिक व्याख्या।"
  }}
]
नोट: correctAnswer 0, 1, 2 या 3 हो। भाषा शुद्ध हिंदी रखें।
"""
    raw_resp = call_gemini_safely(prompt)
    return robust_json_cleaner(raw_resp)

async def handle_quiz_cnt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cnt = int(query.data.replace("quizcnt_", ""))
    user_id = query.from_user.id
    subj = USER_QUIZ_SELECTIONS.get(user_id, {}).get("sub", "सामान्य अध्ययन")

    status_msg = await query.message.reply_text("⏳ [■□□□□□□□□□] 10% UPSC टेस्ट डेस्क प्रारंभ हो रहा है...")

    try:
        all_questions = []
        if cnt == 50:
            await status_msg.edit_text("⏳ [■■■□□□□□□□] 35% 1 लाख+ बैंक से 50 कठिन प्रश्नों का संश्लेषण जारी...")
            q_batch = await asyncio.to_thread(generate_single_quiz_batch, subj, 50, 0)
            if not q_batch or len(q_batch) < 15:
                await status_msg.edit_text("⏳ [■■■■■□□□□□] 55% प्रश्नों का बैकअप संश्लेषण जारी...")
                b1 = await asyncio.to_thread(generate_single_quiz_batch, subj, 25, 1)
                b2 = await asyncio.to_thread(generate_single_quiz_batch, subj, 25, 2)
                all_questions = b1 + b2
            else:
                all_questions = q_batch
        else:
            await status_msg.edit_text("⏳ [■■■□□□□□□□] 30% बैच 1/2: प्रथम 50 प्रश्नों का संश्लेषण जारी...")
            b1 = await asyncio.to_thread(generate_single_quiz_batch, subj, 50, 1)
            await status_msg.edit_text("⏳ [■■■■■■□□□□] 65% बैच 2/2: द्वितीय 50 प्रश्नों का संश्लेषण जारी...")
            b2 = await asyncio.to_thread(generate_single_quiz_batch, subj, 50, 2)
            all_questions = b1 + b2

        if not all_questions:
            raise Exception("प्रश्नों की संरचना संकलित नहीं हो सकी।")

        await status_msg.edit_text("⏳ [■■■■■■■■□□] 85% प्रश्नों की उत्तर कुंजी व नंबरिंग व्यवस्थित हो रही है...")

        for idx, q in enumerate(all_questions):
            q_text = q.get("text", "")
            q_text = re.sub(r'^\d+\.\s*', '', q_text).strip()
            q["text"] = f"{idx + 1}. {q_text}"
            q["topic"] = subj

        await status_msg.edit_text("⏳ [■■■■■■■■■□] 95% विजन IAS ऑनलाइन टेस्ट पोर्टल असेंबल हो रहा है...")

        test_id = f"{int(time.time()) % 100000}"
        portal_html = build_vision_ias_interactive_portal(subj, test_id, len(all_questions), all_questions)

        filename = f"UPSC_Mock_{len(all_questions)}Q_{test_id}.html"
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
                    f"📝 <b>कुल प्रश्न:</b> <code>{len(all_questions)} MCQs (1,00,000+ बैंक, शून्य दोहराव)</code>\n"
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

# ================= साक्षात्कार (/interview) 10-चरणीय DAF =================
@ensure_auth
async def interview_flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id

    daf = get_user_daf(user_id)
    if not daf or not daf[0]:
        await update.message.reply_text(
            f"🏛 <b>UPSC साक्षात्कार बोर्ड (Personality Test - DAF Entry)</b>\n\n"
            f"नमस्ते <b>{user.first_name} जी</b>! बोर्ड कक्ष में प्रवेश से पहले हमें आपकी पृष्ठभूमि का आधिकारिक DAF विवरण चाहिए ताकि बोर्ड मेंबर आपके गृह क्षेत्र, कॉलेज, स्ट्रीम व रुचि से सीधे सवाल पूछ सकें।\n\n"
            "👉 <b>चरण 1/10:</b> कृपया अपना <b>पूरा नाम</b> लिखकर भेजें:",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        return DAF_NAME

    name, home_state, home_district, home_village, college, stream, status, opt_sub, hobby, attempt = daf
    reply_kb = [["✅ इसी DAF प्रोफाइल से साक्षात्कार दें"], ["✏️ DAF अपडेट करें (Edit DAF)"]]
    await update.message.reply_text(
        f"🏛 <b>आपकी पूर्व दर्ज यूपीएससी DAF प्रोफाइल:</b>\n\n"
        f"👤 <b>नाम:</b> {name}\n"
        f"📍 <b>गृह राज्य:</b> {home_state}\n"
        f"🏙️ <b>गृह जिला:</b> {home_district}\n"
        f"🏡 <b>गांव/कस्बा:</b> {home_village}\n"
        f"🏫 <b>कॉलेज:</b> {college}\n"
        f"🎓 <b>स्नातक स्ट्रीम:</b> {stream}\n"
        f"📊 <b>ग्रेजुएशन स्थिति:</b> {status}\n"
        f"📚 <b>वैकल्पिक विषय:</b> {opt_sub}\n"
        f"🎨 <b>हॉबी / अभिरुचि:</b> {hobby}\n"
        f"🎯 <b>तैयारी / प्रयास:</b> {attempt}\n\n"
        "👉 कृपया विकल्प चुनें:",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_NAME

async def handle_daf_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip() if update.message.text else update.effective_user.first_name

    if txt == "✅ इसी DAF प्रोफाइल से साक्षात्कार दें":
        reply_kb = [
            ["⚡ 1 प्रश्न (क्विक टेस्ट - 25 अंक)"],
            ["🎯 3 प्रश्न (मानक बोर्ड - 75 अंक)"],
            ["🏆 5 प्रश्न (विस्तृत बोर्ड - 125 अंक)"],
            ["🏛 संपूर्ण बोर्ड इंटरव्यू (9 प्रश्न - 275 अंक)"]
        ]
        await update.message.reply_text(
            "👉 <b>आप कितने प्रश्नों का साक्षात्कार सेट देना चाहते हैं?</b>",
            reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
            parse_mode=ParseMode.HTML
        )
        return DAF_QCOUNT

    if txt == "✏️ DAF अपडेट करें (Edit DAF)":
        await update.message.reply_text("👉 <b>चरण 1/10:</b> अपना <b>पूरा नाम</b> लिखकर भेजें:", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return DAF_NAME

    context.user_data["daf_name"] = txt
    await update.message.reply_text("👉 <b>चरण 2/10:</b> अपना <b>गृह राज्य (Home State)</b> दर्ज करें (उदा. राजस्थान, उत्तर प्रदेश):", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return DAF_STATE

async def handle_daf_state_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_state"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 3/10:</b> अपना <b>गृह जिला (Home District)</b> लिखें (उदा. कोटपूतली-बहरोड़, अलवर, प्रयागराज):", parse_mode=ParseMode.HTML)
    return DAF_DISTRICT

async def handle_daf_district_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_district"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 4/10:</b> अपने <b>गांव / कस्बे / शहर</b> का नाम लिखें:", parse_mode=ParseMode.HTML)
    return DAF_VILLAGE

async def handle_daf_village_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_village"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 5/10:</b> अपने <b>कॉलेज / विश्वविद्यालय</b> का नाम लिखें:", parse_mode=ParseMode.HTML)
    return DAF_COLLEGE

async def handle_daf_college_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_college"] = update.message.text.strip()
    reply_kb = [["B.A. (कला / मानविकी)"], ["B.Sc. (विज्ञान / कृषि)"], ["B.Tech / B.E. (इंजीनियरिंग)"], ["B.Com (वाणिज्य / प्रबंधन)"]]
    await update.message.reply_text(
        "👉 <b>चरण 6/10:</b> आपकी <b>स्नातक स्ट्रीम (Graduation Stream)</b> क्या है? (चुनें या लिखकर भेजें):",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_STREAM

async def handle_daf_stream_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_stream"] = update.message.text.strip()
    reply_kb = [["🎓 स्नातक पूर्ण (Completed)"], ["⏳ अध्ययनरत (Running / Final Year)"]]
    await update.message.reply_text(
        "👉 <b>चरण 7/10:</b> कॉलेज की वर्तमान स्थिति क्या है?",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_STATUS

async def handle_daf_status_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_status"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 8/10:</b> अपना <b>वैकल्पिक विषय (Optional Subject)</b> लिखें (उदा. भूगोल, इतिहास, राजनीति विज्ञान):", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return DAF_OPTIONAL_STEP

async def handle_daf_optional_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_optional"] = update.message.text.strip()
    await update.message.reply_text("👉 <b>चरण 9/10:</b> अपनी <b>हॉबी / अभिरुचि (Hobby)</b> लिखें (उदा. डायरी लेखन, योग, ग्रामीण खेती, क्रिकेट):", parse_mode=ParseMode.HTML)
    return DAF_HOBBY

async def handle_daf_hobby_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["daf_hobby"] = update.message.text.strip()
    reply_kb = [
        ["🎯 सिर्फ तैयारी कर रहा हूँ (Preparation Phase)"],
        ["1st Attempt (पहला प्रयास)"],
        ["2nd Attempt (दूसरा प्रयास)"],
        ["3rd+ Attempt (तीसरा या अधिक)"]
    ]
    await update.message.reply_text("👉 <b>चरण 10/10:</b> आपकी <b>तैयारी या प्रयास (Attempt Status)</b> की वर्तमान स्थिति क्या है?", reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True), parse_mode=ParseMode.HTML)
    return DAF_ATTEMPT_STEP

async def handle_daf_attempt_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    attempt_txt = update.message.text.strip()

    name = context.user_data.get("daf_name", update.effective_user.first_name)
    state = context.user_data.get("daf_state", "राजस्थान")
    dist = context.user_data.get("daf_district", "गृह जिला")
    vill = context.user_data.get("daf_village", "गृह क्षेत्र")
    college = context.user_data.get("daf_college", "विश्वविद्यालय")
    stream = context.user_data.get("daf_stream", "कला/मानविकी")
    status = context.user_data.get("daf_status", "पूर्ण")
    opt = context.user_data.get("daf_optional", "सामान्य अध्ययन")
    hobby = context.user_data.get("daf_hobby", "अध्ययन")

    save_user_daf(user_id, name, state, dist, vill, college, stream, status, opt, hobby, attempt_txt)

    reply_kb = [
        ["⚡ 1 प्रश्न (क्विक टेस्ट - 25 अंक)"],
        ["🎯 3 प्रश्न (मानक बोर्ड - 75 अंक)"],
        ["🏆 5 प्रश्न (विस्तृत बोर्ड - 125 अंक)"],
        ["🏛 संपूर्ण बोर्ड इंटरव्यू (9 प्रश्न - 275 अंक)"]
    ]
    await update.message.reply_text(
        "✅ <b>आपकी 10-चरणीय संपूर्ण यूपीएससी DAF प्रोफाइल सुरक्षित कर ली गई है!</b>\n\n"
        "👉 <b>आप कितने प्रश्नों का साक्षात्कार सेट देना चाहते हैं?</b>",
        reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return DAF_QCOUNT

async def handle_daf_qcount_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    txt = update.message.text.strip()
    
    cnt = 1
    max_m = 25
    if "9 प्रश्न" in txt or "275 अंक" in txt:
        cnt = 9
        max_m = 275
    elif "5 प्रश्न" in txt:
        cnt = 5
        max_m = 125
    elif "3 प्रश्न" in txt:
        cnt = 3
        max_m = 75
    elif "1 प्रश्न" in txt:
        cnt = 1
        max_m = 25

    daf = get_user_daf(user_id)
    INTERVIEW_SESSION[user_id] = {
        "total": cnt,
        "max_marks": max_m,
        "current": 1,
        "daf": daf,
        "history": []
    }

    status_m = await update.message.reply_text("🏛 <b>बोर्ड कक्ष में स्वागत है।</b> प्रश्न तैयार किया जा रहा है...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return await ask_interview_question(update, context, user_id, status_m)

async def ask_interview_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, status_m = None) -> int:
    sess = INTERVIEW_SESSION.get(user_id)
    curr = sess["current"]
    tot = sess["total"]
    name, state, dist, vill, college, stream, status, opt_sub, hobby, attempt = sess["daf"]

    prompt = f"""
आप UPSC साक्षात्कार बोर्ड के अध्यक्ष हैं।
उम्मीदवार विवरण (DAF Data):
- नाम: {name}
- गृह राज्य: {state}
- गृह जिला: {dist}
- गृह गांव/कस्बा: {vill}
- कॉलेज: {college}
- स्नातक स्ट्रीम: {stream} ({status})
- वैकल्पिक विषय: {opt_sub}
- हॉबी / अभिरुचि: {hobby}
- तैयारी स्थिति/प्रयास: {attempt}
- राउंड: {curr}/{tot} (कठिनाई स्तर: {curr * 2}/10)

सख्त निर्देश:
- सीधे '{name} जी' कहकर संबोधित करें।
- उम्मीदवार के जिले ({dist}), गांव ({vill}), स्ट्रीम ({stream}), वैकल्पिक विषय ({opt_sub}) या हॉबी ({hobby}) को आधार बनाकर 3-4 पंक्तियों का अत्यंत गंभीर, प्रशासनिक स्थितिजन्य प्रश्न पूछें जिसमें निर्णय-क्षमता की वास्तविक परीक्षा हो।
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

        await send_mandatory_voice(
            context,
            update.effective_chat.id,
            q_text,
            f"🎙️ साक्षात्कार प्रश्न {curr}/{tot} (बोर्ड अध्यक्ष आवाज़) | {AUTHOR_NAME}"
        )

    except Exception as e:
        await update.effective_message.reply_text(f"❌ साक्षात्कार प्रश्न बनाने में समस्या: {e}")

    return WAITING_INTERVIEW_VOICE

async def send_mandatory_voice(context, chat_id, text, caption):
    try:
        audio_bytes = await download_audio_stream(text)
        if audio_bytes:
            audio_io = io.BytesIO(audio_bytes)
            audio_io.name = "Board_Voice.mp3"
            await context.bot.send_voice(chat_id=chat_id, voice=audio_io, caption=caption)
    except Exception as e:
        print(f"Mandatory Voice Send Error: {e}")

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
उम्मीदवार को {name} जी कहकर संबोधित करते हुए 2-3 पंक्तियों में प्रशासनिक भाषा में संतुलित और निष्पक्ष मौखिक फीडबैक दें। केवल शुद्ध हिंदी लिखें।
"""
        eval_resp = await asyncio.to_thread(call_gemini_safely, eval_prompt)
        await wait_m.delete()

        await update.message.reply_text(f"🏛 <b>बोर्ड का अवलोकन ({sess['current']}/{sess['total']}):</b>\n\n{eval_resp}", parse_mode=ParseMode.HTML)

        await send_mandatory_voice(
            context,
            update.effective_chat.id,
            eval_resp,
            f"🎙️ बोर्ड अवलोकन एवं फीडबैक (अध्यक्ष) | {AUTHOR_NAME}"
        )

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
        sess["max_marks"] = sess.get("max_marks", 25) + 25
        INTERVIEW_SESSION[user_id] = sess
        status_m = await update.message.reply_text("अगला उन्नत स्तर का प्रश्न तैयार हो रहा है...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return await ask_interview_question(update, context, user_id, status_m)

    wait_m = await update.message.reply_text("⏳ बोर्ड सदस्य अंतिम मूल्यांकन पत्रक तैयार कर रहे हैं...", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    name = sess["daf"][0]
    total_q = len(sess['history'])
    max_marks = sess.get("max_marks", total_q * 25)

    final_prompt = f"""
उम्मीदवार {name} का UPSC साक्षात्कार पूर्ण हो चुका है।
कुल प्रश्न पूछे गए: {total_q}
अधिकतम अंक (Scale): {max_marks} अंक।

कार्य:
एक अत्यधिक सख्त, निष्पक्ष और आधिकारिक UPSC साक्षात्कार रिपोर्ट कार्ड तैयार करें।
प्रारूप:
1. 🏆 प्राप्तांक: (सख्त मार्किंग के अनुसार {max_marks} में से अंक दें, उदा. {int(max_marks*0.55)}/{max_marks} अंक)
2. 🌟 मुख्य प्रशासनिक खूबियाँ (Strengths): भूमिका, वाणी में ठहराव, संतुलित दृष्टिकोण
3. ⚠️ गंभीर कमियाँ एवं सुधार योग्य क्षेत्र (Areas of Improvement): डेटा की कमी, स्थितिजन्य असमंजस
4. 🚀 बोर्ड की अंतिम अनुशंसा (Final Board Recommendation)

केवल शुद्ध हिंदी में लिखें।
"""
    try:
        final_report = await asyncio.to_thread(call_gemini_safely, final_prompt)
        await wait_m.delete()
        
        await update.message.reply_text(
            f"📜 <b>UPSC साक्षात्कार परिणाम पत्रक ({total_q} प्रश्न सत्र - {max_marks} अंक):</b>\n\n"
            f"{final_report}\n\n"
            f"👤 <b>बोर्ड संरक्षक:</b> {AUTHOR_NAME}",
            parse_mode=ParseMode.HTML
        )

        summary_voice_text = f"नमस्कार {name} जी, आपके साक्षात्कार का मूल्यांकन पूर्ण हो गया है। आपका कुल स्कोर {max_marks} अंकों में से निर्धारित किया गया है। विस्तृत विश्लेषण आपके चैट पर प्रेषित है।"
        await send_mandatory_voice(
            context,
            update.effective_chat.id,
            summary_voice_text,
            f"🎙️ साक्षात्कार परिणाम सारांश (बोर्ड अध्यक्ष) | {AUTHOR_NAME}"
        )

    except Exception as e:
        await wait_m.edit_text(f"त्रुटि: {e}")

    INTERVIEW_SESSION.pop(user_id, None)
    return ConversationHandler.END

# ================= मुख्य परीक्षा अभ्यास (/mains) =================
@ensure_auth
async def mains_special_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📜 विगत वर्षों के प्रश्न (PYQs 2013-2026 Complete Archive)", callback_data="mq_type_pyq")],
        [InlineKeyboardButton("✨ नए संभावित मॉडल प्रश्न (New Expected)", callback_data="mq_type_new")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("✍️ <b>UPSC मुख्य परीक्षा (Mains) अभ्यास:</b>\nआप 2013 से 2026 के वास्तविक PYQs देखना चाहते हैं या नए मॉडल प्रश्न?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

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
        keyboard.append([InlineKeyboardButton("📚 2013-2026 तक के सभी मुख्य PYQs (संपूर्ण आर्काइव)", callback_data="mq_cnt_all")])
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
    sel = MAINS_SELECTIONS.get(user_id, {"q_type": "new", "gs": "2"})
    is_pyq = (sel.get("q_type") == "pyq")
    gs_paper = f"सामान्य अध्ययन - {sel.get('gs')}"

    wait_m = await query.message.reply_text("⏳ [■■□□□□□□□□] 20% UPSC मुख्य परीक्षा प्रश्न बैंक से डेटा संकलन प्रारंभ...")

    try:
        combined_text = ""
        if is_pyq and cnt_raw == "all":
            await wait_m.edit_text("⏳ [■■■■□□□□□□] 40% भाग 1/3: वर्ष 2026 से 2022 तक के PYQs का संकलन जारी...")
            p1 = f"""
UPSC CSE मुख्य परीक्षा {gs_paper} के वर्ष 2026, 2025, 2024, 2023 एवं 2022 के सभी प्रमुख प्रश्नों का संपूर्ण संकलन करें।
प्रत्येक प्रश्न पर स्पष्ट टैग: [UPSC CSE वर्ष / GS {sel.get('gs')} / अंक]।
ढांचा: 📌 भूमिका, 📊 मुख्य विश्लेषणात्मक आयाम (3 बिंदु), 🚀 आगे की राह, ⚖️ संतुलित प्रशासनिक निष्कर्ष।
केवल शुद्ध हिंदी में लिखें।
"""
            r1 = await asyncio.to_thread(call_gemini_safely, p1)

            await wait_m.edit_text("⏳ [■■■■■■□□□□] 65% भाग 2/3: वर्ष 2021 से 2017 तक के PYQs का संकलन जारी...")
            p2 = f"""
UPSC CSE मुख्य परीक्षा {gs_paper} के वर्ष 2021, 2020, 2019, 2018 एवं 2017 के सभी प्रमुख प्रश्नों का संपूर्ण संकलन करें।
प्रत्येक प्रश्न पर स्पष्ट टैग: [UPSC CSE वर्ष / GS {sel.get('gs')} / अंक]।
ढांचा: 📌 भूमिका, 📊 मुख्य विश्लेषणात्मक आयाम (3 बिंदु), 🚀 आगे की राह, ⚖️ संतुलित प्रशासनिक निष्कर्ष।
केवल शुद्ध हिंदी में लिखें।
"""
            r2 = await asyncio.to_thread(call_gemini_safely, p2)

            await wait_m.edit_text("⏳ [■■■■■■■■□□] 85% भाग 3/3: वर्ष 2016 से 2013 तक के PYQs का संकलन जारी...")
            p3 = f"""
UPSC CSE मुख्य परीक्षा {gs_paper} के वर्ष 2016, 2015, 2014 एवं 2013 के सभी प्रमुख प्रश्नों का संपूर्ण संकलन करें।
प्रत्येक प्रश्न पर स्पष्ट टैग: [UPSC CSE वर्ष / GS {sel.get('gs')} / अंक]।
ढांचा: 📌 भूमिका, 📊 मुख्य विश्लेषणात्मक आयाम (3 बिंदु), 🚀 आगे की राह, ⚖️ संतुलित प्रशासनिक निष्कर्ष।
केवल शुद्ध हिंदी में लिखें।
"""
            r3 = await asyncio.to_thread(call_gemini_safely, p3)
            combined_text = f"{r1}\n\n<hr style='border:2px solid #0284c7; margin:30px 0;'>\n\n{r2}\n\n<hr style='border:2px solid #0284c7; margin:30px 0;'>\n\n{r3}"
            topic = f"UPSC CSE {gs_paper} — संपूर्ण PYQs महा-संग्रह (2013 से 2026)"

        else:
            cnt_desc = f"{cnt_raw} प्रश्न"
            await wait_m.edit_text(f"⏳ [■■■■■■□□□□] 60% {gs_paper} के {cnt_desc} मॉडल उत्तर-लेखन मॉड्यूल का संश्लेषण जारी...")
            tag_inst = f"[UPSC CSE PYQ / GS {sel.get('gs')} / 15 अंक]" if is_pyq else f"[संभावित मॉडल प्रश्न / GS {sel.get('gs')} / 15 अंक]"
            p_single = f"""
आप UPSC मुख्य परीक्षा के शीर्ष विशेषज्ञ हैं।
विषय: {gs_paper} के {cnt_desc} उच्च-स्तरीय उत्तर-लेखन मॉड्यूल तैयार करें।
टैग निर्देश: प्रत्येक प्रश्न पर लिखें: {tag_inst}

सख्त नियम:
1. पाठ्यक्रम संदर्भ: प्रत्येक प्रश्न के साथ संबंधित GS पेपर एवं आधिकारिक सिलेबस टॉपिक भी स्पष्ट मेंशन करें।
2. विस्तृत उत्तर ढांचा:
   - 📌 भूमिका (Introduction)
   - 📊 मुख्य विश्लेषणात्मक आयाम (Body): 3 स्पष्ट उप-शीर्षक
   - 🚀 आगे की राह (Way Forward)
   - ⚖️ संतुलित प्रशासनिक निष्कर्ष
भाषा केवल शुद्ध हिंदी रखें।
"""
            combined_text = await asyncio.to_thread(call_gemini_safely, p_single)
            topic = f"UPSC Mains Module — GS {sel.get('gs')} ({cnt_desc})"

        await wait_m.edit_text("⏳ [■■■■■■■■■□] 95% 360° मास्टर HTML फाइल असेंबल हो रही है...")
        filename = f"UPSC_Mains_GS{sel.get('gs')}_{cnt_raw}.html"
        html_out = build_standalone_master_html(topic, combined_text)

        with open(filename, "wb") as f:
            f.write(html_out.encode("utf-8"))

        await wait_m.edit_text("⏳ [■■■■■■■■■■] 100% मुख्य परीक्षा मॉड्यूल तैयार!")

        with open(filename, "rb") as send_doc:
            await context.bot.send_document(
                chat_id=user_id,
                document=send_doc,
                filename=filename,
                caption=(
                    f"📝 <b>UPSC मुख्य परीक्षा संग्रह:</b> <code>{topic}</code>\n"
                    f"🎯 <b>कवरेज:</b> 2013-2026 संपूर्ण आधिकारिक प्रश्न एवं मॉडल उत्तर-ढांचा\n"
                    f"👤 <b>संचालक:</b> {AUTHOR_NAME}\n"
                    f"📢 <b>ग्रुप:</b> {CHANNEL_NAME}"
                ),
                parse_mode=ParseMode.HTML
            )
        if os.path.exists(filename):
            os.remove(filename)
        await wait_m.delete()

    except Exception as e:
        await wait_m.edit_text(f"❌ त्रुटि: {e}। कृपया पुनः प्रयास करें।")

# ================= उत्तर-पुस्तिका मूल्यांकन (/checkanswer) =================
@ensure_auth
async def check_answer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        ["📜 विगत वर्ष का प्रश्न (PYQ 2013-2026)"],
        ["✍️ नया / मॉडल प्रश्न (New Expected)"],
        ["🔙 वापस जाएँ (Back)"]
    ]
    await update.message.reply_text(
        "📝 <b>UPSC मुख्य परीक्षा उत्तर पुस्तिका मूल्यांकन</b>\n\n"
        "👉 <b>चरण 1/2:</b> आप किस प्रकार के प्रश्न की जांच करवाना चाहते हैं? (नीचे दिए गए बटन पर टैप करें):",
        reply_markup=ReplyKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return CA_CHOOSE_TYPE

async def handle_ca_type_choice_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    user_id = update.effective_user.id

    if "वापस जाएँ" in txt or "Back" in txt:
        await update.message.reply_text("मुख्य मेनू पर वापस आ गए हैं।", reply_markup=ReplyKeyboardRemove())
        await start_handler(update, context)
        return ConversationHandler.END

    is_pyq = ("PYQ" in txt or "विगत वर्ष" in txt)
    CHECK_ANSWER_CACHE[user_id] = {"is_pyq": is_pyq}

    prompt_msg = (
        "📜 <b>विगत वर्ष का प्रश्न (PYQ 2013-2026):</b>\n\n"
        "👉 <b>अब अपना प्रश्न भेजें:</b>\n"
        "• टेक्स्ट लिखकर भेजें\n"
        "• या बोलकर वॉयस नोट रिकॉर्ड करें\n"
        "• या प्रश्न की फ़ोटो भेजें!\n\n"
        "<i>💡 AI मुख्य परीक्षक प्रश्न को पहचानकर उसके वास्तविक वर्ष और आधिकारिक अंकों (10 या 15 अंक) का स्वतः निर्धारण करेगा।</i>"
    ) if is_pyq else (
        "✍️ <b>नया / मॉडल प्रश्न (New Expected):</b>\n\n"
        "👉 <b>अब अपना प्रश्न भेजें:</b>\n"
        "• टेक्स्ट लिखकर भेजें\n"
        "• या बोलकर वॉयस नोट रिकॉर्ड करें\n"
        "• या प्रश्न की फ़ोटो भेजें!\n\n"
        "<i>💡 AI मुख्य परीक्षक प्रश्न की प्रकृति और शब्द-सीमा के आधार पर अंकों का स्वतः निर्धारण करेगा।</i>"
    )

    await update.message.reply_text(prompt_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    return CA_QUESTION_INPUT

async def handle_ca_question_input_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message

    if msg.text and msg.text.strip().lower() in ["/cancel", "cancel", "रद्द"]:
        CHECK_ANSWER_CACHE.pop(user_id, None)
        await msg.reply_text("मूल्यांकन प्रक्रिया रद्द कर दी गई।", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    q_content = ""
    if msg.text:
        q_content = msg.text.strip()
    elif msg.voice or msg.audio:
        wait_m = await msg.reply_text("⏳ [■■■□□□□□□□] 30% प्रश्न का ऑडियो सुना जा रहा है...")
        try:
            f_obj = await (msg.voice or msg.audio).get_file()
            f_bytes = await f_obj.download_as_bytearray()
            q_content = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ ऑडियो पढ़ने में त्रुटि: {e}। कृपया लिखकर भेजें।")
            return CA_QUESTION_INPUT
    elif msg.photo:
        wait_m = await msg.reply_text("⏳ [■■■□□□□□□□] 30% प्रश्न की फ़ोटो स्कैन की जा रही है...")
        try:
            f_obj = await msg.photo[-1].get_file()
            f_bytes = await f_obj.download_as_bytearray()
            q_content = await asyncio.to_thread(call_gemini_multimodal_inline, "इस फ़ोटो में लिखे UPSC प्रश्न को निकालें।", bytes(f_bytes), "image/jpeg")
            await wait_m.delete()
        except Exception:
            q_content = "संलग्न फ़ोटो में दिया गया प्रश्न"

    if len(q_content) < 4:
        await msg.reply_text("⚠️ <b>कृपया एक वैध UPSC मुख्य परीक्षा का प्रश्न दर्ज करें।</b>", parse_mode=ParseMode.HTML)
        return CA_QUESTION_INPUT

    sess = CHECK_ANSWER_CACHE.get(user_id, {"is_pyq": False})
    sess["question"] = q_content
    CHECK_ANSWER_CACHE[user_id] = sess

    await msg.reply_text(
        f"✅ <b>प्रश्न सफलतापूर्वक दर्ज हुआ:</b>\n<i>\"{q_content[:200]}...\"</i>\n\n"
        "👉 <b>चरण 2/2: अब अपना उत्तर भेजें:</b>\n"
        "• अपनी लिखी हुई <b>उत्तर-पुस्तिका की साफ़ फ़ोटो या PDF</b> भेजें\n"
        "• या अपना उत्तर सीधे <b>वॉयस नोट (बोलकर)</b> रिकॉर्ड करके भेजें!\n\n"
        "<i>💡 मुख्य परीक्षक उत्तर में बने मानचित्रों, आरेखों, फ़्लोचार्ट्स, डेटा और कमियों की अत्यंत सख्त जांच करेगा।</i>",
        parse_mode=ParseMode.HTML
    )
    return CA_ANSWER_COPY

async def handle_ca_answer_copy_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message
    sess = CHECK_ANSWER_CACHE.get(user_id, {})
    q_text = sess.get("question", "UPSC मुख्य परीक्षा प्रश्न")
    is_pyq = sess.get("is_pyq", False)

    wait_m = await msg.reply_text("⏳ [■■□□□□□□□□] 20% उत्तर पुस्तिका प्राप्त हुई, सामग्री लोड हो रही है...", parse_mode=ParseMode.HTML)

    pyq_note = "यह UPSC विगत वर्षों (2013-2026) का प्रश्न है। प्रश्न को पहचानकर उसके वास्तविक वर्ष और आधिकारिक अंकों (10 अंक या 15 अंक) के आधार पर ही सटीक अंक दें।" if is_pyq else "प्रश्न के स्तर और शब्द-सीमा का स्वयं विश्लेषण करके तय करें कि यह 10 अंक का प्रश्न है या 15 अंक का।"

    prompt = f"""
आप संघ लोक सेवा आयोग (UPSC CSE Mains) के सबसे वरिष्ठ और सख्त मुख्य परीक्षक (Chief Copy Evaluator) हैं।
प्रश्न: "{q_text}"
{pyq_note}

सख्त मूल्यांकन निर्देश:
1. प्रश्न के मानक के आधार पर कुल अंक (10 अंक या 15 अंक) स्वयं निर्धारित करें।
2. अत्यंत सख्त और वास्तविक UPSC मानकों पर निष्पक्ष जांच करें (साधारण उत्तर पर 30-40% से अधिक अंक न दें)।
3. आरेख एवं मानचित्र (Diagrams & Maps) का विशेष मूल्यांकन:
   - उत्तर में यदि फ़्लोचार्ट, वेन डायग्राम या भारत/विश्व का मानचित्र बनाया गया है, तो उसकी सटीकता की जांच करें।
   - यदि प्रश्न में भौगोलिक, सामरिक या आर्थिक स्थल शामिल हैं और छात्र ने मानचित्र/डायग्राम नहीं बनाया है, तो स्पष्ट लिखें कि यहाँ कौन सा मानचित्र या फ़्लोचार्ट अनिवार्य था और उसके लिए कितने अंक काटे गए हैं।
4. प्रारूप:
   - 🎯 निर्धारित अंक पैमाना: (उदा. 10 अंक / 150 शब्द या 15 अंक / 250 शब्द)
   - 📊 प्राप्तांक (Marks Awarded): (उदा. 3.5 / 10 अंक या 5.5 / 15 अंक)
   - 🌟 सकारात्मक पक्ष (Strengths): (भूमिका, संरचना, प्रासंगिक बिंदु)
   - 🗺️ मानचित्र व आरेख विश्लेषण (Maps & Diagrams): (चित्रों की उपस्थिति, सटीकता अथवा गैर-मौजूदगी पर टिप्पणी)
   - ⚠️ गंभीर संरचनात्मक कमियाँ (Areas of Improvement): (डेटा, केस लॉ, अनुच्छेद, आयोगों की सिफारिशों का अभाव)
   - 🚀 परीक्षक की मूल्य संवर्धन सलाह (Value Addition): (आगे की राह व संतुलित निष्कर्ष को टॉपर स्तर का बनाने के सुझाव)

केवल और केवल शुद्ध, गरिमापूर्ण एवं अकादमिक हिंदी में उत्तर दें।
"""
    try:
        await wait_m.edit_text("⏳ [■■■■■□□□□□] 50% हस्तलेखन, मानचित्र व तार्किक संरचना का स्कैनिंग जारी...")

        clean_eval = ""
        if msg.voice or msg.audio:
            f_obj = await (msg.voice or msg.audio).get_file()
            f_bytes = await f_obj.download_as_bytearray()
            candidate_ans = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
            full_prompt = f"{prompt}\n\nउम्मीदवार का मौखिक उत्तर (Transcribed Answer):\n\"{candidate_ans}\""
            eval_result = await asyncio.to_thread(call_gemini_safely, full_prompt)
            clean_eval = clean_all_markdown_and_fix_content(eval_result)
        else:
            m_type = "application/pdf" if (msg.document and msg.document.file_name.lower().endswith('.pdf')) else "image/jpeg"
            doc_obj = msg.document or (msg.photo[-1] if msg.photo else None)
            f_obj = await doc_obj.get_file()
            f_bytes = await f_obj.download_as_bytearray()
            eval_result = await asyncio.to_thread(call_gemini_multimodal_inline, prompt, bytes(f_bytes), m_type)
            clean_eval = clean_all_markdown_and_fix_content(eval_result)

        await wait_m.edit_text("⏳ [■■■■■■■■■□] 90% मूल्य संवर्धन एवं अंतिम अंक तालिका तैयार हो रही है...")
        await wait_m.delete()

        if len(clean_eval) > 3800:
            for p in [clean_eval[i:i+3800] for i in range(0, len(clean_eval), 3800)]:
                await msg.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text(clean_eval, parse_mode=ParseMode.HTML)

    except Exception as e:
        await wait_m.edit_text(f"❌ मूल्यांकन में त्रुटि: {e}। कृपया साफ़ फ़ोटो, PDF या वॉयस मैसेज भेजें।")

    CHECK_ANSWER_CACHE.pop(user_id, None)
    return ConversationHandler.END

# ================= मेंटरशिप सत्र (/ask) =================
@ensure_auth
async def start_ask_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🎓 <b>UPSC 1-on-1 मेंटरशिप सत्र सक्रिय हो गया है!</b>\n\n"
        "आप UPSC सिविल सेवा परीक्षा (GS 1-4, करेंट अफेयर्स, वैकल्पिक विषय व निबंध) से जुड़ा कोई भी सवाल <b>टेक्स्ट लिखकर या वॉयस मैसेज बोलकर</b> लगातार पूछते रह सकते हैं।\n\n"
        "👉 <i>सत्र समाप्त करने के लिए कभी भी <code>/cancel</code> या <code>/stop</code> भेजें।</i>",
        parse_mode=ParseMode.HTML
    )
    return WAITING_ASK_SESSION

async def handle_ask_continuous_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    user_query = ""

    if msg.text:
        user_query = msg.text.strip()
        if user_query.lower() in ["/cancel", "/stop", "/exit", "cancel", "stop", "exit", "रद्द", "बंद"]:
            await update.message.reply_text("✅ <b>मेंटरशिप सत्र समाप्त हुआ।</b> अध्ययन जारी रखें और शुभकामनाएं!", parse_mode=ParseMode.HTML)
            return ConversationHandler.END
    elif msg.voice or msg.audio:
        wait_m = await msg.reply_text("🎧 आपका वॉयस सवाल सुना जा रहा है...")
        try:
            f_obj = await (msg.voice or msg.audio).get_file()
            f_bytes = await f_obj.download_as_bytearray()
            user_query = await asyncio.to_thread(call_gemini_audio_transcribe, bytes(f_bytes), "audio/ogg")
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ वॉयस समझने में समस्या: {e}। कृपया लिखकर पूछें।")
            return WAITING_ASK_SESSION

    blocked_non_upsc = [
        r"मेरा नाम", r"तुम्हारा नाम", r"आपका नाम", r"तुम कौन", r"आप कौन",
        r"हेलो", r"हाय", r"hello", r"hi", r"hey", r"कैसे हो", r"क्या कर रहे",
        r"शायरी", r"मजाक", r"मौसम", r"गाना", r"लव", r"प्यार", r"गर्लफ्रेंड",
        r"बॉयफ्रेंड", r"joke", r"time pass"
    ]
    if any(re.search(pat, user_query, re.IGNORECASE) for pat in blocked_non_upsc) or len(user_query) < 4:
        await update.message.reply_text(
            "⚠️ <b>अमान्य प्रश्न:</b> यह डेस्क केवल <b>संघ लोक सेवा आयोग (UPSC CSE)</b> पाठ्यक्रम के गंभीर अकादमिक विमर्श हेतु समर्पित है। कृपया परीक्षा संबंधी विषय ही पूछें।",
            parse_mode=ParseMode.HTML
        )
        return WAITING_ASK_SESSION

    wait_msg = await update.message.reply_text("⏳ [■■■■□□□□□□] 40% UPSC परिप्रेक्ष्य में बिंदुवार विश्लेषण तैयार हो रहा है...")
    try:
        prompt = f"""
आप UPSC मेंटर हैं। निम्नलिखित विषय का बिंदुवार, सटीक एवं संतुलित प्रशासनिक विश्लेषण दें:
विषय: '{user_query}'
सख्त नियम:
- संबंधित GS पेपर एवं आधिकारिक सिलेबस उप-विषय (Micro-Topic) स्पष्ट मेंशन करें।
- मार्कडाउन स्टार्स का प्रयोग न करें। भाषा केवल शुद्ध हिंदी रखें।
"""
        reply_text = await asyncio.to_thread(call_gemini_safely, prompt)
        clean_reply = clean_all_markdown_and_fix_content(reply_text)

        await wait_msg.delete()
        if len(clean_reply) > 3800:
            for p in [clean_reply[i:i+3800] for i in range(0, len(clean_reply), 3800)]:
                await update.message.reply_text(p, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(clean_reply, parse_mode=ParseMode.HTML)
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
        prompt = f"आज {today} के संदर्भ में UPSC CSE परीक्षा हेतु 9 सबसे महत्वपूर्ण ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. [GS पेपर / सिलेबस टॉपिक] - मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"
    elif tr_type == "monthly":
        scope_str = f"माह ({current_month})"
        prompt = f"माह {current_month} के 9 सबसे महत्वपूर्ण नीतिगत, अंतर्राष्ट्रीय एवं पर्यावरणीय ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. [GS पेपर / सिलेबस टॉपिक] - मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"
    else:
        scope_str = f"वर्ष {current_year}"
        prompt = f"वर्ष {current_year} के 9 सबसे बड़े राष्ट्रीय व वैश्विक ट्रेंडिंग मुद्दे प्रत्येक पंक्ति में '1. [GS पेपर / सिलेबस टॉपिक] - मुद्दा नाम - 2 पंक्ति सारांश' के प्रारूप में लिखें। केवल हिंदी में लिखें।"

    wait_m = await query.message.reply_text(f"🛰 [■■■■□□□□□□] 40% <b>{scope_str}</b> के ट्रेंडिंग मुद्दों का रडार संकलन जारी...", parse_mode=ParseMode.HTML)
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
    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back") ] )
    await update.message.reply_text("📁 <b>जिस महीने का संपूर्ण UPSC मंथली कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    years = ["2026", "2025", "2024"]
    keyboard = [[InlineKeyboardButton(f"📚 वर्ष {y} वार्षिक महा-संकलन (PT-365)", callback_data=f"genyear_{y}")] for y in years]
    keyboard.append([InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back") ] )
    await update.message.reply_text("🏛️ <b>जिस वर्ष का संपूर्ण UPSC वार्षिक कंपाइलेशन (PT-365 Style) चाहिए, उस पर क्लिक करें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

@ensure_auth
async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = get_ist_now()
    days_since_monday = today.weekday()
    start_of_current_week = today - timedelta(days=days_since_monday)
    current_week_str = f"{start_of_current_week.strftime('%d %b')} से {today.strftime('%d %b %Y')}"

    prev_week_end = start_of_current_week - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)
    prev_week_str = f"{prev_week_start.strftime('%d %b')} से {prev_week_end.strftime('%d %b %Y')}"

    keyboard = [
        [InlineKeyboardButton(f"🗓 चालू सप्ताह ({current_week_str})", callback_data=f"genweek_current_{today.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton(f"🗓 पिछला सप्ताह ({prev_week_str})", callback_data=f"genweek_prev_{prev_week_end.strftime('%Y-%m-%d')}")],
        [InlineKeyboardButton("🔙 वापस जाएँ (Back)", callback_data="root_back")]
    ]
    await update.message.reply_text("🗓 <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ================= DYNAMIC GENERATION PROCESSOR (ऑप्टिमाइज़्ड प्रॉम्प्ट - नो स्टकिंग) =================
async def handle_dynamic_generation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    if data == "root_back":
        try:
            await query.message.delete()
        except Exception:
            pass
        await start_handler(update, context)
        return

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
                text=f"🏛 <b>UPSC STUDY DESK</b>\n\n📅 <b>दिनांक:</b> <code>{target_date}</code>\n⏳ [■■□□□□□□□□] 20% The Hindu, PIB व Vision IAS से डेटा संकलन प्रारंभ...",
                parse_mode=ParseMode.HTML
            )
            prompt = f"""
तारीख: "{target_date}" के लिए संपूर्ण, 360° और विश्लेषणात्मक UPSC समसामयिक महा-संकलन तैयार करें।
स्रोत: The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS।

अनिवार्य निर्देश (सिलेबस मैपिंग):
1. प्रत्येक मुख्य खबर पर सिलेबस बॉक्स दें:
   - 📑 संबंधित पेपर: (उदा. GS-2 / GS-3)
   - 🎯 आधिकारिक पाठ्यक्रम विषय: (उदा. 'बुनियादी ढांचा', 'संवैधानिक संशोधन', 'जैव विविधता')
2. GS-1 से GS-3 के सभी प्रमुख घटनाक्रम, तुलनात्मक 2-कॉलम तालिकाएँ, और चर्चित भौगोलिक स्थल शामिल करें।
3. अंत में 1 मेन्स मॉडल प्रश्न ढांचा और 5 मानक अभ्यास MCQs दें।
भाषा केवल शुद्ध और गंभीर हिंदी रखें।
"""
            try:
                await wait_m.edit_text(f"🏛 <b>UPSC STUDY DESK</b>\n\n📅 <b>दिनांक:</b> <code>{target_date}</code>\n⏳ [■■■■■■□□□□] 60% पाठ्यक्रम मैपिंग व 360° विश्लेषण का संश्लेषण जारी...", parse_mode=ParseMode.HTML)
                ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
                
                await wait_m.edit_text(f"🏛 <b>UPSC STUDY DESK</b>\n\n📅 <b>दिनांक:</b> <code>{target_date}</code>\n⏳ [■■■■■■■■■□] 90% मास्टर HTML फाइल असेंबल हो रही है...", parse_mode=ParseMode.HTML)
                topic = f"दैनिक समसामयिक महा-संकलन — {target_date}"
                filename = f"UPSC_Notes_{target_date.replace('-', '')}.html"
                
                html_content = build_standalone_master_html(topic, ai_text, date_str=target_date)
                save_to_archive("daily", topic, html_content, target_date)
                await wait_m.delete()
            except Exception as e:
                await wait_m.edit_text(f"❌ त्रुटि: {e}। कृपया पुनः प्रयास करें।")
                return

    elif data.startswith("genmonth_"):
        m_name = data.split("_")[1]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"📁 <b>{m_name}</b>\n⏳ [■■■□□□□□□□] 30% मासिक डाइजेस्ट संकलित हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"""
माह: '{m_name}' का सम्पूर्ण, 360° और अत्यंत विस्तृत UPSC Monthly Digest तैयार करें।
स्रोत: The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS।

प्रत्येक खंड में संबंधित GS पेपर (1, 2, 3) एवं आधिकारिक यूपीएससी सिलेबस टॉपिक का स्पष्ट उल्लेख करें:
- GS-1, GS-2 व GS-3 के बड़े नीतिगत व आर्थिक मुद्दे
- चर्चित स्थल एवं मैपिंग
- 10 मानक प्रीलिम्स MCQs व्याख्या सहित।
केवल शुद्ध हिंदी में लिखें।
"""
        try:
            await wait_m.edit_text(f"📁 <b>{m_name}</b>\n⏳ [■■■■■■■□□□] 70% GS 1-3 व प्रीलिम्स MCQs का संश्लेषण जारी...", parse_mode=ParseMode.HTML)
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
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ वर्ष <b>{y_name}</b>\n[■■■□□□□□□□] 30% वार्षिक महा-संकलन (PT-365) तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"""
वर्ष {y_name} का UPSC CSE हेतु अत्यंत विस्तृत और संपूर्ण Annual Compendium (PT-365 Style) तैयार करें।
स्रोत: The Hindu, Indian Express, PIB, Vision IAS, Drishti IAS।
प्रत्येक विषय पर GS पेपर और सिलेबस टॉपिक स्पष्ट मेंशन करें।
केवल शुद्ध हिंदी में लिखें।
"""
        try:
            await wait_m.edit_text(f"⏳ वर्ष <b>{y_name}</b>\n[■■■■■■■□□□] 70% प्रमुख राष्ट्रीय व वैश्विक घटनाक्रमों का संकलन जारी...", parse_mode=ParseMode.HTML)
            ai_text = await asyncio.to_thread(call_gemini_safely, prompt)
            topic = f"UPSC Annual Compendium — {y_name}"
            filename = f"UPSC_Annual_{y_name}.html"
            html_content = build_standalone_master_html(topic, ai_text, date_str=y_name)
            await wait_m.delete()
        except Exception as e:
            await wait_m.edit_text(f"❌ त्रुटि: {e}")
            return

    elif data.startswith("genweek_"):
        parts = data.split("_")
        w_date = parts[2]
        wait_m = await context.bot.send_message(chat_id=user_id, text=f"⏳ [■■■■□□□□□□] 40% साप्ताहिक संकलन तैयार हो रहा है...", parse_mode=ParseMode.HTML)
        prompt = f"""
सप्ताह संदर्भ: '{w_date}' का संपूर्ण साप्ताहिक UPSC क्विक रिवीजन नोट्स तैयार करें।
स्रोत: The Hindu, PIB, Indian Express, Vision IAS।
प्रत्येक GS पेपर (1, 2, 3) के सप्ताह भर के सबसे निर्णायक बिंदु, सिलेबस टैग्स, चर्चित स्थान और 5 अभ्यास प्रश्न शामिल करें।
केवल शुद्ध हिंदी में लिखें।
"""
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
                f"🎯 <b>सुविधा:</b> यूपीएससी सिलेबस एवं माइक्रो-टॉपिक मैपिंग शामिल\n"
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

    if not is_authorized(user_id):
        user_link = get_tg_user_link(user_id, update.effective_user.first_name)
        await msg.reply_text(
            f"👋 <b>नमस्ते {user_link}!</b>\n\n"
            "🔒 <b>प्रीमियम यूपीएससी डेस्क — एक्सेस प्रतिबंधित</b>\n\n"
            "⚠️ यह पोर्टल केवल <b>प्रीमियम सदस्यों</b> के लिए सुरक्षित है। सभी कमांड्स और फीचर्स अनलॉक करने के लिए ओनर से संपर्क करें।\n\n"
            f"🆔 <b>आपकी टेलीग्राम ID:</b> <code>{user_id}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=get_free_user_access_markup(user_id)
        )
        return

    user_input = msg.text.strip().lower()
    today = get_ist_now().strftime("%d %B %Y")
    cached_list = TRENDING_CACHE.get(user_id, [])

    if user_input == "all" and cached_list:
        raw_trend = "\n".join(cached_list)
        wait_m = await msg.reply_text("⏳ [■■■■□□□□□□] 40% सभी ट्रेंडिंग मुद्दों के 360° नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
        prompt = f"नीचे दिए गए सभी ट्रेंडिंग मुद्दों पर UPSC स्तर के गहन और 360° संपूर्ण नोट्स सिलेबस टैग्स सहित तैयार करें:\n{raw_trend}\nकेवल शुद्ध हिंदी में लिखें।"
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
        wait_m = await msg.reply_text(f"⏳ [■■■■□□□□□□] 40% चुने गए ट्रेंडिंग मुद्दे ({', '.join(nums)}) का 360° विश्लेषण जारी...", parse_mode=ParseMode.HTML)
        raw_trend = "\n".join(cached_list)
        prompt = f"सूची में से क्रमांक {', '.join(nums)} पर मौजूद मुद्दों का UPSC हेतु 360° विश्लेषण सिलेबस मैपिंग सहित तैयार करें:\n{raw_trend}\nकेवल हिंदी में लिखें।"
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
        user_link = get_tg_user_link(user_id, update.effective_user.first_name)
        await msg.reply_text(
            f"⛔ <b>एक्सेस अस्वीकृत {user_link}:</b> PDF प्रोसेसिंग केवल प्रीमियम सदस्यों के लिए उपलब्ध है।\n\n"
            f"🆔 <b>आपकी टेलीग्राम ID:</b> <code>{user_id}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=get_free_user_access_markup(user_id)
        )
        return

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        return

    wait_m = await msg.reply_text("📥 [■■■■□□□□□□] 40% PDF सामग्री निकाली जा रही है व UPSC 360° नोट्स तैयार किए जा रहे हैं...", parse_mode=ParseMode.HTML)
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
        prompt = f"नीचे दी गई PDF सामग्री का UPSC सिविल सेवा स्तर पर 360° अध्ययन नोट्स सिलेबस टैगिंग, शुद्ध HTML सारणी व मेन्स फ्रेमवर्क सहित तैयार करें:\n{pdf_text[:4500]}\nकेवल हिंदी भाषा का प्रयोग करें।"
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

# ================= BROADCAST SYSTEM (स्वाइप रिप्लाई से डायरेक्ट ब्रॉडकास्ट सपोर्ट) =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल मुख्य व्यवस्थापक के लिए आरक्षित है।")
        return ConversationHandler.END

    msg = update.message
    # यदि एडमिन ने किसी संदेश पर स्वाइप करके रिप्लाई में सीधे /broadcast लिखा है:
    if msg.reply_to_message:
        target_msg = msg.reply_to_message
        all_uids = get_all_user_ids()
        status_m = await msg.reply_text(f"⏳ स्वाइप संदेश का डायरेक्ट ब्रॉडकास्ट जारी (कुल: {len(all_uids)} छात्र)...")
        
        succ = 0
        sent_map = {}
        for uid in all_uids:
            try:
                sent_obj = await context.bot.copy_message(chat_id=uid, from_chat_id=admin_id, message_id=target_msg.message_id)
                sent_map[uid] = sent_obj.message_id
                succ += 1
                await asyncio.sleep(0.04)
            except Exception:
                pass

        LAST_BROADCAST_DATA[admin_id] = sent_map
        await status_m.delete()

        keyboard = [
            [InlineKeyboardButton("📌 हाँ, सभी चैट में पिन करें", callback_data="pin_broadcast_yes")],
            [InlineKeyboardButton("❌ नहीं, सामान्य रहने दें", callback_data="pin_broadcast_no")]
        ]
        await msg.reply_text(
            f"✅ डायरेक्ट ब्रॉडकास्ट सफल: <b>{succ} / {len(all_uids)}</b> छात्रों को संदेश प्राप्त हुआ।\n\n"
            "👉 <b>क्या आप इस संदेश को सभी छात्रों के चैट में पिन (Pin) करना चाहते हैं?</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    # यदि सादा /broadcast भेजा है तो स्टेप-बाय-स्टेप इनपुट मांगना
    await update.message.reply_text(
        f"📢 <b>ब्रॉडकास्ट कंट्रोल रूम ({AUTHOR_NAME}):</b>\n\n"
        "सभी छात्रों को भेजा जाने वाला संदेश, इमेज या पीडीएफ भेजें:\n"
        "<i>(टिप: आप किसी भी पुराने मैसेज/वीडियो पर स्वाइप करके रिप्लाई में सीधे <code>/broadcast</code> लिखकर भी भेज सकते हैं!)</i>\n"
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
            await asyncio.sleep(0.04)
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

# ================= ADMIN USER MANAGEMENT =================
async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल मुख्य व्यवस्थापक के लिए आरक्षित है।")
        return
    if len(context.args) < 2:
        await update.message.reply_text("💡 उपयोग: <code>/adduser &lt;user_id&gt; &lt;दिन&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        t_uid = int(context.args[0])
        days = int(context.args[1])
        add_vip_user(t_uid, days)
        expiry_dt = get_ist_now() + timedelta(days=days)
        exp_formatted = expiry_dt.strftime('%d %B %Y, %I:%M %p')
        user_link = get_tg_user_link(t_uid, str(t_uid))

        await update.message.reply_text(
            f"✅ छात्र {user_link} को <b>{days} दिन</b> के लिए अधिकृत कर दिया गया है।\n"
            f"⏳ वैधता: <code>{exp_formatted}</code> (IST)",
            parse_mode=ParseMode.HTML
        )

        congrats_msg = (
            "🎉 <b>बधाई हो! आपका प्रीमियम यूपीएससी डेस्क सक्रिय हो गया है।</b>\n\n"
            f"👑 <b>व्यवस्थापक:</b> {AUTHOR_NAME}\n"
            f"📅 <b>सब्सक्रिप्शन अवधि:</b> <code>{days} दिन</code>\n"
            f"⏳ <b>वैधता (Expiry Date):</b> <code>{exp_formatted} (IST)</code>\n\n"
            "🌟 <b>अनलॉक किए गए मुख्य फीचर्स:</b>\n"
            "• <code>/daily</code> — 360° दैनिक समसामयिक महा-संकलन (सिलेबस टैग्स सहित)\n"
            "• <code>/quiz</code> — 1 लाख+ बैंक से विजन IAS स्टाइल लाइव मॉक टेस्ट (50 व 100 प्रश्न)\n"
            "• <code>/mains</code> — 2013-2026 संपूर्ण PYQs व मॉडल उत्तर-ढांचा\n"
            "• <code>/checkanswer</code> — सख्त मुख्य परीक्षा कॉपी चेकिंग (मानचित्र व आरेख स्कैनिंग)\n"
            "• <code>/interview</code> — 1-on-1 लाइव DAF साक्षात्कार (ऑडियो सहित)\n"
            "• <code>/ask</code> — 24/7 यूपीएससी मेंटरशिप (टेक्स्ट व वॉयस)\n\n"
            "👉 अभी शुरू करने के लिए <code>/start</code> दबाएं।\n"
            f"📢 आधिकारिक चैनल: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
        )
        try:
            await context.bot.send_message(
                chat_id=t_uid,
                text=congrats_msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as e:
            await update.message.reply_text(f"⚠️ यूज़र को बधाई संदेश नहीं भेजा जा सका: {e}")

    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def remove_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल मुख्य व्यवस्थापक के लिए आरक्षित है।")
        return
    if not context.args:
        await update.message.reply_text("💡 उपयोग: <code>/removeuser &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        t_uid = int(context.args[0])
        remove_vip_user(t_uid)
        user_link = get_tg_user_link(t_uid, str(t_uid))
        await update.message.reply_text(f"🚫 छात्र {user_link} का एक्सेस रद्द कर दिया गया है।", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

async def info_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल मुख्य व्यवस्थापक के लिए आरक्षित है।")
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
        user_link = get_tg_user_link(uid, fn or str(uid))
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
            name, state, dist, vill, college, stream, status, opt_sub, hobby, attempt, updated = daf_row
            info_text += (
                f"🏛 <b>दर्ज DAF (साक्षात्कार प्रोफाइल):</b>\n"
                f"• <b>पूरा नाम:</b> {name}\n"
                f"• <b>गृह राज्य:</b> {state}\n"
                f"• <b>गृह जिला:</b> {dist}\n"
                f"• <b>गांव/कस्बा:</b> {vill}\n"
                f"• <b>कॉलेज/स्ट्रीम:</b> {college} ({stream})\n"
                f"• <b>ग्रेजुएशन स्थिति:</b> {status}\n"
                f"• <b>वैकल्पिक विषय:</b> {opt_sub}\n"
                f"• <b>हॉबी:</b> {hobby}\n"
                f"• <b>तैयारी/प्रयास:</b> {attempt}\n"
                f"• <b>अंतिम अपडेट:</b> {updated.strftime('%d-%b-%Y') if updated else 'N/A'}"
            )
        else:
            info_text += "🏛 <b>दर्ज DAF:</b> इस छात्र ने अभी तक <code>/interview</code> कमांड नहीं चलाई है या अपनी DAF प्रोफाइल सेव नहीं की है।"

        await update.message.reply_text(info_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ विवरण निकालने में त्रुटि: {e}")

# ================= LIST USERS (प्रीमियम और फ्री यूज़र्स का स्पष्ट विभाजन) =================
async def list_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ यह कमांड केवल मुख्य व्यवस्थापक के लिए आरक्षित है।")
        return
        
    rows = get_all_users_detailed()
    
    vip_users = []
    free_users = []
    
    for uid, un, fn, is_vip, exp in rows:
        display_name = fn.strip() if (fn and fn.strip()) else str(uid)
        user_link = get_tg_user_link(uid, display_name)
        id_link = get_tg_user_link(uid, str(uid))
        
        if is_vip == 1:
            exp_str = f" | वैधता: {exp.strftime('%d-%b-%Y')}" if exp else ""
            vip_users.append(f"• 👑 {user_link} ({id_link}){exp_str}")
        else:
            free_users.append(f"• 👤 {user_link} ({id_link})")

    text = f"👥 <b>पंजीकृत सदस्य (कुल: {len(rows)})</b>\n\n"
    
    text += "👑 <b>प्रशासनिक संरक्षक (Owners):</b>\n"
    for aid in ADMIN_IDS:
        text += f"• <b>{ADMIN_NAMES.get(aid, 'व्यवस्थापक')}</b>: {get_tg_user_link(aid, str(aid))}\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    text += f"⭐ <b>सत्यापित प्रीमियम सदस्य ({len(vip_users)} छात्र):</b>\n"
    if vip_users:
        text += "\n".join(vip_users) + "\n\n"
    else:
        text += "<i>वर्तमान में कोई सक्रिय प्रीमियम सदस्य नहीं है।</i>\n\n"
        
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"👤 <b>निःशुल्क सदस्य ({len(free_users)} छात्र):</b>\n"
    if free_users:
        text += "\n".join(free_users) + "\n"
    else:
        text += "<i>कोई निःशुल्क सदस्य नहीं है।</i>\n"

    for part in [text[i:i+3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(part, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ================= ADMIN DIRECT REPLIES =================
async def handle_admin_reply_or_direct_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return

    if msg.reply_to_message:
        reply_to_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
        clean_search = re.sub(r'<[^>]+>', ' ', reply_to_text)
        match = re.search(r'(?:यूज़र\s*ID|ID|User|uid)[:\s]*([0-9]{8,11})', clean_search, re.IGNORECASE) or re.search(r'\b([0-9]{8,11})\b', clean_search)
        
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
    user_link = get_tg_user_link(user.id, user.first_name)
    CONTACT_SESSIONS[user.id] = time.time()
    await update.message.reply_text(
        f"⏱ <b>2 मिनट का समय सक्रिय है ({user_link})!</b>\n\n"
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

    user_link = get_tg_user_link(user.id, user.first_name)
    alert_text = (
        f"📩 <b>छात्र संदेश ({AUTHOR_NAME}):</b>\n\n"
        f"👤 प्रेषक: {user_link}\n"
        f"🆔 यूज़र ID: <code>{user.id}</code>\n"
        f"🔗 प्रोफाइल लिंक: {get_tg_user_link(user.id, f'tg://user?id={user.id}')}\n\n"
        f"💬 संदेश: {msg.text or '[मीडिया / वॉयस]'}\n\n"
        f"<i>(इस संदेश पर स्वाइप करके रिप्लाई करें)</i>"
    )

    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=alert_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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

# ================= BACKGROUND SERVER (KEEP-ALIVE) =================
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

    bot_app.add_handler(CallbackQueryHandler(copy_id_callback, pattern=r"^copyid_"))
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
            DAF_DISTRICT: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_district_step)],
            DAF_VILLAGE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_village_step)],
            DAF_COLLEGE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_college_step)],
            DAF_STREAM: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_stream_step)],
            DAF_STATUS: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_status_step)],
            DAF_OPTIONAL_STEP: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_optional_step)],
            DAF_HOBBY: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_daf_hobby_step)],
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
            CA_CHOOSE_TYPE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ca_type_choice_msg)],
            CA_QUESTION_INPUT: [MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO) & (~filters.COMMAND), handle_ca_question_input_step)],
            CA_ANSWER_COPY: [MessageHandler((filters.PHOTO | filters.Document.ALL | filters.VOICE | filters.AUDIO) & (~filters.COMMAND), handle_ca_answer_copy_submission)]
        },
        fallbacks=[CommandHandler("cancel", global_cancel)],
        allow_reentry=True
    )
    bot_app.add_handler(answer_check_conv)

    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", start_ask_session)],
        states={WAITING_ASK_SESSION: [MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO) & (~filters.COMMAND), handle_ask_continuous_message)]},
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
