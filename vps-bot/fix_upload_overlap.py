#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מעלה לטלגרם *תוך כדי* הקליטה מהטלפון, במקום לחכות שהיא תסתיים.

## למה לא פשוט להאיץ את שלב ①

כי אי אפשר. המדידה שלך עצמך: הקו נושא ~14.75 מגהביט — ארבעה חיבורים לקחו
9.2 ו-Speedtest שרץ במקביל לקח את ה-5.55 הנותרים. עם שמונה חיבורים אתה
כבר על התקרה של הקו, ומחקר על העברות גדולות אומר את אותו דבר: מעבר
לשלושה-ארבעה חיבורים כמעט ואין רווח, ולפעמים יש נזק.

3.91GB על 14.75 מגהביט הם ~35 דקות. זה רצפה פיזית. שום טכניקה לא תוריד
אותה בלי קו אחר.

## מה כן אפשר

היום השלבים רצים בטור: הטלפון מסיים להעלות לשרת (35 דקות), ורק אז השרת
מתחיל להעלות לטלגרם (עוד 55). הזמן הכולל הוא הסכום.

אבל אין שום סיבה לחכות. הקובץ מוקצה מראש בגודלו הסופי וכל חלק נכתב
להיסט שלו, כך שברגע שחלק נכתב — הוא מוכן לשליחה. וטלגרם מקבל מקטעים
מחוץ לסדר. אז ברגע שחלק מגיע מהטלפון, הוא נדחף לטלגרם.

הזמן הכולל הופך מ-‎T1+T2 ל-max(T1,T2).

## איך זה מסתדר בדיוק

חלק מהטלפון הוא 8MB, ומקטע של טלגרם הוא 512KB — בדיוק 16 מקטעים לחלק,
בלי שאריות. גם ההגבלה של טלגרם ש"רק המקטע האחרון יכול להיות קטן יותר"
נשמרת, כי החלוקה מיושרת מתחילת הקובץ.

## אם משהו משתבש

כל תקלה — מקטע שנכשל, חלק שלא הספיק להישלח, אי-התאמה בספירת הבייטים —
מבטלת את המסלול הזה, וההעלאה נעשית מהתחלה בדרך הרגילה. במקרה הגרוע זה
בדיוק כמו היום.

## דורש

fix_upload_parallel.py מוחל קודם — הפאץ' הזה נשען על התשתית שלו.

## ידוע

משימה שנקלטה חלקית ונזנחה (הטלפון נסגר באמצע ולא נשלח finish) משאירה את
חיבורי ההעלאה פתוחים עד ההפעלה מחדש הבאה. לא דליפה שמצטברת בקצב מסוכן,
אבל שווה לדעת.

    SAVED_TG_STREAM=0    לכבות את החפיפה בלי לבטל את הפאץ'

    python3 fix_upload_overlap.py --check     # לא נוגע בכלום
    python3 fix_upload_overlap.py             # מחיל, עם גיבוי
    python3 fix_upload_overlap.py --revert    # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

HELPERS = '''
# ── חפיפה: העלאה לטלגרם תוך כדי הקליטה מהטלפון ───────────────────────────
# הקובץ מוקצה מראש בגודלו הסופי וכל חלק נכתב להיסט שלו, ולכן חלק שנכתב
# מוכן לשליחה מיד. טלגרם מקבל מקטעים מחוץ לסדר, אז אין צורך לחכות לסוף.
# חלק מהטלפון = 8MB = בדיוק 16 מקטעים של טלגרם, בלי שאריות.
SAVED_TG_STREAM = os.environ.get("SAVED_TG_STREAM", "1") != "0"


async def _tgs_put(st, sess, part_index, data):
    for attempt in range(5):
        try:
            await sess.invoke(functions.upload.SaveBigFilePart(
                file_id=st["file_id"], file_part=part_index,
                file_total_parts=st["total_parts"], bytes=data))
            return
        except FloodWait as e:
            await asyncio.sleep(e.value + 0.5)
        except Exception:
            if attempt == 4:
                raise
            await asyncio.sleep(0.4 * (attempt + 1))


async def _tgs_worker(j, st, sess):
    per = j["part_size"] // _TG_PART          # 16
    while True:
        idx = await st["q"].get()
        if idx is None:
            return
        off = idx * j["part_size"]
        end = min(off + j["part_size"], st["size"])
        try:
            with open(j["path"], "rb") as fp:
                fp.seek(off)
                p, pos = idx * per, off
                while pos < end:
                    chunk = fp.read(min(_TG_PART, end - pos))
                    if not chunk:
                        raise RuntimeError("קריאה ריקה מהקובץ הזמני")
                    await _tgs_put(st, sess, p, chunk)
                    pos += len(chunk)
                    p += 1
                    st["sent"] += len(chunk)
            st["done"].add(idx)
        except Exception as e:
            st["failed"] = True
            log.warning("חפיפה: חלק %s נכשל (%s) — ההעלאה תיעשה בדרך הרגילה",
                        idx, e)
            return


async def _tgs_start(j):
    bot = _pick_userbot()
    if bot is None:
        return None
    client = bot["client"]
    size = int(j["total"])
    st = {"client": client, "file_id": client.rnd_id(), "size": size,
          "total_parts": (size + _TG_PART - 1) // _TG_PART,
          "q": asyncio.Queue(), "sent": 0, "failed": False,
          "done": set(), "sessions": [], "tasks": []}
    dc_id = await client.storage.dc_id()
    for _ in range(max(1, min(TG_UPLOAD_CONNS, 16))):
        st["sessions"].append(await _make_media_session(client, dc_id))
    st["tasks"] = [asyncio.create_task(_tgs_worker(j, st, s))
                   for s in st["sessions"]]
    log.info("חפיפה: התחילה העלאה לטלגרם על %d חיבורים", len(st["sessions"]))
    return st


def _tgs_feed(j, index):
    st = j.get("tgs")
    if not st or st["failed"]:
        return
    try:
        st["q"].put_nowait(index)
    except Exception:
        st["failed"] = True


async def _tgs_drain(j):
    """מחזיר InputFileBig מוכן, או None — ואז מעלים מחדש בדרך הרגילה."""
    st = j.get("tgs")
    if not st:
        return None
    try:
        for _ in st["tasks"]:
            try:
                st["q"].put_nowait(None)
            except Exception:
                pass
        _d, pending = await asyncio.wait(st["tasks"], timeout=900)
        for t in pending:
            t.cancel()
        await asyncio.gather(*st["tasks"], return_exceptions=True)
    finally:
        for s in st["sessions"]:
            try:
                await s.stop()
            except Exception:
                pass
    # כל אי-התאמה — נופלים למסלול הרגיל. עדיף להעלות שוב מאשר לשלוח חסר.
    if st["failed"] or st["sent"] != st["size"] \\
            or len(st["done"]) != j["n_parts"]:
        if not st["failed"]:
            log.info("חפיפה: %d/%d חלקים, %d/%d בייט — מעלים מחדש",
                     len(st["done"]), j["n_parts"], st["sent"], st["size"])
        return None
    log.info("חפיפה: כל הקובץ כבר בטלגרם בזמן הקליטה")
    return raw_types.InputFileBig(
        id=st["file_id"], parts=st["total_parts"],
        name=os.path.basename(str(j["path"])))


'''

ANCHOR_HELPERS = "def _saved_new_job(total, safe, caption, meta):"

OLD_PART = '''    if index not in j["parts"]:
        j["parts"].add(index)
        j["received"] += got
        if j["total"]:
            j["pct"] = round(100 * j["received"] / j["total"], 1)'''

NEW_PART = '''    if index not in j["parts"]:
        j["parts"].add(index)
        j["received"] += got
        if j["total"]:
            j["pct"] = round(100 * j["received"] / j["total"], 1)
        # מדליקים את ההעלאה החופפת בחלק הראשון בלבד. הדגל נקבע לפני ה-await
        # כדי ששתי בקשות מקבילות לא יבנו שתי בריכות חיבורים.
        if SAVED_TG_STREAM and not j.get("tgs_init"):
            j["tgs_init"] = True
            try:
                j["tgs"] = await _tgs_start(j)
            except Exception as e:
                j["tgs"] = None
                log.warning("חפיפה: לא הצלחתי להתחיל (%s) — ממשיכים רגיל", e)
        _tgs_feed(j, index)'''

OLD_SIG = '''async def _send_video_parallel(client, chat, path, *, caption, filename,
                               duration, width, height, thumb, progress):
    """מעלה במקביל ושולח. זורק אם משהו לא הסתדר — הקורא נופל למסלול הישן."""
    big = await _upload_parallel(client, path, progress=progress)'''

NEW_SIG = '''async def _send_video_parallel(client, chat, path, *, caption, filename,
                               duration, width, height, thumb, progress,
                               big=None):
    """מעלה במקביל ושולח. זורק אם משהו לא הסתדר — הקורא נופל למסלול הישן.

    big: קובץ שכבר הועלה תוך כדי הקליטה (ראה _tgs_drain). כשהוא קיים אין
    מה להעלות שוב — רק לשלוח."""
    if big is None:
        big = await _upload_parallel(client, path, progress=progress)'''

OLD_CALL = '''        try:
            await _send_video_parallel(
                bot["client"], "me", path,
                caption=caption or filename, filename=filename,
                duration=_dur, width=int(meta.get("width") or 0),
                height=int(meta.get("height") or 0),
                thumb=thumb or None, progress=_progress)'''

NEW_CALL = '''        # מה שכבר עלה תוך כדי הקליטה. None ⇒ מעלים כרגיל.
        _pre = await _tgs_drain(job)
        if _pre is not None:
            job.update(sent=total, pct=100)
        try:
            await _send_video_parallel(
                bot["client"], "me", path,
                caption=caption or filename, filename=filename,
                duration=_dur, width=int(meta.get("width") or 0),
                height=int(meta.get("height") or 0),
                thumb=thumb or None, progress=_progress, big=_pre)'''

MARK = "_tgs_drain"


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-ovl-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return
    if "_send_video_parallel" not in src:
        _fail("צריך להחיל קודם את fix_upload_parallel.py — "
              "הפאץ' הזה נשען עליו.")

    parts = [("העוגן להוספה", ANCHOR_HELPERS),
             ("קליטת חלק", OLD_PART),
             ("חתימת השליחה", OLD_SIG),
             ("קריאת השליחה", OLD_CALL)]
    for name, txt in parts:
        n = src.count(txt)
        if n != 1:
            _fail(f"{name}: נמצאו {n} התאמות, ציפינו ל-1. לא נוגעים.")

    out = src.replace(ANCHOR_HELPERS, HELPERS.lstrip("\n") + ANCHOR_HELPERS)
    out = out.replace(OLD_PART, NEW_PART)
    out = out.replace(OLD_SIG, NEW_SIG)
    out = out.replace(OLD_CALL, NEW_CALL)

    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if "--check" in sys.argv:
        print("✓ ארבעת החלקים מתאימים והתוצאה עוברת קומפילציה. "
              "לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-ovl-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print()
    print("   ⚠ ההפעלה מחדש תהרוג העלאה שרצה כרגע.")
    print("   systemctl restart zovex-bot")
    print()
    print("   לכיבוי החפיפה בלי לבטל את הפאץ':  SAVED_TG_STREAM=0")


if __name__ == "__main__":
    main()
