#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_live_autofix — הערוץ מתקן את עצמו, והקישור נשאר אותו קישור.

## הבקשה

"אולי יש משהו קטנצ'יק ולא מזיק בכלל שרץ על השרת וגורם לזה לעבוד חלק,
והקישור נשאר אותו קישור, ככה לא נעדכן את האפליקציה."

זה בדיוק מה שאפשר לעשות, ושתי הבעיות שחסמו את זה נמדדו ולא שוערו.

## מה חסם

**1 · ‎_fix‎ דחה כל ערוץ שיושב על פורט לא-רגיל.** נמדד על השרת החי:

    /hls-relay/tv-provider:7070/.../playlist.m3u8        →  200
    /hls-relay/_fix/tv-provider:7070/.../playlist.m3u8   →  403

המסלול הרגיל מפצל ‎host.partition(":")‎ ובודק את ההרשאה מול שם המארח
בלבד; ‎_fix‎ בדק ‎host not in HLS_RELAY_ALLOWED_HOSTS‎ על המחרוזת כולה.
‎HLS_RELAY_ALLOWED_HOSTS‎ הוא מילון של שמות בלי פורטים, ולכן כל ערוץ
עם פורט מפורש קיבל 403 — וספורט 5 פלוס יושב על 7070. כלומר גם הפניה
אליו הייתה נכשלת, ולא היה אפשר לדעת את זה בלי לבדוק.

**2 · לא היה מי שיפנה.** הערוץ שמור בקטלוג בכתובת של המסלול הרגיל, ורק
מי שיודע שהזרם הוא open-GOP יכול לדעת שצריך המרה. הידיעה הזאת קיימת
בשרת — ‎_hls_no_idr‎ מ-fix_live_opengop — אבל אף אחד לא שאל אותה במסלול
הרגיל.

## מה משתנה

הבקשה ל-playlist במסלול הרגיל שואלת את המטמון האם הערוץ הזה חסר IDR.
אם כן — ‎307‎ אל אותו ערוץ ב-‎_fix‎. הנגן עוקב אחרי ההפניה בעצמו, ולכן
**הכתובת בקטלוג, באתר ובאפליקציה נשארת בדיוק כפי שהיא.** אין מה לעדכן.

ו-‎_fix‎ מקבל עכשיו פורט מפורש, כמו המסלול הרגיל. ההרשאה עדיין נבדקת
מול שם המארח בלבד, ולכן זה אינו פותח שום מארח חדש.

## למה זה "קטנצ'יק ולא מזיק"

* **הצופה הראשון לא משלם כלום.** אם אין תשובה במטמון, הבדיקה נשלחת
  לרקע והבקשה נענית **בדיוק כמו היום**. אין שום המתנה חדשה בשום מסלול.
  מהצופה הבא — הערוץ כבר מופנה לבד.
* **ערוץ תקין לא נוגע בזה.** 21 מ-22 הערוצים שנדגמו מחזירים IDR, והם
  ממשיכים בדיוק במסלול הרגיל. ההפניה חלה רק על מי שבאמת חסר IDR.
* **אין לולאה, ובאופן מוכח ולא בתקווה.** כש-‎_fix‎ נכשל בכל הפרופילים
  הוא מסמן את הערוץ ב-‎_hls_fix_profile[key] = None‎, וההפניה בודקת את
  הסימן הזה. ערוץ שנכשל אינו מופנה שוב, ולכן ההפניה אינה יכולה לחזור
  אל עצמה. לפני השינוי השורה הזאת הייתה ‎pop‎ — כלומר הסימן נמחק,
  וההפניה הייתה נשלחת שוב בבקשה הבאה. זו הייתה לולאה.
* **כיבוי מיידי בלי פאץ':** ‎HLS_AUTOFIX=0‎ בסביבה מחזיר את ההתנהגות
  הקודמת בדיוק.
* **רק playlist מופנה**, לא מקטעים: ה-playlist ש-‎_fix‎ מחזיר מצביע
  ממילא למקטעים שלו.

## התלות

דורש ‎fix_live_opengop‎ (‎_hls_no_idr‎, ‎_hls_idr_cache‎) ו-‎fix_live_robust‎
(‎_hls_fix_profile‎, ‎RedirectResponse‎). הסקריפט מסרב לרוץ בלעדיהם.

    python3 fix_live_autofix.py --check
    python3 fix_live_autofix.py
    python3 fix_live_autofix.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_live_autofix"
MARK = "fix_live_autofix"
NEEDS = ("fix_live_opengop", "fix_live_robust")

# ── 1 · _fix מקבל פורט מפורש ─────────────────────────────────────────────
A_HOST = '''    if host not in HLS_RELAY_ALLOWED_HOSTS:
        raise HTTPException(403, "host not allowed")
'''
N_HOST = '''    # [fix_live_autofix] host יכול לכלול פורט מפורש, בדיוק כמו במסלול
    # הרגיל: ‎/hls-relay/<host>:7070/...‎. כאן נבדקה המחרוזת כולה מול
    # HLS_RELAY_ALLOWED_HOSTS, שהוא מילון של שמות בלי פורטים — ולכן כל
    # ערוץ עם פורט מפורש קיבל 403. נמדד על השרת החי: אותו ערוץ החזיר
    # 200 במסלול הרגיל ו-403 כאן. ההרשאה עדיין נבדקת מול שם המארח בלבד,
    # ולכן זה אינו פותח שום מארח חדש.
    if host.partition(":")[0] not in HLS_RELAY_ALLOWED_HOSTS:
        raise HTTPException(403, "host not allowed")
'''

# ── 2 · כשל מוחלט מסמן ולא מוחק ──────────────────────────────────────────
A_MARK = '''        _hls_fix_profile.pop(key, None)
'''
N_MARK = '''        # [fix_live_autofix] סימון ולא מחיקה.
        # ההפניה האוטומטית מהמסלול הרגיל בודקת את הסימן הזה. pop היה
        # מוחק אותו, וההפניה הייתה נשלחת שוב בבקשה הבאה — כלומר לולאה.
        _hls_fix_profile[key] = None
'''

A_FIRST = '''    first = _hls_fix_profile.get(key, 0)
'''
N_FIRST = '''    # [fix_live_autofix] None (כשל מוחלט) נקרא כ-0, כדי שניסיון ישיר
    # ב-_fix ימשיך לנסות להתאושש ולא יקבל פרופיל None.
    first = _hls_fix_profile.get(key) or 0
'''

# ── 3 · ההפניה עצמה ──────────────────────────────────────────────────────
A_MAN = '''    if _is_hls_manifest(path):
'''
N_MAN = '''    if _is_hls_manifest(path):
        # [fix_live_autofix] ערוץ בלי IDR מופנה אל _fix, והקישור שבקטלוג
        # נשאר כפי שהוא — הנגן עוקב אחרי ההפניה בעצמו.
        _fix_host = f"{base_host}:{explicit_port}" if explicit_port.isdigit() \\
            else base_host
        if _hls_autofix_wanted(_fix_host, path):
            return RedirectResponse(f"/hls-relay/_fix/{_fix_host}/{path}",
                                    status_code=307)
'''

# ── 4 · הלוגיקה ──────────────────────────────────────────────────────────
A_HELPER = '''def _is_hls_manifest(path: str) -> bool:
    return path.endswith(".m3u8")
'''
N_HELPER = '''def _is_hls_manifest(path: str) -> bool:
    return path.endswith(".m3u8")


# [fix_live_autofix]
# כיבוי בסביבה, בלי פאץ' ובלי הפעלה מחדש של שום דבר אחר.
HLS_AUTOFIX = os.environ.get("HLS_AUTOFIX", "1") not in ("0", "false", "no")
_hls_idr_probing: set = set()


def _hls_idr_probe_bg(host: str, path: str) -> None:
    """שולח את בדיקת ה-IDR לרקע ומחזיר מיד.

    זה מה שהופך את זה ל"לא מזיק": הבדיקה מריצה ffmpeg על שמונה שניות
    של זרם, וקריאה לה מתוך הבקשה הייתה מוסיפה את ההמתנה הזאת לצופה
    הראשון של כל ערוץ. כאן הבקשה נענית בדיוק כמו היום, והתשובה מגיעה
    למטמון בינתיים — מהצופה הבא הערוץ מופנה לבד.
    """
    key = f"{host}/{path}"
    if key in _hls_idr_probing:
        return
    _hls_idr_probing.add(key)
    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"

    async def _run():
        try:
            await _hls_no_idr(host, path, src)
        except Exception as e:
            log.warning("autofix: בדיקת IDR נכשלה על %s - %s", key, e)
        finally:
            _hls_idr_probing.discard(key)

    try:
        asyncio.ensure_future(_run())
    except Exception:
        _hls_idr_probing.discard(key)


def _hls_autofix_wanted(host: str, path: str) -> bool:
    """האם להפנות את הערוץ הזה אל _fix.

    מחזיר True רק כשיש **תשובה במטמון** שאומרת שאין IDR. בלי תשובה
    מחזיר False ושולח בדיקה לרקע, ולכן אף בקשה אינה מחכה בגלל זה.
    """
    if not HLS_AUTOFIX:
        return False
    # ערוץ ש-_fix כבר נכשל עליו בכל הפרופילים מסומן ב-None. בלי הבדיקה
    # הזאת ההפניה הייתה חוזרת אל עצמה: _fix מפנה בחזרה למסלול הרגיל.
    if _hls_fix_profile.get(key := _hls_fix_key(host, path), 0) is None:
        return False
    ent = _hls_idr_cache.get(f"{host}/{path}")
    if ent is None:
        _hls_idr_probe_bg(host, path)
        return False
    # תשובה שהתיישנה: ממשיכים לפי מה שידוע, ומרעננים ברקע. ספק יכול
    # לתקן את הקידוד של ערוץ, ובלי הרענון היינו ממשיכים להמיר אותו
    # לנצח — וההמרה היא הדבר היחיד כאן שעולה משאבים.
    if time.time() - ent[0] > _HLS_IDR_TTL:
        _hls_idr_probe_bg(host, path)
    return bool(ent[1])
'''

EDITS = [("הרשאת פורט ב-_fix", A_HOST, N_HOST),
         ("סימון כשל מוחלט", A_MARK, N_MARK),
         ("קריאת הסימון", A_FIRST, N_FIRST),
         ("ההפניה במסלול הרגיל", A_MAN, N_MAN),
         ("הלוגיקה", A_HELPER, N_HELPER)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def code_only(fn: str) -> str:
    parts = fn.split('"""')
    body = parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_hls_autofix_wanted", "_hls_idr_probe_bg", "_is_hls_manifest",
              "hls_relay", "hls_relay_fixed", "_hls_no_idr", "_hls_fix_key"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    rel = code_only(fn_source(s, "hls_relay"))
    fx = code_only(fn_source(s, "hls_relay_fixed"))

    # ההפניה יושבת בענף ה-playlist, לפני כל משיכה מהמקור
    assert "_hls_autofix_wanted" in rel, "המסלול הרגיל אינו מפנה"
    assert rel.index("_is_hls_manifest(path)") < rel.index("_hls_autofix_wanted")
    assert rel.index("_hls_autofix_wanted") < rel.index("_hls_relay_client.get"), \
        "ההפניה אחרי המשיכה מהמקור — מבזבזת בקשה"
    # ומקטעים אינם מופנים
    assert "_proxy_segment" in rel and rel.count("_hls_autofix_wanted") == 1

    # הפורט
    assert 'host.partition(":")[0] not in HLS_RELAY_ALLOWED_HOSTS' in fx, \
        "_fix עוד דוחה פורט מפורש"

    # שובר הלולאה
    assert "_hls_fix_profile[key] = None" in fx, "הכשל אינו מסומן"
    assert "_hls_fix_profile.pop(key, None)" not in fx, "הסימון עוד נמחק"
    assert "_hls_fix_profile.get(key) or 0" in fx, "None ייקרא כפרופיל"

    # ── התנהגות ──────────────────────────────────────────────────────────
    import time as _t
    ns = {"HLS_AUTOFIX": True, "_hls_idr_probing": set(), "PORT": 8000,
          "time": _t, "_HLS_IDR_TTL": 6 * 3600,
          "log": type("L", (), {"warning": lambda *a: None})()}
    probed = []
    ns["_hls_idr_probe_bg"] = lambda h, p: probed.append(f"{h}/{p}")
    ns["_hls_fix_key"] = lambda h, p: f"K:{h}/{p}"
    exec(fn_source(s, "_hls_autofix_wanted"), ns)
    want = ns["_hls_autofix_wanted"]

    # 1. אין תשובה במטמון — לא מפנים, ושולחים בדיקה לרקע. זה הצופה הראשון.
    ns["_hls_idr_cache"] = {}
    ns["_hls_fix_profile"] = {}
    assert want("h", "a.m3u8") is False, "הצופה הראשון הופנה בלי שידוע כלום"
    assert probed == ["h/a.m3u8"], probed

    # 2. יש IDR — ממשיכים במסלול הרגיל, בלי לגעת בכלום
    ns["_hls_idr_cache"] = {"h/a.m3u8": (_t.time(), False)}
    assert want("h", "a.m3u8") is False, "ערוץ תקין הופנה סתם"

    # 3. אין IDR — מפנים
    ns["_hls_idr_cache"] = {"h/a.m3u8": (_t.time(), True)}
    assert want("h", "a.m3u8") is True, "ערוץ בלי IDR לא הופנה"

    # 3א. תשובה טרייה אינה גוררת בדיקה מיותרת ברקע
    probed.clear()
    assert want("h", "a.m3u8") is True
    assert probed == [], f"בדיקה מיותרת על תשובה טרייה: {probed}"

    # 3ב. תשובה שהתיישנה — עונים לפי מה שידוע ומרעננים ברקע. בלי זה
    #     ערוץ שהספק תיקן היה ממשיך לעבור המרה לנצח.
    ns["_hls_idr_cache"] = {"h/a.m3u8": (_t.time() - 7 * 3600, True)}
    probed.clear()
    assert want("h", "a.m3u8") is True, "תשובה ישנה שינתה את התשובה"
    assert probed == ["h/a.m3u8"], "תשובה ישנה לא רועננה"

    # 4. _fix כבר נכשל לגמרי — **לא** מפנים. זה שובר הלולאה.
    ns["_hls_fix_profile"] = {"K:h/a.m3u8": None}
    assert want("h", "a.m3u8") is False, "לולאה: ערוץ שנכשל הופנה שוב"

    # 5. פרופיל 0 שעובד אינו נקרא בטעות ככשל
    ns["_hls_fix_profile"] = {"K:h/a.m3u8": 0}
    assert want("h", "a.m3u8") is True, "פרופיל 0 נקרא כאילו נכשל"

    # 6. כיבוי בסביבה מחזיר את ההתנהגות הקודמת
    ns["HLS_AUTOFIX"] = False
    assert want("h", "a.m3u8") is False, "HLS_AUTOFIX=0 לא מכבה"

    # 7. הבדיקה ברקע אינה נשלחת פעמיים לאותו ערוץ
    ns2 = {"HLS_AUTOFIX": True, "_hls_idr_probing": set(), "PORT": 8000,
           "asyncio": type("A", (), {"ensure_future": staticmethod(
               lambda c: (c.close(), None)[1])})(),
           "log": type("L", (), {"warning": lambda *a: None})(),
           "_hls_no_idr": lambda *a: None}
    exec(fn_source(s, "_hls_idr_probe_bg"), ns2)
    bg = ns2["_hls_idr_probe_bg"]
    bg("h", "a.m3u8")
    n_after_first = len(ns2["_hls_idr_probing"])
    bg("h", "a.m3u8")
    assert n_after_first == 1 and len(ns2["_hls_idr_probing"]) == 1, \
        "בדיקה כפולה לאותו ערוץ"
    return True


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

    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("הקישור בקטלוג לא משתנה, ואין מה לעדכן באפליקציה או באתר.")
    print("הצופה הראשון של ערוץ כזה מקבל את מה שקיבל עד היום, והבדיקה")
    print("רצה לו ברקע. מהשני — הערוץ מופנה לבד.")
    print()
    print("לראות את זה קורה:")
    print("  journalctl -u zovex-bot -n 200 | grep -E 'hls_codec|hls_fix|autofix'")
    print("  ואז לבקש את הערוץ פעמיים:  curl -s -o /dev/null -w '%{http_code}\\n' <הקישור>")
    print("  הפעם השנייה צריכה להחזיר 307.")
    print()
    print("לכיבוי בלי לבטל את הפאץ':  HLS_AUTOFIX=0 בסביבת השירות.")


if __name__ == "__main__":
    main()
