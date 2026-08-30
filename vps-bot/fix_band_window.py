#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן את הסיבה ל"תקיעות של 12 שניות" — חיבור מת שנשאר בבריכה לנצח.

מה נמדד: 15%–42% מהבקשות נתקעות, וכולן על אותו מספר (12.0 · 11.7 · 12.5
שניות). התקציב לחלון הוא `min(35, 6 + מגהבייט×3)` — 9 שניות לרצועה של
מגהבייט. חיבור MTProto מת לא מחזיר שגיאה, הוא נתקע; החלון ממתין את כל 9
השניות, מוותר, ונופל למסלול הגיבוי שמצליח תוך ~3. סה"כ 12.

למה זה לא מתרפא לבד: הבריכה מופלת רק אחרי N timeouts *רצופים* לאותו
(בוט, DC), והמונה מתאפס בכל הצלחה. בבריכה יש כמה חיבורים — אחד מת וכמה
חיים — אז בקשות שנופלות על החיים מאפסות את המונה, והמת לעולם לא מגיע
לרצף. כל בקשה שנופלת עליו משלמת 9 שניות, עד אתחול.

למה לא פשוט להוריד את הסף ל-1: זה כבר נוסה והיה גרוע יותר. ההערה בקוד
עצמו אומרת שהפלת הבריכה על כל timeout בודד היא ה-thrash שהקפיץ תקיעות כל
כמה דקות. timeout בודד באמת יכול להיות סתם איטיות.

התיקון: המונה נשאר בדיוק אותו סף, אבל נספר בחלון זמן במקום ברצף. כלומר
"שלושה timeouts בעשר דקות" במקום "שלושה ברצף". איטיות מזדמנת עדיין לא
מפילה כלום, אבל חיבור מת צובר פגיעות עד שהוא מפונה — וזה בדיוק מה שהמונה
הרצוף לא מצליח לעשות.

    python3 fix_band_window.py           # מחיל
    python3 fix_band_window.py --undo    # מחזיר את הגיבוי האחרון
"""
import datetime, glob, os, pathlib, py_compile, re, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
WINDOW_DEFAULT = 600          # שניות — חלון הספירה


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-band-*"))
    if not baks:
        _fail("לא נמצא גיבוי להחזרה.")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "BAND_TIMEOUT_WINDOW" in src:
        print("✓ התיקון כבר מוחל. אין מה לעשות.")
        return

    # ── מאתרים את שלושת העוגנים. כל אחד חייב להופיע בדיוק פעם אחת; אם לא,
    #    הקובץ שרץ בשרת אינו מה שציפינו לו ועדיף לא לגעת בו בכלל.
    anchors = {
        "limit": re.compile(
            r'^BAND_TIMEOUT_LIMIT = int\(os\.environ\.get\("STREAM_BAND_TIMEOUT_LIMIT", "\d+"\)\)$',
            re.M),
        "reset": re.compile(r'^(\s*)_band_timeouts\.pop\(\(bot\["name"\], dc_id\), None\).*$', re.M),
        "count": re.compile(
            r'^(\s*)n = _band_timeouts\.get\(key, 0\) \+ 1\n\s*_band_timeouts\[key\] = n$', re.M),
    }
    found = {}
    for name, rx in anchors.items():
        hits = rx.findall(src)
        if len(hits) != 1:
            _fail(f"העוגן '{name}' נמצא {len(hits)} פעמים (ציפינו לאחת) — "
                  f"הקובץ בשרת שונה ממה שהפאץ' מכיר.")
        found[name] = rx.search(src)

    out = src

    # 1 · קבוע החלון, מיד אחרי הסף
    out = anchors["limit"].sub(
        lambda m: m.group(0) + "\n"
        '# חלון הספירה. הסף נשאר כפי שהוא, אבל נספר "N timeouts בתוך X שניות"\n'
        '# ולא "N ברצף": הצלחה על חיבור בריא באותה בריכה כבר לא מוחקת את\n'
        '# העדות על חיבור מת שיושב לידו.\n'
        'BAND_TIMEOUT_WINDOW = float(os.environ.get("STREAM_BAND_TIMEOUT_WINDOW", '
        f'"{WINDOW_DEFAULT}"))',
        out, count=1)

    # 2 · הצלחה כבר לא מאפסת
    ind = found["reset"].group(1)
    out = anchors["reset"].sub(
        f"{ind}# (בכוונה בלי איפוס: הצלחה כאן היא של חיבור אחר בבריכה, והיא\n"
        f"{ind}#  שהסתירה עד היום את החיבור המת. הפגיעות פגות לבד לפי הזמן.)",
        out, count=1)

    # 3 · ספירה בחלון זמן
    ind2 = found["count"].group(1)
    out = anchors["count"].sub(
        f"{ind2}_now = time.time()\n"
        f"{ind2}hits = [t for t in _band_timeouts.get(key, [])\n"
        f"{ind2}        if _now - t < BAND_TIMEOUT_WINDOW]\n"
        f"{ind2}hits.append(_now)\n"
        f"{ind2}_band_timeouts[key] = hits\n"
        f"{ind2}n = len(hits)",
        out, count=1)

    if out == src:
        _fail("שום החלפה לא בוצעה בפועל.")

    # ── בודקים שהתוצאה מתקמפלת לפני שנוגעים בקובץ החי
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

    bak = f"{TARGET}.bak-band-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")

    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print("   מונה ה-timeouts עבר מ'רצוף' ל'בתוך חלון של "
          f"{WINDOW_DEFAULT // 60} דקות'. הסף עצמו לא שונה.")
    print()
    print("   עכשיו:   systemctl restart zovex-bot")
    print("   ואז:     python3 /opt/zovex-bot/bench.py --runs 20")
    print("   נסיגה:   python3 fix_band_window.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
