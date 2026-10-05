import re
from bs4 import BeautifulSoup
from config import AUTHOR_NAME, CHANNEL_LINK, CHANNEL_NAME, get_ist_now

def create_standalone_vector_map(place_name: str) -> str:
    return f"""
    <figure class="img-figure">
      <svg width="100%" height="220" viewBox="0 0 800 220" xmlns="http://www.w3.org/2000/svg" style="background: linear-gradient(135deg, #f8fafc, #f1f5f9); border-radius: 8px;">
        <rect width="100%" height="100%" fill="none" stroke="#0284c7" stroke-width="1.5" rx="8"/>
        <g opacity="0.15">
          <line x1="0" y1="55" x2="800" y2="55" stroke="#0284c7" stroke-width="1"/>
          <line x1="0" y1="110" x2="800" y2="110" stroke="#0284c7" stroke-width="1"/>
          <line x1="0" y1="165" x2="800" y2="165" stroke="#0284c7" stroke-width="1"/>
          <line x1="200" y1="0" x2="200" y2="220" stroke="#0284c7" stroke-width="1"/>
          <line x1="400" y1="0" x2="400" y2="220" stroke="#0284c7" stroke-width="1"/>
          <line x1="600" y1="0" x2="600" y2="220" stroke="#0284c7" stroke-width="1"/>
        </g>
        <circle cx="740" cy="45" r="22" fill="#ffffff" stroke="#0284c7" stroke-width="1.5"/>
        <path d="M 740 27 L 745 45 L 740 42 L 735 45 Z" fill="#ef4444"/>
        <text x="740" y="24" font-size="10" font-weight="bold" fill="#ef4444" text-anchor="middle">N</text>
        <rect x="50" y="35" width="300" height="150" rx="8" fill="#ffffff" stroke="#e2e8f0" stroke-width="1.5"/>
        <text x="70" y="70" font-family="'Hind', sans-serif" font-size="16" font-weight="bold" fill="#0369a1">📍 {place_name}</text>
        <text x="70" y="102" font-family="'Hind', sans-serif" font-size="13" fill="#475569">• रणनीतिक अवस्थिति एवं जलग्रहण क्षेत्र</text>
        <text x="70" y="128" font-family="'Hind', sans-serif" font-size="13" fill="#475569">• पारिस्थितिकी एवं संरक्षित हॉटस्पॉट</text>
        <text x="70" y="154" font-family="'Hind', sans-serif" font-size="12" font-weight="bold" fill="#059669">✓ UPSC मैपिंग एवं प्रीलिम्स संदर्भ</text>
        <circle cx="560" cy="110" r="50" fill="#e0f2fe" stroke="#0284c7" stroke-width="2"/>
        <circle cx="560" cy="110" r="8" fill="#ef4444"/>
        <text x="560" y="175" font-family="'Hind', sans-serif" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">प्रमुख स्थल नोड</text>
      </svg>
      <figcaption>🗺️ भौगोलिक एवं रणनीतिक मानचित्र: {place_name}</figcaption>
    </figure>
    """

def markdown_tables_to_html(text: str) -> str:
    lines = text.split("\n")
    in_table = False
    html_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r'^:?-+:?$', c) for c in cells):
                continue
            if not in_table:
                in_table = True
                html_lines.append('<div class="table-box"><table><thead><tr>')
                for h in cells:
                    html_lines.append(f'<th>{h}</th>')
                html_lines.append('</tr></thead><tbody>')
            else:
                html_lines.append('<tr>')
                for c in cells:
                    html_lines.append(f'<td>{c}</td>')
                html_lines.append('</tr>')
        else:
            if in_table:
                html_lines.append('</tbody></table></div>')
                in_table = False
            html_lines.append(line)
    if in_table:
        html_lines.append('</tbody></table></div>')
    return "\n".join(html_lines)

def clean_all_markdown_and_fix_content(raw_text: str) -> str:
    text = raw_text.strip()
    text = markdown_tables_to_html(text)

    text = re.sub(r'```(?:xml|svg|html)?[\s\S]*?```', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```', '', text)
    text = re.sub(r'<figure[^>]*>[\s\S]*?<\/figure>', '', text, flags=re.IGNORECASE)

    text = re.sub(r'###\s*(.*)', r'<h4 class="sub-title">\1</h4>', text)
    text = re.sub(r'##\s*(.*)', r'<h3 class="section-title">\1</h3>', text)
    text = re.sub(r'#\s*(.*)', r'<h2 class="section-title">\1</h2>', text)

    text = re.sub(
        r'(?:प्रश्न\s*\d*\s*[:\-]|UPSC\s*CSE\s*प्रश्न\s*[:\-])\s*(.*)',
        r'<div class="mains-q-card"><div class="q-icon">📝 मुख्य परीक्षा प्रश्न:</div><h3 class="q-bold-text">\1</h3></div>',
        text
    )
    text = re.sub(
        r'(\[UPSC\s*CSE[^\]]*\])',
        r'<div class="badge-wrap"><span class="mains-badge">\1</span></div>',
        text
    )
    text = re.sub(
        r'(?:📌\s*)?(?:\*\*|\#\#)?\s*भूमिका\s*[:\-]?\s*(?:\*\*)?\s*(.*)',
        r'<div class="mains-point"><span class="point-badge-intro">📌 भूमिका (Introduction):</span><p class="para-bold">\1</p></div>',
        text
    )
    text = re.sub(
        r'(?:📊\s*)?(?:\*\*|\#\#)?\s*मुख्य\s*विश्लेषणात्मक\s*आयाम\s*[:\-]?\s*(?:\*\*)?',
        r'<div class="point-badge-body">📊 मुख्य विश्लेषणात्मक आयाम (Core Analysis):</div>',
        text
    )
    text = re.sub(
        r'(?:🚀\s*)?(?:\*\*|\#\#)?\s*आगे\s*की\s*राह\s*\(Way\s*Forward\)\s*[:\-]?\s*(?:\*\*)?\s*(.*)',
        r'<div class="mains-point"><span class="point-badge-wf">🚀 आगे की राह (Way Forward):</span><p class="para-bold">\1</p></div>',
        text
    )
    text = re.sub(
        r'(?:⚖️\s*)?(?:\*\*|\#\#)?\s*संतुलित\s*प्रशासनिक\s*निष्कर्ष\s*[:\-]?\s*(?:\*\*)?\s*(.*)',
        r'<div class="mains-point"><span class="point-badge-conc">⚖️ संतुलित प्रशासनिक निष्कर्ष:</span><p class="para-bold">\1</p></div>',
        text
    )

    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'^[•\-\*]\s*(.*)', r'<li class="list-item">\1</li>', text, flags=re.MULTILINE)

    key_locations = ["कूनो", "गांधी सागर", "मन्नार की खाड़ी", "कच्छ का रण", "होर्मुज़", "लाल सागर", "अंडमान", "पश्चिमी घाट", "लद्दाख", "ताइवान", "चाबहार"]
    for loc in key_locations:
        if loc in text:
            vector_card = create_standalone_vector_map(loc)
            text += f"\n<div class='map-section'><h4>🗺️ भौगोलिक एवं रणनीतिक मैपिंग</h4><p><i>(नोट: संबंधित विषय का भौगोलिक परिदृश्य नीचे प्रदर्शित है)</i></p>{vector_card}</div>"
            break

    return text

def build_standalone_master_html(topic: str, raw_content: str, date_str: str = "", is_trending: bool = False) -> str:
    cleaned_body = clean_all_markdown_and_fix_content(raw_content)
    display_date = date_str if date_str else get_ist_now().strftime("%d %B %Y")

    nav_links = '<a href="#sec-overview">📋 सत्र सार</a>\n'
    soup = BeautifulSoup(cleaned_body, 'html.parser')
    sec_idx = 1

    for tag in soup.find_all(['h2', 'h3']):
        title_text = tag.get_text().strip()
        if len(title_text) > 3 and not tag.get('id'):
            sec_id = f"custom-sec-{sec_idx}"
            tag['id'] = sec_id
            clean_tab_name = re.sub(r'^(?:खंड|खण्ड|भाग|\d+|[:\.\-\s])+', '', title_text).strip()
            clean_tab_name = re.sub(r'[📌🎯⚡📖💡🗳⚖️🔍📝🛣️❄🌏📰🌍🌱🔬💰🔑📚🔸|━─—_:-]', '', clean_tab_name).strip()
            if not clean_tab_name:
                clean_tab_name = f"विषय {sec_idx}"
            if len(clean_tab_name) > 20:
                clean_tab_name = clean_tab_name[:18] + ".."
            nav_links += f'<a href="#{sec_id}">{clean_tab_name}</a>\n'
            sec_idx += 1

    final_body = str(soup)
    overview_title = "🧭 ट्रेंडिंग समसामयिक विश्लेषण" if is_trending else "📌 सत्र विहंगावलोकन"

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} | {AUTHOR_NAME}</title>
<link href="[https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap](https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap)" rel="stylesheet">
<style>
:root {{
  --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0;
  --accent: #0284c7; --accent-dark: #0369a1; --saffron: #f59e0b; --green: #10b981;
  --tag-bg: #e0f2fe; --tag-text: #0369a1; --shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
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
    font-size: 5rem; font-weight: 900; color: rgba(0, 0, 0, 0.50) !important;
    opacity: 0.50 !important; transform: rotate(-35deg); z-index: 9999; pointer-events: none; letter-spacing: 8px;
  }}
  .controls, nav.dashboard, #telegramBtn, .print-btn, .theme-btn {{ display: none !important; }}
  .news-card {{ box-shadow: none !important; border: 1px solid #ccc !important; page-break-inside: avoid; }}
}}
.top-header {{
  background: linear-gradient(135deg, #071529, #0284c7 65%, #0369a1);
  color: #fff; padding: 26px 16px 20px; text-align: center; border-bottom: 4px solid var(--saffron);
}}
.top-header h1 {{ font-size: 1.65rem; margin-bottom: 6px; font-weight: 700; }}
.author-pill {{
  display: inline-block; margin-top: 4px; background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.35); padding: 5px 18px; border-radius: 30px;
  font-weight: 600; font-size: 0.92rem;
}}
.controls {{ display: flex; justify-content: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
.controls input {{ width: min(340px, 85vw); padding: 9px 14px; border-radius: 20px; border: none; outline: none; font-size: 0.9rem; }}
.controls button {{
  padding: 8px 18px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.2); color: #fff; font-weight: 600; cursor: pointer;
}}
nav.dashboard {{
  position: sticky; top: 0; z-index: 50; background: var(--card); border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow); overflow-x: auto; white-space: nowrap; padding: 10px 14px;
}}
nav.dashboard .nav-wrap {{ display: flex; gap: 8px; max-width: 1000px; margin: 0 auto; }}
nav.dashboard a {{
  display: inline-block; padding: 7px 14px; background: var(--tag-bg); color: var(--tag-text);
  border-radius: 16px; font-size: 0.86rem; font-weight: 600; text-decoration: none; flex: none;
}}
nav.dashboard a:hover {{ background: var(--accent); color: #fff; }}
.wrap {{ max-width: 1000px; margin: 22px auto; padding: 0 16px; width: 100%; }}
.overview-box {{
  background: var(--tag-bg); border: 2px solid var(--accent); border-radius: 12px;
  padding: 18px; margin-bottom: 22px; box-shadow: var(--shadow);
}}
.overview-title {{ color: var(--accent-dark); font-size: 1.2rem; font-weight: 700; margin-bottom: 8px; }}
.news-card {{
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px; margin-bottom: 24px; box-shadow: var(--shadow); width: 100%; scroll-margin-top: 70px;
}}
.section-title {{
  color: var(--accent); font-size: 1.3rem; margin-bottom: 14px;
  border-left: 5px solid var(--saffron); padding-left: 12px; font-weight: 700;
}}
.sub-title {{ font-size: 1.1rem; color: var(--accent-dark); margin: 16px 0 8px; font-weight: 700; }}
.para {{ margin: 8px 0; font-size: 1rem; word-break: break-word; text-align: justify; }}
.para-bold {{ margin: 8px 0; font-size: 1.02rem; font-weight: 600; color: var(--text); text-align: justify; line-height: 1.8; }}
.mains-q-card {{
  background: linear-gradient(135deg, #f0fdf4, #e0f2fe);
  border: 2px solid var(--accent);
  border-radius: 10px;
  padding: 18px 20px;
  margin: 24px 0 14px;
  box-shadow: var(--shadow);
}}
.q-icon {{ font-size: 0.95rem; font-weight: 800; color: var(--accent-dark); text-transform: uppercase; margin-bottom: 6px; }}
.q-bold-text {{ font-size: 1.3rem; font-weight: 900; color: #0f172a; line-height: 1.6; letter-spacing: 0.2px; }}
.badge-wrap {{ margin: 8px 0 16px; }}
.mains-badge {{
  display: inline-block; background: #0284c7; color: #ffffff; padding: 4px 12px;
  border-radius: 20px; font-weight: 800; font-size: 0.9rem; letter-spacing: 0.5px;
}}
.mains-point {{ margin: 16px 0; padding-left: 12px; border-left: 4px solid var(--accent); }}
.point-badge-intro {{ background: #0284c7; color: #fff; padding: 3px 10px; border-radius: 4px; font-weight: 800; font-size: 0.92rem; display: inline-block; margin-bottom: 6px; }}
.point-badge-body {{ color: var(--accent-dark); font-weight: 900; font-size: 1.15rem; margin: 18px 0 8px; border-bottom: 2px solid var(--border); padding-bottom: 4px; }}
.point-badge-wf {{ background: #10b981; color: #fff; padding: 3px 10px; border-radius: 4px; font-weight: 800; font-size: 0.92rem; display: inline-block; margin-bottom: 6px; }}
.point-badge-conc {{ background: #f59e0b; color: #000; padding: 3px 10px; border-radius: 4px; font-weight: 800; font-size: 0.92rem; display: inline-block; margin-bottom: 6px; }}
.table-box {{ overflow-x: auto; margin: 16px 0; width: 100%; border-radius: 8px; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ background: var(--accent); color: #fff; padding: 11px 13px; font-size: 0.92rem; }}
td {{ padding: 11px 13px; border-bottom: 1px solid var(--border); font-size: 0.92rem; vertical-align: top; }}
.img-figure {{
  margin: 18px 0; text-align: center; background: #ffffff; padding: 10px;
  border-radius: 10px; border: 1px solid #bae6fd; box-shadow: var(--shadow);
}}
#telegramBtn {{
  position: fixed; bottom: 18px; right: 18px; z-index: 90; background: #229ED9; color: #fff;
  border: none; border-radius: 30px; padding: 11px 20px; font-weight: 700; cursor: pointer; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25); font-size: 0.88rem;
}}
footer {{ background: #071529; color: #dbe6f2; text-align: center; padding: 26px 16px; margin-top: 36px; font-size: 0.88rem; }}
footer a {{ color: #8bc4ef; font-weight: 700; text-decoration: none; }}
</style>
</head>
<body data-theme="light">
<header class="top-header">
  <h1>🇮🇳 {topic}</h1>
  <div class="author-pill">✍️ संकलन: {AUTHOR_NAME} | {CHANNEL_NAME}</div>
  <div class="controls">
    <input type="text" id="searchBox" placeholder="🔍 खोजें: विषय, अनुच्छेद, कीवर्ड...">
    <button onclick="toggleTheme()" class="theme-btn">🌗 डार्क / लाइट</button>
    <button onclick="window.print()" class="print-btn">🖨️ प्रिंट / सेव PDF</button>
  </div>
</header>
<nav class="dashboard"><div class="nav-wrap">{nav_links}</div></nav>
<main class="wrap" id="mainContent">
  <section id="sec-overview" class="overview-box">
    <div class="overview-title">📌 {overview_title}</div>
    <p class="para"><strong>📅 संदर्भ काल:</strong> {display_date} (IST)</p>
    <p class="para"><strong>🎯 संकलन आयाम:</strong> 360° समग्र विश्लेषण, 2-कॉलम सारणी, मानक भौगोलिक मानचित्र एवं मुख्य परीक्षा उत्तर-लेखन फ्रेमवर्क।</p>
    <p class="para"><strong>📰 अधिकृत स्रोत:</strong> The Hindu, Indian Express, PIB, Yojana, Vision IAS, Drishti IAS, Sanskriti IAS।</p>
  </section>
  <div class="news-card">{final_body}</div>
</main>
<button id="telegramBtn" onclick="window.open('{CHANNEL_LINK}','_blank')">📲 TELEGRAM — {CHANNEL_NAME}</button>
<footer>
  <div><b>UPSC CIVIL SERVICES EXAMINATION COMPREHENSIVE STUDY DESK</b></div>
  <div style="margin-top:6px;">संकलन एवं प्रस्तुति: <b>{AUTHOR_NAME}</b> | टेलीग्राम: <a href="{CHANNEL_LINK}" target="_blank">{CHANNEL_NAME}</a></div>
  <div style="margin-top:4px; font-size:0.8rem; color:#94a3b8;">कॉपीराइट सुरक्षित © {get_ist_now().strftime('%Y')} | केवल शैक्षणिक एवं स्व-अध्ययन हेतु</div>
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

def build_vision_ias_interactive_portal(subject_title: str, test_id: str, q_count: int, questions_json: str) -> str:
    duration_min = 60 if q_count == 50 else (120 if q_count == 100 else 180)

    html_template = """<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>UPSC CSE - __SUBJ__ | __AUTH__</title>
<style>
:root {
    --home-bg-top: #0f172a; --home-bg-bot: #020617; --home-card: #1e293b; --home-box: #334155;      
    --home-text-accent: #facc15; --home-btn: #facc15; --bg-dark: #0b0f19; --card-dark: #151b2b;     
    --primary: #facc15; --secondary: #3b82f6; --text-main: #f8fafc; --text-muted: #94a3b8;
    --border-color: #1e293b; --option-bg: #0b0f19; --correct: #10b981; --wrong: #ef4444; --skipped: #3b82f6; --current: #facc15;       
}
* { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; -webkit-tap-highlight-color: transparent; }
body { background-color: var(--bg-dark); color: var(--text-main); display: flex; justify-content: center; height: 100vh; height: 100dvh; overflow: hidden; }
.app-container { width: 100%; max-width: 520px; background-color: var(--bg-dark); display: flex; flex-direction: column; position: relative; height: 100%; border: none; }
.hidden { display: none !important; }
#print-container { display: none; }
#home-screen { background: linear-gradient(180deg, var(--home-bg-top) 0%, var(--home-bg-bot) 100%); padding: 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100%; overflow-y: auto; }
.brand-header { text-align: center; margin-bottom: 20px; width: 100%; }
.brand-header h1 { color: var(--home-text-accent); font-size: 26px; font-weight: 900; letter-spacing: 1px; margin-bottom: 4px; text-shadow: 0 2px 10px rgba(250, 204, 21, 0.4); }
.brand-header p { color: #e2e8f0; font-size: 11px; letter-spacing: 3px; font-weight: 600; text-transform: uppercase; }
.test-info-card { background: var(--home-card); padding: 22px 18px; border-radius: 16px; width: 100%; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid rgba(250, 204, 21, 0.2); }
.test-title { font-size: 17px; font-weight: bold; text-align: center; margin-bottom: 4px; color: white; }
.test-subtitle { font-size: 12px; color: #cbd5e1; text-align: center; margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px dashed rgba(255,255,255,0.3); }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 18px; }
.info-box { background: var(--home-box); padding: 10px 8px; border-radius: 10px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }
.info-val { font-size: 18px; font-weight: 800; color: var(--home-text-accent); margin-bottom: 2px; }
.info-lbl { font-size: 10px; color: white; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
.name-input-container { margin-bottom: 18px; }
.name-input { width: 100%; padding: 13px 15px; border-radius: 10px; border: 2px solid var(--home-text-accent); background: #0b0f19; color: white; font-size: 15px; font-weight: bold; text-align: center; outline: none; }
.start-btn { width: 100%; padding: 15px; border-radius: 12px; background: var(--home-btn); color: #0f172a; font-size: 16px; font-weight: bold; border: none; cursor: pointer; box-shadow: 0 4px 15px rgba(250, 204, 21, 0.4); text-transform: uppercase; letter-spacing: 1px; }
#test-screen { display: flex; flex-direction: column; height: 100%; background: var(--bg-dark); }
.test-header { flex-shrink: 0; background: var(--card-dark); border-bottom: 1px solid var(--border-color); padding: 10px 15px; }
.header-row { display: flex; justify-content: space-between; align-items: flex-start; }
.head-left h2 { font-size: 12px; color: var(--primary); font-weight: 800; text-transform: uppercase; }
.head-left p { font-size: 11px; color: var(--text-muted); font-weight: 600; }
.timer-box { font-size: 13px; font-weight: bold; color: #0b0f19; background: var(--primary); padding: 2px 8px; border-radius: 4px; display: inline-block; }
.progress-bar-container { height: 3px; background: var(--border-color); width: 100%; }
.progress-bar { height: 100%; background: var(--primary); width: 0%; transition: width 0.3s ease; }
.sub-header { display: flex; justify-content: space-between; padding: 8px 15px; font-size: 12px; font-weight: 600; background: var(--bg-dark); color: var(--text-muted); border-bottom: 1px solid var(--border-color); }
.question-area { flex: 1; padding: 12px 15px; overflow-y: auto; background: var(--bg-dark); padding-bottom: 20px; }
.q-card { background: var(--card-dark); padding: 15px 12px; border-radius: 10px; border: 1px solid var(--border-color); margin-bottom: 10px; }
.q-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.q-tag { background: rgba(250, 204, 21, 0.15); color: var(--primary); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; }
.q-topic-tag { background: var(--primary); color: #000; padding: 4px 10px; border-radius: 15px; font-size: 11px; font-weight: 800; }
.q-text { font-size: 14.5px; line-height: 1.5; font-weight: 500; margin-bottom: 15px; color: #fff; }
.options-list { display: flex; flex-direction: column; gap: 8px; }
.option { display: flex; align-items: center; padding: 10px 12px; background: var(--option-bg); border: 1px solid var(--border-color); border-radius: 8px; cursor: pointer; }
.option.selected { border-color: var(--primary); background: rgba(250, 204, 21, 0.12); }
.opt-letter { width: 22px; height: 22px; border-radius: 4px; background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 10px; color: var(--text-muted); flex-shrink: 0; }
.option.selected .opt-letter { background: var(--primary); color: #000; }
.opt-text { font-size: 13.5px; line-height: 1.3; color: #f1f5f9; }
.bottom-actions-container { flex-shrink: 0; background: var(--card-dark); padding: 8px 12px; border-top: 1px solid var(--border-color); }
.nav-buttons-row { display: flex; justify-content: space-between; gap: 6px; margin-bottom: 6px; }
.nav-btn { flex: 1; height: 36px; padding: 0; border-radius: 6px; font-size: 12px; font-weight: 700; border: none; background: var(--bg-dark); color: var(--text-main); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.nav-btn.icon-btn { flex: 0.4; font-size: 16px; }
.big-green-btn { width: 100% !important; height: 40px !important; background: #10b981 !important; color: white !important; border-radius: 8px !important; font-weight: bold !important; font-size: 14px !important; border: none !important; cursor: pointer !important; text-transform: uppercase !important; display: flex; align-items: center; justify-content: center; }
.palette-modal { position: absolute; bottom: 0; left: 0; width: 100%; max-height: 80vh; background: var(--card-dark); border-top-left-radius: 20px; border-top-right-radius: 20px; padding: 18px; transform: translateY(100%); transition: transform 0.3s ease; z-index: 100; display: flex; flex-direction: column; border-top: 1px solid var(--primary); }
.palette-modal.open { transform: translateY(0); }
.palette-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }
.q-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; overflow-y: auto; padding-bottom: 12px; flex: 1; }
.q-grid-btn { width: 100%; aspect-ratio: 1; border-radius: 8px; border: none; background: var(--bg-dark); color: var(--text-main); font-weight: bold; font-size: 13px; cursor: pointer; }
.status-answered { background: var(--correct) !important; color: white !important; }
.status-current { background: var(--current) !important; color: #000 !important; }
#result-screen { background: var(--bg-dark); color: var(--text-main); height: 100%; overflow-y: auto; padding: 20px 15px; flex: 1; }
.res-header { text-align: center; margin-bottom: 15px; }
.res-header h2 { font-size: 19px; color: var(--primary); }
.score-card-compact { background: linear-gradient(135deg, var(--card-dark), var(--bg-dark)); border: 1px solid var(--primary); padding: 18px; border-radius: 12px; text-align: center; margin-bottom: 15px; }
.score-card-compact h1 { font-size: 36px; color: #fff; }
.res-grid-compact { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 18px; }
.res-box-compact { background: var(--card-dark); padding: 10px 5px; border-radius: 8px; text-align: center; border: 1px solid var(--border-color); }
.res-box-compact .val { font-size: 16px; font-weight: 900; margin-bottom: 2px; color: #fff; }
.res-box-compact .lbl { font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }
.btn-row { display: flex; gap: 10px; margin-bottom: 20px; }
.r-btn-small { flex: 1; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: bold; cursor: pointer; border: none; text-align: center; }
.r-btn-small.print-btn { background: var(--secondary); color: #fff; }
.review-box { background: var(--card-dark); padding: 14px; border-radius: 10px; margin-bottom: 12px; border: 1px solid var(--border-color); }
.review-q { font-size: 13.5px; font-weight: 600; margin-bottom: 10px; color: #fff; line-height: 1.4; }
.ans-row { display: flex; gap: 8px; font-size: 12.5px; margin-bottom: 4px; }
.ans-lbl { color: var(--text-muted); width: 85px; flex-shrink: 0; font-weight: bold; }
.solution-box { background: rgba(250, 204, 21, 0.05); border-left: 4px solid var(--primary); border-radius: 4px; padding: 10px; margin-top: 10px; font-size: 12.5px; color: #e2e8f0; line-height: 1.5; }
.solution-title { font-weight: bold; margin-bottom: 4px; color: var(--primary); font-size: 11px; text-transform: uppercase; }
@media print {
    @page { size: A4 portrait; margin: 12mm; }
    body { background: white !important; color: black !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .app-container { display: none !important; } 
    #print-container { display: block !important; width: 100%; position: relative; }
    .watermark-print {
        position: fixed; top: 40%; left: 5%; width: 90%; text-align: center;
        font-size: 5rem; font-weight: 900; color: rgba(0, 0, 0, 0.50) !important;
        opacity: 0.50 !important; transform: rotate(-35deg); z-index: 9999; pointer-events: none;
    }
    .print-header-box { border: 2px solid #000; padding: 14px 18px; border-radius: 8px; margin-bottom: 18px; text-align: center; }
    .print-q-box { margin-bottom: 15px !important; padding-bottom: 10px; border-bottom: 1px solid #cbd5e1; page-break-inside: avoid !important; }
    .print-q-head { display: flex; justify-content: space-between; margin-bottom: 5px; font-weight: bold; }
    .print-q-topic { background: #facc15 !important; color: #000 !important; padding: 2px 6px; font-size: 10px; border-radius: 12px; font-weight: 800; }
    .print-q-text { font-size: 13px; margin-bottom: 6px; font-weight: 600; color: #000 !important; }
    .print-ans-row { font-size: 11.5px; margin-bottom: 3px; }
    .print-sol-box { background: #f8fafc !important; border-left: 4px solid #facc15 !important; padding: 8px !important; margin-top: 5px; font-size: 11.5px; color: #1e293b !important; }
}
</style>
</head>
<body>
    <div id="print-container">
        <div class="watermark-print">SACHIN SHARMA | @UPSCHTML</div>
        <div id="print-content"></div>
    </div>
    <div class="app-container" id="main-app">
        <div id="home-screen">
            <div class="brand-header">
                <h1>UPSC ONLINE TEST DESK</h1>
                <p>PORTAL — __AUTH__</p>
            </div>
            <div class="test-info-card">
                <div class="test-title">__SUBJ__</div>
                <div class="test-subtitle">Test Series ID: __TID__</div>
                <div class="grid-2">
                    <div class="info-box"><div class="info-val">__QCNT__</div><div class="info-lbl">Questions</div></div>
                    <div class="info-box"><div class="info-val">__DUR__ Min</div><div class="info-lbl">Duration</div></div>
                    <div class="info-box"><div class="info-val" style="color: var(--correct);">+2.00</div><div class="info-lbl">Marks/Qn</div></div>
                    <div class="info-box"><div class="info-val" style="color: var(--wrong);">-0.66</div><div class="info-lbl">Negative</div></div>
                </div>
                <div class="name-input-container">
                    <input type="text" id="candidate-name" class="name-input" placeholder="यहाँ अपना नाम लिखें..." autocomplete="off">
                </div>
                <button class="start-btn" onclick="startTest()">▶|| परीक्षा शुरू करें (Start Test)</button>
            </div>
            <div style="text-align:center; font-size:11px; color:var(--text-muted); margin-top:20px;">© __AUTH__ - ALL RIGHTS RESERVED.</div>
        </div>

        <div id="test-screen" class="hidden">
            <div class="test-header">
                <div class="header-row">
                    <div class="head-left">
                        <h2>UPSC TEST — __TID__</h2>
                        <p>+2.00/Qn | -0.66 Neg</p>
                    </div>
                    <div class="head-right">
                        <div class="timer-box" id="timer-display">__DUR__:00</div>
                    </div>
                </div>
            </div>
            <div class="progress-bar-container"><div class="progress-bar" id="progress-bar"></div></div>
            <div class="sub-header">
                <span id="q-counter">प्रश्न 1 / __QCNT__</span>
                <span id="answered-counter">उत्तर दिए: 0</span>
            </div>
            <div class="question-area">
                <div class="q-card">
                    <div class="q-header-row">
                        <div class="q-tag" id="q-num-display">Q. 1 / __QCNT__</div>
                        <div class="q-topic-tag" id="q-topic-display">__SUBJ__</div>
                    </div>
                    <div class="q-text" id="q-text">लोड हो रहा है...</div>
                    <div class="options-list" id="options-container"></div>
                </div>
            </div>
            <div class="bottom-actions-container">
                <div class="nav-buttons-row">
                    <button class="nav-btn" onclick="prevQuestion()">◀ Prev</button>
                    <button class="nav-btn" onclick="markSkipped()">Skip</button>
                    <button class="nav-btn icon-btn" onclick="togglePalette()">▦</button>
                    <button class="nav-btn" id="next-btn" onclick="nextQuestion()" style="background: var(--primary); color: #000;">Next ▶</button>
                </div>
                <button class="big-green-btn" onclick="submitTest()">✅ Submit Exam</button>
            </div>
        </div>

        <div class="overlay" id="overlay" onclick="togglePalette()" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); display:none; z-index:50;"></div>
        <div class="palette-modal" id="palette-modal">
            <div class="palette-header">
                <h3 style="color:#fff; font-size:15px;">Question Palette</h3>
                <button onclick="togglePalette()" style="background:transparent; border:none; color:#fff; font-size:18px;">✕</button>
            </div>
            <div class="q-grid" id="palette-grid"></div>
            <div style="margin-top:10px;"><button class="big-green-btn" onclick="submitTest()">✅ Final Submit</button></div>
        </div>

        <div id="result-screen" class="hidden">
            <div class="res-header">
                <h2>UPSC EXAM RESULT SUMMARY</h2>
                <p><span id="res-display-name"></span> | __SUBJ__</p>
            </div>
            <div class="score-card-compact">
                <h1 id="final-score">0.00</h1>
                <p>Total Marks</p>
            </div>
            <div class="res-grid-compact">
                <div class="res-box-compact"><div class="val" id="stat-correct" style="color: var(--correct);">0</div><div class="lbl">सही</div></div>
                <div class="res-box-compact"><div class="val" id="stat-wrong" style="color: var(--wrong);">0</div><div class="lbl">गलत</div></div>
                <div class="res-box-compact"><div class="val" id="stat-skipped" style="color: var(--skipped);">0</div><div class="lbl">छूटे</div></div>
                <div class="res-box-compact"><div class="val" id="stat-accuracy" style="color: var(--primary);">0%</div><div class="lbl">सटीकता</div></div>
                <div class="res-box-compact"><div class="val" id="stat-time" style="color: var(--primary);">0m 0s</div><div class="lbl">समय</div></div>
                <div class="res-box-compact"><div class="val" id="stat-avg-time" style="color: var(--primary);">0s</div><div class="lbl">औसत/प्रश्न</div></div>
            </div>
            <div class="btn-row">
                <button class="r-btn-small print-btn" onclick="window.print()">🖨️ Print PDF Result (50% Watermark)</button>
            </div>
            <h3 style="font-size: 14px; margin-bottom: 12px; color: var(--primary);">📝 विस्तृत व्याख्या एवं समाधान</h3>
            <div id="review-container"></div>
        </div>
    </div>

    <script>
        const questions = __JSON__;
        const TOTAL_Q = questions.length;
        const MARKS_PER_CORRECT = 2.00;
        const NEGATIVE_MARK = 0.66;
        const TIME_MINUTES = __DUR__;

        let totalSeconds = TIME_MINUTES * 60;
        let timerInterval;
        let currentQIndex = 0;
        let userAnswers = new Array(TOTAL_Q).fill(null);
        let studentName = "";

        function startTest() {
            studentName = document.getElementById('candidate-name').value.trim();
            if(!studentName) { alert("कृपया अपना नाम दर्ज करें!"); return; }
            document.getElementById('res-display-name').innerText = studentName;
            document.getElementById('home-screen').classList.add('hidden');
            document.getElementById('test-screen').classList.remove('hidden');
            initPalette();
            loadQuestion(0);
            timerInterval = setInterval(() => {
                totalSeconds--;
                let mins = Math.floor(totalSeconds / 60);
                let secs = totalSeconds % 60;
                document.getElementById('timer-display').innerText = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
                if(totalSeconds <= 0) { clearInterval(timerInterval); submitTest(); }
            }, 1000);
        }

        function loadQuestion(index) {
            currentQIndex = index;
            document.getElementById('q-counter').innerText = 'प्रश्न ' + (index + 1) + ' / ' + TOTAL_Q;
            document.getElementById('q-num-display').innerText = 'Q. ' + (index + 1) + ' / ' + TOTAL_Q;
            const q = questions[index];
            document.getElementById('progress-bar').style.width = (((index + 1) / TOTAL_Q) * 100) + '%';
            document.getElementById('q-text').innerHTML = q.text;
            const optsContainer = document.getElementById('options-container');
            optsContainer.innerHTML = '';
            const letters = ['A', 'B', 'C', 'D'];
            q.options.forEach((optText, i) => {
                const optDiv = document.createElement('div');
                optDiv.className = 'option' + (userAnswers[index] === i ? ' selected' : '');
                optDiv.onclick = () => { userAnswers[currentQIndex] = i; loadQuestion(currentQIndex); };
                optDiv.innerHTML = '<div class="opt-letter">' + letters[i] + '</div><div class="opt-text">' + optText + '</div>';
                optsContainer.appendChild(optDiv);
            });
            document.getElementById('next-btn').innerText = (index === TOTAL_Q - 1) ? 'Submit' : 'Next ▶';
            document.getElementById('answered-counter').innerText = 'उत्तर दिए: ' + userAnswers.filter(ans => ans !== null).length;
            updatePaletteUI();
        }

        function markSkipped() { nextQuestion(); }
        function nextQuestion() { if (currentQIndex < TOTAL_Q - 1) loadQuestion(currentQIndex + 1); else submitTest(); }
        function prevQuestion() { if (currentQIndex > 0) loadQuestion(currentQIndex - 1); }

        function initPalette() {
            const grid = document.getElementById('palette-grid');
            grid.innerHTML = '';
            for(let i = 0; i < TOTAL_Q; i++) {
                const btn = document.createElement('button');
                btn.className = 'q-grid-btn';
                btn.id = 'pal-btn-' + i;
                btn.innerText = i + 1;
                btn.onclick = () => { loadQuestion(i); togglePalette(); };
                grid.appendChild(btn);
            }
        }

        function updatePaletteUI() {
            for(let i = 0; i < TOTAL_Q; i++) {
                const btn = document.getElementById('pal-btn-' + i);
                if(!btn) continue;
                btn.className = 'q-grid-btn';
                if(i === currentQIndex) {
                    btn.classList.add('status-current');
                } else if(userAnswers[i] !== null) {
                    btn.classList.add('status-answered');
                }
            }
        }

        function togglePalette() {
            const modal = document.getElementById('palette-modal');
            const overlay = document.getElementById('overlay');
            if(modal.classList.contains('open')) {
                modal.classList.remove('open');
                overlay.style.display = 'none';
            } else {
                updatePaletteUI();
                modal.classList.add('open');
                overlay.style.display = 'block';
            }
        }

        function submitTest() {
            if(totalSeconds > 0 && !confirm("क्या आप परीक्षा सबमिट करना चाहते हैं?")) return;
            clearInterval(timerInterval);
            document.getElementById('test-screen').classList.add('hidden');
            document.getElementById('result-screen').classList.remove('hidden');
            document.getElementById('palette-modal').classList.remove('open');
            document.getElementById('overlay').style.display = 'none';

            let correct = 0, wrong = 0, skipped = 0;
            const reviewContainer = document.getElementById('review-container');
            reviewContainer.innerHTML = '';
            const letters = ['A', 'B', 'C', 'D'];

            let printHTML = '<div class="print-header-box"><h2>UPSC CSE PRELIMS MOCK TEST</h2><h3>' + (questions[0].topic || '__SUBJ__') + '</h3><p>Candidate: ' + studentName + ' | Marking: +2.00, -0.66</p></div>';

            questions.forEach((q, idx) => {
                const uAns = userAnswers[idx];
                let statusColor = '', statusText = '';
                if (uAns === null) { skipped++; statusColor = 'var(--skipped)'; statusText = 'अनुत्तरित'; }
                else if (uAns === q.correctAnswer) { correct++; statusColor = 'var(--correct)'; statusText = 'सही (CORRECT)'; }
                else { wrong++; statusColor = 'var(--wrong)'; statusText = 'गलत (INCORRECT)'; }

                const uAnsText = uAns !== null ? '(' + letters[uAns] + ') ' + q.options[uAns] : 'कोई नहीं';
                const cAnsText = '(' + letters[q.correctAnswer] + ') ' + q.options[q.correctAnswer];

                reviewContainer.innerHTML += '<div class="review-box"><div class="q-header-row"><span style="color:var(--primary); font-weight:bold;">Q' + (idx + 1) + '.</span><span class="q-topic-tag">' + q.topic + '</span></div><div class="review-q">' + q.text + '</div><div class="ans-row"><div class="ans-lbl">आपका उत्तर:</div><div style="color:' + statusColor + '">' + uAnsText + '</div></div><div class="ans-row"><div class="ans-lbl">सही उत्तर:</div><div style="color:var(--correct)">' + cAnsText + '</div></div><div class="solution-box"><div class="solution-title">💡 आधिकारिक व्याख्या:</div>' + q.solution + '</div></div>';

                printHTML += '<div class="print-q-box"><div class="print-q-head"><span>Q' + (idx + 1) + '.</span><span class="print-q-topic">' + q.topic + '</span></div><div class="print-q-text">' + q.text + '</div><div class="print-ans-row"><strong>आपका उत्तर:</strong> ' + uAnsText + ' | <strong>सही:</strong> ' + cAnsText + '</div><div class="print-sol-box"><b>व्याख्या:</b> ' + q.solution + '</div></div>';
            });

            document.getElementById('print-content').innerHTML = printHTML;
            let marks = Math.max(0, (correct * MARKS_PER_CORRECT) - (wrong * NEGATIVE_MARK));
            document.getElementById('final-score').innerHTML = marks.toFixed(2) + ' <span style="font-size:16px; color:var(--text-muted);">/ ' + (TOTAL_Q * MARKS_PER_CORRECT).toFixed(2) + '</span>';
            document.getElementById('stat-correct').innerText = correct;
            document.getElementById('stat-wrong').innerText = wrong;
            document.getElementById('stat-skipped').innerText = skipped;
            let acc = (correct + wrong) > 0 ? Math.round((correct / (correct + wrong)) * 100) : 0;
            document.getElementById('stat-accuracy').innerText = acc + '%';
            let timeTaken = (TIME_MINUTES * 60) - totalSeconds;
            document.getElementById('stat-time').innerText = Math.floor(timeTaken/60) + 'm ' + (timeTaken%60) + 's';
            document.getElementById('stat-avg-time').innerText = Math.round(timeTaken/TOTAL_Q) + 's';
            window.scrollTo(0,0);
        }
    </script>
</body>
</html>"""

    html_out = html_template.replace("__SUBJ__", subject_title)
    html_out = html_out.replace("__AUTH__", AUTHOR_NAME)
    html_out = html_out.replace("__TID__", test_id)
    html_out = html_out.replace("__QCNT__", str(q_count))
    html_out = html_out.replace("__DUR__", str(duration_min))
    html_out = html_out.replace("__JSON__", questions_json)
    return html_out
