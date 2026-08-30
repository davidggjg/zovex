#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מחליף פוסטרים של ערוצי שידור חי בלוגו הרשמי שלהם.

מה היה: 7 ערוצים נשאו תמונות ממוזערות של גוגל במשקל 2KB — מטושטשות בכל
מסך גדול מטלפון; כמה ערוצים חלקו פוסטר זהה (ארבעת הטורקיים באותה תמונה,
NatGeo/NatGeo Wild/Discovery באותה תמונה); ולערוצי FreeTV הוצמדו לוגואים
של מותגים אחרים לגמרי (yes דוקו במקום FreeTV דוקו, "החיים הטובים" במקום
לייף סטייל, וסרטי *משפחה* על ערוץ ה*אימה*).

מאיפה הכתובות: הלוגואים של FreeTV נלקחו מדף הערוצים הרשמי שלהם, כלומר
שם הערוץ והתמונה הגיעו מאותו מקור ולא הוצמדו בניחוש. השאר מ-tv-logo/
tv-logos. כל כתובת כאן נבדקה בפועל — נטענת, ומעל 3KB.

בטיחות: מגבה בדיוק לאותה תיקייה שהשרת מגבה אליה, מחליף רק ערוצים שה-slug
שלהם מופיע כאן, מדלג בשקט על מה שלא קיים, ומעדכן את מונה הגרסה כדי שהפאנל
לא יחשוב שהתוכן השתנה מתחתיו. אין צורך בהפעלה מחדש — השרת קורא את הקובץ
בכל בקשה.

    python3 fix_posters.py --dry     # מראה מה ישתנה, בלי לגעת
    python3 fix_posters.py           # מחיל
    python3 fix_posters.py --undo    # מחזיר את הגיבוי האחרון
"""
import json, pathlib, shutil, sys, time

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
BAKDIR = DATA / "content_backups"
VERSION = DATA / "content_version.txt"

TVL = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/"
FTV = "https://cms.freetv.tv/uploads/"

# slug → כתובת הלוגו. רק ערוצים שהפוסטר הנוכחי שלהם שגוי, זעיר או משוכפל.
POSTERS = {
    # ── FreeTV — מהדף הרשמי שלהם, אחרי שהערוץ זוהה מהזרם עצמו ──
    "free-doco":     FTV + "doco_921225597b.webp",        # היה: לוגו של yes דוקו
    "Freetvfod":     FTV + "food_ce2f05de9f.webp",        # היה: ערוץ האוכל (מותג אחר)
    "Freetvlffs":    FTV + "lifestyle_139fcc1577.webp",   # היה: החיים הטובים (מותג אחר)
    "Freetv9":       FTV + "movies_horror_c9da326579.webp",  # היה: פוסטר של סרטי משפחה
    "Freetv6":       FTV + "comedy_13a7ab94fb.webp",      # סדרות קומדיה
    "Freetvkomdia2": FTV + "freetvcomedy_6415d26723.webp",  # סדרות קומדיה 2
    "Freetv5":       FTV + "movies_drama_a61206165b.webp",
    "Freetvmovis":   FTV + "movies_action_a5e6590270.webp",
    "Freetvisral":   FTV + "movies_israeli_cba89b2f95.webp",
    "Freetv2":       FTV + "movie_romance_ad8b023d3f.webp",
    "Freetvfrins":   FTV + "movies_family_dba8c5d33e.png",
    "Fretv10":       FTV + "series_global_0b4913dd85.webp",
    "karaoke":       FTV + "karoake_08f151c09a.png",      # הקריוקי האמיתי, לא לוגו מוזיקה של HOT
    # ONE ו-EDGE חלקו לוגו זהה; ל-EDGE יש משלו
    "Oneedge":       FTV + "edge_06973a878a.webp",

    # ── HOT — במקום ממוזערות גוגל של 2KB ──
    "Hotcinema":     TVL + "hot-cinema1-il.png",
    "Hotcinema2":    TVL + "hot-cinema2-il.png",
    "Hotcinema3":    TVL + "hot-cinema3-il.png",
    "Hotcinema4":    TVL + "hot-cinema4-il.png",
    "hot-real":      TVL + "hot-real-il.png",
    "Hotril":        TVL + "hot-real-il.png",
    "HOT8":          TVL + "hot8-il.png",

    # ── ששת ה"טורקיים" חלקו תמונה אחת, ושלושה מהם בכלל אינם טורקיים ──
    # ההצלבה מול HOT ו-yes הראתה ש"הדרמות הטורקיות +/2/3" הם בעצם ויוה
    # איסטנבול, ויוה טלנובלות וויוה וינטג' — אותם ערוצים שכבר יש לנו תחת
    # שמות ויוה. לכן הם מקבלים את הלוגו של הערוץ האמיתי שלהם.
    "Dramottorki":     TVL + "turkish-dramas-channel-plus-il.png",  # HOT: הדרמות הטורקיות +
    "Torki2":          TVL + "turkish-dramas-channel-2-il.png",
    # הזיווג אומת מול הלוח החי, לא לפי השמות: שודרה אותה תוכנית ואותו פרק
    # באותה דקה. לפי השם לבדו הם היו יוצאים הפוך.
    "turkish-plus":    TVL + "viva-plus-il.png",       # = ויוה טלנובלות ("בעושר ובעוני")
    "turkish-plus-2":  TVL + "viva-il.png",            # = ויוה איסטנבול ("בנות הירח")
    "turkish-plus-3":  TVL + "viva-vintage-il.png",    # = ויוה וינטג' ("דולסה אמור")
}


def load():
    if not CONTENT.exists():
        print(f"❌ לא נמצא {CONTENT}")
        sys.exit(1)
    return json.loads(CONTENT.read_text(encoding="utf-8"))


def undo():
    baks = sorted(BAKDIR.glob("content_*.json"))
    if not baks:
        print("❌ אין גיבוי")
        sys.exit(1)
    shutil.copy2(baks[-1], CONTENT)
    print(f"↩️  שוחזר מ-{baks[-1].name}")


def main():
    dry = "--dry" in sys.argv
    arr = load()
    by = {}
    for e in arr:
        s = e.get("custom_slug")
        if s:
            by.setdefault(s, []).append(e)

    changes, missing = [], []
    for slug, url in POSTERS.items():
        ents = by.get(slug)
        if not ents:
            missing.append(slug)
            continue
        for e in ents:
            old = (e.get("thumbnail_url") or "")
            if old == url:
                continue
            changes.append((e.get("title", slug), old, url))
            if not dry:
                e["thumbnail_url"] = url

    for title, old, new in changes:
        short = "(תמונה מוטבעת)" if old.startswith("data:") else old.rsplit("/", 1)[-1][:44]
        print(f"  {title:<22} {short:<46} → {new.rsplit('/', 1)[-1]}")
    if missing:
        print("\n  ⏭ לא נמצאו בתוכן (מדלג):", ", ".join(missing))

    if dry:
        print(f"\nיוחלפו {len(changes)} פוסטרים. הרץ בלי --dry כדי להחיל.")
        return
    if not changes:
        print("אין מה לשנות.")
        return

    BAKDIR.mkdir(parents=True, exist_ok=True)
    bak = BAKDIR / f"content_{int(time.time())}.json"
    bak.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")
    CONTENT.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        v = int(VERSION.read_text(encoding="utf-8").strip()) if VERSION.exists() else 0
        VERSION.write_text(str(v + 1), encoding="utf-8")
    except Exception:
        pass

    print(f"\n✅ הוחלפו {len(changes)} פוסטרים · גיבוי: {bak.name}")
    print("   אין צורך בהפעלה מחדש. רענון חזק בדפדפן כדי לעקוף מטמון תמונות.")
    print("   נסיגה:  python3 fix_posters.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
