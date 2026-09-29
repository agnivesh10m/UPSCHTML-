import asyncio
import base64
from datetime import datetime
import os
import re
import sqlite3
import time
from aiohttp import web
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ================= CONFIGURATION =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [1745425595, 7850454902]
CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "सचिन शर्मा"

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

  # डेटाबेस चेक: अगर खाली है तो पूरा वास्तविक UPSC कंटेंट इंजेक्ट करना
  c.execute("SELECT COUNT(*) FROM archive")
  if c.fetchone()[0] == 0:
    # 1. 29 सितंबर 2026 (Kashmir Eurasian Gateway)
    doc_29 = build_interactive_dashboard_html(
        "Kashmir as India’s Gateway to Eurasian Opportunity",
        """संदर्भ: हालिया विश्लेषण में जम्मू-कश्मीर और लद्दाख को केवल सुरक्षा-केंद्रित क्षेत्र के बजाय भारत और मध्य एशिया/यूरेशिया के बीच आर्थिक एवं कनेक्टिविटी सेतु के रूप में विकसित करने की संभावना पर चर्चा की गई है।
1. ऐतिहासिक पृष्ठभूमि — Kashmir as a Crossroads
• कश्मीर और लद्दाख ऐतिहासिक रूप से Silk Route के महत्वपूर्ण हिस्से रहे हैं।
• इन मार्गों ने दक्षिण एशिया को तिब्बत और मध्य एशिया से जोड़ा।
• व्यापार के साथ-साथ विचारों, संस्कृति, साहित्य और शिल्प का भी आदान-प्रदान हुआ।
• 1947 के बाद विभाजन और LoC/LAC से जुड़ी परिस्थितियों ने पारंपरिक trans-Himalayan routes को बाधित किया।
2. क्यों महत्वपूर्ण है Eurasian Connectivity?
• भारत के लिए Central Asia महत्वपूर्ण है: ऊर्जा + Critical Minerals + व्यापार + रणनीतिक सुरक्षा।
• Connectivity → Trucking → Warehousing → Cold Chains → Trade Finance → Local Employment
• कश्मीर के स्थानीय उत्पादों (Horticulture, Saffron, Handicrafts) को यूरेशियाई बाजारों तक सीधी पहुंच मिल सकती है।
3. प्रमुख सामरिक चुनौतियाँ
• पाकिस्तान और चीन से जुड़ी कूटनीतिक और क्षेत्रीय सीमा संवेदनशीलताएं (Territorial Sensitivities)।
• हिमालयी क्षेत्र का कठिन भूगोल, भारी बर्फबारी, भूस्खलन और भूकंपीय संवेदनशीलता।
• सीमा-पार सुरक्षा जोखिम: नशीले पदार्थों की तस्करी और सीमा पार घुसपैठ की आशंकाएं।
4. आगे की राह (Way Forward)
• Phased Pilot Corridors: पहले सीमित और नियंत्रित व्यापारिक गलियारे शुरू किए जाएं।
• Smart Border Management: RFID ट्रैकिंग और नॉन-इंट्रूसीव कार्गो स्कैनर का उपयोग।
• SCO (शंघाई सहयोग संगठन) जैसे बहुपक्षीय मंचों पर क्षेत्रीय कनेक्टिविटी संवाद।
• चाबहार बंदरगाह और INSTC (International North-South Transport Corridor) के साथ समेकन।
📌 Prelims Facts
• Historic Silk Route संपर्क: कश्मीर व लद्दाख
• वैकल्पिक भारतीय पहलें: Chabahar Port + INSTC
• संबंधित बहुपक्षीय संगठन: SCO (Shanghai Cooperation Organisation)
📝 Mains Question — GS-II
"भारत के लिए जम्मू-कश्मीर और लद्दाख को यूरेशियाई कनेक्टिविटी गेटवे के रूप में विकसित करने की संभावनाओं और सामरिक चुनौतियों का परीक्षण कीजिए।" (250 शब्द)""",
    )

    # 2. 28 सितंबर 2026 (Right to Vote & EC)
    doc_28 = build_interactive_dashboard_html(
        "भारत में मतदान का अधिकार ও ECI सुधार",
        """संदर्भ: सितंबर 2026 में electoral-roll management और ECI की कार्यप्रणाली को लेकर उठी चिंताओं के बीच यह बहस तेज हुई है कि क्या मतदान के अधिकार को मौलिक अधिकार बनाया जाना चाहिए।
1. भारत में Right to Vote की वर्तमान संवैधानिक स्थिति
• संविधान के अनुच्छेद 326 (Article 326) के तहत वयस्क मताधिकार (Universal Adult Suffrage) का प्रावधान है।
• Right to Vote संविधान के Part III में प्रत्यक्ष मौलिक अधिकार नहीं है, बल्कि यह एक संवैधानिक एवं विधिक (Statutory) अधिकार है।
• 61वें संविधान संशोधन अधिनियम, 1988 द्वारा मतदान की आयु 21 वर्ष से घटाकर 18 वर्ष की गई थी।
2. Supreme Court का दृष्टिकोण (Kuldeep Nayar Case 2006)
• 5-जज संविधान पीठ ने स्पष्ट किया कि मतदान का अधिकार संसद द्वारा बनाए गए कानूनों (जैसे लोक प्रतिनिधित्व अधिनियम, 1951) द्वारा विनियमित होता है।
• मत देने का अधिकार केवल अभिव्यक्ति का साधन मात्र नहीं बल्कि स्वतंत्र वैधानिक विकल्प है।
3. Fundamental Right बनाने के पक्ष व विपक्ष
• पक्ष: मजबूत Constitutional Protection और मनमाने तरीके से नाम कटने से सुरक्षा।
• विपक्ष: Electoral roll management में अत्यधिक न्यायिक हस्तक्षेप (Judicial Litigation) की संभावना।
• अनुच्छेद 329(b) चुनावी मामलों में अदालतों के हस्तक्षेप पर सीमा तय करता है।
📌 महत्वपूर्ण Constitutional Articles
• Article 19(1)(a) → अभिव्यक्ति की स्वतंत्रता
• Article 324 → निर्वाचन आयोग का अधीक्षण, निदेशन और नियंत्रण
• Article 326 → वयस्क मताधिकार के आधार पर चुनाव
• Article 329(b) → निर्वाचन संबंधी मामलों में न्यायालयों के हस्तक्षेप का वर्जन
🎯 संभावित Prelims MCQ
प्रश्न: भारत में मतदान के अधिकार के संबंध में निम्नलिखित कथनों पर विचार कीजिए:
1. यह संविधान के भाग III के अंतर्गत एक मौलिक अधिकार है।
2. कुलदीप नायर बनाम भारत संघ (2006) में इसे वैधानिक अधिकार माना गया था।
उत्तर: केवल 2 सही है।""",
    )

    # 3. 27 सितंबर 2026 (Western Ghats ESA & UNGA)
    doc_27 = build_interactive_dashboard_html(
        "UPSC Daily Current Affairs — Western Ghats ESA & UNGA",
        """1. कर्नाटक द्वारा पश्चिमी घाट ESA मसौदे की अस्वीकृति
• कर्नाटक विधानमंडल ने पश्चिमी घाट के 20,668 वर्ग किमी क्षेत्र को Ecologically Sensitive Area (ESA) घोषित करने वाली केंद्र की 7वीं मसौदा अधिसूचना को खारिज किया।
• राज्य ने सेटेलाइट डेटा के बजाय ज़मीनी भौतिक सर्वेक्षण (Ground-truthing) हेतु एक वर्ष का समय माँगा।
• कस्तूरीरंगन समिति (2013) ने 37% क्षेत्र को ESA प्रस्तावित किया था, जबकि माधव गाडगिल समिति (2011) ने 64% क्षेत्र को संरक्षण में लाने की सिफारिश की थी।
• पश्चिमी घाट विश्व का प्रमुख जैव-विविधता हॉटस्पॉट (Biodiversity Hotspot) और यूनेस्को विश्व धरोहर स्थल है।
2. विदेश मंत्री का संयुक्त राष्ट्र महासभा (UNGA 81st Session) में संबोधन
• EAM एस. जयशंकर ने सीमा-पार आतंकवाद और संयुक्त राष्ट्र सुरक्षा परिषद (UNSC) सुधारों पर भारत का रुख स्पष्ट किया।
• UNGA के 81वें सत्र की अध्यक्षता बांग्लादेश द्वारा की गई।
3. अमेरिकी-चीनी शिखर वार्ता एवं AI Dialogue
• अमेरिका और चीन के मध्य $30 बिलियन के टैरिफ में कटौती तथा AI राष्ट्रीय सुरक्षा जोखिमों पर द्विपक्षीय संवाद पर सहमति।
4. न्यायिक निर्णय: POCSO Act बनाम Personal Law
• उच्च न्यायालय ने स्पष्ट किया कि POCSO Act, 2012 के बाल संरक्षण प्रावधान किसी भी पर्सनल लॉ से ऊपर हैं और इस कानून से कोई धार्मिक छूट नहीं दी जा सकती।
📌 5-Minute Rapid Prelims Facts
• पश्चिमी घाट से जुड़े 6 राज्य: गुजरात, महाराष्ट्र, गोवा, कर्नाटक, केरल, तमिलनाडु
• भारत का आर्कटिक अनुसंधान केंद्र: हिमाद्री (स्वालबार्ड, नॉर्वे)
• स्टेट डिजास्टर रिस्पांस फंड (SDRF): सामान्य राज्यों हेतु केंद्र-राज्य अनुपात 75:25 होता है।""",
    )

    # 4. मासिक एवं वार्षिक कंपाइलेशन
    doc_monthly = build_interactive_dashboard_html(
        "UPSC Monthly Current Affairs Digest — September 2026",
        """📚 UPSC मासिक संकलन — सितंबर 2026 (सम्पूर्ण माह का सार)
1. राजव्यवस्था एवं संविधान (Polity & Governance — GS-II)
• निर्वाचन आयोग में निर्णय प्रक्रिया एवं स्वायत्तता: अनुच्छेद 324 और CEC Act 2023 की समीक्षा।
• मतदान का अधिकार: विधिक बनाम मौलिक अधिकार की बहस (अनुच्छेद 326)।
• मध्यस्थता अधिनियम (Mediation Act, 2023) एवं अनुच्छेद 142 के तहत मुकदमों का समाधान।
2. अंतर्राष्ट्रीय संबंध एवं कूटनीति (International Relations — GS-II)
• UNGA का 81वां सत्र: भारत की बहुपक्षीय प्राथमिकताओं और सीमा-पार आतंकवाद पर प्रहार।
• यूरेशियाई कनेक्टिविटी गलियारा: सिल्क रूट, SCO और INSTC के परिप्रेक्ष्य में कश्मीर-लद्दाख की भूमिका।
• आर्कटिक भू-राजनीति: पिघलती बर्फ, नए नौवहन मार्ग और भारत की आर्कटिक नीति 2022।
3. पर्यावरण एवं पारिस्थितिकी (Environment & Ecology — GS-III)
• पश्चिमी घाट पारिस्थितिकी संवेदी क्षेत्र (ESA): कस्तूरीरंगन बनाम गाडगिल रिपोर्ट विवाद।
• महाराष्ट्र में सूखा घोषणा: SDRF/NDRF आवंटन एवं जलवायु-अनुकूल कृषि की आवश्यकता।
4. विज्ञान एवं प्रौद्योगिकी (Sci & Tech — GS-III)
• ड्रग डिस्कवरी में रासायनिक नवाचार: Skeletal Editing और C-to-N Atom Swap तकनीक।
• Small Modular Reactors (SMRs): परमाणु ऊर्जा और नागरिक रिएक्टर सहयोग।""",
    )

    doc_yearly = build_interactive_dashboard_html(
        "UPSC Annual Prelims & Mains Compendium 2026",
        """🏛️ UPSC Civil Services Annual Compendium 2026 (PT-365 Style)
1. मास्टर रिवीजन: संविधान एवं शासन (GS-II)
• सभी प्रमुख संवैधानिक पीठ के ऐतिहासिक निर्णय और अनुच्छेदों का समेकन।
• स्वायत्त संस्थाओं (ECI, UPSC, CAG) से संबंधित न्यायिक व्याख्याएं।
2. मास्टर रिवीजन: पर्यावरण एवं आपदा प्रबंधन (GS-III)
• भारत के सभी जैव-विविधता हॉटस्पॉट, राष्ट्रीय उद्यान एवं रामसर आर्द्रभूमियां।
• COP सम्मेलन एवं वैश्विक जलवायु परिवर्तन संधियाँ।
3. मास्टर रिवीजन: अंतर्राष्ट्रीय संबंध एवं चोकपॉइंट्स
• महत्वपूर्ण वैश्विक समुद्री चोकपॉइंट्स: Strait of Hormuz, Malacca, Bab-el-Mandeb।
• भारत के द्विपक्षीय व बहुपक्षीय रणनीतिक समझौते।""",
    )

    samples = [
        (
            "daily",
            "2026-09-29",
            "September 2026",
            "2026",
            "Kashmir as India’s Gateway to Eurasian Opportunity",
            "Kashmir_Eurasian_Gateway_29Sep.html",
            doc_29,
        ),
        (
            "daily",
            "2026-09-28",
            "September 2026",
            "2026",
            "भारत में मतदान का अधिकार ও ECI सुधार",
            "Right_To_Vote_ECI_28Sep.html",
            doc_28,
        ),
        (
            "daily",
            "2026-09-27",
            "September 2026",
            "2026",
            "Western Ghats ESA & UNGA 81st Session",
            "Western_Ghats_UNGA_27Sep.html",
            doc_27,
        ),
        (
            "weekly",
            "2026-09-28",
            "September 2026",
            "2026",
            "Weekly Current Affairs (21–28 September 2026)",
            "Weekly_Sep_Week4_2026.html",
            doc_28,
        ),
        (
            "monthly",
            "2026-09-29",
            "September 2026",
            "2026",
            "UPSC Monthly Digest — September 2026",
            "UPSC_Monthly_September_2026.html",
            doc_monthly,
        ),
        (
            "yearly",
            "2026-09-01",
            "September 2026",
            "2026",
            "UPSC Annual Compendium 2026",
            "UPSC_Yearly_Compendium_2026.html",
            doc_yearly,
        ),
    ]

    c.executemany(
        """
            INSERT INTO archive (period, date_str, month_str, year_str, topic, filename, html_content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        samples,
    )

  conn.commit()
  conn.close()


def register_user(user_id, username, first_name):
  try:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
            INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            username or "",
            first_name or "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
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
    c.execute(
        """
            INSERT INTO archive (period, date_str, month_str, year_str, topic, filename, html_content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            period,
            today_str,
            month_str,
            year_str,
            topic,
            filename,
            html_content,
        ),
    )
    conn.commit()
    conn.close()
  except Exception as e:
    print(f"Error archiving: {e}")


def get_archive_list(period, limit=8):
  try:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if period == "daily":
      c.execute(
          """
                SELECT id, date_str, topic FROM archive 
                WHERE period = 'daily' ORDER BY id DESC LIMIT ?
            """,
          (limit,),
      )
    elif period == "monthly":
      c.execute(
          """
                SELECT id, month_str, topic FROM archive 
                WHERE period = 'monthly' OR period = 'daily' 
                GROUP BY month_str ORDER BY id DESC LIMIT ?
            """,
          (limit,),
      )
    elif period == "yearly":
      c.execute(
          """
                SELECT id, year_str, topic FROM archive 
                GROUP BY year_str ORDER BY id DESC LIMIT ?
            """,
          (limit,),
      )
    elif period == "weekly":
      c.execute(
          """
                SELECT id, date_str, topic FROM archive 
                WHERE period = 'weekly' OR period = 'daily' ORDER BY id DESC LIMIT ?
            """,
          (limit,),
      )
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
    c.execute(
        """
            SELECT topic, filename, html_content FROM archive WHERE id = ?
        """,
        (archive_id,),
    )
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
def sanitize_and_rebrand_html(
    soup: BeautifulSoup, custom_title: str = None
) -> None:
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
  lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
  sections = []
  current_sec_title = "भूमिका / सामान्य सारांश"
  current_sec_lines = []

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
                "🔸",
            ]
        )
        or (line.endswith(":") and len(line) < 55)
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
    sec_id = f"sec-{idx}"
    short_name = re.sub(r"^[0-9]+\.\s*", "", sec_title)
    short_name = re.sub(
        r"[📌💡⚡✨🔥📖🎯📝🌪️🗳️⚖️🔍|━─—_:-🔸]", "", short_name
    ).strip()
    if len(short_name) > 20:
      short_name = short_name[:18] + ".."
    if not short_name:
      short_name = f"भाग {idx}"

    nav_links_html += f'<a href="#{sec_id}">{short_name}</a>\n'

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

      if "→" in line:
        steps = [s.strip() for s in line.split("→") if s.strip()]
        if len(steps) > 1:
          step_tags = "".join(
              [f"<span class='flow-step'>{s}</span>" for s in steps]
          )
          sec_body_html += f"<div class='flow-container'>{step_tags}</div>"
          continue

      if line.startswith(("•", "-", "▪", "▫", "*")):
        clean_bullet = re.sub(r"^[•\-▪▫\*]\s*", "", line)
        sec_body_html += f"<li class='list-item'>{clean_bullet}</li>"
        continue

      formatted = re.sub(
          r"\*\*(.*?)\*\*", r'<strong class="hl-bold">\1</strong>', line
      )
      formatted = re.sub(
          r"(GS-[I|II|III|IV]+)", r'<span class="badge-gs">\1</span>', formatted
      )
      formatted = re.sub(
          r"(Article\s+\d+[A-Za-z]?|अनुच्छेद\s+\d+[A-Za-z]?)",
          r'<span class="badge-art">\1</span>',
          formatted,
          flags=re.IGNORECASE,
      )
      formatted = re.sub(
          r"(https?://[^\s]+)",
          r'<a href="\1" target="_blank" class="text-link">\1</a>',
          formatted,
      )
      sec_body_html += f"<p class='para'>{formatted}</p>"

    if in_table:
      sec_body_html += (
          f"<div class='table-box'><table>{''.join(table_rows)}</table></div>"
      )

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
.hl-bold {{ color:#0284c7; font-weight:700; }}
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


# ================= PUBLIC MENU & INLINE BUTTONS =================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  register_user(user.id, user.username, user.first_name)
  is_admin = user.id in ADMIN_IDS

  if is_admin:
    msg = (
        f"👋 <b>नमस्ते एडमिन {AUTHOR_NAME}!</b>\n\n"
        "👑 <b>एडमिन कंट्रोल सक्रिय है:</b>\n"
        "• <code>/html</code> — नए नोट्स संकलन शुरू करें\n"
        "• <code>/sachin</code> — HTML फ़ाइल तैयार करें\n"
        "• <code>/broadcast</code> — सभी को मैसेज भेजें\n\n"
        "📚 <b>छात्रों के लिए आर्काइव कमांड्स:</b>\n"
        "• <code>/daily</code> — तारीख चुनकर नोट्स डाउनलोड करें\n"
        "• <code>/weekly</code> — सप्ताह चुनकर नोट्स देखें\n"
        "• <code>/monthly</code> — महीना चुनकर पत्रिका देखें\n"
        "• <code>/yearly</code> — साल चुनकर नोट्स देखें\n"
        "• <code>/owner</code> — सीधे छात्रों के संदेश प्राप्त करें"
    )
  else:
    msg = (
        f"👋 <b>नमस्ते {user.first_name}!</b>\n\n"
        "📚 <b>UPSC HTML Notes Portal में आपका स्वागत है!</b>\n\n"
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
      "• <code>/daily</code> दबाएं — आपको पिछली तारीखों के बटन मिलेंगे। मनपसंद"
      " तारीख पर क्लिक करते ही उस दिन की HTML फ़ाइल मिल जाएगी।\n\n"
      "2️⃣ <b>मासिक या वार्षिक नोट्स:</b>\n"
      "• <code>/monthly</code> — महीनों के नाम के बटन दिखेंगे।\n"
      "• <code>/yearly</code> — वर्षों के बटन दिखेंगे।\n\n"
      "3️⃣ <b>सीधे एडमिन से संपर्क:</b>\n"
      "• <code>/owner</code> दबाएं और 2 मिनट में अपनी बात लिखें।\n\n"
      f"📢 <b>ऑफिशियल ग्रुप:</b> <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>"
  )
  await update.message.reply_text(
      help_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
  )


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
    keyboard.append(
        [InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")]
    )

  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text(
      "📅 <b>जिस तारीख के नोट्स चाहिए, उस बटन पर क्लिक करें:</b>",
      reply_markup=reply_markup,
      parse_mode=ParseMode.HTML,
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
    keyboard.append(
        [InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")]
    )

  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text(
      "📁 <b>जिस महीने के नोट्स चाहिए, उस पर क्लिक करें:</b>",
      reply_markup=reply_markup,
      parse_mode=ParseMode.HTML,
  )


async def yearly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  register_user(user.id, user.username, user.first_name)
  rows = get_archive_list("yearly", limit=5)

  if not rows:
    await update.message.reply_text(
        "ℹ️ अभी कोई वार्षिक नोट्स उपलब्ध नहीं हैं।"
    )
    return

  keyboard = []
  for arch_id, y_str, topic in rows:
    btn_text = f"📚 वर्ष {y_str} वार्षिक संकलन"
    keyboard.append(
        [InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")]
    )

  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text(
      "🏛️ <b>जिस वर्ष का कंपाइलेशन चाहिए, उस पर क्लिक करें:</b>",
      reply_markup=reply_markup,
      parse_mode=ParseMode.HTML,
  )


async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  register_user(user.id, user.username, user.first_name)
  rows = get_archive_list("weekly", limit=6)

  if not rows:
    await update.message.reply_text(
        "ℹ️ अभी कोई साप्ताहिक नोट्स उपलब्ध नहीं हैं।"
    )
    return

  keyboard = []
  for arch_id, w_str, topic in rows:
    btn_text = f"🗓️ {w_str} का सप्ताह"
    keyboard.append(
        [InlineKeyboardButton(btn_text, callback_data=f"arch_{arch_id}")]
    )

  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text(
      "🗓️ <b>साप्ताहिक रिवीजन हेतु सप्ताह चुनें:</b>",
      reply_markup=reply_markup,
      parse_mode=ParseMode.HTML,
  )


async def archive_button_click(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  await query.answer()

  arch_id = int(query.data.split("_")[1])
  data = get_archive_by_id(arch_id)

  if not data:
    await query.message.reply_text("❌ यह फ़ाइल उपलब्ध नहीं है।")
    return

  topic, filename, html_content = data
  with open(filename, "w", encoding="utf-8") as f:
    f.write(html_content)

  with open(filename, "rb") as send_doc:
    await query.message.reply_document(
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
async def contact_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  user = update.effective_user
  register_user(user.id, user.username, user.first_name)
  user_id = user.id

  CONTACT_SESSIONS[user_id] = time.time()
  await update.message.reply_text(
      "⏱ <b>2 मिनट का समय सक्रिय है!</b>\n\n"
      "अपनी समस्या या सवाल लिखकर भेजें।\n"
      f"यह सीधे <b>{AUTHOR_NAME}</b> के पास पहुँचा दिया जाएगा।\n\n"
      "<i>(रद्द करने हेतु <code>/cancel</code> भेजें)</i>",
      parse_mode=ParseMode.HTML,
  )
  return WAITING_CONTACT_MSG


async def forward_contact_msg(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  user = update.effective_user
  user_id = user.id
  start_time = CONTACT_SESSIONS.get(user_id, 0)

  if time.time() - start_time > 120:
    CONTACT_SESSIONS.pop(user_id, None)
    await update.message.reply_text(
        "⚠️ <b>समय समाप्त!</b> 2 मिनट पूरे हो चुके हैं। पुनः प्रयास के लिए"
        " <code>/owner</code> भेजें।",
        parse_mode=ParseMode.HTML,
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
      await context.bot.send_message(
          chat_id=admin_id, text=owner_alert, parse_mode=ParseMode.HTML
      )
    except Exception as e:
      print(f"Error notifying admin {admin_id}: {e}")

  await update.message.reply_text(
      "✅ <b>आपका संदेश ओनर को भेज दिया गया है!</b> जैसे ही वे देखेंगे, आपको"
      " यहीं उत्तर मिल जाएगा।",
      parse_mode=ParseMode.HTML,
  )
  CONTACT_SESSIONS.pop(user_id, None)
  return ConversationHandler.END


async def handle_admin_reply_to_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
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
          disable_web_page_preview=True,
      )
      await msg.reply_text("✅ जवाब छात्र को सफलतापूर्वक भेज दिया गया!")
    except Exception as e:
      await msg.reply_text(f"❌ छात्र तक मैसेज नहीं पहुँचा: {e}")


# ================= BROADCAST SYSTEM =================
async def broadcast_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  admin_id = update.effective_user.id
  if admin_id not in ADMIN_IDS:
    await update.message.reply_text("⛔ यह केवल एडमिन के लिए है।")
    return ConversationHandler.END

  all_users = get_all_users()
  await update.message.reply_text(
      "📢 <b>ब्रॉडकास्ट प्रणाली</b>\n\n"
      f"कुल पंजीकृत छात्र: <b>{len(all_users)}</b>\n\n"
      "वह संदेश भेजें जो सभी को पहुँचाना है:\n<i>(रद्द करने हेतु"
      " <code>/cancel</code> भेजें)</i>",
      parse_mode=ParseMode.HTML,
  )
  return WAITING_BROADCAST_MSG


async def execute_broadcast(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  admin_id = update.effective_user.id
  if admin_id not in ADMIN_IDS:
    return ConversationHandler.END

  b_msg = update.message
  all_users = get_all_users()

  status_msg = await update.message.reply_text(
      f"⏳ ब्रॉडकास्ट जारी है... (कुल: {len(all_users)})"
  )
  success_count = 0
  fail_count = 0

  for uid in all_users:
    try:
      if b_msg.text:
        await context.bot.send_message(
            chat_id=uid,
            text=f"📢 <b>UPSC HTML सूचना:</b>\n\n{b_msg.text}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
      else:
        await context.bot.copy_message(
            chat_id=uid, from_chat_id=admin_id, message_id=b_msg.message_id
        )
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


# ================= ADMIN-ONLY HTML GENERATION =================
async def start_html_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
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
      "🟢 <b>एडमिन सत्र चालू!</b> सामग्री फॉरवर्ड करें, फिर"
      " <code>/sachin</code> भेजें।",
      parse_mode=ParseMode.HTML,
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


async def ask_for_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  user_id = update.effective_user.id
  if user_id not in ADMIN_IDS:
    await update.message.reply_text("⛔ यह कमांड केवल एडमिन के लिए है।")
    return ConversationHandler.END

  session = USER_BUFFERS.get(user_id)
  if not session or (
      not session.get("texts") and not session.get("html_soups")
  ):
    await update.message.reply_text(
        "❌ कोई सामग्री नहीं मिली। पहले <code>/html</code> भेजें।",
        parse_mode=ParseMode.HTML,
    )
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


async def generate_final_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
  user_id = update.effective_user.id
  session = USER_BUFFERS.get(user_id)
  if not session:
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

  # डेटाबेस में नई फ़ाइल जोड़ना
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
  app.router.add_get(
      "/",
      lambda r: web.Response(
          text="Bot Active 24/7 with Pre-loaded Archive Buttons"
      ),
  )
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

  # सार्वजनिक कमांड्स
  bot_app.add_handler(CommandHandler("start", start_handler))
  bot_app.add_handler(CommandHandler("help", help_handler))
  bot_app.add_handler(CommandHandler("daily", daily_cmd))
  bot_app.add_handler(CommandHandler("weekly", weekly_cmd))
  bot_app.add_handler(CommandHandler("monthly", monthly_cmd))
  bot_app.add_handler(CommandHandler("yearly", yearly_cmd))

  bot_app.add_handler(
      CallbackQueryHandler(archive_button_click, pattern=r"^arch_\d+$")
  )

  contact_conv = ConversationHandler(
      entry_points=[
          CommandHandler("owner", contact_cmd),
          CommandHandler("contact", contact_cmd),
      ],
      states={
          WAITING_CONTACT_MSG: [
              MessageHandler(
                  filters.TEXT & (~filters.COMMAND), forward_contact_msg
              )
          ]
      },
      fallbacks=[CommandHandler("cancel", cancel)],
  )
  bot_app.add_handler(contact_conv)

  broadcast_conv = ConversationHandler(
      entry_points=[CommandHandler("broadcast", broadcast_cmd)],
      states={
          WAITING_BROADCAST_MSG: [
              MessageHandler(
                  (filters.TEXT | filters.PHOTO | filters.Document.ALL)
                  & (~filters.COMMAND),
                  execute_broadcast,
              )
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
              MessageHandler(
                  filters.TEXT & (~filters.COMMAND), generate_final_file
              )
          ]
      },
      fallbacks=[CommandHandler("cancel", cancel)],
  )
  bot_app.add_handler(html_conv)

  bot_app.add_handler(
      MessageHandler(filters.REPLY & filters.TEXT, handle_admin_reply_to_user)
  )
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
