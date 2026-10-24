#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompts — "לחץ, ואז פשוט שלח לי את הטקסט".

## הבקשה שמאחורי המודול

"אני רוצה שכמה שיותר יהיה בכפתורים ולא פקודות שצריך להעתיק ולשלוח."

הפאנל כבר עשה את זה לכל מה שהוא **בחירה**: נעילה, מתג, שעה, עיר. מה
שנשאר בפקודות היה כל מה שהוא **טקסט חופשי** — ברכה, חוקים, הודעת
שבת — כי לכפתור אין שדה קלט.

הפתרון הוא לא שדה קלט אלא מצב: לחיצה על "✏️ ערוך" רושמת שהמשתמש
הזה, בצ'אט הפרטי, עומד לשלוח ערך לשדה מסוים. ההודעה הבאה שלו היא
הערך. אין פקודה להקליד, אין תחביר לזכור, ואי אפשר לטעות בשם ההגדרה.

## למה זה מודול טהור ולמה בזיכרון

אין כאן טלגרם ואין מסד: ‎start‎ · ‎get‎ · ‎clear‎, והמאגר הוא מילון.
המתנה לטקסט היא מצב של דקה, לא נתון שצריך לשרוד אתחול — ושירות
שעלה מחדש באמצע עריכה פשוט לא לוכד את ההודעה הבאה, וזה נכון יותר
מלתפוס הודעה אקראית חצי שעה אחרי שהמשתמש שכח.

## תפוגה

‎TTL‎ קצר בכוונה. מי שלחץ "ערוך ברכה", התחרט והמשיך לכתוב לבוט על
משהו אחר לא אמור לגלות שהמשפט שלו נשמר כברכת הקבוצה.

## אימות

כל שדה מצהיר על סוגו, ו-‎validate‎ מחזיר ‎(ערך, שגיאה)‎. מספר מחוץ
לטווח נחתך לטווח ולא נדחה: מנהל שכתב 9999 שניות התכוון למקסימום,
לא לשגיאה.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

TTL = 300.0          # חמש דקות להקליד תשובה. אחר כך זו הודעה רגילה

TEXT, NUMBER, SPEC = "text", "number", "spec"


@dataclass(frozen=True)
class Field:
    """שדה שאפשר לערוך בלחיצה.

    ‎key‎ הוא מפתח ההגדרה במסד, ‎label‎ מפתח תרגום לכותרת, ו-‎hint‎
    מפתח תרגום להסבר שמוצג ברגע ההמתנה — שם, ולא בתיעוד."""
    name: str
    key: str
    kind: str = TEXT
    label: str = ""
    hint: str = ""
    lo: int = 0
    hi: int = 0
    maxlen: int = 3000
    perm: str = "settings.write"

    @property
    def label_key(self) -> str:
        return self.label or f"field.{self.name}"

    @property
    def hint_key(self) -> str:
        return self.hint or f"field.{self.name}.hint"


# כל מה שהיה פקודה עם טקסט. שם השדה הוא מה שעובר במזהה הכפתור,
# ולכן הוא קצר: ‎g:<chat>:ask:<שם>‎ מוגבל ל-64 בייט.
FIELDS: dict[str, Field] = {
    "welcome": Field("welcome", "welcome", TEXT, perm="welcome.write"),
    "goodbye": Field("goodbye", "goodbye", TEXT, perm="welcome.write"),
    "rules": Field("rules", "rules", TEXT, perm="settings.write"),
    "shablock": Field("shablock", "shabbat_msg_lock", TEXT),
    "shabopen": Field("shabopen", "shabbat_msg_open", TEXT),
    "shabnote": Field("shabnote", "shabbat_msg_notice", TEXT),
    "aictx": Field("aictx", "ai_context", TEXT, maxlen=200),
    "warnpol": Field("warnpol", "warn_policy", SPEC, maxlen=60),
    "floodrate": Field("floodrate", "flood_rate", NUMBER, lo=2, hi=60),
    "floodwin": Field("floodwin", "flood_window", NUMBER, lo=3, hi=300),
    "floodrep": Field("floodrep", "flood_repeat", NUMBER, lo=2, hi=20),
    "floodment": Field("floodment", "flood_mentions", NUMBER, lo=2, hi=50),
    "floodtime": Field("floodtime", "flood_time", NUMBER, lo=60, hi=86400),
    "captime": Field("captime", "captcha_time", NUMBER, lo=20, hi=900),
    "captries": Field("captries", "captcha_tries", NUMBER, lo=1, hi=10),
    "dupcount": Field("dupcount", "dup_count", NUMBER, lo=2, hi=20),
    # לוח השעות: הערך הוא טווח ליום אחד, והיום עובר ב-‎arg‎.
    "hrange": Field("hrange", "hours", SPEC, maxlen=20,
                    label="hours.typed", hint="hours.typed_hint"),
}

# השדות שמוצגים במסך "הודעות", לפי הסדר
TEXT_FIELDS = ("welcome", "goodbye", "rules", "aictx")
SHAB_FIELDS = ("shabnote", "shablock", "shabopen")
NUMBER_FIELDS = ("floodrate", "floodwin", "floodrep", "floodment",
                 "floodtime", "captime", "captries", "dupcount")


@dataclass(frozen=True)
class Waiting:
    user_id: int
    chat_id: int        # הקבוצה שעליה עורכים, לא הצ'אט הפרטי
    field: str
    since: float
    # ‎arg‎ הוא מה שהשדה לבדו אינו מספיק לו: איזה **יום** בלוח
    # השעות עורכים. בלעדיו היה צריך שדה נפרד לכל יום בשבוע.
    arg: str = ""

    def expired(self, now: float, ttl: float = TTL) -> bool:
        return now - self.since > ttl


class Pending:
    """מי ממתין להקליד מה. מפתח אחד לכל משתמש.

    לחיצה על שדה אחר **מחליפה** את ההמתנה ולא מוסיפה לה: אדם אינו
    עורך שני דברים בו-זמנית, ושתי המתנות פתוחות הן הדרך הבטוחה
    לשמור טקסט במקום הלא נכון."""

    def __init__(self, ttl: float = TTL):
        self.ttl = ttl
        self._d: dict[int, Waiting] = {}

    def start(self, user_id: int, chat_id: int, field: str,
              *, arg: str = "",
              now: Optional[float] = None) -> Optional[Waiting]:
        if field not in FIELDS:
            return None
        w = Waiting(user_id, chat_id, field,
                    now if now is not None else time.time(), arg)
        self._d[user_id] = w
        return w

    def get(self, user_id: int,
            now: Optional[float] = None) -> Optional[Waiting]:
        w = self._d.get(user_id)
        if w is None:
            return None
        if w.expired(now if now is not None else time.time(), self.ttl):
            self._d.pop(user_id, None)
            return None
        return w

    def clear(self, user_id: int) -> None:
        self._d.pop(user_id, None)

    def count(self) -> int:
        return len(self._d)


def validate(field: str, raw: str) -> tuple[Optional[str], str]:
    """‎(ערך לשמירה, מפתח שגיאה)‎. ערך ריק מוחק את ההגדרה.

    מספר מחוץ לטווח **נחתך** ולא נדחה — מנהל שכתב 9999 התכוון
    למקסימום. טקסט ארוך מדי כן נדחה, כי חיתוך שקט של ברכה באמצע
    משפט נראה כמו באג."""
    f = FIELDS.get(field)
    if f is None:
        return None, "err.unknown"
    val = (raw or "").strip()
    if val.lower() in ("-", "off", "none", "ריק", "מחק"):
        return "", ""
    if f.kind == NUMBER:
        digits = val.replace(",", "").strip()
        if not digits.lstrip("-").isdigit():
            return None, "field.need_number"
        n = int(digits)
        if f.lo or f.hi:
            n = max(f.lo, min(f.hi, n))
        return str(n), ""
    if not val:
        return "", ""
    if len(val) > f.maxlen:
        return None, "field.too_long"
    return val, ""
