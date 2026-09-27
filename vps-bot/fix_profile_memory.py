#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_profile_memory — הפרופיל שעובד נזכר על הדיסק, ונזרע מראש.

## הבאג, כפי שנמדד

שלושת הערוצים שניתבנו ל-‎_fix‎ אומתו כמייצרים פלט נגיש לגמרי:

    Hotril    IDR=30  slices=2000  fmo=1  1280x720
    HOTGOLD   IDR=30  slices=2000  fmo=1  1280x720
    5plus     IDR=30  slices=2000  fmo=1  1280x720

ובכל זאת, בחימום של שלוש בקשות רצופות:

    Hotril    000 200 200
    HOTGOLD   302 302 302      ← הפניה בכל שלוש
    5plus     200 200 200

‎HOTGOLD‎ מייצר זרם מושלם ומקבל הפניה בכל פעם. שתי סיבות שמצטרפות:

**1 · הבקשה משלמת על שני סבבי ffmpeg.** ערוץ שאין לו פרופיל זכור מתחיל
בפרופיל 0 (‎-c:v copy‎), ממתין עד 12 שניות לסגמנט, עובר אימות פלט
(‎timeout=25‎), נמצא בלי IDR, נהרג — ורק אז מתחיל פרופיל 1, ועוד עד 12
שניות. במקרה הגרוע זה כדקה, והנגן מתייבש לפני שהתשובה חוזרת. אז מוחזרת
הפניה, והצופה נשלח בחזרה למסלול שאינו נגיש לו.

**2 · סימון הכשל נדבק עד הפעלה מחדש.** ‎_hls_fix_profile[key] = None‎
נכתב כשובר-לולאה להפניה האוטומטית, ואין לו תוקף. ערוץ שנכשל פעם אחת
בגלל הזמן — מסומן, וההפניה האוטומטית מפסיקה לשלוח אליו לנצח.

ושני אלה מזינים זה את זה: הזיכרון של הפרופיל יושב בזיכרון התהליך, ולכן
כל הפעלה מחדש של השירות מאבדת אותו — וכל ערוץ משלם את המחיר מחדש.

## מה משתנה

* **הזיכרון עובר לדיסק** — ‎data/hls_fix_profile.json‎. פרופיל שנמצא
  פעם אחת נשמר, וכל הפעלה מחדש מתחילה ממה שכבר ידוע.
* **נזרע מראש** עבור עשרת ערוצי ה-open-GOP שנמדדו. הם ילכו ישר לקידוד
  המלא, בלי לשלם על סבב ההעתקה — כלומר **המחיר נעלם לגמרי** עבורם, ולא
  רק מוקטן.
* **לסימון הכשל יש תוקף** (‎HLS_FIX_FAIL_TTL‎, ברירת מחדל 10 דקות). ערוץ
  שנכשל ינסה שוב, ולא יישאר חסום עד restart.
* **האימות מקבל תקציב אמיתי** — ‎timeout=8‎ במקום 25. הוא רץ על שני
  קבצים מקומיים שאנחנו כתבנו; 25 שניות שם היו רק דרך לשרוף את חלון
  הבקשה כשמשהו נתקע.

## למה זה לא יכול לשבור משהו

* ערוץ בלי רשומה מתנהג בדיוק כמו היום.
* קובץ פגום או חסר נקרא כ"אין זיכרון" ולא מפיל כלום.
* כתיבה אטומית, ורק כשהערך באמת השתנה.
* הזריעה נוגעת **רק** בעשרת הסלאגים שנמדדו, ומחשבת את המפתח מהקטלוג
  באותה נוסחה בדיוק שהשרת משתמש בה — sha1 של ‎host/dir‎, 16 תווים.

    python3 fix_profile_memory.py --check
    python3 fix_profile_memory.py
    python3 fix_profile_memory.py --revert
"""
import ast
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_profile_memory"
MARK = "fix_profile_memory"
NEEDS = ("fix_live_robust", "fix_verify_output")

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
SEED = DATA / "hls_fix_profile.json"

# נמדדו כ-open-GOP עם h264_analyze.py: אפס IDR, פריימי I עם recovery
# point SEI, ו-frame_mbs_only=0. כולם צריכים קידוד מלא, כלומר פרופיל 1.
OPENGOP = ["hot-family-backup", "turkish-drama-3", "Torki2", "Dramottorki",
           "Hotspo", "Hotril", "HOT8", "hotfrns", "HOTGOLD", "5plus"]

A_DECL = '''_hls_fix_profile: dict = {}
'''

N_DECL = '''# [fix_profile_memory]
# הפרופיל שעובד לכל ערוץ, על הדיסק. קודם הוא ישב בזיכרון התהליך בלבד,
# ולכן כל הפעלה מחדש איבדה אותו וכל ערוץ שילם מחדש על סבב ההעתקה
# הכושל — עד דקה בבקשה הראשונה, שבה הנגן מתייבש ומקבל הפניה.
HLS_PROFILE_FILE = DATA_DIR / "hls_fix_profile.json"
# לסימון כשל יש תוקף. בלעדיו ערוץ שנכשל פעם אחת בגלל הזמן נשאר חסום
# להפניה האוטומטית עד restart.
HLS_FIX_FAIL_TTL = int(os.environ.get("HLS_FIX_FAIL_TTL", "600"))


def _load_fix_profiles() -> dict:
    """{key: profile} מהדיסק. קובץ חסר או פגום נקרא כ'אין זיכרון'."""
    try:
        raw = json.loads(HLS_PROFILE_FILE.read_text(encoding="utf-8"))
        out = {}
        for k, v in (raw or {}).items():
            if v is None or (isinstance(v, int) and v in (0, 1)):
                out[k] = v
        if out:
            log.info("hls_fix: נטענו %d פרופילים מהדיסק", len(out))
        return out
    except Exception:
        return {}


def _save_fix_profiles() -> None:
    """כתיבה אטומית. נקראת רק כשהערך באמת השתנה."""
    try:
        keep = {k: v for k, v in _hls_fix_profile.items() if v is not None}
        HLS_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HLS_PROFILE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
        tmp.replace(HLS_PROFILE_FILE)
    except Exception as e:
        log.warning("hls_fix: שמירת הפרופילים נכשלה — %s", e)


_hls_fix_profile: dict = {}
_hls_fix_failed_at: dict = {}      # key -> מתי סומן ככשל
'''

# ── הסימון מקבל תוקף ─────────────────────────────────────────────────────
A_MARKF = '''        _hls_fix_profile[key] = None
'''
N_MARKF = '''        # [fix_profile_memory] סימון עם חותמת זמן, כדי שיפוג.
        _hls_fix_profile[key] = None
        _hls_fix_failed_at[key] = time.time()
'''

A_WANT = '''    if _hls_fix_profile.get(key := _hls_fix_key(host, path), 0) is None:
        return False
'''
N_WANT = '''    key = _hls_fix_key(host, path)
    # [fix_profile_memory] הסימון פג אחרי HLS_FIX_FAIL_TTL.
    # קודם הוא היה נצחי: ערוץ שנכשל פעם אחת בגלל הזמן — ולא בגלל תקלה —
    # נשאר חסום להפניה האוטומטית עד להפעלה מחדש של השירות.
    if _hls_fix_profile.get(key, 0) is None:
        if time.time() - _hls_fix_failed_at.get(key, 0) < HLS_FIX_FAIL_TTL:
            return False
        _hls_fix_profile.pop(key, None)
        _hls_fix_failed_at.pop(key, None)
        log.info("hls_fix: סימון הכשל של %s פג — מנסים שוב", key)
'''

# ── שמירה כשנמצא פרופיל עובד ─────────────────────────────────────────────
A_SAVE = '''            if _hls_fix_profile.get(key) != profile:
                _hls_fix_profile[key] = profile
                log.info("hls_fix: %s עובד בפרופיל %s", key, profile)
'''
N_SAVE = '''            if _hls_fix_profile.get(key) != profile:
                _hls_fix_profile[key] = profile
                _hls_fix_failed_at.pop(key, None)
                # [fix_profile_memory] לדיסק, כדי שהפעלה מחדש לא תאבד
                # את זה והצופה הבא לא ישלם שוב על סבב ההעתקה.
                _save_fix_profiles()
                log.info("hls_fix: %s עובד בפרופיל %s", key, profile)
'''

# ── טעינה בעלייה ─────────────────────────────────────────────────────────
A_BOOT = '''async def _hls_fix_reaper():
'''
N_BOOT = '''# [fix_profile_memory] נטען פעם אחת בעלייה, לפני הבקשה הראשונה.
_hls_fix_profile.update(_load_fix_profiles())


async def _hls_fix_reaper():
'''

# ── האימות מקבל תקציב אמיתי ──────────────────────────────────────────────
A_TO = '''                capture_output=True, timeout=25)
'''
N_TO = '''                # [fix_profile_memory] 8 ולא 25: זה רץ על שני קבצים
                # מקומיים שאנחנו כתבנו, ולוקח פחות משנייה. 25 שניות היו
                # רק דרך לשרוף את חלון הבקשה כשמשהו נתקע.
                capture_output=True, timeout=8)
'''

EDITS = [("הצהרה וטעינה", A_DECL, N_DECL),
         ("חותמת זמן לכשל", A_MARKF, N_MARKF),
         ("תוקף לסימון", A_WANT, N_WANT),
         ("שמירה לדיסק", A_SAVE, N_SAVE),
         ("טעינה בעלייה", A_BOOT, N_BOOT),
         ("תקציב האימות", A_TO, N_TO)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def code_only(fn: str) -> str:
    """הקוד בלי תיעוד והערות. בלי זה בדיקה נתפסת על ההערה של עצמה —
    'HLS_FIX_FAIL_TTL' הופיע בהסבר לפני שהופיע בקוד, וזה הפיל אותה."""
    parts = fn.split('"""')
    body = parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_load_fix_profiles", "_save_fix_profiles",
              "_hls_autofix_wanted", "hls_relay_fixed", "_hls_out_has_idr"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    want = code_only(fn_source(s, "_hls_autofix_wanted"))
    assert "HLS_FIX_FAIL_TTL" in want, "לסימון אין תוקף"
    assert "_hls_fix_failed_at" in want, "אין חותמת זמן"
    # התוקף חייב לשבת **בתוך** ענף הסימון ולפני ניקויו, אחרת הוא חסר
    # משמעות. השוואה ל-return False הראשון הייתה שגויה: הראשון הוא
    # שומר HLS_AUTOFIX, ולגיטימית לפני הכל.
    assert want.index("is None") < want.index("HLS_FIX_FAIL_TTL"), \
        "התוקף נבדק מחוץ לענף הסימון"
    assert want.index("HLS_FIX_FAIL_TTL") < want.index("_hls_fix_profile.pop"), \
        "הסימון מנוקה לפני שנבדק אם פג"

    fx = code_only(fn_source(s, "hls_relay_fixed"))
    assert "_save_fix_profiles()" in fx, "הפרופיל אינו נשמר"
    assert "_hls_fix_failed_at[key] = time.time()" in fx, "הכשל בלי חותמת"

    v = code_only(fn_source(s, "_hls_out_has_idr"))
    assert "timeout=8" in v and "timeout=25" not in v, "התקציב לא הוקטן"

    # הטעינה חייבת להיות ברמת המודול, אחרי ההצהרה ולפני השימוש
    assert "_hls_fix_profile.update(_load_fix_profiles())" in s
    assert s.index("_hls_fix_profile: dict = {}") < \
        s.index("_hls_fix_profile.update(_load_fix_profiles())")

    # ── התנהגות ──────────────────────────────────────────────────────────
    import pathlib as _pl
    import tempfile
    import time as _t
    d = _pl.Path(tempfile.mkdtemp())
    ns = {"json": json, "pathlib": _pl, "os": os, "time": _t,
          "HLS_PROFILE_FILE": d / "p.json",
          "log": type("L", (), {"info": lambda *a: None,
                                "warning": lambda *a: None})()}
    exec(fn_source(s, "_load_fix_profiles"), ns)
    exec(fn_source(s, "_save_fix_profiles"), ns)
    load, save = ns["_load_fix_profiles"], ns["_save_fix_profiles"]

    # 1. אין קובץ — אין זיכרון, ולא נופל
    assert load() == {}
    # 2. שמירה וטעינה, ו-None אינו נשמר (הוא מצב רגעי ולא זיכרון)
    ns["_hls_fix_profile"] = {"a": 1, "b": 0, "c": None}
    save()
    got = load()
    assert got == {"a": 1, "b": 0}, got
    # 3. קובץ פגום — נקרא כ"אין זיכרון" ולא מפיל
    (d / "p.json").write_text("{ זה לא json", encoding="utf-8")
    assert load() == {}
    # 4. ערכים לא חוקיים מסוננים
    (d / "p.json").write_text(json.dumps({"a": 7, "b": "x", "c": 1}),
                              encoding="utf-8")
    assert load() == {"c": 1}, load()
    return True


def seed_keys() -> dict:
    """{key: 1} לעשרת ערוצי ה-open-GOP, לפי הקטלוג.

    המפתח מחושב באותה נוסחה בדיוק שהשרת משתמש בה — sha1 של
    ‎host/dir‎, 16 תווים ראשונים — ולכן זריעה כאן נקראת שם.
    """
    content = DATA / "content.json"
    if not content.exists():
        print(f"  ⚠ אין {content} — מדלג על הזריעה")
        return {}
    items = json.loads(content.read_text(encoding="utf-8"))
    live = {i.get("custom_slug"): i for i in items if i.get("is_live")}
    out, missing = {}, []
    for slug in OPENGOP:
        it = live.get(slug)
        if not it:
            missing.append(slug)
            continue
        p = urlparse(it.get("video_url") or "").path
        m = re.match(r"^/hls-relay/(?:_fix/)?([^/]+)/(.+)$", p)
        if not m:
            missing.append(slug)
            continue
        host, path = m.group(1), m.group(2)
        last = path.rsplit("/", 1)[-1]
        d = path.rsplit("/", 1)[0] if ("." in last and "/" in path) \
            else path.strip("/")
        key = hashlib.sha1(f"{host}/{d}".encode()).hexdigest()[:16]
        out[key] = 1
    if missing:
        print(f"  ⚠ לא נזרעו (אין בקטלוג): {', '.join(missing)}")
    return out


def main():
    if not os.path.exists(PATH):
        sys.exit(f"לא נמצא {PATH}")
    src = open(PATH, encoding="utf-8").read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        return

    if MARK in src:
        print("כבר מותקן.")
        return
    for dep in NEEDS:
        if dep not in src:
            sys.exit(f"✗ דורש {dep}, שאינו מוחל. לא נוגע בכלום.")

    out = src
    for label, a, n in EDITS:
        if out.count(a) != 1:
            sys.exit(f"✗ העוגן '{label}' נמצא {out.count(a)} פעמים — "
                     "לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")

    seed = seed_keys()
    if "--check" in sys.argv:
        print(f"--check: שום דבר לא נכתב. היו נזרעים {len(seed)} ערוצים.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")

    if seed:
        merged = {}
        if SEED.exists():
            try:
                merged = json.loads(SEED.read_text(encoding="utf-8")) or {}
            except Exception:
                merged = {}
        merged.update(seed)
        SEED.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEED.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SEED)
        print(f"✓ נזרעו {len(seed)} ערוצי open-GOP ל-{SEED}")
        print("  הם ילכו ישר לקידוד המלא — בלי לשלם על סבב ההעתקה הכושל.")
    print()
    print("אחרי ההפעלה מחדש, ביומן:")
    print("  hls_fix: נטענו N פרופילים מהדיסק")
    print()
    print("ואז הבקשה הראשונה ל-HOTGOLD אמורה להחזיר 200 ולא 302.")


if __name__ == "__main__":
    main()
