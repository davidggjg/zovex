#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_probe_loop — ערוץ שנפל פעם אחת לא קם לעולם. הבאג שלי.

## הדיווח

    shaka 1002 [".../hls-relay/_fix/<ספק>/live/330/chunks.m3u8"]
    hls networkError/manifestLoadError

וכל הערוצים החיים, לא אחד. מיד אחרי שהוחל ‎fix_relay_dead_check‎.

## הלולאה

‎fix_relay_dead_check‎ הוסיף למסלול הרגיל בדיקה של הסימון:

    _dead = _hls_dead_reason(_hls_fix_key(host, path))
    if _dead:
        raise HTTPException(502, f"hls_relay: {_dead}")

וזה נכון בפני עצמו. מה שפספסתי הוא **מי עוד קורא למסלול הרגיל**:

    async def _hls_upstream_alive(host, path):
        src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"

הבדיקה שקובעת אם הערוץ חי עוברת דרך אותו מסלול בדיוק. ומכאן:

    ① ערוץ נכשל פעם אחת  →  מסומן ל-45 שניות
    ② בקשה ל-_fix        →  מריצה בדיקת חיות
    ③ הבדיקה פונה למסלול הרגיל  →  הוא רואה את הסימון ומחזיר 502
    ④ הבדיקה מדווחת "המקור החזיר 502"
    ⑤ _fix מסמן שוב  →  **הטיימר מתאפס ל-45 שניות**
    ⑥ חזרה ל-②

הסימון מאשש את עצמו. כל ניסיון צפייה מאריך אותו בעוד 45 שניות, ולכן
ערוץ שנפל פעם אחת אינו קם כל עוד מישהו מנסה לצפות בו — והטלוויזיה
מנסה כל הזמן. זה מסביר למה **הכל** נפל ולא ערוץ אחד.

הבדיקה נועדה למדוד את המקור. היא מדדה את הדעה שלנו על המקור.

## התיקון

הבדיקה חייבת לראות את המקור, לא את המטמון שלנו. היא נושאת עכשיו אסימון
שנוצר בעלייה, והמסלול הרגיל מדלג על הסימון כשהוא מגיע — ורק אז.

אסימון ולא כותרת קבועה: דילוג על הסימון פירושו לשלם שוב שש שניות
המתנה למקור מת, ולכן מי שמבחוץ לא אמור להיות מסוגל לבקש אותו.

**ורשת ביטחון שנייה:** בדיקה שמצליחה מוחקת את הסימון. עד עכשיו לא היה
שום מסלול שמסיר סימון מלבד פקיעתו, כלומר "הספק חזר" לא היה עובדה
שהמערכת יכולה לגלות — רק להמתין לה.

    python3 fix_relay_probe_loop.py --check
    python3 fix_relay_probe_loop.py
    python3 fix_relay_probe_loop.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_relay_probe_loop"
MARK = "fix_relay_probe_loop"

# ── 1. אסימון לבדיקה, ומחיקת סימון כשהמקור חוזר ───────────────────────────
A_PROBE = '''    if _hls_relay_client is None:
        return True, ""              # לפני האתחול אין מה לבדוק
    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"
    try:
        r = await _hls_relay_client.get(src, timeout=HLS_UP_PROBE_TIMEOUT)
    except Exception as e:
        return False, (f"המקור לא ענה תוך {HLS_UP_PROBE_TIMEOUT:.0f} שניות "
                       f"({type(e).__name__})")
    if r.status_code != 200:
        return False, f"המקור החזיר {r.status_code}"
    if _hls_manifest_entries(r.text) == 0:
        return False, "playlist ריק מהמקור"
    return True, ""
'''

N_PROBE = '''    if _hls_relay_client is None:
        return True, ""              # לפני האתחול אין מה לבדוק
    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"
    try:
        # [fix_relay_probe_loop] הבדיקה נושאת אסימון שמדלג על הסימון.
        # בלעדיו היא פנתה למסלול הרגיל, קיבלה ממנו את ה-502 שנובע
        # מהסימון שלנו עצמו, והסיקה "המקור לא עונה" — כלומר איששה את
        # מה שהיא נשלחה לבדוק, והאריכה אותו בעוד 45 שניות בכל ניסיון.
        r = await _hls_relay_client.get(
            src, timeout=HLS_UP_PROBE_TIMEOUT,
            headers={"x-zovex-probe": HLS_PROBE_TOKEN})
    except Exception as e:
        return False, (f"המקור לא ענה תוך {HLS_UP_PROBE_TIMEOUT:.0f} שניות "
                       f"({type(e).__name__})")
    if r.status_code != 200:
        return False, f"המקור החזיר {r.status_code}"
    if _hls_manifest_entries(r.text) == 0:
        return False, "playlist ריק מהמקור"
    # [fix_relay_probe_loop] המקור עונה — הסימון יורד עכשיו ולא בעוד
    # 45 שניות. עד כה לא היה שום מסלול שמסיר סימון מלבד פקיעתו, כלומר
    # "הספק חזר" לא היה משהו שהמערכת יכולה לגלות, רק להמתין לו.
    _hls_dead.pop(_hls_fix_key(host, path), None)
    return True, ""
'''

# ── 2. האסימון עצמו ───────────────────────────────────────────────────────
A_TOKEN = '''HLS_DEAD_TTL = float(os.environ.get("HLS_DEAD_TTL", "45"))
'''

N_TOKEN = '''HLS_DEAD_TTL = float(os.environ.get("HLS_DEAD_TTL", "45"))
# [fix_relay_probe_loop] אסימון פנימי לבדיקת החיות. מי שנושא אותו מדלג
# על סימון "לא עונה" — כי הוא זה שנשלח לבדוק אם הסימון עדיין נכון.
#
# אסימון ולא כותרת קבועה: דילוג פירושו לשלם שוב שש שניות המתנה למקור
# מת, ולקוח חיצוני לא אמור להיות מסוגל לבקש את זה. נוצר בעלייה ומת
# איתה, ולכן אינו צריך להישמר בשום מקום.
HLS_PROBE_TOKEN = __import__("secrets").token_hex(16)
'''

# ── 3. המסלול הרגיל מכבד את האסימון ───────────────────────────────────────
A_CHECK = '''        _dead = _hls_dead_reason(_hls_fix_key(host, path))
        if _dead:
            raise HTTPException(502, f"hls_relay: {_dead}")
'''

N_CHECK = '''        # [fix_relay_probe_loop] בדיקת החיות עוברת דרך המסלול הזה, ולכן
        # היא חייבת לראות את המקור ולא את הדעה שלנו עליו. בלי הדילוג
        # הזה הסימון אישש את עצמו בלולאה, וערוץ שנפל פעם אחת לא קם כל
        # עוד מישהו ניסה לצפות בו.
        if request.headers.get("x-zovex-probe") != HLS_PROBE_TOKEN:
            _dead = _hls_dead_reason(_hls_fix_key(host, path))
            if _dead:
                raise HTTPException(502, f"hls_relay: {_dead}")
'''

EDITS = [
    ("אסימון הבדיקה", A_TOKEN, N_TOKEN, 1),
    ("הבדיקה נושאת אסימון", A_PROBE, N_PROBE, 1),
    ("המסלול הרגיל מדלג", A_CHECK, N_CHECK, 1),
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
    assert "fix_relay_dead_check" in out, "הרץ קודם fix_relay_dead_check"

    probe = code_only(fn_source(out, "_hls_upstream_alive"))
    assert "HLS_PROBE_TOKEN" in probe, "הבדיקה אינה נושאת אסימון"
    assert "_hls_dead.pop" in probe, "בדיקה שמצליחה אינה מוחקת את הסימון"
    # המחיקה אחרי כל הבדיקות, ולא לפניהן
    i_empty = probe.index("playlist ריק")
    i_pop = probe.index("_hls_dead.pop")
    assert i_pop > i_empty, "הסימון נמחק לפני שהתשובה אומתה"

    plain = code_only(fn_source(out, "hls_relay"))
    assert "x-zovex-probe" in plain, "המסלול הרגיל אינו מכבד את האסימון"
    # הסימון עדיין נבדק — רק לא עבור הבדיקה עצמה
    assert "_hls_dead_reason" in plain, "בדיקת הסימון נעלמה לגמרי"
    i_hdr = plain.index("x-zovex-probe")
    i_dead = plain.index("_hls_dead_reason")
    assert i_hdr < i_dead, "הדילוג אינו עוטף את הבדיקה"

    # מסלול ההמרה לא נגעתי בו, והבדיקה שלו נשארת
    fixed = code_only(fn_source(out, "hls_relay_fixed"))
    assert "_hls_dead_reason" in fixed, "מסלול ההמרה איבד את הבדיקה"

    # ── ההתנהגות, ולא רק המחרוזות ───────────────────────────────────────
    ns = {}
    exec("import secrets\nHLS_PROBE_TOKEN = secrets.token_hex(16)", ns)
    tok = ns["HLS_PROBE_TOKEN"]
    assert len(tok) == 32 and tok != ns["secrets"].token_hex(16), \
        "האסימון אינו אקראי"

    # הלולאה עצמה: מדמים את שרשרת הסימון
    dead = {}

    def reason(k):
        return dead.get(k)

    def mark(k):
        dead[k] = "המקור החזיר 502"

    def plain_route(k, probe_hdr, upstream_ok):
        if probe_hdr != tok:
            if reason(k):
                return 502
        return 200 if upstream_ok else 599

    def alive(k, upstream_ok, with_token):
        st = plain_route(k, tok if with_token else "", upstream_ok)
        if st != 200:
            return False
        dead.pop(k, None)
        return True

    # ① בלי אסימון, מקור שחזר לעבוד: הלולאה — נשאר מת לנצח
    dead.clear(); mark("c")
    for _ in range(5):
        if not alive("c", True, with_token=False):
            mark("c")
    assert "c" in dead, "הלולאה לא שוחזרה — הבדיקה חסרת ערך"

    # ② עם אסימון, אותו מקור: קם בניסיון הראשון
    dead.clear(); mark("c")
    assert alive("c", True, with_token=True), "האסימון לא פתח את הבדיקה"
    assert "c" not in dead, "הסימון לא הוסר אחרי בדיקה מוצלחת"

    # ③ מקור שבאמת מת: נשאר מסומן, וזה הרצוי
    dead.clear(); mark("c")
    assert not alive("c", False, with_token=True)
    mark("c")
    assert "c" in dead, "מקור מת חייב להישאר מסומן"


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
    print("ההפעלה מחדש גם מרוקנת את כל הסימונים הקיימים, ולכן ערוצים")
    print("שנתקעו בלולאה יחזרו מיד.")


if __name__ == "__main__":
    main()
