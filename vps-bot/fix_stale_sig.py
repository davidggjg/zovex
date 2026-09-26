#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_stale_sig — כל הקטלוג החזיר 403. החתימות היו קפואות מיום השמירה.

## התסמין

"פתאום מלא תכנים לא עובדים, שידורים חיים לא עובדים, כאילו הקישור תקוע."
השרת בריא לגמרי: load 0.12, אפס שגיאות ביומן, ה-API עונה ב-6ms.

## מה נמדד

נשלף ‎/content/lite‎ מהאתר החי ונבדקו כל הקישורים החתומים:

    קישורים חתומים ................ 14,876
    פג תוקף ....................... 14,876      ← כולם
    תקפים ......................... 0

    המוקדם ...... 17/09 19:46   (לפני 213 שעות)
    חציון ....... 26/09 11:23   (לפני 5 שעות)
    המאוחר ...... 26/09 14:52   (לפני 1.5 שעות)

**ולכן היומן נקי.** 403 היא תשובה תקינה של השרת, לא שגיאה — אין מה
לרשום. זה גם למה כל מדד מערכת נראה מושלם בזמן שכלום לא עבד.

## הסיבה

    def sign_stream_url(url):
        m = _STREAM_PATH_RE.search(url)
        if not m or "sig=" in url:
            return url                    ← כאן

‎SIGN_TTL‎ הוא 86400 (24 שעות), ו-‎CONTENT_CACHE_TTL‎ הוא 180 שניות. כלומר
הקטלוג נבנה מחדש כל שלוש דקות, והתכנון היה שכל בנייה תחתום מחדש.

אבל חלק מנתיבי השמירה שומרים ב-‎video_url‎ את הקישור **כולל** ‎?exp=&sig=‎
(‎_vf_local_url‎ ודומיו). כשהחותם פוגש קישור כזה הוא רואה ‎sig=‎ ומחזיר
אותו כמו שהוא. החתימה קפואה מרגע השמירה, ואחרי 24 שעות היא 403 — לנצח.

215 פריטים פגו ב-17/09 ו-14,661 ב-26/09. זה לא אירוע חד-פעמי: זה כל
פריט, 24 שעות אחרי שנשמר.

## מה משתנה

‎sign_stream_url‎ **חותם מחדש תמיד.** הוא מסיר ‎exp‎ ו-‎sig‎ קיימים ומוסיף
חתימה טרייה. הסרה מבוססת פירוק המחרוזת לפי ‎&‎, לא ביטוי רגולרי, כדי
שפרמטרים אחרים בכתובת יישרדו.

זה מה שהתכנון התכוון אליו מלכתחילה — ההערה בשורה 5537 אומרת במפורש
שהקטלוג מוגש עם חתימות טריות וה-ETag מכיל חלון זמן כדי לאלץ רענון.
החלון עבד; החותם הוא זה שדילג.

## למה זה לא יכול לשבור משהו

* חתימה נוצרת מ-‎chat/msg/exp‎ בלבד. אותו מפתח, אותו אלגוריתם, אותם
  שרתים (פייתון ו-Go) — קישור טרי מתקבל בכל מקום שקישור ישן התקבל.
* קישור **שאינו** ‎/stream‎ או ‎/vh‎ לא נוגעים בו, כמו קודם.
* אם ‎SIGN_SECRET‎ ריק, הפונקציה מחזירה את הקישור כמו שהוא, כמו קודם.
* במקרה הגרוע קישור נחתם מחדש מיותר — וזה בדיוק המצב הרצוי.

## מה **לא** נעשה כאן, בכוונה

לא נוגעים במה שכבר שמור במסד. תיקון הנתונים הוא פעולה הרסנית על 18
אלף שורות, והוא מיותר: מרגע שהחותם חותם מחדש, מה שכתוב במסד לא משנה.
מי שירצה לנקות את המסד יעשה זאת בנחת, לא באמצע תקלה.

    python3 fix_stale_sig.py --check
    python3 fix_stale_sig.py
    python3 fix_stale_sig.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_stale_sig"
MARK = "fix_stale_sig"

A_SIGN = '''def sign_stream_url(url):
    """מוסיף ?exp=&sig= לקישור /stream. משאיר קישורים אחרים כמו שהם."""
    if not isinstance(url, str) or not SIGN_SECRET:
        return url
    m = _STREAM_PATH_RE.search(url)
    if not m or "sig=" in url:
        return url
    exp = int(time.time()) + SIGN_TTL
    sig = _stream_sig(m.group(1), m.group(2), exp)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}exp={exp}&sig={sig}"
'''

N_SIGN = '''def _strip_stream_sig(url: str) -> str:
    """[fix_stale_sig] מסיר exp ו-sig מכתובת, ומשאיר כל פרמטר אחר.

    פירוק לפי ‎&‎ ולא ביטוי רגולרי: כתובת עם ‎?t=90&exp=...&sig=...‎ חייבת
    לשמור על ‎t‎, וביטוי שמוחק "מ-exp עד הסוף" היה אוכל אותו."""
    base, sep, query = url.partition("?")
    if not sep:
        return url
    keep = [p for p in query.split("&")
            if p and p.split("=", 1)[0] not in ("exp", "sig")]
    return base + ("?" + "&".join(keep) if keep else "")


def sign_stream_url(url):
    """[fix_stale_sig] חותם קישור /stream מחדש. קישורים אחרים לא נוגעים.

    קודם הייתה כאן יציאה מוקדמת כשהכתובת כבר נשאה חתימה, והיא הפילה את
    כל הקטלוג.
    חלק מנתיבי השמירה שומרים ב-video_url את הקישור כולל ‎?exp=&sig=‎, ולכן
    החתימה נשארה קפואה מיום השמירה — ואחרי SIGN_TTL היא 403 לנצח. נמדד
    על השרת החי: 14,876 קישורים חתומים, 14,876 פגי תוקף, אפס תקפים.

    חותמים מחדש **תמיד**. זו גם הכוונה המקורית: הקטלוג נבנה כל
    CONTENT_CACHE_TTL שניות, וה-ETag נושא חלון זמן כדי לאלץ לקוח לרענן
    לפני שהחתימות פגות. החלון עבד; הפונקציה הזאת היא שדילגה.
    """
    if not isinstance(url, str) or not SIGN_SECRET:
        return url
    m = _STREAM_PATH_RE.search(url)
    if not m:
        return url
    clean = _strip_stream_sig(url)
    exp = int(time.time()) + SIGN_TTL
    sig = _stream_sig(m.group(1), m.group(2), exp)
    sep = "&" if "?" in clean else "?"
    return f"{clean}{sep}exp={exp}&sig={sig}"
'''

EDITS = [("sign_stream_url", A_SIGN, N_SIGN, None)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert names.count("sign_stream_url") == 1, "sign_stream_url כפולה או חסרה"
    assert names.count("_strip_stream_sig") == 1, "_strip_stream_sig כפולה"
    fn = fn_source(s, "sign_stream_url")
    # הבדיקה על הקוד ולא על המקור: הסבר בתיעוד שמזכיר את התנאי הישן
    # אינו התנאי הישן, וגרסה קודמת של הבדיקה הזאת נתפסה בדיוק על כך.
    code = "\n".join(l for l in fn.splitlines()
                     if not l.strip().startswith("#")).split('"""')
    code = code[0] + (code[2] if len(code) > 2 else "")
    assert '"sig=" in url' not in code, "הדילוג על חתימה קיימת עוד שם"
    assert "_strip_stream_sig(url)" in fn, "לא מסירים את החתימה הישנה"
    assert "_stream_sig(m.group(1), m.group(2), exp)" in fn, "החתימה לא נבנית"
    # הסדר קריטי: קודם מסירים, אחר כך מרכיבים על ה-clean ולא על ה-url
    assert fn.index("clean = _strip_stream_sig") < fn.index("sep ="), \
        "מסירים אחרי שמרכיבים"
    assert "{clean}{sep}exp=" in fn, "מרכיבים על הכתובת המקורית ולא על הנקייה"
    # הפונקציה חייבת להישאר מוגנת מפני קישור שאינו /stream
    assert "if not m:" in fn, "בוטלה ההגנה על קישור שאינו /stream"
    assert "not SIGN_SECRET" in fn, "בוטלה ההגנה כשאין מפתח"

    # בדיקת התנהגות אמיתית, על הפונקציות שחולצו מהקוד שנכתב
    ns = {"time": __import__("time"), "hmac": __import__("hmac"),
          "hashlib": __import__("hashlib"), "re": __import__("re"),
          "SIGN_SECRET": "x" * 32, "SIGN_TTL": 86400}
    ns["_STREAM_PATH_RE"] = ns["re"].compile(r"/(?:stream|vh)/(-?\d+)/(\d+)")
    exec(fn_source(s, "_stream_sig"), ns)
    exec(fn_source(s, "_strip_stream_sig"), ns)
    exec(fn, ns)
    sign, strip = ns["sign_stream_url"], ns["_strip_stream_sig"]

    old = "/stream/-100123/456?exp=1&sig=deadbeef"
    new = sign(old)
    assert "exp=1&" not in new and "sig=deadbeef" not in new, \
        f"החתימה הישנה נשארה: {new}"
    assert int(new.split("exp=")[1].split("&")[0]) > ns["time"].time(), \
        "החתימה החדשה אינה בעתיד"
    # פרמטר אחר חייב לשרוד
    keep = sign("/stream/-100/7?t=90&exp=1&sig=old")
    assert "t=90" in keep, f"פרמטר אחר נמחק: {keep}"
    assert keep.count("exp=") == 1 and keep.count("sig=") == 1, \
        f"חתימה כפולה: {keep}"
    # חתימה חוזרת אינה מצטברת
    assert sign(sign(old)).count("sig=") == 1, "חתימה מצטברת"
    # כתובת ללא חתימה — כמו קודם
    assert sign("/stream/-100/7").count("sig=") == 1
    # כתובת שאינה /stream — לא נוגעים
    assert sign("https://example.com/x?a=1") == "https://example.com/x?a=1"
    assert strip("/x") == "/x" and strip("/x?exp=1&sig=2") == "/x"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--revert":
        if not os.path.exists(BAK):
            print(f"❌ אין גיבוי ב-{BAK}")
            return 1
        shutil.copyfile(BAK, PATH)
        print("✓ שוחזר. הרץ:  systemctl restart zovex-bot")
        return 0
    if not os.path.exists(PATH):
        print(f"❌ לא נמצא {PATH}")
        return 1
    with open(PATH, encoding="utf-8") as f:
        s = f.read()
    if MARK in s:
        print("כבר מותקן. אין מה לעשות.")
        return 0
    out = s
    for name, a, b, fn in EDITS:
        if out.count(a) != 1:
            print(f"❌ העוגן '{name}' נמצא {out.count(a)} פעמים (ציפיתי 1). "
                  "לא נוגע.")
            return 1
        out = out.replace(a, b, 1)
    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1
    print(f"יעד:   {PATH}")
    print("שינוי: sign_stream_url חותם מחדש תמיד, במקום לדלג על חתימה קיימת")
    print("       זה מה שהחזיר 403 על כל 14,876 הקישורים בקטלוג")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0
    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_stale_sig"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_stale_sig.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
