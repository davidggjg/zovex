#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_admin_upload — טופס ההוספה בפאנל, מ-15 שדות לחמישה.

## הבעיה

דוד, מדווח מהשטח: "מאוד קשה להעלות סדרה או סרט, אנשים לא מבינים".
הטופס ב-/admin הציג **חמישה-עשר שדות בשורה**, בלי סימון מה חובה, וקישור
הווידאו — הדבר היחיד שיש ביד כשמתחילים — היה שדה מספר 12 מתוכם. שדה
ה-custom_slug היה חשוף לכולם עם הדוגמה "fauda", והוא זה שהפיק את 4,251
הכתובות המתועתקות שתוקנו ב-fix_slugs.

## מה נעשה כאן

progressive disclosure, שזו הגישה שמערכות מדיה אחרות משתמשות בה: מציגים
את המינימום ומסתירים את השאר עד שצריך אותו.

    1. סוג תוכן
    2. בחר סדרה קיימת   (השם, הקטגוריה והפוסטר מתמלאים לבד)
    3. קישור וידאו *     ← עלה ממקום 12
    4. שם *
    5. קטגוריה *
    ▸ פרטים נוספים — שנה, פוסטר, תקציר, טריילר, כתובת, פרק שני

חמישה שדות גלויים במקום חמישה-עשר. חיפוש ה-TMDB נשאר במקומו מעל הטופס,
כי הוא כבר היה ראשון וכבר כתוב עליו מה הוא ממלא. "פרק" מקבל placeholder
"אוטומטי" והבהרה שריק = הבא בתור, כי המספור האוטומטי היה קיים מאז ומתמיד
ואף אחד לא ידע עליו.

## למה פאצ' ולא החלפת קובץ

admin.html שבשרת **גדול ב-6.6KB מזה שבמאגר** — נערך שם ישירות. החלפת
הקובץ הייתה מוחקת את ההפרש. לכן זו החלפה מדויקת של אזור אחד בלבד,
שמאומתת מול הטקסט הקיים, ומשאירה את כל השאר כמו שהוא.

## מה נשמר

כל שבעה-עשר ה-id וכל ארבעת ה-handlers נשארים — הם מה שה-JS של הפאנל
תלוי בו. הכלי בודק את זה במפורש לפני שהוא כותב, ונופל אם משהו חסר.

    python3 fix_admin_upload.py --check
    python3 fix_admin_upload.py
    python3 fix_admin_upload.py --revert
"""
import argparse, os, re, shutil, sys
from pathlib import Path

TARGET = Path(os.environ.get("ZOVEX_ADMIN", "/opt/zovex-bot/admin.html"))
BAK = TARGET.with_name(TARGET.name + ".bak_upload")
MARK = "פרטים נוספים — כמעט תמיד לא צריך"

OLD = '<label>סוג תוכן</label>\n      <select id="f_kind" onchange="toggleSeries()">\n        <option value="movie">סרט</option><option value="series">פרק בסדרה</option>\n      </select>\n\n      <div id="seriesFields" class="hidden">\n        <label>בחר סדרה קיימת (אופציונלי)</label>\n        <select id="f_existing" onchange="pickExisting()"><option value="">— סדרה חדשה —</option></select>\n        <label>שם הסדרה (זהה בכל הפרקים!)</label><input id="f_series">\n        <div class="grid2">\n          <div><label>עונה</label><input id="f_season" type="number" min="1" placeholder="1"></div>\n          <div><label>פרק</label><input id="f_episode" type="number" min="1" placeholder="1"></div>\n        </div>\n        <label>פרק שני (רק אם שני פרקים באותו וידאו — יוצג "פרק 1+2")</label>\n        <input id="f_episode_end" type="number" min="1" placeholder="ריק = פרק אחד רגיל">\n      </div>\n\n      <label id="lbl_title">שם</label>\n      <input id="f_title" placeholder="שם הסרט / למשל: פאודה פרק 1">\n      <label>כתובת URL באנגלית (custom_slug, לא חובה)</label>\n      <input id="f_slug" dir="ltr" placeholder="fauda">\n      <div class="grid2">\n        <div><label>שנה</label><input id="f_year" type="number"></div>\n        <div><label>קטגוריה</label><select id="f_category" onchange="onCatChange()"></select></div>\n      </div>\n      <label>קישור וידאו <span class="muted">(הסוג יזוהה אוטומטית)</span></label>\n      <input id="f_video" dir="ltr" placeholder="קישור סטרימינג / YouTube / Drive / mp4 / Kaltura…" oninput="detectType()">\n      <div id="typeHint" class="muted" style="margin:-4px 0 8px"></div>\n      <label>פוסטר (thumbnail_url)</label><input id="f_thumb" dir="ltr">\n      <label>קישור טריילר <span class="muted">(יוטיוב — גובר על הטריילר האוטומטי)</span></label>\n      <input id="f_trailer" dir="ltr" placeholder="https://www.youtube.com/watch?v=… או המזהה בלבד">\n      <label>תקציר</label><textarea id="f_desc"></textarea>'

NEW = '<label>1. סוג תוכן</label>\n<select id="f_kind" onchange="toggleSeries()"><option value="movie">סרט</option><option value="series">פרק בסדרה</option></select>\n<div id="seriesFields" class="hidden"><label>2. בחר סדרה קיימת <span class="muted">(השם, הקטגוריה והפוסטר יתמלאו לבד)</span></label>\n<select id="f_existing" onchange="pickExisting()"><option value="">— סדרה חדשה —</option></select>\n<label>שם הסדרה <span class="muted">(זהה בכל הפרקים!)</span></label><input id="f_series">\n<div class="grid2"><div><label>עונה</label><input id="f_season" type="number" min="1" placeholder="1"></div><div><label>פרק <span class="muted">(ריק = הבא בתור)</span></label><input id="f_episode" type="number" min="1" placeholder="אוטומטי"></div></div></div>\n<label>3. קישור וידאו <span style="color:#ff3b30">*</span> <span class="muted">(הסוג יזוהה אוטומטית)</span></label>\n<input id="f_video" dir="ltr" placeholder="הדבק כאן את הקישור" oninput="detectType()">\n<div id="typeHint" class="muted" style="margin:-4px 0 8px"></div>\n<label id="lbl_title">4. שם <span style="color:#ff3b30">*</span></label>\n<input id="f_title" placeholder="שם הסרט / למשל: פאודה פרק 1">\n<label>5. קטגוריה <span style="color:#ff3b30">*</span></label>\n<select id="f_category" onchange="onCatChange()"></select>\n<details style="margin:10px 0 8px"><summary style="cursor:pointer;font-size:12px;font-weight:700;color:#0071e3;padding:6px 0">פרטים נוספים — כמעט תמיד לא צריך</summary>\n<div style="padding-top:6px">\n<div class="grid2"><div><label>שנה</label><input id="f_year" type="number"></div><div><label>פרק שני <span class="muted">(שני פרקים בוידאו אחד)</span></label><input id="f_episode_end" type="number" min="1" placeholder="ריק = פרק אחד"></div></div>\n<label>פוסטר (thumbnail_url)</label><input id="f_thumb" dir="ltr">\n<label>קישור טריילר <span class="muted">(יוטיוב — גובר על האוטומטי)</span></label>\n<input id="f_trailer" dir="ltr" placeholder="https://www.youtube.com/watch?v=… או המזהה בלבד">\n<label>כתובת URL באנגלית <span class="muted">(נוצרת לבד — עדכן רק אם חייב)</span></label><input id="f_slug" dir="ltr" placeholder="נוצר אוטומטית">\n<label>תקציר</label><textarea id="f_desc"></textarea>\n</div></details>'

# ה-JS של הפאנל תלוי בכל אלה. חסר אחד — הטופס נשבר בשקט.
NEED_IDS = ["f_category", "f_desc", "f_episode", "f_episode_end", "f_existing",
            "f_kind", "f_season", "f_series", "f_slug", "f_thumb", "f_title",
            "f_trailer", "f_video", "f_year", "lbl_title", "seriesFields",
            "typeHint"]
NEED_FNS = ["detectType", "onCatChange", "pickExisting", "toggleSeries"]


def validate(new_region):
    missing = [i for i in NEED_IDS if 'id="%s"' % i not in new_region]
    if missing:
        sys.exit("אימות נכשל: חסרים id: %s" % ", ".join(missing))
    missing = [f for f in NEED_FNS if f + "(" not in new_region]
    if missing:
        sys.exit("אימות נכשל: חסרים handlers: %s" % ", ".join(missing))
    for i in NEED_IDS:
        n = new_region.count('id="%s"' % i)
        if n != 1:
            sys.exit("אימות נכשל: id=%s מופיע %d פעמים (ציפיתי 1)" % (i, n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not TARGET.exists():
        sys.exit("לא נמצא %s (הגדר ZOVEX_ADMIN אם הנתיב שונה)" % TARGET)
    src = TARGET.read_text(encoding="utf-8")

    if a.revert:
        if not BAK.exists():
            sys.exit("אין גיבוי ב-%s" % BAK)
        shutil.copy2(BAK, TARGET)
        print("✓ שוחזר מ-%s" % BAK)
        print("  בלי restart — הקובץ נקרא בכל בקשה.")
        return

    if MARK in src:
        print("כבר מותקן. אין מה לעשות.")
        return

    n = src.count(OLD)
    if n != 1:
        sys.exit("האזור נמצא %d פעמים (ציפיתי 1) — admin.html השתנה, לא כותב." % n)

    validate(NEW)
    out = src.replace(OLD, NEW, 1)
    if MARK not in out:
        sys.exit("ההחלפה לא נתפסה — לא כותב.")

    print("שדות גלויים: 5 (היו 15) · המוסתרים עברו ל'פרטים נוספים'")
    print("כל %d ה-id ו-%d ה-handlers אומתו" % (len(NEED_IDS), len(NEED_FNS)))
    if a.check:
        print("--check: שום דבר לא נכתב. היעד: %s" % TARGET)
        return

    shutil.copy2(TARGET, BAK)
    TARGET.write_text(out, encoding="utf-8")
    print("✓ הוחל · גיבוי: %s" % BAK)
    print("  בלי restart. רענן את /admin (Ctrl+Shift+R).")
    print("  לביטול: python3 fix_admin_upload.py --revert")


if __name__ == "__main__":
    main()
