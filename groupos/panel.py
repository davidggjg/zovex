#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""panel — מסכי הניהול בצ'אט הפרטי.

## הבקשה שמאחורי המודול

"אני לא אוהב שצריך לשלוח פקודות בתוך הקבוצה בשביל לנעול אותה."

צודק. Rose בנויה סביב פקודות, וזה מציף את הקבוצה בהודעות ניהול שכל
החברים רואים. כאן: הניהול בפרטי, והקבוצה נשארת נקייה.

## למה המודול הזה לא מכיר את aiogram

כל מסך מחזיר ‎Screen(text, rows)‎ — טקסט ורשימת שורות כפתורים כנתונים
פשוטים. המתאם הופך אותם למקלדת של טלגרם. כך אפשר לבדוק את כל עץ
הניווט בלי בוט: שכל כפתור מוביל למסך קיים, שאין מסך ללא חזרה, ושאף
מזהה כפתור אינו חורג מ-64 בייט — המגבלה של טלגרם, שנשברת בשקט.

## מבנה מזהה הכפתור

    g:<chat_id>:<מסך>:<ארגומנט>

‎chat_id‎ נישא בכל לחיצה כי לצ'אט הפרטי אין הקשר של קבוצה. זה גם מה
שמאפשר לנהל עשר קבוצות מאותו חלון בלי "להתחבר" לאחת מהן.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import i18n
import templates as _tpl
from locks import ACTIONS, GROUPS, LOCK_TYPES
from moderation import format_policy, parse_policy

CB_MAX = 64          # מגבלת טלגרם למזהה כפתור, בבייטים

def action_label(action: str, lang: str = i18n.DEFAULT) -> str:
    return i18n.t(f"act.{action}", lang)


# שמות הפעולות בעברית, לשימושים שאין להם הקשר של שפה
ACTION_LABEL = {a: action_label(a) for a in ACTIONS}
# מחזור הלחיצות על נעילה. לא כל שמונה הפעולות — ארבע שמכסות כמעט הכול,
# והשאר נגישות מהמסך המפורט. תפריט עם שמונה אפשרויות לכל נעילה הוא
# בדיוק סוג העומס שהפאנל הזה נועד למנוע.
CYCLE = ("off", "delete", "warn", "mute", "ban")


@dataclass
class Screen:
    text: str
    rows: list[list[tuple[str, str]]] = field(default_factory=list)

    def all_callbacks(self) -> list[str]:
        return [cb for row in self.rows for _, cb in row]


def cb(chat_id: int, screen: str, arg: str = "") -> str:
    s = f"g:{chat_id}:{screen}" + (f":{arg}" if arg else "")
    if len(s.encode()) > CB_MAX:
        raise ValueError(f"מזהה כפתור ארוך מדי ({len(s.encode())}): {s}")
    return s


def parse_cb(data: str) -> Optional[tuple[int, str, str]]:
    parts = data.split(":", 3)
    if len(parts) < 3 or parts[0] != "g":
        return None
    try:
        chat_id = int(parts[1])
    except ValueError:
        return None
    return chat_id, parts[2], (parts[3] if len(parts) > 3 else "")


# ── המסכים ────────────────────────────────────────────────────────────────
def head(key: str, lang: str, extra: str = "") -> str:
    """כותרת מסך. הודגשה במקום אחד, כדי שהתרגום יישאר טקסט נקי."""
    return f"<b>{i18n.t(key, lang)}{extra}</b>"


# קבוצות התמיכה. ‎he‎ לדוברי עברית, וכל השאר — העולמית.
#
# **ובמסך העולמי אין שום רמז שקיימת קבוצה ישראלית.** זו לא רק
# העדפה: קבוצת תמיכה בשפה שאינך קורא היא מבוי סתום, ואזכור שלה
# במסך האנגלי שולח אנשים למקום שבו לא יענו להם.
SUPPORT_LINKS = {
    "he": "https://t.me/Rocky1t3",
    "*": "https://t.me/Rocky1g",
}


def support_link(lang: str = i18n.DEFAULT) -> str:
    return SUPPORT_LINKS.get(lang, SUPPORT_LINKS["*"])


def support_button(lang: str = i18n.DEFAULT) -> list:
    return [(i18n.t("home.support", lang), support_link(lang))]


# סכומי הכוכבים שמוצעים. ‎XTR‎ הוא המטבע של טלגרם, והתשלום עובר
# דרכה בלבד — אין כאן ספק סליקה, אין פרטי אשראי, ואין מה לאחסן.
#
# **הסכומים מיושרים לחבילות שטלגרם מוכרת.** מי שאין לו כוכבים
# ביתרה נשלח לקנות אותם, והחבילה הקטנה ביותר היא 100. בקשה ל-10
# או ל-25 כוכבים נראית נדיבה ונכשלת אצלו בשלב הרכישה עם "אמצעי
# התשלום אינו זמין למוצר שנבחר" — שגיאה שנראית כמו תקלה בבוט.
#
# 25 ו-50 נשארו ראשונים בכוונה: למי שכבר יש יתרה הם עובדים, והם
# הסכום שאדם באמת שולח כשהוא רק רוצה לומר תודה.
STAR_AMOUNTS = (25, 50, 100, 250, 500, 1000)


def donate_screen(lang: str = i18n.DEFAULT) -> Screen:
    """תרומה בכוכבים. כפתור לכל סכום, ואז החשבונית של טלגרם."""
    rows, line = [], []
    for n in STAR_AMOUNTS:
        line.append((f"⭐ {n}", cb(0, "star", str(n))))
        if len(line) == 3:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([(i18n.t("menu.back", lang), "g:0:home")])
    return Screen(head("star.title", lang) + "\n\n"
                  + i18n.t("star.hint", lang), rows)


def add_button(bot_username: str, lang: str = i18n.DEFAULT) -> list:
    """"הוסף אותי לקבוצה" — הכפתור שפותח את הבחירה של טלגרם עצמה.

    בלעדיו ההוראה היא "לך לפרופיל של הבוט, לחץ על שלוש הנקודות,
    בחר הוספה לקבוצה" — שלושה צעדים שמאבדים חצי מהאנשים בצעד
    הראשון. ‎?startgroup=true‎ עושה את זה בלחיצה."""
    if not bot_username:
        return []
    return [(i18n.t("home.add_me", lang),
             f"https://t.me/{bot_username}?startgroup=true")]


def home(groups: list[tuple[int, str]], lang: str = i18n.DEFAULT,
         bot_username: str = "") -> Screen:
    """רשימת הקבוצות שהמשתמש מנהל."""
    title = head("home.title", lang)
    add = add_button(bot_username, lang)
    if not groups:
        # מי שעוד לא הוסיף את הבוט לשום מקום צריך כפתור, לא הוראות.
        rows = [add] if add else []
        rows.append(support_button(lang))
        return Screen(f"{title}\n\n" + i18n.t("home.empty", lang), rows)
    rows = [[(f"👥 {name[:28]}", cb(cid, "main"))] for cid, name in groups]
    if add:
        rows.append(add)
    # בחירת השפה האישית הייתה חד-פעמית: מי שבחר פעם אחת לא יכול היה
    # לשנות לעולם, כי הבורר מוצג רק למי שטרם בחר.
    rows.append([(i18n.t("menu.language", lang), "g:0:mylang")])
    rows.append(support_button(lang))
    rows.append([(i18n.t("home.donate", lang), "g:0:donate")])
    return Screen(
        f"{title}\n\n" + i18n.t("home.groups", lang, n=len(groups)) + "\n"
        + i18n.t("home.hint", lang), rows)


def main_menu(chat_id: int, title: str, stats: dict,
              lang: str = i18n.DEFAULT) -> Screen:
    """תפריט הקבוצה, מסודר לפי נושא.

    סדר ולא ערימה: עד כה הכפתורים נערמו לפי סדר הוספתם, ושני מסכים
    של מתגים ישבו זה לצד זה בלי שאיש הבין למה יש שניים. כאן כל שורה
    היא נושא אחד — מה אסור · תוכן · זמנים · הגנה · מעקב · הגדרות —
    ובסוף הפעולה היחידה שמשנה את הקבוצה מיד.

    ‎🎛 מתגים‎ ירד לתוך ‎⚙️ הגדרות‎: שני מסכים שבשניהם מכבים ומדליקים
    דברים הם בדיוק מה שגרם לשאלה "למה יש פה שתיים"."""
    txt = f"<b>{title}</b>\n\n" + "\n".join(
        f"{i18n.t(key, lang)}: {stats.get(field, 0)}"
        for key, field in (("stat.members", "members"),
                           ("stat.locks", "locks"),
                           ("stat.warns", "warns"),
                           ("stat.today", "actions_today")))
    rows = [
        # מה מותר ומה לא
        [(i18n.t("menu.locks", lang), cb(chat_id, "locks")),
         (i18n.t("menu.warns", lang), cb(chat_id, "warns"))],
        # מה הבוט אומר
        [(i18n.t("menu.replies", lang), cb(chat_id, "reps"))],
        [(i18n.t("menu.texts", lang), cb(chat_id, "texts")),
         (i18n.t("menu.state", lang), cb(chat_id, "stmsgs"))],
        # מתי
        ([(i18n.t("menu.hours", lang), cb(chat_id, "hours"))]
         + ([(i18n.t("menu.shabbat", lang), cb(chat_id, "shab"))]
            if lang == "he" else [])),
        # הגנה
        [(i18n.t("menu.security", lang), cb(chat_id, "sec")),
         (i18n.t("menu.ai", lang), cb(chat_id, "aim"))],
        [(i18n.t("menu.numbers", lang), cb(chat_id, "nums"))],
        # מעקב
        [(i18n.t("menu.proofs", lang), cb(chat_id, "proofs")),
         (i18n.t("menu.audit", lang), cb(chat_id, "audit"))],
        # הגדרות
        [(i18n.t("menu.settings", lang), cb(chat_id, "settings")),
         (i18n.t("menu.language", lang), cb(chat_id, "lang"))],
        # הפעולה שמשנה את הקבוצה מיד — אחרונה, ולבדה
        [(i18n.t("menu.lockdown_on" if stats.get("lockdown")
                 else "menu.lockdown", lang), cb(chat_id, "ldown"))],
        [(i18n.t("home.support", lang), support_link(lang)),
         (i18n.t("home.donate", lang), "g:0:donate")],
        [(i18n.t("menu.groups", lang), "g:0:home")],
    ]
    return Screen(txt, rows)


def locks_groups(chat_id: int, counts: dict[str, int],
                 lang: str = i18n.DEFAULT) -> Screen:
    txt = head("locks.title", lang) + "\n\n" + i18n.t("locks.hint", lang)
    rows = [[(f"{i18n.t('group.' + g, lang)} ({counts.get(g, 0)})",
              cb(chat_id, "lockg", g))] for g in GROUPS]
    # נעילה או פתיחה של הכול בלחיצה אחת. כשמתחיל ספאם, אף אחד לא
    # עובר על 32 כפתורים אחד-אחד.
    rows.append([(i18n.t("locks.all_on", lang), cb(chat_id, "lockall", "on")),
                 (i18n.t("locks.all_off", lang), cb(chat_id, "lockall", "off"))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    return Screen(txt, rows)


def locks_in_group(chat_id: int, group: str,
                   items: list[tuple[str, str]],
                   lang: str = i18n.DEFAULT) -> Screen:
    """items: [(מפתח, פעולה נוכחית)]. השם מתורגם כאן ולא מגיע מוכן."""
    txt = (head("locks.title", lang, f" · {i18n.t('group.' + group, lang)}")
           + "\n\n" + i18n.t("locks.cycle", lang))
    rows = []
    for key, action in items:
        mark = "🔴" if action != "off" else "⚪"
        suffix = f" · {action_label(action, lang)}" if action != "off" else ""
        rows.append([(f"{mark} {i18n.t('lock.' + key, lang)}{suffix}",
                      cb(chat_id, "lock", key))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "locks"))])
    return Screen(txt, rows)


def warns_screen(chat_id: int, policy_raw: str,
                 top: list[tuple[int, str, int]],
                 lang: str = i18n.DEFAULT) -> Screen:
    pol = parse_policy(policy_raw)
    txt = (head("warns.title", lang) + "\n\n"
           + i18n.t("warns.policy", lang) + "\n"
           + (format_policy(pol) or i18n.t("warns.none", lang)) + "\n")
    if top:
        txt += "\n" + i18n.t("warns.top", lang) + "\n" + "\n".join(
            f"• {name} — {n}" for _, name, n in top)
    rows = [
        [("3 · 5 · 7", cb(chat_id, "wpol", "a")),
         ("2 · 4 · 6", cb(chat_id, "wpol", "b")),
         (i18n.t("warns.preset_c", lang), cb(chat_id, "wpol", "c"))],
        [(i18n.t("menu.back", lang), cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


WARN_PRESETS = {
    "a": "3:mute:3600,5:mute:86400,7:ban:0",
    "b": "2:mute:1800,4:mute:86400,6:ban:0",
    "c": "",
}


def audit_screen(chat_id: int, rows_data: list[dict], fmt_time,
                 lang: str = i18n.DEFAULT) -> Screen:
    if not rows_data:
        txt = head("audit.empty", lang) + "\n\n" + i18n.t("audit.none", lang)
    else:
        txt = head("audit.title", lang) + "\n\n" + "\n".join(
            f"<code>{fmt_time(r['ts'])}</code> {r['action']}"
            + (f" ← {r['target_id']}" if r["target_id"] else "")
            for r in rows_data)
    return Screen(txt, [[(i18n.t("menu.back", lang), cb(chat_id, "main"))]])


def settings_screen(chat_id: int, current: dict,
                    lang: str = i18n.DEFAULT) -> Screen:
    clean = current.get("autoclean", "30")
    silent = current.get("silent", "1") == "1"
    on, off = i18n.t("settings.on", lang), i18n.t("settings.off", lang)
    txt = (head("settings.title", lang) + "\n\n"
           + i18n.t("settings.clean_help", lang) + "\n\n"
           + i18n.t("settings.silent_help", lang))
    clean_txt = (i18n.t("settings.seconds", lang, n=clean)
                 if clean != "0" else off)
    rows = [
        [(f"{i18n.t('settings.clean', lang)}: {clean_txt}",
          cb(chat_id, "clean"))],
        [(f"{i18n.t('settings.silent', lang)}: {on if silent else off}",
          cb(chat_id, "silent"))],
        [(i18n.t("menu.service", lang), cb(chat_id, "svcs"))],
        [(i18n.t("sw.title", lang), cb(chat_id, "sws"))],
        [(i18n.t("menu.back", lang), cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


CLEAN_CYCLE = ("0", "10", "30", "60", "300")


def next_in_cycle(cycle: tuple, current: str) -> str:
    try:
        return cycle[(cycle.index(current) + 1) % len(cycle)]
    except ValueError:
        return cycle[0]


def language_screen(chat_id: int, current: str) -> Screen:
    """בורר השפה. סימון על הנוכחית, כי בלעדיו אי אפשר לדעת מה פעיל.

    המסך הזה נכתב תמיד בשפה הנוכחית — אחרת מי שבחר שפה שאינו מבין
    נשאר בלי דרך חזרה."""
    txt = (head("lang.title", current) + "\n\n"
           + i18n.t("lang.hint", current))
    rows, line = [], []
    for code, name in i18n.available():
        mark = "● " if code == current else ""
        line.append((f"{mark}{name}", cb(chat_id, "setlang", code)))
        if len(line) == 3:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([(i18n.t("menu.back", current), cb(chat_id, "main"))])
    return Screen(txt, rows)


def welcome_screen(current: str = "") -> Screen:
    """המסך הראשון שמשתמש חדש רואה — בחירת שפה, וגם שינוי שלה אחר כך.

    הוא מוצג לפני כל טקסט אחר, ולכן אי אפשר לכתוב אותו בשפה אחת:
    השורה העליונה היא שם השפה בשפה עצמה. מי שלא קרא עברית מימיו
    עדיין מזהה את "English" או "العربية" ברשימה."""
    rows, line = [], []
    for code, name in i18n.available():
        mark = "● " if code == current else ""
        line.append((f"{mark}{name}", cb(0, "pick", code)))
        if len(line) == 3:
            rows.append(line); line = []
    if line:
        rows.append(line)
    if current:
        rows.append([(i18n.t("menu.back", current), "g:0:home")])
    return Screen("<b>GroupOS</b>\n\n🌐 Choose your language", rows)


# ── המתגים ────────────────────────────────────────────────────────────────
# כל הגדרה של כן/לא במקום אחד. (מפתח, ברירת מחדל, מפתח תרגום)
#
# הבעיה שזה פותר: ‎/lockdown‎ בלי ארגומנט היה **מחליף** מצב. מנהל שלא
# זכר איפה הוא עומד לחץ פעמיים וחזר בדיוק לאותו מקום, ונראה היה
# שפקודת הכיבוי "לא נלחצה". פקודה לעולם אינה מחליפה בעיוורון: היא
# מציגה מצב ונותנת שני כפתורים.
SWITCHES: tuple[tuple[str, str, str], ...] = (
    ("captcha",      "0", "sec.captcha"),
    ("flood",        "1", "sec.flood"),
    ("antiraid",     "1", "sec.antiraid"),
    ("reports",      "1", "sec.reports"),
    ("ai",           "1", "sec.ai"),
    ("aivision",     "1", "sw.aivision"),
    ("aivoice",      "0", "sw.aivoice"),
    ("adminpriv",    "1", "sw.adminpriv"),
    ("silent",       "1", "settings.silent"),
    ("cleanservice", "0", "cmd.cleanservice"),
    ("xp",           "1", "sw.xp"),
    ("levelup",      "0", "sw.levelup"),
    ("privatenotes", "0", "sw.privatenotes"),
    ("lockwarns",    "0", "sw.lockwarns"),
    ("spamguard",    "1", "sw.spamguard"),
    ("strict",       "1", "sw.strict"),
    ("keepproof",    "1", "sw.keepproof"),
    ("ephemeral",    "1", "sw.ephemeral"),
    ("welcome_private", "1", "greet.private_sw"),
    ("cleancmds",    "0", "sw.cleancmds"),
    ("tellwhy",      "1", "sw.tellwhy"),
    ("replies",      "1", "sw.replies"),
    ("onlyme",       "0", "sw.onlyme"),
    ("welcome_on",   "1", "sw.welcome"),
    ("goodbye_on",   "1", "sw.goodbye"),
)

SWITCH_KEYS = {k for k, _, _ in SWITCHES}
SWITCH_DEFAULT = {k: d for k, d, _ in SWITCHES}


def switches_screen(chat_id: int, values: dict,
                    lang: str = i18n.DEFAULT) -> Screen:
    """כל המתגים, כל אחד עם מצבו. לחיצה מחליפה — ורואים את התוצאה."""
    rows, line = [], []
    for key, default, label in SWITCHES:
        on = values.get(key, default) == "1"
        line.append((("🟢 " if on else "⚪ ") + i18n.t(label, lang),
                     cb(chat_id, "sw", key)))
        if len(line) == 2:
            rows.append(line); line = []
    if line:
        rows.append(line)
    # "אנשים לא מבינים מה כל דבר עושה." מתג שאי אפשר להבין הוא מתג
    # שלא ייגעו בו, או גרוע מזה — שידליקו בלי לדעת מה הוא משנה.
    rows.append([("❓ " + i18n.t("sw.what", lang), cb(chat_id, "swhelp"))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "settings"))])
    return Screen(head("sw.title", lang) + "\n\n" + i18n.t("sw.hint", lang),
                  rows)


def switches_help(chat_id: int, lang: str = i18n.DEFAULT) -> Screen:
    """שורה אחת לכל מתג: מה הוא עושה, בשפה של אדם."""
    lines = []
    for key, _default, label in SWITCHES:
        why = i18n.t(f"why.{key}", lang)
        if why == f"why.{key}":
            continue
        lines.append(i18n.t("sw.explain", lang,
                            name=f"<b>{i18n.t(label, lang)}</b>", why=why))
    return Screen(head("sw.what_title", lang) + "\n\n"
                  + "\n\n".join(lines),
                  [[(i18n.t("menu.back", lang), cb(chat_id, "sws"))]])


def switch_label(key: str, lang: str = i18n.DEFAULT) -> str:
    """השם שהאדם רואה למתג — ולעולם לא המפתח שבמסד.

    ‎/lockdown‎ ו-‎/emergency‎ אינם ב-‎SWITCHES‎ (הם לא מופיעים במסך
    המתגים), ולכן החיפוש כאן נפל עליהם חזרה למפתח והכותרת שהוצגה
    הייתה ‎<b>lockdown</b>‎ — שם משתנה באנגלית בתוך הודעה בעברית. יש
    להם תווית מלאה תחת ‎cmd.<שם>‎, ולכן זה נופל לשם לפני שהוא מוותר.

    שתי נפילות ולא אחת, כי ‎t()‎ מחזירה את המפתח עצמו כשאין תרגום —
    כלומר "יש תשובה" אינו "יש תווית"."""
    for k, _d, label in SWITCHES:
        if k == key:
            return i18n.t(label, lang)
    alt = f"cmd.{key}"
    return i18n.t(alt, lang) if i18n.t(alt, lang) != alt else key


def switch_screen(chat_id: int, key: str, on: bool,
                  lang: str = i18n.DEFAULT) -> Screen:
    """מתג בודד, לתשובה על פקודה. שני כפתורים מפורשים ולא החלפה."""
    why = i18n.t(f"why.{key}", lang)
    txt = (f"<b>{switch_label(key, lang)}</b>\n"
           + i18n.t("sw.now", lang,
                    state=i18n.t("on" if on else "off", lang)))
    if why != f"why.{key}":
        txt += "\n\n<i>" + why + "</i>"
    rows = [[("✅ " + i18n.t("sw.enable", lang), cb(chat_id, "sw1", key)),
             ("⛔ " + i18n.t("sw.disable", lang), cb(chat_id, "sw0", key))]]
    return Screen(txt, rows)


def security_screen(chat_id: int, rows_state: list[tuple[str, bool]],
                    numbers: dict, lang: str = i18n.DEFAULT) -> Screen:
    """מה מגן על הקבוצה עכשיו, בשורה אחת לכל הגנה.

    מסך שמראה רק "הכול תקין" חסר ערך. כאן כל הגנה מופיעה עם מצבה,
    גם כשהיא כבויה — כי הכבויה היא זו שמעניינת."""
    on, off = i18n.t("on", lang), i18n.t("off", lang)
    lines = [f"{'🟢' if v else '⚪'} {i18n.t(k, lang)} — {on if v else off}"
             for k, v in rows_state]
    txt = (head("sec.title", lang) + "\n\n" + "\n".join(lines) + "\n\n"
           + i18n.t("sec.locks", lang, n=numbers.get("locks", 0)) + "\n"
           + i18n.t("sec.blocks", lang, n=numbers.get("blocks", 0)) + "\n"
           + i18n.t("sec.pending", lang, n=numbers.get("pending", 0)) + "\n"
           + i18n.t("sec.events", lang, n=numbers.get("events", 0)))
    rows = [
        [(i18n.t("menu.emergency", lang), cb(chat_id, "emerg"))],
        [(i18n.t("sec.captcha", lang) + ": "
          + (on if numbers.get("captcha") else off), cb(chat_id, "tgl", "captcha")),
         (i18n.t("sec.flood", lang) + ": "
          + (on if numbers.get("flood") else off), cb(chat_id, "tgl", "flood"))],
        [(i18n.t("sec.antiraid", lang) + ": "
          + (on if numbers.get("antiraid") else off), cb(chat_id, "tgl", "antiraid")),
         (i18n.t("sec.reports", lang) + ": "
          + (on if numbers.get("reports") else off), cb(chat_id, "tgl", "reports"))],
        [(i18n.t("sec.ai", lang) + ": "
          + (on if numbers.get("ai") else off), cb(chat_id, "tgl", "ai"))],
        [(i18n.t("menu.back", lang), cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


def captcha_screen(challenge, lang: str = i18n.DEFAULT) -> Screen:
    """האתגר עצמו. הכפתורים נושאים את התשובה, ולכן הם קצרים בכוונה."""
    secs = max(0, int(challenge.deadline - __import__("time").time()))
    if challenge.kind == "button":
        txt = i18n.t("captcha.prompt", lang, mention="{mention}", secs=secs)
        rows = [[(i18n.t("captcha.button", lang),
                  f"c:{challenge.user_id}:ok")]]
        return Screen(txt, rows)
    key = "captcha.prompt_math" if challenge.kind == "math" else "captcha.prompt_emoji"
    txt = i18n.t(key, lang, mention="{mention}", q=challenge.prompt, secs=secs)
    rows = [[(c, f"c:{challenge.user_id}:{c}") for c in challenge.choices]]
    return Screen(txt, rows)


# הפקודות: שם והרשאה. התיאור מגיע מ-i18n לפי מפתח ‎cmd.<שם>‎, כי אותה
# רשימה מזינה גם את ‎/help‎ וגם את תפריט ✏️ של טלגרם — שם התיאור נרשם
# בנפרד לכל שפה.
COMMANDS: list[tuple[str, str]] = [
    ("start",  ""),
    ("help",   ""),
    ("lock",     "locks.write"),
    ("unlock",   "locks.write"),
    ("locks",    "settings.read"),
    ("lockdown", "chat.lockdown"),
    ("say",      "chat.say"),
    ("del",      "msg.delete"),
    ("pin",      "chat.pin"),
    ("unpin",    "chat.pin"),
    ("ban",    "user.ban"),
    ("unban",  "user.unban"),
    ("mute",   "user.mute"),
    ("unmute", "user.unmute"),
    ("kick",   "user.kick"),
    ("warn",   "user.warn"),
    ("unwarn", "user.unwarn"),
    ("warns",  "user.warn"),
    ("purge",  "chat.purge"),
    ("role",   "roles.assign"),
    ("lang",   "settings.write"),
    ("save",     "notes.write"),
    ("get",      "notes.read"),
    ("notes",    "notes.read"),
    ("clear",    "notes.write"),
    ("filter",   "filters.write"),
    ("stop",     "filters.write"),
    ("filteradd", "filters.write"),
    ("filterbulk", "filters.write"),
    ("filteritems", "filters.write"),
    ("filters",  "settings.read"),
    ("addblock", "blocklist.write"),
    ("rmblock",  "blocklist.write"),
    ("blocklist", "settings.read"),
    ("rules",    ""),
    ("setrules", "rules.write"),
    ("welcome",  "welcome.write"),
    ("goodbye",  "welcome.write"),
    ("report",   ""),
    ("reportlist", "reports.handle"),
    ("resolve",  "reports.handle"),
    ("dismiss",  "reports.handle"),
    ("reopen",   "reports.handle"),
    ("addcmd",   "customcmd.write"),
    ("cmdadd",   "customcmd.write"),
    ("cmdbulk",  "customcmd.write"),
    ("done",     ""),
    ("cancel",   ""),
    ("cmditems", "customcmd.write"),
    ("delcmd",   "customcmd.write"),
    ("cmds",     ""),
    ("info",     "settings.read"),
    ("sban",     "user.ban"),
    ("dban",     "user.ban"),
    ("smute",    "user.mute"),
    ("dmute",    "user.mute"),
    ("skick",    "user.kick"),
    ("dkick",    "user.kick"),
    ("resetwarns", "user.unwarn"),
    ("warnings", "user.warn"),
    ("warnlimit", "settings.write"),
    ("promote",  "roles.assign"),
    ("demote",   "roles.assign"),
    ("adminlist", ""),
    ("roles",    "settings.read"),
    ("link",     "settings.read"),
    ("settitle", "settings.write"),
    ("setdesc",  "settings.write"),
    ("pinned",   ""),
    ("setflood", "settings.write"),
    ("floodaction", "settings.write"),
    ("antiraid", "settings.write"),
    ("reports",  "settings.write"),
    ("silent",   "settings.write"),
    ("adminpriv", "settings.write"),
    ("setclean", "settings.write"),
    ("cleanservice", "settings.write"),
    ("allow",    "settings.write"),
    ("unallow",  "settings.write"),
    ("allowlist", "settings.read"),
    ("stats",    "settings.read"),
    ("actions",  "audit.read"),
    ("locktypes", ""),
    ("vars",     ""),
    ("export",   "chat.export"),
    ("import",   "chat.import"),
    ("policy",   "settings.write"),
    ("simulate", "settings.read"),
    ("schedule",   "schedule.write"),
    ("scheduled",  "settings.read"),
    ("unschedule", "schedule.write"),
    ("newfed",     "fed.manage"),
    ("joinfed",    "fed.manage"),
    ("leavefed",   "fed.manage"),
    ("fedinfo",    "settings.read"),
    ("fban",       "fed.ban"),
    ("unfban",     "fed.ban"),
    ("fedadmin",   "fed.manage"),
    ("fedbans",    "settings.read"),
    ("rep",        ""),
    ("top",        ""),
    ("disable",   "settings.write"),
    ("enable",    "settings.write"),
    ("disabled",  "settings.read"),
    ("dwarn",     "user.warn"),
    ("swarn",     "user.warn"),
    ("spurge",    "chat.purge"),
    ("purgefrom", "chat.purge"),
    ("purgeto",   "chat.purge"),
    ("stopall",   "filters.write"),
    ("rmblockall", "blocklist.write"),
    ("rmallowall", "settings.write"),
    ("admincache", "settings.read"),
    ("approve",   "settings.write"),
    ("unapprove", "settings.write"),
    ("approved",  "settings.read"),
    ("setwelcome", "welcome.write"),
    ("setgoodbye", "welcome.write"),
    ("captchatime", "settings.write"),
    ("captchatries", "settings.write"),
    ("captchafail", "settings.write"),
    ("blockmode",  "blocklist.write"),
    ("setwarnmode", "settings.write"),
    ("echo",      "chat.say"),
    ("automation", "settings.read"),
    ("addauto",    "automation.write"),
    ("rmauto",     "automation.write"),
    ("analytics",  "settings.read"),
    ("broadcast",  "broadcast.send"),
    ("linkcheck",  "settings.read"),
    ("settings", "settings.read"),
    ("shabbat",  "settings.write"),
    ("hours",    "settings.write"),
    ("ai",       "settings.write"),
    ("aivision", "settings.write"),
    ("aivoice",  "settings.write"),
    ("aikeys",   "settings.read"),
    ("emergency", "emergency.toggle"),
    ("captcha",   "settings.write"),
    ("security",  "settings.read"),
    ("delall",    "chat.purge"),
    ("id",     ""),
    ("diag",   "settings.read"),
    ("health", ""),
]


def command_list(lang: str = "he") -> list[tuple[str, str]]:
    """‎[(שם, תיאור)]‎ בשפה המבוקשת, לרישום בתפריט של טלגרם."""
    return [(name, i18n.t(f"cmd.{name}", lang)) for name, _ in COMMANDS]


TG_LIMIT = 4096          # תקרת אורך הודעה בטלגרם
HELP_CHUNK = 3500        # מתחת לתקרה, עם מרווח לתגיות ולתרגום ארוך


def member_commands() -> list[str]:
    """הפקודות שכל חבר יכול להריץ.

    לא רק "בלי דרישת הרשאה": ‎/notes‎ ו-‎/get‎ דורשות ‎notes.read‎,
    שמותרת לחבר רגיל. הגדרה לפי מחרוזת ריקה בלבד הייתה מסתירה מהחברים
    שתי פקודות שהן דווקא בשבילם — ולכן ההגדרה היא **לפי הדירוג הנדרש**,
    כמו שהבדיקה בפועל עושה.

    זו הרשימה שנרשמת בתפריט ✏️ של טלגרם בקבוצות. עד כה נרשמו שם כל
    132 הפקודות לכל אחד, כלומר כל חבר ראה את ‎/ban‎ ואת ‎/lockdown‎
    בהשלמה האוטומטית — רשימה שרובה תיענה לו ב"אין לך הרשאה", וגם
    חשיפה מיותרת של מה שאפשר לעשות בקבוצה."""
    from permissions import PERMISSIONS, RANK
    return [n for n, perm in COMMANDS
            if not perm or PERMISSIONS.get(perm, 10 ** 9) <= RANK["member"]]


def help_pages(lang: str = i18n.DEFAULT,
               allowed: Optional[set] = None) -> list[str]:
    """העזרה, מפוצלת להודעות שנכנסות בתקרת טלגרם.

    עם 76 פקודות טקסט אחד חורג מ-4096 תווים, וטלגרם דוחה אותו —
    כלומר ‎/help‎ פשוט לא היה עונה. הפיצול הוא לפי שורות שלמות, כי
    חיתוך באמצע שורה קוטע פקודה.

    ‎allowed‎ מסנן לפי מה שהפונה **יכול** להריץ. חבר רגיל שקיבל רשימה
    של 132 פקודות קיבל בעיקר רשימה של דברים שייענו לו ב"אין לך
    הרשאה" — וגם ידע בדיוק מה אפשר לעשות בקבוצה הזאת. ‎None‎ = הכול,
    וזה מה שמשמש את התיעוד ואת הבדיקות."""
    head_txt = head("help.title", lang)
    rows = [f"/{name} — {i18n.t(f'cmd.{name}', lang)}"
            + (f"  <i>{perm}</i>" if perm else "")
            for name, perm in COMMANDS
            if allowed is None or name in allowed]
    hint = i18n.t("help.hint", lang)

    pages, cur = [], [head_txt, ""]
    size = len(head_txt) + 1
    for line in rows:
        if size + len(line) + 1 > HELP_CHUNK:
            pages.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    cur += ["", hint]
    pages.append("\n".join(cur))
    return [p for p in pages if p.strip()]


# ── עזרה בקטגוריות ────────────────────────────────────────────────────────
# 134 פקודות ברשימה אחת הן לא עזרה, הן מפרט. מי שרק רוצה להגדיר ברכה
# צריך לקרוא 134 שורות כדי למצוא שורה אחת, וזה מה שגורם לאנשים לוותר.
#
# לכן: תפריט של קטגוריות עם כפתורים, ובכל קטגוריה רק הפקודות שלה ורק
# אלה שהפונה יכול להריץ. הרשימה המלאה נשארת — היא מה שמזין את התפריט
# של טלגרם ואת התיעוד — אבל היא אינה מה שמוצג לאדם.
#
# יש בדיקה שמאמתת שכל פקודה נמצאת בקטגוריה **אחת בדיוק**. בלי זה
# פקודה חדשה נעלמת מהעזרה בלי שאף אחד ישים לב.
HELP_CATS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("start", "🚀", ("start", "help", "settings", "diag", "id", "health",
                     "lang", "info", "stats", "adminlist", "roles")),
    ("greet", "👋", ("welcome", "goodbye", "setwelcome", "setgoodbye",
                     "rules", "setrules", "vars", "cleanservice")),
    ("mod", "🛡️", ("ban", "unban", "mute", "unmute", "kick", "sban", "dban",
                   "smute", "dmute", "skick", "dkick", "del", "purge",
                   "spurge", "purgefrom", "purgeto", "delall")),
    ("warns", "⚠️", ("warn", "unwarn", "warns", "dwarn", "swarn",
                     "warnings", "warnlimit", "resetwarns", "setwarnmode")),
    ("locks", "🔒", ("lock", "unlock", "locks", "locktypes", "lockdown",
                     "silent")),
    ("filters", "🧹", ("filter", "filteradd", "filterbulk", "filteritems",
                       "stop",
                       "stopall", "filters", "addblock",
                       "rmblock", "blocklist", "rmblockall", "blockmode",
                       "linkcheck")),
    ("notes", "📝", ("save", "get", "notes", "clear", "addcmd", "cmdadd",
                     "cmdbulk", "cmditems", "done", "cancel", "delcmd",
                     "cmds", "say", "echo", "pin", "unpin", "pinned")),
    ("members", "👥", ("promote", "demote", "role", "approve", "unapprove",
                       "approved", "allow", "unallow", "allowlist",
                       "rmallowall", "admincache", "link", "settitle",
                       "setdesc", "rep", "top")),
    ("safety", "🚨", ("captcha", "captchatime", "captchatries",
                      "captchafail", "setflood", "floodaction", "antiraid",
                      "emergency", "security", "policy", "simulate")),
    ("reports", "📣", ("report", "reports", "reportlist", "resolve",
                       "dismiss", "reopen", "actions", "analytics")),
    ("ai", "🤖", ("ai", "aivision", "aivoice", "aikeys")),
    ("auto", "⏰", ("schedule", "scheduled", "unschedule", "automation",
                   "addauto", "rmauto", "broadcast", "setclean",
                   "adminpriv", "disable", "enable", "disabled",
                   "shabbat", "hours")),
    ("fed", "🌐", ("newfed", "joinfed", "leavefed", "fedinfo", "fban",
                   "unfban", "fedadmin", "fedbans", "export", "import")),
)

CAT_OF = {name: key for key, _icon, names in HELP_CATS for name in names}


def help_menu(lang: str = i18n.DEFAULT, allowed: Optional[set] = None,
              deep: str = "") -> Screen:
    """תפריט הקטגוריות. שתי עמודות, כי בטלפון שלוש נחתכות."""
    rows, line = [], []
    for key, icon, names in HELP_CATS:
        shown = [n for n in names if allowed is None or n in allowed]
        if not shown:
            continue
        line.append((f"{icon} {i18n.t('hcat.' + key, lang)}",
                     cb(0, "hc", key)))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    return Screen(i18n.t("help.menu", lang), rows)


def help_category(key: str, lang: str = i18n.DEFAULT,
                  allowed: Optional[set] = None) -> Optional[Screen]:
    for k, icon, names in HELP_CATS:
        if k != key:
            continue
        rows = [f"/{n} — {i18n.t('cmd.' + n, lang)}"
                for n in names if allowed is None or n in allowed]
        if not rows:
            return None
        txt = (f"{icon} <b>{i18n.t('hcat.' + key, lang)}</b>\n\n"
               + "\n".join(rows))
        return Screen(txt[:TG_LIMIT - 200],
                      [[(i18n.t("menu.back", lang), cb(0, "help"))]])
    return None


def help_screen(lang: str = i18n.DEFAULT) -> Screen:
    """העמוד הראשון בלבד. מי ששולח ‎/help‎ מקבל את כל העמודים."""
    return Screen(help_pages(lang)[0])


# ── שבת, חגים ושעות פתיחה ─────────────────────────────────────────────────
# מחזורי הלחיצה. מספר חופשי נקבע בפקודה; הכפתור מכסה את מה שרוב
# הקבוצות בוחרות, ושבעה ערכים הם עדיין לחיצה אחת ולא תפריט.
BEFORE_CYCLE = ("0", "5", "10", "15", "20", "30", "40")
AFTER_CYCLE = ("0", "5", "10", "15", "30", "60")
NOTICE_CYCLE = ("0", "15", "30", "60", "120")
# אין יותר רשימת טווחים מוכנים: הבחירה היא מלוח של 24 שעות, ומי
# שצריך דקות מדויקות מקליד ‎08:15-23:45‎.


def shabbat_screen(chat_id: int, cfg: dict,
                   lang: str = i18n.DEFAULT) -> Screen:
    """נעילת שבת וחג: מצב, עיר, היסטים, והודעות.

    הכול במסך אחד ובצ'אט הפרטי. מנהל שמכין את הקבוצה לשבת לא אמור
    לשלוח ולו פקודה אחת בתוך הקבוצה."""
    on = cfg.get("on")
    state = i18n.t("on" if on else "off", lang)
    nxt = cfg.get("next") or i18n.t("shab.unknown", lang)
    txt = (head("shab.title", lang) + "\n\n"
           + i18n.t("shab.hint", lang) + "\n\n"
           + i18n.t("shab.state", lang, state=state) + "\n"
           + i18n.t("shab.city", lang, city=cfg.get("city_name", "")) + "\n"
           + i18n.t("shab.next", lang, when=nxt))
    rows = [
        [(("🟢 " if on else "⚪ ") + i18n.t("shab.toggle", lang),
          cb(chat_id, "shabsw"))],
        [(f"🏙 {cfg.get('city_name', '')}", cb(chat_id, "shabcity")),
         (i18n.t("shab.cities", lang), cb(chat_id, "shabcities"))],
        [(i18n.t("shab.before", lang, n=cfg.get("before", 0)),
          cb(chat_id, "shabofs", "before")),
         (i18n.t("shab.after", lang, n=cfg.get("after", 0)),
          cb(chat_id, "shabofs", "after"))],
        [(i18n.t("shab.notice", lang, n=cfg.get("notice", 0)),
          cb(chat_id, "shabofs", "notice"))],
        [(i18n.t("shab.preview", lang), cb(chat_id, "shabprev"))],
        [(i18n.t("menu.back", lang), cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


def cities_screen(chat_id: int, current: str, city_list: list[tuple[str, str]],
                  lang: str = i18n.DEFAULT) -> Screen:
    """בורר עיר. העיר היא מה שקובע את הזמנים, ולכן היא בחירה מפורשת
    ולא ניחוש מאזור הזמן של השרת."""
    rows, line = [], []
    for key, name in city_list:
        mark = "● " if key == current else ""
        line.append((f"{mark}{name}", cb(chat_id, "setcity", key)))
        if len(line) == 2:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "shab"))])
    return Screen(head("shab.city_title", lang) + "\n\n"
                  + i18n.t("shab.city_hint", lang), rows)


def cities_pick(chat_id: int, chosen: list[str],
                city_list: list[tuple[str, str]],
                lang: str = i18n.DEFAULT) -> Screen:
    """אילו ערים יופיעו בלוח. בחירה מרובה — לחיצה מוסיפה או מורידה.

    העיר שלפיה הקבוצה ננעלת מסומנת תמיד ואינה יורדת מהרשימה: לוח
    שלא מכיל את העיר שקובעת את הנעילה מבלבל יותר משהוא עוזר."""
    rows, line = [], []
    for key, name in city_list:
        mark = "☑️ " if key in chosen else "▫️ "
        line.append((f"{mark}{name}", cb(chat_id, "shabc2", key)))
        if len(line) == 2:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "shab"))])
    return Screen(head("shab.cities_title", lang) + "\n\n"
                  + i18n.t("shab.cities_hint", lang), rows)


def zone_label(name: str, lang: str = i18n.DEFAULT) -> str:
    """השם שמוצג לאזור: תרגום אם יש, אחרת שם העיר שבמזהה.

    הבוט מיועד לעולם, ולכן אין כאן רשימת תוויות בשפה אחת: ‎Asia/Tokyo‎
    מוצג כ-‎Tokyo‎ בכל שפה שלא תרגמה אותו, וזה ממילא מה שאנשים
    מחפשים ברשימה."""
    import grouphours as _gh
    key = f"zone.{name}"
    shown = i18n.t(key, lang)
    return shown if shown != key else _gh.zone_city(name)


def zones_screen(chat_id: int, current: str, page: int = 0,
                 lang: str = i18n.DEFAULT) -> Screen:
    """בורר אזור זמן, מחולק לעמודים. בלעדיו כל לוח שעות הוא ניחוש.

    כל אזור מוצג עם ההיסט שלו **ברגע הזה** — ‎Tokyo · UTC+9‎ — כי זה
    מה שמאפשר לאדם לזהות את האזור שלו גם כשהוא לא בטוח בשם העיר."""
    import grouphours as _gh
    pages = _gh.zone_pages()
    page = max(0, min(page, pages - 1))
    rows, line = [], []
    for name in _gh.zone_page(page):
        mark = "● " if name == current else ""
        label = f"{mark}{zone_label(name, lang)} · {_gh.offset_label(_gh.zone_offset(name))}"
        line.append((label[:40], cb(chat_id, "setz", name)))
        if len(line) == 2:
            rows.append(line); line = []
    if line:
        rows.append(line)
    nav = []
    if page > 0:
        nav.append(("◀︎", cb(chat_id, "zones", str(page - 1))))
    nav.append((f"{page + 1}/{pages}", cb(chat_id, "zones", str(page))))
    if page < pages - 1:
        nav.append(("▶︎", cb(chat_id, "zones", str(page + 1))))
    rows.append(nav)
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "hours"))])
    return Screen(head("tz.title", lang) + "\n\n" + i18n.t("tz.hint", lang),
                  rows)


def hours_screen(chat_id: int, table: str, lang: str = i18n.DEFAULT,
                 zone: str = "", now: str = "") -> Screen:
    """לוח שבועי: יום אחד בשורה, לחיצה פותחת את היום.

    לוח ריק אינו שגיאה — הוא המצב הרגיל של רוב הקבוצות, ולכן הוא
    נאמר במילים ולא נשאר מסך ריק."""
    txt = (head("hours.title", lang) + "\n\n" + i18n.t("hours.hint", lang)
           + "\n\n" + (table or i18n.t("hours.none", lang)))
    if now:
        # השעה שהבוט רואה, בראש המסך. תקלת אזור זמן מתגלה כאן
        # בשנייה אחת במקום בלילה שבו הקבוצה לא נסגרה.
        txt += "\n\n" + i18n.t("tz.now", lang, time=now)
    rows, line = [], []
    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        line.append((i18n.t(f"day.{d}", lang), cb(chat_id, "hrday", d)))
        if len(line) == 4:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([("🌍 " + i18n.t("tz.button", lang,
                                 zone=zone or i18n.t("tz.unset", lang)),
                  cb(chat_id, "zones"))])
    # ההודעה שתישלח כשהלוח סוגר ופותח יושבת במסך משלה, ומי שמגדיר
    # לוח שעות הוא בדיוק מי שרוצה לכתוב אותה עכשיו.
    rows.append([(i18n.t("menu.state", lang), cb(chat_id, "stmsgs"))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    return Screen(txt, rows)


def hours_day(chat_id: int, day: str, current: str,
              lang: str = i18n.DEFAULT) -> Screen:
    """יום אחד: קודם **מה** עושים, ורק אחר כך השעות.

    הרשימה הקודמת הציעה שישה טווחים מוכנים, ומי שרצה "סגור מחצות עד
    שבע" לא מצא אותו שם — הצעה אינה בחירה. כאן בוחרים סוג, ואז
    שעות מלוח של 24, בלחיצות."""
    txt = (f"<b>{i18n.t(f'day.{day}', lang)}</b>\n\n"
           + i18n.t("hours.now", lang,
                    value=current or i18n.t("hours.off", lang)))
    rows = [
        [("🟢 " + i18n.t("hours.open_range", lang),
          cb(chat_id, "hrm", f"{day}.o"))],
        [("🔴 " + i18n.t("hours.shut_range", lang),
          cb(chat_id, "hrm", f"{day}.c"))],
        [(i18n.t("hours.closed", lang), cb(chat_id, "hrset", f"{day}=closed")),
         (i18n.t("hours.off", lang), cb(chat_id, "hrset", f"{day}=off"))],
        [("⌨️ " + i18n.t("hours.typed", lang), cb(chat_id, "hrtype", day))],
        [(i18n.t("menu.back", lang), cb(chat_id, "hours"))],
    ]
    return Screen(txt, rows)


def hour_grid(chat_id: int, day: str, mode: str, start: Optional[int] = None,
              half: bool = False, lang: str = i18n.DEFAULT) -> Screen:
    """לוח 24 שעות. ‎start=None‎ = בוחרים התחלה, אחרת בוחרים סיום.

    שש שורות של ארבע — כל שעה ביממה, ולא מה שמישהו ניחש שרוצים.
    ‎half‎ מזיז את כל הלוח לחצאי שעות (‎08:30‎ במקום ‎08:00‎) בלחיצה
    אחת, ולכן גם מי שצריך ‎08:30-23:30‎ נשאר בשתי לחיצות ולא עובר
    להקלדה. זמן שאינו עגול ואינו חצי הוא נדיר מספיק כדי להיות
    כפתור הקלדה ולא מסך נוסף.

    הערכים במזהה הם **דקות מחצות**, לא שעות: כך אותו מסך משרת כל
    רזולוציה שתתווסף בלי לשנות את הפרוטוקול."""
    which = "hours.pick_end" if start is not None else "hours.pick_start"
    head_txt = (f"<b>{i18n.t(f'day.{day}', lang)}</b> · "
                + i18n.t("hours.open_range" if mode == "o"
                         else "hours.shut_range", lang))
    body = i18n.t(which, lang)
    if start is not None:
        body += "\n" + i18n.t("hours.from", lang,
                               time=f"{start // 60:02d}:{start % 60:02d}")
    mm = 30 if half else 0
    rows, line = [], []
    for h in range(24):
        mins = h * 60 + mm
        arg = (f"{day}.{mode}.{mins}" if start is None
               else f"{day}.{mode}.{start}.{mins}")
        line.append((f"{h:02d}:{mm:02d}",
                     cb(chat_id, "hrs" if start is None else "hre", arg)))
        if len(line) == 4:
            rows.append(line); line = []
    if line:
        rows.append(line)
    flip = "0" if half else "1"
    toggle = f"{day}.{mode}.{flip}" if start is None \
        else f"{day}.{mode}.{start}.{flip}"
    rows.append([
        (i18n.t("hours.round" if half else "hours.half", lang),
         cb(chat_id, "hrh" if start is None else "hrh2", toggle)),
        ("⌨️ " + i18n.t("hours.typed", lang), cb(chat_id, "hrtype", day)),
    ])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "hrday", day))])
    return Screen(head_txt + "\n\n" + body, rows)


# ── עריכה בכפתורים ────────────────────────────────────────────────────────
# כל מה שהיה פקודה עם טקסט הפך לכפתור: לוחצים, הבוט מבקש, שולחים.
# המזהה הוא ‎ask:<שדה>‎ ו-‎clr:<שדה>‎, והשדות עצמם ב-‎prompts.FIELDS‎.
def _mark(value: str) -> str:
    return "✅" if (value or "").strip() else "—"


def texts_screen(chat_id: int, values: dict, lang: str = i18n.DEFAULT,
                 shabbat: bool = False) -> Screen:
    """ההודעות של הקבוצה. אין כאן פקודה אחת להקליד."""
    import prompts
    names = list(prompts.TEXT_FIELDS) + (list(prompts.SHAB_FIELDS)
                                         if shabbat else [])
    rows = []
    for name in names:
        val = values.get(prompts.FIELDS[name].key, "")
        rows.append([
            (f"{_mark(val)} {i18n.t(prompts.FIELDS[name].label_key, lang)}",
             cb(chat_id, "ask", name)),
            (i18n.t("btn.clear", lang), cb(chat_id, "clr", name)),
        ])
    rows.append([("👋 " + i18n.t("greet.title", lang),
                  cb(chat_id, "greet"))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    lines = [f"<b>{i18n.t(prompts.FIELDS[n].label_key, lang)}</b> — "
             + i18n.t(prompts.FIELDS[n].hint_key, lang) for n in names]
    return Screen(head("texts.title", lang) + "\n\n"
                  + i18n.t("texts.hint", lang) + "\n\n" + "\n".join(lines),
                  rows)


def numbers_screen(chat_id: int, values: dict,
                   lang: str = i18n.DEFAULT) -> Screen:
    """הספים, כל אחד עם ערכו ועם הסבר מה הוא עושה.

    שורה אחת לכל פריט ולא שתיים: שני כפתורים בשורה חותכים את השם
    באמצע, ו"הודעות בחל…" אינו הגדרה שאפשר להבין. רוחב המסך הוא
    מה שיש, ולכן הוא מוקדש לפריט אחד."""
    import prompts
    rows, lines = [], []
    for name in prompts.NUMBER_FIELDS:
        f = prompts.FIELDS[name]
        cur = values.get(f.key, "") or i18n.t("nums.default", lang)
        rows.append([(f"{i18n.t(f.label_key, lang)}: {cur}",
                      cb(chat_id, "ask", name))])
        lines.append(f"<b>{i18n.t(f.label_key, lang)}</b> — "
                     + i18n.t(f.hint_key, lang))
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    return Screen(head("nums.title", lang) + "\n\n"
                  + i18n.t("nums.hint", lang) + "\n\n" + "\n".join(lines),
                  rows)


GREET_CLEAN_CYCLE = ("0", "30", "120", "600", "3600")


def greet_screen(chat_id: int, state: dict,
                 lang: str = i18n.DEFAULT) -> Screen:
    """ברכת הכניסה: הנוסח, מי רואה אותה, וכמה זמן היא נשארת.

    **השם הזה חשוב.** הפונקציה נקראה פעם ‎welcome_screen‎ — בדיוק כמו
    בורר השפה שמוצג למשתמש חדש — והשנייה דרסה את הראשונה. התוצאה:
    ‎/start‎ של משתמש שמעולם לא בחר שפה קרס בשקט, והוא לא קיבל שום
    תשובה. יש בדיקה שמוודאת שאין שני מסכים באותו שם.

    "יש מנהלים שרוצים שכל הקבוצה תראה" — ולכן זו בחירה ולא התנהגות.
    וכשבוחרים שכולם יראו, השאלה הבאה היא כמה זמן היא נשארת: הכרזה
    על כל נכנס בקבוצה פעילה היא בדיוק הרעש שהבוט הזה נועד למנוע."""
    secs = state.get("clean", "0")
    who = "shown.me" if state.get("private") else "shown.all"
    body = [head("greet.title", lang), "",
            i18n.t("greet.who", lang, who=i18n.t(who, lang))]
    if secs != "0":
        body.append(i18n.t("greet.clean_on", lang,
                           what=_secs_label(secs, lang)))
    else:
        body.append(i18n.t("greet.clean_off", lang))
    text = (state.get("text") or "").strip()
    body += ["", (f"<blockquote>{_tpl.esc(text[:300])}</blockquote>"
                  if text else i18n.t("greet.no_text", lang))]
    rows = [
        [(("● " if state.get("private") else "") + i18n.t("shown.me", lang),
          cb(chat_id, "gwho", "1")),
         (("● " if not state.get("private") else "") + i18n.t("shown.all", lang),
          cb(chat_id, "gwho", "0"))],
        [(i18n.t("greet.clean_btn", lang,
                 what=_secs_label(secs, lang)), cb(chat_id, "gclean"))],
        [("✏️ " + i18n.t("field.welcome", lang), cb(chat_id, "ask", "welcome")),
         ("👁 " + i18n.t("state.preview", lang), cb(chat_id, "gprev"))],
        [(("🟢 " if state.get("on") else "⚪ ") + i18n.t("sw.welcome", lang),
          cb(chat_id, "sw", "welcome_on"))],
        [(i18n.t("menu.back", lang), cb(chat_id, "texts"))],
    ]
    return Screen("\n".join(body), rows)


def _secs_label(secs: str, lang: str = i18n.DEFAULT) -> str:
    n = int(secs or 0)
    if n <= 0:
        return i18n.t("greet.forever", lang)
    if n % 3600 == 0:
        return i18n.t("time.hours", lang, n=n // 3600)
    if n % 60 == 0:
        return i18n.t("time.minutes", lang, n=n // 60)
    return i18n.t("time.seconds", lang, n=n)


def ai_screen(chat_id: int, state: dict, lang: str = i18n.DEFAULT) -> Screen:
    """ניתוח תוכן: מה דלוק, ומה הקבוצה **היא**.

    ההקשר אינו קישוט: בלעדיו פוסטר של "קזינו" בקבוצת סרטים נראה
    למודל כמו פרסומת להימורים, וזו המחיקה שמכבה בוט ניהול."""
    on, off = i18n.t("on", lang), i18n.t("off", lang)
    ctx = (state.get("context") or "").strip()
    txt = (head("aim.title", lang) + "\n\n" + i18n.t("aim.hint", lang)
           + "\n\n" + i18n.t("aim.context", lang,
                             value=ctx or i18n.t("aim.no_context", lang)))
    if not state.get("keys"):
        txt += "\n\n" + i18n.t("aim.no_keys", lang)
    rows = [
        [(("🟢 " if state.get("ai") else "⚪ ") + i18n.t("sec.ai", lang),
          cb(chat_id, "sw", "ai")),
         (("🟢 " if state.get("aivision") else "⚪ ")
          + i18n.t("sw.aivision", lang), cb(chat_id, "sw", "aivision"))],
        [(("🟢 " if state.get("aivoice") else "⚪ ")
          + i18n.t("sw.aivoice", lang), cb(chat_id, "sw", "aivoice")),
         (("🟢 " if state.get("titles") else "⚪ ")
          + i18n.t("sw.titles_ok", lang), cb(chat_id, "sw", "ai_titles_ok"))],
        [("✏️ " + i18n.t("field.aictx", lang), cb(chat_id, "ask", "aictx"))],
        [(i18n.t("menu.back", lang), cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


def waiting_screen(chat_id: int, field: str, current: str,
                   lang: str = i18n.DEFAULT) -> Screen:
    """"שלח לי עכשיו". המסך שמחליף את הפקודה שהיה צריך להקליד."""
    import prompts
    f = prompts.FIELDS[field]
    txt = (f"<b>{i18n.t(f.label_key, lang)}</b>\n\n"
           + i18n.t(f.hint_key, lang) + "\n\n"
           + i18n.t("field.ask", lang))
    if f.cmd:
        # אותה פעולה בפקודה. מנהל שעושה את זה כל יום לא צריך לעבור
        # ארבעה מסכים, והוא גם לא צריך לחפש את הפקודה בעזרה.
        txt += "\n" + i18n.t("field.same_cmd", lang, cmd=f.cmd)
    if (current or "").strip():
        txt += "\n\n" + i18n.t("field.current", lang,
                               value=(current or "")[:300])
    rows = [[(i18n.t("btn.cancel", lang), cb(chat_id, "cancel"))]]
    return Screen(txt, rows)


# ── יומן האכיפה ───────────────────────────────────────────────────────────
# "אני רוצה לראות על מה הוא העיף אנשים." רשימה, ולחיצה פותחת את ההודעה
# עצמה — הטקסט, ואם הייתה מדיה אפשר לבקש שתישלח בפרטי.
ACTION_ICON = {"ban": "⛔", "kick": "👢", "mute": "🔇", "warn": "⚠️",
               "delete": "🗑", "tmute": "🔇", "tban": "⛔"}


def proof_list(chat_id: int, items: list, fmt_time,
               lang: str = i18n.DEFAULT, page: int = 0,
               more: bool = False) -> Screen:
    """מה הבוט עשה לאחרונה, שורה למקרה.

    הזמן והשם בשורה, כי בלעדיהם הרשימה היא רק רצף של פעולות; והתוכן
    בתצוגה מקדימה, כי לרוב השאלה "על מה?" נענית כבר בשורה."""
    if not items:
        return Screen(head("proof.title", lang) + "\n\n"
                      + i18n.t("proof.empty", lang),
                      [[(i18n.t("menu.back", lang), cb(chat_id, "main"))]])
    rows = []
    for it in items:
        icon = ACTION_ICON.get(it.action, "•")
        label = f"{icon} {it.name or it.user_id}: {it.preview(28)}"
        rows.append([(label[:60], cb(chat_id, "pf", str(it.id)))])
    nav = []
    if page > 0:
        nav.append(("◀︎", cb(chat_id, "proofs", str(page - 1))))
    if more:
        nav.append(("▶︎", cb(chat_id, "proofs", str(page + 1))))
    if nav:
        rows.append(nav)
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    lines = [f"{fmt_time(it.ts)} · {i18n.t('act.' + it.action, lang)} · "
             f"{it.name or it.user_id}" for it in items]
    return Screen(head("proof.title", lang) + "\n\n"
                  + i18n.t("proof.hint", lang) + "\n\n" + "\n".join(lines),
                  rows)


def proof_item(chat_id: int, it, when: str, others: int,
               lang: str = i18n.DEFAULT) -> Screen:
    """המקרה עצמו: מי, מה נעשה, למה — ומה היה כתוב שם.

    כפתורי הביטול כאן ולא במסך נפרד: הרגע שבו מנהל מגלה שהבוט טעה
    הוא הרגע שבו הוא רוצה לבטל, ולא אחרי חיפוש הפקודה הנכונה."""
    body = [
        f"<b>{i18n.t('act.' + it.action, lang)}</b> · {when}",
        i18n.t("proof.who", lang, who=it.name or it.user_id, id=it.user_id),
        i18n.t("proof.why", lang, why=it.reason or "—"),
    ]
    if it.risk:
        body.append(i18n.t("proof.risk", lang, pct=int(it.risk * 100)))
    if others > 1:
        body.append(i18n.t("proof.others", lang, n=others - 1))
    body.append("")
    body.append(i18n.t("proof.content", lang))
    if (it.text or "").strip():
        body.append(f"<blockquote>{_tpl.esc(it.text[:600])}</blockquote>")
    if it.media_kind:
        body.append(i18n.t("proof.media", lang, kind=it.media_kind))
    if not (it.text or "").strip() and not it.media_kind:
        body.append("—")
    rows = []
    if it.has_media:
        rows.append([("📎 " + i18n.t("proof.send_media", lang),
                      cb(chat_id, "pfm", str(it.id)))])
    rows.append([("↩︎ " + i18n.t("proof.undo", lang),
                  cb(chat_id, "pfu", str(it.id))),
                 ("👤 " + i18n.t("proof.user", lang),
                  cb(chat_id, "pfuser", str(it.user_id)))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "proofs"))])
    return Screen("\n".join(body), rows)


# ── תגובות ופקודות: המסך שמחליף את כל הפקודות ─────────────────────────────
# ההשראה היא Manybot — "צור פקודה, שלח את מה שהיא תחזיר, סיים" — ומה
# שחסר שם: אותו זרימה עובדת גם על **מילה** ולא רק על פקודה, היא
# מחזירה כמה הודעות ולא אחת, והיא כולה בצ'אט הפרטי בלי לגעת בקבוצה.
def replies_screen(chat_id: int, words: list[tuple[str, int]],
                   commands: list[tuple[str, int]],
                   lang: str = i18n.DEFAULT) -> Screen:
    """כל מה שהקבוצה עונה עליו: מילים ופקודות, עם מספר ההודעות."""
    rows = []
    # **מזהה ולא שם.** מזהה כפתור בטלגרם מוגבל ל-64 בתים, ואות בעברית
    # היא שני בתים: "צאלח א דין כובש ירושלים" הגיע ל-65, ‎cb‎ זרקה
    # חריגה, ובניית המסך כולו נפלה. כלומר הכפתור "תגובות אוטומטיות"
    # היה מת — אבל רק בקבוצות שבהן היה שם ארוך אחד, ולכן זה נראה
    # אקראי. מזהה הוא תמיד קצר, בכל שפה ובכל אורך שם.
    for item in words[:20]:
        name, n = item[0], item[1]
        # הדק מושהה נשאר ברשימה ומסומן. אחרת מנהל שהשהה אותו מחפש
        # אותו, לא מוצא, ובונה אותו מחדש.
        on = item[2] if len(item) > 2 else True
        alias = item[3] if len(item) > 3 else ""
        fid = item[4] if len(item) > 4 else 0
        mark = "💬" if on else "⏸"
        # הפקודה מוצגת לצד המילה: זו אותה תגובה, ומנהל שרואה רק את
        # המילה לא יודע שאפשר לקרוא לה גם כך.
        tail = f" · /{alias}" if alias else ""
        rows.append([(f"{mark} {name[:18]}{tail[:14]} · {n}",
                      cb(chat_id, "rep", f"f|{fid}"))])
    for item in commands[:20]:
        name, n = item[0], item[1]
        cid = item[2] if len(item) > 2 else 0
        rows.append([(f"⌨️ /{name[:21]} · {n}",
                      cb(chat_id, "rep", f"c|{cid}"))])
    # כפתור אחד ולא שניים. שתי רשימות שעושות אותו דבר הן בדיוק מה
    # שאיש לא הבין — ותגובה אחת ממילא עונה גם למילה וגם לפקודה.
    rows.append([("➕ " + i18n.t("rep.new", lang),
                  cb(chat_id, "ask", "repcmd"))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    body = (head("rep.title", lang) + "\n\n" + i18n.t("rep.hint", lang)
            + "\n\n" + i18n.t("rep.kinds", lang))
    if not words and not commands:
        body += "\n\n" + i18n.t("rep.empty", lang)
    return Screen(body, rows)


def reply_item(chat_id: int, kind: str, name: str, count: int,
               lang: str = i18n.DEFAULT, *, on: bool = True,
               rid: int = 0) -> Screen:
    """‎rid‎ ולא השם עובר בכפתורים — ראו ההערה ב-‎replies_screen‎."""
    label = ("/" + name) if kind == "c" else name
    tok = f"{kind}|{rid}"
    body = (f"<b>{label}</b>\n\n"
            + i18n.t("rep.count", lang, n=count) + "\n"
            + i18n.t("rep.how", lang,
                     what=i18n.t("rep.cmd_word" if kind == "c"
                                 else "rep.word_word", lang), name=label))
    rows = [
        [("➕ " + i18n.t("rep.add_more", lang),
          cb(chat_id, "repadd", tok))],
    ]
    # השהיה קודמת למחיקה, ובשורה נפרדת לפניה: "תעצור את הפילטר"
    # כמעט תמיד אומר "שיפסיק לירות", ולא "תאבד לי את כל ההודעות
    # שצירפתי אליו". מחיקה נשארת, פשוט לא ראשונה.
    if kind == "f":
        body += "\n\n" + i18n.t("rep.state_on" if on else "rep.state_off",
                                 lang)
        rows.append([(("⏸ " + i18n.t("rep.pause", lang)) if on
                      else ("▶️ " + i18n.t("rep.resume", lang)),
                      cb(chat_id, "reppause", tok))])
    rows.append([("👁 " + i18n.t("rep.preview", lang),
                  cb(chat_id, "repprev", tok)),
                 ("🗑 " + i18n.t("rep.delete", lang),
                  cb(chat_id, "repdel", tok))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "reps"))])
    return Screen(body, rows)


def collecting_screen(chat_id: int, label: str, count: int,
                      lang: str = i18n.DEFAULT) -> Screen:
    """"שלח עכשיו". המסך שמחליף את ‎/filterbulk‎ ואת ‎/done‎."""
    body = (i18n.t("rep.collecting", lang, name=label) + "\n\n"
            + i18n.t("rep.collect_hint", lang) + "\n\n"
            + i18n.t("rep.count", lang, n=count))
    return Screen(body, [[("✅ " + i18n.t("rep.finish", lang),
                           cb(chat_id, "repdone"))]])


# ── הודעות המצב: סגירה ופתיחה ─────────────────────────────────────────────
# "כשאני משבית את הקבוצה — שתישלח ההודעה שאני הגדרתי, וכשהיא נפתחת
# הודעה אחרת. לא משנה אם זה טקסט או תמונה."
#
# שלוש אפשרויות לכל הודעה ולא שתיים: נוסח משלי · ברירת המחדל · בלי
# הודעה בכלל. בלי השלישית, מי שרצה שקט היה צריך לכתוב רווח.
STATE_MSGS = (
    ("lockmsg", "state.lock_close"),
    ("openmsg", "state.lock_open"),
    ("hclose", "state.hours_close"),
    ("hopen", "state.hours_open"),
)

SILENT = "off"          # הערך שאומר "אל תשלח כלום"

# מפתח ברירת המחדל לכל הודעת מצב. כאן ולא בשני מקומות, כדי
# שהתצוגה המקדימה תציג בדיוק את מה שיישלח.
STATE_DEFAULTS = (
    ("lockmsg", "state.msg_lock"),
    ("openmsg", "state.msg_open"),
    ("hclose", "hours.msg_close"),
    ("hopen", "hours.msg_open"),
)


def state_msgs_screen(chat_id: int, values: dict,
                      lang: str = i18n.DEFAULT) -> Screen:
    rows = []
    for field, label in STATE_MSGS:
        val = (values.get(field) or "").strip()
        mark = "✅" if (val and val != SILENT) else "🔇"
        rows.append([(f"{mark} {i18n.t(label, lang)}",
                      cb(chat_id, "stmsg", field))])
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "main"))])
    return Screen(head("state.title", lang) + "\n\n"
                  + i18n.t("state.hint", lang) + "\n\n"
                  + i18n.t("state.legend", lang), rows)


def state_msg_screen(chat_id: int, field: str, value: str, media: str,
                     lang: str = i18n.DEFAULT) -> Screen:
    label = dict(STATE_MSGS).get(field, field)
    val = (value or "").strip()
    if (val and val != SILENT) or media:
        now = (f"<blockquote>{_tpl.esc(val[:300])}</blockquote>"
               if val and val != SILENT else "")
        if media:
            now += ("\n" if now else "") + i18n.t("state.has_media", lang)
    else:
        # ריק פירושו שקט, ולא "נוסח ברירת מחדל": הודעה שאיש לא כתב
        # לא אמורה להופיע בשם הקבוצה, וזו הייתה השאלה "מי כתב את
        # 'נסגרה על ידי ההנהלה' ואיפה משנים".
        now = i18n.t("state.silent", lang)
    # "שאוכל לראות מה מוגדר, לערוך את זה, לצפות, ולמחוק." ארבע
    # הפעולות במסך אחד, והצפייה שולחת את ההודעה **כמו שהיא** —
    # תמונה נראית כתמונה, ולא כשורה שכתוב בה "כולל מדיה".
    rows = [
        [("✏️ " + i18n.t("state.edit", lang), cb(chat_id, "ask", field)),
         ("👁 " + i18n.t("state.preview", lang),
          cb(chat_id, "stprev", field))],
        [("💡 " + i18n.t("state.suggest", lang),
          cb(chat_id, "stdef", field)),
         ("🔇 " + i18n.t("state.no_msg", lang), cb(chat_id, "stoff", field))],
        [(i18n.t("menu.back", lang), cb(chat_id, "stmsgs"))],
    ]
    return Screen(f"<b>{i18n.t(label, lang)}</b>\n\n" + now, rows)


# ── ניקוי הודעות השירות ───────────────────────────────────────────────────
# "X הצטרף", "Y שינה את תמונת הקבוצה", "הודעה נעוצה" — בקבוצה פעילה
# אלה עשרות שורות ביום שאיש לא קורא. מתג ראשי, ואז מה בדיוק.
SERVICE_CATS = (
    ("join", "svc.join"),
    ("about", "svc.about"),
    ("pin", "svc.pin"),
    ("call", "svc.call"),
    ("topic", "svc.topic"),
    ("other", "svc.other"),
)


def service_screen(chat_id: int, on: bool, values: dict,
                   lang: str = i18n.DEFAULT) -> Screen:
    txt = (head("svc.title", lang) + "\n\n" + i18n.t("svc.hint", lang)
           + "\n\n" + i18n.t("svc.note", lang))
    rows = [[(("🟢 " if on else "⚪ ") + i18n.t("svc.master", lang),
              cb(chat_id, "sw", "cleanservice"))]]
    line = []
    for key, label in SERVICE_CATS:
        mark = "☑️ " if (on and values.get(key, "1") == "1") else "▫️ "
        line.append((mark + i18n.t(label, lang), cb(chat_id, "svc", key)))
        if len(line) == 2:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([(i18n.t("menu.back", lang), cb(chat_id, "settings"))])
    return Screen(txt, rows)
