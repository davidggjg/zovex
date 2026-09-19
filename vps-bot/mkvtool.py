#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mkvtool — שולחים קובץ MKV לחשבון, בוחרים רצועות בכפתורים, מקבלים בחזרה.

## מה זה עושה

  1. שולחים קובץ (‎.mkv‎ / ‎.mp4‎ / ‎.mov‎ ...) לחשבון שהכלי רץ עליו.
  2. הוא מוריד, קורא מה יש בפנים, ומציג את כל רצועות האודיו והכתוביות
     עם השפה של כל אחת.
  3. לוחצים על הרצועות הרצויות — אודיו אחד או יותר, כתוביות אחת או יותר.
  4. "בצע" מחזיר:
       • את הווידאו עם **רק** האודיו שנבחר (שאר השפות נעלמות)
       • ו/או קובץ כתוביות נפרד לכל כתובית שנבחרה

הווידאו נבנה ב-stream copy — כלומר בלי קידוד מחדש. קובץ של 8 ג'יגה נחתך
בעשרות שניות ולא בשעות, והאיכות זהה לחלוטין למקור.

## שתי מלכודות שהכלי מטפל בהן, כי הן שוברות את הדבר הזה בשקט

**כתוביות תמונה.** ב-MKV רבים הכתוביות אינן טקסט אלא **תמונות**
(‎hdmv_pgs_subtitle‎ מבלוריי, ‎dvd_subtitle‎ מ-DVD). אי אפשר להפוך אותן
ל-SRT בלי OCR — ffmpeg פשוט ייכשל, או גרוע מזה יפלוט קובץ ריק. הכלי מזהה
את זה מראש, מוציא אותן בפורמט המקורי (‎.sup‎ / ‎.sub‎), ואומר במפורש שהן
תמונה ולמה אין מהן טקסט.

**הזרמה חיה על אותו שרת.** ffmpeg על קובץ גדול יכול לגזול CPU מהשירות
שמגיש סרטים לצופים. לכן הוא רץ תחת ‎nice‎, ומוגבל למשימה אחת בכל רגע.

## ומה הכלי מסרב לעשות

הוא **לא ישתמש ב-session שבריכת ההזרמה מחזיקה**. אותו session בשני
לקוחות במקביל הוא שגיאה מוכרת של טלגרם (AUTH_KEY_DUPLICATED), והתוצאה
היא נפילת החשבון מהבריכה — כלומר הכלי הזה היה מוריד סרטים לצופים כדי
לחתוך קובץ. הוא בודק את זה בהפעלה ונעצר עם הסבר.

## התקדמות, הרשאות, ומחיקה אוטומטית

**התקדמות.** הורדה והעלאה מציגות אחוז, מהירות בפועל וזמן משוער, ומתעדכנות
כל כמה שניות. העריכות מווסתות בכוונה: טלגרם מגביל קצב עריכות, וכלי
שמעדכן על כל נתח חוטף FloodWait ומפסיק לדווח בדיוק כשהקובץ גדול.

**הרשאות.** הבעלים יכול לפתוח את הכלי לאנשים נוספים:

    /allow 123456789      — מוסיף
    /deny  123456789      — מסיר
    /allowed              — מי מורשה

הרשימה נשמרת לקובץ ושורדת הפעלה מחדש. הבעלים תמיד מורשה ולא ניתן להסרה,
כדי שלא ייווצר מצב שבו אין לאיש גישה.

**מחיקה מהשרת.** הקבצים נמחקים מהשרת שעה אחרי הטיפול, וזה נאמר למשתמש
בהודעה. המחיקה היא **רק מהשרת** — מה שכבר נשלח בטלגרם נשאר בטלגרם. מטאטא
רץ ברקע כל חמש דקות, ולא רק כשמגיע קובץ חדש: אחרת קובץ אחרון שנשלח בערב
היה יושב על הדיסק עד הקובץ הבא.

## הפעלה

צריך בקובץ הסביבה (‎/opt/zovex-bot/.env‎):

    API_ID, API_HASH          — כבר קיימים שם
    MKVTOOL_OWNER=<user id>   — מי מורשה להשתמש. חובה.
    MKVTOOL_SESSION=mkvtool   — שם session נפרד (ברירת מחדל)
    MKVTOOL_RETENTION=3600    — שניות עד מחיקה מהשרת (ברירת מחדל: שעה)

בהרצה ראשונה הוא יבקש התחברות (טלפון + קוד) ויישמר ל-session משלו.

    python3 mkvtool.py
"""
import asyncio, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

try:
    from pyrogram import Client, filters, idle
    from pyrogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                                Message, CallbackQuery)
except ImportError:
    sys.exit("צריך pyrogram:  pip install pyrogram tgcrypto")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
WORK_DIR = Path(os.environ.get("MKVTOOL_WORK", "/opt/zovex-bot/mkvwork"))
SESSION = os.environ.get("MKVTOOL_SESSION", "mkvtool")
STREAM_BOTS_FILE = Path(os.environ.get("STREAM_BOTS_FILE",
                                       str(DATA_DIR / "stream_bots.txt")))

# כמה מקום פנוי צריך: הקובץ המקורי + הפלט + מרווח. בלי הבדיקה הזאת הורדה
# של קובץ גדול ממלאת את הדיסק ומפילה גם את שירות ההזרמה.
FREE_SPACE_FACTOR = 2.5
MAX_UPLOAD = int(os.environ.get("MKVTOOL_MAX_UPLOAD", str(2000 * 1024 * 1024)))

RETENTION = int(os.environ.get("MKVTOOL_RETENTION", "3600"))
ALLOW_FILE = DATA_DIR / "mkvtool_allowed.json"
# כל כמה שניות מותר לערוך הודעת התקדמות. טלגרם מגביל קצב עריכות, וכלי
# שמעדכן על כל נתח חוטף FloodWait ומפסיק לדווח בדיוק כשהקובץ גדול.
EDIT_EVERY = float(os.environ.get("MKVTOOL_EDIT_EVERY", "4"))

# כתוביות שהן תמונה ולא טקסט. אי אפשר להמיר אותן ל-SRT בלי OCR.
BITMAP_SUBS = {"hdmv_pgs_subtitle": "sup", "dvd_subtitle": "sub",
               "dvb_subtitle": "sub", "xsub": "sub"}
# כתוביות טקסט: הסיומת שבה נוציא אותן. ass/ssa נשמרות כמו שהן כדי לא לאבד
# עיצוב; srt ודומיו יוצאים כ-srt.
TEXT_SUBS = {"subrip": "srt", "srt": "srt", "ass": "ass", "ssa": "ass",
             "mov_text": "srt", "webvtt": "vtt", "text": "srt"}

LANG_HE = {
    "eng": "אנגלית", "en": "אנגלית", "heb": "עברית", "he": "עברית",
    "iw": "עברית", "ara": "ערבית", "ar": "ערבית", "rus": "רוסית",
    "ru": "רוסית", "fre": "צרפתית", "fra": "צרפתית", "fr": "צרפתית",
    "spa": "ספרדית", "es": "ספרדית", "ger": "גרמנית", "deu": "גרמנית",
    "de": "גרמנית", "ita": "איטלקית", "it": "איטלקית", "jpn": "יפנית",
    "ja": "יפנית", "kor": "קוריאנית", "ko": "קוריאנית", "chi": "סינית",
    "zho": "סינית", "zh": "סינית", "por": "פורטוגזית", "pt": "פורטוגזית",
    "tur": "טורקית", "tr": "טורקית", "hin": "הינדי", "hi": "הינדי",
    "tam": "טמילית", "ta": "טמילית", "tel": "טלוגו", "mal": "מלאיאלאם",
    "kan": "קאנאדה", "ben": "בנגלית", "mar": "מראטהי", "pan": "פנג'אבי",
    "urd": "אורדו", "fas": "פרסית", "per": "פרסית", "tha": "תאית",
    "vie": "וייטנאמית", "ind": "אינדונזית", "may": "מלאית", "msa": "מלאית",
    "pol": "פולנית", "nld": "הולנדית", "dut": "הולנדית", "swe": "שוודית",
    "nor": "נורווגית", "dan": "דנית", "fin": "פינית", "ces": "צ'כית",
    "cze": "צ'כית", "slk": "סלובקית", "hun": "הונגרית", "ron": "רומנית",
    "rum": "רומנית", "bul": "בולגרית", "ell": "יוונית", "gre": "יוונית",
    "ukr": "אוקראינית", "srp": "סרבית", "hrv": "קרואטית", "slv": "סלובנית",
    "lit": "ליטאית", "lav": "לטבית", "est": "אסטונית", "und": "לא מצוין",
    "mul": "רב-לשוני", "zxx": "בלי דיבור",
}


# טלגרם ואנדרואיד מוסיפים סימני כיווניות נסתרים סביב טקסט מעורב
# עברית-מספרים. "1 וידאו" הגיע לקוד כ-"1", "\u200fוידאו" — והמילה השנייה
# לא התאימה לשום פקודה, ולכן ההודעה נראתה כאילו התעלמו ממנה.
INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def strip_invisible(t):
    return INVISIBLE.sub("", t or "")


def lang_name(code):
    c = (code or "und").lower()
    return LANG_HE.get(c, c)


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}"
        n /= 1024


# ── התקדמות ──────────────────────────────────────────────────────────────────
def make_prog(msg, label, total):
    """מחזיר callback להורדה/העלאה: אחוז, מהירות בפועל וזמן משוער.

    **חייב להיות פונקציה ולא אובייקט.** pyrogram בודק
    inspect.iscoroutinefunction(progress), ועבור מופע של מחלקה עם
    ‎async def __call__‎ הבדיקה מחזירה False — ואז הוא מריץ אותו כפונקציה
    רגילה, מקבל קורוטינה שאיש לא ממתין לה, וזורק אותה בשקט. כך נבנתה
    הגרסה הראשונה, ולכן לא הוצג שום פס.

    העריכות מווסתות: טלגרם מגביל קצב עריכות, וכלי שמעדכן על כל נתח חוטף
    FloodWait ומפסיק לדווח בדיוק כשהקובץ גדול.
    """
    state = {"t0": time.time(), "last": 0.0}

    async def cb(current, total_in):
        tot = total_in or total or 0
        now = time.time()
        if tot and current < tot and now - state["last"] < EDIT_EVERY:
            return
        state["last"] = now
        el = max(0.001, now - state["t0"])
        speed = current / el
        pct = (current * 100.0 / tot) if tot else 0
        filled = int(pct / 5)
        bar = "█" * filled + "░" * (20 - filled)
        eta = "—"
        if speed > 0 and tot and current < tot:
            left = int((tot - current) / speed)
            eta = f"{left // 60}:{left % 60:02d}"
        try:
            await msg.edit(
                f"{label}\n\n`{bar}`  **{pct:.0f}%**\n"
                f"{human(current)} מתוך {human(tot)}\n"
                f"מהירות {human(speed)}/ש · נותרו {eta}")
        except Exception:
            pass          # FloodWait/עריכה זהה — דיווח הוא נוחות, לא תלות

    return cb


# ── מי מורשה ─────────────────────────────────────────────────────────────────
ALLOWED: set = set()


def load_allowed():
    try:
        ALLOWED.update(int(x) for x in json.loads(ALLOW_FILE.read_text()))
    except Exception:
        pass


def save_allowed():
    try:
        ALLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALLOW_FILE.write_text(json.dumps(sorted(ALLOWED)), encoding="utf-8")
    except Exception as e:
        print(f"אזהרה: לא נשמרה רשימת ההרשאות: {e}")


# ── בדיקות הפעלה ─────────────────────────────────────────────────────────────
def guard_session_collision():
    """מסרב לרוץ על session שבריכת ההזרמה מחזיקה.

    אותו session בשני לקוחות במקביל = AUTH_KEY_DUPLICATED, והחשבון נופל
    מהבריכה. כלומר הכלי הזה היה מוריד סרטים לצופים כדי לחתוך קובץ.
    """
    ours = (DATA_DIR / f"{SESSION}.session").resolve()
    for name in ("stream_bot",):
        other = (DATA_DIR / f"{name}.session").resolve()
        if ours == other:
            sys.exit(f"❌ {SESSION} הוא ה-session של שירות ההזרמה.\n"
                     f"   הרצה עליו תפיל את החשבון מהבריכה.\n"
                     f"   הגדר MKVTOOL_SESSION לשם אחר.")
    # כל session שמופיע בקובץ הבריכה אסור גם הוא
    try:
        if STREAM_BOTS_FILE.exists():
            for line in STREAM_BOTS_FILE.read_text().splitlines():
                t = line.strip()
                if t and SESSION == t.split(":")[0]:
                    sys.exit(f"❌ {SESSION} מופיע בקובץ בריכת ההזרמה. "
                             f"בחר שם אחר ב-MKVTOOL_SESSION.")
    except Exception:
        pass


def need(cmd):
    if shutil.which(cmd) is None:
        sys.exit(f"❌ {cmd} לא מותקן.  apt install ffmpeg")


# ── ffprobe ──────────────────────────────────────────────────────────────────
def probe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "ffprobe נכשל").strip()[:300])
    return json.loads(r.stdout)


def describe(info: dict):
    """מחזיר (audio, subs, video) — רשימות של dict עם מה שצריך לכפתורים.

    ה-index שנשמר הוא המיקום **בתוך הסוג** (‎0:a:2‎), כי זה מה ש-ffmpeg
    מצפה לו ב-map. שימוש במספר הזרם הגלובלי כאן הוא באג נפוץ ושקט: הוא
    "עובד" על קבצים שבהם הסדר במקרה תואם, ובוחר את הרצועה הלא נכונה בכל
    השאר.
    """
    audio, subs, video = [], [], []
    ai = si = 0
    for s in info.get("streams", []):
        kind = s.get("codec_type")
        tags = s.get("tags") or {}
        lang = tags.get("language") or tags.get("LANGUAGE") or "und"
        title = tags.get("title") or tags.get("TITLE") or ""
        if kind == "audio":
            audio.append({"i": ai, "lang": lang, "codec": s.get("codec_name", ""),
                          "ch": s.get("channels"), "title": title,
                          "default": bool((s.get("disposition") or {}).get("default"))})
            ai += 1
        elif kind == "subtitle":
            codec = s.get("codec_name", "")
            subs.append({"i": si, "lang": lang, "codec": codec, "title": title,
                         "bitmap": codec in BITMAP_SUBS,
                         "ext": BITMAP_SUBS.get(codec) or TEXT_SUBS.get(codec, "srt"),
                         "forced": bool((s.get("disposition") or {}).get("forced"))})
            si += 1
        elif kind == "video" and not s.get("disposition", {}).get("attached_pic"):
            video.append({"codec": s.get("codec_name", ""),
                          "w": s.get("width"), "h": s.get("height")})
    return audio, subs, video


# ── ניקוי SRT ────────────────────────────────────────────────────────────────
# ההמרה מ-ass ל-srt גוררת איתה את תגיות העיצוב של ass, והתוצאה נראית כך:
#   <font size="20" color="#000000">{\an0}</font>Hello
# זה תקין תחבירית ומכוער לקריאה, ורוב הנגנים מציגים את הזבל כטקסט. מנקים
# את מה ששייך ל-ass ומשאירים את מה ש-srt באמת תומך בו (<i>, <b>, <u>).
ASS_OVERRIDE = re.compile(r"\{\\[^}]*\}")
FONT_TAG = re.compile(r"</?font[^>]*>", re.I)


def clean_srt(path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    out = FONT_TAG.sub("", ASS_OVERRIDE.sub("", txt))
    # שורות שנשארו ריקות אחרי הניקוי היו כולן עיצוב — מסירים כדי שלא
    # יופיעו כמסגרות ריקות על המסך.
    out = re.sub(r"\n{3,}", "\n\n", out)
    if out != txt:
        try:
            path.write_text(out, encoding="utf-8")
        except Exception:
            pass


# ── מצב לכל קובץ ─────────────────────────────────────────────────────────────
# TTL: בלי זה המילון גדל לנצח וגם משאיר קבצים על הדיסק. נלמד בדרך הקשה
# בחלקים אחרים של המערכת הזאת.
JOBS: dict = {}
JOB_TTL = RETENTION


def sweep_jobs():
    now = time.time()
    for k in [k for k, v in JOBS.items() if now - v["born"] > JOB_TTL]:
        j = JOBS.pop(k, None)
        if j:
            shutil.rmtree(j["dir"], ignore_errors=True)


def presets(job):
    """אפשרויות מוכנות, ממוספרות, עם שמות השפות בפועל.

    הגרסה הקודמת דרשה להרכיב פקודה ("1 s1 הכל") — שפה קטנה שצריך ללמוד,
    וזה בדיוק מה שלא עובד כשמישהו אחר מקבל את הכלי ליד. כאן כל שילוב
    סביר כבר כתוב במפורש, והמשתמש שולח מספר אחד.

    התפריט נבנה מהקובץ עצמו, ולכן השפות שמופיעות הן אלה שבאמת יש בו.
    """
    out = []
    for a in job["audio"]:
        out.append({"t": f"וידאו ב{lang_name(a['lang'])} בלבד",
                    "a": {a["i"]}, "s": set(), "v": True, "sb": False})
    for a in job["audio"]:
        for x in job["subs"]:
            out.append({
                "t": f"וידאו ב{lang_name(a['lang'])} + קובץ כתוביות "
                     f"{lang_name(x['lang'])}",
                "a": {a["i"]}, "s": {x["i"]}, "v": True, "sb": True})
    for x in job["subs"]:
        out.append({"t": f"רק קובץ כתוביות {lang_name(x['lang'])}",
                    "a": set(), "s": {x["i"]}, "v": False, "sb": True})
    return out[:9]


# האם אנחנו בוט אמיתי (עם טוקן) או חשבון משתמש. **חשבון משתמש אינו יכול
# לשלוח כפתורים** — זו מגבלה של טלגרם, לא באג. לכן במצב יוזר-בוט הממשק
# הוא פקודות טקסט, ורק במצב בוט מוצגים כפתורים.
IS_BOT = [False]


def keyboard(job):
    if not IS_BOT[0]:
        return None
    rows = []
    for a in job["audio"]:
        on = a["i"] in job["pick_a"]
        ch = f" · {a['ch']}ch" if a.get("ch") else ""
        extra = f" · {a['title'][:18]}" if a["title"] else ""
        rows.append([InlineKeyboardButton(
            f"{'✅' if on else '▫️'} 🔊 {lang_name(a['lang'])} ({a['codec']}{ch}){extra}",
            callback_data=f"a{job['id']}:{a['i']}")])
    for s in job["subs"]:
        on = s["i"] in job["pick_s"]
        kind = "🖼" if s["bitmap"] else "📝"
        extra = " · forced" if s["forced"] else ""
        rows.append([InlineKeyboardButton(
            f"{'✅' if on else '▫️'} {kind} {lang_name(s['lang'])} ({s['codec']}){extra}",
            callback_data=f"s{job['id']}:{s['i']}")])
    rows.append([
        InlineKeyboardButton("🎬 וידאו", callback_data=f"gv{job['id']}:0"),
        InlineKeyboardButton("📄 כתוביות", callback_data=f"gs{job['id']}:0"),
        InlineKeyboardButton("🎬+📄 שניהם", callback_data=f"gb{job['id']}:0"),
    ])
    rows.append([InlineKeyboardButton("🗑 בטל", callback_data=f"x{job['id']}:0")])
    return InlineKeyboardMarkup(rows)


def summary(job):
    v = job["video"][0] if job["video"] else None
    head = f"**{job['name']}**\n{human(job['size'])}"
    if v:
        head += f" · {v['codec']} {v.get('w')}×{v.get('h')}"

    head += "\n\n**מה יש בקובץ:**\n"
    for a in job["audio"]:
        ch = f" · {a['ch']} ערוצים" if a.get("ch") else ""
        t = f" · {a['title'][:24]}" if a["title"] else ""
        head += f"🔊 {lang_name(a['lang'])} ({a['codec']}{ch}){t}\n"
    for x in job["subs"]:
        kind = "🖼 תמונה" if x["bitmap"] else "📝 טקסט"
        head += f"{kind} · כתוביות {lang_name(x['lang'])}\n"
    if not job["subs"]:
        head += "📝 אין כתוביות בקובץ\n"

    head += "\n**מה לעשות? שלח מספר:**\n"
    for n, pr in enumerate(presets(job), 1):
        head += f"`{n}` · {pr['t']}\n"
    if any(x["bitmap"] for x in job["subs"]):
        head += ("\n🖼 כתובית תמונה (בלוריי/DVD) — תצא בפורמט המקורי. "
                 "אין ממנה טקסט בלי OCR.\n")
    head += "\n`mkv` — הקובץ המקורי בלי המרות · `בטל` — מחיקה"
    return head


# ── ffmpeg ───────────────────────────────────────────────────────────────────
FFMPEG_LOCK = asyncio.Lock()      # משימה אחת בכל רגע — לא לגזול CPU מההזרמה


async def run_ff(args, timeout=7200):
    """ffmpeg תחת nice. מחזיר (ok, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "nice", "-n", "10", "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return False, "ffmpeg חרג מהזמן"
    return proc.returncode == 0, (err or b"").decode("utf-8", "replace")[-600:]


async def build_video(job, container="mp4") -> tuple:
    """וידאו + רק האודיו שנבחר.

    ## למה mp4 ולמה לא סתם copy

    כדי שטלגרם ינגן את הקובץ בלחיצה ולא יבקש להוריד אותו, צריך שלושה
    דברים: מיכל mp4, ‎+faststart‎ (מזיז את טבלת האינדקס לתחילת הקובץ, אחרת
    הנגן חייב את כל הקובץ לפני שהוא מתחיל), ושליחה כווידאו ולא כמסמך.

    הווידאו עצמו **מועתק** ולא מקודד מחדש — זה מה שמשאיר את זה בשניות
    במקום שעות, ובאיכות זהה. האודיו הוא הסיפור: AC3 ו-DTS חוקיים ב-mp4
    אבל רוב הנגנים, כולל של טלגרם, לא מנגנים אותם. לכן אודיו שאינו
    AAC מומר ל-AAC — קידוד זול שלוקח שניות — וזה בדיוק ההבדל בין קובץ
    שנפתח לקובץ ששותק.

    ‎-tag:v hvc1‎ נדרש ל-HEVC בתוך mp4: בלי התג אפל ו-QuickTime לא מזהים
    את הזרם, והקובץ "תקין" בכל בדיקה ופשוט לא נפתח אצל חצי מהמשתמשים.

    container="mkv" משאיר הכל בהעתקה מלאה, בלי המרת אודיו ובלי הגבלות
    מיכל — לשמירה ארכיונית ולא לצפייה ישירה.
    """
    ext = "mkv" if container == "mkv" else "mp4"
    out = job["dir"] / f"{Path(job['name']).stem}.{ext}"
    args = ["-i", str(job["src"]), "-map", "0:v:0"]
    for i in sorted(job["pick_a"]):
        args += ["-map", f"0:a:{i}"]
    for i in sorted(job["pick_s"]):
        args += ["-map", f"0:s:{i}"]

    if ext == "mkv":
        args += ["-c", "copy"]
    else:
        args += ["-c:v", "copy"]
        vcodec = (job["video"][0]["codec"] if job["video"] else "").lower()
        if vcodec in ("hevc", "h265"):
            args += ["-tag:v", "hvc1"]
        # אודיו: מעתיקים רק AAC, כל השאר מומר. הבדיקה היא על הרצועות
        # שנבחרו בפועל ולא על הקובץ כולו.
        picked = [a for a in job["audio"] if a["i"] in job["pick_a"]]
        if all((a["codec"] or "").lower() == "aac" for a in picked):
            args += ["-c:a", "copy"]
        else:
            args += ["-c:a", "aac", "-b:a", "192k"]
        # mp4 לא מחזיק ass/subrip; mov_text הוא מה שיש בו.
        if job["pick_s"]:
            args += ["-c:s", "mov_text"]
        args += ["-movflags", "+faststart"]
    args += [str(out)]

    ok, err = await run_ff(args)
    if not ok and ext == "mp4" and job["pick_s"]:
        # כתובית תמונה אינה ניתנת להטמעה ב-mp4. מנסים שוב בלעדיה — הקובץ
        # הנפרד ממילא נשלח, אז אין כאן אובדן אמיתי.
        args2 = [a for a in args]
        for i in sorted(job["pick_s"]):
            while f"0:s:{i}" in args2:
                k = args2.index(f"0:s:{i}")
                del args2[k - 1:k + 1]
        if "-c:s" in args2:
            k = args2.index("-c:s")
            del args2[k:k + 2]
        ok, err = await run_ff(args2)
    return (out if ok else None), err


async def build_subs(job) -> tuple:
    """כל כתובית שנבחרה לקובץ נפרד. מחזיר (קבצים, הערות)."""
    files, notes = [], []
    for s in job["subs"]:
        if s["i"] not in job["pick_s"]:
            continue
        stem = f"{Path(job['name']).stem}.{s['lang']}"
        if s["forced"]:
            stem += ".forced"
        out = job["dir"] / f"{stem}.{s['ext']}"
        if s["bitmap"]:
            # תמונה: מוציאים כמו שהיא. המרה ל-srt כאן פשוט נכשלת, ובלי
            # ההפרדה הזאת המשתמש מקבל קובץ ריק בלי שום הסבר.
            #
            # איזה מיכל מתאים תלוי בקודק, ולא היה לי דגימה אמיתית לבדוק
            # עליה. לכן לא מנחשים: מנסים את המיכל המועדף, ואם ffmpeg מסרב
            # נופלים ל-.mks (מטרוסקה־כתוביות) שמקבל כל קודק. הנפילה
            # מדווחת, כך שלא נשארים עם קובץ שבור בלי לדעת.
            cands = [(s["ext"], "copy"), ("mks", "copy")]
        else:
            # SRT תמיד קודם, גם עבור ass/ssa. זה מה שמבוקש ומה שכל נגן
            # קורא; המחיר הוא עיצוב ומיקום שאובדים בהמרה, ולכן אם ההמרה
            # נכשלת נופלים לפורמט המקורי במקום להחזיר כלום.
            cands = [("srt", "srt"), (s["ext"], "copy"), ("ass", "copy")]

        ok = False
        for ext, codec in cands:
            out = job["dir"] / f"{stem}.{ext}"
            ok, err = await run_ff(
                ["-i", str(job["src"]), "-map", f"0:s:{s['i']}",
                 "-c:s", codec, str(out)], timeout=1800)
            if ok and out.exists() and out.stat().st_size > 0:
                break
            ok = False
            out.unlink(missing_ok=True)

        if ok:
            if out.suffix.lower() == ".srt":
                clean_srt(out)
            files.append(out)
            if s["bitmap"]:
                notes.append(f"🖼 {lang_name(s['lang'])} — כתובית **תמונה**, "
                             f"יצאה כ-{out.suffix.lstrip('.')}. "
                             f"אין ממנה טקסט בלי OCR (למשל Subtitle Edit).")
        else:
            notes.append(f"⚠️ {lang_name(s['lang'])} ({s['codec']}) — לא הצלחתי "
                         f"לחלץ באף פורמט"
                         + (f": {err.splitlines()[-1][:120]}" if err else ""))
    return files, notes


# ── הלקוח ────────────────────────────────────────────────────────────────────
def main():
    need("ffmpeg")
    need("ffprobe")
    guard_session_collision()
    owner = os.environ.get("MKVTOOL_OWNER", "").strip()
    if not owner.isdigit():
        sys.exit("❌ חסר MKVTOOL_OWNER (מזהה המשתמש המורשה).\n"
                 "   בלעדיו כל אחד שישלח קובץ יפעיל עיבוד על השרת שלך.")
    owner_id = int(owner)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    load_allowed()

    # מהירות. שני דברים משפיעים בפועל:
    #
    # 1. tgcrypto — בלעדיו ההצפנה של MTProto רצה בפייתון טהור, וזה חונק
    #    כל העברה גדולה. זו הבדיקה הראשונה ששווה לעשות כשמשהו איטי.
    # 2. max_concurrent_transmissions — כמה העברות במקביל. ברירת המחדל
    #    של pyrogram היא 1, כלומר גם שתי בקשות מאותו משתמש מחכות בתור.
    try:
        import tgcrypto           # noqa: F401
    except ImportError:
        print("⚠️  tgcrypto לא מותקן — ההצפנה רצה בפייתון טהור וזה איטי.")
        print("    pip install tgcrypto   (מאיץ הורדות והעלאות משמעותית)")

    conns = int(os.environ.get("MKVTOOL_CONNS", "8"))
    try:
        app = Client(SESSION, api_id=int(os.environ["API_ID"]),
                     api_hash=os.environ["API_HASH"], workdir=str(DATA_DIR),
                     max_concurrent_transmissions=conns)
    except TypeError:
        # גרסת pyrogram ישנה שאינה מכירה את הפרמטר. לא נכשלים בגללו.
        print("(גרסת pyrogram לא תומכת ב-max_concurrent_transmissions)")
        app = Client(SESSION, api_id=int(os.environ["API_ID"]),
                     api_hash=os.environ["API_HASH"], workdir=str(DATA_DIR))

    def allowed():
        """מסנן דינמי. filters.user() נקבע פעם אחת בטעינה, ולכן לא היה
        מתעדכן כשמוסיפים מישהו ב-/allow."""
        async def f(_, __, m):
            u = m.from_user.id if m.from_user else None
            return u is not None and (u == owner_id or u in ALLOWED)
        return filters.create(f)

    # הודעה אחרונה של כל צ'אט, כדי שאפשר יהיה לענות בלי לצטט
    LAST_JOB: dict = {}


    async def do_run(client, job, want_v, want_s, container="mp4"):
        """ההרצה עצמה. משותפת לכפתורים (מצב בוט) ולפקודות טקסט (יוזר-בוט),
        כדי שלא יהיו שתי גרסאות שנסחפות זו מזו."""
        note = await client.send_message(job["chat"], "⏳ ממתין לתור של ffmpeg...")
        sent_any = False
        async with FFMPEG_LOCK:
            try:
                if want_s:
                    await note.edit("📄 מחלץ כתוביות...")
                    files, notes = await build_subs(job)
                    for f in files:
                        await client.send_document(job["chat"], str(f))
                        sent_any = True
                    if notes:
                        await client.send_message(job["chat"], "\n".join(notes))
                if want_v:
                    await note.edit("🎬 בונה וידאו (stream copy, בלי קידוד מחדש)...")
                    out, err = await build_video(job, container)
                    if out is None:
                        await note.edit(f"❌ בניית הווידאו נכשלה:\n`{err[-300:]}`")
                        return
                    sz = out.stat().st_size
                    if sz > MAX_UPLOAD:
                        await note.edit(
                            f"⚠️ הפלט {human(sz)} — מעל מגבלת ההעלאה "
                            f"({human(MAX_UPLOAD)}).\nהקובץ נשאר בשרת:\n`{out}`")
                        return
                    await note.edit(f"⬆️ מעלה ({human(sz)})...")
                    up = make_prog(note, "⬆️ מעלה", sz)
                    if out.suffix.lower() == ".mp4":
                        # send_video ולא send_document: מסמך מוצג ככרטיס
                        # להורדה גם כשהקובץ מושלם. רק כווידאו טלגרם מנגן
                        # אותו בלחיצה, וזה מה שביקשת ב"צפייה ישירה".
                        v = job["video"][0] if job["video"] else {}
                        await client.send_video(
                            job["chat"], str(out), file_name=out.name,
                            duration=job.get("duration") or 0,
                            width=v.get("w") or 0, height=v.get("h") or 0,
                            supports_streaming=True, progress=up)
                    else:
                        await client.send_document(job["chat"], str(out),
                                                   file_name=out.name, progress=up)
                    sent_any = True
                job["born"] = time.time()
                mins = max(1, RETENTION // 60)
                await note.edit("✅ סיימתי." + (
                    f"\n\n🗑 הקבצים יימחקו **מהשרת** בעוד {mins} דקות. "
                    f"מה שכבר נשלח כאן נשאר בטלגרם." if sent_any else ""))
            except Exception as e:
                await note.edit(f"❌ שגיאה: {type(e).__name__}: {e}")

    @app.on_message(allowed() & (filters.document | filters.video))
    async def on_file(client: Client, m: Message):
        sweep_jobs()
        media = m.document or m.video
        name = getattr(media, "file_name", None) or f"file_{m.id}.mkv"
        size = getattr(media, "file_size", 0) or 0

        free = shutil.disk_usage(WORK_DIR).free
        if free < size * FREE_SPACE_FACTOR:
            await m.reply(f"❌ אין מספיק מקום. צריך ~{human(size * FREE_SPACE_FACTOR)}, "
                          f"פנוי {human(free)}.")
            return

        status = await m.reply(f"⬇️ מוריד **{name}** ({human(size)})...")
        prog = make_prog(status, f"⬇️ מוריד **{name}**", size)
        jid = str(m.id)
        jdir = WORK_DIR / jid
        jdir.mkdir(parents=True, exist_ok=True)
        try:
            src = await client.download_media(m, file_name=str(jdir / name),
                                              progress=prog)
        except Exception as e:
            shutil.rmtree(jdir, ignore_errors=True)
            await status.edit(f"❌ ההורדה נכשלה: {type(e).__name__}")
            return
        src = Path(src)

        await status.edit("🔍 קורא את הרצועות...")
        try:
            info = await asyncio.to_thread(probe, src)
        except Exception as e:
            shutil.rmtree(jdir, ignore_errors=True)
            await status.edit(f"❌ לא הצלחתי לקרוא את הקובץ: {e}")
            return
        audio, subs, video = describe(info)
        try:
            duration = int(float((info.get("format") or {}).get("duration") or 0))
        except Exception:
            duration = 0
        if not audio and not subs:
            shutil.rmtree(jdir, ignore_errors=True)
            await status.edit("❌ לא נמצאו רצועות אודיו או כתוביות בקובץ.")
            return

        job = {"id": jid, "dir": jdir, "src": src, "name": name, "size": size,
               "audio": audio, "subs": subs, "video": video,
               # ברירת מחדל: הרצועות שמסומנות default בקובץ. זה מה שנגן
               # היה בוחר, ולכן זו הבחירה שהכי סביר שהמשתמש רוצה.
               "pick_a": {a["i"] for a in audio if a["default"]} or ({0} if audio else set()),
               "pick_s": set(), "born": time.time(), "chat": m.chat.id,
               "msg_id": status.id, "duration": duration}
        JOBS[jid] = job
        LAST_JOB[m.chat.id] = jid
        await status.edit(summary(job), reply_markup=keyboard(job))

    @app.on_callback_query(allowed())
    async def on_click(client: Client, q: CallbackQuery):
        data = q.data or ""
        m = re.match(r"^(gv|gs|gb|a|s|x)(\d+):(\d+)$", data)
        if not m:
            await q.answer("לא מזוהה")
            return
        act, jid, idx = m.group(1), m.group(2), int(m.group(3))
        job = JOBS.get(jid)
        if not job:
            await q.answer("הבקשה הזאת כבר לא בתוקף — שלח את הקובץ שוב", show_alert=True)
            return

        if act == "a":
            job["pick_a"] ^= {idx}
            await q.edit_message_text(summary(job), reply_markup=keyboard(job))
            await q.answer()
            return
        if act == "s":
            job["pick_s"] ^= {idx}
            await q.edit_message_text(summary(job), reply_markup=keyboard(job))
            await q.answer()
            return
        if act == "x":
            shutil.rmtree(job["dir"], ignore_errors=True)
            JOBS.pop(jid, None)
            await q.edit_message_text("🗑 בוטל והקבצים נמחקו.")
            await q.answer()
            return

        want_v = act in ("gv", "gb")
        want_s = act in ("gs", "gb")
        if want_v and not job["pick_a"]:
            await q.answer("לא נבחרה אף רצועת אודיו", show_alert=True)
            return
        if want_s and not job["pick_s"]:
            await q.answer("לא נבחרה אף כתובית", show_alert=True)
            return

        await q.answer("מתחיל")
        await do_run(client, job, want_v, want_s)


    # ── ממשק טקסט ────────────────────────────────────────────────────────────
    # חשבון משתמש אינו יכול לשלוח כפתורים (מגבלת טלגרם, לא באג), ולכן במצב
    # יוזר-בוט הבחירה נעשית בהודעה. אפשר לצרף הכל בשורה אחת: "2 s1 הכל".
    WORDS_V = {"וידאו", "video", "v", "סרט"}
    WORDS_S = {"כתוביות", "subs", "s", "כתובית"}
    WORDS_B = {"הכל", "שניהם", "both", "b", "all"}
    WORDS_X = {"בטל", "ביטול", "cancel", "x"}
    WORDS_MKV = {"mkv", "מקורי", "ארכיון"}

    @app.on_message(allowed() & filters.text & ~filters.regex(r"^/"))
    async def on_text(client: Client, m: Message):
        jid = None
        if m.reply_to_message_id:
            jid = next((k for k, v in JOBS.items()
                        if v["msg_id"] == m.reply_to_message_id), None)
        if jid is None:
            jid = LAST_JOB.get(m.chat.id)
        job = JOBS.get(jid) if jid else None
        if not job:
            return                      # לא קשור לקובץ — לא מתערבים בשיחה

        want_v = want_s = cancel = False
        container = "mp4"
        chosen = None
        text = strip_invisible(m.text).strip().lower()
        for tok in re.split(r"[\s,]+", text):
            if not tok:
                continue
            if tok in WORDS_MKV:
                container = "mkv"
                want_v = True
            elif tok in WORDS_X:
                cancel = True
            elif tok in WORDS_B:
                want_v = want_s = True
            elif tok in WORDS_V:
                want_v = True
            elif tok in WORDS_S:
                want_s = True
            elif tok.isdigit():
                # מספר = אפשרות מהתפריט, לא רצועה. זה מה שהופך את זה
                # לשימושי למי שרואה את הכלי בפעם הראשונה.
                pr = presets(job)
                k = int(tok) - 1
                if 0 <= k < len(pr):
                    chosen = pr[k]

        if chosen:
            job["pick_a"] = set(chosen["a"])
            job["pick_s"] = set(chosen["s"])
            want_v, want_s = chosen["v"], chosen["sb"]

        if cancel:
            shutil.rmtree(job["dir"], ignore_errors=True)
            JOBS.pop(jid, None)
            await m.reply("🗑 בוטל והקבצים נמחקו מהשרת.")
            return
        if want_v and not job["pick_a"]:
            await m.reply("לא נבחרה אף רצועת אודיו.")
            return
        if want_s and not job["pick_s"]:
            await m.reply("לא נבחרה אף כתובית.")
            return
        if want_v or want_s:
            await do_run(client, job, want_v, want_s, container)
        else:
            await m.reply("לא הבנתי. שלח את **המספר** של מה שאתה רוצה "
                          "מהרשימה למעלה (למשל `1`).")

    # ── הרשאות ───────────────────────────────────────────────────────────────
    @app.on_message(filters.user(owner_id) & filters.command(
        ["allow", "deny", "allowed"], prefixes="/"))
    async def on_admin(client: Client, m: Message):
        parts = (m.text or "").split()
        cmd = parts[0].lstrip("/").split("@")[0]
        if cmd == "allowed":
            if not ALLOWED:
                await m.reply(f"מורשים: רק אתה ({owner_id}).")
            else:
                await m.reply("מורשים:\n" + "\n".join(
                    [f"• {owner_id} (בעלים)"] + [f"• {u}" for u in sorted(ALLOWED)]))
            return
        ids = [int(x) for x in parts[1:] if x.lstrip("-").isdigit()]
        if not ids:
            await m.reply(f"שימוש: `/{cmd} 123456789`")
            return
        for u in ids:
            if cmd == "allow":
                ALLOWED.add(u)
            else:
                # הבעלים לא ניתן להסרה — אחרת אפשר לנעול את כולם בחוץ
                if u == owner_id:
                    await m.reply("לא מסירים את הבעלים.")
                    continue
                ALLOWED.discard(u)
        save_allowed()
        await m.reply(("✅ נוסף: " if cmd == "allow" else "✅ הוסר: ")
                      + ", ".join(str(u) for u in ids))

    # כל קובץ שמגיע ממי שאינו המורשה — נרשם עם המזהה שלו.
    #
    # זו התקלה הכי סבירה בהתקנה הזאת, והיא **שקטה**: אם MKVTOOL_OWNER הוא
    # המזהה של החשבון שהכלי רץ עליו, אבל הקבצים נשלחים אליו מחשבון אישי
    # אחר, שום דבר לא יקרה ולא תהיה שום הודעה. כאן זה הופך לשורה שאומרת
    # בדיוק איזה מספר צריך להיות שם.
    @app.on_message((filters.document | filters.video) & ~allowed())
    async def on_stranger(client: Client, m: Message):
        who = m.from_user.id if m.from_user else "?"
        name = (m.from_user.first_name if m.from_user else "") or ""
        print(f"⚠️  התקבל קובץ מ-{who} ({name}) — לא ברשימת המורשים.")
        print(f"    אם זה אתה: MKVTOOL_OWNER={who}")

    async def sweeper():
        """מוחק מהשרת קבצים שפג זמנם. רץ ברקע ולא רק כשמגיע קובץ חדש —
        אחרת קובץ אחרון שנשלח בערב יושב על הדיסק עד הקובץ הבא."""
        while True:
            await asyncio.sleep(300)
            try:
                sweep_jobs()
            except Exception:
                pass

    async def runner():
        await app.start()
        me = await app.get_me()
        IS_BOT[0] = bool(getattr(me, "is_bot", False))
        asyncio.create_task(sweeper())
        print(f"✅ מחובר כ-{me.first_name or ''} "
              f"(@{me.username or '—'}) · id={me.id}")
        if me.id == owner_id:
            print("   MKVTOOL_OWNER הוא המזהה של החשבון הזה עצמו, כלומר הכלי")
            print("   יגיב רק לקבצים שהחשבון הזה שולח לעצמו (Saved Messages).")
            print("   אם תשלח מחשבון אישי אחר — שנה את MKVTOOL_OWNER למזהה שלו.")
        if not IS_BOT[0]:
            print("מצב חשבון־משתמש: אין כפתורים (מגבלת טלגרם) — הבחירה בטקסט.")
        print(f"מחיקה מהשרת: {RETENTION // 60} דקות אחרי הטיפול")
        if ALLOWED:
            print(f"מורשים נוספים: {', '.join(str(u) for u in sorted(ALLOWED))}")
        print("מוכן. שלח קובץ.")
        await idle()
        await app.stop()

    print(f"mkvtool · session={SESSION} · owner={owner_id}")
    print(f"תיקיית עבודה: {WORK_DIR}")
    app.run(runner())


if __name__ == "__main__":
    main()
