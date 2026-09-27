#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_edge_evict — פינוי מטמון שקובץ אחד שנעלם מבטל לגמרי.

## מה נמדד על השרת

    EDGE_CACHE_MAX  = 3GB   (ברירת המחדל בקוד)
    edge_cache בפועל = 22GB  — פי שבעה מהתקרה

והדיסק ב-86%: 80G מתוך 99G, 14G פנויים. דיסק מלא אינו "איטי" — הוא
כישלון של הכול בבת אחת: העלאות, ffmpeg, וכתיבה ל-sqlite.

## למה הפינוי לא עבד

    def _edge_evict():
        try:
            files = [(p.stat().st_atime, p.stat().st_size, p)
                     for p in EDGE_CACHE_DIR.glob("*.*")]
        except OSError:
            return

**‎return‎ אחד על כל הרשימה.** ‎glob‎ מחזיר שמות, ואחר כך ‎stat‎ נקרא על
כל אחד מהם בנפרד — ובין השניים הקובץ יכול להיעלם. זה לא תרחיש נדיר
אלא **מה שהקוד עצמו עושה בכל מילוי**:

    tmp.write_bytes(...)      # נוצר X.head.tmp
    tmp.replace(path)         # ונעלם באותו רגע
    _edge_evict()

שני מילויים במקביל — וזה המצב הרגיל כששני אנשים פותחים סרטים — ואחד
מהם עושה ‎glob‎ בדיוק כשהשני עושה ‎replace‎. ‎FileNotFoundError‎ הוא
‎OSError‎, ולכן **הפינוי כולו יוצא בלי למחוק דבר**, ובשקט: אין לוג.

כלומר: כמה שיותר צופים, כך הפינוי נכשל יותר, וכך המטמון גדל יותר.
בדיוק ההיפך ממה שצריך לקרות.

## מה משתנה

* ‎stat‎ עוטף כל קובץ בנפרד. קובץ שנעלם מדולג — הוא כבר לא תופס מקום.
* נסרקים **כל** הקבצים ולא רק ‎*.*‎, כולל ‎.tmp‎ שנשארו מהעבודה שנקטעה.
  ‎.tmp‎ ישן מחמש דקות נמחק תמיד: אין מילוי שנמשך כל כך.
* הפינוי נרשם ביומן. פינוי שקט הוא פינוי שאי אפשר לדעת שהוא לא קרה.
* התקרה נקראת מחדש בכל פינוי, כדי שאפשר יהיה להקטין אותה ב-.env
  בלי לחכות להפעלה מחדש.

## מה זה לא עושה

לא מוחק את 19 הג'יגה שכבר שם — פינוי רץ רק כשמישהו צופה במשהו חדש.
לזה יש ‎reclaim.sh‎, שגם מפנה וגם מראה מה תופס מקום.

    python3 fix_edge_evict.py --check
    python3 fix_edge_evict.py
    python3 fix_edge_evict.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_edge_evict"
MARK = "fix_edge_evict"

A_EVICT = '''def _edge_evict():
    """שומר על תקרת הגודל — מוחק את הקבצים שלא נגענו בהם הכי מזמן."""
    try:
        files = [(p.stat().st_atime, p.stat().st_size, p)
                 for p in EDGE_CACHE_DIR.glob("*.*")]
    except OSError:
        return
    total = sum(s for _, s, _ in files)
    for _atime, size, p in sorted(files):
        if total <= EDGE_CACHE_MAX:
            break
        try:
            p.unlink()
            total -= size
        except OSError:
            pass
'''

N_EVICT = '''def _edge_evict():
    """שומר על תקרת הגודל — מוחק את הקבצים שלא נגענו בהם הכי מזמן.

    [fix_edge_evict] ‎stat‎ לכל קובץ בנפרד, ולא רשימה אחת עם ‎except
    OSError: return‎ עליה. נמדד: המטמון הגיע ל-22GB מול תקרה של 3GB,
    כי ‎glob‎ מחזיר שמות ו-‎stat‎ נקרא אחר כך — ובין השניים ‎tmp.replace‎
    של מילוי מקביל מוחק את הקובץ. ‎FileNotFoundError‎ הוא ‎OSError‎,
    ולכן הפינוי כולו יצא בלי למחוק דבר. כמה שיותר צופים, כך זה קרה
    יותר.
    """
    cap = int(os.environ.get("STREAM_EDGE_CACHE_MAX", EDGE_CACHE_MAX))
    now = time.time()
    files, total, stale = [], 0, []
    try:
        listing = list(EDGE_CACHE_DIR.iterdir())
    except OSError:
        return
    for p in listing:
        try:
            st = p.stat()
        except OSError:
            continue                      # נעלם בדיוק עכשיו — לא תופס מקום
        if not p.is_file():
            continue
        # ‎.tmp‎ שנשאר מעבודה שנקטעה. מילוי אינו נמשך חמש דקות.
        if p.name.endswith(".tmp") and now - st.st_mtime > 300:
            stale.append(p)
            continue
        files.append((st.st_atime, st.st_size, p))
        total += st.st_size

    removed = 0
    freed = 0
    for p in stale:
        try:
            freed += p.stat().st_size
            p.unlink()
            removed += 1
        except OSError:
            pass

    for _atime, size, p in sorted(files):
        if total <= cap:
            break
        try:
            p.unlink()
        except OSError:
            continue
        total -= size
        freed += size
        removed += 1
    if removed:
        log.info("מטמון קצה: נמחקו %d קבצים (%.1fGB) — נשאר %.1fGB מתוך %.1fGB",
                 removed, freed / (1 << 30), total / (1 << 30), cap / (1 << 30))
'''

EDITS = [("פינוי מטמון הקצה", A_EVICT, N_EVICT)]


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
    body = code_only(fn_source(out, "_edge_evict"))
    assert "except OSError:\n            continue" in body, \
        "stat אינו עטוף לכל קובץ בנפרד"
    assert "iterdir()" in body, "עדיין סורק רק *.*"
    assert "log.info" in body, "הפינוי נשאר שקט"

    # הפונקציה מורצת בפועל על תיקייה אמיתית
    import tempfile
    import time as _t
    from pathlib import Path

    d = Path(tempfile.mkdtemp(prefix="edge_"))
    # עשרה קבצים של מגה, תקרה של 4 מגה ⇒ שישה צריכים להיעלם,
    # והישנים ביותר (atime קטן) הם שנמחקים
    for i in range(10):
        f = d / f"-100_{i}.tail"
        f.write_bytes(b"x" * (1 << 20))
        os.utime(f, (_t.time() - (10 - i) * 100, _t.time()))
    (d / "-100_9.head.tmp").write_bytes(b"x" * (1 << 20))
    os.utime(d / "-100_9.head.tmp", (_t.time() - 9999, _t.time() - 9999))
    (d / "fresh.tmp").write_bytes(b"x" * 10)        # חדש — לא נוגעים

    logs = []

    class _Log:
        def info(self, fmt, *a):
            logs.append(fmt % a)

    ns = {"os": os, "time": _t, "EDGE_CACHE_DIR": d,
          "EDGE_CACHE_MAX": 4 << 20, "log": _Log()}
    exec(fn_source(out, "_edge_evict"), ns)
    ns["_edge_evict"]()

    left = sorted(p.name for p in d.iterdir())
    total = sum(p.stat().st_size for p in d.iterdir() if p.is_file())
    assert total <= (4 << 20) + 32, f"לא ירד לתקרה: {total}"
    assert "-100_9.head.tmp" not in left, "‎.tmp‎ ישן לא נמחק"
    assert "fresh.tmp" in left, "‎.tmp‎ חדש נמחק — מילוי פעיל היה נשבר"
    assert "-100_0.tail" not in left, "הישן ביותר לא נמחק"
    assert "-100_9.tail" in left, "החדש ביותר נמחק"
    assert logs and "נמחקו" in logs[0], f"לא נרשם ביומן: {logs}"

    # קובץ שנעלם בין ההצגה ל-stat אינו מבטל את הפינוי כולו
    d2 = Path(tempfile.mkdtemp(prefix="edge2_"))
    for i in range(6):
        (d2 / f"-100_{i}.tail").write_bytes(b"x" * (1 << 20))

    real_iterdir = type(d2).iterdir
    ghost = d2 / "לא-קיים.tail"

    class _Dir:
        def __init__(self, p):
            self.p = p

        def iterdir(self):
            return list(real_iterdir(self.p)) + [ghost]

    ns2 = dict(ns)
    ns2["EDGE_CACHE_DIR"] = _Dir(d2)
    ns2["EDGE_CACHE_MAX"] = 2 << 20
    ns2["log"] = _Log()
    exec(fn_source(out, "_edge_evict"), ns2)
    ns2["_edge_evict"]()
    total2 = sum(p.stat().st_size for p in d2.iterdir())
    assert total2 <= (2 << 20) + 32, \
        f"קובץ שנעלם ביטל את הפינוי — זה הבאג עצמו ({total2})"

    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(d2, ignore_errors=True)


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
    for label, a, n in EDITS:
        if out.count(a) != 1:
            sys.exit(f"✗ העוגן '{label}' נמצא {out.count(a)} פעמים — "
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
    print("הפינוי יעבוד מעכשיו, אבל הוא רץ רק כשנשמר מטמון חדש.")
    print("לפנות את מה שכבר שם:")
    print("  bash reclaim.sh          # מראה מה יפונה, בלי למחוק")
    print("  bash reclaim.sh --yes    # מפנה")


if __name__ == "__main__":
    main()
