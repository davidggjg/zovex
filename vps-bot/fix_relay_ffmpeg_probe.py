#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_ffmpeg_probe — ffmpeg נחסם מהסימון שלנו, בשקט מוחלט.

## מה היומן אמר, ומה זה אומר באמת

    hls_fix: 6d0bbf6ce770183c נכשל בפרופיל 0 — ffmpeg קוד None

שתי עובדות בשורה אחת, ושתיהן חשובות:

    why = _hls_fix_err(ent) or f"ffmpeg קוד {ent['proc'].returncode}"

* ‎_hls_fix_err‎ ריקה ⇒ **ffmpeg לא כתב דבר ל-stderr**
* ‎returncode is None‎ ⇒ **ffmpeg עדיין רץ**

כלומר הוא לא קרס ולא התלונן. הוא ישב שקט ולא הוציא סגמנט, עד שהמועד
של 14 שניות עבר. וזה בדיוק מה ש-‎-reconnect_on_http_error 5xx‎ עושה:

    "-reconnect_on_http_error", "5xx",
    "-reconnect_delay_max", "10",

הוא מנסה שוב ושוב בשקט מול 5xx. לכן 502 חוזר נראה לו כמו "נסה עוד
פעם", לא כמו שגיאה — ואין מה לכתוב ל-stderr.

## ומאיפה ה-502

    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"

**הקלט של ffmpeg הוא המסלול הרגיל שלנו.** ‎fix_relay_probe_loop‎ נתן
אסימון לבדיקת החיות כדי שהיא לא תיחסם מהסימון שלנו — ופספסתי שיש כאן
צרכן שני בדיוק לאותו מסלול. ffmpeg אינו נושא אסימון, ולכן:

    ① ערוץ מסומן (משנייה אחת של תקלה, או משארית של הלולאה הקודמת)
    ② בדיקת החיות עוברת עכשיו — יש לה אסימון
    ③ ffmpeg פונה לאותו מסלול **בלי** אסימון  →  502
    ④ הוא מתחבר מחדש בשקט, בלי לכתוב כלום
    ⑤ 14 שניות  →  "ffmpeg קוד None"

התיקון הקודם פתח את הדלת לבודק ושכח את מי שנשלח לעבוד.

## מה משתנה

ffmpeg נושא את אותו אסימון, בכותרת HTTP. שתי שורות.

ובנוסף: כשה-stderr ריק ו-‎returncode‎ הוא ‎None‎, ההודעה אומרת עכשיו
מה קרה במקום להדפיס ‎None‎. "ffmpeg קוד None" עלה לי סבב שלם עד
שהבנתי שזה אומר "הוא חי ולא הוציא כלום".

    python3 fix_relay_ffmpeg_probe.py --check
    python3 fix_relay_ffmpeg_probe.py
    python3 fix_relay_ffmpeg_probe.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_ffmpeg_probe"
MARK = "fix_relay_ffmpeg_probe"

# ── 1. ffmpeg נושא את האסימון ─────────────────────────────────────────────
A_ARGS = '''            "-reconnect_delay_max", "10",
            "-fflags", "+genpts", "-i", src,
'''

N_ARGS = '''            "-reconnect_delay_max", "10",
            # [fix_relay_ffmpeg_probe] הקלט של ffmpeg הוא המסלול הרגיל
            # שלנו, ולכן גם הוא נחסם מסימון "לא עונה" — ומכיוון שהוא
            # מוגדר להתחבר מחדש על 5xx, הוא עשה את זה **בשקט מוחלט**:
            # בלי שורת stderr, בלי לצאת, עד שהמועד עבר. ביומן זה נראה
            # כ"ffmpeg קוד None", וזה הדבר הכי פחות מסביר שאפשר.
            #
            # הכותרת חייבת להופיע לפני ‎-i‎, כי היא חלה על הקלט.
            "-headers", f"x-zovex-probe: {HLS_PROBE_TOKEN}\\r\\n",
            "-fflags", "+genpts", "-i", src,
'''

# ── 2. הודעה שאומרת מה קרה ────────────────────────────────────────────────
A_WHY = '''        why = _hls_fix_err(ent) or f"ffmpeg קוד {ent['proc'].returncode}"
'''

N_WHY = '''        # [fix_relay_ffmpeg_probe] stderr ריק ותהליך חי אינם "קוד None".
        # הם אומרים דבר מדויק: ffmpeg לא התלונן ולא יצא, הוא פשוט לא
        # הוציא סגמנט בזמן — כמעט תמיד כי הקלט לא זורם.
        _rc = ent["proc"].returncode
        why = _hls_fix_err(ent) or (
            f"ffmpeg חי ולא הוציא סגמנט תוך {HLS_FIX_DEADLINE:.0f} שניות "
            f"(הקלט כנראה אינו זורם)" if _rc is None
            else f"ffmpeg יצא בקוד {_rc} בלי הודעה")
'''

EDITS = [
    ("האסימון ב-ffmpeg", A_ARGS, N_ARGS, 1),
    ("הודעת הכישלון", A_WHY, N_WHY, 1),
]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"לא נמצאה הפונקציה {name}")


def code_only(text: str) -> str:
    out = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    joined = "\n".join(out)
    parts = joined.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else joined


def validate(out: str) -> None:
    compile(out, "main.py", "exec")
    assert "fix_relay_probe_loop" in out, "הרץ קודם fix_relay_probe_loop"

    start = code_only(fn_source(out, "_hls_fix_start"))
    assert "HLS_PROBE_TOKEN" in start, "ffmpeg אינו נושא את האסימון"
    # הכותרת לפני ‎-i‎, אחרת היא חלה על הפלט ולא על הקלט
    i_hdr = start.index('"-headers"')
    i_in = start.index('"-i", src')
    assert i_hdr < i_in, "הכותרת אחרי ‎-i‎ — היא לא תחול על הקלט"
    # ו-‎src‎ הוא אכן המסלול המקומי, כלומר יש בכלל מה לעקוף
    assert "127.0.0.1" in start, "הקלט אינו המסלול המקומי"

    fixed = code_only(fn_source(out, "hls_relay_fixed"))
    assert "ffmpeg קוד" not in fixed, "ההודעה הישנה נשארה"
    assert "לא הוציא סגמנט" in fixed, "ההודעה אינה מסבירה"

    # ── ההודעה עצמה ─────────────────────────────────────────────────────
    ns = {"HLS_FIX_DEADLINE": 14.0}
    for rc, expect in ((None, "לא הוציא סגמנט"), (1, "יצא בקוד 1")):
        ns["_rc"] = rc
        exec('why = "" or (f"ffmpeg חי ולא הוציא סגמנט תוך '
             '{HLS_FIX_DEADLINE:.0f} שניות (הקלט כנראה אינו זורם)" '
             'if _rc is None else f"ffmpeg יצא בקוד {_rc} בלי הודעה")', ns)
        assert expect in ns["why"], (rc, ns["why"])
    # stderr אמיתי גובר על שניהם
    ns["_rc"] = None
    exec('why = "Server returned 404" or "x"', ns)
    assert ns["why"] == "Server returned 404", "stderr אמיתי נדרס"

    # ── והכותרת כפי שהיא נמסרת ל-ffmpeg ─────────────────────────────────
    tok = "a" * 32
    hdr = f"x-zovex-probe: {tok}\r\n"
    assert hdr.endswith("\r\n"), "כותרת בלי CRLF — ffmpeg שולח אותה שבורה"
    assert hdr.count(":") == 1 and " " in hdr


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit(f"אין קובץ ב-{PATH} (אפשר MAIN_PY=...)")
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — "
                     "לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
