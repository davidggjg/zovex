#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן "הסרט נתקע באמצע".

מה קורה היום, לפי הקוד עצמו:

  _fetch_subrange מנסה עד 4 בוטים, ואם אף אחד לא סיפק את הבייטים הוא זורק
  StreamGap. ה-asyncio.gather ב-_fetch_window מעביר את החריגה הלאה מיד. ב-
  channel_stream_range_parallel אין שום try סביב המשיכה — לא סביב הקריאה
  הישירה ולא סביב ה-await על הקריאה-מראש. החריגה עולה דרך המחולל אל
  StreamingResponse, וגוף התשובה פשוט *נגמר באמצע הסרט*.

  כלומר: כשל חולף אחד — בוט חנוק, FloodWait, חיבור שנפל — מספיק כדי להרוג
  הזרמה שלמה. אין ניסיון חוזר בשום מקום בשרשרת.

  ראיה נוספת שזה לא התנהגות מכוונת: התיעוד של _fetch_subrange מבטיח במפורש
  "מחזיר תמיד בדיוק (hi-lo+1) בייטים (משלים באפסים אם נכשל — לשמירת
  Content-Length)". המימוש לא עושה את זה. מישהו התכוון שיהיה מסלול רך, והוא
  לא קיים.

התיקון: ניסיון חוזר ברמת החלון. כשל חולף → מנסים שוב אחרי המתנה קצרה
והסרט ממשיך. אם הקריאה-מראש נכשלה — מושכים את אותו חלון ישירות במקום למות.
זה לא יכול להחמיר: היום כשל ראשון מסיים את ההזרמה, ואחרי התיקון הוא מסיים
אותה רק אם גם הניסיונות החוזרים נכשלו.

בטוח: מגבה · מוודא שכל עוגן יחיד · בודק שהתוצאה מתקמפלת · --undo מחזיר.

    python3 fix_mid_stall.py          # מחיל
    python3 fix_mid_stall.py --undo   # מחזיר את הגיבוי האחרון
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

A1 = "    def _window_end(p, i):\n"

A1_NEW = '''    # כשל אחד בהורדת חלון סיים עד היום את כל ההזרמה: החריגה עולה מ-
    # _fetch_window דרך המחולל אל StreamingResponse, וגוף התשובה נגמר באמצע
    # הסרט. אין בדרך אף try. בוט חנוק, FloodWait או חיבור שנפל הם דברים
    # חולפים, ולכן ניסיון חוזר אחרי המתנה קצרה מחזיר את הסרט לרוץ.
    WINDOW_TRIES = 3

    async def _fetch_window_retry(wstart, wend):
        for attempt in range(WINDOW_TRIES):
            try:
                return await _fetch_window(wstart, wend)
            except asyncio.CancelledError:
                raise                      # הצופה עזב — לא ניסיון חוזר
            except Exception as e:
                if attempt == WINDOW_TRIES - 1:
                    log.error("חלון %s-%s נכשל סופית אחרי %d ניסיונות: %s",
                              wstart, wend, WINDOW_TRIES, e)
                    raise
                log.warning("חלון %s-%s נכשל (%d/%d): %s - מנסה שוב",
                            wstart, wend, attempt + 1, WINDOW_TRIES, e)
                await asyncio.sleep(1 + attempt)

''' + A1

A2 = """            if ahead is not None and ahead[1] == pos:
                data = await ahead[0]
                ahead = None
            else:
                data = await _fetch_window(pos, wend)
"""

A2_NEW = """            if ahead is not None and ahead[1] == pos:
                try:
                    data = await ahead[0]
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # הקריאה-מראש נכשלה. עד היום זה הרג את הסרט; עכשיו מושכים
                    # את אותו חלון עכשיו, בדיוק כמו במצב בלי קריאה-מראש.
                    log.warning("קריאה-מראש נכשלה ב-%s: %s - מושך ישירות", pos, e)
                    data = await _fetch_window_retry(pos, wend)
                ahead = None
            else:
                data = await _fetch_window_retry(pos, wend)
"""

A3 = "                ahead = (asyncio.create_task(_fetch_window(npos, nend)), npos, nend)\n"
A3_NEW = "                ahead = (asyncio.create_task(_fetch_window_retry(npos, nend)), npos, nend)\n"

EDITS = [("עוגן החלון", A1, A1_NEW),
         ("עוגן הלולאה", A2, A2_NEW),
         ("עוגן הקריאה-מראש", A3, A3_NEW)]


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-midstall-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "_fetch_window_retry" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    if "channel_stream_range_parallel" not in src:
        _fail("אין ב-main.py את מסלול ההזרמה המקבילי — זה לא הקובץ שרץ בשרת")

    out = src
    for name, old, new in EDITS:
        if out.count(old) != 1:
            _fail(f"{name} נמצא {out.count(old)} פעמים (ציפינו לאחת)")
        out = out.replace(old, new, 1)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out); tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp); _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    bak = f"{TARGET}.bak-midstall-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   מעקב:  journalctl -u zovex-bot -f | grep -E 'חלון|קריאה-מראש'")
    print("   נסיגה: python3 fix_mid_stall.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
