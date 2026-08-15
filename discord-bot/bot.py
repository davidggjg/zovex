"""בוט תמיכה ל-Discord — אימות, בניית שרת, ומערכת טיקטים.

מה הוא עושה
-----------
· ‎/setup בונה את כל השרת: תפקידים, קטגוריות, ערוצים והרשאות.
· ‎@everyone לא רואה שום ערוץ. רק "חוקים" ו"אימות" גלויים לפני אימות.
· לחיצה על "אני מאשר את החוקים" נותנת את תפקיד המאומת — וכל הערוצים נפתחים.
· לחיצה על "פתח טיקט" פותחת בחירת סוג, ואז חלון שבו כותבים את הסיבה.
· הטיקט נפתח כערוץ פרטי בקטגוריה של אותו סוג, עם כפתורי "אני מטפל" ו"סגור".
· בסגירה נשלח תמליל מלא בפרטי — גם לפותח וגם למי שלקח את הטיקט.

הרצה
----
    pip install -U discord.py
    export DISCORD_TOKEN=...        # או קובץ .env לצד הקובץ הזה
    python3 bot.py

ב-Developer Portal חובה להדליק ל-bot את שני ה-Intents:
SERVER MEMBERS ו-MESSAGE CONTENT. בלי הראשון אי אפשר לתת תפקידים,
בלי השני התמליל יֵצא ריק.
"""
import asyncio
import io
import logging
import os
import pathlib
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from rules import (RULES, RULES_TITLE, RULES_INTRO, RULES_FOOTER, SERVER_NAME,
                   WELCOME_AFTER_VERIFY, TICKET_TYPES, TICKET_PROMPTS)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("zovex-discord")

# ── טוקן ─────────────────────────────────────────────────────────────────────
ENV_FILE = pathlib.Path(__file__).with_name(".env")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

TOKEN = os.environ.get("DISCORD_TOKEN", "")

ROLE_VERIFIED = "מאומת"
ROLE_STAFF = "צוות"
ROLE_ADMIN = "מנהל"

COLOR = 0xE50914

# ── מבנה השרת ────────────────────────────────────────────────────────────────
# (שם קטגוריה, [(שם ערוץ, סוג)], מי רואה)
#   visibility: "public"   — כולם, גם לפני אימות
#               "verified" — רק אחרי אימות
#               "staff"    — צוות ומנהלים בלבד
SERVER_LAYOUT = [
    ("ברוכים הבאים", [("חוקים", "text"), ("אימות", "text")], "public"),
    ("מידע", [("הודעות", "text"), ("עדכוני-גרסה", "text")], "verified"),
    ("כללי", [("צאט-כללי", "text"), ("מדיה", "text"),
              ("המלצות", "text"), ("אוף-טופיק", "text")], "verified"),
    ("צפייה משותפת", [("על-מה-צופים", "text"), ("צפייה-1", "voice"),
                      ("צפייה-2", "voice"), ("צפייה-3", "voice")], "verified"),
    ("דיבורים", [("דיבורים-כללי", "voice"), ("מוזיקה", "voice"),
                 ("שקט", "voice")], "verified"),
    ("תמיכה", [("פתיחת-טיקט", "text")], "verified"),
    ("צוות", [("צוות-כללי", "text"), ("לוג-טיקטים", "text"),
              ("חדר-צוות", "voice")], "staff"),
]


def ticket_type(tid):
    for t in TICKET_TYPES:
        if t[0] == tid:
            return t
    return None


class ZovexBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True           # נדרש למתן תפקידים
        intents.message_content = True   # נדרש לתמליל
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # Views קבועים: הכפתורים ממשיכים לעבוד גם אחרי הפעלה מחדש של הבוט,
        # כי הם מזוהים לפי custom_id ולא לפי אובייקט שנשמר בזיכרון.
        self.add_view(VerifyView())
        self.add_view(TicketPanelView())
        self.add_view(TicketControlView())
        await self.tree.sync()
        log.info("פקודות סונכרנו")


bot = ZovexBot()


# ── אימות ────────────────────────────────────────────────────────────────────
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="אני מאשר את החוקים", style=discord.ButtonStyle.success,
                       emoji="✅", custom_id="zovex:verify")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name=ROLE_VERIFIED)
        if role is None:
            await interaction.response.send_message(
                "תפקיד האימות לא קיים. שיצור צוות יריץ /setup.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                "כבר אומתת — כל הערוצים פתוחים לך.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="אישר את החוקים")
        except discord.Forbidden:
            await interaction.response.send_message(
                "אין לי הרשאה לתת תפקידים. יש להעלות את תפקיד הבוט מעל "
                f"'{ROLE_VERIFIED}' בהגדרות התפקידים.", ephemeral=True)
            return
        await interaction.response.send_message(WELCOME_AFTER_VERIFY, ephemeral=True)
        log.info("אימות: %s", interaction.user)


# ── טיקטים ───────────────────────────────────────────────────────────────────
def _topic(opener_id: int, tid: str, claimer_id: int = 0) -> str:
    """מקודד את בעלי הטיקט בנושא הערוץ. שורד הפעלה מחדש בלי בסיס נתונים."""
    return f"zovex|opener:{opener_id}|type:{tid}|claimer:{claimer_id}"


def _parse_topic(topic: str) -> dict:
    out = {"opener": 0, "type": "", "claimer": 0}
    for part in (topic or "").split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            if k in ("opener", "claimer"):
                out[k] = int(v) if v.isdigit() else 0
            elif k == "type":
                out["type"] = v
    return out


class ReasonModal(discord.ui.Modal):
    def __init__(self, tid: str):
        self.tid = tid
        t = ticket_type(tid)
        super().__init__(title=f"טיקט · {t[1]}"[:45])
        self.reason = discord.ui.TextInput(
            label="הסיבה",
            placeholder=TICKET_PROMPTS.get(tid, "תאר את הבעיה")[:100],
            style=discord.TextStyle.paragraph, max_length=1500, required=True)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        t = ticket_type(self.tid)
        cat_name = t[4]

        # טיקט אחד פתוח לכל אדם — מונע הצפה
        existing = [c for c in guild.text_channels
                    if (c.topic or "").startswith("zovex|")
                    and _parse_topic(c.topic)["opener"] == interaction.user.id]
        if existing:
            await interaction.followup.send(
                f"כבר יש לך טיקט פתוח: {existing[0].mention}\n"
                "סגור אותו לפני שתפתח חדש.", ephemeral=True)
            return

        category = discord.utils.get(guild.categories, name=cat_name)
        if category is None:
            category = await guild.create_category(
                cat_name, overwrites=_staff_only_overwrites(guild))

        staff = discord.utils.get(guild.roles, name=ROLE_STAFF)
        admin = discord.utils.get(guild.roles, name=ROLE_ADMIN)
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True,
                read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                  manage_channels=True),
        }
        for r in (staff, admin):
            if r:
                ow[r] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True,
                    read_message_history=True)

        safe = re.sub(r"[^\w\-]+", "-", interaction.user.name.lower())[:20] or "user"
        ch = await guild.create_text_channel(
            f"{t[2]}-{safe}"[:95], category=category, overwrites=ow,
            topic=_topic(interaction.user.id, self.tid),
            reason=f"טיקט {t[1]} מאת {interaction.user}")

        emb = discord.Embed(title=f"{t[2]} {t[1]}", color=COLOR,
                            description=str(self.reason), timestamp=datetime.now(timezone.utc))
        emb.add_field(name="נפתח על ידי", value=interaction.user.mention, inline=True)
        emb.add_field(name="סטטוס", value="ממתין לצוות", inline=True)
        emb.set_footer(text="חבר צוות ילחץ 'אני מטפל'. בסגירה יישלח תמליל לשני הצדדים.")

        mention = staff.mention if staff else ""
        await ch.send(content=f"{interaction.user.mention} {mention}".strip(),
                      embed=emb, view=TicketControlView())
        await interaction.followup.send(f"הטיקט נפתח: {ch.mention}", ephemeral=True)
        log.info("טיקט %s נפתח על ידי %s", self.tid, interaction.user)


class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=t[1], value=t[0], emoji=t[2],
                                        description=t[3][:100])
                   for t in TICKET_TYPES]
        super().__init__(placeholder="איזה סוג טיקט?", options=options,
                         custom_id="zovex:ticket_type")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReasonModal(self.values[0]))


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="אני מטפל", style=discord.ButtonStyle.primary,
                       emoji="🙋", custom_id="zovex:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("רק צוות יכול לקחת טיקט.", ephemeral=True)
            return
        info = _parse_topic(interaction.channel.topic)
        if info["claimer"]:
            who = interaction.guild.get_member(info["claimer"])
            await interaction.response.send_message(
                f"הטיקט כבר נלקח על ידי {who.mention if who else 'חבר צוות'}.", ephemeral=True)
            return
        await interaction.channel.edit(
            topic=_topic(info["opener"], info["type"], interaction.user.id))
        await interaction.response.send_message(
            f"🙋 {interaction.user.mention} לקח את הטיקט ומטפל בו.")

    @discord.ui.button(label="סגור טיקט", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="zovex:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        info = _parse_topic(interaction.channel.topic)
        if not _is_staff(interaction.user) and interaction.user.id != info["opener"]:
            await interaction.response.send_message(
                "רק הצוות או מי שפתח את הטיקט יכולים לסגור אותו.", ephemeral=True)
            return
        await interaction.response.send_message("סוגר ושולח תמליל...")
        await close_ticket(interaction.channel, interaction.user)


async def close_ticket(channel: discord.TextChannel, closed_by: discord.Member):
    info = _parse_topic(channel.topic)
    t = ticket_type(info["type"])
    label = t[1] if t else "טיקט"

    lines = [f"תמליל טיקט · {label}",
             f"ערוץ: #{channel.name}",
             f"נסגר על ידי: {closed_by} ({closed_by.id})",
             f"נסגר בתאריך: {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC",
             "─" * 60, ""]
    count = 0
    async for m in channel.history(limit=None, oldest_first=True):
        stamp = m.created_at.strftime("%d/%m %H:%M")
        body = m.clean_content or ""
        for e in m.embeds:
            if e.description:
                body += ("\n" if body else "") + e.description
        for a in m.attachments:
            body += f"\n[קובץ מצורף] {a.filename} — {a.url}"
        lines.append(f"[{stamp}] {m.author}: {body}".rstrip())
        count += 1
    lines += ["", "─" * 60, f"סה\"כ {count} הודעות"]

    data = "\n".join(lines).encode("utf-8")
    fname = f"ticket-{channel.name}-{datetime.now(timezone.utc):%Y%m%d-%H%M}.txt"

    guild = channel.guild
    targets, seen = [], set()
    for uid in (info["opener"], info["claimer"]):
        if uid and uid not in seen:
            seen.add(uid)
            member = guild.get_member(uid)
            if member:
                targets.append(member)

    note = (f"הטיקט שלך בשרת **{guild.name}** נסגר.\n"
            f"סוג: {label}\nנסגר על ידי: {closed_by}\n\n"
            "מצורף תמליל מלא של השיחה.")
    for member in targets:
        try:
            await member.send(note, file=discord.File(io.BytesIO(data), filename=fname))
        except discord.Forbidden:
            log.warning("אי אפשר לשלוח פרטי ל-%s (חסם הודעות פרטיות)", member)

    # עותק לערוץ הלוג של הצוות
    logch = discord.utils.get(guild.text_channels, name="לוג-טיקטים")
    if logch:
        opener = guild.get_member(info["opener"])
        claimer = guild.get_member(info["claimer"])
        emb = discord.Embed(title=f"טיקט נסגר · {label}", color=COLOR,
                            timestamp=datetime.now(timezone.utc))
        emb.add_field(name="פתח", value=opener.mention if opener else "לא ידוע", inline=True)
        emb.add_field(name="טיפל", value=claimer.mention if claimer else "לא נלקח", inline=True)
        emb.add_field(name="סגר", value=closed_by.mention, inline=True)
        emb.add_field(name="הודעות", value=str(count), inline=True)
        try:
            await logch.send(embed=emb, file=discord.File(io.BytesIO(data), filename=fname))
        except discord.Forbidden:
            pass

    await asyncio.sleep(3)
    try:
        await channel.delete(reason=f"טיקט נסגר על ידי {closed_by}")
    except discord.Forbidden:
        log.warning("אין הרשאה למחוק את %s", channel)


# ── עזר ──────────────────────────────────────────────────────────────────────
def _is_staff(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return bool({ROLE_STAFF, ROLE_ADMIN} & names) or member.guild_permissions.manage_guild


def _staff_only_overwrites(guild):
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for name in (ROLE_STAFF, ROLE_ADMIN):
        r = discord.utils.get(guild.roles, name=name)
        if r:
            ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    return ow


# ── בניית השרת ───────────────────────────────────────────────────────────────
@bot.tree.command(name="setup", description="בונה את כל השרת: תפקידים, ערוצים והרשאות")
@app_commands.checks.has_permissions(administrator=True)
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    created = []

    # תפקידים
    roles = {}
    for name, color in ((ROLE_VERIFIED, 0x2ECC71), (ROLE_STAFF, 0x3498DB), (ROLE_ADMIN, COLOR)):
        r = discord.utils.get(guild.roles, name=name)
        if r is None:
            r = await guild.create_role(name=name, colour=discord.Colour(color),
                                        hoist=(name != ROLE_VERIFIED),
                                        reason="setup של בוט התמיכה")
            created.append(f"תפקיד {name}")
        roles[name] = r

    # ‎@everyone לא רואה כלום. זו הנקודה שגורמת לערוצים "להיעלם" עד האימות.
    await guild.default_role.edit(permissions=discord.Permissions(
        read_message_history=True, change_nickname=True))

    verified, staff, admin = roles[ROLE_VERIFIED], roles[ROLE_STAFF], roles[ROLE_ADMIN]

    def overwrites_for(vis):
        deny_all = discord.PermissionOverwrite(view_channel=False)
        if vis == "public":
            return {guild.default_role: discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, add_reactions=False),
                    staff: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    admin: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
        if vis == "verified":
            return {guild.default_role: deny_all,
                    verified: discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, connect=True, speak=True),
                    staff: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    admin: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
        return {guild.default_role: deny_all,
                staff: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                   connect=True, speak=True),
                admin: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                   connect=True, speak=True)}

    rules_ch = verify_ch = panel_ch = None
    for cat_name, channels, vis in SERVER_LAYOUT:
        ow = overwrites_for(vis)
        cat = discord.utils.get(guild.categories, name=cat_name)
        if cat is None:
            cat = await guild.create_category(cat_name, overwrites=ow)
            created.append(f"קטגוריה {cat_name}")
        else:
            await cat.edit(overwrites=ow)
        for ch_name, kind in channels:
            existing = discord.utils.get(guild.channels, name=ch_name)
            if existing is None:
                if kind == "voice":
                    existing = await guild.create_voice_channel(ch_name, category=cat, overwrites=ow)
                else:
                    existing = await guild.create_text_channel(ch_name, category=cat, overwrites=ow)
                created.append(f"ערוץ {ch_name}")
            if ch_name == "חוקים":
                rules_ch = existing
            elif ch_name == "אימות":
                verify_ch = existing
            elif ch_name == "פתיחת-טיקט":
                panel_ch = existing

    # קטגוריות הטיקטים — אחת לכל סוג, גלויות לצוות בלבד
    for t in TICKET_TYPES:
        if discord.utils.get(guild.categories, name=t[4]) is None:
            await guild.create_category(t[4], overwrites=_staff_only_overwrites(guild))
            created.append(f"קטגוריה {t[4]}")

    # לוחות: חוקים, אימות, פתיחת טיקט
    if rules_ch:
        await rules_ch.purge(limit=20, check=lambda m: m.author == guild.me)
        emb = discord.Embed(title=RULES_TITLE, description=RULES_INTRO, color=COLOR)
        for title, body in RULES:
            emb.add_field(name=title, value=body, inline=False)
        emb.set_footer(text=RULES_FOOTER[:2040])
        await rules_ch.send(embed=emb)
    if verify_ch:
        await verify_ch.purge(limit=20, check=lambda m: m.author == guild.me)
        emb = discord.Embed(
            title="אימות כניסה",
            description=("קראת את החוקים בערוץ החוקים?\n"
                         "לחיצה על הכפתור מאשרת אותם ופותחת את כל הערוצים בשרת.\n\n"
                         "**עד ללחיצה לא תראה אף ערוץ.**"),
            color=COLOR)
        await verify_ch.send(embed=emb, view=VerifyView())
    if panel_ch:
        await panel_ch.purge(limit=20, check=lambda m: m.author == guild.me)
        emb = discord.Embed(
            title="פתיחת טיקט",
            description=("בחר סוג טיקט מהרשימה, וכתוב את הסיבה בחלון שייפתח.\n"
                         "ייפתח לך ערוץ פרטי מול הצוות.\n\n"
                         "**טיקט אחד פתוח בכל פעם.** בסגירה יישלח אליך תמליל מלא בפרטי."),
            color=COLOR)
        for t in TICKET_TYPES:
            emb.add_field(name=f"{t[2]} {t[1]}", value=t[3], inline=True)
        await panel_ch.send(embed=emb, view=TicketPanelView())

    msg = (f"השרת נבנה. נוצרו {len(created)} פריטים.\n\n"
           "**חשוב:** גררו את תפקיד הבוט מעל התפקידים "
           f"'{ROLE_VERIFIED}', '{ROLE_STAFF}' ו-'{ROLE_ADMIN}' בהגדרות → תפקידים, "
           "אחרת הוא לא יוכל לתת אותם.\n"
           f"אחר כך תנו לעצמכם ולצוות את התפקיד '{ROLE_STAFF}' או '{ROLE_ADMIN}'.")
    await interaction.followup.send(msg[:1900], ephemeral=True)
    log.info("setup הושלם: %d פריטים", len(created))


@bot.tree.command(name="close", description="סוגר את הטיקט הנוכחי ושולח תמליל")
async def close_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel) or not (ch.topic or "").startswith("zovex|"):
        await interaction.response.send_message("הפקודה הזו עובדת רק בתוך ערוץ טיקט.",
                                                ephemeral=True)
        return
    info = _parse_topic(ch.topic)
    if not _is_staff(interaction.user) and interaction.user.id != info["opener"]:
        await interaction.response.send_message("רק הצוות או פותח הטיקט יכולים לסגור.",
                                                ephemeral=True)
        return
    await interaction.response.send_message("סוגר ושולח תמליל...")
    await close_ticket(ch, interaction.user)


@bot.event
async def on_ready():
    log.info("מחובר כ-%s · %d שרתים", bot.user, len(bot.guilds))
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=SERVER_NAME))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("חסר DISCORD_TOKEN — הגדר משתנה סביבה או קובץ .env")
    bot.run(TOKEN)
