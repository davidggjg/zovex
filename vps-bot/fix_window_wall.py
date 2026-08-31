#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
תוחם את הזמן שחלון יחיד רשאי לשתוק, ומסיים את התשובה במקום להיתקע.

מה שהמדידה הראתה (12 ריצות, לוג השרת מהדקה שלפני כל נפילה):

    06:47   21 × Session stopped · 11 × Session started
            10 × Send exception: RuntimeError (כתיבה לחיבור סגור)
             1 × media bands (bot_0) 3 timeouts רצופים — מרענן חיבורים
             1 × subrange: bot_1  לא סיפק בייטים תוך 25s
             1 × subrange: bot_14 לא סיפק בייטים תוך 25s
    06:48   ← הצופה נפל, TimeoutError אחרי 90 שניות בלי בייט

השרשרת: חיבורי המדיה נכשלים → הבריכה מופלת ונבנית מחדש → החלון נופל למסלול
הגיבוי → שם 25 שניות לכל בוט על עד ארבעה בוטים → עד 100 שניות שבהן הלקוח
לא מקבל דבר. הניסיון החוזר שהוספתי אתמול הכפיל את זה לכ-110 שניות ומעלה.

הטעות בתפיסה: ניסיתי להציל חלון בכל מחיר. אבל נגן שמקבל תשובה קטועה מבקש
את הטווח מחדש ומתאושש תוך שנייה, ואילו נגן שמקבל חיבור פתוח ששותק דקה וחצי
פשוט מוותר. לכן עדיף להיכשל מהר מאשר לנסות לאורך זמן.

התיקון: תקציב קיר לחלון (ברירת מחדל 30 שניות סך הכל, כולל כל הניסיונות),
ואם הוא נגמר — מסיימים את התשובה בנקייה במקום להמשיך לשתוק.

דורש שה-fix_mid_stall.py כבר הוחל (הוא זה שיצר את _fetch_window_retry).

בטוח: מגבה · מוודא שכל עוגן יחיד · בודק שהתוצאה מתקמפלת · --undo מחזיר.

    python3 fix_window_wall.py          # מחיל
    python3 fix_window_wall.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD_RETRY = '''    # כשל אחד בהורדת חלון סיים עד היום את כל ההזרמה: החריגה עולה מ-
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
'''

NEW_RETRY = '''    # חלון שנכשל היה מסיים את כל ההזרמה, ולכן נוסף ניסיון חוזר. אבל ניסיון
    # חוזר בלי גבול זמן החמיר: המסלול שאליו נופלים נותן 25 שניות לכל בוט על
    # עד ארבעה בוטים, כלומר עד 100 שניות שקטות, וכפול מספר הניסיונות.
    # לכן התקציב כאן הוא תקציב *קיר* לחלון שלם, כולל כל הניסיונות והנפילה
    # למסלול הגיבוי. הנגן לא שורד שתיקה ארוכה, אבל כן מתאושש מתשובה קטועה.
    WINDOW_WALL = float(os.environ.get("STREAM_WINDOW_WALL", "30"))
    WINDOW_TRIES = 2

    async def _fetch_window_retry(wstart, wend):
        """מנסה שוב רק אם *נשאר* זמן בתקציב הקיר, ולא מספר קבוע של פעמים."""
        t0 = time.time()
        last = None
        for attempt in range(WINDOW_TRIES):
            left = WINDOW_WALL - (time.time() - t0)
            if left <= 1.0:
                break
            try:
                return await asyncio.wait_for(_fetch_window(wstart, wend),
                                              timeout=left)
            except asyncio.CancelledError:
                raise                      # הצופה עזב — לא ניסיון חוזר
            except Exception as e:
                last = e
                log.warning("חלון %s-%s נכשל (%d/%d, נותרו %.0fש): %s: %s",
                            wstart, wend, attempt + 1, WINDOW_TRIES,
                            max(0.0, WINDOW_WALL - (time.time() - t0)),
                            type(e).__name__, e)
        raise last or asyncio.TimeoutError(
            f"חלון {wstart}-{wend} חרג מתקציב הקיר ({WINDOW_WALL:.0f}ש)")
'''

OLD_LOOP = '''            if ahead is not None and ahead[1] == pos:
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
'''

NEW_LOOP = '''            try:
                if ahead is not None and ahead[1] == pos:
                    try:
                        data = await ahead[0]
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log.warning("קריאה-מראש נכשלה ב-%s: %s - מושך ישירות",
                                    pos, e)
                        data = await _fetch_window_retry(pos, wend)
                    ahead = None
                else:
                    data = await _fetch_window_retry(pos, wend)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # מסיימים את התשובה במקום להמשיך לשתוק. הנגן מזהה תשובה
                # קטועה, מבקש את אותו טווח מחדש ומתאושש תוך שנייה — לעומת
                # דקה וחצי של חיבור פתוח ושותק, שממנה הוא לא חוזר.
                log.error("חלון %s-%s ויתר אחרי %.0fש — מסיים את התשובה כדי "
                          "שהנגן יבקש שוב: %s: %s",
                          pos, wend, WINDOW_WALL, type(e).__name__, e)
                return
'''

EDITS = [("בלוק הניסיון החוזר", OLD_RETRY, NEW_RETRY),
         ("לולאת ההגשה", OLD_LOOP, NEW_LOOP)]


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-wall-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "WINDOW_WALL" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    if "_fetch_window_retry" not in src:
        _fail("fix_mid_stall.py לא הוחל — הרץ אותו קודם")

    out = src
    for name, old, new in EDITS:
        if out.count(old) != 1:
            _fail(f"{name}: נמצא {out.count(old)} פעמים (ציפינו לאחת)")
        out = out.replace(old, new, 1)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out); tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp); _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    bak = f"{TARGET}.bak-wall-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   מעקב:  journalctl -u zovex-bot -f | grep -E 'חלון|ויתר'")
    print("   נסיגה: python3 fix_window_wall.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
