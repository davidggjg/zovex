#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן את "הערוץ עובד 20-40 דקות ואז נתקע לתמיד".

הסיפור: 56 מתוך 102 הערוצים עוברים דרך /hls-relay/_fix/, כלומר דרך תהליך
ffmpeg שרץ בשרת וממיר את הזרם. ל-ffmpeg הזה אין כרגע שום דגל התחברות-מחדש,
ולכן *כל* שיהוק זמני של המקור הורג אותו — כולל 502 שהרלֵיי שלנו עצמו מחזיר
כשהמקור לא ענה בזמן.

ולמה זה "נתקע לתמיד" ולא "נתקע לרגע": כשהנגן מבקש את הפלייליסט הבא, הקוד
מפעיל ffmpeg מחדש על תיקייה נקייה — כלומר המספור חוזר ל-s0 ו-MEDIA-SEQUENCE
חוזר ל-0. הנגן, שנמצא באמצע ברצף גבוה, מבקש סגמנט שכבר לא קיים ומקבל 404.
הוא לא מתאושש מזה. זה בדיוק ההבדל בין ערוץ רגיל (שמדלג על מקטע אחד וממשיך)
לבין ערוץ _fix (שקופא) — ומסביר למה "יש מלא דברים שעובדים שלא עובדים אצלנו".

התיקון תוקף את השורש: שה-ffmpeg פשוט לא ימות. הדגלים גורמים לו להתחבר מחדש
לבד, כולל על שגיאות HTTP מהרלֵיי שלנו, במקום לצאת.

הסקריפט בודק בעצמו אילו דגלים ה-ffmpeg שמותקן בשרת מכיר, ומוסיף רק אותם.

בטוח: מגבה · מוודא שהעוגן יחיד · בודק שהתוצאה מתקמפלת · --undo מחזיר.

    python3 fix_hls_stall.py          # מחיל
    python3 fix_hls_stall.py --undo   # מחזיר את הגיבוי האחרון
"""
import datetime, glob, os, pathlib, py_compile, shutil, subprocess, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

# העוגן: שורת הקלט של ffmpeg ב-_hls_fix_start. קצרה ומדויקת, וקיימת פעם אחת.
ANCHOR_ARGS = '            "-fflags", "+genpts", "-i", src,\n'

# עוגן שני: הרגע שבו מגלים ש-ffmpeg מת ומפעילים מחדש. כרגע זה קורה בשקט
# מוחלט, ולכן אין שום דרך לדעת בדיעבד שזה מה שקרה.
ANCHOR_RESTART = """        ent = _hls_fix.get(key)
        if ent and ent["proc"].returncode is None:
            ent["last"] = time.time()
            return ent
"""

RESTART_LOG = """        ent = _hls_fix.get(key)
        if ent and ent["proc"].returncode is None:
            ent["last"] = time.time()
            return ent
        if ent is not None:
            # אם זה מופיע ביומן — מצאנו את הרגע שהערוץ נתקע אצל הצופה: מכאן
            # והלאה המספור מתחיל מאפס והנגן מבקש סגמנטים שכבר לא קיימים.
            log.warning("hls_fix: ffmpeg של %s מת (קוד %s) - מפעיל מחדש, "
                        "הנגן יראה קפיצה במספור", key, ent["proc"].returncode)
"""

# כל דגל: (שם, ערך, המחרוזת שצריכה להופיע ב-ffmpeg -h protocol=http)
CANDIDATES = [
    ("-reconnect", "1", "reconnect"),
    ("-reconnect_streamed", "1", "reconnect_streamed"),
    ("-reconnect_on_network_error", "1", "reconnect_on_network_error"),
    # רק 5xx: זה מה שהרלֵיי שלנו מחזיר כשהמקור לא ענה בזמן, וזה בדיוק המקרה
    # שהורג את ffmpeg היום. 4xx לא נכלל בכוונה — 404 על מקטע שבאמת נעלם היה
    # גורם ל-ffmpeg לנסות שוב לנצח במקום להמשיך הלאה.
    ("-reconnect_on_http_error", "5xx", "reconnect_on_http_error"),
    ("-reconnect_delay_max", "10", "reconnect_delay_max"),
]


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def supported_flags():
    """שואל את ה-ffmpeg שמותקן כאן מה הוא מכיר, במקום להניח."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-h", "protocol=http"],
                             capture_output=True, text=True, timeout=20)
        help_txt = (out.stdout or "") + (out.stderr or "")
    except FileNotFoundError:
        _fail("ffmpeg לא מותקן בשרת")
    except Exception as e:
        _fail(f"הרצת ffmpeg נכשלה: {e}")
    ok, missing = [], []
    for flag, val, needle in CANDIDATES:
        (ok if needle in help_txt else missing).append((flag, val, needle))
    return ok, missing


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-hlsstall-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "-reconnect_delay_max" in src or '"-reconnect"' in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    if "_hls_fix_start" not in src:
        _fail("אין ב-main.py את מסלול ה-_fix — זה לא הקובץ שרץ בשרת")
    if src.count(ANCHOR_ARGS) != 1:
        _fail(f"עוגן הארגומנטים נמצא {src.count(ANCHOR_ARGS)} פעמים (ציפינו לאחת)")

    ok, missing = supported_flags()
    if not ok:
        _fail("ה-ffmpeg בשרת לא מכיר אף אחד מדגלי ההתחברות-מחדש")
    for flag, val, _ in missing:
        print(f"⚠️  {flag} לא נתמך בגרסת ה-ffmpeg כאן — מדלגת עליו")

    flags = "".join(f'            "{f}", "{v}",\n' for f, v, _ in ok)
    new_args = (
        "            # בלי הדגלים האלה כל שיהוק זמני של המקור הורג את ffmpeg,\n"
        "            # וההפעלה מחדש מאפסת את המספור — הנגן מבקש סגמנט שכבר לא\n"
        "            # קיים ונתקע לתמיד. עדיף שפשוט לא ימות.\n"
        + flags + ANCHOR_ARGS
    )
    out = src.replace(ANCHOR_ARGS, new_args, 1)

    if out.count(ANCHOR_RESTART) == 1:
        out = out.replace(ANCHOR_RESTART, RESTART_LOG, 1)
    else:
        print("⚠️  לא נמצא העוגן לרישום ההפעלה-מחדש — מחילה רק את הדגלים")

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out); tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp); _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    bak = f"{TARGET}.bak-hlsstall-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל. דגלים שנוספו: " + " ".join(f for f, _, _ in ok))
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   מעקב:  journalctl -u zovex-bot -f | grep hls_fix")
    print("   נסיגה: python3 fix_hls_stall.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
