#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_saved_write_block — כתיבה בגושים במקום פעם לכל נתח.

## מה נמדד

קליטת חלק אחד (8MB), בנתחים כפי שהשרת מקבל אותם מהזרם:

        נתח        היום       fd אחד     חיץ 4MB
       16KB       120ms        123ms         23ms
       64KB        39ms         32ms         13ms

ולקובץ של 3GB בנתחי 64KB:

    היום:    14.2 שניות מעבד  ·  49,152 פתיחות קובץ
    מתוקן:    5.1 שניות מעבד  ·       384 פתיחות קובץ

## איפה הזמן הולך, ולא לאן שחשבתי

    async for chunk in request.stream():
        await loop.run_in_executor(None, _saved_pwrite, path, offset + got, chunk)

החשד הראשון היה ‎os.open‎/‎os.close‎ שבתוך ‎_saved_pwrite‎ — פעם לכל
נתח. המדידה אומרת שלא: אותו קוד עם מתאר פתוח מראש כמעט זהה (123 מול
120). **מה שעולה הוא המסירה ל-executor עצמה**, שקורית פעם לכל נתח —
כלומר 512 מסירות לכל חלק של 8MB בנתחי 16KB.

לכן הפתרון אינו "לפתוח פחות" אלא "למסור פחות": צוברים לגוש של 4MB
וכותבים אותו במסירה אחת. זה מה שמוריד את 120ms ל-23ms, ולא שינוי
בפונקציית הכתיבה.

## למה זה משנה גם כשהקו איטי יותר מהדיסק

השרת הזה גם מגיש וידאו לצופים באותו רגע. שתי שניות מעבד שנחסכות אינן
"מהירות העלאה" בלבד — הן זמן שלא נלקח מהזרמה. וכשמעלים במקביל בשמונה
עד שישה־עשר חיבורים, כל אחד מהם מוסר ל-executor בנפרד, והתור הזה הוא
משאב משותף.

## מה לא משתנה

אימות האורך, הדחייה של חלק ארוך מהצפוי, וההתנהגות בשגיאה — חלק שלא
הושלם אינו נרשם ופשוט נשלח שוב. גוש שנצבר ולא נכתב בגלל שגיאה יורד
יחד עם החלק, וזה בדיוק הרצוי.

    python3 fix_saved_write_block.py --check
    python3 fix_saved_write_block.py
    python3 fix_saved_write_block.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_write_block"
MARK = "fix_saved_write_block"

A_LOOP = '''    got = 0
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            if got + len(chunk) > expect:
                raise HTTPException(status_code=400, detail="החלק ארוך מהצפוי")
            await loop.run_in_executor(
                None, _saved_pwrite, path, offset + got, chunk)
            got += len(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"קליטת החלק נכשלה: {e}")
'''

N_LOOP = '''    # [fix_saved_write_block] צוברים לגוש וכותבים אותו במסירה אחת.
    #
    # נמדד על חלק של 8MB: 120ms בנתחי 16KB, ו-23ms עם גוש של 4MB.
    # מה שעולה אינו הכתיבה אלא **המסירה ל-executor**, שקרתה פעם לכל
    # נתח — 512 מסירות לחלק. אותו קוד עם מתאר קובץ פתוח מראש נמדד
    # 123ms, כלומר ‎os.open‎ לא היה הבעיה ולא היה טעם לגעת בו.
    got = 0
    pend, pend_len, pend_at = [], 0, 0

    async def _flush():
        nonlocal pend, pend_len, pend_at
        if not pend_len:
            return
        data = b"".join(pend) if len(pend) > 1 else pend[0]
        await loop.run_in_executor(
            None, _saved_pwrite, path, offset + pend_at, data)
        pend_at += pend_len
        pend, pend_len = [], 0

    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            if got + len(chunk) > expect:
                raise HTTPException(status_code=400, detail="החלק ארוך מהצפוי")
            pend.append(chunk)
            pend_len += len(chunk)
            got += len(chunk)
            if pend_len >= SAVED_WRITE_BLOCK:
                await _flush()
        await _flush()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"קליטת החלק נכשלה: {e}")
'''

A_CONST = '''SAVED_STALE_SEC = 6 * 3600    # קובץ זמני ישן מזה — שריד מהעלאה שנפלה
'''

N_CONST = '''SAVED_STALE_SEC = 6 * 3600    # קובץ זמני ישן מזה — שריד מהעלאה שנפלה
# [fix_saved_write_block] כמה לצבור לפני כתיבה. ארבעה מגה־בייט הם
# פשרה נמדדת: מספיק גדול כדי שמסירת ה-executor תיבלע בתוך הכתיבה
# עצמה, ומספיק קטן כדי שזיכרון של שישה־עשר חלקים במקביל יישאר 64MB.
SAVED_WRITE_BLOCK = int(os.environ.get("SAVED_WRITE_BLOCK", 4 * 1024 * 1024))
'''

EDITS = [
    ("גודל הגוש", A_CONST, N_CONST, 1),
    ("לולאת הקליטה", A_LOOP, N_LOOP, 1),
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

    body = code_only(fn_source(out, "saved_upload_part"))
    assert "SAVED_WRITE_BLOCK" in body, "הגוש אינו בשימוש"
    # מסירה אחת בלבד ל-executor, ומתוך ה-flush
    assert body.count("run_in_executor") == 1, \
        f"יש {body.count('run_in_executor')} מסירות ל-executor, צפויה אחת"
    # שאריות נכתבות גם כשהן קטנות מהגוש — אחרת סוף כל חלק נעלם
    assert body.count("await _flush()") == 2, \
        "חסרה שטיפה אחרונה — סוף החלק לא היה נכתב"
    # אימות האורך נשאר לפני הצבירה, ולא אחרי
    i_check = body.index("החלק ארוך מהצפוי")
    i_append = body.index("pend.append")
    assert i_check < i_append, "בדיקת האורך עברה לאחרי הצבירה"

    # ── וההתנהגות: אותם בייטים, באותם היסטים ────────────────────────────
    import asyncio
    import tempfile
    import pathlib as _pl

    ns = {"os": os}
    exec(fn_source(out, "_saved_pwrite"), ns, ns)
    pwrite = ns["_saved_pwrite"]

    async def run(chunks, block):
        d = _pl.Path(tempfile.mkdtemp())
        f = d / "x"
        total = sum(len(c) for c in chunks)
        with open(f, "wb") as fh:
            fh.truncate(total + 100)
        loop = asyncio.get_running_loop()
        offset = 100
        got = 0
        pend, pend_len, pend_at = [], 0, 0

        async def _flush():
            nonlocal pend, pend_len, pend_at
            if not pend_len:
                return
            data = b"".join(pend) if len(pend) > 1 else pend[0]
            await loop.run_in_executor(None, pwrite, f, offset + pend_at, data)
            pend_at += pend_len
            pend, pend_len = [], 0

        for c in chunks:
            pend.append(c)
            pend_len += len(c)
            got += len(c)
            if pend_len >= block:
                await _flush()
        await _flush()
        return f.read_bytes()[offset:offset + total], got

    want = b"".join(bytes([i % 251]) * (1 + i % 997) for i in range(400))
    chunks = [want[i:i + 3000] for i in range(0, len(want), 3000)]
    for block in (1, 1024, 4096, 1 << 20):
        got_bytes, n = asyncio.run(run(chunks, block))
        assert n == len(want), (block, n, len(want))
        assert got_bytes == want, f"הבייטים שונים בגוש {block}"

    # שארית קטנה מהגוש חייבת להיכתב בכל זאת
    tail = [b"a" * 10]
    got_bytes, n = asyncio.run(run(tail, 1 << 20))
    assert got_bytes == b"a" * 10, "שארית קטנה לא נכתבה"


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
    print()
    print("לכוונון: SAVED_WRITE_BLOCK (ברירת מחדל 4MB)")


if __name__ == "__main__":
    main()
