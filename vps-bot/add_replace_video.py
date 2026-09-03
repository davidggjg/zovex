#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף לשרת מסלול אחד: החלפת הקובץ של פריט קיים בקטלוג, בלי לגעת בשאר הכניסה.

למה זה נדרש: 16 פרקי ונסדיי הועלו עם פס קול `ec-3` (Dolby Digital Plus 5.1).
שום דפדפן אינו מפענח ec-3, ולכן הוא זורק את רצועת הקול **בשקט** — וידאו מתנגן,
אין סאונד, אין שגיאה. התיקון הוא להמיר את האודיו ל-AAC ולהעלות מחדש. ההמרה
עצמה נעשית ב-`fix_audio_track.py`; מה שחסר הוא הדרך להחליף את הקובץ בטלגרם
ולעדכן את `content.json` — וזה מה שהמסלול הזה עושה.

למה מסלול בשרת ולא סקריפט עצמאי: העלאה ל-ערוץ דורשת קליינט Pyrogram מחובר.
פתיחת קליינט שני על אותו קובץ session מתנגשת עם הבוט שרץ. המסלול הזה משתמש
בקליינט שכבר מחובר, ולכן אין התנגשות ואין צורך ב-session נוסף.

**הפאץ' רק מוסיף בסוף הקובץ.** אינו נוגע באף שורה קיימת, ולכן אין עוגנים שיכולים
לא להתאים — הבעיה שהפילה תיקונים קודמים כאן.

    python3 add_replace_video.py --check
    python3 add_replace_video.py
    python3 add_replace_video.py --undo
"""
import datetime, glob, os, pathlib, py_compile, re, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "panel_replace_video"

# שמות שהתוספת מסתמכת עליהם. אם אחד מהם חסר — הקובץ בשרת אינו מה שציפינו,
# ואז לא נוגעים בכלום. עדיף להיכשל בבירור מאשר להוסיף קוד שיפיל את השירות.
NEEDED = ["api = FastAPI", "def check_panel_password", "def load_content",
          "def save_content", "bot_client", "log = logging.getLogger",
          "from pydantic import BaseModel", "from pathlib import Path",
          "from datetime import datetime", "STREAM_CHANNEL_ID"]

BLOCK = r'''

# ── החלפת הקובץ של פריט קיים ────────────────────────────────────────────────
# נועד לתיקון קבצים שהועלו עם פס קול שדפדפן אינו מפענח (ec-3/ac-3/DTS). ההמרה
# נעשית מחוץ לתהליך, וכאן רק ההעלאה מחדש ועדכון הקטלוג — כי להעלאה נדרש קליינט
# מחובר, ופתיחת קליינט שני על אותו session מתנגשת עם הבוט הרץ.
#
# הקובץ החדש חייב לשבת בתיקייה מוגדרת אחת. אחרת מסלול מוגן-סיסמה היה הופך
# לקריאה של כל קובץ בשרת.
AUDIOFIX_DIR = Path(os.environ.get("AUDIOFIX_DIR", "/opt/zovex-bot/audiofix"))


def _rv_probe(path: str) -> dict:
    """אורך/רוחב/גובה מהקובץ עצמו. בלעדיהם טלגרם מציג 0:00 ותצוגה שבורה."""
    import subprocess
    import shutil as _sh
    out = {"duration": 0, "width": 0, "height": 0}
    exe = _sh.which("ffprobe")
    if not exe:
        log.warning("replace-video: ffprobe אינו מותקן — טלגרם יציג 0:00")
        return out
    try:
        r = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of",
             "default=nw=1:nk=0", path],
            capture_output=True, text=True, timeout=90).stdout
        for line in r.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            try:
                if k == "width":
                    out["width"] = int(float(v))
                elif k == "height":
                    out["height"] = int(float(v))
                elif k == "duration":
                    out["duration"] = int(float(v))
            except ValueError:
                pass
        # סרטון מסובב: טלגרם מצפה למידות התצוגה
        rot = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream_side_data=rotation:stream_tags=rotate", "-of",
             "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60).stdout
        nums = [abs(int(float(x))) % 360 for x in rot.split() if x.strip("-").replace(".", "").isdigit()]
        if any(n in (90, 270) for n in nums):
            out["width"], out["height"] = out["height"], out["width"]
    except Exception as e:
        log.warning("replace-video: ffprobe נכשל על %s: %s", path, e)
    return out


def _rv_thumb(path: str, at: int) -> str:
    """תמונה ממוזערת. בלעדיה טלגרם מציג מלבן שחור."""
    import subprocess
    import shutil as _sh
    exe = _sh.which("ffmpeg")
    if not exe:
        return ""
    dst = str(Path(path).with_suffix(".thumb.jpg"))
    try:
        subprocess.run(
            [exe, "-nostdin", "-y", "-ss", str(max(1, at)), "-i", path,
             "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", dst],
            capture_output=True, timeout=120)
        return dst if os.path.exists(dst) and os.path.getsize(dst) > 0 else ""
    except Exception:
        return ""


def _rv_swap_msg_id(url: str, old_id, new_id: int) -> str:
    """מחליף את מזהה ההודעה בקישור, ומשאיר את שאר המבנה בדיוק כמו שהוא.
    בונים מחדש רק את החלק שאחרי /stream/<chat>/ כדי לא להסתמך על צורת הבסיס
    (יש כניסות עם טוקן בסיס ולא עם דומיין מלא)."""
    if not isinstance(url, str):
        return url
    m = re.search(r"(/stream/-?\d+/)(\d+)", url)
    if m:
        return url[:m.start(2)] + str(new_id) + url[m.end(2):]
    if old_id is not None and str(old_id) in url:
        return url.replace(str(old_id), str(new_id), 1)
    return url


class ReplaceVideoReq(BaseModel):
    password: str
    item_id: str
    path: str
    caption: str = ""
    delete_old: bool = False


@api.post("/panel/replace-video")
async def panel_replace_video(req: ReplaceVideoReq, request: Request):
    check_panel_password(request, req.password)

    p = Path(req.path).resolve()
    root = AUDIOFIX_DIR.resolve()
    if root not in p.parents:
        raise HTTPException(400, f"הקובץ חייב לשבת תחת {root}")
    if not p.exists() or p.stat().st_size < 1000:
        raise HTTPException(400, "הקובץ אינו קיים או ריק")

    arr = load_content()
    idx = next((i for i, e in enumerate(arr)
                if str(e.get("id")) == str(req.item_id)), None)
    if idx is None:
        raise HTTPException(404, "הפריט לא נמצא בקטלוג")
    item = arr[idx]

    chat = item.get("channel_id") or STREAM_CHANNEL_ID
    if not chat:
        raise HTTPException(400, "לפריט אין channel_id ואין ערוץ ברירת מחדל")
    old_msg = item.get("channel_msg_id")

    meta = _rv_probe(str(p))
    thumb = _rv_thumb(str(p), max(1, (meta["duration"] or 60) // 10))
    cap = req.caption or (f"{item.get('series_name') or item.get('title')} "
                          f"S{item.get('season_number')}E{item.get('episode_number')}"
                          if item.get("series_name") else str(item.get("title") or ""))

    if bot_client is None:
        raise HTTPException(503, "הבוט אינו מחובר")
    try:
        msg = await bot_client.send_video(
            chat, str(p), caption=cap[:1000],
            duration=meta["duration"] or None,
            width=meta["width"] or None, height=meta["height"] or None,
            thumb=thumb or None, supports_streaming=True)
    except Exception as e:
        log.warning("replace-video: העלאה נכשלה: %s", e)
        raise HTTPException(502, f"העלאה לטלגרם נכשלה: {e}")
    finally:
        if thumb:
            try:
                os.unlink(thumb)
            except OSError:
                pass

    vid = getattr(msg, "video", None) or getattr(msg, "document", None)
    new_item = dict(item)
    new_item["channel_msg_id"] = msg.id
    new_item["channel_id"] = chat
    new_item["video_url"] = _rv_swap_msg_id(item.get("video_url", ""),
                                            old_msg, msg.id)
    if vid is not None and getattr(vid, "file_unique_id", None):
        new_item["file_unique_id"] = vid.file_unique_id
    new_item["audio_fixed_at"] = datetime.utcnow().isoformat()

    arr[idx] = new_item
    save_content(arr)     # save_content מגבה את content.json לפני הדריסה

    deleted = False
    if req.delete_old and old_msg:
        try:
            await bot_client.delete_messages(chat, int(old_msg))
            deleted = True
        except Exception as e:
            log.warning("replace-video: מחיקת ההודעה הישנה נכשלה: %s", e)

    log.info("replace-video: %s  %s → %s%s", req.item_id, old_msg, msg.id,
             "  (הישנה נמחקה)" if deleted else "")
    return {"ok": True, "item_id": req.item_id, "old_msg_id": old_msg,
            "new_msg_id": msg.id, "video_url": new_item["video_url"],
            "duration": meta["duration"], "width": meta["width"],
            "height": meta["height"], "old_deleted": deleted}
'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if DONE_MARK in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return

    missing = [n for n in NEEDED if n not in src]
    if missing:
        _fail("חסרים בקובץ שבשרת: " + ", ".join(missing))

    out = src.rstrip("\n") + "\n" + BLOCK

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out)
        tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-replacevideo-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    d = pathlib.Path(os.environ.get("AUDIOFIX_DIR", "/opt/zovex-bot/audiofix"))
    d.mkdir(parents=True, exist_ok=True)
    print("✅ הוחל. נוסף מסלול /panel/replace-video (לא שונתה אף שורה קיימת).")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print(f"   תיקיית עבודה: {d}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 add_replace_video.py --undo")


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-replacevideo-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
