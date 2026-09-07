#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מעלה לטלגרם על כמה חיבורים במקביל במקום אחד.

## המדידה

שלב ② (שרת → טלגרם) רץ ב-1.9 MB/s, כלומר ~15 מגהביט. 3.91GB ב-55 דקות.
זה לא מגבלת הקו של השרת — זו מגבלה של **חיבור בודד**, בדיוק אותה תופעה
שנמדדה בהעלאה מהטלפון וטופלה שם עם שמונה חיבורים.

## למה זה קורה — מקוד המקור של Pyrogram

מתוך pyrogram/methods/advanced/save_file.py (2.0.106):

    part_size = 512 * 1024
    workers_count = 4 if is_big else 1
    session = Session(...)                                    ← אחד
    workers = [... worker(session) for _ in range(workers_count)]
    queue = asyncio.Queue(1)                                  ← עומק 1

ארבעה עובדים, אבל כולם על **אותו Session** — כלומר חיבור TCP אחד. ועוד
תור בעומק 1, שלא נותן לקורא להקדים יותר ממקטע אחד. כל מקטע הוא 512KB
והלוך-חזור לדאטה-סנטר של טלגרם, אז הקצב נקבע בעיקר על ידי ההשהיה ולא על
ידי הרוחב.

יש שם עוד דבר ששווה לדעת:

    try:  await session.invoke(data)
    except Exception as e:  log.exception(e)          ← ולא נזרק הלאה

מקטע שנכשל נרשם ליומן והריצה ממשיכה. כלומר קובץ יכול "להסתיים בהצלחה"
כשחסר לו חלק. כאן מקטע שנכשל אחרי חמישה ניסיונות מפיל את ההעלאה, כמו
שצריך.

## מה עושים במקום

SaveBigFilePart מקבל מקטעים **מחוץ לסדר וממספר חיבורים**, כל עוד ה-file_id
זהה — זה מנגנון מתועד של טלגרם. אז: N חיבורים לאותו DC ביתי, כל אחד
מושך מקטעים מתור משותף. אחרי שכל המקטעים עלו, ההודעה עצמה נשלחת עם
messages.SendMedia והקובץ המוכן.

בניית החיבורים משתמשת ב-_make_media_session שכבר קיים בקובץ ומשמש את
מסלול ההורדה — אותו auth_key, בלי אימות מחדש.

## אם משהו משתבש

כל כשל — בבניית החיבורים, בהעלאה, בשליחה — נופל חזרה ל-send_video המקורי.
במקרה הגרוע ההעלאה תהיה איטית כמו היום, לא שבורה.

## כוונון בלי בנייה מחדש

    TG_UPLOAD_CONNS=8     מספר החיבורים (ברירת מחדל 8, תקרה 16)

כמו בהעלאה מהטלפון: אפשר לנסות 8 / 12 / 16 ע"י שינוי משתנה סביבה
והפעלה מחדש, בלי לגעת בקוד.

## חשוב

החלת הפאץ' דורשת `systemctl restart zovex-bot`, וזה **יהרוג העלאה שרצה
כרגע**. להריץ רק כשאין העלאה פעילה.

    python3 fix_upload_parallel.py --check     # לא נוגע בכלום
    python3 fix_upload_parallel.py             # מחיל, עם גיבוי
    python3 fix_upload_parallel.py --revert    # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

HELPER = '''
# ── העלאה מקבילה לטלגרם ──────────────────────────────────────────────────
# Pyrogram מעלה על Session אחד (ארבעה עובדים, תור בעומק 1, מקטעי 512KB),
# ולכן הקצב נקבע על ידי ההשהיה לדאטה-סנטר ולא על ידי רוחב הפס. נמדד:
# 1.9 MB/s על קו שנותן הרבה יותר.
#
# SaveBigFilePart מקבל מקטעים מחוץ לסדר וממספר חיבורים כל עוד file_id זהה.
TG_UPLOAD_CONNS = int(os.environ.get("TG_UPLOAD_CONNS", "8"))
_TG_PART = 512 * 1024          # התקרה של טלגרם למקטע. אי אפשר לחרוג ממנה.


async def _upload_parallel(client, path, progress=None):
    """מעלה קובץ גדול על כמה חיבורים ומחזיר InputFileBig מוכן לשליחה."""
    size = os.path.getsize(path)
    total_parts = (size + _TG_PART - 1) // _TG_PART
    file_id = client.rnd_id()
    dc_id = await client.storage.dc_id()
    n = max(1, min(TG_UPLOAD_CONNS, 16, total_parts))

    sessions = []
    try:
        for _ in range(n):
            sessions.append(await _make_media_session(client, dc_id))
        if not sessions:
            raise RuntimeError("לא נוצר אף חיבור")

        q = asyncio.Queue(maxsize=len(sessions) * 2)
        sent = 0
        errors = []

        async def worker(sess):
            nonlocal sent
            while True:
                item = await q.get()
                if item is None:
                    return
                idx, chunk = item
                for attempt in range(5):
                    try:
                        await sess.invoke(functions.upload.SaveBigFilePart(
                            file_id=file_id, file_part=idx,
                            file_total_parts=total_parts, bytes=chunk))
                        break
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 0.5)
                    except Exception as e:          # ניתוק רגעי — ננסה שוב
                        if attempt == 4:
                            # ולא מתעלמים, כמו ש-Pyrogram עושה: מקטע חסר
                            # פירושו קובץ פגום שנראה כאילו הצליח.
                            errors.append(e)
                            return
                        await asyncio.sleep(0.4 * (attempt + 1))
                sent += len(chunk)
                if progress:
                    try:
                        progress(sent, size)
                    except Exception:
                        pass

        tasks = [asyncio.create_task(worker(s)) for s in sessions]
        try:
            with open(path, "rb") as fp:
                idx = 0
                while True:
                    if errors:
                        break
                    chunk = fp.read(_TG_PART)
                    if not chunk:
                        break
                    await q.put((idx, chunk))
                    idx += 1
        finally:
            # put_nowait ולא await: אם עובד כבר מת (מקטע שנכשל), תור מלא
            # היה תוקע את ה-finally לנצח. סנטינל שנפל מטופל ע"י ה-wait
            # והביטול שאחריו.
            for _ in tasks:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            _done, pending = await asyncio.wait(tasks, timeout=60)
            for t in pending:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        if errors:
            raise errors[0]
        if sent < size:
            raise RuntimeError(
                f"עלו {sent} מתוך {size} בייט — לא שולחים קובץ חסר")
        return raw_types.InputFileBig(
            id=file_id, parts=total_parts, name=os.path.basename(str(path)))
    finally:
        for s in sessions:
            try:
                await s.stop()
            except Exception:
                pass


async def _send_video_parallel(client, chat, path, *, caption, filename,
                               duration, width, height, thumb, progress):
    """מעלה במקביל ושולח. זורק אם משהו לא הסתדר — הקורא נופל למסלול הישן."""
    big = await _upload_parallel(client, path, progress=progress)
    thumb_in = None
    if thumb:
        # התמונה זעירה; המסלול הרגיל של Pyrogram מספיק לה בהחלט.
        try:
            thumb_in = await client.save_file(thumb)
        except Exception:
            thumb_in = None
    attrs = [
        raw_types.DocumentAttributeVideo(
            supports_streaming=True, duration=int(duration or 0),
            w=int(width or 0), h=int(height or 0)),
        raw_types.DocumentAttributeFilename(file_name=filename),
    ]
    media = raw_types.InputMediaUploadedDocument(
        mime_type="video/mp4", file=big, thumb=thumb_in, attributes=attrs)
    return await client.invoke(functions.messages.SendMedia(
        peer=await client.resolve_peer(chat), media=media,
        message=(caption or "")[:1000], random_id=client.rnd_id()))


'''

ANCHOR = "async def get_media_session_pool(client, owner: str, dc_id: int, n: int) -> list:"

OLD_CALL = '''        await bot["client"].send_video(
            "me", str(path), caption=caption or filename,
            file_name=filename, duration=_dur,
            width=int(meta.get("width") or 0),
            height=int(meta.get("height") or 0),
            thumb=thumb or None, supports_streaming=True,
            progress=_progress)'''

NEW_CALL = '''        # קודם המסלול המקביל; אם הוא נכשל מכל סיבה — המסלול המקורי.
        # במקרה הגרוע זה איטי כמו קודם, לא שבור.
        try:
            await _send_video_parallel(
                bot["client"], "me", path,
                caption=caption or filename, filename=filename,
                duration=_dur, width=int(meta.get("width") or 0),
                height=int(meta.get("height") or 0),
                thumb=thumb or None, progress=_progress)
        except Exception as _e:
            log.warning("העלאה מקבילה נכשלה (%s) — נופל למסלול הרגיל",
                        _e)
            job.update(sent=0, pct=0, started_tg=time.time())
            await bot["client"].send_video(
                "me", str(path), caption=caption or filename,
                file_name=filename, duration=_dur,
                width=int(meta.get("width") or 0),
                height=int(meta.get("height") or 0),
                thumb=thumb or None, supports_streaming=True,
                progress=_progress)'''

MARK = "_send_video_parallel"


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-upar-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return

    for name, txt in (("העוגן", ANCHOR), ("קריאת ההעלאה", OLD_CALL)):
        n = src.count(txt)
        if n != 1:
            _fail(f"{name}: נמצאו {n} התאמות, ציפינו ל-1. לא נוגעים.")

    out = src.replace(ANCHOR, HELPER.lstrip("\n") + ANCHOR)
    out = out.replace(OLD_CALL, NEW_CALL)

    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if "--check" in sys.argv:
        print("✓ שני החלקים מתאימים והתוצאה עוברת קומפילציה. "
              "לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-upar-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print()
    print("   ⚠ ההפעלה מחדש תהרוג העלאה שרצה כרגע. לוודא שאין אחת.")
    print("   systemctl restart zovex-bot")
    print()
    print("   לכוונון מספר החיבורים (ברירת מחדל 8):")
    print("     systemctl set-environment TG_UPLOAD_CONNS=12")
    print("     או שורת Environment= ביחידת ה-systemd")


if __name__ == "__main__":
    main()
