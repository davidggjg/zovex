#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i18n — כל טקסט שהמשתמש רואה עובר מכאן.

## למה זה נבנה עכשיו ולא "אחר כך"

תרגום שמתווסף בסוף פירושו לעבור על כל שורת טקסט בכל מודול. תרגום
שנבנה בהתחלה פירושו ‎t(key)‎ במקום מחרוזת — ומשם הוספת שפה היא מילון
אחד, בלי לגעת בקוד.

## איך נבחרת השפה

    1. שפת הקבוצה, אם המנהל קבע אחת
    2. שפת הטלגרם של המשתמש
    3. עברית

## RTL

עברית, ערבית, פרסית ואורדו נכתבות מימין לשמאל. ‎is_rtl()‎ מאפשר למי
שמרכיב הודעה לדעת את זה — למשל כדי לא לשבור רשימה עם תווי כיווניות.

## מה קורה כשחסר תרגום

נופלים לאנגלית, ואם גם היא חסרה — למפתח עצמו. **לעולם לא שגיאה**:
טקסט חסר הוא פגם בתצוגה, לא סיבה להפיל פעולת ניהול.
"""
from __future__ import annotations

from typing import Any

RTL_LANGS = {"he", "ar", "fa", "ur", "yi"}

LANG_NAMES = {
    "he": "עברית",
    "en": "English",
    "ar": "العربية",
    "ru": "Русский",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
    "tr": "Türkçe",
    "de": "Deutsch",
    "fa": "فارسی",
    "hi": "हिन्दी",
    "id": "Bahasa Indonesia",
}

# ── המילונים ───────────────────────────────────────────────────────────────
# מפתח הוא ‎תחום.פעולה‎. הוספת שפה = הוספת מילון, בלי לגעת בשום מודול אחר.
STRINGS: dict[str, dict[str, str]] = {
    "he": {
        "bot.name": "GroupOS",
        "start.private": "<b>GroupOS</b>\n\nהוסף אותי לקבוצה ותן לי הרשאות ניהול.\nאחר כך שלח כאן /start כדי לנהל אותה.",
        "start.group": "GroupOS מחובר. לניהול — שלח לי /start בפרטי.",
        "home.title": "GroupOS",
        "home.groups": "הקבוצות שלך ({n}):",
        "home.hint": "בחר קבוצה כדי לנהל אותה מכאן, בלי לשלוח פקודות בקבוצה עצמה.",
        "home.empty": "עוד לא ראיתי אותך מנהל באף קבוצה.\n\nהוסף אותי לקבוצה, תן לי הרשאות ניהול, ושלח שם הודעה אחת — ואז חזור לכאן.",
        "menu.locks": "🔒 נעילות",
        "menu.warns": "⚠️ אזהרות",
        "menu.audit": "📋 יומן",
        "menu.settings": "⚙️ הגדרות",
        "menu.language": "🌐 שפה",
        "menu.back": "↩︎ חזרה",
        "menu.groups": "↩︎ לרשימת הקבוצות",
        "stat.members": "חברים במעקב",
        "stat.locks": "נעילות פעילות",
        "stat.warns": "אזהרות פתוחות",
        "stat.today": "פעולות היום",
        "err.no_permission": "אין לך הרשאה לזה — {reason}.",
        "err.group_only": "הפקודה הזאת עובדת בתוך קבוצה. לניהול מכאן שלח /start.",
        "err.need_reply": "צריך להשיב להודעה של מי שרוצים לטפל בו.",
        "err.failed": "הפעולה נכשלה — כנראה שאין לי הרשאה מתאימה בקבוצה.",
        "err.need_admin": "נדרש admin",
        "act.banned": "נחסם",
        "act.muted": "הושתק",
        "act.kicked": "הורחק",
        "act.unbanned": "החסימה הוסרה.",
        "act.unmuted": "ההשתקה הוסרה.",
        "act.reason": " סיבה: {reason}",
        "warn.added": "אזהרה {n}.",
        "warn.triggered": "אזהרה {n}. הופעל: {action}.",
        "warn.removed": "בוטלה אזהרה. נשארו {n}.",
        "warn.count": "אזהרות פתוחות: {n}",
        "purge.done": "נמחקו {n} הודעות.",
        "purge.need_reply": "השב להודעה שממנה להתחיל למחוק.",
        "lang.title": "שפה",
        "lang.set": "השפה שונתה.",
        "help.title": "הפקודות",
        "help.hint": "כל הפקודות פועלות בתגובה להודעה. זמן נכתב כך: 30m, 2h, 7d.\n\nרוב הניהול נוח יותר מהפאנל הפרטי — שלח /start בפרטי.",
        "saved": "נשמר",
        "policy.updated": "המדיניות עודכנה",
        "locks.title": "נעילות",
        "locks.hint": "נעילה קובעת מה מותר לשלוח בקבוצה.\nלחיצה על סוג מחליפה את הפעולה שלו.",
        "locks.cycle": "לחיצה מחליפה: כבוי ← מחיקה ← אזהרה ← השתקה ← חסימה",
        "act.off": "כבוי",
        "act.delete": "מחיקה",
        "act.warn": "אזהרה",
        "act.mute": "השתקה",
        "act.kick": "הרחקה",
        "act.ban": "חסימה",
        "act.tmute": "השתקה זמנית",
        "act.tban": "חסימה זמנית",
        "warns.title": "אזהרות",
        "warns.policy": "המדיניות בקבוצה:",
        "warns.none": "אין מדיניות",
        "warns.top": "הכי הרבה אזהרות פתוחות:",
        "warns.preset_c": "רק אזהרות",
        "audit.title": "יומן · עשר אחרונות",
        "audit.empty": "יומן",
        "audit.none": "אין עדיין פעולות.",
        "settings.title": "הגדרות",
        "settings.clean_help": "<b>ניקוי אוטומטי</b> — אחרי כמה שניות למחוק את הפקודה ואת התשובה של הבוט מהקבוצה. זה מה ששומר על הקבוצה נקייה.",
        "settings.silent_help": "<b>מצב שקט</b> — כשהוא פעיל, פעולה אוטומטית מוחקת בלי להודיע בקבוצה. הכל נרשם ביומן.",
        "settings.clean": "ניקוי",
        "settings.silent": "מצב שקט",
        "settings.seconds": "{n} שניות",
        "settings.on": "פעיל",
        "settings.off": "כבוי",
        "lang.hint": "השפה שבה הבוט מדבר בקבוצה הזאת. משתמש שלא נקבעה לו שפה מקבל את שפת הטלגרם שלו.",
        "lock.violation": "{name} — {label} אסורים כאן. אזהרה {n}.",
        "role.changed": "התפקיד: {before} ← {after}",
        "role.pick": "השב להודעה ובחר: {roles}",
        "id.line": "משתמש: <code>{user}</code>\nצ'אט: <code>{chat}</code>",
        "health.line": "סכימה v{v} · שליחות {calls} · המתנה ממוצעת {ms}ms",
        "btn.unknown": "כפתור לא מוכר",
        "screen.unknown": "מסך לא מוכר",
        "err.not_your_group": "אין לך הרשאה לנהל את הקבוצה הזאת",
        # תיאורי הפקודות — גם ל-/help וגם לתפריט ✏️ של טלגרם
        "cmd.start": "פתיחת פאנל הניהול",
        "cmd.help": "כל הפקודות",
        "cmd.ban": "חסימה [זמן] [סיבה]",
        "cmd.unban": "ביטול חסימה",
        "cmd.mute": "השתקה [זמן] [סיבה]",
        "cmd.unmute": "ביטול השתקה",
        "cmd.kick": "הרחקה [סיבה]",
        "cmd.warn": "אזהרה [סיבה]",
        "cmd.unwarn": "ביטול האזהרה האחרונה",
        "cmd.warns": "כמה אזהרות פתוחות",
        "cmd.purge": "מחיקה מההודעה שהשבת עליה",
        "cmd.role": "שינוי תפקיד",
        "cmd.lang": "שפת הבוט בקבוצה",
        "cmd.id": "מזהה משתמש וצ'אט",
        "cmd.health": "מצב הבוט",
    },
    "en": {
        "bot.name": "GroupOS",
        "start.private": "<b>GroupOS</b>\n\nAdd me to a group and give me admin rights.\nThen send /start here to manage it.",
        "start.group": "GroupOS is connected. Send me /start in private to manage.",
        "home.title": "GroupOS",
        "home.groups": "Your groups ({n}):",
        "home.hint": "Pick a group to manage it from here, without sending commands in the group.",
        "home.empty": "I have not seen you as an admin in any group yet.\n\nAdd me to a group, give me admin rights, send one message there, then come back.",
        "menu.locks": "🔒 Locks",
        "menu.warns": "⚠️ Warnings",
        "menu.audit": "📋 Log",
        "menu.settings": "⚙️ Settings",
        "menu.language": "🌐 Language",
        "menu.back": "↩︎ Back",
        "menu.groups": "↩︎ All groups",
        "stat.members": "Members tracked",
        "stat.locks": "Active locks",
        "stat.warns": "Open warnings",
        "stat.today": "Actions today",
        "err.no_permission": "You are not allowed to do that — {reason}.",
        "err.group_only": "That command works inside a group. Send /start to manage from here.",
        "err.need_reply": "Reply to the message of the person you want to act on.",
        "err.failed": "That failed — I probably lack the right permission in the group.",
        "err.need_admin": "Admin required",
        "act.banned": "banned",
        "act.muted": "muted",
        "act.kicked": "removed",
        "act.unbanned": "Ban lifted.",
        "act.unmuted": "Mute lifted.",
        "act.reason": " Reason: {reason}",
        "warn.added": "Warning {n}.",
        "warn.triggered": "Warning {n}. Applied: {action}.",
        "warn.removed": "Warning removed. {n} left.",
        "warn.count": "Open warnings: {n}",
        "purge.done": "Deleted {n} messages.",
        "purge.need_reply": "Reply to the message to start deleting from.",
        "lang.title": "Language",
        "lang.set": "Language changed.",
        "help.title": "Commands",
        "help.hint": "All commands work as a reply to a message. Durations look like 30m, 2h, 7d.\n\nMost management is easier from the private panel — send /start in private.",
        "saved": "Saved",
        "policy.updated": "Policy updated",
        "locks.title": "Locks",
        "locks.hint": "A lock decides what may be sent in the group.\nTap a type to change what happens.",
        "locks.cycle": "Tap to change: off → delete → warn → mute → ban",
        "act.off": "off",
        "act.delete": "delete",
        "act.warn": "warn",
        "act.mute": "mute",
        "act.kick": "remove",
        "act.ban": "ban",
        "act.tmute": "temporary mute",
        "act.tban": "temporary ban",
        "warns.title": "Warnings",
        "warns.policy": "Policy in this group:",
        "warns.none": "no policy",
        "warns.top": "Most open warnings:",
        "warns.preset_c": "warnings only",
        "audit.title": "Log · last ten",
        "audit.empty": "Log",
        "audit.none": "Nothing has happened yet.",
        "settings.title": "Settings",
        "settings.clean_help": "<b>Auto-clean</b> — how many seconds until the command and the bot's reply are deleted from the group. This is what keeps the group clean.",
        "settings.silent_help": "<b>Silent mode</b> — when on, an automatic action deletes without announcing it in the group. Everything is still logged.",
        "settings.clean": "Auto-clean",
        "settings.silent": "Silent mode",
        "settings.seconds": "{n} seconds",
        "settings.on": "on",
        "settings.off": "off",
        "lang.hint": "The language the bot speaks in this group. A user with no set language gets their own Telegram language.",
        "lock.violation": "{name} — {label} are not allowed here. Warning {n}.",
        "role.changed": "Role: {before} → {after}",
        "role.pick": "Reply to a message and pick one of: {roles}",
        "id.line": "User: <code>{user}</code>\nChat: <code>{chat}</code>",
        "health.line": "schema v{v} · {calls} sends · avg wait {ms}ms",
        "btn.unknown": "Unknown button",
        "screen.unknown": "Unknown screen",
        "err.not_your_group": "You are not an admin of that group",
        "cmd.start": "Open the control panel",
        "cmd.help": "All commands",
        "cmd.ban": "Ban [duration] [reason]",
        "cmd.unban": "Lift a ban",
        "cmd.mute": "Mute [duration] [reason]",
        "cmd.unmute": "Lift a mute",
        "cmd.kick": "Remove from the group [reason]",
        "cmd.warn": "Warn [reason]",
        "cmd.unwarn": "Undo the last warning",
        "cmd.warns": "How many warnings are open",
        "cmd.purge": "Delete from the replied message",
        "cmd.role": "Change a role",
        "cmd.lang": "Bot language in this group",
        "cmd.id": "User and chat id",
        "cmd.health": "Bot status",
    },
    "ar": {
        "start.private": "<b>GroupOS</b>\n\nأضفني إلى مجموعة وامنحني صلاحيات الإدارة.\nثم أرسل /start هنا لإدارتها.",
        "start.group": "GroupOS متصل. أرسل لي /start في الخاص للإدارة.",
        "home.groups": "مجموعاتك ({n}):",
        "menu.locks": "🔒 الأقفال",
        "menu.warns": "⚠️ التحذيرات",
        "menu.audit": "📋 السجل",
        "menu.settings": "⚙️ الإعدادات",
        "menu.language": "🌐 اللغة",
        "menu.back": "↩︎ رجوع",
        "err.need_reply": "قم بالرد على رسالة الشخص المعني.",
        "act.banned": "تم الحظر",
        "act.muted": "تم الكتم",
        "act.kicked": "تم الطرد",
        "warn.count": "التحذيرات المفتوحة: {n}",
        "saved": "تم الحفظ",
    },
    "ru": {
        "start.private": "<b>GroupOS</b>\n\nДобавьте меня в группу и дайте права администратора.\nЗатем отправьте /start здесь.",
        "start.group": "GroupOS подключён. Напишите мне /start в личные сообщения.",
        "home.groups": "Ваши группы ({n}):",
        "menu.locks": "🔒 Замки",
        "menu.warns": "⚠️ Предупреждения",
        "menu.audit": "📋 Журнал",
        "menu.settings": "⚙️ Настройки",
        "menu.language": "🌐 Язык",
        "menu.back": "↩︎ Назад",
        "err.need_reply": "Ответьте на сообщение пользователя.",
        "act.banned": "заблокирован",
        "act.muted": "заглушён",
        "act.kicked": "удалён",
        "warn.count": "Открытых предупреждений: {n}",
        "saved": "Сохранено",
    },
}

DEFAULT = "he"
FALLBACK = "en"


def normalize(code: str | None) -> str:
    """'he-IL' → 'he'. שפה לא מוכרת נופלת לברירת המחדל."""
    if not code:
        return DEFAULT
    base = str(code).replace("_", "-").split("-")[0].lower()
    return base if base in STRINGS else (base if base in LANG_NAMES else DEFAULT)


def is_rtl(lang: str) -> bool:
    return normalize(lang) in RTL_LANGS


def t(key: str, lang: str = DEFAULT, **kw: Any) -> str:
    """הטקסט בשפה המבוקשת. חסר → אנגלית → המפתח עצמו."""
    lang = normalize(lang)
    for candidate in (lang, FALLBACK, DEFAULT):
        table = STRINGS.get(candidate)
        if table and key in table:
            raw = table[key]
            break
    else:
        return key
    try:
        return raw.format(**kw) if kw else raw
    except (KeyError, IndexError, ValueError):
        # מציין מקום חסר בתרגום אינו סיבה להפיל פעולה
        return raw


class Lang:
    """בוחר שפה לפי קבוצה ומשתמש, עם ברירות מחדל."""

    def __init__(self, db):
        self.db = db

    def for_chat(self, chat_id: int) -> str:
        return normalize(self.db.get(chat_id, "lang", DEFAULT))

    def for_user(self, chat_id: int, user_id: int,
                 tg_code: str | None = None) -> str:
        """שפת הקבוצה מנצחת; אחרת שפת הטלגרם של המשתמש."""
        explicit = self.db.get(chat_id, "lang", None)
        if explicit:
            return normalize(explicit)
        return normalize(tg_code)

    def set_chat(self, chat_id: int, lang: str) -> None:
        self.db.set(chat_id, "lang", normalize(lang))


def available() -> list[tuple[str, str]]:
    """שפות שיש להן מילון, לתצוגה בבורר."""
    return [(code, LANG_NAMES.get(code, code)) for code in STRINGS]


def coverage() -> dict[str, float]:
    """כמה מהמפתחות מתורגמים בכל שפה. משמש בבדיקות ובדוח."""
    base = set(STRINGS[DEFAULT])
    return {code: round(100 * len(base & set(table)) / len(base), 1)
            for code, table in STRINGS.items()}
