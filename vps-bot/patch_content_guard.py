#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# קריאה אחת שנכשלה מחקה 25,084 פריטים.
#
# ## מה קרה, מתוארך לשנייה
#
#   content_1793557064.json  18:17  25,084 פריטים  31.6MB
#   content_1793557084.json  18:18       6 פריטים   3KB
#
# עשרים שניות. והמספר 6 הוא בדיוק מספר הפרקים בסדרה שהועלתה באותו רגע:
# הכותב קרא את הקטלוג, קיבל רשימה ריקה, הוסיף את ששת הפרקים, ושמר.
#
# ## השורש
#
#     except Exception:
#         _content_cache["data"] = None
#         return []
#
# ‎load_content‎ מחזיר רשימה ריקה על **כל** כשל קריאה — קריאה חלקית בזמן
# כתיבה מקבילה, תקלת דיסק רגעית, כל דבר. הקורא אינו יכול להבחין בין
# "הקטלוג ריק" ל"לא הצלחתי לקרוא", והכותב הבא שומר את הריק כמקור האמת.
#
# ## שתי שכבות
#
# 1. **‎load_content‎ נופל לגיבוי במקום לשקר.** לפני שהוא מוותר הוא מנסה
#    את שלושת הגיבויים האחרונים. רשימה ריקה מוחזרת רק כשבאמת אין כלום.
#
# 2. **‎save_content‎ מסרב לכיווץ דרמטי.** זו השכבה שחשובה יותר: היא
#    חוסמת את הנזק **בלי קשר לסיבה** — גם באג עתידי, גם סקריפט שגוי, גם
#    טעות אנוש. שמירה שמקטינה קטלוג של 100+ פריטים ביותר ממחצית נדחית
#    ונרשמת ברעש.
#
# מחיקה המונית אמיתית עדיין אפשרית דרך ‎CONTENT_ALLOW_SHRINK=1‎. מחיקת
# מחצית מ-25 אלף פריטים אינה פעולה שקורית בטעות, ולכן היא צריכה כוונה.
#
#   python3 patch_content_guard.py [נתיב ל-main.py]
#   python3 patch_content_guard.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "content_guard"

OLD_LOAD = '''        except Exception:
            _content_cache["key"] = None
            _content_cache["data"] = None
            return []
    return []'''
NEW_LOAD = '''        except Exception as e:
            # [content_guard] נפילה לגיבוי, לא שקר.
            #
            # החזרת [] כאן אומרת לקורא "הקטלוג ריק", והוא אינו יכול
            # להבחין בזה מ"לא הצלחתי לקרוא". הכותב הבא שמר את הריק
            # ודרס 25,084 פריטים — זה קרה, ולא בתיאוריה.
            _content_cache["key"] = None
            _content_cache["data"] = None
            log.error("load_content: קריאה נכשלה (%s: %s) — מנסה גיבוי",
                      type(e).__name__, e)
            try:
                baks = sorted(CONTENT_BAK_DIR.glob("content_*.json"),
                              reverse=True)[:3]
            except Exception:
                baks = []
            for b in baks:
                try:
                    data = json.loads(b.read_text(encoding="utf-8"))
                    if isinstance(data, list) and data:
                        log.warning("load_content: שוחזר מ-%s (%d פריטים)",
                                    b.name, len(data))
                        return list(data)
                except Exception:
                    continue
            log.critical("load_content: גם הגיבויים לא נקראו — מחזיר ריק")
            return []
    return []'''

OLD_SAVE = '''def save_content(arr: list):
    arr = _normalize_live_flag(arr)'''
NEW_SAVE = '''# [content_guard] כמה מותר לקטלוג להתכווץ בשמירה אחת.
#
# 0.5 = שמירה שמשאירה פחות ממחצית מהפריטים נדחית. מחיקה המונית אמיתית
# עדיין אפשרית עם CONTENT_ALLOW_SHRINK=1 — מחיקת מחצית מ-25 אלף פריטים
# אינה קורית בטעות, ולכן היא צריכה כוונה מפורשת.
CONTENT_SHRINK_GUARD = float(os.environ.get("CONTENT_SHRINK_GUARD", "0.5"))
CONTENT_SHRINK_MIN = int(os.environ.get("CONTENT_SHRINK_MIN", "100"))


class ContentShrinkRefused(RuntimeError):
    """שמירה נדחתה כי היא הייתה מוחקת את רוב הקטלוג."""


def save_content(arr: list):
    # [content_guard] השכבה שעוצרת את הנזק בלי קשר לסיבה.
    #
    # היא אינה מתקנת את הבאג שגרם לרשימה הריקה — היא מוודאת שגם הבאג
    # הבא, והסקריפט השגוי הבא, לא יוכלו למחוק קטלוג שלם בכתיבה אחת.
    if os.environ.get("CONTENT_ALLOW_SHRINK") != "1":
        try:
            if CONTENT_FILE.exists():
                cur = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
                if (isinstance(cur, list) and len(cur) >= CONTENT_SHRINK_MIN
                        and len(arr) < len(cur) * CONTENT_SHRINK_GUARD):
                    log.critical(
                        "🛑 save_content נדחתה: %d → %d פריטים. "
                        "הקטלוג לא נגע. להרשות במכוון: CONTENT_ALLOW_SHRINK=1",
                        len(cur), len(arr))
                    raise ContentShrinkRefused(
                        f"שמירה נדחתה: {len(cur)} → {len(arr)} פריטים")
        except ContentShrinkRefused:
            raise
        except Exception as e:
            # כשל בבדיקה עצמה אינו סיבה לחסום שמירה תקינה
            log.warning("content_guard: הבדיקה נכשלה (%s) — ממשיכים", e)
    arr = _normalize_live_flag(arr)'''

PAIRS = [(OLD_LOAD, NEW_LOAD), (OLD_SAVE, NEW_SAVE)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_cguard_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")
    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return
    for i, (old, _) in enumerate(PAIRS, 1):
        if s.count(old) != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} נמצא {s.count(old)} פעמים. "
                     f"לא נגעתי בכלום.")
    bak = f"{d}/main_before_cguard_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)
    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")
    print(f"✓ הוחל. גיבוי: {bak}")
    print("  load_content נופל לגיבוי · save_content דוחה כיווץ מעל 50%")


if __name__ == "__main__":
    main()
