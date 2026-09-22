#!/usr/bin/env python3
"""fix_vh_mkv_readahead — מקטע MKV נבנה בכל פעם מחדש, בלי מטמון ובלי קידום מראש.

## מה נמדד

הדיווח מהשטח: "נטען הרבה זמן ואז נתקע, ויש קליטה". מדדתי את ארבעת
המקטעים הראשונים של קורליין דרך ‎/vh, אחד אחרי השני, בדיוק כמו שהנגן
מבקש אותם:

    s0   6.5s   (12.2s של סרט)
    s1   9.0s   (16.3s)
    s2   8.7s   (17.1s)
    s3   4.4s   (10.3s)
    ────────────────────────
         28.6s  עבור 55.9 שניות של סרט

כלומר פי 2 מזמן אמת. זה *עובד* — ובלי שום רזרבה: על כל שתי שניות
צפייה יש שנייה של המתנה. צופה שני, קפיצה, או רגע של עומס במעבד, והבאפר
מתרוקן. ככה נראית "טעינה ארוכה ואז תקיעה".

## למה זה קורה רק ב-MKV

ב-‎vodfix_segment המטמון והקידום-מראש נמצאים **בתוך** התנאי:

    if not info.get("video_ok", True):     # ← רק כאן יש מטמון וקידום מראש

בזמנו זו הייתה החלטה נכונה: copy היה קיים רק ל-MP4, שם ה-moov יושב
בזיכרון, הקלט מגיע דרך ‎/fs, והבנייה זולה. אבל ב-MKV, שהתווסף
ב-fix_vh_matroska, ‎video_ok הוא **True** ל-h264 — ולכן כל מקטע של כל
הסרטים האלה נבנה מחדש בכל בקשה: ffmpeg מפרק את ה-EBML ואת ה-Cues מעל
HTTP, קופץ לנקודה, ומקודד את הקול. וזה טורי, כי הנגן מבקש מקטע רק אחרי
שקיבל את הקודם.

ועוד: קפיצה חזרה לאותה נקודה שילמה את כל המחיר שוב, כי שום דבר לא נשמר.

## התיקון

מסלול ה-MKV מקבל את מה שיש למסלול הקידוד — מטמון וקידום מראש — בשתי
הסתייגויות:

1. **המקטע שהצופה מחכה לו עכשיו ממשיך להיזרם חי, בלי הסמפור.** אחרת
   הייתי מכניס אותו לתור מאחורי שלוש בניות של קידום מראש ומגדיל דווקא
   את ההשהיה שבאתי לתקן.
2. אם הקידום-מראש כבר בונה בדיוק את המקטע הזה, מחכים לו במקום לבנות
   אותו פעמיים במקביל. ‎_vf_build_to_cache נועל לפי מקטע, ומי שמגיע
   שני מקבל את התוצאה.

בפועל: המקטע הראשון עולה כמו היום, ומשם והלאה הנגן מקבל מקטעים
שמוכנים מראש על הדיסק, ובקפיצה חזרה לאותו מקום — מיד.

## למה זה רק ל-MKV

ל-MP4 ב-copy לא מדדתי השהיה, ולכן לא נוגע בו. השורה שמסמנת את המסלול
היא ‎"mkv": True במידע שנבנה מ-Cues, ולא ניחוש לפי שדה אחר.

## הגנת דיסק

מעכשיו גם סרטים ב-copy נכנסים למטמון, ולכן הוא יתמלא הרבה יותר מהר.
‎_vf_cache_sweep שומר על התקרה (‎VODFIX_CACHE_GB, ברירת מחדל 20GB), אבל
אם אין על הדיסק מקום לתקרה הזאת — התסריט **לא יחיל כלום** ויגיד לך
בדיוק מה להריץ. אני לא רוצה להפיל את השרת על דיסק מלא בגלל תיקון
לתקיעות.

    python3 fix_vh_mkv_readahead.py --check
    python3 fix_vh_mkv_readahead.py
    python3 fix_vh_mkv_readahead.py --revert
"""
import ast
import os
import re
import shutil
import sys
from pathlib import Path

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
ENV = os.environ.get("ZOVEX_ENV", "/opt/zovex-bot/.env")
BAK = PATH + ".bak_vh_mkv_readahead"
MARK = "fix_vh_mkv_readahead"
MARGIN_GB = 4.0        # כמה חייב להישאר פנוי גם כשהמטמון מלא עד התקרה

# ── עוגן 1: המידע שנבנה מ-Cues, ב-_vf_info_or_mkv ─────────────────────────
A1 = '        info = {"segments": plan, "header": None, "moov_at_end": False,\n'
N1 = ('        info = {"segments": plan, "header": None, "moov_at_end": False,\n'
      '                # [fix_vh_mkv_readahead] מסמן את מסלול ה-MKV במפורש.\n'
      '                # שם המקטע נבנה ב-4.4 עד 9.0 שניות גם ב-copy, ולכן\n'
      '                # הוא צריך מטמון וקידום מראש כמו מסלול הקידוד.\n'
      '                "mkv": True,\n')

# ── עוגן 2: סוף בלוק המטמון של מסלול הקידוד, לפני בניית הפקודה ────────────
A2 = '''        _vf_schedule_readahead(chat_id, message_id, seg, info)
        return _vf_cached_response(dest)

    args = _vf_seg_args(chat_id, message_id, info, seg)
'''
N2 = '''        _vf_schedule_readahead(chat_id, message_id, seg, info)
        return _vf_cached_response(dest)

    # [fix_vh_mkv_readahead]
    # ב-MKV גם copy יקר: ffmpeg מפרק את ה-EBML ואת ה-Cues מעל HTTP בכל
    # מקטע, קופץ לנקודה, ומקודד את הקול. נמדד על קורליין, ארבעה מקטעים
    # בזה אחר זה:
    #     s0 6.5s · s1 9.0s · s2 8.7s · s3 4.4s  =  28.6 שניות
    #     עבור 12.2+16.3+17.1+10.3 = 55.9 שניות של סרט
    # פי 2 מזמן אמת, בלי רזרבה. והנגן מבקש מקטע רק אחרי הקודם, ולכן
    # ההמתנות מצטברות: צופה נוסף, קפיצה או רגע עומס — והבאפר מתרוקן.
    # כך נראה הדיווח "נטען הרבה זמן ואז נתקע".
    #
    # המקטע שמחכים לו עכשיו ממשיך להיזרם חי ובלי הסמפור, כדי שההשהיה
    # לא תגדל אף פעם; רק המקטעים הבאים נבנים ברקע ונשמרים. מכאן והלאה
    # הנגן מקבל אותם מוכנים, וקפיצה חזרה לאותו מקום לא משלמת שוב.
    if info.get("mkv"):
        dest = _vf_cache_path(chat_id, message_id, seg)
        if dest.exists():
            try:
                os.utime(dest, None)      # נגיעה אחרונה, בשביל הניקוי
            except OSError:
                pass
            _vf_schedule_readahead(chat_id, message_id, seg, info)
            return _vf_cached_response(dest)
        # אם הקידום מראש בונה בדיוק את המקטע הזה, מחכים לו במקום לבנות
        # אותו שוב במקביל: _vf_build_to_cache נועל לפי מקטע, ומי שמגיע
        # שני מקבל True ברגע שהראשון סיים.
        if (chat_id, message_id, seg) in _vf_readahead:
            ok = await _vf_build_to_cache(
                chat_id, message_id, seg,
                _vf_seg_args(chat_id, message_id, info, seg), dest)
            if ok and dest.exists():
                _vf_schedule_readahead(chat_id, message_id, seg, info)
                return _vf_cached_response(dest)
        _vf_schedule_readahead(chat_id, message_id, seg, info)

    args = _vf_seg_args(chat_id, message_id, info, seg)
'''

EDITS = [("סימון מסלול MKV", A1, N1, "_vf_info_or_mkv"),
         ("מטמון וקידום מראש ל-MKV", A2, N2, "vodfix_segment")]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def env_val(key, default):
    """קורא מפתח אחד מ-.env. לא מדפיס כלום ממנו — יש שם סודות."""
    try:
        with open(ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return os.environ.get(key, default)


def disk_report():
    """(פנוי, גידול אפשרי, תקרה) בג'יגה-בייט. כולם על הדיסק של המטמון."""
    cdir = Path(env_val("VODFIX_CACHE_DIR", "/var/cache/zovex-vh"))
    try:
        cap = float(env_val("VODFIX_CACHE_GB", "20"))
    except ValueError:
        cap = 20.0
    probe = cdir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free / (1 << 30)
    used = 0
    if cdir.exists():
        for p in cdir.rglob("s*.ts"):
            try:
                used += p.stat().st_size
            except OSError:
                pass
    used /= (1 << 30)
    return free, max(cap - used, 0.0), cap


def disk_ok():
    free, growth, cap = disk_report()
    print(f"דיסק:  {free:.1f}GB פנוי · תקרת מטמון {cap:.0f}GB · "
          f"יכול לגדול בעוד {growth:.1f}GB")
    if free - growth >= MARGIN_GB:
        return True
    want = max(int(free + (cap - growth) - MARGIN_GB - 1), 2)
    print(f"❌ אחרי שהמטמון יתמלא יישארו {free - growth:.1f}GB בלבד, "
          f"ואני לא מחיל תיקון שעלול למלא את הדיסק.")
    print("   הורד את התקרה ואז הרץ שוב:")
    print(f"     printf '\\nVODFIX_CACHE_GB={want}\\n' >> {ENV}")
    print("     systemctl restart zovex-bot")
    return False


def validate(s):
    compile(s, PATH, "exec")
    assert s.count('"mkv": True') == 1, "הסימון לא נוסף פעם אחת"
    assert s.count('info.get("mkv")') == 1, "התנאי לא נוסף פעם אחת"
    iom = fn_source(s, "_vf_info_or_mkv")
    assert iom and '"mkv": True' in iom, "הסימון לא בתוך _vf_info_or_mkv"
    vs = fn_source(s, "vodfix_segment")
    assert vs, "vodfix_segment נעלמה"
    assert 'if info.get("mkv"):' in vs, "התנאי לא בתוך vodfix_segment"
    # הבלוק החדש חייב לבוא *אחרי* בלוק הקידוד, אחרת MKV שמקודד מחדש
    # (HEVC) היה נתפס כאן ומאבד את הסמפור.
    assert vs.index('if not info.get("video_ok", True):') \
        < vs.index('if info.get("mkv"):'), "הבלוק החדש הוקדם לבלוק הקידוד"
    # וחייב לבוא לפני בניית הפקודה לזרימה החיה
    assert vs.index('if info.get("mkv"):') \
        < vs.index("args = _vf_seg_args("), "הבלוק החדש אחרי הזרימה החיה"
    # חמשת האזכורים: ההגדרה, הקריאה במסלול הקידוד, ושלוש במסלול MKV
    assert s.count("_vf_schedule_readahead") == 5, \
        f"ציפיתי ל-5 אזכורי קידום מראש, יש {s.count('_vf_schedule_readahead')}"
    # ומסלול הזרימה החיה נשאר קיים — הוא הדרך של המקטע הראשון
    assert "StreamingResponse(gen(), media_type=\"video/mp2t\"" in vs, \
        "הזרימה החיה נעלמה"


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

    if "_mkv_segment_plan" not in s:
        print("❌ הרץ קודם fix_vh_matroska.py — בלי מסלול MKV אין מה לתקן.")
        return 1

    out = s
    for name, a, b, inside in EDITS:
        n = out.count(a)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            print("   main.py שונה ממה שציפיתי — לא נוגע בכלום.")
            return 1
        body = fn_source(out, inside)
        if body is None or a not in body:
            print(f"❌ העוגן '{name}' לא נמצא בתוך {inside}.")
            return 1
        out = out.replace(a, b, 1)

    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: מקטעי MKV נשמרים ומוקדמים מראש; המקטע שמחכים לו נשאר חי")
    ok_disk = disk_ok()
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0 if ok_disk else 1
    if not ok_disk:
        return 1

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_mkvra"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_vh_mkv_readahead.py --revert")
    print()
    print("  ואחרי זה, בדיקה שזה באמת עזר — אותה מדידה, שוב:")
    print("    פותחים את קורליין באפליקציה, נותנים לו לרוץ 20 שניות,")
    print("    ואז קופצים לאמצע. מה שהיה 9 שניות אמור להיות מיידי.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
