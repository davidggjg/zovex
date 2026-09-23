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


def home(groups: list[tuple[int, str]], lang: str = i18n.DEFAULT) -> Screen:
    """רשימת הקבוצות שהמשתמש מנהל."""
    title = head("home.title", lang)
    if not groups:
        return Screen(f"{title}\n\n" + i18n.t("home.empty", lang))
    rows = [[(f"👥 {name[:28]}", cb(cid, "main"))] for cid, name in groups]
    return Screen(
        f"{title}\n\n" + i18n.t("home.groups", lang, n=len(groups)) + "\n"
        + i18n.t("home.hint", lang), rows)


def main_menu(chat_id: int, title: str, stats: dict,
              lang: str = i18n.DEFAULT) -> Screen:
    txt = f"<b>{title}</b>\n\n" + "\n".join(
        f"{i18n.t(key, lang)}: {stats.get(field, 0)}"
        for key, field in (("stat.members", "members"),
                           ("stat.locks", "locks"),
                           ("stat.warns", "warns"),
                           ("stat.today", "actions_today")))
    rows = [
        [(i18n.t("menu.locks", lang), cb(chat_id, "locks")),
         (i18n.t("menu.warns", lang), cb(chat_id, "warns"))],
        [(i18n.t("menu.audit", lang), cb(chat_id, "audit")),
         (i18n.t("menu.settings", lang), cb(chat_id, "settings"))],
        [(i18n.t("menu.lockdown", lang), cb(chat_id, "ldown"))],
        [(i18n.t("menu.language", lang), cb(chat_id, "lang"))],
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


def welcome_screen() -> Screen:
    """המסך הראשון שמשתמש חדש רואה — בחירת שפה.

    הוא מוצג לפני כל טקסט אחר, ולכן אי אפשר לכתוב אותו בשפה אחת:
    השורה העליונה היא שם השפה בשפה עצמה. מי שלא קרא עברית מימיו
    עדיין מזהה את "English" או "العربية" ברשימה."""
    rows, line = [], []
    for code, name in i18n.available():
        line.append((name, cb(0, "pick", code)))
        if len(line) == 3:
            rows.append(line); line = []
    if line:
        rows.append(line)
    return Screen("<b>GroupOS</b>\n\n🌐 Choose your language", rows)


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
    ("filters",  "settings.read"),
    ("addblock", "blocklist.write"),
    ("rmblock",  "blocklist.write"),
    ("blocklist", "settings.read"),
    ("rules",    ""),
    ("setrules", "rules.write"),
    ("welcome",  "welcome.write"),
    ("goodbye",  "welcome.write"),
    ("report",   ""),
    ("info",     "settings.read"),
    ("id",     ""),
    ("health", ""),
]


def command_list(lang: str = "he") -> list[tuple[str, str]]:
    """‎[(שם, תיאור)]‎ בשפה המבוקשת, לרישום בתפריט של טלגרם."""
    return [(name, i18n.t(f"cmd.{name}", lang)) for name, _ in COMMANDS]


def help_screen(lang: str = i18n.DEFAULT) -> Screen:
    lines = [head("help.title", lang), ""]
    for name, perm in COMMANDS:
        tail = f"  <i>{perm}</i>" if perm else ""
        lines.append(f"/{name} — {i18n.t(f'cmd.{name}', lang)}{tail}")
    lines += ["", i18n.t("help.hint", lang)]
    return Screen("\n".join(lines))
