#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""content — Notes, Filters, Rules, Welcome ו-Goodbye.

## למה הארבעה יחד

כולם אותו דבר מבחינת נתונים: **טקסט שמור, אולי מדיה, אולי כפתורים,
שנשלח בתגובה לאירוע.** ההבדל היחיד הוא מה מפעיל אותם — פקודה, מילה,
כניסה לקבוצה או יציאה ממנה. פיצול לארבעה מודולים היה משכפל את אותו
קוד ארבע פעמים, ואז ‎{user}‎ היה עובד בברכה ולא בפילטר.

## כפתורים

נשמרים כטקסט בשורה אחת לכפתור:

    כותרת|https://example.com

הסיבה שזה טקסט ולא JSON: המנהל כותב את זה בטלגרם, ובטלגרם אין עורך
JSON. מה שלא נפרס נזרק בשקט — כפתור שבור לא אמור למנוע מהערה להישלח.

## למה ‎Filter‎ בודק מילה ולא ‎in‎

‎"היי"‎ בתוך ‎"היינו"‎ אינו אותה מילה. פילטר שנורה על כל הופעה הוא
פילטר שמנהלים מכבים אחרי יומיים. ברירת המחדל היא מילה שלמה, ומי
שרוצה אחרת מבקש ‎substring‎ במפורש.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

import blocklist as _bl

MATCH_KINDS = ("word", "substring", "regex", "starts")
FILTER_ACTIONS = ("reply", "delete", "warn", "mute", "kick", "ban",
                  "delete_reply")
VISIBILITY = ("public", "admin")

# הגדרות שהן "תוכן של הקבוצה" ולא התנהגות. נשמרות ב-settings.
RULES_KEY = "rules"
WELCOME_KEY = "welcome"
GOODBYE_KEY = "goodbye"


# ── כפתורים ───────────────────────────────────────────────────────────────
def parse_buttons(raw: str) -> list[list[tuple[str, str]]]:
    """‎'כותרת|url'‎ בכל שורה. שתי כותרות בשורה מופרדות ב-‎&&‎."""
    rows: list[list[tuple[str, str]]] = []
    for line in (raw or "").splitlines():
        row: list[tuple[str, str]] = []
        for cell in line.split("&&"):
            if "|" not in cell:
                continue
            label, url = cell.split("|", 1)
            label, url = label.strip(), url.strip()
            # רק http/https. ‎javascript:‎ ו-‎tg://‎ בידי משתמש הם וקטור.
            if label and re.match(r"^https?://\S+$", url):
                row.append((label[:64], url))
        if row:
            rows.append(row[:3])
    return rows[:8]


def format_buttons(rows: list[list[tuple[str, str]]]) -> str:
    return "\n".join(" && ".join(f"{t}|{u}" for t, u in row) for row in rows)


# ── Notes ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Note:
    name: str
    content: str
    media_id: Optional[str]
    media_kind: Optional[str]
    buttons: str
    visibility: str


def clean_name(name: str) -> str:
    """שם הערה. בלי ‎#‎ מוביל, בלי רווחים, אותיות קטנות."""
    return re.sub(r"\s+", "_", (name or "").strip().lstrip("#/")).lower()[:64]


class Notes:
    def __init__(self, db):
        self.db = db

    def save(self, chat_id: int, name: str, content: str, *,
             media_id: Optional[str] = None, media_kind: Optional[str] = None,
             buttons: str = "", visibility: str = "public",
             by: Optional[int] = None) -> bool:
        name = clean_name(name)
        if not name or (not content.strip() and not media_id):
            return False
        if visibility not in VISIBILITY:
            visibility = "public"
        self.db.run("""INSERT INTO notes
                       (chat_id,name,content,media_id,media_kind,buttons,
                        visibility,created_by,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT (chat_id,name) DO UPDATE SET
                         content=excluded.content, media_id=excluded.media_id,
                         media_kind=excluded.media_kind,
                         buttons=excluded.buttons,
                         visibility=excluded.visibility""",
                    (chat_id, name, content, media_id, media_kind, buttons,
                     visibility, by, time.time()))
        return True

    def get(self, chat_id: int, name: str) -> Optional[Note]:
        r = self.db.one("""SELECT name,content,media_id,media_kind,buttons,
                                  visibility FROM notes
                           WHERE chat_id=? AND name=?""",
                        (chat_id, clean_name(name)))
        return Note(r["name"], r["content"], r["media_id"], r["media_kind"],
                    r["buttons"] or "", r["visibility"]) if r else None

    def names(self, chat_id: int, include_admin: bool = False) -> list[str]:
        q = "SELECT name FROM notes WHERE chat_id=?"
        if not include_admin:
            q += " AND visibility='public'"
        return [r["name"] for r in self.db.q(q + " ORDER BY name", (chat_id,))]

    def delete(self, chat_id: int, name: str) -> int:
        return self.db.change("DELETE FROM notes WHERE chat_id=? AND name=?",
                              (chat_id, clean_name(name)))

    def clear(self, chat_id: int) -> int:
        return self.db.change("DELETE FROM notes WHERE chat_id=?", (chat_id,))


# ── Filters ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FilterHit:
    trigger: str
    action: str
    content: str
    # פילטר יכול להשיב גם בקובץ. ‎media_id‎ הוא ‎file_id‎ של טלגרם,
    # ולכן קובץ של ארבעה ג'יגה אינו שונה מתמונה: לא מאחסנים אותו.
    media_id: str = ""
    media_kind: str = ""
    buttons: str = ""


class Filters:
    def __init__(self, db):
        self.db = db

    def all(self, chat_id: int) -> list[dict]:
        return [dict(r) for r in self.db.q(
            """SELECT id,trigger,match_kind,action,content,media_id,
                      media_kind,buttons
               FROM filters WHERE chat_id=? AND enabled=1 ORDER BY id""",
            (chat_id,))]

    def add(self, chat_id: int, trigger: str, content: str, *,
            match_kind: str = "word", action: str = "reply",
            media_id: str = "", media_kind: str = "",
            buttons: str = "", allow_empty: bool = False) -> bool:
        trigger = (trigger or "").strip().lower()
        if not trigger or match_kind not in MATCH_KINDS:
            return False
        if action not in FILTER_ACTIONS:
            return False
        # תוכן ריק לגמרי אינו פילטר — אבל קובץ בלי טקסט כן, ו-‎
        # ‎allow_empty‎ הוא המקרה של "נוצר עכשיו כדי שימלאו אותו":
        # מצב איסוף יוצר את ההדק ואז מצרף אליו הודעות.
        if not (content or "").strip() and not media_id and not allow_empty \
                and action in ("reply", "delete_reply"):
            return False
        if match_kind == "regex":
            try:
                re.compile(trigger)
            except re.error:
                return False
        self.db.run("DELETE FROM filters WHERE chat_id=? AND trigger=?",
                    (chat_id, trigger))
        self.db.run("""INSERT INTO filters
                       (chat_id,trigger,match_kind,action,content,media_id,
                        media_kind,buttons,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (chat_id, trigger, match_kind, action, content,
                     media_id or "", media_kind or "", buttons or "",
                     time.time()))
        return True

    def remove(self, chat_id: int, trigger: str) -> int:
        trg = (trigger or "").strip().lower()
        self.db.change(
            """DELETE FROM filter_items
               WHERE chat_id=? AND trigger=? AND kind='filter'""",
            (chat_id, trg))
        return self.db.change(
            "DELETE FROM filters WHERE chat_id=? AND trigger=?", (chat_id, trg))

    # ── תשובה בכמה הודעות ────────────────────────────────────────────
    # קובץ, הסבר ותמונה הם שלוש הודעות בטלגרם. פילטר שדוחס אותן
    # לאחת מאבד את מה שהמנהל בנה, ולכן אפשר לצרף פריטים להדק אחד.
    def add_item(self, chat_id: int, trigger: str, content: str = "", *,
                 media_id: str = "", media_kind: str = "",
                 buttons: str = "", kind: str = "filter") -> int:
        """‎kind‎: ‎filter‎ למילה, ‎cmd‎ לפקודה מותאמת. אותו מנגנון לשניהם."""
        trg = (trigger or "").strip().lower()
        if not trg or (not content.strip() and not media_id):
            return 0
        r = self.db.one(
            """SELECT COALESCE(MAX(seq), 0) m FROM filter_items
               WHERE chat_id=? AND trigger=? AND kind=?""",
            (chat_id, trg, kind))
        return self.db.run(
            """INSERT INTO filter_items
               (chat_id,trigger,seq,content,media_id,media_kind,buttons,
                kind,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (chat_id, trg, (r["m"] if r else 0) + 1, content, media_id or "",
             media_kind or "", buttons or "", kind, time.time()))

    def items(self, chat_id: int, trigger: str,
              kind: str = "filter") -> list[dict]:
        """הפריטים הנוספים, לפי הסדר שנשמרו. ריק = תשובה אחת בלבד."""
        return [dict(r) for r in self.db.q(
            """SELECT content,media_id,media_kind,buttons FROM filter_items
               WHERE chat_id=? AND trigger=? AND kind=? ORDER BY seq""",
            (chat_id, (trigger or "").strip().lower(), kind))]

    def item_count(self, chat_id: int, trigger: str,
                   kind: str = "filter") -> int:
        r = self.db.one(
            """SELECT COUNT(*) c FROM filter_items
               WHERE chat_id=? AND trigger=? AND kind=?""",
            (chat_id, (trigger or "").strip().lower(), kind))
        return r["c"] if r else 0

    def clear_items(self, chat_id: int, trigger: str,
                    kind: str = "filter") -> int:
        return self.db.change(
            """DELETE FROM filter_items
               WHERE chat_id=? AND trigger=? AND kind=?""",
            (chat_id, (trigger or "").strip().lower(), kind))

    # ── השהיה ────────────────────────────────────────────────────────
    # "תעצור את הפילטר שלו" — מנהל שהדק מפריע לו רוצה לכבות אותו
    # עכשיו, לא למחוק אותו. מחיקה מאבדת את כל ההודעות שצורפו אליו,
    # ואז הדרך היחידה חזרה היא לבנות אותו מחדש. ‎enabled=0‎ משאיר
    # הכול במקום ורק מפסיק לירות.
    def set_enabled(self, chat_id: int, trigger: str, on: bool) -> int:
        return self.db.change(
            "UPDATE filters SET enabled=? WHERE chat_id=? AND trigger=?",
            (1 if on else 0, chat_id, (trigger or "").strip().lower()))

    def is_enabled(self, chat_id: int, trigger: str) -> bool:
        r = self.db.one(
            "SELECT enabled FROM filters WHERE chat_id=? AND trigger=?",
            (chat_id, (trigger or "").strip().lower()))
        return bool(r["enabled"]) if r else False

    def id_of(self, chat_id: int, trigger: str) -> int:
        r = self.db.one(
            "SELECT id FROM filters WHERE chat_id=? AND trigger=?",
            (chat_id, (trigger or "").strip().lower()))
        return r["id"] if r else 0

    def name_by_id(self, chat_id: int, fid: int) -> str:
        """שם ההדק לפי מזהה. זה מה שעובר בכפתור.

        הכפתור נשא קודם את **השם עצמו**, ומזהה כפתור בטלגרם מוגבל
        ל-64 בתים. שם סדרה בעברית הוא שני בתים לאות, ולכן
        "צאלח א דין כובש ירושלים" הגיע ל-65 — ובניית המסך זרקה
        חריגה, כלומר הכפתור "תגובות אוטומטיות" מת לגמרי. בקבוצה עם
        שמות קצרים הוא עבד, ובקבוצה אחת עם שם ארוך לא; זה היה
        ההבדל. מזהה הוא תמיד קצר, ובכל שפה."""
        r = self.db.one("SELECT trigger FROM filters WHERE chat_id=? AND id=?",
                        (chat_id, fid))
        return r["trigger"] if r else ""

    def listing(self, chat_id: int) -> list[tuple[str, bool, str, int]]:
        """כל ההדקים, **כולל המושהים**. המסך צריך להראות גם אותם:
        הדק שנעלם מהרשימה כשמשהים אותו נראה כמו הדק שנמחק."""
        return [(r["trigger"], bool(r["enabled"]), r["alias"] or "", r["id"])
                for r in self.db.q(
                    """SELECT id,trigger,enabled,alias FROM filters
                       WHERE chat_id=? ORDER BY id""", (chat_id,))]

    # ── שם שני: הפקודה ───────────────────────────────────────────────
    # אותה תגובה בדיוק, שני אופנים לקרוא לה. ‎/יאנקי‎ ו-"יאנקי" מחזירים
    # את אותן הודעות, כי זו רשומה אחת — לא שתיים שצריך לסנכרן.
    def set_alias(self, chat_id: int, trigger: str, alias: str) -> int:
        a = (alias or "").strip().lstrip("/").split("@")[0].lower()[:32]
        return self.db.change(
            "UPDATE filters SET alias=? WHERE chat_id=? AND trigger=?",
            (a, chat_id, (trigger or "").strip().lower()))

    def by_alias(self, chat_id: int, alias: str) -> Optional[FilterHit]:
        """הפקודה שמצביעה על תגובה. מכבד ‎enabled‎ כמו המילה."""
        a = (alias or "").strip().lstrip("/").split("@")[0].lower()
        if not a:
            return None
        r = self.db.one(
            """SELECT trigger,match_kind,action,content,media_id,media_kind,
                      buttons FROM filters
               WHERE chat_id=? AND alias=? AND enabled=1""", (chat_id, a))
        return _as_hit(r["trigger"], dict(r)) if r else None

    def alias_of(self, chat_id: int, trigger: str) -> str:
        r = self.db.one(
            "SELECT alias FROM filters WHERE chat_id=? AND trigger=?",
            (chat_id, (trigger or "").strip().lower()))
        return (r["alias"] or "") if r else ""

    def row(self, chat_id: int, trigger: str) -> Optional[dict]:
        """הדק אחד, גם אם הוא מושהה — לתצוגה מקדימה ולעריכה."""
        r = self.db.one(
            """SELECT id,trigger,match_kind,action,content,media_id,
                      media_kind,buttons,enabled
               FROM filters WHERE chat_id=? AND trigger=?""",
            (chat_id, (trigger or "").strip().lower()))
        return dict(r) if r else None

    def triggers(self, chat_id: int) -> list[str]:
        return [r["trigger"] for r in self.db.q(
            "SELECT trigger FROM filters WHERE chat_id=? ORDER BY trigger",
            (chat_id,))]

    def check(self, chat_id: int, text: str) -> Optional[FilterHit]:
        return match_filters(text, self.all(chat_id))


_RX_URL = re.compile(
    r"(?:https?://|t\.me/|www\.)\S+|\b[\w.-]+\.(?:com|net|org|co|il|me|io|"
    r"info|biz|ru|tv|xyz|link|site|app|online|club)\b/?\S*",
    re.I)


def _strip_urls(text: str) -> str:
    """מוציא כתובות מהטקסט לפני השוואת מילים שלמות."""
    return _RX_URL.sub(" ", text or "")


# ── התאמת שם ──────────────────────────────────────────────────────────────
# ‎blocklist.normalize‎ נבנה נגד **התחמקות**: הוא הופך ‎p0rn‎ ל-‎porn‎,
# ולכן גם ‎!‎ ל-‎i‎. על רשימת חסומים זה נכון; על שם של סדרה שמנהל
# הגדיר זה הרסני — ‎"ורדים וחטאים!"‎ הפך ל-‎"ורדים וחטאיםi"‎ ולא התאים
# לשום דבר. אנשים מסיימים בקשה בסימן קריאה או בשאלה כמעט תמיד, וזו
# הסיבה האמיתית ש"ההדקים לא עובדים".
#
# לשם של יצירה צריך בדיוק ההפך: לנקות סימני פיסוק ואימוג'י לרווח,
# ולא להמציא אותיות.
_RX_KEEP = re.compile(r"[^\w\s]", re.U)
_RX_SPACE = re.compile(r"\s+")

# אותיות השימוש בעברית. "אשמח **ל**ורדים וחטאים" הוא אותה בקשה
# בדיוק כמו "אשמח לורדים וחטאים", ובעברית זו הצורה הרגילה לכתוב —
# לא חריג. בלי זה ההדק נורה רק כשכותבים את השם חשוף.
_HEB_PREFIX = "בהוכלמש"


def plain(text: str) -> str:
    """נרמול לשמות: אותיות קטנות, פיסוק לרווח, רווחים מכווצים."""
    return _RX_SPACE.sub(" ", _RX_KEEP.sub(" ", (text or "").lower())).strip()


def _word_rx(trigger: str) -> Optional[re.Pattern]:
    """ההדק כמילה שלמה, עם אות שימוש אפשרית לפניו."""
    t = plain(trigger)
    if not t:
        return None
    body = r"\s+".join(re.escape(w) for w in t.split())
    return re.compile(r"(?<!\w)[" + _HEB_PREFIX + r"]?" + body + r"(?!\w)")


def _all_words_present(trigger: str, hay: str) -> bool:
    """כל מילות השם מופיעות בהודעה, בכל סדר.

    זה מה שעונה על "מישהו מבקש *אפשר בבקשה את הסדרה X*": הבקשה
    נכתבת בעשרים נוסחים שונים, אבל מילות השם תמיד שם. נדרשות **שתי
    מילים לפחות** בשם — לשם בן מילה אחת הכלל הזה מתנוון לחיפוש
    מילה בודדת, וזה כבר מה שהכלל הרגיל עושה."""
    words = plain(trigger).split()
    if len(words) < 2:
        return False
    return all(
        re.search(r"(?<!\w)[" + _HEB_PREFIX + r"]?" + re.escape(w) + r"(?!\w)",
                  hay)
        for w in words)


def match_filters(text: str, rules: list[dict]) -> Optional[FilterHit]:
    """הפילטר הראשון שמתאים. טהור, כדי שאפשר לבדוק בלי מסד."""
    if not text or not rules:
        return None
    low = text.lower()
    # מילה שלמה נבדקת **בלי הכתובות**. חבר שלח רשימה של כל קישורי
    # הקבוצות שלו, ובאחד מהם הופיע השם "חדשות" — וההדק על המילה
    # הזאת מחק לו את כל הרשימה. כתובת אינה מישהו שאמר את המילה.
    # ‎substring‎ ו-‎regex‎ נשארים על הטקסט המלא: מי שביקש אותם
    # במפורש כן רוצה להיתפס גם בתוך קישור.
    hay = plain(_strip_urls(text))
    # סיבוב שני, ורק אם הראשון לא מצא כלום: שם שכל מילותיו מופיעות
    # בהודעה. הוא רחב יותר, ולכן הוא לא רץ ראשון — התאמה מדויקת
    # צריכה תמיד לנצח התאמה משוערת.
    loose: Optional[FilterHit] = None
    for r in rules:
        trg, kind = r["trigger"], r.get("match_kind", "word")
        hit = False
        if kind == "regex":
            try:
                hit = re.search(trg, text, re.I) is not None
            except re.error:
                hit = False
        elif kind == "substring":
            hit = trg in low
        elif kind == "starts":
            hit = low.startswith(trg)
        else:
            rx = _word_rx(trg)
            hit = rx is not None and rx.search(hay) is not None
            if not hit and loose is None and _all_words_present(trg, hay):
                loose = _as_hit(trg, r)
        if hit:
            return _as_hit(trg, r)
    return loose


def _as_hit(trg: str, r: dict) -> FilterHit:
    return FilterHit(trg, r.get("action", "reply"),
                     r.get("content") or "",
                     r.get("media_id") or "",
                     r.get("media_kind") or "",
                     r.get("buttons") or "")
