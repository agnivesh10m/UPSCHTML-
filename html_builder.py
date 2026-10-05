import re
import json

def clean_all_markdown_and_fix_content(raw_text: str) -> str:
    """मार्कडाउन स्टार्स और अवांछित सिंबल हटाकर साफ और सुंदर टेक्स्ट तैयार करता है"""
    if not raw_text:
        return ""
    text = re.sub(r'[*_`#]', '', raw_text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def build_standalone_master_html(title: str, content: str, date_str: str = "", is_trending: bool = False) -> str:
    """UPSC 360° दैनिक, साप्ताहिक, मासिक व ट्रेंडिंग नोट्स का प्रीमियम HTML इंजन"""
    clean_body = clean_all_markdown_and_fix_content(content)
    # पैराग्राफ को HTML पैराग्राफ में बदलना
    formatted_content = "".join([f"<p>{p.strip()}</p>" for p in clean_body.split("\n\n") if p.strip()])

    html = f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{title} | SACHIN SHARMA</title>
<style>
:root {{
    --bg-dark: #0b0f19;
    --card-dark: #151b2b;
    --primary: #facc15;
    --secondary: #3b82f6;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --border-color: #1e293b;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
body {{ background-color: var(--bg-dark); color: var(--text-main); line-height: 1.7; padding: 20px 15px; display: flex; justify-content: center; }}
.container {{ width: 100%; max-width: 750px; background: var(--card-dark); border: 1px solid var(--border-color); border-radius: 16px; padding: 24px 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); }}
.header-box {{ border-bottom: 2px solid var(--primary); padding-bottom: 15px; margin-bottom: 20px; text-align: center; }}
.header-box h1 {{ color: var(--primary); font-size: 22px; font-weight: 800; letter-spacing: 0.5px; margin-bottom: 6px; }}
.header-box p {{ color: var(--text-muted); font-size: 12px; font-weight: 600; text-transform: uppercase; }}
.content-area p {{ font-size: 14.5px; margin-bottom: 16px; color: #e2e8f0; }}
.content-area strong {{ color: var(--primary); }}
.table-box {{ width: 100%; overflow-x: auto; margin: 18px 0; border-radius: 8px; border: 1px solid var(--border-color); }}
table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
th {{ background: #1e293b; color: var(--primary); padding: 10px 12px; font-weight: bold; border-bottom: 1px solid var(--border-color); }}
td {{ padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.05); color: #cbd5e1; }}
.footer-tag {{ margin-top: 30px; padding-top: 15px; border-top: 1px dashed var(--border-color); text-align: center; font-size: 11px; color: var(--text-muted); }}
@media print {{
    body {{ background: white !important; color: black !important; }}
    .container {{ border: none; box-shadow: none; max-width: 100%; padding: 0; }}
    .header-box h1 {{ color: black; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header-box">
        <h1>{title}</h1>
        <p>मार्गदर्शक: SACHIN SHARMA | स्रोत: THE HINDU, PIB, VISION IAS</p>
    </div>
    <div class="content-area">
        {formatted_content}
    </div>
    <div class="footer-tag">
        © SACHIN SHARMA (@UPSCHTML) - सर्वाधिकार सुरक्षित
    </div>
</div>
</body>
</html>"""
    return html

def build_vision_ias_interactive_portal(subj: str, test_id: str, cnt: int, json_questions_str: str) -> str:
    """main.py की लाइन 192 पर कॉल होने वाला विजन IAS लाइव OMR टेस्ट पोर्टल इंजन"""
    try:
        # JSON सत्यापन
        parsed = json.loads(json_questions_str)
        clean_json_str = json.dumps(parsed, ensure_ascii=False)
    except Exception:
        clean_json_str = json_questions_str

    html_content = f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>UPSC CSE - {subj} | SACHIN SHARMA</title>
<style>
:root {{
    --home-bg-top: #0f172a; --home-bg-bot: #020617; --home-card: #1e293b; --home-box: #334155;      
    --home-text-accent: #facc15; --home-btn: #facc15; --bg-dark: #0b0f19; --card-dark: #151b2b;     
    --primary: #facc15; --secondary: #3b82f6; --text-main: #f8fafc; --text-muted: #94a3b8;
    --border-color: #1e293b; --option-bg: #0b0f19; --correct: #10b981; --wrong: #ef4444; --skipped: #3b82f6; --current: #facc15;       
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; -webkit-tap-highlight-color: transparent; }}
body {{ background-color: var(--bg-dark); color: var(--text-main); display: flex; justify-content: center; height: 100vh; height: 100dvh; overflow: hidden; }}
.app-container {{ width: 100%; max-width: 540px; background-color: var(--bg-dark); display: flex; flex-direction: column; position: relative; height: 100%; border: none; box-shadow: 0 0 50px rgba(0,0,0,0.8); }}
.hidden {{ display: none !important; }}
#print-container {{ display: none; }}

#home-screen {{ background: linear-gradient(180deg, var(--home-bg-top) 0%, var(--home-bg-bot) 100%); padding: 24px 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100%; overflow-y: auto; }}
.brand-header {{ text-align: center; margin-bottom: 24px; width: 100%; }}
.brand-header h1 {{ color: var(--home-text-accent); font-size: 26px; font-weight: 900; letter-spacing: 1.5px; margin-bottom: 6px; text-shadow: 0 2px 12px rgba(250, 204, 21, 0.35); }}
.brand-header p {{ color: #e2e8f0; font-size: 11px; letter-spacing: 3px; font-weight: 700; text-transform: uppercase; }}
.test-info-card {{ background: var(--home-card); padding: 24px 20px; border-radius: 18px; width: 100%; box-shadow: 0 15px 35px rgba(0,0,0,0.55); border: 1px solid rgba(250, 204, 21, 0.25); }}
.test-title {{ font-size: 17px; font-weight: 800; text-align: center; margin-bottom: 4px; color: #ffffff; line-height: 1.4; }}
.test-subtitle {{ font-size: 12px; color: #cbd5e1; text-align: center; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px dashed rgba(255,255,255,0.25); }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }}
.info-box {{ background: var(--home-box); padding: 12px 10px; border-radius: 12px; text-align: center; border: 1px solid rgba(255,255,255,0.08); }}
.info-val {{ font-size: 19px; font-weight: 900; color: var(--home-text-accent); margin-bottom: 3px; }}
.info-lbl {{ font-size: 10px; color: #ffffff; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; }}
.name-input-container {{ margin-bottom: 20px; }}
.name-input {{ width: 100%; padding: 14px 16px; border-radius: 12px; border: 2px solid var(--home-text-accent); background: #0b0f19; color: #ffffff; font-size: 15px; font-weight: 700; text-align: center; outline: none; }}
.start-btn {{ width: 100%; padding: 16px; border-radius: 14px; background: var(--home-btn); color: #0f172a; font-size: 16px; font-weight: 800; border: none; cursor: pointer; box-shadow: 0 5px 20px rgba(250, 204, 21, 0.4); text-transform: uppercase; letter-spacing: 1.2px; }}

#test-screen {{ display: flex; flex-direction: column; height: 100%; background: var(--bg-dark); }}
.test-header {{ flex-shrink: 0; background: var(--card-dark); border-bottom: 1px solid var(--border-color); padding: 12px 16px; }}
.header-row {{ display: flex; justify-content: space-between; align-items: center; }}
.head-left h2 {{ font-size: 13px; color: var(--primary); font-weight: 900; text-transform: uppercase; }}
.head-left p {{ font-size: 11px; color: var(--text-muted); font-weight: 600; margin-top: 2px; }}
.timer-box {{ font-size: 14px; font-weight: 800; color: #0b0f19; background: var(--primary); padding: 4px 10px; border-radius: 6px; display: inline-block; }}
.progress-bar-container {{ height: 4px; background: var(--border-color); width: 100%; }}
.progress-bar {{ height: 100%; background: var(--primary); width: 0%; transition: width 0.3s ease; }}
.sub-header {{ display: flex; justify-content: space-between; padding: 10px 16px; font-size: 12px; font-weight: 700; background: var(--bg-dark); color: var(--text-muted); border-bottom: 1px solid var(--border-color); }}
.question-area {{ flex: 1; padding: 14px 16px; overflow-y: auto; background: var(--bg-dark); padding-bottom: 24px; }}
.q-card {{ background: var(--card-dark); padding: 18px 14px; border-radius: 12px; border: 1px solid var(--border-color); margin-bottom: 12px; }}
.q-header-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }}
.q-tag {{ background: rgba(250, 204, 21, 0.15); color: var(--primary); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; }}
.q-topic-tag {{ background: var(--primary); color: #000; padding: 4px 12px; border-radius: 15px; font-size: 11px; font-weight: 800; max-width: 65%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.q-text {{ font-size: 15px; line-height: 1.6; font-weight: 500; margin-bottom: 18px; color: #ffffff; }}
.options-list {{ display: flex; flex-direction: column; gap: 10px; }}
.option {{ display: flex; align-items: center; padding: 12px 14px; background: var(--option-bg); border: 1px solid var(--border-color); border-radius: 10px; cursor: pointer; transition: all 0.2s ease; }}
.option.selected {{ border-color: var(--primary); background: rgba(250, 204, 21, 0.12); }}
.opt-letter {{ width: 24px; height: 24px; border-radius: 6px; background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800; margin-right: 12px; color: var(--text-muted); flex-shrink: 0; }}
.option.selected .opt-letter {{ background: var(--primary); color: #000; }}
.opt-text {{ font-size: 14px; line-height: 1.4; color: #f1f5f9; }}
.bottom-actions-container {{ flex-shrink: 0; background: var(--card-dark); padding: 10px 14px; border-top: 1px solid var(--border-color); }}
.nav-buttons-row {{ display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }}
.nav-btn {{ flex: 1; height: 38px; padding: 0; border-radius: 8px; font-size: 12px; font-weight: 700; border: none; background: var(--bg-dark); color: var(--text-main); cursor: pointer; display: flex; align-items: center; justify-content: center; border: 1px solid var(--border-color); }}
.nav-btn.icon-btn {{ flex: 0.45; font-size: 17px; }}
.big-green-btn {{ width: 100% !important; height: 42px !important; background: #10b981 !important; color: #ffffff !important; border-radius: 10px !important; font-weight: 800 !important; font-size: 14px !important; border: none !important; cursor: pointer !important; text-transform: uppercase !important; display: flex; align-items: center; justify-content: center; }}

.palette-modal {{ position: absolute; bottom: 0; left: 0; width: 100%; max-height: 80vh; background: var(--card-dark); border-top-left-radius: 24px; border-top-right-radius: 24px; padding: 20px 18px; transform: translateY(100%); transition: transform 0.3s ease; z-index: 100; display: flex; flex-direction: column; border-top: 2px solid var(--primary); }}
.palette-modal.open {{ transform: translateY(0); }}
.palette-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; }}
.q-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; overflow-y: auto; padding-bottom: 16px; flex: 1; }}
.q-grid-btn {{ width: 100%; aspect-ratio: 1; border-radius: 10px; border: 1px solid var(--border-color); background: var(--bg-dark); color: var(--text-main); font-weight: 800; font-size: 13px; cursor: pointer; }}
.status-answered {{ background: var(--correct) !important; color: #ffffff !important; border-color: var(--correct) !important; }}
.status-current {{ background: var(--current) !important; color: #000000 !important; border-color: var(--current) !important; }}

#result-screen {{ background: var(--bg-dark); color: var(--text-main); height: 100%; overflow-y: auto; padding: 24px 16px; flex: 1; }}
.res-header {{ text-align: center; margin-bottom: 18px; }}
.res-header h2 {{ font-size: 20px; color: var(--primary); font-weight: 900; }}
.score-card-compact {{ background: linear-gradient(135deg, var(--card-dark), var(--bg-dark)); border: 1px solid var(--primary); padding: 20px; border-radius: 16px; text-align: center; margin-bottom: 18px; }}
.score-card-compact h1 {{ font-size: 38px; color: #ffffff; font-weight: 900; }}
.res-grid-compact {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px; }}
.res-box-compact {{ background: var(--card-dark); padding: 12px 6px; border-radius: 10px; text-align: center; border: 1px solid var(--border-color); }}
.res-box-compact .val {{ font-size: 17px; font-weight: 900; margin-bottom: 3px; color: #ffffff; }}
.res-box-compact .lbl {{ font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
.btn-row {{ display: flex; gap: 10px; margin-bottom: 24px; }}
.r-btn-small {{ flex: 1; padding: 13px; border-radius: 10px; font-size: 13px; font-weight: 800; cursor: pointer; border: none; text-align: center; }}
.r-btn-small.print-btn {{ background: var(--secondary); color: #ffffff; }}
.review-box {{ background: var(--card-dark); padding: 16px 14px; border-radius: 12px; margin-bottom: 14px; border: 1px solid var(--border-color); }}
.review-q {{ font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #ffffff; line-height: 1.5; }}
.ans-row {{ display: flex; gap: 8px; font-size: 13px; margin-bottom: 6px; }}
.ans-lbl {{ color: var(--text-muted); width: 85px; flex-shrink: 0; font-weight: 700; }}
.solution-box {{ background: rgba(250, 204, 21, 0.05); border-left: 4px solid var(--primary); border-radius: 6px; padding: 12px; margin-top: 12px; font-size: 13px; color: #e2e8f0; line-height: 1.6; }}
.solution-title {{ font-weight: 800; margin-bottom: 6px; color: var(--primary); font-size: 11.5px; text-transform: uppercase; }}

@media print {{
    @page {{ size: A4 portrait; margin: 12mm; }}
    body {{ background: #ffffff !important; color: #000000 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .app-container {{ display: none !important; }} 
    #print-container {{ display: block !important; width: 100%; position: relative; }}
    .watermark-print {{
        position: fixed; top: 38%; left: 5%; width: 90%; text-align: center;
        font-size: 4.8rem; font-weight: 900; color: rgba(0, 0, 0, 0.50) !important;
        opacity: 0.50 !important; transform: rotate(-35deg); z-index: 9999; pointer-events: none;
    }}
    .print-header-box {{ border: 2px solid #000000; padding: 14px 18px; border-radius: 8px; margin-bottom: 18px; text-align: center; }}
    .print-q-box {{ margin-bottom: 16px !important; padding-bottom: 10px; border-bottom: 1px solid #cbd5e1; page-break-inside: avoid !important; }}
    .print-q-head {{ display: flex; justify-content: space-between; margin-bottom: 6px; font-weight: bold; }}
    .print-q-topic {{ background: #facc15 !important; color: #000000 !important; padding: 2px 8px; font-size: 10px; border-radius: 12px; font-weight: 800; }}
    .print-q-text {{ font-size: 13px; margin-bottom: 6px; font-weight: 600; color: #000000 !important; line-height: 1.4; }}
    .print-ans-row {{ font-size: 11.5px; margin-bottom: 3px; }}
    .print-sol-box {{ background: #f8fafc !important; border-left: 4px solid #facc15 !important; padding: 8px 10px !important; margin-top: 6px; font-size: 11.5px; color: #1e293b !important; line-height: 1.4; }}
}}
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
                <p>PORTAL — SACHIN SHARMA</p>
            </div>
            <div class="test-info-card">
                <div class="test-title">{subj}</div>
                <div class="test-subtitle">Test Series ID: {test_id}</div>
                <div class="grid-2">
                    <div class="info-box"><div class="info-val">{cnt}</div><div class="info-lbl">Questions</div></div>
                    <div class="info-box"><div class="info-val">60 Min</div><div class="info-lbl">Duration</div></div>
                    <div class="info-box"><div class="info-val" style="color: var(--correct);">+2.00</div><div class="info-lbl">Marks/Qn</div></div>
                    <div class="info-box"><div class="info-val" style="color: var(--wrong);">-0.66</div><div class="info-lbl">Negative</div></div>
                </div>
                <div class="name-input-container">
                    <input type="text" id="candidate-name" class="name-input" placeholder="यहाँ अपना नाम लिखें..." autocomplete="off">
                </div>
                <button class="start-btn" id="start-btn-trigger">▶|| परीक्षा शुरू करें (Start Test)</button>
            </div>
            <div style="text-align:center; font-size:11px; color:var(--text-muted); margin-top:20px; font-weight:600;">
                © SACHIN SHARMA - ALL RIGHTS RESERVED.
            </div>
        </div>

        <div id="test-screen" class="hidden">
            <div class="test-header">
                <div class="header-row">
                    <div class="head-left">
                        <h2>UPSC TEST — {test_id}</h2>
                        <p>+2.00/Qn | -0.66 Neg</p>
                    </div>
                    <div class="head-right">
                        <div class="timer-box" id="timer-display">60:00</div>
                    </div>
                </div>
            </div>
            <div class="progress-bar-container"><div class="progress-bar" id="progress-bar"></div></div>
            <div class="sub-header">
                <span id="q-counter">प्रश्न 1 / {cnt}</span>
                <span id="answered-counter">उत्तर दिए: 0</span>
            </div>
            <div class="question-area">
                <div class="q-card">
                    <div class="q-header-row">
                        <div class="q-tag" id="q-num-display">Q. 1 / {cnt}</div>
                        <div class="q-topic-tag" id="q-topic-display">{subj}</div>
                    </div>
                    <div class="q-text" id="q-text">लोड हो रहा है...</div>
                    <div class="options-list" id="options-container"></div>
                </div>
            </div>
            <div class="bottom-actions-container">
                <div class="nav-buttons-row">
                    <button class="nav-btn" id="prev-btn">◀ Prev</button>
                    <button class="nav-btn" id="skip-btn">Skip</button>
                    <button class="nav-btn icon-btn" id="pal-btn-toggle">▦</button>
                    <button class="nav-btn" id="next-btn" style="background: var(--primary); color: #000; font-weight:800;">Next ▶</button>
                </div>
                <button class="big-green-btn" id="submit-btn-mid">✅ Submit Exam</button>
            </div>
        </div>

        <div class="overlay" id="overlay" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.65); display:none; z-index:50;"></div>
        <div class="palette-modal" id="palette-modal">
            <div class="palette-header">
                <h3 style="color:#ffffff; font-size:15px; font-weight:800;">Question Palette</h3>
                <button id="close-pal-btn" style="background:transparent; border:none; color:#ffffff; font-size:20px; cursor:pointer;">✕</button>
            </div>
            <div class="q-grid" id="palette-grid"></div>
            <div style="margin-top:12px;"><button class="big-green-btn" id="final-sub-btn">✅ Final Submit</button></div>
        </div>

        <div id="result-screen" class="hidden">
            <div class="res-header">
                <h2>UPSC EXAM RESULT SUMMARY</h2>
                <p><span id="res-display-name"></span> | {subj}</p>
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
                <button class="r-btn-small print-btn" onclick="window.print()">🖨️️ Print PDF Result (50% Watermark)</button>
            </div>
            <h3 style="font-size: 14px; margin-bottom: 14px; color: var(--primary); font-weight:800;">📝 विस्तृत व्याख्या एवं समाधान</h3>
            <div id="review-container"></div>
        </div>
    </div>

    <script>
        const questions = {clean_json_str};
        const TOTAL_Q = questions.length;
        const MARKS_PER_CORRECT = 2.00;
        const NEGATIVE_MARK = 0.66;
        const TIME_MINUTES = 60;

        let totalSeconds = TIME_MINUTES * 60;
        let timerInterval = null;
        let currentQIndex = 0;
        let userAnswers = new Array(TOTAL_Q).fill(null);
        let studentName = "";

        document.getElementById('start-btn-trigger').addEventListener('click', function() {{
            studentName = document.getElementById('candidate-name').value.trim();
            if(!studentName) {{ alert("कृपया अपना नाम दर्ज करें!"); return; }}
            document.getElementById('res-display-name').innerText = studentName;
            document.getElementById('home-screen').classList.add('hidden');
            document.getElementById('test-screen').classList.remove('hidden');
            initPalette();
            loadQuestion(0);
            
            timerInterval = setInterval(() => {{
                totalSeconds--;
                let mins = Math.floor(totalSeconds / 60);
                let secs = totalSeconds % 60;
                document.getElementById('timer-display').innerText = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
                if(totalSeconds <= 0) {{ clearInterval(timerInterval); submitTest(); }}
            }}, 1000);
        }});

        function loadQuestion(index) {{
            currentQIndex = index;
            document.getElementById('q-counter').innerText = 'प्रश्न ' + (index + 1) + ' / ' + TOTAL_Q;
            document.getElementById('q-num-display').innerText = 'Q. ' + (index + 1) + ' / ' + TOTAL_Q;
            
            const q = questions[index];
            document.getElementById('progress-bar').style.width = (((index + 1) / TOTAL_Q) * 100) + '%';
            document.getElementById('q-text').innerHTML = q.text;
            
            const optsContainer = document.getElementById('options-container');
            optsContainer.innerHTML = '';
            const letters = ['A', 'B', 'C', 'D'];
            
            q.options.forEach((optText, i) => {{
                const optDiv = document.createElement('div');
                optDiv.className = 'option' + (userAnswers[index] === i ? ' selected' : '');
                optDiv.onclick = () => {{ userAnswers[currentQIndex] = i; loadQuestion(currentQIndex); }};
                optDiv.innerHTML = '<div class="opt-letter">' + letters[i] + '</div><div class="opt-text">' + optText + '</div>';
                optsContainer.appendChild(optDiv);
            }});
            
            document.getElementById('next-btn').innerText = (index === TOTAL_Q - 1) ? 'Submit' : 'Next ▶';
            document.getElementById('answered-counter').innerText = 'उत्तर दिए: ' + userAnswers.filter(ans => ans !== null).length;
            updatePaletteUI();
        }}

        function markSkipped() {{ nextQuestion(); }}
        function nextQuestion() {{
            if (currentQIndex < TOTAL_Q - 1) loadQuestion(currentQIndex + 1);
            else submitTest();
        }}
        function prevQuestion() {{
            if (currentQIndex > 0) loadQuestion(currentQIndex - 1);
        }}

        document.getElementById('next-btn').onclick = nextQuestion;
        document.getElementById('prev-btn').onclick = prevQuestion;
        document.getElementById('skip-btn').onclick = markSkipped;
        document.getElementById('submit-btn-mid').onclick = submitTest;
        document.getElementById('final-sub-btn').onclick = submitTest;

        function initPalette() {{
            const grid = document.getElementById('palette-grid');
            grid.innerHTML = '';
            for(let i = 0; i < TOTAL_Q; i++) {{
                const btn = document.createElement('button');
                btn.className = 'q-grid-btn';
                btn.id = 'pal-btn-' + i;
                btn.innerText = i + 1;
                btn.onclick = () => {{ loadQuestion(i); togglePalette(); }};
                grid.appendChild(btn);
            }}
        }}

        function updatePaletteUI() {{
            for(let i = 0; i < TOTAL_Q; i++) {{
                const btn = document.getElementById('pal-btn-' + i);
                if(!btn) continue;
                btn.className = 'q-grid-btn';
                if(i === currentQIndex) btn.classList.add('status-current');
                else if(userAnswers[i] !== null) btn.classList.add('status-answered');
            }}
        }}

        function togglePalette() {{
            const modal = document.getElementById('palette-modal');
            const overlay = document.getElementById('overlay');
            if(modal.classList.contains('open')) {{
                modal.classList.remove('open');
                overlay.style.display = 'none';
            }} else {{
                updatePaletteUI();
                modal.classList.add('open');
                overlay.style.display = 'block';
            }}
        }}

        document.getElementById('pal-btn-toggle').onclick = togglePalette;
        document.getElementById('close-pal-btn').onclick = togglePalette;
        document.getElementById('overlay').onclick = togglePalette;

        function submitTest() {{
            if(totalSeconds > 0 && !confirm("क्या आप परीक्षा सबमिट करना चाहते हैं?")) return;
            if(timerInterval) clearInterval(timerInterval);
            document.getElementById('test-screen').classList.add('hidden');
            document.getElementById('result-screen').classList.remove('hidden');
            document.getElementById('palette-modal').classList.remove('open');
            document.getElementById('overlay').style.display = 'none';

            let correct = 0, wrong = 0, skipped = 0;
            const reviewContainer = document.getElementById('review-container');
            reviewContainer.innerHTML = '';
            const letters = ['A', 'B', 'C', 'D'];

            let printHTML = '<div class="print-header-box"><h2>UPSC CSE PRELIMS MOCK TEST</h2><h3>' + (questions[0].topic || '{subj}') + '</h3><p>Candidate: ' + studentName + ' | Marking: +2.00, -0.66</p></div>';

            questions.forEach((q, idx) => {{
                const uAns = userAnswers[idx];
                let statusColor = '', statusText = '';
                if (uAns === null) {{ skipped++; statusColor = 'var(--skipped)'; statusText = 'अनुत्तरित'; }}
                else if (uAns === q.correctAnswer) {{ correct++; statusColor = 'var(--correct)'; statusText = 'सही (CORRECT)'; }}
                else {{ wrong++; statusColor = 'var(--wrong)'; statusText = 'गलत (INCORRECT)'; }}

                const uAnsText = uAns !== null ? '(' + letters[uAns] + ') ' + q.options[uAns] : 'कोई नहीं';
                const cAnsText = '(' + letters[q.correctAnswer] + ') ' + q.options[q.correctAnswer];

                reviewContainer.innerHTML += '<div class="review-box"><div class="q-header-row"><span style="color:var(--primary); font-weight:bold;">Q' + (idx + 1) + '.</span><span class="q-topic-tag">' + (q.topic || '{subj}') + '</span></div><div class="review-q">' + q.text + '</div><div class="ans-row"><div class="ans-lbl">आपका उत्तर:</div><div style="color:' + statusColor + '; font-weight:bold;">' + uAnsText + '</div></div><div class="ans-row"><div class="ans-lbl">सही उत्तर:</div><div style="color:var(--correct); font-weight:bold;">' + cAnsText + '</div></div><div class="solution-box"><div class="solution-title">💡 आधिकारिक व्याख्या:</div>' + q.solution + '</div></div>';

                printHTML += '<div class="print-q-box"><div class="print-q-head"><span>Q' + (idx + 1) + '.</span><span class="print-q-topic">' + (q.topic || '{subj}') + '</span></div><div class="print-q-text">' + q.text + '</div><div class="print-ans-row"><strong>आपका उत्तर:</strong> ' + uAnsText + ' | <strong>सही:</strong> ' + cAnsText + '</div><div class="print-sol-box"><b>व्याख्या:</b> ' + q.solution + '</div></div>';
            }});

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
        }}
    </script>
</body>
</html>"""
    return html_content

# बैकवर्ड कम्पैटिबिलिटी के लिए उपनाम
generate_quiz_html = build_vision_ias_interactive_portal
