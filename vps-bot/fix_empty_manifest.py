#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_empty_manifest — playlist בלי סגמנטים אינו playlist תקין.

## מה נמדד

סריקה של כל 105 ערוצי השידור החי מצאה ש-46 מהם מחזירים **playlist ריק**:

    #EXTM3U
    #EXT-X-VERSION:3
    #EXT-X-MEDIA-SEQUENCE:0
    #EXT-X-TARGETDURATION:0

73 בתים, אפס ‎#EXTINF‎, אפס סגמנטים. עקבי — שלוש בקשות לכל ערוץ נתנו
אפס בכולן, בעוד ערוץ שעובד מחזיר שש.

ונבדק אם זה אנחנו: ‎_rewrite_hls_manifest‎ **אינו מוריד אף שורה** — כל
שורה נכנסת ל-out_lines. ‎TARGETDURATION:0‎ גם אינו משהו שאנחנו כותבים.
ואז נשלף הנתיב מהקטלוג ונשאל ישירות, בשלושה User-Agent שונים: כרום
(מה שהריליי שולח), VLC, ובלי UA בכלל — **73 בתים ואפס סגמנטים בכל
השלושה**. כלומר זה לא ה-UA ולא הריליי; הספק מחזיר ריק לנתיבים האלה.

## הבאג שכן אצלנו

    if resp.status_code != 200 or not resp.text.lstrip().startswith("#EXTM3U"):
        raise HTTPException(502, ...)

**playlist ריק עובר את הבדיקה הזאת.** הוא מתחיל ב-‎#EXTM3U‎, ולכן הוא
"תקין", ואנחנו מגישים אותו לנגן. הנגן מקבל רשימה בלי מה לבקש, ויושב על
0:00 **בלי לזרוק שגיאה** — וזה בדיוק התסמין שדווח על עשרות ערוצים.
גרוע מכך, הוא גם נכנס למטמון, ולכן אפילו כשהספק מתאושש הצופה ממשיך
לקבל את הריק עד שה-TTL עובר.

זה הדפוס הרביעי מאותו סוג בסיבוב הזה: בדיקה ששואלת על הצורה ולא על
התוכן. (‎stderr=DEVNULL‎; ‎_fix‎ שאישר "נוצר קובץ"; ‎_hls_no_idr‎ שניבא
על הקלט; וכאן.)

## מה משתנה

* **ריק אינו תקין.** נספרים שורות שאינן הערה. אפס ⇒ אינו playhead תקף.
* **ניסיון חוזר אחד**, כי בקצה של שידור חי ריק חולף הוא דבר שקורה.
  אם הניסיון השני מחזיר סגמנטים — הצופה לא יודע שהיה משהו.
* **ריק אינו נכנס למטמון.** בלי זה ניסיון חוזר היה חסר טעם, והתאוששות
  של הספק הייתה מתעכבת עד שה-TTL עובר.
* **נרשם ביומן** עם שם הערוץ ומספר הבתים, כך ש-46 כשלים שקטים הופכים
  למשהו שרואים.
* 502 עם הודעה שאומרת מה קרה, במקום 200 עם מסך שנתקע לנצח.

## למה 502 ולא משהו "רך" יותר

הנגן אינו יכול לעשות שום דבר עם playlist ריק, ולכן 200 הוא שקר שגורם
לו להמתין ללא סוף. שגיאה מפורשת נותנת לו — ולנו — לדעת. וכבר יש נפילה
אחורה במקום אחר: ‎_fix‎ מפנה למסלול הרגיל כשההמרה נכשלת, ולא להיפך.

## מה זה לא מתקן

הספק ממשיך להחזיר ריק. 46 הערוצים האלה לא יתנגנו מזה — השאלה למה הוא
מחזיר ריק (מזהה שהתיישן, מגבלת חיבורים, ערוץ שהוסר) היא שאלה אצלו,
והיא מסומנת עכשיו במקום להיראות כמו תקלה שלנו.

    python3 fix_empty_manifest.py --check
    python3 fix_empty_manifest.py
    python3 fix_empty_manifest.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_empty_manifest"
MARK = "fix_empty_manifest"

A_HELPER = '''def _is_hls_manifest(path: str) -> bool:
    return path.endswith(".m3u8")
'''

N_HELPER = '''def _is_hls_manifest(path: str) -> bool:
    return path.endswith(".m3u8")


# [fix_empty_manifest]
def _hls_manifest_entries(text: str) -> int:
    """כמה שורות שאינן הערה יש ב-playlist, כלומר כמה סגמנטים או גרסאות.

    זו הבדיקה שהייתה חסרה. ‎startswith("#EXTM3U")‎ עובר גם על playlist
    של 73 בתים בלי אף סגמנט, ואז הנגן מקבל רשימה בלי מה לבקש ונתקע
    על 0:00 בלי שגיאה. נמדד על 46 מ-105 ערוצי השידור החי.
    """
    return sum(1 for ln in text.splitlines()
               if ln.strip() and not ln.strip().startswith("#"))
'''

A_FETCH = '''            try:
                resp = await _hls_relay_client.get(upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS)
            except httpx.HTTPError as e:
                raise HTTPException(502, f"hls_relay: upstream fetch failed - {e}")
            # אם המקור לא החזיר manifest תקין (שגיאה, redirect שלא נופה, דף
            # HTML כלשהו) - חשוב לעצור כאן. אחרת שכתוב-שורה-שורה "יצליח" גם
            # על HTML ומחזיר ללקוח playlist שבור בלי שום שגיאה ברורה.
            if resp.status_code != 200 or not resp.text.lstrip().startswith("#EXTM3U"):
                raise HTTPException(
                    502, f"hls_relay: upstream did not return a valid m3u8 "
                         f"(status {resp.status_code})")
            rewritten = _rewrite_hls_manifest(resp.text, upstream_url)
            _hls_manifest_cache[upstream_url] = (now + MANIFEST_CACHE_TTL, rewritten)
'''

N_FETCH = '''            # [fix_empty_manifest] ניסיון חוזר אחד על playlist ריק.
            # בקצה של שידור חי ריק חולף הוא דבר שקורה, ובמקרה כזה הצופה
            # לא צריך לדעת שהיה משהו. ריק **אינו** נכנס למטמון, אחרת
            # הניסיון החוזר היה חסר טעם והתאוששות של הספק הייתה מתעכבת.
            resp = None
            n_entries = 0
            for _try in range(2):
                try:
                    resp = await _hls_relay_client.get(
                        upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS)
                except httpx.HTTPError as e:
                    raise HTTPException(
                        502, f"hls_relay: upstream fetch failed - {e}")
                # אם המקור לא החזיר manifest תקין (שגיאה, redirect שלא נופה,
                # דף HTML כלשהו) - חשוב לעצור כאן. אחרת שכתוב-שורה-שורה
                # "יצליח" גם על HTML ומחזיר ללקוח playlist שבור בלי שגיאה.
                if resp.status_code != 200 or not resp.text.lstrip().startswith("#EXTM3U"):
                    raise HTTPException(
                        502, f"hls_relay: upstream did not return a valid m3u8 "
                             f"(status {resp.status_code})")
                n_entries = _hls_manifest_entries(resp.text)
                if n_entries:
                    break
                if _try == 0:
                    await asyncio.sleep(0.4)
            if not n_entries:
                # 200 עם #EXTM3U ואפס סגמנטים. עד כה זה עבר כתקין, נכנס
                # למטמון, והנגן נתקע עליו לנצח בלי שגיאה.
                log.warning("hls_relay: playlist ריק מהמקור — %s בתים, "
                            "אפס סגמנטים · %s", len(resp.text), path)
                raise HTTPException(
                    502, "hls_relay: upstream returned an empty playlist "
                         "(no segments)")
            rewritten = _rewrite_hls_manifest(resp.text, upstream_url)
            _hls_manifest_cache[upstream_url] = (now + MANIFEST_CACHE_TTL, rewritten)
'''

EDITS = [("מונה הסגמנטים", A_HELPER, N_HELPER),
         ("המשיכה מהמקור", A_FETCH, N_FETCH)]


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
    for f in ("_hls_manifest_entries", "hls_relay", "_is_hls_manifest",
              "_rewrite_hls_manifest"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    rel = code_only(fn_source(s, "hls_relay"))
    assert "_hls_manifest_entries" in rel, "הספירה אינה נקראת"
    assert "for _try in range(2)" in rel, "אין ניסיון חוזר"
    # ריק לא נכנס למטמון: השמירה חייבת לבוא אחרי הבדיקה
    assert rel.index("if not n_entries") < rel.index("_hls_manifest_cache[upstream_url] ="), \
        "ריק נשמר במטמון"
    assert rel.count("_hls_manifest_cache[upstream_url] =") == 1

    # ── התנהגות ──────────────────────────────────────────────────────────
    ns = {}
    exec(fn_source(s, "_hls_manifest_entries"), ns)
    cnt = ns["_hls_manifest_entries"]

    EMPTY = ("#EXTM3U\n#EXT-X-VERSION:3\n"
             "#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-TARGETDURATION:0\n")
    GOOD = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n"
            "#EXTINF:4.5,\nseg1.ts\n#EXTINF:4.5,\nseg2.ts\n")
    VARIANT = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n"
               "low/index.m3u8\n")

    # 1. זה הריק שנמדד בפועל — 46 ערוצים
    assert cnt(EMPTY) == 0, cnt(EMPTY)
    # 2. playlist תקין
    assert cnt(GOOD) == 2, cnt(GOOD)
    # 3. playlist של גרסאות נספר גם הוא — אחרת master תקין היה נחסם
    assert cnt(VARIANT) == 1, cnt(VARIANT)
    # 4. רווחים וסיומות שורה של חלונות
    assert cnt("#EXTM3U\r\n\r\n#EXTINF:1,\r\n  a.ts  \r\n") == 1
    # 5. הכל הערות
    assert cnt("#EXTM3U\n#FOO\n#BAR\n") == 0
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
    print("מעכשיו ערוץ שהספק מחזיר לו playlist ריק יקבל 502 מפורש במקום")
    print("200 שמקפיא את הנגן, וזה יופיע ביומן:")
    print("  hls_relay: playlist ריק מהמקור — 73 בתים, אפס סגמנטים · ...")
    print()
    print("לספור כמה ערוצים במצב הזה:")
    print("  journalctl -u zovex-bot --since '1 hour ago' \\")
    print("    | grep -c 'playlist ריק'")


if __name__ == "__main__":
    main()
