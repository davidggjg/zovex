#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מסדר את /setup בבוט הדיסקורד (/opt/zovex-discord/bot.py) — בלי למחוק ערוצים
ובלי ליצור כפילויות.

  1. זיהוי מנורמל: ערוץ/קטגוריה נמצאים גם אם השם שונה או קיבל אימוג'י
     ("✅-אימות" == "אימות"). זה מקור הכפילויות ומקור זה ש-/setup "בנה מחדש".
     בכפילות קיימת הוא בוחר את הוותיק (המזהה הנמוך) ולא יוצר שלישי.
  2. הרשאות קוליות: נוספים use_voice_activation (בלעדיו דיסקורד כופה
     push-to-talk), stream (מצלמה ושיתוף מסך), use_soundboard ו-
     use_external_emojis.
  3. אימוג'ים בשמות: מפה נפרדת (CHANNEL_EMOJI). השמות ב-SERVER_LAYOUT נשארים
     קנוניים בכוונה — שורות ההשוואה ch_name == "חוקים" / "אימות" תלויות בהם.
     השינוי נעשה ב-edit(name=...) על הערוץ הקיים, כך שההיסטוריה נשמרת.
  4. DISABLED_CHANNELS: רשימה של ערוצים שהבוט יפסיק ליצור. הוא לא מוחק אותם —
     מחיקה נשארת ידנית, כדי לא לאבד הודעות.

    python3 fix_discord_layout.py --check
    python3 fix_discord_layout.py
    python3 fix_discord_layout.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-discord/bot.py"))
MARK = "def find_by_name("

HELPERS = '''

# ---- סידור מבנה: זיהוי מנורמל, אימוג'ים, ערוצים מושבתים ----------------
# אימוג'י לכל שם קנוני. מה שלא מופיע כאן נשאר בלי אימוג'י.
CHANNEL_EMOJI = {
    "ברוכים הבאים": "👋", "חוקים": "📜", "אימות": "✅",
    "מידע": "ℹ️", "הודעות": "📢", "עדכוני-גרסה": "🆕",
    "צאט-ראשי": "💬", "מדיה": "🖼️", "המלצות": "⭐", "אוף-טופיק": "🎲",
    "בקשות": "📝", "בקשות-תוכן": "🎬",
    "צפייה משותפת": "🍿", "על-מה-צופים": "🗳️",
    "צפייה-1": "🎥", "צפייה-2": "🎥", "צפייה-3": "🎥",
    "דיבורים": "🔊", "דיבורים-כללי": "🗣️", "מוזיקה": "🎵", "שקט": "🤫",
    "תמיכה": "🎫", "פתיחת-טיקט": "🎫",
    "אזור תמיכה": "🛠️", "תמיכה-צאט": "💼", "חדר-תמיכה": "🎧",
    "צוות": "👮", "צוות-כללי": "🗂️", "לוג-טיקטים": "📋", "חדר-צוות": "🔈",
    "בעלים": "👑", "בעלים-כללי": "👑", "חדר-בעלים": "🎙️",
}

# ערוצים שהבוט יפסיק ליצור. ריק = שום דבר לא מושבת.
# למשל: DISABLED_CHANNELS = {norm_name("שקט"), norm_name("צפייה-3")}
DISABLED_CHANNELS = set()


def norm_name(s):
    """שם להשוואה: בלי אימוג'ים, מקפים, רווחים ורישיות."""
    return "".join(c for c in str(s) if c.isalnum()).lower()


def display_name(canon, kind="text"):
    """השם שהערוץ אמור לשאת בדיסקורד: אימוג'י + השם הקנוני."""
    emo = CHANNEL_EMOJI.get(canon)
    if not emo:
        return canon
    return f"{emo} {canon}" if kind == "category" else f"{emo}-{canon}"


def find_by_name(pool, canon):
    """מחפש לפי הכלה מנורמלת ולא לפי שוויון, כדי לא ליצור כפילות לערוץ
    שהשם שלו שונה. בכפילות קיימת בוחר את הוותיק (מזהה נמוך)."""
    want = norm_name(canon)
    hits = [c for c in pool if norm_name(c.name) == want]
    if not hits:
        return None
    # הוותיק ביותר הוא זה שמחזיק את ההיסטוריה. במכוון לא מעדיפים התאמת שם
    # מדויקת: ערוץ כפול שנוצר בשם הקנוני חדש יותר מהמקורי שקיבל אימוג'י.
    return min(hits, key=lambda c: c.id)
'''

PATCHES = [
    ("עוזרים: norm_name / display_name / find_by_name",
     '''OBSOLETE_CATEGORIES = ["טיקטים · בקשות תוכן"]''',
     '''OBSOLETE_CATEGORIES = ["טיקטים · בקשות תוכן"]
''' + HELPERS),

    ("הרשאות קוליות: מיקרופון, מצלמה ושיתוף מסך",
     '''            connect=True, speak=True, **kw)''',
     '''            connect=True, speak=True, use_voice_activation=True,
            stream=True, use_soundboard=True, use_external_emojis=True,
            use_application_commands=True, **kw)'''),

    ("קטגוריה: זיהוי מנורמל + שם תצוגה",
     '''        cat = discord.utils.get(guild.categories, name=cat_name)
        if cat is None:
            cat = await guild.create_category(cat_name, overwrites=ow)
            created.append(f"קטגוריה {cat_name}")
        else:
            await cat.edit(overwrites=ow)''',
     '''        cat_want = display_name(cat_name, "category")
        cat = find_by_name(guild.categories, cat_name)
        if cat is None:
            cat = await guild.create_category(cat_want, overwrites=ow)
            created.append(f"קטגוריה {cat_want}")
        else:
            await cat.edit(overwrites=ow)
            if cat.name != cat_want:
                try:
                    await cat.edit(name=cat_want, reason="אימוג'י בשם הקטגוריה")
                    created.append(f"שם קטגוריה: {cat_name} → {cat_want}")
                except (discord.Forbidden, discord.HTTPException):
                    pass'''),

    ("ערוץ: זיהוי מנורמל, דילוג על מושבתים, יצירה בשם תצוגה",
     '''            existing = discord.utils.get(pool, name=ch_name)
            if existing is None:
                if kind == "voice":
                    existing = await guild.create_voice_channel(ch_name, category=cat, overwrites=ow)
                else:
                    existing = await guild.create_text_channel(ch_name, category=cat, overwrites=ow)
                created.append(f"ערוץ {ch_name}")''',
     '''            if norm_name(ch_name) in DISABLED_CHANNELS:
                continue
            want = display_name(ch_name, kind)
            existing = find_by_name(pool, ch_name)
            if existing is None:
                if kind == "voice":
                    existing = await guild.create_voice_channel(want, category=cat, overwrites=ow)
                else:
                    existing = await guild.create_text_channel(want, category=cat, overwrites=ow)
                created.append(f"ערוץ {want}")'''),

    ("ערוץ קיים: שינוי שם במקום יצירה מחדש",
     '''                except discord.Forbidden:
                    pass
            if ch_name == "חוקים":''',
     '''                except discord.Forbidden:
                    pass
            # שינוי שם ולא יצירה מחדש: ההודעות שבערוץ נשמרות.
            if existing.name != want:
                try:
                    await existing.edit(name=want, reason="אימוג'י בשם הערוץ")
                    created.append(f"שם ערוץ: {existing.name} → {want}")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            if ch_name == "חוקים":'''),
]


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def validate(out):
    for tok in ("def find_by_name(", "def norm_name(", "CHANNEL_EMOJI",
                "use_voice_activation=True", "stream=True",
                "find_by_name(guild.categories, cat_name)",
                "find_by_name(pool, ch_name)"):
        if tok not in out:
            _fail(f"בדיקה נכשלה: חסר {tok}")
    if "discord.utils.get(pool, name=ch_name)" in out:
        _fail("בדיקה נכשלה: החיפוש לפי שם מדויק עוד שם")
    if "create_text_channel(ch_name" in out or "create_voice_channel(ch_name" in out:
        _fail("בדיקה נכשלה: יצירה בשם קנוני במקום שם תצוגה")
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-layout-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-discord")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return
    for tok in ("SERVER_LAYOUT", "OBSOLETE_CATEGORIES", "overwrites_for"):
        if tok not in src:
            _fail(f"bot.py חסר {tok} — הקובץ לא מה שציפינו לו.")

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            _fail(f"{name}: נמצאו {n} התאמות, ציפינו ל-1. לא נוגעים בכלום.")
        out = out.replace(old, new)
        print(f"  ✓ {name}")
    validate(out)

    if a.check:
        print("\n✓ כל חמשת העוגנים התאימו והתוצאה עוברת קומפילציה ובדיקות. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-layout-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"\n✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-discord")
    print("   ואז /setup פעם אחת. הוא לא ימחק ולא ייצור כפילויות — רק ישנה שמות והרשאות.")


if __name__ == "__main__":
    main()
