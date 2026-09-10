#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף לבוט הדיסקורד הקיים (/opt/zovex-discord/bot.py) שלושה דברים שדוד ביקש,
בלי לבנות בוט שני ובלי לגעת בטוקן:

  1. הודעת כניסה ציבורית: כשמישהו מאמת את עצמו, הבוט מתייג אותו וכותב ברוך הבא
     בערוץ "צאט-ראשי" (שנפתח לו בדיוק אחרי האימות).
  2. ערוץ ה-verify נעלם אחרי אימות: התפקיד "מאומת" נחסם מערוץ "אימות", כך
     שברגע שמקבלים את התפקיד הערוץ נעלם. (מוחל ב-/setup — צריך להריץ /setup פעם
     אחת אחרי הפאץ' כדי שיחול על הערוץ הקיים ועל מי שכבר מאומת.)
  3. ניסיון אימות שני: ההודעה "כבר אומתת" מקבלת אימוג'י ונוסח "אתה כבר מאומת".

    python3 fix_discord_welcome.py --check
    python3 fix_discord_welcome.py
    python3 fix_discord_welcome.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-discord/bot.py"))
MARK = "שמחים שהצטרפת"   # ייחודי לתוספת שלנו

PATCHES = [
    ("3) 'כבר מאומת' + אימוג'י",
     '''        if role in interaction.user.roles:
            await interaction.response.send_message(
                "כבר אומתת — כל הערוצים פתוחים לך.", ephemeral=True)
            return''',
     '''        if role in interaction.user.roles:
            await interaction.response.send_message(
                "✅ אתה כבר מאומת! כל הערוצים פתוחים לך.", ephemeral=True)
            return'''),

    ("1) הודעת כניסה ציבורית בצאט-ראשי",
     '''        await interaction.response.send_message(WELCOME_AFTER_VERIFY, ephemeral=True)
        log.info("אימות: %s", interaction.user)''',
     '''        await interaction.response.send_message(WELCOME_AFTER_VERIFY, ephemeral=True)
        # הודעת כניסה ציבורית: מתייגת את מי שהצטרף, בערוץ שנפתח לו כרגע
        main_ch = discord.utils.get(interaction.guild.text_channels, name="צאט-ראשי")
        if main_ch:
            try:
                await main_ch.send(
                    f"👋 ברוך הבא {interaction.user.mention} ל-{SERVER_NAME}! שמחים שהצטרפת 🎬")
            except discord.HTTPException:
                pass
        log.info("אימות: %s", interaction.user)'''),

    ("2) חסימת ערוץ האימות מהתפקיד 'מאומת'",
     '''    if verify_ch:
        await verify_ch.purge(limit=20, check=lambda m: m.author == guild.me)''',
     '''    if verify_ch:
        # ערוץ האימות נעלם ממי שכבר אומת: @everyone רואה (כדי לאמת), והתפקיד
        # "מאומת" חסום — כך אחרי קבלת התפקיד הערוץ נעלם מהמשתמש.
        try:
            await verify_ch.set_permissions(verified, view_channel=False,
                                            reason="ערוץ האימות נעלם אחרי אימות")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await verify_ch.purge(limit=20, check=lambda m: m.author == guild.me)'''),
]


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-welcome-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-discord")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return
    for tok in ("SERVER_NAME", "צאט-ראשי", "verify_ch", "WELCOME_AFTER_VERIFY"):
        if tok not in src:
            _fail(f"bot.py חסר {tok} — הקובץ לא מה שציפינו לו.")

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            _fail(f"{name}: נמצאו {n} התאמות, ציפינו ל-1. לא נוגעים.")
        out = out.replace(old, new)
        print(f"  ✓ {name}")
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")

    if a.check:
        print("\n✓ שלושת השינויים מתאימים והתוצאה עוברת קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-welcome-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"\n✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-discord")
    print("   ואז להריץ /setup בשרת פעם אחת (כדי שערוץ האימות ייעלם ממי שכבר מאומת).")


if __name__ == "__main__":
    main()
