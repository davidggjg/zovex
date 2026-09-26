#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_stale_sig2 — החותם תוקן, אבל אף אחד לא קרא לו. זה השער האמיתי.

## איך זה נמדד

אחרי ‎fix_stale_sig‎ נשלף הקטלוג מהאתר החי:

    קישורים חתומים ................ 14,876
    קיבלו חתימה טרייה .............      1
    נשארו פגי תוקף ................ 14,875

כלומר התיקון הראשון נכון — ‎sign_stream_url‎ אכן חותם מחדש — אבל הוא
**אינו נקרא** על 14,875 פריטים.

## הסיבה

    def _expand_urls(items):
        for e in items:
            for k in ("video_url", "video_id"):
                v = e.get(k)
                if isinstance(v, str) and BASE_TOKEN in v:      ← השער
                    e[k] = sign_stream_url(v.replace(BASE_TOKEN, ...))

חתימה מתבצעת **רק** על קישור ששמור עם ה-placeholder ‎%BASE%‎. פריט
ששמור עם כתובת מוחלטת אינו מכיל ‎%BASE%‎, ולכן החותם לא רואה אותו
בכלל — ומה שכתוב במסד מוגש כמו שהוא, כולל חתימה שפגה מזמן.

והצד השני סובל מאותה חולשה בדיוק:

    def _collapse_urls(items):
        if isinstance(v, str) and STREAM_PUBLIC_BASE and STREAM_PUBLIC_BASE in v:
            ...
            v = re.sub(r"[?&](exp|sig)=[^&]*", "", v)           ← בתוך התנאי

הסרת החתימה לפני שמירה נמצאת **בתוך** התנאי על הבסיס. כתובת ששמורה
עם בסיס אחר מזה שמוגדר כרגע — ‎http‎ מול ‎https‎, IP מול דומיין, או
בסיס שהוחלף מאז — לא עוברת כאן, והחתימה נשמרת לתוך המסד.

שני השערים יחד מייצרים בדיוק את מה שנמדד: החתימה נכנסת למסד בשמירה,
ואף פעם לא מוחלפת בהגשה.

## מה משתנה

**‎_expand_urls‎ חותם כל קישור ‎/stream‎ או ‎/vh‎, בלי תלות בבסיס.**
‎sign_stream_url‎ מחזיר כל קישור אחר כמו שהוא, ולכן ההרחבה בטוחה:
קישורי ‎/hls-relay/‎, כתובות חיצוניות וכל השאר אינם נוגעים.

**‎_collapse_urls‎ מסיר ‎exp‎ ו-‎sig‎ מכל קישור ‎/stream‎**, גם כשהבסיס
אינו מתאים. זה מונע את הישנות התקלה על תכנים חדשים.

## למה זה לא יכול לשבור משהו

* החתימה נגזרת מ-‎chat/msg/exp‎ בלבד, ולכן קישור טרי תקף בכל מקום
  שקישור ישן היה תקף — כולל שרת ה-Go, שמשתמש באותו מפתח.
* ‎sign_stream_url‎ בודק ‎_STREAM_PATH_RE‎ ומחזיר כל דבר אחר בלי שינוי.
* ה-placeholder ממשיך לעבוד כקודם: מרחיבים אותו, ואז חותמים.
* אם ‎SIGN_SECRET‎ ריק — שתי הפונקציות מתנהגות כמו קודם.

## התלות

דורש ‎fix_stale_sig‎. בלעדיו ‎sign_stream_url‎ עוד מדלג על קישור
שנושא חתימה, וקריאה אליו לא תשנה דבר — לכן הסקריפט מסרב לרוץ בלעדיו.

    python3 fix_stale_sig2.py --check
    python3 fix_stale_sig2.py
    python3 fix_stale_sig2.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_stale_sig2"
MARK = "fix_stale_sig2"

A_EXPAND = '''def _expand_urls(items: list) -> list:
    for e in items:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if isinstance(v, str) and BASE_TOKEN in v:
                e[k] = sign_stream_url(v.replace(BASE_TOKEN, STREAM_PUBLIC_BASE))
    return items
'''

N_EXPAND = '''def _expand_urls(items: list) -> list:
    """[fix_stale_sig2] מרחיב את ה-placeholder וחותם כל קישור /stream.

    קודם החתימה הייתה בתוך התנאי ‎if BASE_TOKEN in v‎, ולכן פריט ששמור
    עם כתובת מוחלטת לא נחתם **בכלל** — הוא הוגש עם מה שכתוב במסד,
    כולל חתימה שפגה. נמדד אחרי fix_stale_sig: 14,876 קישורים חתומים,
    רק 1 קיבל חתימה טרייה, 14,875 נשארו פגי תוקף.

    ‎sign_stream_url‎ מחזיר כל קישור שאינו /stream או /vh כמו שהוא,
    ולכן קריאה על כל הקישורים בטוחה: /hls-relay וכתובות חיצוניות
    עוברות בלי שינוי.
    """
    for e in items:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if not isinstance(v, str):
                continue
            if BASE_TOKEN in v:
                v = v.replace(BASE_TOKEN, STREAM_PUBLIC_BASE)
            e[k] = sign_stream_url(v)
    return items
'''

A_COLLAPSE = '''def _collapse_urls(items: list) -> list:
    for e in items:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if isinstance(v, str) and STREAM_PUBLIC_BASE and STREAM_PUBLIC_BASE in v:
                v = v.replace(STREAM_PUBLIC_BASE, BASE_TOKEN)
                # מסירים חתימה/תוקף אם דבקו בקישור (הם מתווספים מחדש בכל הגשה)
                if "/stream/" in v:
                    v = re.sub(r"[?&](exp|sig)=[^&]*", "", v)
                e[k] = v
    return items
'''

N_COLLAPSE = '''def _collapse_urls(items: list) -> list:
    """[fix_stale_sig2] מחליף את הבסיס ב-placeholder, ומסיר חתימה תמיד.

    הסרת ה-exp/sig הייתה **בתוך** התנאי על הבסיס, ולכן כתובת ששמורה
    עם בסיס אחר מזה שמוגדר כרגע — http מול https, IP מול דומיין, או
    בסיס שהוחלף מאז — נשמרה למסד יחד עם החתימה. משם היא לא הוחלפה
    אף פעם, וזה מה שהפיל את כל הקטלוג ל-403.

    עכשיו: הסרת החתימה חלה על כל קישור /stream או /vh, בלי תלות בבסיס.
    """
    for e in items:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if not isinstance(v, str):
                continue
            if STREAM_PUBLIC_BASE and STREAM_PUBLIC_BASE in v:
                v = v.replace(STREAM_PUBLIC_BASE, BASE_TOKEN)
            # חתימה לעולם לא נשמרת: היא מתווספת מחדש בכל הגשה
            if _STREAM_PATH_RE.search(v):
                v = _strip_stream_sig(v)
            e[k] = v
    return items
'''

EDITS = [("_expand_urls", A_EXPAND, N_EXPAND),
         ("_collapse_urls", A_COLLAPSE, N_COLLAPSE)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def code_only(fn: str) -> str:
    """הקוד בלי התיעוד והערות — כדי שהסבר לא ייתפס כתנאי."""
    parts = fn.split('"""')
    body = parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_expand_urls", "_collapse_urls", "sign_stream_url",
              "_strip_stream_sig"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    ex = code_only(fn_source(s, "_expand_urls"))
    # החתימה חייבת לצאת מחוץ לתנאי על ה-placeholder
    assert "if BASE_TOKEN in v:\n                v = v.replace" in ex, \
        "ההרחבה לא הופרדה מהחתימה"
    assert "e[k] = sign_stream_url(v)" in ex, "לא חותמים כל קישור"
    assert "sign_stream_url(v.replace(" not in ex, "החתימה עוד בתוך התנאי"

    co = code_only(fn_source(s, "_collapse_urls"))
    assert "_strip_stream_sig(v)" in co, "לא מסירים חתימה בשמירה"
    assert "_STREAM_PATH_RE.search(v)" in co, "ההסרה לא חלה על /vh"
    # ההסרה חייבת להיות מחוץ לתנאי על הבסיס
    assert co.index("_strip_stream_sig") > co.index("STREAM_PUBLIC_BASE in v")
    assert co.count("if ") >= 3, "התנאים התמזגו"

    # ── בדיקת התנהגות על הפונקציות שנכתבו ──────────────────────────────
    import re as _re
    import time as _time
    import hmac as _hmac
    import hashlib as _hashlib
    ns = {"time": _time, "hmac": _hmac, "hashlib": _hashlib, "re": _re,
          "SIGN_SECRET": "k" * 32, "SIGN_TTL": 86400,
          "BASE_TOKEN": "%BASE%",
          "STREAM_PUBLIC_BASE": "https://example.org",
          "_STREAM_PATH_RE": _re.compile(r"/(?:stream|vh)/(-?\d+)/(\d+)")}
    for f in ("_stream_sig", "_strip_stream_sig", "sign_stream_url",
              "_expand_urls", "_collapse_urls"):
        exec(fn_source(s, f), ns)
    expand, collapse = ns["_expand_urls"], ns["_collapse_urls"]
    now = _time.time()

    def exp_of(u):
        return int(u.split("exp=")[1].split("&")[0])

    # 1. כתובת מוחלטת עם חתימה שפגה — זה המקרה שהפיל את הקטלוג
    items = [{"video_url":
              "https://zovex.duckdns.org/stream/-100123/9250"
              "?exp=1&sig=deadbeef"}]
    got = expand(items)[0]["video_url"]
    assert exp_of(got) > now, f"כתובת מוחלטת לא נחתמה מחדש: {got}"
    assert "sig=deadbeef" not in got, "החתימה הישנה נשארה"

    # 2. placeholder ממשיך לעבוד כקודם
    got = expand([{"video_url": "%BASE%/stream/-1/2"}])[0]["video_url"]
    assert got.startswith("https://example.org/stream/-1/2?"), got
    assert exp_of(got) > now

    # 3. קישורים שאינם /stream לא נוגעים בהם
    for u in ("https://zovex.duckdns.org/hls-relay/h/live/5/chunks.m3u8",
              "https://cdn.example.com/poster.jpg", ""):
        assert expand([{"video_url": u}])[0]["video_url"] == u, u

    # 4. שדה שאינו מחרוזת לא מפיל
    assert expand([{"video_url": None}, {}])[0]["video_url"] is None

    # 5. שמירה מסירה חתימה — גם כשהבסיס אינו מתאים
    out = collapse([{"video_url":
                     "https://other-host.net/stream/-1/2?exp=9&sig=abc"}])
    assert "sig=" not in out[0]["video_url"], out[0]["video_url"]
    assert "exp=" not in out[0]["video_url"]

    # 6. שמירה עם הבסיס המתאים — גם מחליפה וגם מסירה
    out = collapse([{"video_url":
                     "https://example.org/stream/-1/2?exp=9&sig=abc"}])
    assert out[0]["video_url"] == "%BASE%/stream/-1/2", out[0]["video_url"]

    # 7. פרמטר אחר שורד את שני הכיוונים
    out = collapse([{"video_url":
                     "https://example.org/stream/-1/2?t=90&exp=9&sig=abc"}])
    assert "t=90" in out[0]["video_url"], out[0]["video_url"]

    # 8. הלוך-חזור: שמירה ואז הגשה נותנות חתימה תקפה אחת
    saved = collapse([{"video_url":
                       "https://example.org/stream/-5/7?exp=1&sig=old"}])
    served = expand(saved)[0]["video_url"]
    assert served.count("sig=") == 1 and exp_of(served) > now, served


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
    if "fix_stale_sig" not in s:
        print("❌ חסר fix_stale_sig — הרץ אותו קודם:")
        print("   python3 fix_stale_sig.py")
        return 1
    out = s
    for name, a, b in EDITS:
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
    print("שינוי: _expand_urls חותם כל קישור /stream ולא רק עם %BASE%")
    print("       _collapse_urls מסיר חתימה תמיד ולא רק כשהבסיס מתאים")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0
    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_stale_sig2"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_stale_sig2.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
