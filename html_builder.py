import re
import json

def clean_all_markdown_and_fix_content(raw_text: str) -> str:
    if not raw_text:
        return ""
    text = re.sub(r'[*_`#]', '', raw_text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def build_standalone_master_html(title: str, content: str, date_str: str = "", is_trending: bool = False) -> str:
    clean_body = clean_all_markdown_and_fix_content(content)
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
    """ओरिजिनल 20482.html जैसा ही शुद्ध व मजबूत पोर्टल"""
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
.app-container {{ width: 100%; max-width: 520px; background-color: var(--bg-dark); display: flex; flex-direction: column; position: relative; height: 100%; border: none; }}
.hidden {{ display: none !important; }}
#print-container {{ display: none; }}
#home-screen {{ background: linear-gradient(180deg, var(--home-bg-top) 0%, var(--home-bg-bot) 100%); padding: 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100%; overflow-y: auto; }}
.brand-header {{ text-align: center; margin-bottom: 20px; width: 100%; }}
.brand-header h1 {{ color: var(--home-text-accent); font-size: 26px; font-weight: 900; letter-spacing: 1px; margin-bottom: 4px; text-shadow: 0 2px 10px rgba(250, 204, 21, 0.4); }}
.brand-header p {{ color: #e2e8f0; font-size: 11px; letter-spacing: 3px; font-weight: 600; text-transform: uppercase; }}
.test-info-card {{ background: var(--home-card); padding: 22px 18px; border-radius: 16px; width: 100%; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid rgba(250, 204, 21, 0.2); }}
.test-title {{ font-size: 17px; font-weight: bold; text-align: center; margin-bottom: 4px; color: white; }}
.test-subtitle {{ font-size: 12px; color: #cbd5e1; text-align: center; margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px dashed rgba(255,255,255,0.3); }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 18px; }}
.info-box {{ background: var(--home-box); padding: 10px 8px; border-radius: 10px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }}
.info-val {{ font-size: 18px; font-weight: 800; color: var(--home-text-accent); margin-bottom: 2px; }}
.info-lbl {{ font-size: 10px; color: white; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }}
.name-input-container {{ margin-bottom: 18px; }}
.name-input {{ width: 100%; padding: 13px 15px; border-radius: 10px; border: 2px solid var(--home-text-accent); background: #0b0f19; color: white; font-size: 15px; font-weight: bold; text-align: center; outline: none; }}
.start-btn {{ width: 100%; padding: 15px; border-radius: 12px; background: var(--home-btn); color: #0f172a; font-size: 16px; font-weight: bold; border: none; cursor: pointer; box-shadow: 0 4px 15px rgba(250, 204, 21, 0.4); text-transform: uppercase; letter-spacing: 1px; }}
#test-screen {{ display: flex; flex-direction: column; height: 100%; background: var(--bg-dark); }}
.test-header {{ flex-shrink: 0; background: var(--card-dark); border-bottom: 1px solid var(--border-color); padding: 10px 15px; }}
.header-row {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.head-left h2 {{ font-size: 12px; color: var(--primary); font-weight: 800; text-transform: uppercase; }}
.head-left p {{ font-size: 11px; color: var(--text-muted); font-weight: 600; }}
.timer-box {{ font-size: 13px; font-weight: bold; color: #0b0f19; background: var(--primary); padding: 2px 8px; border-radius: 4px; display: inline-block; }}
.progress-bar-container {{ height: 3px; background: var(--border-color); width: 100%; }}
.progress-bar {{ height: 100%; background: var(--primary); width: 0%; transition: width 0.3s ease; }}
.sub-header {{ display: flex; justify-content: space-between; padding: 8px 15px; font-size: 12px; font-weight: 600; background: var(--bg-dark); color: var(--text-muted); border-bottom: 1px solid var(--border-color); }}
.question-area {{ flex: 1; padding: 12px 15px; overflow-y: auto; background: var(--bg-dark); padding-bottom: 20px; }}
.q-card {{ background: var(--card-dark); padding: 15px 12px; border-radius: 10px; border: 1px solid var(--border-color); margin-bottom: 10px; }}
.q-header-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
.q-tag {{ background: rgba(250, 204, 21, 0.15); color: var(--primary); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
.q-topic-tag {{ background: var(--primary); color: #000; padding: 4px 10px; border-radius: 15px; font-size: 11px; font-weight: 800; }}
.q-text {{ font-size: 14.5px; line-height: 1.5; font-weight: 500; margin-bottom: 15px; color: #fff; }}
.options-list {{ display: flex; flex-direction: column; gap: 8px; }}
.option {{ display: flex; align-items: center; padding: 10px 12px; background: var(--option-bg); border: 1px solid var(--border-color); border-radius: 8px; cursor: pointer; }}
.option.selected {{ border-color: var(--primary); background: rgba(250, 204, 21, 0.12); }}
.opt-letter {{ width: 22px; height: 22px; border-radius: 4px; background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 10px; color: var(--text-muted); flex-shrink: 0; }}
.option.selected .opt-letter {{ background: var(--primary); color: #000; }}
.opt-text {{ font-size: 13.5px; line-height: 1.3; color: #f1f5f9; }}
.bottom-actions-container {{ flex-shrink: 0; background: var(--card-dark); padding: 8px 12px; border-top: 1px solid var(--border-color); }}
.nav-buttons-row {{ display: flex; justify-content: space-between; gap: 6px; margin-bottom: 6px; }}
.nav-btn {{ flex: 1; height: 36px; padding: 0; border-radius: 6px; font-size: 12px; font-weight: 700; border: none; background: var(--bg-dark); color: var(--text-main); cursor: pointer; display: flex; align-items: center; justify-content: center; }}
.nav-btn.icon-btn {{ flex: 0.4; font-size: 16px; }}
.big-green-btn {{ width: 100% !important; height: 40px !important; background: #10b981 !important; color: white !important; border-radius: 8px !important; font-weight: bold !important; font-size: 14px !important; border: none !important; cursor: pointer !important; text-transform: uppercase !important; display: flex; align-items: center; justify-content: center; }}
.palette-modal {{ position: absolute; bottom: 0; left: 0; width: 100%; max-height: 80vh; background: var(--card-dark); border-top-left-radius: 20px; border-top-right-radius: 20px; padding: 18px; transform: translateY(100%); transition: transform 0.3s ease; z-index: 100; display: flex; flex-direction: column; border-top: 1px solid var(--primary); }}
.palette-modal.open {{ transform: translateY(0); }}
.palette-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }}
.q-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; overflow-y: auto; padding-bottom: 12px; flex: 1; }}
.q-grid-btn {{ width: 100%; aspect-ratio: 1; border-radius: 8px; border: none; background: var(--bg-dark); color: var(--text-main); font-weight: bold; font-size: 13px; cursor: pointer; }}
.status-answered {{ background: var(--correct) !important; color: white !important; }}
.status-current {{ background: var(--current) !important; color: #000 !important; }}
#result-screen {{ background: var(--bg-dark); color: var(--text-main); height: 100%; overflow-y: auto; padding: 20px 15px; flex: 1; }}
.res-header {{ text-align: center; margin-bottom: 15px; }}
.res-header h2 {{ font-size: 19px; color: var(--primary); }}
.score-card-compact {{ background: linear-gradient(135deg, var(--card-dark), var(--bg-dark)); border: 1px solid var(--primary); padding: 18px; border-radius: 12px; text-align: center; margin-bottom: 15px; }}
.score-card-compact h1 {{ font-size: 36px; color: #fff; }}
.res-grid-compact {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 18px; }}
.res-box-compact {{ background: var(--card-dark); padding: 10px 5px; border-radius: 8px; text-align: center; border: 1px solid var(--border-color); }}
.res-box-compact .val {{ font-size: 16px; font-weight: 900; margin-bottom: 2px; color: #fff; }}
.res-box-compact .lbl {{ font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
.btn-row {{ display: flex; gap: 10px; margin-bottom: 20px; }}
.r-btn-small {{ flex: 1; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: bold; cursor: pointer; border: none; text-align: center; }}
.r-btn-small.print-btn {{ background: var(--secondary); color: #fff; }}
.review-box {{ background: var(--card-dark); padding: 14px; border-radius: 10px; margin-bottom: 12px; border: 1px solid var(--border-color); }}
.review-q {{ font-size: 13.5px; font-weight: 600; margin-bottom: 10px; color: #fff; line-height: 1.4; }}
.ans-row {{ display: flex; gap: 8px; font-size: 12.5px; margin-bottom: 4px; }}
.ans-lbl {{ color: var(--text-muted); width: 85px; flex-shrink: 0; font-weight: bold; }}
.solution-box {{ background: rgba(250, 204, 21, 0.05); border-left: 4px solid var(--primary); border-radius: 4px; padding: 10px; margin-top: 10px; font-size: 12.5px; color: #e2e8f0; line-height: 1.5; }}
.solution-title {{ font-weight: bold; margin-bottom: 4px; color: var(--primary); font-size: 11px; text-transform: uppercase; }}
@media print {{
    @page {{ size: A4 portrait; margin: 12mm; }}
    body {{ background: white !important; color: black !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .app-container {{ display: none !important; }} 
    #print-container {{ display: block !important; width: 100%; position: relative; }}
    .watermark-print {{
        position: fixed; top: 40%; left: 5%; width: 90%; text-align: center;
        font-size: 5rem; font-weight: 900; color: rgba(0, 0, 0, 0.50) !important;
        opacity: 0.50 !important; transform: rotate(-35deg); z-index: 9999; pointer-events: none;
    }}
    .print-header-box {{ border: 2px solid #000; padding: 14px 18px; border-radius: 8px; margin-bottom: 18px; text-align: center; }}
    .print-q-box {{ margin-bottom: 15px !important; padding-bottom: 10px; border-bottom: 1px solid #cbd5e1; page-break-inside: avoid !important; }}
    .print-q-head {{ display: flex; justify-content: space-between; margin-bottom: 5px; font-weight: bold; }}
    .print-q-topic {{ background: #facc15 !important; color: #000 !important; padding: 2px 6px; font-size: 10px; border-radius: 12px; font-weight: 800; }}
    .print-q-text {{ font-size: 13px; margin-bottom: 6px; font-weight: 600; color: #000 !important; }}
    .print-ans-row {{ font-size: 11.5px; margin-bottom: 3px; }}
    .print-sol-box {{ background: #f8fafc !important; border-left: 4px solid #facc15 !important; padding: 8px !important; margin-top: 5px; font-size: 11.5px; color: #1e293b !important; }}
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
                <button class="start-btn" onclick="startTest()">▶|| परीक्षा शुरू करें (Start Test)</button>
            </div>
            <div style="text-align:center; font-size:11px; color:var(--text-muted); margin-top:20px;">© SACHIN SHARMA - ALL RIGHTS RESERVED.</div>
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
                <button class="r-btn-small print-btn" onclick="window.print()">🖨️ Print PDF Result (50% Watermark)</button>
            </div>
            <h3 style="font-size: 14px; margin-bottom: 12px; color: var(--primary);">📝 विस्तृत व्याख्या एवं समाधान</h3>
            <div id="review-container"></div>
        </div>
    </div>

    <script>
        const questions = {json_questions_str};
        const TOTAL_Q = questions.length;
        const MARKS_PER_CORRECT = 2.00;
        const NEGATIVE_MARK = 0.66;
        const TIME_MINUTES = 60;

        let totalSeconds = TIME_MINUTES * 60;
        let timerInterval;
        let currentQIndex = 0;
        let userAnswers = new Array(TOTAL_Q).fill(null);
        let studentName = "";

        function startTest() {{
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
        }}

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
        function nextQuestion() {{ if (currentQIndex < TOTAL_Q - 1) loadQuestion(currentQIndex + 1); else submitTest(); }}
        function prevQuestion() {{ if (currentQIndex > 0) loadQuestion(currentQIndex - 1); }}

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
                if(i === currentQIndex) {{
                    btn.classList.add('status-current');
                }} else if(userAnswers[i] !== null) {{
                    btn.classList.add('status-answered');
                }}
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

        function submitTest() {{
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

            let printHTML = '<div class="print-header-box"><h2>UPSC CSE PRELIMS MOCK TEST</h2><h3>' + (questions[0].topic || '{subj}') + '</h3><p>Candidate: ' + studentName + ' | Marking: +2.00, -0.66</p></div>';

            questions.forEach((q, idx) => {{
                const uAns = userAnswers[idx];
                let statusColor = '', statusText = '';
                if (uAns === null) {{ skipped++; statusColor = 'var(--skipped)'; statusText = 'अनुत्तरित'; }}
                else if (uAns === q.correctAnswer) {{ correct++; statusColor = 'var(--correct)'; statusText = 'सही (CORRECT)'; }}
                else {{ wrong++; statusColor = 'var(--wrong)'; statusText = 'गलत (INCORRECT)'; }}

                const uAnsText = uAns !== null ? '(' + letters[uAns] + ') ' + q.options[uAns] : 'कोई नहीं';
                const cAnsText = '(' + letters[q.correctAnswer] + ') ' + q.options[q.correctAnswer];

                reviewContainer.innerHTML += '<div class="review-box"><div class="q-header-row"><span style="color:var(--primary); font-weight:bold;">Q' + (idx + 1) + '.</span><span class="q-topic-tag">' + q.topic + '</span></div><div class="review-q">' + q.text + '</div><div class="ans-row"><div class="ans-lbl">आपका उत्तर:</div><div style="color:' + statusColor + '">' + uAnsText + '</div></div><div class="ans-row"><div class="ans-lbl">सही उत्तर:</div><div style="color:var(--correct)">' + cAnsText + '</div></div><div class="solution-box"><div class="solution-title">💡 आधिकारिक व्याख्या:</div>' + q.solution + '</div></div>';

                printHTML += '<div class="print-q-box"><div class="print-q-head"><span>Q' + (idx + 1) + '.</span><span class="print-q-topic">' + q.topic + '</span></div><div class="print-q-text">' + q.text + '</div><div class="print-ans-row"><strong>आपका उत्तर:</strong> ' + uAnsText + ' | <strong>सही:</strong> ' + cAnsText + '</div><div class="print-sol-box"><b>व्याख्या:</b> ' + q.solution + '</div></div>';
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

generate_quiz_html = build_vision_ias_interactive_portal
