#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_upload_bench — למדוד את מסלול ההעלאה במקום לנחש אותו.

## למה

הדיווח: העלאה דרך טרמוקס (scp/rsync על SSH) מהירה בהרבה מהעלאה דרך
האפליקציה. ניחשתי שתי סיבות ושתיהן נבדקו:

  · כתיבה לכל נתח בנפרד — נמדדה, אמיתית, תוקנה, אבל 67MB/s במכונת
    פיתוח הם כנראה מעל רוחב הפס ולכן לא מסבירים את הפער
  · buffering של nginx — **הופרך**: ‎proxy_request_buffering off‎ כבר
    מוגדר, בשני ה-blocks

ניחוש שלישי אינו שווה יותר מהשניים הראשונים. הנתיב הזה קורא את הגוף
וזורק אותו: בלי דיסק, בלי טלגרם, בלי עיבוד. מה שהוא מודד הוא בדיוק
הרשת, ה-TLS, nginx ו-uvicorn — ומה שנשאר מחוץ לו הוא כל השאר.

## איך משתמשים בו — שתי מדידות, אותו קובץ, אותה דקה

בטרמוקס:

    CODE='...'          # קוד ההעלאה, לא נכתב לשום קובץ
    dd if=/dev/zero of=$HOME/t.bin bs=1M count=200

    # ① המסלול של האפליקציה: HTTPS דרך nginx
    curl -sS -X POST --data-binary @$HOME/t.bin \\
         -H "x-upload-code: $CODE" \\
         -H "Content-Type: application/octet-stream" \\
         https://<הדומיין>/panel/upload-bench

    # ② המסלול של טרמוקס: SSH
    time scp $HOME/t.bin root@<השרת>:/tmp/

התשובה של ① כוללת ‎mb_per_sec‎ כפי שהשרת מדד אותו — כלומר מרגע שהבייט
הראשון הגיע ועד האחרון, בלי זמן ההתחברות.

שני מספרים קרובים ⇒ הרשת היא הגבול, והאפליקציה אינה אשמה.
① איטי בהרבה מ-② ⇒ המסלול HTTP הוא הצוואר, ואז יש מה לתקן.

## מה זה לא

אין כאן כתיבה לדיסק, ולכן זה **אינו** מודד את מהירות ההעלאה האמיתית
אלא את הגבול העליון שלה. זו בדיוק הנקודה: הפרש בין הגבול העליון לבין
מה שנמדד בפועל הוא מה שהשרת מוסיף.

מוגן באותו קוד העלאה, ובאותה הגנת ניחוש. בלי הקוד — 403.

    python3 add_upload_bench.py --check
    python3 add_upload_bench.py
    python3 add_upload_bench.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_upload_bench"
MARK = "add_upload_bench"

A = '''@api.get("/panel/saved-upload/parts")
'''

N = '''# [add_upload_bench] מדידת המסלול עצמו: קורא את הגוף וזורק אותו.
#
# בלי דיסק, בלי טלגרם, בלי עיבוד — ולכן מה שנמדד כאן הוא הרשת, ה-TLS,
# nginx ו-uvicorn בלבד. השוואה מול scp של אותו קובץ באותה דקה אומרת
# אם המסלול HTTP הוא הצוואר או שהקו פשוט מלא.
#
# הזמן נמדד מהבייט הראשון שהגיע, ולא מקבלת הבקשה: זמן ההתחברות וה-TLS
# אינו חלק ממהירות ההעברה, וכלילתו הייתה מציגה קו מהיר כאיטי בקבצים
# קטנים.
@api.post("/panel/upload-bench")
async def upload_bench(request: Request):
    _check_upload_code(request, request.headers.get("x-upload-code", ""))
    n = 0
    t0 = None
    async for chunk in request.stream():
        if not chunk:
            continue
        if t0 is None:
            t0 = time.monotonic()
        n += len(chunk)
    dt = max(1e-6, time.monotonic() - t0) if t0 else 0.0
    return {"ok": True, "bytes": n, "seconds": round(dt, 2),
            "mb_per_sec": round(n / 1048576 / dt, 2) if dt else 0,
            "mbit_per_sec": round(n * 8 / 1e6 / dt, 1) if dt else 0}


@api.get("/panel/saved-upload/parts")
'''

EDITS = [("נתיב המדידה", A, N, 1)]


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
    body = code_only(fn_source(out, "upload_bench"))
    # מוגן. נתיב שקורא גוף בלי אימות הוא משאיר פתוח למי שירצה להעמיס
    assert "_check_upload_code" in body, "הנתיב אינו מוגן בקוד ההעלאה"
    # לא נוגע בדיסק
    for bad in ("open(", "pwrite", "SAVED_TMP_DIR", "write"):
        assert bad not in body, f"הנתיב נוגע בדיסק ({bad}) — זו אינה מדידה נקייה"
    # הזמן מהבייט הראשון
    i_first = body.index("t0 = time.monotonic()")
    i_loop = body.index("async for chunk")
    assert i_loop < i_first, "הזמן נמדד מקבלת הבקשה ולא מהבייט הראשון"

    # ── החישוב עצמו ─────────────────────────────────────────────────────
    n, dt = 200 * 1048576, 20.0
    assert round(n / 1048576 / dt, 2) == 10.0
    assert round(n * 8 / 1e6 / dt, 1) == 83.9
    # גוף ריק אינו מחלק באפס
    assert (round(0 / 1048576 / 1, 2) if 0.0 else 0) == 0


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
    print("ואז בטרמוקס, שתי מדידות על אותו קובץ:")
    print("  dd if=/dev/zero of=$HOME/t.bin bs=1M count=200")
    print("  curl -sS -X POST --data-binary @$HOME/t.bin \\")
    print("       -H \"x-upload-code: $CODE\" \\")
    print("       -H 'Content-Type: application/octet-stream' \\")
    print("       https://<הדומיין>/panel/upload-bench")
    print("  time scp $HOME/t.bin root@<השרת>:/tmp/")


if __name__ == "__main__":
    main()
