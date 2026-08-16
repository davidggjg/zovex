"""בוט תמיכה ל-Discord — אימות, בניית שרת, ומערכת טיקטים.

מה הוא עושה
-----------
· ‎/setup בונה את כל השרת: תפקידים, קטגוריות, ערוצים והרשאות.
· ‎@everyone לא רואה שום ערוץ. רק "חוקים" ו"אימות" גלויים לפני אימות.
· לחיצה על "אני מאשר את החוקים" נותנת את תפקיד המאומת — וכל הערוצים נפתחים.
· לחיצה על "פתח טיקט" פותחת בחירת סוג, ואז חלון שבו כותבים את הסיבה.
· הטיקט נפתח כערוץ פרטי בקטגוריה של אותו סוג, עם כפתורי "אני מטפל" ו"סגור".
· בסגירה נשלח תמליל מלא בפרטי — גם לפותח וגם למי שלקח את הטיקט.
· ארבע דרגות: מאומת → תמיכה → צוות → בעלים. לכל דרגה אזור משלה עם חדר
  קול פרטי, וכל דרגה רואה את האזורים שמתחתיה בלבד.
· בקשות להוספת תוכן אינן טיקט — יש להן ערוץ ייעודי, "בקשות-תוכן".

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
                   WELCOME_AFTER_VERIFY, TICKET_TYPES, TICKET_PROMPTS,
                   CONTENT_REQUEST_TITLE, CONTENT_REQUEST_BODY)

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
# רק המזהה הזה יכול לנהל רמות בהודעה פרטית לבוט. כל אחד אחר מקבל תשובה
# כללית ולא רואה שהפקודות קיימות בכלל.
OWNER_ID = int(os.environ.get("DISCORD_OWNER_ID", "1532515146751017030"))

ROLE_VERIFIED = "מאומת"
ROLE_SUPPORT = "תמיכה"     # עונה לטיקטים, מוחק הודעות
ROLE_STAFF = "צוות"        # גם פאנל הניהול והעלאת תוכן
ROLE_ADMIN = "בעלים"       # הדרגה הגבוהה ביותר

# תפקידים ששמם השתנה — /setup ישנה במקום ליצור חדש, אחרת כל מי שהיה
# ב"מנהל" מאבד את ההרשאות שלו ברגע שהמבנה מדבר על "בעלים".
ROLE_RENAMES = [("מנהל", ROLE_ADMIN)]

COLOR = 0xE50914

# ── מבנה השרת ────────────────────────────────────────────────────────────────
# (שם קטגוריה, [(שם ערוץ, סוג)], מי רואה)
#   visibility: "public"   — כולם, גם לפני אימות
#               "verified" — רק אחרי אימות
#               "support"  — תמיכה ומעלה
#               "staff"    — צוות ובעלים בלבד (תמיכה לא רואה)
#               "admin"    — בעלים בלבד
# לכל דרגה יש אזור משלה עם חדר קול פרטי, וכל דרגה רואה גם את האזורים
# שמתחתיה. כך "חדר-תמיכה" פתוח לתמיכה/צוות/בעלים, ו"חדר-בעלים" לבעלים בלבד.
SERVER_LAYOUT = [
    ("ברוכים הבאים", [("חוקים", "text"), ("אימות", "text")], "public"),
    ("מידע", [("הודעות", "text"), ("עדכוני-גרסה", "text")], "verified"),
    ("צאט-ראשי", [("צאט-ראשי", "text"), ("מדיה", "text"),
                  ("המלצות", "text"), ("אוף-טופיק", "text")], "verified"),
    ("בקשות", [("בקשות-תוכן", "text")], "verified"),
    ("צפייה משותפת", [("על-מה-צופים", "text"), ("צפייה-1", "voice"),
                      ("צפייה-2", "voice"), ("צפייה-3", "voice")], "verified"),
    ("דיבורים", [("דיבורים-כללי", "voice"), ("מוזיקה", "voice"),
                 ("שקט", "voice")], "verified"),
    ("תמיכה", [("פתיחת-טיקט", "text")], "verified"),
    ("אזור תמיכה", [("תמיכה-צאט", "text"), ("חדר-תמיכה", "voice")], "support"),
    ("צוות", [("צוות-כללי", "text"), ("לוג-טיקטים", "text"),
              ("חדר-צוות", "voice")], "staff"),
    ("בעלים", [("בעלים-כללי", "text"), ("חדר-בעלים", "voice")], "admin"),
]

# שמות שהשתנו — /setup ישנה אותם במקום ליצור כפילות
RENAMES = [
    ("צאט-כללי", "צאט-ראשי"),
    ("כללי", "צאט-ראשי"),          # שם הקטגוריה הישן
    ("הנהלה", "בעלים"),
    ("הנהלה-כללי", "בעלים-כללי"),
    ("חדר-הנהלה", "חדר-בעלים"),
]

# קטגוריות שכבר לא במבנה. מוסרות ב-/setup רק אם הן ריקות, כדי לא למחוק
# טיקטים פתוחים שעדיין יושבים שם.
OBSOLETE_CATEGORIES = ["טיקטים · בקשות תוכן"]


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

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        """בלי זה כשל בפתיחת טיקט מופיע למשתמש כ'משהו השתבש' ונעלם בלוג."""
        log.exception("פתיחת טיקט נכשלה: %s", error)
        msg = f"פתיחת הטיקט נכשלה: {type(error).__name__}: {error}"[:1900]
        if isinstance(error, discord.Forbidden):
            msg = ("אין לבוט הרשאה ליצור את ערוץ הטיקט.\n"
                   "הגדרות שרת → תפקידים → הבוט: Administrator, "
                   "וגרור אותו לראש הרשימה.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_submit(self, interaction: discord.Interaction):
        log.info("שליחת טופס טיקט %s על ידי %s", self.tid, interaction.user)
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

        support = discord.utils.get(guild.roles, name=ROLE_SUPPORT)
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
        for r in (support, staff, admin):
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

        mention = (support or staff).mention if (support or staff) else ""
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
        # נשאר ב-INFO בכוונה: בלי זה אי אפשר להבדיל בין "הלחיצה לא הגיעה לבוט"
        # לבין "הגיעה ונכשלה", ושתי התקלות נראות למשתמש בדיוק אותו דבר.
        log.info("בחירת סוג טיקט: %s על ידי %s", self.values, interaction.user)
        try:
            await interaction.response.send_modal(ReasonModal(self.values[0]))
        except Exception as e:
            log.exception("פתיחת חלון הטיקט נכשלה: %s", e)
            try:
                await interaction.response.send_message(
                    f"לא הצלחתי לפתוח את החלון: {type(e).__name__}: {e}"[:300],
                    ephemeral=True)
            except discord.HTTPException:
                pass


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
    """מי רשאי לקחת ולסגור טיקטים — תמיכה, צוות ומנהלים."""
    names = {r.name for r in getattr(member, "roles", [])}
    return (bool({ROLE_SUPPORT, ROLE_STAFF, ROLE_ADMIN} & names)
            or member.guild_permissions.manage_guild)


def _staff_only_overwrites(guild):
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    verified = discord.utils.get(guild.roles, name=ROLE_VERIFIED)
    if verified:
        ow[verified] = discord.PermissionOverwrite(view_channel=False)
    for name in (ROLE_SUPPORT, ROLE_STAFF, ROLE_ADMIN):
        r = discord.utils.get(guild.roles, name=name)
        if r:
            ow[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True,
                read_message_history=True, attach_files=True, embed_links=True)
    return ow


# ── בניית השרת ───────────────────────────────────────────────────────────────
PERM_HELP = (
    "**חסרות לבוט הרשאות.**\n\n"
    "הגדרות שרת → תפקידים → התפקיד של הבוט:\n"
    "1. הדלק **Administrator**\n"
    "2. **גרור את התפקיד שלו לראש הרשימה**, מעל כל השאר\n\n"
    "דיסקורד לא מרשה לבוט ליצור או להעניק תפקיד שנמצא מעליו, ולכן שני "
    "השלבים נחוצים — הרשאה לבד לא מספיקה.\n\n"
    "אחר כך הרץ `/setup` שוב."
)


@bot.tree.command(name="setup", description="בונה את כל השרת: תפקידים, ערוצים והרשאות")
@app_commands.checks.has_permissions(administrator=True)
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    # בדיקה מראש: עדיף להגיד מה חסר מאשר להיכשל באמצע הבנייה
    me = guild.me
    missing = [n for n, has in (
        ("Manage Roles", me.guild_permissions.manage_roles),
        ("Manage Channels", me.guild_permissions.manage_channels),
    ) if not has]
    if missing:
        await interaction.followup.send(
            PERM_HELP + f"\n\nחסר כרגע: {', '.join(missing)}", ephemeral=True)
        return
    created = []

    # שינוי שם לתפקידים לפני היצירה — אחרת ייווצר תפקיד חדש וריק לצד הישן
    # וכל מי שהיה בו יאבד את ההרשאות.
    for old_name, new_name in ROLE_RENAMES:
        old = discord.utils.get(guild.roles, name=old_name)
        if old and not discord.utils.get(guild.roles, name=new_name):
            try:
                await old.edit(name=new_name, reason="שינוי שם דרגה")
                created.append(f"תפקיד שונה: {old_name} → {new_name}")
            except discord.Forbidden:
                pass

    # תפקידים. permissions=none() בכוונה: הגישה לערוצים מגיעה *רק* מ-overwrites
    # לכל ערוץ, אף פעם לא מהרשאות ברמת השרת. כך אף תפקיד — כולל "בעלים" —
    # לא יכול למחוק ערוצים, לגרש, או "לפוצץ" את השרת. גם ב-/setup חוזר
    # מאפסים את ההרשאות, כדי לנקות כל הרשאה מסוכנת שנוספה ידנית בטעות.
    roles = {}
    for name, color in ((ROLE_VERIFIED, 0x2ECC71), (ROLE_SUPPORT, 0xF1C40F),
                        (ROLE_STAFF, 0x3498DB), (ROLE_ADMIN, COLOR)):
        r = discord.utils.get(guild.roles, name=name)
        if r is None:
            r = await guild.create_role(name=name, colour=discord.Colour(color),
                                        hoist=(name != ROLE_VERIFIED),
                                        permissions=discord.Permissions.none(),
                                        reason="setup של בוט התמיכה")
            created.append(f"תפקיד {name}")
        else:
            # תפקיד קיים — מוודאים שאין לו הרשאות שרת מסוכנות
            try:
                if r.permissions.value != 0:
                    await r.edit(permissions=discord.Permissions.none(),
                                 reason="הקשחה: אין הרשאות שרת לתפקידי הבוט")
                    created.append(f"אופסו הרשאות: {name}")
            except discord.Forbidden:
                pass
        roles[name] = r

    # ‎@everyone לא רואה כלום, וגם אין לו שום הרשאה שרת מסוכנת. זו הנקודה
    # שגורמת לערוצים "להיעלם" עד האימות — וגם מה שמונע מכל משתמש רגיל
    # למחוק/לגרש/לפוצץ. הרשאות מסוכנות (Manage Channels/Server/Roles, Kick,
    # Ban, Administrator, Webhooks, Mention @everyone) פשוט לא קיימות פה.
    await guild.default_role.edit(permissions=discord.Permissions(
        read_message_history=True, change_nickname=True))

    # הקשחת השרת: רמת אימות גבוהה (חשבון חייב טלפון מאומת/ותק) וסינון תוכן —
    # מקטין דרמטית ניסיונות "רייד"/הצפה מחשבונות חד-פעמיים. עוטפים ב-try כי
    # דורש הרשאת Manage Server, ולא רוצים להפיל את כל ה-setup אם חסרה.
    try:
        await guild.edit(
            verification_level=discord.VerificationLevel.high,
            explicit_content_filter=discord.ContentFilter.all_members,
            reason="הקשחת אבטחה")
        created.append("הוקשחה רמת האימות והסינון")
    except (discord.Forbidden, discord.HTTPException):
        pass

    verified = roles[ROLE_VERIFIED]
    support, staff, admin = roles[ROLE_SUPPORT], roles[ROLE_STAFF], roles[ROLE_ADMIN]

    # שינוי שם לערוצים/קטגוריות שהשם שלהם השתנה — במקום ליצור כפילות
    # שינוי שם מודע-סוג: קטגוריה מול ערוץ נבדקות בנפרד, אחרת שינוי שם של
    # ערוץ "תופס" את השם ומדלג על הקטגוריה — וזה יוצר קטגוריה כפולה וריקה.
    for old_name, new_name in RENAMES:
        for obj in list(guild.categories) + list(guild.channels):
            if obj.name != old_name:
                continue
            pool = guild.categories if isinstance(obj, discord.CategoryChannel) \
                else [c for c in guild.channels
                      if not isinstance(c, discord.CategoryChannel)]
            if any(o.name == new_name for o in pool):
                continue
            try:
                await obj.edit(name=new_name)
                created.append(f"שונה שם: {old_name} → {new_name}")
            except discord.Forbidden:
                pass

    # סולם הדרגות. אזור בדרגה X נפתח לכל מי שנמצא ב-X ומעלה, ונחסם במפורש
    # לכל מי שמתחת — חסימה מפורשת ולא היעדר הרשאה, כדי שתפקיד נוסף שמישהו
    # מחזיק לא "יפתח" לו בטעות אזור גבוה יותר.
    TIERS = [(ROLE_SUPPORT, support), (ROLE_STAFF, staff), (ROLE_ADMIN, admin)]

    def overwrites_for(vis):
        deny = discord.PermissionOverwrite(view_channel=False)
        talk = lambda **kw: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True, add_reactions=True,
            connect=True, speak=True, **kw)

        if vis == "public":
            # חוקים ואימות — כולם רואים, אף אחד לא כותב חוץ מהצוות
            ow = {guild.default_role: discord.PermissionOverwrite(
                      view_channel=True, send_messages=False, add_reactions=False)}
            for _, r in TIERS:
                if r:
                    ow[r] = discord.PermissionOverwrite(view_channel=True,
                                                        send_messages=True)
            return ow

        if vis == "verified":
            # כל מי שאומת רואה, כותב ומדבר. תמיכה ומעלה גם מוחקים הודעות.
            ow = {guild.default_role: deny}
            if verified:
                ow[verified] = talk()
            for _, r in TIERS:
                if r:
                    ow[r] = talk(manage_messages=True)
            return ow

        # אזור דרגה: פתוח מהדרגה הזו ומעלה, חסום במפורש מתחתיה
        order = ["support", "staff", "admin"]      # מקביל ל-TIERS, באותו סדר
        floor = order.index(vis) if vis in order else 0
        ow = {guild.default_role: deny}
        if verified:
            ow[verified] = deny
        for i, (_, r) in enumerate(TIERS):
            if not r:
                continue
            ow[r] = talk(manage_messages=True) if i >= floor else deny
        return ow

    rules_ch = verify_ch = panel_ch = content_ch = None
    for cat_name, channels, vis in SERVER_LAYOUT:
        ow = overwrites_for(vis)
        cat = discord.utils.get(guild.categories, name=cat_name)
        if cat is None:
            cat = await guild.create_category(cat_name, overwrites=ow)
            created.append(f"קטגוריה {cat_name}")
        else:
            await cat.edit(overwrites=ow)
        for ch_name, kind in channels:
            # מחפשים רק בערוצים מהסוג הנכון, ולא ב-guild.channels שכולל גם
            # קטגוריות: יש קטגוריה וערוץ באותו שם ("צאט-ראשי"), וחיפוש כללי
            # היה מוצא את הקטגוריה ומנסה להכניס אותה לקטגוריה — דיסקורד דוחה
            # ("Categories cannot have subcategories") וכל ה-setup נכשל.
            pool = guild.voice_channels if kind == "voice" else guild.text_channels
            existing = discord.utils.get(pool, name=ch_name)
            if existing is None:
                if kind == "voice":
                    existing = await guild.create_voice_channel(ch_name, category=cat, overwrites=ow)
                else:
                    existing = await guild.create_text_channel(ch_name, category=cat, overwrites=ow)
                created.append(f"ערוץ {ch_name}")
            else:
                # ערוץ קיים מחזיק הרשאות משלו ולא יורש מהקטגוריה, ולכן תפקיד
                # שנוסף מאוחר לא מגיע אליו — הקטגוריה נראית אבל היא ריקה.
                # בנוסף מעבירים אותו לקטגוריה שהמבנה קובע, כדי לאחד שאריות.
                try:
                    if existing.category_id != cat.id:
                        await existing.edit(category=cat, overwrites=ow)
                        created.append(f"הועבר: {ch_name} → {cat_name}")
                    else:
                        await existing.edit(overwrites=ow)
                except discord.Forbidden:
                    pass
            if ch_name == "חוקים":
                rules_ch = existing
            elif ch_name == "אימות":
                verify_ch = existing
            elif ch_name == "פתיחת-טיקט":
                panel_ch = existing
            elif ch_name == "בקשות-תוכן":
                content_ch = existing

    # קטגוריות הטיקטים — אחת לכל סוג, גלויות לצוות בלבד.
    # מרעננים הרשאות גם לקיימות: תפקיד שנוסף אחרי היצירה (למשל "תמיכה")
    # לא נכנס להרשאות שנקבעו בזמנו, והמשתמש מקבל את התפקיד אבל לא רואה כלום.
    ticket_ow = _staff_only_overwrites(guild)
    for t in TICKET_TYPES:
        cat = discord.utils.get(guild.categories, name=t[4])
        if cat is None:
            cat = await guild.create_category(t[4], overwrites=ticket_ow)
            created.append(f"קטגוריה {t[4]}")
        else:
            await cat.edit(overwrites=ticket_ow)

    # וגם טיקטים פתוחים כרגע — שם ההרשאות נקבעו לכל ערוץ בנפרד ברגע היצירה,
    # ולכן תפקיד שנוצר או שונה אחר כך פשוט לא קיים שם. מזוהים לפי ה-topic
    # ולא לפי הקטגוריה, כדי לתפוס גם טיקטים שהוזזו ידנית.
    for ch in guild.text_channels:
        if not (ch.topic or "").startswith("zovex|"):
            continue
        for r in (roles[ROLE_SUPPORT], roles[ROLE_STAFF], roles[ROLE_ADMIN]):
            try:
                await ch.set_permissions(
                    r, view_channel=True, send_messages=True,
                    manage_messages=True, read_message_history=True)
            except discord.Forbidden:
                pass
        created.append(f"רועננו הרשאות בטיקט {ch.name}")

    # קטגוריות ישנות שהתרוקנו אחרי שהערוצים עברו — מוסרות. רק שמות שמופיעים
    # ברשימת שינויי-השם או ברשימת המיושנות, כדי לא לגעת בקטגוריות ידניות.
    legacy = {old for old, _ in RENAMES} | set(OBSOLETE_CATEGORIES)
    for cat in list(guild.categories):
        if cat.name in legacy and not cat.channels:
            try:
                await cat.delete(reason="קטגוריה ישנה שהתרוקנה")
                created.append(f"הוסרה קטגוריה ריקה: {cat.name}")
            except discord.Forbidden:
                pass

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
        emb.add_field(name="🎬 בקשה להוסיף תוכן",
                      value="לא נפתחת כטיקט — כותבים בערוץ **בקשות-תוכן**.",
                      inline=False)
        await panel_ch.send(embed=emb, view=TicketPanelView())
    if content_ch:
        await content_ch.purge(limit=20, check=lambda m: m.author == guild.me)
        emb = discord.Embed(title=CONTENT_REQUEST_TITLE,
                            description=CONTENT_REQUEST_BODY, color=COLOR)
        msg_pin = await content_ch.send(embed=emb)
        try:
            await msg_pin.pin(reason="הסבר קבוע בערוץ הבקשות")
        except discord.HTTPException:
            pass

    msg = (f"השרת נבנה. נוצרו {len(created)} פריטים.\n\n"
           "**חשוב:** גררו את תפקיד הבוט לראש רשימת התפקידים, אחרת הוא לא "
           "יוכל להעניק אותם.\n\n"
           "**התפקידים, מהגבוה לנמוך:**\n"
           f"· **{ROLE_ADMIN}** — הכל, כולל 'בעלים' ו'חדר-בעלים'\n"
           f"· **{ROLE_STAFF}** — פאנל הניהול והעלאת תוכן. רואה 'צוות' + 'חדר-צוות'\n"
           f"· **{ROLE_SUPPORT}** — טיקטים ומחיקת הודעות. רואה 'אזור תמיכה' + "
           "'חדר-תמיכה'\n"
           f"· **{ROLE_VERIFIED}** — ניתן אוטומטית בלחיצה על כפתור האימות\n\n"
           "כל דרגה רואה גם את האזורים שמתחתיה, ולא את אלה שמעליה.")
    await interaction.followup.send(msg[:1900], ephemeral=True)
    log.info("setup הושלם: %d פריטים", len(created))


@setup_cmd.error
async def setup_error(interaction: discord.Interaction, error):
    """Forbidden באמצע הבנייה = הרשאה חסרה או שהתפקיד של הבוט נמוך מדי."""
    orig = getattr(error, "original", error)
    if isinstance(orig, discord.Forbidden):
        send = (interaction.followup.send if interaction.response.is_done()
                else interaction.response.send_message)
        await send(PERM_HELP, ephemeral=True)
        return
    if isinstance(error, app_commands.MissingPermissions):
        send = (interaction.followup.send if interaction.response.is_done()
                else interaction.response.send_message)
        await send("הפקודה הזו למנהלי השרת בלבד.", ephemeral=True)
        return
    log.exception("setup נכשל: %s", error)
    if interaction.response.is_done():
        await interaction.followup.send(f"השרת לא נבנה: {orig}", ephemeral=True)


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


# ── ניהול רמות בהודעה פרטית (הבעלים בלבד) ───────────────────────────────────
# שולחים לבוט בפרטי:  <מזהה משתמש> <רמה>     למשל:  123456789 תמיכה
# להורדה:             הורד <מזהה> <רמה>
# רשימת רמות:         רמות

LEVELS = {
    "1": ROLE_VERIFIED, "מאומת": ROLE_VERIFIED, "verified": ROLE_VERIFIED,
    "2": ROLE_SUPPORT,  "תמיכה": ROLE_SUPPORT,  "support": ROLE_SUPPORT,
    "3": ROLE_STAFF,    "צוות": ROLE_STAFF,     "staff": ROLE_STAFF,
    "4": ROLE_ADMIN,    "בעלים": ROLE_ADMIN,    "admin": ROLE_ADMIN,
    "מנהל": ROLE_ADMIN,   # השם הישן, כדי שהרגל ישן לא ייכשל
    "owner": ROLE_ADMIN,
}

DM_HELP = (
    "**ניהול רמות**\n"
    "```\n"
    "<מזהה משתמש> <רמה>       העלאה\n"
    "הורד <מזהה> <רמה>        הורדה\n"
    "מי <מזהה>                 אילו רמות יש לו\n"
    "בדוק <מזהה>               מה הוא רואה בפועל ולמה\n"
    "רמות                      רשימת הרמות\n"
    "```\n"
    "רמות: `1` מאומת · `2` תמיכה · `3` צוות · `4` בעלים\n"
    "אפשר גם בשם: `123456789 תמיכה`"
)


def _guild_for_owner():
    """השרת שבו מנהלים. אם הבוט בכמה — DISCORD_GUILD_ID קובע."""
    gid = os.environ.get("DISCORD_GUILD_ID")
    if gid and gid.isdigit():
        return bot.get_guild(int(gid))
    return bot.guilds[0] if bot.guilds else None


async def _handle_owner_dm(message: discord.Message):
    text = (message.content or "").strip()
    if not text:
        return
    low = text.lower()

    if low in ("עזרה", "help", "?"):
        await message.channel.send(DM_HELP)
        return
    if low in ("רמות", "levels"):
        await message.channel.send(
            "‎1 · מאומת — גישה רגילה לכל הערוצים הפתוחים\n"
            "‎2 · תמיכה — טיקטים, מחיקת הודעות, 'אזור תמיכה' ו'חדר-תמיכה'\n"
            "‎3 · צוות — פאנל הניהול והעלאת תוכן, 'צוות' ו'חדר-צוות'\n"
            "‎4 · בעלים — הכל, כולל 'בעלים' ו'חדר-בעלים'")
        return

    guild = _guild_for_owner()
    if guild is None:
        await message.channel.send("הבוט לא נמצא באף שרת.")
        return

    parts = text.split()
    remove = parts[0] in ("הורד", "remove", "-")
    if remove:
        parts = parts[1:]

    if parts and parts[0] in ("בדוק", "check", "debug") and len(parts) >= 2:
        uid = re.sub(r"\D", "", parts[1])
        member = guild.get_member(int(uid)) if uid.isdigit() else None
        if member is None:
            await message.channel.send("לא נמצא משתמש עם המזהה הזה בשרת.")
            return
        lines = [f"**{member}**",
                 "תפקידים: " + (", ".join(r.name for r in member.roles
                                          if r.name != "@everyone") or "אין"),
                 ""]
        # מה הוא רואה בפועל, לפי חישוב ההרשאות של דיסקורד עצמו
        for cat in guild.categories:
            can = cat.permissions_for(member).view_channel
            kids = [c for c in cat.channels
                    if c.permissions_for(member).view_channel]
            lines.append(f"{'✅' if can else '⛔'} {cat.name} — {len(kids)}/"
                         f"{len(cat.channels)} ערוצים")
        # טיקטים פתוחים בפועל. קטגוריה ריקה לא מוכיחה כלום — אם אין אף טיקט
        # פתוח, "לא רואה טיקטים" הוא פשוט המצב הנכון.
        open_tickets = [c for c in guild.text_channels
                        if (c.topic or "").startswith("zovex|")]
        lines += ["", f"**טיקטים פתוחים: {len(open_tickets)}**"]
        for c in open_tickets[:10]:
            ok = c.permissions_for(member).view_channel
            lines.append(f"{'✅' if ok else '⛔'} {c.name}")
        if not open_tickets:
            lines.append("אין אף טיקט פתוח כרגע — אין מה לראות.")

        # מי מוגדר במפורש על קטגוריית טיקטים אחת, לאימות ההרשאות
        sample = next((c for c in guild.categories
                       if c.name.startswith("טיקטים")), None)
        if sample:
            lines += ["", f"**הרשאות מוגדרות על '{sample.name}':**"]
            for target, ov in sample.overwrites.items():
                v = ov.pair()[0].view_channel or (
                    None if not ov.pair()[1].view_channel else False)
                lines.append(f"· {getattr(target, 'name', target)}: "
                             f"{'רואה' if v else 'חסום'}")
        await message.channel.send("\n".join(lines)[:1900])
        return

    if parts and parts[0] in ("מי", "who") and len(parts) >= 2:
        uid = re.sub(r"\D", "", parts[1])
        member = guild.get_member(int(uid)) if uid.isdigit() else None
        if member is None:
            await message.channel.send("לא נמצא משתמש עם המזהה הזה בשרת.")
            return
        names = [r.name for r in member.roles if r.name != "@everyone"]
        await message.channel.send(
            f"**{member}**\nרמות: {', '.join(names) if names else 'אין'}")
        return

    if len(parts) < 2:
        await message.channel.send(DM_HELP)
        return

    uid = re.sub(r"\D", "", parts[0])          # מקבל גם <@123> וגם 123
    level_key = " ".join(parts[1:]).strip().lower()
    role_name = LEVELS.get(level_key)
    if not uid.isdigit() or role_name is None:
        await message.channel.send(
            f"לא הבנתי. הרמה '{' '.join(parts[1:])}' לא מוכרת.\n\n" + DM_HELP)
        return

    member = guild.get_member(int(uid))
    if member is None:
        try:                                    # אולי פשוט לא במטמון
            member = await guild.fetch_member(int(uid))
        except discord.NotFound:
            await message.channel.send(f"אין בשרת משתמש עם המזהה `{uid}`.")
            return
        except discord.Forbidden:
            await message.channel.send("אין לי הרשאה לקרוא את רשימת החברים.")
            return

    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        await message.channel.send(
            f"התפקיד '{role_name}' לא קיים בשרת. הרץ /setup קודם.")
        return

    try:
        if remove:
            await member.remove_roles(role, reason=f"הורדת רמה ע\"י הבעלים")
            await message.channel.send(f"✅ הורדה: **{member}** כבר לא **{role_name}**")
        else:
            # רמה כלשהי מחייבת גם אימות, אחרת הוא לא רואה את הערוצים
            verified = discord.utils.get(guild.roles, name=ROLE_VERIFIED)
            to_add = [role] + ([verified] if verified and verified not in member.roles
                               and role_name != ROLE_VERIFIED else [])
            await member.add_roles(*to_add, reason="העלאת רמה ע\"י הבעלים")
            extra = " (וגם מאומת)" if len(to_add) > 1 else ""
            await message.channel.send(f"✅ **{member}** קיבל **{role_name}**{extra}")
        log.info("רמה: %s %s ל-%s", "הורדה" if remove else "העלאה", role_name, member)
    except discord.Forbidden:
        await message.channel.send(
            f"אין לי הרשאה לתת את '{role_name}'. גרור את תפקיד הבוט לראש "
            "רשימת התפקידים — דיסקורד חוסם מתן תפקיד שנמצא מעליו.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if isinstance(message.channel, discord.DMChannel):
        if message.author.id == OWNER_ID:
            await _handle_owner_dm(message)
        else:
            await message.channel.send(
                "היי. לתמיכה פתח טיקט בערוץ **פתיחת-טיקט** בשרת — "
                "שם הצוות רואה ועונה.")
        return
    await bot.process_commands(message)


@bot.event
async def on_ready():
    log.info("מחובר כ-%s · %d שרתים", bot.user, len(bot.guilds))
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=SERVER_NAME))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("חסר DISCORD_TOKEN — הגדר משתנה סביבה או קובץ .env")
    bot.run(TOKEN)
