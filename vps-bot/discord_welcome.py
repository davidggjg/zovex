#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט דיסקורד ל-ZOVEX: כשמישהו חדש נכנס לשרת — מתייג אותו וכותב לו ברוך הבא.

הגדרות דרך משתני סביבה (בקובץ /etc/zovex-discord.env — ראה setup_discord_bot.sh):
  DISCORD_TOKEN           — הטוקן של הבוט מפורטל המפתחים של דיסקורד (חובה).
  DISCORD_WELCOME_CHANNEL — ערוץ הברכה: מזהה מספרי או שם. ריק = ערוץ המערכת,
                            ואם אין — הערוץ הראשון שהבוט יכול לכתוב בו.
  DISCORD_WELCOME_TEXT    — נוסח הברכה. {mention} = תיוג, {name} = שם התצוגה.

דורש: pip install -U discord.py  (מותקן ב-venv ע"י setup_discord_bot.sh)
וגם: להדליק "SERVER MEMBERS INTENT" בפורטל המפתחים — בלעדיו on_member_join
לא נורה בכלל, והבוט לא ידע שמישהו נכנס.
"""
import os
import discord

TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
WELCOME_CHANNEL = os.environ.get("DISCORD_WELCOME_CHANNEL", "").strip()
WELCOME_TEXT = os.environ.get(
    "DISCORD_WELCOME_TEXT",
    "ברוך הבא {mention} ל-ZOVEX! 🎬 שמחים שהצטרפת. כל הסרטים והסדרות בעברית "
    "מחכים לך — הקישור לאתר ולאפליקציה בערוצים למעלה.")

# ברירת מחדל: intents רגיל + members. members הוא "privileged" — חייב להדליק
# אותו גם בפורטל, אחרת הבוט נופל בהתחברות עם PrivilegedIntentsRequired.
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)


def _pick_channel(guild):
    """בוחר ערוץ לכתוב בו: לפי ההגדרה, אחרת ערוץ המערכת, אחרת הראשון שאפשר."""
    me = guild.me
    if WELCOME_CHANNEL:
        if WELCOME_CHANNEL.isdigit():
            ch = guild.get_channel(int(WELCOME_CHANNEL))
            if ch and ch.permissions_for(me).send_messages:
                return ch
        ch = discord.utils.get(guild.text_channels, name=WELCOME_CHANNEL.lstrip("#"))
        if ch and ch.permissions_for(me).send_messages:
            return ch
    if guild.system_channel and guild.system_channel.permissions_for(me).send_messages:
        return guild.system_channel
    for ch in guild.text_channels:
        if ch.permissions_for(me).send_messages:
            return ch
    return None


@client.event
async def on_ready():
    print(f"✓ מחובר כ-{client.user} · {len(client.guilds)} שרתים", flush=True)


@client.event
async def on_member_join(member):
    ch = _pick_channel(member.guild)
    if not ch:
        print(f"אין ערוץ שאפשר לכתוב בו בשרת {member.guild}", flush=True)
        return
    try:
        await ch.send(WELCOME_TEXT.format(mention=member.mention,
                                          name=member.display_name))
        print(f"ברוך הבא נשלח ל-{member} ב-#{ch}", flush=True)
    except Exception as e:
        print("שליחת ברוך הבא נכשלה:", e, flush=True)


def main():
    if not TOKEN:
        raise SystemExit("❌ חסר DISCORD_TOKEN — הגדר אותו ב-/etc/zovex-discord.env")
    try:
        client.run(TOKEN)
    except discord.PrivilegedIntentsRequired:
        raise SystemExit(
            "❌ צריך להדליק 'SERVER MEMBERS INTENT' בפורטל המפתחים של דיסקורד "
            "(Bot → Privileged Gateway Intents), אחרת הבוט לא רואה כניסות.")


if __name__ == "__main__":
    main()
