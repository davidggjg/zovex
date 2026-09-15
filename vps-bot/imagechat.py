#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
imagechat.py — אתר צ'אט ליצירת תמונות מול Cloudflare Workers AI.

למה שירות נפרד ולא בתוך main.py:
main.py כבר 7,855 שורות עם קוד אחרי uvicorn.run(). הוספת עוד מערכת לשם
הייתה מגדילה בדיוק את הבעיה שהדוחות החיצוניים הצביעו עליה. זה תהליך
עצמאי על פורט משלו — אם הוא ייפול או ייתקע, הסטרימינג לא מרגיש כלום.

בלי תלויות: ספריית התקן של פייתון בלבד. אין pip install, אין סיכון
לשבור את הסביבה של zovex-bot.

הרצה:
    export CF_ACCOUNT=...            # מזהה החשבון ב-Cloudflare
    export CF_TOKEN=...              # הטוקן. לעולם לא בקוד ולא בגיט.
    export IMG_PASS=...              # סיסמה לכניסה לאתר
    python3 imagechat.py             # פורט 8090

    nohup python3 imagechat.py > /tmp/imagechat.log 2>&1 &

הפורט פתוח לאינטרנט, ולכן יש סיסמה: בלעדיה כל מי שימצא את הכתובת
יוכל לשרוף את המכסה שלך ב-Cloudflare.
"""
import base64, hashlib, hmac, json, os, re, secrets, threading, time, urllib.error, urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ACCOUNT = os.environ.get("CF_ACCOUNT", "").strip()
TOKEN = os.environ.get("CF_TOKEN", "").strip()
PASSWORD = os.environ.get("IMG_PASS", "").strip()
PORT = int(os.environ.get("IMG_PORT", "8090"))
OUTDIR = Path(os.environ.get("IMG_DIR", "/var/tmp/imagechat"))
MAX_IMAGES = int(os.environ.get("IMG_KEEP", "300"))
CF_TIMEOUT = 120

# מודלים שעובדים עם JSON פשוט. flux-2 דורש multipart ולכן אינו כאן.
MODELS = [
    ("@cf/black-forest-labs/flux-1-schnell", "FLUX.1 Schnell — מהיר, ברירת מחדל"),
    ("@cf/leonardo/phoenix-1.0", "Leonardo Phoenix — איכות גבוהה"),
    ("@cf/leonardo/lucid-origin", "Leonardo Lucid Origin"),
    ("@cf/stabilityai/stable-diffusion-xl-base-1.0", "Stable Diffusion XL"),
    ("@cf/bytedance/stable-diffusion-xl-lightning", "SDXL Lightning — מהיר"),
    ("@cf/lykon/dreamshaper-8-lcm", "DreamShaper 8"),
]
MODEL_IDS = {m for m, _ in MODELS}

# המודלים דוחים שדות שהם לא מכירים — לא מתעלמים מהם. שליחת num_steps
# ל-flux מחזירה 400 ולא תמונה. נבדק אחד-אחד מול ה-API: flux מקבל רק
# prompt ו-steps, כל השאר מקבלים את כל הסט.
FULL_PARAMS = {"num_steps", "width", "height", "negative_prompt", "guidance", "seed"}
MODEL_PARAMS = {
    "@cf/black-forest-labs/flux-1-schnell": {"steps"},          # steps עד 8
}
STEP_CAP = {"@cf/black-forest-labs/flux-1-schnell": 8}

_fails = defaultdict(lambda: deque(maxlen=20))
_lock = threading.Lock()


def throttled(ip: str) -> bool:
    """חמישה כשלונות סיסמה בחמש דקות → חסימה. הפורט ציבורי."""
    with _lock:
        q = _fails[ip]
        now = time.time()
        while q and now - q[0] > 300:
            q.popleft()
        return len(q) >= 5


def note_fail(ip: str) -> None:
    with _lock:
        _fails[ip].append(time.time())


def generate(model: str, prompt: str, opts: dict):
    """מחזיר (bytes, סיומת). מזהה את הפורמט לפי Content-Type — חלק
    מהמודלים מחזירים JSON עם base64 וחלק מחזירים בייטים של תמונה."""
    allowed = MODEL_PARAMS.get(model, FULL_PARAMS | {"steps"})
    body = {"prompt": prompt}
    for k, v in opts.items():
        if k in allowed and v not in (None, "", 0):
            body[k] = v
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{model}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=CF_TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        try:
            j = json.loads(detail)
            errs = j.get("errors") or []
            if errs:
                detail = "; ".join(str(x.get("message", x)) for x in errs)
        except Exception:
            pass
        raise RuntimeError(f"Cloudflare החזיר {e.code}: {detail}")
    except Exception as e:
        raise RuntimeError(f"שגיאת רשת מול Cloudflare: {type(e).__name__}: {e}")

    if ctype.startswith("image/"):
        return raw, ctype.split("/")[-1].split(";")[0] or "png"
    try:
        j = json.loads(raw.decode("utf-8", "ignore"))
    except Exception:
        raise RuntimeError("תשובה לא מזוהה מ-Cloudflare")
    if not j.get("success", True) and j.get("errors"):
        raise RuntimeError("; ".join(str(x.get("message", x)) for x in j["errors"]))
    b64 = (j.get("result") or {}).get("image")
    if not b64:
        raise RuntimeError(f"אין תמונה בתשובה: {str(j)[:200]}")
    return base64.b64decode(b64), "jpg"


def prune() -> None:
    """שומר רק את התמונות האחרונות. בלי זה הדיסק מתמלא בשקט."""
    try:
        files = sorted(OUTDIR.glob("img_*"), key=lambda p: p.stat().st_mtime)
        for p in files[:-MAX_IMAGES]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


PAGE = """<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>ZOVEX · יצירת תמונות</title><style>
*{box-sizing:border-box}
body{margin:0;background:#0b0f17;color:#e8eefc;font:15px/1.6 system-ui,-apple-system,"Segoe UI",Arial,sans-serif;
 padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
header{padding:14px 16px;border-bottom:1px solid #1d2636;display:flex;gap:12px;align-items:center;
 position:sticky;top:env(safe-area-inset-top);background:#0b0f17;z-index:5}
h1{font-size:17px;margin:0;font-weight:700;letter-spacing:.3px}
h1 span{color:#3b9dff}
main{max-width:860px;margin:0 auto;padding:16px}
.row{display:flex;gap:10px;flex-wrap:wrap}
textarea,select,input{background:#121a27;color:#e8eefc;border:1px solid #243147;border-radius:10px;
 padding:11px 12px;font:inherit;width:100%}
textarea{min-height:88px;resize:vertical}
button{background:#3b9dff;color:#04101f;border:0;border-radius:10px;padding:12px 22px;
 font:600 15px inherit;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.opts{flex:1;min-width:140px}
label{display:block;font-size:12px;color:#8fa3c0;margin:0 2px 5px}
#feed{margin-top:22px;display:flex;flex-direction:column;gap:18px}
.card{background:#111926;border:1px solid #1d2636;border-radius:14px;overflow:hidden}
.card .p{padding:11px 14px;font-size:13px;color:#a9bcd8;border-bottom:1px solid #1d2636;
 word-break:break-word}
.card img{display:block;width:100%;height:auto;background:#0b0f17}
.card .f{padding:9px 14px;font-size:12px;color:#7286a3;display:flex;justify-content:space-between;gap:10px}
.card a{color:#3b9dff;text-decoration:none}
.err{border-color:#7a2230;background:#1a0f13}
.err .p{color:#ff9aa8;border:0}
.spin{display:inline-block;width:15px;height:15px;border:2px solid #04101f60;border-top-color:#04101f;
 border-radius:50%;animation:s .7s linear infinite;vertical-align:-3px;margin-left:7px}
@keyframes s{to{transform:rotate(360deg)}}
#gate{max-width:340px;margin:16vh auto;padding:0 16px;text-align:center}
#gate h1{margin-bottom:18px;font-size:22px}
.hint{color:#7286a3;font-size:12px;margin-top:9px}
</style></head><body>
<div id="gate" hidden>
  <h1>ZO<span>VEX</span></h1>
  <input id="pw" type="password" placeholder="סיסמה" autocomplete="current-password">
  <div class="row" style="margin-top:10px"><button id="enter" style="flex:1">כניסה</button></div>
  <div class="hint" id="gerr"></div>
</div>
<div id="app" hidden>
<header><h1>ZO<span>VEX</span> · יצירת תמונות</h1></header>
<main>
  <label for="prompt">מה ליצור</label>
  <textarea id="prompt" placeholder="תאר את התמונה. באנגלית התוצאות טובות יותר — המודלים אומנו עליה.
לדוגמה: cinematic poster of a lion in the savanna at sunset, dramatic lighting"></textarea>
  <div class="row" style="margin-top:12px">
    <div class="opts" style="flex:3;min-width:220px"><label for="model">מודל</label>
      <select id="model"></select></div>
    <div class="opts"><label for="steps">צעדים</label>
      <input id="steps" type="number" min="1" max="20" value="8"></div>
  </div>
  <div class="row" style="margin-top:12px">
    <div class="opts"><label for="w">רוחב</label><input id="w" type="number" step="64" placeholder="ברירת מחדל"></div>
    <div class="opts"><label for="h">גובה</label><input id="h" type="number" step="64" placeholder="ברירת מחדל"></div>
    <div class="opts" style="flex:2;min-width:180px"><label for="neg">מה לא לכלול</label>
      <input id="neg" placeholder="blurry, text, watermark"></div>
  </div>
  <div class="row" style="margin-top:14px"><button id="go">צור תמונה</button></div>
  <div id="feed"></div>
</main>
</div>
<script>
const $=s=>document.querySelector(s), feed=$('#feed');
let PW=localStorage.getItem('zx_pw')||'';
const MODELS=__MODELS__;
MODELS.forEach(([id,label])=>{const o=document.createElement('option');o.value=id;o.textContent=label;$('#model').appendChild(o)});

function showApp(){$('#gate').hidden=true;$('#app').hidden=false}
function showGate(m){$('#app').hidden=true;$('#gate').hidden=false;if(m)$('#gerr').textContent=m}
if(PW) showApp(); else showGate('');

$('#enter').onclick=()=>{PW=$('#pw').value;localStorage.setItem('zx_pw',PW);$('#gerr').textContent='';showApp()};
$('#pw').addEventListener('keydown',e=>{if(e.key==='Enter')$('#enter').click()});

function card(cls,html){const d=document.createElement('div');d.className='card'+(cls?' '+cls:'');
  d.innerHTML=html;feed.prepend(d);return d}

$('#go').onclick=async()=>{
  const prompt=$('#prompt').value.trim();
  if(!prompt){$('#prompt').focus();return}
  const btn=$('#go');btn.disabled=true;
  const t0=Date.now();
  const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  btn.innerHTML='יוצר<span class="spin"></span>';
  const holder=card('', '<div class="p">'+esc(prompt)+'</div><div class="f"><span>ממתין לתשובה…</span></div>');
  try{
    const r=await fetch('api/gen',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:PW,prompt,model:$('#model').value,
        steps:+$('#steps').value||null,width:+$('#w').value||null,height:+$('#h').value||null,
        negative_prompt:$('#neg').value.trim()||null})});
    const j=await r.json();
    if(r.status===401){holder.remove();showGate('סיסמה שגויה');localStorage.removeItem('zx_pw');PW='';return}
    if(!r.ok||j.error){holder.className='card err';
      holder.innerHTML='<div class="p">'+esc(prompt)+'</div><div class="p">⚠ '+esc(j.error||('שגיאה '+r.status))+'</div>';return}
    const secs=((Date.now()-t0)/1000).toFixed(1);
    holder.innerHTML='<div class="p">'+esc(prompt)+'</div><img src="'+j.url+'" alt="">'+
      '<div class="f"><span>'+esc(j.model.split("/").pop())+' · '+secs+'ש · '+Math.round(j.bytes/1024)+'KB</span>'+
      '<a href="'+j.url+'" download>הורדה</a></div>';
  }catch(e){holder.className='card err';
    holder.innerHTML='<div class="p">⚠ '+esc(String(e))+'</div>';}
  finally{btn.disabled=false;btn.textContent='צור תמונה'}
};
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    server_version = "imagechat"

    def log_message(self, fmt, *a):
        print(f"{self.address_string()} {fmt % a}", flush=True)

    def _send(self, code, ctype, body, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, obj):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            page = PAGE.replace("__MODELS__", json.dumps(MODELS, ensure_ascii=False))
            return self._send(200, "text/html; charset=utf-8", page)
        if path.startswith("/img/"):
            name = path[5:]
            # רק שם קובץ שאנחנו יצרנו. חוסם ../ ונתיבים מוחלטים.
            if not re.fullmatch(r"img_[0-9a-f]{16}\.[a-z]{3,4}", name):
                return self._send(404, "text/plain", "not found")
            f = OUTDIR / name
            if not f.exists():
                return self._send(404, "text/plain", "not found")
            ext = f.suffix.lstrip(".")
            return self._send(200, f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}",
                              f.read_bytes(), {"Cache-Control": "public, max-age=86400"})
        return self._send(404, "text/plain", "not found")

    def do_POST(self):
        if self.path.split("?")[0] != "/api/gen":
            return self._send(404, "text/plain", "not found")
        ip = self.address_string()
        if throttled(ip):
            return self._json(429, {"error": "יותר מדי נסיונות. המתן חמש דקות."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20000:
                return self._json(413, {"error": "בקשה גדולה מדי"})
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "בקשה לא תקינה"})

        if not PASSWORD or not hmac.compare_digest(str(req.get("password") or ""), PASSWORD):
            note_fail(ip)
            time.sleep(1.0)
            return self._json(401, {"error": "סיסמה שגויה"})

        prompt = (req.get("prompt") or "").strip()
        if not prompt:
            return self._json(400, {"error": "חסר תיאור"})
        if len(prompt) > 2000:
            return self._json(400, {"error": "התיאור ארוך מדי"})
        model = req.get("model") or MODELS[0][0]
        if model not in MODEL_IDS:
            return self._json(400, {"error": "מודל לא מוכר"})

        opts = {}
        if req.get("steps"):
            cap = STEP_CAP.get(model, 20)
            s = max(1, min(cap, int(req["steps"])))
            opts["steps"] = s
            opts["num_steps"] = s      # generate() ישלח רק את מה שהמודל מקבל
        for k in ("width", "height"):
            if req.get(k):
                opts[k] = max(256, min(2048, int(req[k])))
        if req.get("negative_prompt"):
            opts["negative_prompt"] = str(req["negative_prompt"])[:500]

        t0 = time.time()
        try:
            data, ext = generate(model, prompt, opts)
        except RuntimeError as e:
            self.log_message("generate failed: %s", e)
            return self._json(502, {"error": str(e)})
        except Exception as e:
            self.log_message("generate crashed: %s: %s", type(e).__name__, e)
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})

        OUTDIR.mkdir(parents=True, exist_ok=True)
        name = f"img_{secrets.token_hex(8)}.{'jpg' if ext in ('jpeg','jpg') else ext}"
        (OUTDIR / name).write_bytes(data)
        prune()
        self.log_message("ok %s %.1fs %dKB", model, time.time() - t0, len(data) // 1024)
        return self._json(200, {"url": f"img/{name}", "model": model,
                                "bytes": len(data), "seconds": round(time.time() - t0, 1)})


def main() -> None:
    missing = [n for n, v in (("CF_ACCOUNT", ACCOUNT), ("CF_TOKEN", TOKEN),
                              ("IMG_PASS", PASSWORD)) if not v]
    if missing:
        raise SystemExit(
            "חסרים משתני סביבה: " + ", ".join(missing) + "\n"
            "  export CF_ACCOUNT=...\n  export CF_TOKEN=...\n  export IMG_PASS=...")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    print(f"חשבון {ACCOUNT[:8]}… · טוקן {TOKEN[:9]}… · תמונות ב-{OUTDIR}")
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    except OSError as e:
        if e.errno == 98:
            raise SystemExit(
                f"פורט {PORT} כבר תפוס. מי מחזיק אותו:\n"
                f"   ss -lptn | grep {PORT}\n"
                f"בחר פורט אחר:  IMG_PORT=8099 python3 {Path(__file__).name}")
        raise SystemExit(f"לא ניתן להאזין על פורט {PORT}: {e}")
    print(f"מאזין על פורט {PORT}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
