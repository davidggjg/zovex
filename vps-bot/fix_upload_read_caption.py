#!/usr/bin/env python3
"""fix_upload_read_caption — הבוט יזהה גם לפי הכיתוב, לא רק לפי שם הקובץ.

## מה קורה היום

ב-on_upload, הזיהוי יוצא משם הקובץ בלבד:

    fname = getattr(media, "file_name", None) or (message.caption or "") or ""
    ep = parse_episode_info(fname)
    query, options = await smart_tmdb_search(fname)

הכיתוב נכנס רק אם **אין** שם קובץ בכלל. אבל בערוצים השם האמיתי יושב
דווקא בכיתוב, ושם הקובץ הוא "video_2023.mkv" או
"TLK.SKMD.2023.1080p.BluRay.remux.x265-CARTEL.mkv".

## מה שכבר קיים בקוד

‎_recognition_candidates קוראת בדיוק את זה — שתי שורות הכותרת של
הכיתוב, שנה, וזיהוי טריילר — ו-recognize_media עוטפת אותה. הן נכתבו
לייבוא מערוץ, ובבוט ההעלאה פשוט לא נקראות. ‎recognize_media לא נקראת
באף מקום.

נבדק על הכיתוב מהצילום, "שבעה מלכים צריכים למות (2023)":

    היום (שם הקובץ בלבד):  ['video 2023', 'video']
    עם הכיתוב:             ['שבעה מלכים צריכים למות (2023)',
                            'שבעה מלכים צריכים למות',
                            'The Last Kingdom: Seven Kings Must Die',
                            'video 2023', 'video']    · שנה: 2023

## מה משתנה

1. ‎on_upload קורא ל-recognize_media(caption, fname) במקום
   ל-smart_tmdb_search(fname). המועמדים מהכיתוב נוסו ראשונים, והשנה
   עוברת ל-TMDB בשדה נפרד (היא מדרגת התאמות באותה שנה ראשונות).
2. סימון פרק — קודם משם הקובץ כמו היום, ואם אין שם כלום, משורות
   הכותרת של הכיתוב. **רק מהכותרת ולא מהתקציר**: "בפרק הזה" בתוך
   תקציר היה נקרא כמספר פרק.
3. כשאין זיהוי, השם שמוצע לשמירה הוא המועמד ה**ראשון** — הניחוש הטוב
   ביותר. עד היום נשמר האחרון שנוסה, כלומר הגרוע מכולם.
4. כיתוב שנראה כמו טריילר/קדימון מוסיף אזהרה להודעה. לא חוסם — אם
   העלית בכוונה, זו ההחלטה שלך.
5. שאילתה עם שנה בסוגריים מקבלת גם גרסה בלי השנה, מיד אחרי השם המלא.

ייבוא מערוץ לא משתנה: הוא כבר קרא את הכיתוב.

    python3 fix_upload_read_caption.py --check
    python3 fix_upload_read_caption.py
    python3 fix_upload_read_caption.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_upload_read_caption"
MARK = "fix_upload_read_caption"

# ── 1. מועמד בלי שנה בסוף, מיד אחרי השם המלא ──────────────────────────────
A1 = """    base = clean_name(fname)
    cands = [base]
"""
N1 = """    base = clean_name(fname)
    cands = [base]
    # [fix_upload_read_caption]
    # בלי שנה בסוף, מיד אחרי השם המלא. כיתוב של ערוץ כותב "שם הסרט (2023)",
    # והשנה עוברת ל-tmdb_search בשדה נפרד ממילא — בתוך השאילתה היא רעש.
    _ny = re.sub(r"[\\(\\[]?\\s*\\b(19|20)\\d{2}\\b\\s*[\\)\\]]?\\s*$",
                 "", base).strip(" -–—·.")
    if _ny and _ny != base:
        cands.append(_ny)
"""

# ── 2. שורות הכותרת של הכיתוב, לזיהוי פרק ─────────────────────────────────
A2 = "def _recognition_candidates(caption: str, fname: str):\n"
N2 = '''def _cap_head(caption: str, lines: int = 3) -> str:
    """שורות הכותרת של הכיתוב בלבד — עד השורה הראשונה של מטא-דאטה.

    לזיהוי פרק צריך רק אותן. התקציר מכיל "בפרק הזה" ודומיו, ו-_HE_EP_ONLY
    היה קורא את זה כמספר פרק. ראה fix_upload_read_caption.py.
    """
    out = []
    for line in (caption or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if _CAP_NOISE.search(line):
            break
        out.append(line)
        if len(out) >= lines:
            break
    return "\\n".join(out)


def _episode_from_caption(caption: str):
    """סימון פרק מתוך שורות הכותרת של הכיתוב, עם שם סדרה נקי.

    parse_episode_info לוקח כשם הסדרה את כל מה שלפני הסימון — ובכיתוב
    של ערוץ זה *שתי* שורות כותרת ביחד, כלומר "הדוב (2022) The Bear".
    לכן שם הסדרה נלקח מהשורה הראשונה בלבד, בלי שנה בסוף.
    ראה fix_upload_read_caption.py.
    """
    head = _cap_head(caption)
    if not head:
        return None
    ep = parse_episode_info(head)
    if not ep:
        return None
    name = re.sub(r"[\\(\\[]?\\s*\\b(19|20)\\d{2}\\b\\s*[\\)\\]]?\\s*$", "",
                  clean_name(head.splitlines()[0])).strip(" -–—·.")
    if len(name) >= 2:
        ep["series"] = _series_alias(name)
    return ep


def _recognition_candidates(caption: str, fname: str):
'''

# ── 3. recognize_media תחזיר גם את השאילתה ────────────────────────────────
A3 = '''async def recognize_media(caption: str, fname: str):
    """זיהוי TMDB מתוך כיתוב+שם קובץ, עם שנה. מחזיר (options, year, is_trailer)."""
    cands, year, is_trailer = _recognition_candidates(caption, fname)
    for q in cands:
        opts = await tmdb_search(q, year)
        if opts:
            return opts, year, is_trailer
    return [], year, is_trailer
'''
N3 = '''async def recognize_media(caption: str, fname: str):
    """זיהוי TMDB מתוך כיתוב+שם קובץ, עם שנה.

    מחזיר (query, options, year, is_trailer). query הוא המועמד שהחזיר
    תוצאות; ואם אף אחד לא החזיר — המועמד ה**ראשון**, כלומר הניחוש הטוב
    ביותר לשם, ולא האחרון שנוסה. ראה fix_upload_read_caption.py.
    """
    cands, year, is_trailer = _recognition_candidates(caption, fname)
    for q in cands:
        opts = await tmdb_search(q, year)
        if opts:
            return q, opts, year, is_trailer
    return (cands[0] if cands else clean_name(fname)), [], year, is_trailer
'''

# ── 4. on_upload: סימון פרק גם מהכיתוב ────────────────────────────────────
A4 = '''    fname = getattr(media, "file_name", None) or (message.caption or "") or ""
    # אם שם הקובץ מכיל סימון פרק (S01E05 / עונה X פרק Y / 1x05) — הוספה אוטומטית
    # כפרק סדרה, בלי TMDB אינטראקטיבי. מתאים להעלאה מרובה (עד 20 קבצים ברצף).
    ep = parse_episode_info(fname)
'''
N4 = '''    cap = (message.caption or "").strip()
    fname = getattr(media, "file_name", None) or cap or ""
    # אם שם הקובץ מכיל סימון פרק (S01E05 / עונה X פרק Y / 1x05) — הוספה אוטומטית
    # כפרק סדרה, בלי TMDB אינטראקטיבי. מתאים להעלאה מרובה (עד 20 קבצים ברצף).
    #
    # [fix_upload_read_caption]
    # קודם שם הקובץ, כי שם הסימון הכי אמין; ואם אין בו כלום — שורות
    # הכותרת של הכיתוב. רק הכותרת ולא התקציר, ראה _cap_head.
    ep = parse_episode_info(fname) or _episode_from_caption(cap)
'''

# ── 5. on_upload: חיפוש TMDB לפי הכיתוב ───────────────────────────────────
A5 = '''    await status.edit_text(f"✅ הועלה לערוץ.\\n🔎 מחפש ב-TMDB: <b>{clean_name(fname) or '—'}</b>...")
    query, options = await smart_tmdb_search(fname)
'''
N5 = '''    # [fix_upload_read_caption]
    # הזיהוי קורא גם את הכיתוב ולא רק את שם הקובץ: בערוץ השם העברי, השם
    # האנגלי והשנה יושבים בשתי השורות הראשונות של הכיתוב, בזמן ששם הקובץ
    # הוא לא פעם "video_2023.mkv". recognize_media כבר ידעה לעשות את זה
    # והייתה פשוט לא בשימוש באף מקום.
    _guess = (_recognition_candidates(cap, fname)[0] or [clean_name(fname)])[0]
    await status.edit_text(f"✅ הועלה לערוץ.\\n🔎 מחפש ב-TMDB: <b>{_guess or '—'}</b>...")
    query, options, _year, is_trailer = await recognize_media(cap, fname)
'''

# ── 6. הודעות: אזהרת טריילר, ושם ברירת מחדל טוב יותר ──────────────────────
A6 = '''    if not options:
        # אין זיהוי אוטומטי — נותנים לבחור: שמור בשם הגולמי או הקלד שם ידני
        await status.edit_text(
            f"⚠️ לא זיהיתי אוטומטית «{query or fname}».\\n"
            f"אפשר לשמור בשם הזה, או להקליד שם אחר לחיפוש:",
            reply_markup=_options_keyboard(channel_msg_id, [], query or fname))
        return
    await status.edit_text(
        "🎬 מצאתי כמה התאמות — איזו זו? (או 'שם אחר' אם אף אחת לא נכונה)",
        reply_markup=_options_keyboard(channel_msg_id, options, query))
'''
N6 = '''    # [fix_upload_read_caption] הכיתוב אומר טריילר/קדימון? מזהירים ולא חוסמים:
    # אם העלית את זה בכוונה, זו ההחלטה שלך.
    _tr = "⚠️ הכיתוב נראה כמו טריילר/קדימון — ודא שזה הסרט עצמו.\\n" \\
        if is_trailer else ""
    if not options:
        # אין זיהוי אוטומטי — נותנים לבחור: שמור בשם הגולמי או הקלד שם ידני
        await status.edit_text(
            f"{_tr}⚠️ לא זיהיתי אוטומטית «{query or fname}».\\n"
            f"אפשר לשמור בשם הזה, או להקליד שם אחר לחיפוש:",
            reply_markup=_options_keyboard(channel_msg_id, [], query or fname))
        return
    await status.edit_text(
        f"{_tr}🎬 מצאתי כמה התאמות — איזו זו? (או 'שם אחר' אם אף אחת לא נכונה)",
        reply_markup=_options_keyboard(channel_msg_id, options, query))
'''

EDITS = [("מועמד בלי שנה", A1, N1, "_query_candidates"),
         ("שורות כותרת", A2, N2, None),
         ("recognize_media", A3, N3, None),
         ("פרק מהכיתוב", A4, N4, "on_upload"),
         ("חיפוש לפי כיתוב", A5, N5, "on_upload"),
         ("הודעות", A6, N6, "on_upload")]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    names = {n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for f in ("_cap_head", "_episode_from_caption", "recognize_media",
              "_recognition_candidates",
              "on_upload", "smart_tmdb_search", "_query_candidates"):
        assert f in names, f"{f} חסרה"
    rm = fn_source(s, "recognize_media")
    assert "return q, opts, year, is_trailer" in rm, "recognize_media לא מחזירה שאילתה"
    assert "cands[0] if cands else" in rm, "ברירת המחדל עדיין האחרון שנוסה"
    up = fn_source(s, "on_upload")
    assert "await recognize_media(cap, fname)" in up, "on_upload לא קורא לזיהוי"
    assert "smart_tmdb_search" not in up, "on_upload עדיין מחפש לפי שם בלבד"
    assert "_episode_from_caption(cap)" in up, "פרק לא נקרא מהכיתוב"
    assert up.count("cap = (message.caption or \"\").strip()") == 1, "cap לא הוגדר"
    # cap חייב להיות מוגדר לפני כל שימוש בו
    assert up.index("cap = (message.caption") < up.index("_episode_from_caption("), \
        "cap בשימוש לפני שהוגדר"
    assert up.index("is_trailer = await recognize_media") < up.index("if is_trailer"), \
        "is_trailer בשימוש לפני שהוגדר"
    # הדרך הישנה נשארת למסלול הדרייב, שאין לו כיתוב בכלל
    dr = fn_source(s, "_handle_drive_upload")
    assert dr and "smart_tmdb_search" in dr, "מסלול הדרייב נפגע"
    assert s.count("def _cap_head(") == 1, "_cap_head הוגדרה פעמיים"
    assert s.count("def _episode_from_caption(") == 1, "_episode_from_caption כפולה"
    # שם הסדרה מהכיתוב חייב להילקח מהשורה הראשונה בלבד
    ec = fn_source(s, "_episode_from_caption")
    assert "head.splitlines()[0]" in ec, "שם הסדרה לא מהשורה הראשונה"


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

    out = s
    for name, a, b, inside in EDITS:
        n = out.count(a)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            print("   main.py שונה ממה שציפיתי — לא נוגע בכלום.")
            return 1
        if inside:
            body = fn_source(out, inside)
            # rstrip: מקטע המקור של פונקציה נגמר בלי שורה חדשה בסוף, ועוגן
            # שהוא סוף הפונקציה לא היה נמצא בו אחרת.
            if body is None or a.rstrip("\n") not in body:
                print(f"❌ העוגן '{name}' לא נמצא בתוך {inside}.")
                return 1
        out = out.replace(a, b, 1)

    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: זיהוי העלאה קורא את הכיתוב — שם, שנה, פרק — ולא רק את שם הקובץ")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_urc"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_upload_read_caption.py --revert")
    print()
    print("  בדיקה: שלח לבוט קובץ עם כיתוב של ערוץ ושם קובץ חסר תועלת.")
    print("  ההודעה צריכה להגיד «מחפש ב-TMDB» עם השם מהכיתוב, לא עם שם הקובץ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
