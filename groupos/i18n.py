#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i18n — כל טקסט שהמשתמש רואה עובר מכאן.

## למה זה נבנה עכשיו ולא "אחר כך"

תרגום שמתווסף בסוף פירושו לעבור על כל שורת טקסט בכל מודול. תרגום
שנבנה בהתחלה פירושו ‎t(key)‎ במקום מחרוזת — ומשם הוספת שפה היא מילון
אחד, בלי לגעת בקוד.

## איך נבחרת השפה

    1. השפה שנקבעה במפורש — לקבוצה, או למשתמש בצ'אט הפרטי
    2. שפת הטלגרם של המשתמש
    3. אנגלית

**אנגלית ולא עברית.** מי שהטלגרם שלו בתאילנדית אינו מקבל עברית רק
מפני שכך נכתב הבוט. ברירת מחדל היא הנחה על המשתמש, ובבוט שמיועד
לעולם ההנחה הסבירה היחידה היא אנגלית.

## RTL

עברית, ערבית, פרסית ואורדו נכתבות מימין לשמאל. ‎is_rtl()‎ מאפשר למי
שמרכיב הודעה לדעת את זה — למשל כדי לא לשבור רשימה עם תווי כיווניות.

## מה קורה כשחסר תרגום

נופלים לאנגלית, ואם גם היא חסרה — למפתח עצמו. **לעולם לא שגיאה**:
טקסט חסר הוא פגם בתצוגה, לא סיבה להפיל פעולת ניהול.
"""
from __future__ import annotations

from typing import Any

from locales import EXTRA

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
        "status.ready": "<b>GroupOS מחובר ומוכן.</b>\nזוהו {n} מנהלים.\n\nלניהול — שלח לי /start בפרטי.",
        "status.not_admin": "<b>GroupOS בקבוצה, אבל עדיין לא מנהל.</b>\n\nכל עוד אני לא מנהל, טלגרם לא מוסרת לי הודעות רגילות — ולכן אני לא יכול לאכוף נעילות.\n\nהגדרות הקבוצה ← מנהלים ← הוסף מנהל ← בחר אותי.\nצריך: מחיקת הודעות והגבלת משתמשים.\n\nזוהו {n} מנהלים, ואת הניהול כבר אפשר לפתוח: /start בפרטי.",
        "status.missing": "<b>GroupOS מנהל, אבל חסרות לי הרשאות:</b>\n{list}\n\nבלעדיהן אוכל לזהות הפרות אבל לא לטפל בהן.",
        "right.delete": "מחיקת הודעות",
        "right.restrict": "הגבלת משתמשים",
        "right.ban": "חסימת משתמשים",
        "home.title": "GroupOS",
        "home.groups": "הקבוצות שלך ({n}):",
        "home.hint": "בחר קבוצה כדי לנהל אותה מכאן, בלי לשלוח פקודות בקבוצה עצמה.",
        "home.empty": "עוד לא ראיתי אותך מנהל באף קבוצה.\n\n1. הוסף אותי לקבוצה\n2. שלח שם <b>/start</b>\n3. חזור לכאן\n\nדווקא /start ולא הודעה רגילה: כל עוד אני לא מנהל, טלגרם מוסרת לי רק פקודות.",
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
        "note.saved": "ההערה <code>{name}</code> נשמרה.",
        "note.deleted": "ההערה נמחקה.",
        "note.missing": "אין הערה בשם <code>{name}</code>.",
        "note.list": "<b>הערות בקבוצה</b>\n{list}",
        "note.none": "אין עדיין הערות. לשמירה: השב להודעה עם /save <שם>",
        "note.usage": "שימוש: /save <שם> <תוכן>, או השב להודעה עם /save <שם>",
        "filter.saved": "פילטר על <code>{trigger}</code> נשמר.",
        "filter.removed": "הפילטר הוסר.",
        "filter.list": "<b>פילטרים</b>\n{list}",
        "filter.none": "אין פילטרים בקבוצה הזאת.",
        "filter.usage": "שימוש: /filter <מילה> <תגובה>\nאו השב להודעה עם /filter <מילה>",
        "block.added": "<code>{pattern}</code> נוסף לרשימת החסומים.",
        "block.removed": "הוסר מרשימת החסומים.",
        "block.list": "<b>ביטויים חסומים</b>\n{list}",
        "block.none": "אין ביטויים חסומים בקבוצה הזאת.",
        "block.usage": "שימוש: /addblock <מילה או ביטוי>",
        "block.hit": "{name} — הודעה שהכילה ביטוי חסום נמחקה.",
        "block.evaded": "{name} — ניסיון לעקוף את רשימת החסומים.",
        "block.bad_regex": "הביטוי הרגולרי אינו תקין.",
        "rules.none": "עוד לא נכתבו חוקים לקבוצה הזאת.",
        "rules.set": "החוקים עודכנו.",
        "rules.usage": "שימוש: /setrules <הטקסט>",
        "greet.set": "הטקסט נשמר.",
        "greet.off": "כובה.",
        "greet.usage": "שימוש: {cmd} <הטקסט>\nכיבוי: {cmd} off\n\nמשתנים: {vars}",
        "greet.default": "ברוך הבא {mention} ל־{chat}.",
        "flood.rate": "{name} — יותר מדי הודעות ברצף.",
        "flood.repeat": "{name} — אותה הודעה שוב ושוב.",
        "flood.mention": "{name} — יותר מדי תיוגים בהודעה אחת.",
        "flood.settings": "<b>הגנת הצפה</b>\nקצב: {rate} הודעות ב-{window} שניות\nחזרתיות: {repeat}\nתיוגים: {mentions}\nפעולה: {action}",
        "flood.off": "הגנת ההצפה כבויה.",
        "purge.usage": "שימוש: /purge <מספר>, או השב להודעה עם /purge",
        "report.sent": "הדיווח נשלח למנהלים.",
        "report.need_reply": "השב להודעה שעליה אתה מדווח.",
        "report.alert": "<b>דיווח</b>\nמדווח: {reporter}\nעל: {target}\n{reason}",
        "report.off": "הדיווחים כבויים בקבוצה הזאת.",
        "cmd.save": "שמירת הערה",
        "cmd.get": "שליפת הערה",
        "cmd.notes": "רשימת ההערות",
        "cmd.clear": "מחיקת הערה",
        "cmd.filter": "תגובה אוטומטית למילה",
        "cmd.stop": "ביטול פילטר",
        "cmd.filters": "רשימת הפילטרים",
        "cmd.addblock": "הוספת ביטוי חסום",
        "cmd.rmblock": "הסרת ביטוי חסום",
        "cmd.blocklist": "רשימת החסומים",
        "cmd.rules": "הצגת החוקים",
        "cmd.setrules": "כתיבת החוקים",
        "cmd.welcome": "הודעת כניסה",
        "cmd.goodbye": "הודעת יציאה",
        "cmd.flood": "הגנת הצפה",
        "cmd.report": "דיווח למנהלים",
        "cmd.info": "מידע על משתמש",
        "info.card": "<b>{name}</b>\nמזהה: <code>{id}</code>\nתפקיד: {role}\nהודעות: {msgs}\nאזהרות פתוחות: {warns}\nהצטרף: {joined}",
        "raid.detected": "<b>זוהתה הצטרפות המונית.</b>\n{n} משתמשים נכנסו בזמן קצר. הקבוצה הושבתה אוטומטית.\nלביטול: /lockdown off",
        "raid.alert": "⚠️ <b>חשד לפשיטה ב-{chat}</b>\n{n} הצטרפויות בזמן קצר. הקבוצה הושבתה.",
        "cmd.antiraid": "הגנת פשיטה",
        "locks.all_on": "🔒 נעל הכול",
        "locks.all_off": "🔓 פתח הכול",
        "locks.bulk": "{n} נעילות עודכנו.",
        "menu.lockdown": "🚨 השבתת קבוצה",
        "lockdown.on": "<b>הקבוצה הושבתה.</b>\nרק מנהלים יכולים לכתוב.\nלביטול: /lockdown off",
        "lockdown.off": "<b>ההשבתה בוטלה.</b>\nהקבוצה חזרה לפעולה.",
        "lockdown.short_on": "הקבוצה הושבתה",
        "lockdown.short_off": "ההשבתה בוטלה",
        "lockdown.state_on": "מושבתת",
        "lockdown.state_off": "פעילה",
        "say.usage": "כתוב מה לשלוח: /say ההודעה שלך",
        "del.done": "נמחק.",
        "pin.done": "ההודעה נעוצה.",
        "pin.off": "הנעיצה בוטלה.",
        "lock.usage": "שימוש: /lock <סוג> [פעולה]\n\nסוגים: {types}",
        "lock.done": "{name}: {action}",
        "lock.unknown": "אין נעילה בשם {name}.",
        "locks.state": "<b>נעילות פעילות</b>\n{list}",
        "locks.state_none": "אין נעילות פעילות בקבוצה הזאת.",
        "cmd.lock": "נעילת סוג תוכן",
        "cmd.unlock": "פתיחת סוג תוכן",
        "cmd.locks": "אילו נעילות פעילות",
        "cmd.lockdown": "השבתת הקבוצה כולה",
        "cmd.say": "שליחת הודעה בשם הבוט",
        "cmd.del": "מחיקת ההודעה שהשבת עליה",
        "cmd.pin": "נעיצת הודעה",
        "cmd.unpin": "ביטול נעיצה",
        # שמות הנעילות והקבוצות שלהן
        "group.media": "מדיה",
        "group.links": "קישורים",
        "group.interaction": "אינטראקציה",
        "group.text": "טקסט",
        "lock.photo": "תמונות",
        "lock.video": "סרטונים",
        "lock.gif": "GIF",
        "lock.sticker": "מדבקות",
        "lock.premium_sticker": "מדבקות פרימיום",
        "lock.audio": "קבצי שמע",
        "lock.voice": "הודעות קוליות",
        "lock.video_note": "הודעות וידאו",
        "lock.document": "קבצים",
        "lock.album": "אלבומים",
        "lock.url": "קישורים",
        "lock.invite": "קישורי הזמנה",
        "lock.mention": "תיוג משתמשים",
        "lock.forward": "הודעות מועברות",
        "lock.email": "כתובות מייל",
        "lock.phone": "מספרי טלפון",
        "lock.command": "פקודות",
        "lock.bot": "בוטים",
        "lock.button": "כפתורים",
        "lock.poll": "סקרים",
        "lock.game": "משחקים",
        "lock.contact": "אנשי קשר",
        "lock.location": "מיקום",
        "lock.anonchannel": "הודעות מערוץ",
        "lock.hashtag": "האשטגים",
        "lock.cashtag": "סימני מניה",
        "lock.cjk": "סינית ויפנית",
        "lock.cyrillic": "קירילית",
        "lock.arabic": "ערבית",
        "lock.emoji_only": "הודעות אימוג'י בלבד",
        "lock.caps": "צעקות באותיות גדולות",
        "lock.long": "הודעות ארוכות מאוד",
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
        "status.ready": "<b>GroupOS is connected and ready.</b>\n{n} admins found.\n\nSend me /start in private to manage.",
        "status.not_admin": "<b>GroupOS is in the group, but not an admin yet.</b>\n\nUntil I am an admin, Telegram does not deliver ordinary messages to me — so I cannot enforce locks.\n\nGroup settings → Administrators → Add admin → pick me.\nI need: delete messages and restrict members.\n\n{n} admins found, and you can already open the panel: /start in private.",
        "status.missing": "<b>GroupOS is an admin, but some rights are missing:</b>\n{list}\n\nWithout them I can spot violations but not act on them.",
        "right.delete": "Delete messages",
        "right.restrict": "Restrict members",
        "right.ban": "Ban users",
        "home.title": "GroupOS",
        "home.groups": "Your groups ({n}):",
        "home.hint": "Pick a group to manage it from here, without sending commands in the group.",
        "home.empty": "I have not seen you as an admin in any group yet.\n\n1. Add me to a group\n2. Send <b>/start</b> there\n3. Come back here\n\n/start and not an ordinary message: until I am an admin, Telegram only delivers commands to me.",
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
        "note.saved": "Note <code>{name}</code> saved.",
        "note.deleted": "Note deleted.",
        "note.missing": "There is no note called <code>{name}</code>.",
        "note.list": "<b>Notes in this group</b>\n{list}",
        "note.none": "No notes yet. To save one: reply to a message with /save <name>",
        "note.usage": "Usage: /save <name> <content>, or reply to a message with /save <name>",
        "filter.saved": "Filter on <code>{trigger}</code> saved.",
        "filter.removed": "Filter removed.",
        "filter.list": "<b>Filters</b>\n{list}",
        "filter.none": "There are no filters in this group.",
        "filter.usage": "Usage: /filter <word> <reply>\nor reply to a message with /filter <word>",
        "block.added": "<code>{pattern}</code> added to the blocklist.",
        "block.removed": "Removed from the blocklist.",
        "block.list": "<b>Blocked terms</b>\n{list}",
        "block.none": "There are no blocked terms in this group.",
        "block.usage": "Usage: /addblock <word or phrase>",
        "block.hit": "{name} — a message with a blocked term was deleted.",
        "block.evaded": "{name} — attempted to evade the blocklist.",
        "block.bad_regex": "That regular expression is not valid.",
        "rules.none": "No rules have been written for this group yet.",
        "rules.set": "Rules updated.",
        "rules.usage": "Usage: /setrules <text>",
        "greet.set": "Saved.",
        "greet.off": "Turned off.",
        "greet.usage": "Usage: {cmd} <text>\nTurn off: {cmd} off\n\nVariables: {vars}",
        "greet.default": "Welcome {mention} to {chat}.",
        "flood.rate": "{name} — too many messages in a row.",
        "flood.repeat": "{name} — the same message over and over.",
        "flood.mention": "{name} — too many mentions in one message.",
        "flood.settings": "<b>Flood protection</b>\nRate: {rate} messages in {window}s\nRepeats: {repeat}\nMentions: {mentions}\nAction: {action}",
        "flood.off": "Flood protection is off.",
        "purge.usage": "Usage: /purge <count>, or reply to a message with /purge",
        "report.sent": "Your report was sent to the admins.",
        "report.need_reply": "Reply to the message you are reporting.",
        "report.alert": "<b>Report</b>\nFrom: {reporter}\nAbout: {target}\n{reason}",
        "report.off": "Reports are disabled in this group.",
        "cmd.save": "Save a note",
        "cmd.get": "Get a note",
        "cmd.notes": "List notes",
        "cmd.clear": "Delete a note",
        "cmd.filter": "Auto-reply to a word",
        "cmd.stop": "Remove a filter",
        "cmd.filters": "List filters",
        "cmd.addblock": "Add a blocked term",
        "cmd.rmblock": "Remove a blocked term",
        "cmd.blocklist": "List blocked terms",
        "cmd.rules": "Show the rules",
        "cmd.setrules": "Write the rules",
        "cmd.welcome": "Welcome message",
        "cmd.goodbye": "Goodbye message",
        "cmd.flood": "Flood protection",
        "cmd.report": "Report to admins",
        "cmd.info": "Info about a user",
        "info.card": "<b>{name}</b>\nID: <code>{id}</code>\nRole: {role}\nMessages: {msgs}\nOpen warnings: {warns}\nJoined: {joined}",
        "raid.detected": "<b>Mass join detected.</b>\n{n} users joined in a short window. The group was locked down automatically.\nTo undo: /lockdown off",
        "raid.alert": "⚠️ <b>Possible raid in {chat}</b>\n{n} joins in a short window. The group was locked down.",
        "cmd.antiraid": "Raid protection",
        "locks.all_on": "🔒 Lock all",
        "locks.all_off": "🔓 Unlock all",
        "locks.bulk": "{n} locks updated.",
        "menu.lockdown": "🚨 Lockdown",
        "lockdown.on": "<b>The group is locked down.</b>\nOnly admins can write.\nTo undo: /lockdown off",
        "lockdown.off": "<b>Lockdown lifted.</b>\nThe group is open again.",
        "lockdown.short_on": "Group locked down",
        "lockdown.short_off": "Lockdown lifted",
        "lockdown.state_on": "locked down",
        "lockdown.state_off": "open",
        "say.usage": "Write what to send: /say your message",
        "del.done": "Deleted.",
        "pin.done": "Message pinned.",
        "pin.off": "Unpinned.",
        "lock.usage": "Usage: /lock <type> [action]\n\nTypes: {types}",
        "lock.done": "{name}: {action}",
        "lock.unknown": "There is no lock called {name}.",
        "locks.state": "<b>Active locks</b>\n{list}",
        "locks.state_none": "No locks are active in this group.",
        "cmd.lock": "Lock a content type",
        "cmd.unlock": "Unlock a content type",
        "cmd.locks": "Which locks are active",
        "cmd.lockdown": "Lock down the whole group",
        "cmd.say": "Send a message as the bot",
        "cmd.del": "Delete the replied message",
        "cmd.pin": "Pin a message",
        "cmd.unpin": "Unpin",
        "group.media": "Media",
        "group.links": "Links",
        "group.interaction": "Interaction",
        "group.text": "Text",
        "lock.photo": "Photos",
        "lock.video": "Videos",
        "lock.gif": "GIFs",
        "lock.sticker": "Stickers",
        "lock.premium_sticker": "Premium stickers",
        "lock.audio": "Audio files",
        "lock.voice": "Voice messages",
        "lock.video_note": "Video messages",
        "lock.document": "Files",
        "lock.album": "Albums",
        "lock.url": "Links",
        "lock.invite": "Invite links",
        "lock.mention": "Mentions",
        "lock.forward": "Forwarded messages",
        "lock.email": "Email addresses",
        "lock.phone": "Phone numbers",
        "lock.command": "Commands",
        "lock.bot": "Bots",
        "lock.button": "Buttons",
        "lock.poll": "Polls",
        "lock.game": "Games",
        "lock.contact": "Contacts",
        "lock.location": "Location",
        "lock.anonchannel": "Channel messages",
        "lock.hashtag": "Hashtags",
        "lock.cashtag": "Cashtags",
        "lock.cjk": "Chinese and Japanese",
        "lock.cyrillic": "Cyrillic",
        "lock.arabic": "Arabic",
        "lock.emoji_only": "Emoji-only messages",
        "lock.caps": "ALL-CAPS shouting",
        "lock.long": "Very long messages",
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

# שפה שאין לה מילון — נופלים לאנגלית ולא לעברית. ראה את ההסבר למעלה.
DEFAULT = "en"
FALLBACK = "en"

# המפתחות שמשתמש רואה בפועל. שפה חייבת לכסות אותם כדי להיות מוצעת
# בבורר — ממשק חצי מתורגם גרוע מממשק באנגלית.
CORE: tuple[str, ...] = (
    "home.groups", "home.hint",
    "menu.locks", "menu.warns", "menu.audit", "menu.settings",
    "menu.language", "menu.back", "menu.groups",
    "stat.members", "stat.locks", "stat.warns", "stat.today",
    "err.no_permission", "err.group_only", "err.need_reply", "err.failed",
    "err.need_admin", "err.not_your_group",
    "act.banned", "act.muted", "act.kicked", "act.unbanned", "act.unmuted",
    "act.reason", "act.off", "act.delete", "act.warn", "act.mute",
    "act.kick", "act.ban",
    "warn.added", "warn.triggered", "warn.removed", "warn.count",
    "purge.done", "lang.title", "lang.set", "help.title", "saved",
    "locks.title", "locks.hint",
    "settings.title", "settings.on", "settings.off",
)

# השפות שמעבר לשתי שפות הייחוס נטענות מקובץ נפרד, כדי שהוספת שפה
# תהיה עריכה של קובץ אחד שאין בו לוגיקה.
for _code, _table in EXTRA.items():
    STRINGS.setdefault(_code, {}).update(_table)


def normalize(code: str | None) -> str:
    """'he-IL' → 'he'. שפה לא מוכרת נופלת לברירת המחדל."""
    if not code:
        return DEFAULT
    base = str(code).replace("_", "-").split("-")[0].lower()
    return base if base in STRINGS else DEFAULT


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
    """בוחר שפה לפי קבוצה ומשתמש, עם ברירות מחדל.

    בצ'אט פרטי ‎chat_id‎ שווה ל-‎user_id‎, ולכן אותה טבלה משמשת גם
    לשפת קבוצה וגם לשפה שמשתמש בחר לעצמו — בלי טבלה נוספת."""

    def __init__(self, db):
        self.db = db

    def chosen(self, chat_id: int) -> str | None:
        """מה שנקבע במפורש, או ‎None‎. ההבחנה חשובה: משתמש שטרם בחר
        הוא משתמש שצריך לראות את בורר השפה."""
        raw = self.db.get(chat_id, "lang", None)
        return normalize(raw) if raw else None

    def for_chat(self, chat_id: int) -> str:
        return self.chosen(chat_id) or DEFAULT

    def resolve(self, chat_id: int, tg_code: str | None = None) -> str:
        """הנבחרת אם יש, אחרת שפת הטלגרם, אחרת אנגלית."""
        return self.chosen(chat_id) or normalize(tg_code)

    def for_user(self, chat_id: int, user_id: int,
                 tg_code: str | None = None) -> str:
        return self.resolve(chat_id, tg_code)

    def set_chat(self, chat_id: int, lang: str) -> None:
        self.db.set(chat_id, "lang", normalize(lang))


def available() -> list[tuple[str, str]]:
    """שפות שמכסות את ‎CORE‎, לתצוגה בבורר. שפה חלקית לא מוצעת.

    אנגלית ראשונה. במסך הפתיחה, לפני שידוע מי הפונה, השורה הראשונה
    היא מה שרוב העולם יזהה."""
    codes = [c for c, t in STRINGS.items() if all(k in t for k in CORE)]
    codes.sort(key=lambda c: (c != FALLBACK, list(STRINGS).index(c)))
    return [(c, LANG_NAMES.get(c, c)) for c in codes]


def coverage() -> dict[str, float]:
    """כמה מהמפתחות מתורגמים בכל שפה. משמש בבדיקות ובדוח."""
    base = set(STRINGS[DEFAULT])
    return {code: round(100 * len(base & set(table)) / len(base), 1)
            for code, table in STRINGS.items()}
