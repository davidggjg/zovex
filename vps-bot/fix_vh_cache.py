#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_vh_cache.py — מקודדים כל מקטע פעם אחת, לא בכל צפייה.

למה זה נדרש. fix_vh_video פתר את התוכן (מדידה: לפני — videoCodec=null
ו-0x0, אחרי — avc1.640028 ו-608x336), אבל ההמרה רצה מחדש בכל בקשה.
נמדד בייצור אחרי ההתקנה:

    s0  4.02s   s40  7.86s   s120  4.39s   s220  4.08s

פי 1.3–2.5 מהזמן האמיתי. נגינה יחידה מחזיקה, אבל:
  • כל צופה נוסף מקודד את אותם בייטים מאפס
  • קפיצה אחורה מקודדת שוב מה שכבר נוגן
  • בזמן ארבע משיכות במקביל ‎/content/lite החזיר timeout מ-nginx

הסקריפט מוסיף מטמון על הדיסק. המקטע הראשון עולה כמו עכשיו, וכל
בקשה אחריו — לאותו צופה או לכל אחד אחר — היא קריאת קובץ. וגם קידום
מראש של המקטעים הבאים, שמבטל את שתי התקיעות שנמדדו בהתחלה.

מה **לא** נכנס למטמון: כל מה שעובר ב-copy (‎video_ok=true). שם ההמרה
כבר לא קיימת, וקאשינג שלו היה ממלא את הדיסק בכל מה שמישהו צפה בו.
המטמון מוגבל למה שבאמת דורש מעבד.

תקרה וניקוי: VODFIX_CACHE_GB (ברירת מחדל 20). כשעוברים אותה נמחקים
הקבצים שלא נגעו בהם הכי הרבה זמן, עד 90% מהתקרה. הסריקה רצה לכל
היותר פעם בדקה — לא בכל בקשה.

בקרות סביבה:
    VODFIX_CACHE_DIR      /var/cache/zovex-vh
    VODFIX_CACHE_GB       20
    VODFIX_READAHEAD      3     כמה מקטעים לקודד מראש
    VODFIX_MAX_ENCODERS   3     תקרת ffmpeg-ים במקביל, כולל קידום מראש

    python3 fix_vh_cache.py --check
    python3 fix_vh_cache.py
    python3 fix_vh_cache.py --revert
ואחריו:  systemctl restart zovex-bot

דורש ש-fix_vh_video יותקן קודם — הוא נתלה על הקוד שאותו הטלאי ההוא
יצר, ומסרב אם הוא לא שם.
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_vhcache")
MARK = "# [fix_vh_cache]"
NEED = "# [fix_vh_video]"

# ── 1. תצורה ועוזרים ──────────────────────────────────────────────────────────
A1_OLD = '_VF_ABR = os.environ.get("VODFIX_AUDIO_BITRATE", "192k")'
A1_NEW = A1_OLD + '''

''' + MARK + '''
# ── מטמון מקטעי /vh על הדיסק ──────────────────────────────────────────────
# המרה בזמן אמת עולה 4–8 שניות למקטע של עשר שניות (נמדד). בלי מטמון
# המחיר הזה נגבה מכל צופה ומכל קפיצה אחורה, ולכן הוא נגבה כאן פעם אחת.
_VF_CACHE_DIR = Path(os.environ.get("VODFIX_CACHE_DIR", "/var/cache/zovex-vh"))
_VF_CACHE_MAX = int(float(os.environ.get("VODFIX_CACHE_GB", "20")) * (1 << 30))
_VF_READAHEAD = int(os.environ.get("VODFIX_READAHEAD", "3"))
_VF_MAX_ENCODERS = int(os.environ.get("VODFIX_MAX_ENCODERS", "3"))
_vf_build_locks: dict = {}       # (chat,msg,seg) -> Lock, נמחק כשמשתחרר
_vf_readahead: set = set()       # (chat,msg,seg) בתהליך קידום מראש
_vf_encode_sem = None
_vf_sweep_at = 0.0


def _vf_sem():
    """נוצר בפעם הראשונה ולא ברמת המודול: Semaphore נקשר ללופ שבו הוא
    נוצר, ויצירה לפני שהלופ עלה קושרת אותו ללופ הלא נכון."""
    global _vf_encode_sem
    if _vf_encode_sem is None:
        _vf_encode_sem = asyncio.Semaphore(_VF_MAX_ENCODERS)
    return _vf_encode_sem


def _vf_cache_path(chat: int, msg: int, seg: int) -> Path:
    return _VF_CACHE_DIR / f"{chat}_{msg}" / f"s{seg}.ts"


def _vf_cache_sweep() -> None:
    """מפנה מקום לפי הנגיעה האחרונה. רץ לכל היותר פעם בדקה, אחרת היינו
    סורקים את כל הדיסק בכל בקשת מקטע."""
    global _vf_sweep_at
    now = time.time()
    if now - _vf_sweep_at < 60:
        return
    _vf_sweep_at = now
    try:
        files, total = [], 0
        for p in _VF_CACHE_DIR.rglob("s*.ts"):
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
        if total <= _VF_CACHE_MAX:
            return
        files.sort()
        freed = 0
        for _, size, p in files:
            try:
                p.unlink()
            except OSError:
                continue
            total -= size
            freed += 1
            if total <= _VF_CACHE_MAX * 0.9:
                break
        log.info("vodfix: מטמון — נמחקו %d מקטעים, נשאר %.1fGB",
                 freed, total / (1 << 30))
    except Exception as e:
        log.warning("vodfix: ניקוי מטמון נכשל: %s", e)


def _vf_cached_response(path: Path):
    """מגיש מקטע מהדיסק עם Content-Length אמיתי. עד עכשיו התשובה הייתה
    chunked בלי אורך, כי הבייטים נוצרו תוך כדי."""
    size = path.stat().st_size

    def gen():
        with open(path, "rb") as fh:
            while True:
                b = fh.read(65536)
                if not b:
                    break
                yield b

    return StreamingResponse(gen(), media_type="video/mp2t",
                             headers={"Content-Length": str(size),
                                      "Cache-Control": "no-store",
                                      **CORS_MEDIA})


async def _vf_build_to_cache(chat: int, msg: int, seg: int,
                             args: list, dest: Path) -> bool:
    """מקודד מקטע אחד לקובץ. כותב ל-.part ומעביר בשם רק אחרי שה-ffmpeg
    יצא בהצלחה — קובץ חלקי במטמון היה נראה כמו הצלחה לנצח."""
    key = (chat, msg, seg)
    lock = _vf_build_locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            if dest.exists():
                return True
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            proc = None
            written = 0
            async with _vf_sem():
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *args, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE)
                except FileNotFoundError:
                    raise HTTPException(500, "ffmpeg לא מותקן בשרת")
                try:
                    with open(tmp, "wb") as fh:
                        while True:
                            chunk = await proc.stdout.read(65536)
                            if not chunk:
                                break
                            fh.write(chunk)
                            written += len(chunk)
                        fh.flush()
                        os.fsync(fh.fileno())
                    await proc.wait()
                finally:
                    if proc.returncode is None:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
            err = b""
            try:
                err = (await proc.stderr.read())[-300:]
            except Exception:
                pass
            if proc.returncode != 0 or written == 0:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                log.warning("vodfix: מקטע %s של %s/%s נכשל (קוד %s): %s",
                            seg, chat, msg, proc.returncode,
                            err.decode("utf-8", "replace").strip())
                return False
            os.replace(tmp, dest)
            _vf_cache_sweep()
            return True
    finally:
        # בלי הניקוי הזה המילון גדל בערך אחד לכל מקטע שאי פעם נתבקש
        # ולא משתחרר לעולם — בדיוק סוג הצמיחה שמצטברת לאורך ימי ריצה.
        if not lock.locked():
            _vf_build_locks.pop(key, None)


def _vf_schedule_readahead(chat: int, msg: int, seg: int, info: dict) -> None:
    """מקדם את המקטעים הבאים ברקע. זה מה שמבטל את התקיעות בהתחלה:
    נמדד שהנגן מדביק את הבאפר בעשרים השניות הראשונות ואז מתייצב."""
    if _VF_READAHEAD <= 0:
        return
    segs = info.get("segments") or []
    for nxt in range(seg + 1, min(seg + 1 + _VF_READAHEAD, len(segs))):
        key = (chat, msg, nxt)
        if key in _vf_readahead:
            continue
        dest = _vf_cache_path(chat, msg, nxt)
        if dest.exists():
            continue
        _vf_readahead.add(key)

        async def run(nxt=nxt, key=key, dest=dest):
            try:
                await _vf_build_to_cache(
                    chat, msg, nxt, _vf_seg_args(chat, msg, info, nxt), dest)
            except Exception as e:
                log.warning("vodfix: קידום מראש של מקטע %s נכשל: %s", nxt, e)
            finally:
                _vf_readahead.discard(key)

        try:
            asyncio.create_task(run())
        except RuntimeError:
            _vf_readahead.discard(key)'''

# ── 2. הכנת הקלט ובניית הארגומנטים עוברות לפונקציה ──────────────────────────
# האזור הזה יושב היום בתוך vodfix_segment, ולכן הקידום-מראש לא יכול
# לבנות מקטע שאף אחד עוד לא ביקש. הוא עובר כמו שהוא — כולל ההערות,
# שכל אחת מהן מתעדת תקלה שנתפסה בייצור — ומקבל את מספר המקטע כפרמטר.
# REGION נקרא מהקובץ המותקן ולא נכתב כאן פעמיים, כדי שלא ייווצר עותק
# שיסתור את המקור.
REGION = '''    # קלט: /fs אם ה-moov הוזז (הכותרת בזיכרון, ולכן ffmpeg לא מושך את הקצה
    # מטלגרם בכל סגמנט), אחרת הזרם הרגיל.
    iexp = int(time.time()) + SIGN_TTL
    isig = _stream_sig(str(chat_id), str(message_id), iexp) if SIGN_SECRET else ""
    q = f"?exp={iexp}&sig={isig}" if SIGN_SECRET else ""
    route = "fs" if info["header"] else "stream"
    src = f"http://127.0.0.1:{PORT}/{route}/{chat_id}/{message_id}{q}"

    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        # -ss ו--to שניהם לפני הקלט: ffmpeg קופץ ישר לנקודה בבקשת טווח
        # וקורא רק עד הסוף הדרוש. `-to` ולא `-t`, כי מול -copyts המשך נמדד
        # על ציר הזמן המקורי — `-t` היה מסיים לפני נקודת ההתחלה ומוציא
        # קובץ ריק (נבדק: "Output file is empty, nothing was encoded").
        "-ss", f"{start:.3f}", "-to", f"{start + dur:.3f}", "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",   # מסלול תמונת השער נשאר בחוץ
        # [fix_vh_video]  copy כברירת מחדל, H.264 רק לקודק שהדפדפן לא מפענח
        *_vf_vcodec_args(info),
        "-c:a", "aac", "-ac", "2", "-b:a", _VF_ABR, "-ar", "48000",
        # -copyts שומר את חותמות הזמן המקוריות, ולכן הסגמנטים מתחברים
        # ברצף אצל הנגן. תוספת -output_ts_offset כאן הייתה מוסיפה את ההיסט
        # פעם שנייה ומזיזה כל סגמנט קדימה פי שתיים.
        #
        # make_non_negative ולא disabled: מקודד ה-AAC מוסיף priming של
        # ~21ms, ולכן החבילה הראשונה של המקטע הראשון יוצאת עם חותמת זמן
        # שלילית. שדה ה-PTS ב-MPEG-TS הוא 33 סיביות בלי סימן, אז המינוס
        # נעטף ונכתב כ-95443.696 (‎2**33/90000). הנגן ראה וידאו ב-0 וקול
        # ב-95,443, לא הצליח ליישר, ונתקע בטעינה אחרי כשתי שניות — כך
        # נראתה התקלה בונסדיי באפליקציה.
        #
        # make_non_negative מזיז את כל הרצועות באותו דלתא ורק כשיש חותמת
        # שלילית, ולכן יחס קול/תמונה נשמר. נמדד: s1 ו-s2 יוצאים זהים
        # בייט-בבייט לפני ואחרי — רק המקטע הראשון משתנה.
        "-copyts", "-avoid_negative_ts", "make_non_negative",
        "-muxdelay", "0", "-muxpreload", "0",
        "-f", "mpegts", "pipe:1",
    ]
'''

FN_HEAD = ('' + MARK + """
def _vf_seg_args(chat_id: int, message_id: int, info: dict, seg: int) -> list:
    \"\"\"פקודת ה-ffmpeg למקטע אחד. הועברה לכאן מתוך vodfix_segment כדי
    שגם הקידום-מראש יוכל לבנות מקטע שעוד לא נתבקש.\"\"\"
    start, dur = info["segments"][seg]
""")

# ── 3. ענף המטמון ב-vodfix_segment ────────────────────────────────────────────
A3_OLD = '''    start, dur = segs[seg]
'''
A3_NEW = '''    start, dur = segs[seg]

    ''' + MARK + '''
    # רק תוכן שבאמת מומר נכנס למטמון. ב-copy אין מה לחסוך במעבד, וקאשינג
    # שלו היה ממלא את הדיסק בכל מה שמישהו צפה בו.
    if not info.get("video_ok", True):
        dest = _vf_cache_path(chat_id, message_id, seg)
        if dest.exists():
            try:
                os.utime(dest, None)      # נגיעה אחרונה, בשביל הניקוי
            except OSError:
                pass
        else:
            ok = await _vf_build_to_cache(
                chat_id, message_id, seg,
                _vf_seg_args(chat_id, message_id, info, seg), dest)
            if not ok:
                raise HTTPException(500, "בניית המקטע נכשלה")
        _vf_schedule_readahead(chat_id, message_id, seg, info)
        return _vf_cached_response(dest)
'''

PATCHES = [("תצורה ועוזרי המטמון", A1_OLD, A1_NEW),
           ("ענף המטמון במקטע", A3_OLD, A3_NEW)]


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def validate(src: str) -> None:
    compile(src, str(MAIN), "exec")
    tree = ast.parse(src)
    top = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    top.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            top.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                top.add((al.asname or al.name).split(".")[0])
    new = ["_vf_seg_args", "_vf_cache_path", "_vf_cache_sweep",
           "_vf_cached_response", "_vf_build_to_cache",
           "_vf_schedule_readahead", "_vf_sem",
           "_VF_CACHE_DIR", "_VF_CACHE_MAX", "_VF_READAHEAD",
           "_VF_MAX_ENCODERS", "_vf_build_locks", "_vf_readahead",
           "_vf_encode_sem", "_vf_sweep_at"]
    missing = [n for n in new if n not in top]
    if missing:
        sys.exit(f"  ✗ הוגדרו חסרים ברמת המודול: {missing}")
    # מה שהקוד החדש נשען עליו וכבר קיים
    deps = ["asyncio", "os", "time", "Path", "log", "StreamingResponse",
            "HTTPException", "CORS_MEDIA", "SIGN_TTL", "SIGN_SECRET",
            "PORT", "_stream_sig", "_vf_vcodec_args"]
    bad = [n for n in deps if n not in top]
    if bad:
        sys.exit(f"  ✗ תלויות שלא נמצאו ברמת המודול: {bad}")

    # _vf_seg_args חייב להיות מוגדר לפני vodfix_segment? לא — הקריאה
    # היא בזמן ריצה. אבל הוא כן חייב להיות מוגדר *אחרי* _vf_vcodec_args
    # מבחינת קריאוּת, ובעיקר: אסור שיישאר גוף כפול של אותם ארגומנטים.
    if src.count('"-f", "mpegts", "pipe:1",') != 1:
        sys.exit("  ✗ בלוק הארגומנטים מופיע יותר מפעם אחת — יש כפילות")
    if src.count("def _vf_seg_args") != 1:
        sys.exit("  ✗ _vf_seg_args מוגדר יותר מפעם אחת")
    print(f"  ✓ תחביר תקין · {len(new)} שמות חדשים · {len(deps)} תלויות "
          f"אומתו · אין כפילות של בלוק הארגומנטים")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if not BAK.exists():
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, MAIN)
        print(f"✓ שוחזר מ-{BAK}\n  צריך:  systemctl restart zovex-bot")
        return
    if not MAIN.exists():
        sys.exit(f"לא נמצא: {MAIN}")

    src = MAIN.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הטלאי כבר מותקן. אין מה לעשות.")
        return
    if NEED not in src:
        sys.exit("  ✗ fix_vh_video לא מותקן. הטלאי הזה נשען עליו — "
                 "להריץ אותו קודם.")

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            sys.exit(f"  ✗ '{name}': העוגן נמצא {n} פעמים במקום אחת — "
                     f"לא נוגעים בקובץ")
        out = out.replace(old, new, 1)
        print(f"  ✓ {name}")

    # האזור עובר מתוך vodfix_segment לפונקציה חדשה. שני צעדים, כדי שלא
    # יישאר עותק כפול: מחליפים את האזור בקריאה, ומשתילים את הפונקציה
    # מעל נתיב הפלייליסט — כלומר אחרי _vf_vcodec_args ולפני המשתמשים בה.
    n = out.count(REGION)
    if n != 1:
        sys.exit(f"  ✗ 'אזור הארגומנטים': נמצא {n} פעמים במקום אחת — "
                 f"לא נוגעים בקובץ")
    out = out.replace(
        REGION, "    args = _vf_seg_args(chat_id, message_id, info, seg)\n", 1)
    fn = FN_HEAD + REGION.replace("    args = [", "    return [", 1) + "\n\n"
    marker = '@api.get("/vh/{chat_id}/{message_id}/index.m3u8")'
    if out.count(marker) != 1:
        sys.exit("  ✗ לא מצאתי איפה להשתיל את _vf_seg_args")
    out = out.replace(marker, fn + marker, 1)
    print("  ✓ אזור הארגומנטים הועבר ל-_vf_seg_args")

    print()
    validate(out)

    if a.check:
        print(f"\n--check: שום דבר לא נכתב. "
              f"{len(out) - len(src):+d} בייטים.")
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, out)
    if BAK.read_text(encoding="utf-8") != src:
        sys.exit("  ✗ הגיבוי לא זהה למקור — לא ממשיכים")
    print(f"\n✓ נכתב. גיבוי: {BAK}")
    print("⚠ צריך:  systemctl restart zovex-bot")
    print("\nאחרי ה-restart, המטמון ייבנה תוך כדי צפייה:")
    print("  du -sh /var/cache/zovex-vh")
    print("  ls /var/cache/zovex-vh/*/ | head")
    print("  התקרה היא VODFIX_CACHE_GB (ברירת מחדל 20GB) ומתנקה לבד.")


if __name__ == "__main__":
    main()
