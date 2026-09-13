#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף לבוט הדיסקורד פקודה אחת: /hideverify — מסתירה את ערוץ האימות ממי שכבר
אומת, ולא נוגעת בשום דבר אחר.

למה צריך את זה בנפרד מ-/setup:
  • /setup בונה מחדש את *כל* השרת (תפקידים, קטגוריות, הרשאות, לוחות) — יותר
    מדי בשביל שינוי אחד.
  • ובנוסף /setup כבר לא מוצא את ערוץ האימות בכלל: הוא מחפש שם מדויק "אימות",
    והערוץ שונה ל-"✅-אימות". הפקודה כאן מחפשת לפי *הכלה* ("אימות" בתוך השם),
    ולכן עובדת גם עם אימוג'י או מקפים.

מה היא עושה בדיוק: על ערוץ האימות בלבד, קובעת לתפקיד "מאומת" View Channel = ❌.
@everyone לא נוגעים בו — לא-מאומתים חייבים להמשיך לראות את הערוץ כדי לאמת.
כל שאר הערוצים בשרת לא מושפעים.

    python3 fix_discord_hideverify.py --check
    python3 fix_discord_hideverify.py
    python3 fix_discord_hideverify.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-discord/bot.py"))
MARK = 'name="hideverify"'

ANCHOR = '''@bot.tree.command(name="close", description="סוגר את הטיקט הנוכחי ושולח תמליל")
async def close_cmd(interaction: discord.Interaction):'''

BLOCK = '''def _find_verify_channel(guild):
    """ערוץ האימות, גם אם השם שונה ונוספו אליו אימוג'י/מקפים.
    /setup מחפש שם מדויק ("אימות") ולכן מפספס את "✅-אימות" — כאן מחפשים
    לפי הכלה, ומעדיפים ערוץ שהבוט באמת שלח אליו את כפתור האימות."""
    cands = [c for c in guild.text_channels if "אימות" in c.name]
    if not cands:
        return None
    for c in cands:                      # עדיפות לערוץ שבקטגוריית הכניסה
        if c.category and "ברוכים" in c.category.name:
            return c
    return cands[0]


@bot.tree.command(name="hideverify",
                  description="מסתיר את ערוץ האימות ממי שכבר אומת (לא נוגע בשאר השרת)")
@app_commands.checks.has_permissions(administrator=True)
async def hideverify_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name=ROLE_VERIFIED)
    if role is None:
        await interaction.response.send_message(
            f"התפקיד '{ROLE_VERIFIED}' לא קיים בשרת.", ephemeral=True)
        return
    ch = _find_verify_channel(guild)
    if ch is None:
        await interaction.response.send_message(
            "לא מצאתי ערוץ שהשם שלו מכיל 'אימות'.", ephemeral=True)
        return
    try:
        await ch.set_permissions(role, view_channel=False,
                                 reason="ערוץ האימות נעלם ממי שאומת")
    except discord.Forbidden:
        await interaction.response.send_message(
            "אין לי הרשאה לשנות הרשאות בערוץ הזה. יש להעלות את תפקיד הבוט "
            "ולוודא שיש לו Manage Channels.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ בוצע.\\n**#{ch.name}** מוסתר עכשיו מכל מי שיש לו את התפקיד "
        f"**{role.name}** — כולל אותך.\\n"
        f"@everyone עדיין רואה אותו, כדי שלא-מאומתים יוכלו לאמת.\\n"
        f"שאר הערוצים לא הושפעו.", ephemeral=True)
    log.info("hideverify: %s הוסתר מ-%s", ch.name, role.name)


@hideverify_cmd.error
async def hideverify_error(interaction: discord.Interaction, error):
    await interaction.response.send_message(
        "הפקודה הזו למנהלי שרת בלבד.", ephemeral=True)


'''


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
        baks = sorted(glob.glob(str(TARGET) + ".bak-hideverify-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-discord")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הפקודה כבר קיימת. לא שונה כלום.")
        return
    for tok in ("ROLE_VERIFIED", "app_commands", "@bot.tree.command"):
        if tok not in src:
            _fail(f"bot.py חסר {tok} — הקובץ לא מה שציפינו לו.")
    if src.count(ANCHOR) != 1:
        _fail(f"נמצאו {src.count(ANCHOR)} עוגנים, ציפינו ל-1.")

    out = src.replace(ANCHOR, BLOCK + ANCHOR)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")

    if a.check:
        print("✓ העוגן מתאים והתוצאה עוברת קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-hideverify-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-discord")
    print("   ואז בדיסקורד: /hideverify")


if __name__ == "__main__":
    main()
