#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף התקדמות חיה לבוט העלאת הדרייב: כמה ירד + מהירות בזמן ההורדה, ואחוז +
מהירות + זמן-שנותר בזמן ההעלאה לטלגרם.

מחליף את הפונקציה _handle_drive_upload כולה (בין def שלה לבין on_upload).
הזיהוי מבוסס על שני עוגנים ולא על התאמת טקסט מלאה, כדי לשרוד רווחים שונים.

    python3 fix_drive_progress.py --check
    python3 fix_drive_progress.py
    python3 fix_drive_progress.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py"))
START = "async def _handle_drive_upload(client, message, uid, text):"
END = "async def on_upload(client: Client, message: Message):"
MARK = "async def _prog(current, total):"   # קיים רק בגרסה החדשה

NEW = '''async def _handle_drive_upload(client, message, uid, text):
    import tempfile, time as _t
    link = _extract_drive_link(text)
    if not link:
        await message.reply_text("שלח כך:\\nהיי בוט\\n<קישור Google Drive ציבורי>")
        return
    try:
        free = shutil.disk_usage(str(DATA_DIR)).free
    except Exception:
        free = None
    if free is not None and free < DRIVE_MIN_FREE:
        await message.reply_text(f"❌ אין מספיק מקום פנוי בשרת ({free // 1024**3}GB). נקה ונסה שוב.")
        return
    status = await message.reply_text("⏳ מתחיל הורדה מהדרייב…")
    DRIVE_TMP.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(dir=str(DRIVE_TMP))

    def _dirsize():
        tot = 0
        try:
            for f in os.listdir(workdir):
                fp = os.path.join(workdir, f)
                if os.path.isfile(fp):
                    tot += os.path.getsize(fp)
        except Exception:
            pass
        return tot

    async def _edit(txt):
        try:
            await status.edit_text(txt)
        except Exception:
            pass

    try:
        # הורדה עם התקדמות חיה. gdown לא מדווח התקדמות, אז מנטרים את גודל
        # הקובץ על הדיסק כל 4 שניות — מראה כמה ירד ובאיזו מהירות.
        dl_task = asyncio.create_task(asyncio.to_thread(_blocking_drive_download, link, workdir))
        last_b, last_t = 0, _t.time()
        while not dl_task.done():
            await asyncio.sleep(4)
            cur = _dirsize()
            now = _t.time()
            spd = (cur - last_b) / max(0.1, now - last_t)
            last_b, last_t = cur, now
            await _edit(f"⬇ מוריד מהדרייב… {cur // 1048576}MB · {spd / 1048576:.1f}MB/s")
        try:
            path = dl_task.result()
        except ModuleNotFoundError:
            await _edit("❌ gdown לא מותקן בשרת. הרץ: pip3 install gdown")
            return
        except Exception as e:
            await _edit(f"❌ ההורדה נכשלה: {str(e)[:200]}")
            return
        if not path or not os.path.exists(path):
            await _edit("❌ לא הצלחתי להוריד. ודא שהקישור ציבורי ('כל מי שיש לו הקישור').")
            return
        size = os.path.getsize(path)
        if size > DRIVE_MAX_BYTES:
            await _edit(f"❌ הקובץ גדול מדי ({size // 1024**3}GB). המגבלה דרך הבוט היא "
                        f"{DRIVE_MAX_BYTES // 1024**3}GB — קובץ כזה תעלה מהטלפון.")
            return
        fname = os.path.basename(path)

        # העלאה לטלגרם עם התקדמות חיה: אחוז, מהירות, וזמן שנותר.
        up = {"t0": _t.time(), "last": 0.0}
        async def _prog(current, total):
            now = _t.time()
            if now - up["last"] < 4 and current < total:
                return
            up["last"] = now
            el = max(0.1, now - up["t0"])
            spd = current / el
            eta = int((total - current) / spd) if spd > 0 else 0
            pct = (100 * current / total) if total else 0
            mm, ss = divmod(eta, 60)
            await _edit(f"⬆ מעלה לטלגרם… {pct:.0f}% · {current // 1048576}/{total // 1048576}MB "
                        f"· {spd / 1048576:.1f}MB/s · נותרו {mm}:{ss:02d}")
        dest_channel = current_upload_channel()
        async with _upload_lock:
            try:
                sent = await client.send_document(
                    dest_channel, path, file_name=fname, caption=fname[:200],
                    progress=_prog)
            except Exception as e:
                await _edit(f"❌ ההעלאה לטלגרם נכשלה: {str(e)[:200]}")
                return
            channel_msg_id = sent.id
            note_uploaded_msg_id(dest_channel, channel_msg_id)
            await asyncio.sleep(1.5)
        media = sent.document or sent.video or sent.audio
        fuid = getattr(media, "file_unique_id", "") or ""
        ep = parse_episode_info(fname)
        if ep:
            add_episode_entry(ep, channel_msg_id, fuid, dest_channel)
            await _edit(f"✅ נוסף לרשימת ההעלאות: {ep['series']} — עונה {ep['season']} פרק {ep['episode']}.\\n"
                        f"ממתין לאישור בפאנל.")
            return
        query, options = await smart_tmdb_search(fname)
        if options:
            entry = add_movie_entry(options[0], channel_msg_id, fuid, dest_channel)
            await _edit(f"✅ נוסף לרשימת ההעלאות: {entry['title']} ({entry.get('year') or '?'}).\\nבדוק ואשר בפאנל.")
        else:
            entry = add_movie_entry(
                {"title": query or fname, "year": "", "tmdb_id": 0, "type": "movie",
                 "poster": "", "overview": ""}, channel_msg_id, fuid, dest_channel)
            await _edit(f"✅ נוסף לרשימת ההעלאות בשם: {entry['title']}.\\nבדוק ואשר בפאנל.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


'''


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-dlprog-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ התקדמות חיה כבר מוחלת. לא שונה כלום.")
        return
    if src.count(START) != 1 or src.count(END) != 1:
        _fail(f"עוגנים: START={src.count(START)} END={src.count(END)} (צריך 1 ו-1).")
    si = src.index(START); ei = src.index(END)
    if si >= ei:
        _fail("סדר העוגנים לא צפוי (START אחרי END).")
    out = src[:si] + NEW + src[ei:]
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")
    if a.check:
        print("✓ העוגנים תקינים והתוצאה עוברת קומפילציה. לא שונה כלום (--check).")
        return
    bak = f"{TARGET}.bak-dlprog-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}\n   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
