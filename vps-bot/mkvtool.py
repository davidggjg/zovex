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

## הפעלה

צריך בקובץ הסביבה (‎/opt/zovex-bot/.env‎):

    API_ID, API_HASH          — כבר קיימים שם
    MKVTOOL_OWNER=<user id>   — מי מורשה להשתמש. חובה.
    MKVTOOL_SESSION=mkvtool   — שם session נפרד (ברירת מחדל)

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

# כתוביות שהן תמונה ולא טקסט. אי אפשר להמיר אותן ל-SRT בלי OCR.
BITMAP_SUBS = {"hdmv_pgs_subtitle": "sup", "dvd_subtitle": "sub",
               "dvb_subtitle": "sub", "xsub": "sub"}
# כתוביות טקסט: הסיומת שבה נוציא אותן. ass/ssa נשמרות כמו שהן כדי לא לאבד
# עיצוב; srt ודומיו יוצאים כ-srt.
TEXT_SUBS = {"subrip": "srt", "srt": "srt", "ass": "ass", "ssa": "ass",
             "mov_text": "srt", "webvtt": "vtt", "text": "srt"}

LANG_HE = {
    "eng": "אנגלית", "heb": "עברית", "ara": "ערבית", "rus": "רוסית",
    "fre": "צרפתית", "fra": "צרפתית", "spa": "ספרדית", "ger": "גרמנית",
    "deu": "גרמנית", "ita": "איטלקית", "jpn": "יפנית", "kor": "קוריאנית",
    "chi": "סינית", "zho": "סינית", "por": "פורטוגזית", "tur": "טורקית",
    "hin": "הינדי", "pol": "פולנית", "nld": "הולנדית", "dut": "הולנדית",
    "swe": "שוודית", "und": "לא מצוין",
}


def lang_name(code):
    c = (code or "und").lower()
    return LANG_HE.get(c, c)


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}"
        n /= 1024


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


# ── מצב לכל קובץ ─────────────────────────────────────────────────────────────
# TTL: בלי זה המילון גדל לנצח וגם משאיר קבצים על הדיסק. נלמד בדרך הקשה
# בחלקים אחרים של המערכת הזאת.
JOBS: dict = {}
JOB_TTL = 3600 * 3


def sweep_jobs():
    now = time.time()
    for k in [k for k, v in JOBS.items() if now - v["born"] > JOB_TTL]:
        j = JOBS.pop(k, None)
        if j:
            shutil.rmtree(j["dir"], ignore_errors=True)


def keyboard(job):
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
    head += (f"\n\n🔊 {len(job['audio'])} רצועות אודיו · "
             f"📝 {len(job['subs'])} כתוביות\n")
    if any(s["bitmap"] for s in job["subs"]):
        head += ("\n🖼 = כתובית **תמונה** (בלוריי/DVD). היא תצא בפורמט "
                 "המקורי; אין ממנה טקסט בלי OCR.\n")
    pa = ", ".join(lang_name(a["lang"]) for a in job["audio"] if a["i"] in job["pick_a"])
    ps = ", ".join(lang_name(s["lang"]) for s in job["subs"] if s["i"] in job["pick_s"])
    head += f"\nנבחר — אודיו: {pa or '(אין)'} · כתוביות: {ps or '(אין)'}"
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


async def build_video(job) -> tuple:
    """וידאו + רק האודיו שנבחר. stream copy — בלי קידוד מחדש."""
    out = job["dir"] / f"{Path(job['name']).stem}.selected.mkv"
    args = ["-i", str(job["src"]), "-map", "0:v:0"]
    for i in sorted(job["pick_a"]):
        args += ["-map", f"0:a:{i}"]
    # כתוביות שנבחרו נשארות גם בתוך הווידאו — מי שרוצה רק קובץ נפרד
    # מקבל אותו בנפרד ממילא, ומי שרוצה אותן מוטמעות מקבל.
    for i in sorted(job["pick_s"]):
        args += ["-map", f"0:s:{i}"]
    args += ["-c", "copy", str(out)]
    ok, err = await run_ff(args)
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
        elif s["ext"] == "ass":
            cands = [("ass", "copy")]
        else:
            cands = [("srt", "srt"), ("ass", "copy")]

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

    app = Client(SESSION, api_id=int(os.environ["API_ID"]),
                 api_hash=os.environ["API_HASH"], workdir=str(DATA_DIR))

    @app.on_message(filters.user(owner_id) & (filters.document | filters.video))
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
        jid = str(m.id)
        jdir = WORK_DIR / jid
        jdir.mkdir(parents=True, exist_ok=True)
        try:
            src = await client.download_media(m, file_name=str(jdir / name))
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
        if not audio and not subs:
            shutil.rmtree(jdir, ignore_errors=True)
            await status.edit("❌ לא נמצאו רצועות אודיו או כתוביות בקובץ.")
            return

        job = {"id": jid, "dir": jdir, "src": src, "name": name, "size": size,
               "audio": audio, "subs": subs, "video": video,
               # ברירת מחדל: הרצועות שמסומנות default בקובץ. זה מה שנגן
               # היה בוחר, ולכן זו הבחירה שהכי סביר שהמשתמש רוצה.
               "pick_a": {a["i"] for a in audio if a["default"]} or ({0} if audio else set()),
               "pick_s": set(), "born": time.time(), "chat": m.chat.id}
        JOBS[jid] = job
        await status.edit(summary(job), reply_markup=keyboard(job))

    @app.on_callback_query(filters.user(owner_id))
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
        note = await client.send_message(job["chat"], "⏳ ממתין לתור של ffmpeg...")
        async with FFMPEG_LOCK:
            try:
                if want_s:
                    await note.edit("📄 מחלץ כתוביות...")
                    files, notes = await build_subs(job)
                    for f in files:
                        await client.send_document(job["chat"], str(f))
                    if notes:
                        await client.send_message(job["chat"], "\n".join(notes))
                if want_v:
                    await note.edit("🎬 בונה וידאו (stream copy, בלי קידוד מחדש)...")
                    out, err = await build_video(job)
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
                    await client.send_document(job["chat"], str(out),
                                               file_name=out.name)
                await note.edit("✅ סיימתי.")
            except Exception as e:
                await note.edit(f"❌ שגיאה: {type(e).__name__}: {e}")

    # כל קובץ שמגיע ממי שאינו המורשה — נרשם עם המזהה שלו.
    #
    # זו התקלה הכי סבירה בהתקנה הזאת, והיא **שקטה**: אם MKVTOOL_OWNER הוא
    # המזהה של החשבון שהכלי רץ עליו, אבל הקבצים נשלחים אליו מחשבון אישי
    # אחר, שום דבר לא יקרה ולא תהיה שום הודעה. כאן זה הופך לשורה שאומרת
    # בדיוק איזה מספר צריך להיות שם.
    @app.on_message((filters.document | filters.video) & ~filters.user(owner_id))
    async def on_stranger(client: Client, m: Message):
        who = m.from_user.id if m.from_user else "?"
        name = (m.from_user.first_name if m.from_user else "") or ""
        print(f"⚠️  התקבל קובץ מ-{who} ({name}) — לא ברשימת המורשים.")
        print(f"    אם זה אתה: MKVTOOL_OWNER={who}")

    async def runner():
        await app.start()
        me = await app.get_me()
        print(f"✅ מחובר כ-{me.first_name or ''} "
              f"(@{me.username or '—'}) · id={me.id}")
        if me.id == owner_id:
            print("   MKVTOOL_OWNER הוא המזהה של החשבון הזה עצמו, כלומר הכלי")
            print("   יגיב רק לקבצים שהחשבון הזה שולח לעצמו (Saved Messages).")
            print("   אם תשלח מחשבון אישי אחר — שנה את MKVTOOL_OWNER למזהה שלו.")
        print("מוכן. שלח קובץ.")
        await idle()
        await app.stop()

    print(f"mkvtool · session={SESSION} · owner={owner_id}")
    print(f"תיקיית עבודה: {WORK_DIR}")
    app.run(runner())


if __name__ == "__main__":
    main()
