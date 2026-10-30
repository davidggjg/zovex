#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spamguard — זיהוי הודעה חריגה, בלי AI ובלי רשת.

## מה הוביל לזה

קבוצת בדיקה קיבלה תמונה עם כיתוב שמפרסם תוכן מיני של קטינים. היא
נשלחה שוב ושוב, והבוט הגיב רק אחרי שהחזרתיות עברה את סף ההצפה —
כלומר **טיפל בכמות ולא בתוכן**. הודעה אחת כזאת היא עילה לחסימה
מיידית; המערכת ראתה "משתמש שמדבר מהר".

שלושה פערים היו שם, וכולם מטופלים כאן:

    1. הכיתוב של תמונה לא נבדק מול שום רשימה — רק מול נעילות
    2. הטקסט היה מעורפל בכוונה (‎Ch1ld‎, ‎Te ens‎), ולכן שום
       השוואת מחרוזות לא תפסה אותו
    3. חזרתיות נמדדה על טקסט בלבד — אותה תמונה בדיוק, נשלחת עשר
       פעמים, לא נספרה כחזרה

## הנרמול הוא העיקר

מי שמפרסם תוכן אסור יודע שמסננים קיימים, ולכן כותב ‎Ch1ld‎ עם אחת,
מפזר רווחים, מערבב אותיות קיריליות שנראות לטיניות, ומשתיל תווים
בלתי נראים. ‎normalize‎ מפרק את כל אלה לצורה אחת, ורק אחריה משווים.
הנרמול הוא גם מה שמונע עקיפה חדשה בכל שבוע: לא מוסיפים דפוס לכל
איות — מבטלים את האיות.

## הציונים

    illegal   0.98   פרסום תוכן מיני של קטינים וכיוצא בו
    adult     0.55   פרסום מיני בוטה
    bait      0.35   "לחץ עכשיו", "נפתח ל-24 שעות"
    obfus     0.20   טקסט מעורפל בכוונה, לעצמו

‎illegal‎ אינו "ציון גבוה" אלא מסלול נפרד: הוא מחזיר גם
‎escalate=True‎, ומי שמחזיק את הקריאה אמור לחסום, למחוק ולדווח
למנהלים — בלי להמתין לצבירת אותות ובלי קשר לסף של הקבוצה.

## מה זה לא

זה לא מסווג תוכן ולא מחליף שיקול דעת. זה תופס **פרסומת**: טקסט
שנכתב כדי למכור. הודעה שמדברת על הנושא — דיווח, אזהרה, ידיעה — לא
אמורה להיתפס, ולכן הדפוסים דורשים צירוף של נושא ושל קריאה לפעולה,
ולא מילה בודדת.
"""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from typing import Optional

# ── נרמול ─────────────────────────────────────────────────────────────────
# אותות שנראות זהות ואינן. מי שמשתיל ‎е‎ קירילית באמצע מילה אנגלית
# עושה את זה בכוונה אחת בלבד.
CONFUSABLE = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ԁ": "d", "ɡ": "g", "ᴏ": "o", "ʏ": "y", "α": "a",
    "ο": "o", "ρ": "p", "ι": "i", "ν": "v", "κ": "k", "τ": "t",
}
LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
        "@": "a", "$": "s", "!": "i", "|": "i", "¡": "i"}

_RX_INVISIBLE = re.compile(r"[​-‏‪-‮⁠﻿­]")
_RX_NONWORD = re.compile(r"[^a-z֐-׿0-9 ]+")
_RX_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """טקסט → צורה אחת שאפשר להשוות.

    הסדר חשוב: קודם מפרקים יוניקוד (‎Ⓒ‎, ‎𝐂‎ ואחיותיהן), אחר כך
    מסירים בלתי־נראים, אחר כך מחליפים אותיות מתחזות, ורק בסוף
    פותרים ספרות. ‎1‎ הופך ל-‎i‎ אחרי שכבר ידוע שזו אות באמצע מילה —
    אחרת כל מספר בהודעה הופך לג'יבריש."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _RX_INVISIBLE.sub("", t).lower()
    t = "".join(CONFUSABLE.get(c, c) for c in t)
    out = []
    for i, c in enumerate(t):
        if c in LEET:
            prev = t[i - 1] if i else " "
            nxt = t[i + 1] if i + 1 < len(t) else " "
            # ספרה **בין שתי אותיות** היא איות (‎Ch1ld‎, ‎fr3e‎). ספרה
            # שאות נוגעת בה מצד אחד בלבד היא חלק ממספר: ‎1080p‎ הפך
            # ל-‎108op‎ בכלל הרופף יותר, ואיתו נעלם כל זיהוי של שיחה
            # על איכות וידאו.
            if prev.isalpha() and nxt.isalpha():
                out.append(LEET[c])
                continue
        out.append(c)
    t = _RX_NONWORD.sub(" ", "".join(out))
    return _RX_SPACES.sub(" ", t).strip()


def squeeze(text: str) -> str:
    """כמו ‎normalize‎, בלי רווחים כלל. תופס ‎T e e n s‎ ו-‎c-h-i-l-d‎."""
    return normalize(text).replace(" ", "")


# ── דפוסים ────────────────────────────────────────────────────────────────
# נבדקים על הצורה **הדחוסה**, ולכן פיזור רווחים אינו עוזר למפרסם.
MINOR = (
    "child", "children", "kid", "kids", "teen", "teens", "preteen",
    "underage", "minor", "loli", "lolita", "shota", "jailbait",
    "schoolgirl", "schoolboy", "pedo",
    "ילד", "ילדה", "ילדים", "קטין", "קטינה", "קטינים", "נער", "נערה",
)
SEXUAL = (
    "porn", "pornhub", "xxx", "nude", "nudes", "nsfw", "sex", "sexy",
    "onlyfans", "hentai", "incest", "rape", "scandal", "leaks", "leaked",
    "ladyboy", "hookup", "escort", "camgirl", "stripchat",
    "פורנו", "עירום", "עירומה", "סקס", "סרטון מיני", "תמונות עירום",
)
BAIT = (
    "greatvideos", "trywatching", "watchnow", "fullvideos", "hotvideos",
    "choosethestyle", "setsevery", "hurryup",
    "clickhere", "grabthislink", "getinright", "fullyunlocked", "unlocked",
    "joinnow", "linkinbio", "freeaccess", "limitedtime", "lastchance",
    "vipgroup", "privategroup", "dmme", "telegramlink", "fullvideo",
    "fullalbum", "mega nz", "meganz", "verifyage",
    "לחץכאן", "לינקבפרופיל", "הצטרפועכשיו", "קישורבתגובה",
)
AGE_RANGE = re.compile(r"\b(?:0?[5-9]|1[0-7])\s*[-–]\s*1[0-7]\b")
# ‎18+‎ · ‎21+‎ — שער גיל. הוא לא מונח מיני בפני עצמו, אבל אף אחד לא
# מסמן אותו על תוכן רגיל: הוא קיים כדי להבטיח מה שמעבר לכפתור.
ADULT_GATE = re.compile(r"\b(?:18|21)\s*\+")

ILLEGAL = 0.98
ADULT = 0.55
BAIT_W = 0.35
OBFUS = 0.20

# טקסט שנכתב כדי לעקוף: הרבה ספרות בתוך מילים, או מילים מפוזרות
_RX_INWORD_DIGIT = re.compile(r"[a-z֐-׿][0-9@$!|][a-z֐-׿]")
_RX_SPREAD = re.compile(r"(?:\b\w\b[ ]){3,}\w")


@dataclass(frozen=True)
class Verdict:
    """‎kind‎ הוא ‎illegal‎ · ‎adult‎ · ‎bait‎ · ‎obfuscated‎ · ‎dup‎.

    ‎escalate‎ אומר "אל תחכה לצבירת אותות". רק ‎illegal‎ מרים אותו."""
    kind: str
    weight: float
    detail: str = ""
    escalate: bool = False

    def __bool__(self) -> bool:
        return self.weight > 0


_RX_URL_ANY = re.compile(r"(?:https?://|www\.|t\.me/)\S+", re.I)


def strip_urls(text: str) -> str:
    """מסיר כתובות לפני השוואת מילים.

    ‎https://example.org‎ מנורמל ל-‎httpsexampleorg‎, ובתוכו יושבת
    המחרוזת ‎sex‎. הודעה תמימה עם קישור נחסמה בגלל זה. כתובת אינה
    מילים — היא נבדקת ב-‎solicits‎, לא בדפוסים."""
    return _RX_URL_ANY.sub(" ", text or "")


def _hits(blob: str, words: tuple[str, ...], spaced: str = "") -> list[str]:
    """איזה מונחים מופיעים. ‎blob‎ דחוס, ‎spaced‎ מנורמל עם רווחים.

    מונח קצר נבדק **עם גבולות מילה** על הצורה עם הרווחים: ‎sex‎
    כמחרוזת בתוך מילה אחרת הוא רעש, וכמילה שלמה הוא אות. מונח ארוך
    נבדק גם על הצורה הדחוסה, כי שם נמצא הערפול בפיזור רווחים
    (‎T e e n s‎) — ושם הסיכוי לפגיעה מקרית זניח."""
    out = []
    for w in words:
        flat = w.replace(" ", "")
        if len(flat) >= 6:
            if flat in blob:
                out.append(w)
            continue
        if spaced and re.search(
                r"(?<![a-z\u0590-\u05ff])" + re.escape(flat)
                + r"(?![a-z\u0590-\u05ff])", spaced):
            out.append(w)
    return out


# ZWJ בין שני אימוג'י הוא **הרכבת אימוג'י**, לא הסתרה. ‎🤦‍♀️‎ הוא
# פרצוף ועליו סימן נקבה, מחוברים בתו בלתי-נראה — וכך בנויים גם
# ‎👩‍💻‎, ‎👨‍👩‍👧‎ וכל האימוג'י הממוגדרים. הבדיקה סימנה כל הודעה כזאת
# כ"נכתבה כדי לעקוף מסנן", ובקבוצה אמיתית נמחקה בגללה הודעה תמימה
# לגמרי — "אם אין את עונה 5 אז איך יהיה בדיוק את העונות הבאות🤦‍♀️".
#
# הסתרה אמיתית נראית אחרת: ‎p‌o‌r‌n‎ — התו הבלתי-נראה יושב **בין
# אותיות**, כי שם הוא עושה את העבודה. אימוג'י אינו אות.
def _hides_in_word(text: str) -> bool:
    """תו בלתי-נראה שיושב בתוך מילה, ולא בין אימוג'י."""
    for m in _RX_INVISIBLE.finditer(text or ""):
        before = text[m.start() - 1] if m.start() else ""
        after = text[m.end()] if m.end() < len(text) else ""
        if before.isalnum() and after.isalnum():
            return True
    return False


def obfuscated(text: str) -> bool:
    """האם הטקסט נכתב כדי לא להיקרא במסנן."""
    low = (text or "").lower()
    if _hides_in_word(text or ""):
        return True
    if any(c in CONFUSABLE for c in low) and re.search(r"[a-z]", low):
        return True
    if _RX_INWORD_DIGIT.search(low):
        return True
    return bool(_RX_SPREAD.search(low))


def classify(text: str) -> Optional[Verdict]:
    """הפסק על טקסט אחד. ‎None‎ = אין מה לדווח.

    הצירוף הוא מה שמכריע, לא המילה. ‎'teens'‎ לבדה היא מילה; ‎'teens'‎
    יחד עם מונח מיני ועם קריאה לפעולה היא מודעה."""
    if not text or not text.strip():
        return None
    bare = strip_urls(text)
    blob = squeeze(bare)
    spaced = normalize(bare)
    if not blob:
        return None
    minor = _hits(blob, MINOR, spaced)
    sexual = _hits(blob, SEXUAL, spaced)
    bait = _hits(blob, BAIT, spaced)
    norm = normalize(text)
    age = bool(AGE_RANGE.search(norm))
    obf = obfuscated(text)
    # שער גיל נספר כמונח מיני. ההודעה שהגיעה מהשטח לא הכילה אף מילה
    # מפורשת — כל התוכן ישב ב**כפתורים**: "Great videos for 18+",
    # "Try watching". בלי זה שום דפוס לא נגע בה.
    if ADULT_GATE.search(text or "") or ADULT_GATE.search(norm):
        sexual = sexual + ["18+"]

    if sexual and (minor or age):
        # זה המסלול הנפרד. לא צובר, לא ממתין, לא תלוי בסף של הקבוצה.
        why = ",".join((sexual[:2] + minor[:2])) + (" age" if age else "")
        return Verdict("illegal", ILLEGAL, why[:48], escalate=True)
    if sexual and (bait or solicits(text)):
        # **מודעה** מינית, לא אזכור: מונח מיני יחד עם קישור, תיוג או
        # קריאה לפעולה. זה מה שמוצף כל עשר שניות בטלגרם, ולכן הוא
        # מסלול מהיר ולא ציון שמצטבר — חשבון שמפרסם כך אינו חבר
        # בקבוצה שצריך להזהיר, הוא ספאמר שצריך לצאת.
        #
        # הבלם היחיד: שיחה על יצירה שיש בה מונח מיני אבל אין בה שום
        # הזמנה לשום מקום. "סדרה על תעשיית הפורנו" אינה מודעה.
        hard = solicits(text) or not media_context(text)
        return Verdict("adult_ad" if hard else "adult",
                       0.95 if hard else ADULT,
                       ",".join(sexual[:2] + bait[:1])[:48],
                       escalate=hard)
    if sexual:
        return Verdict("adult", ADULT - 0.2 + (0.1 if obf else 0.0),
                       ",".join(sexual[:2])[:48])
    if bait and obf:
        return Verdict("bait", BAIT_W + 0.15, ",".join(bait[:2])[:48])
    if bait:
        return Verdict("bait", BAIT_W, ",".join(bait[:2])[:48])
    if obf:
        return Verdict("obfuscated", OBFUS, "")
    return None


# ── חזרתיות על תוכן, ולא על טקסט ──────────────────────────────────────────
def fingerprint(*, text: str = "", media_id: str = "") -> str:
    """טביעה של **ההודעה**, לא של הטקסט.

    ‎file_unique_id‎ של טלגרם זהה לאותה תמונה בכל קבוצה ובכל שולח,
    ולכן תמונה שנשלחת שוב ושוב נספרת כחזרה גם כשהכיתוב מתחלף בכל
    פעם — וזה בדיוק מה שהוחמץ."""
    base = (media_id or "") + "|" + squeeze(text)[:160]
    return hashlib.sha1(base.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Repeat:
    count: int
    chats: int
    fp: str


class RepeatTracker:
    """אותו תוכן, שוב ושוב — ממשתמש אחד, ועל פני כמה קבוצות.

    שני חלונות ולא אחד: ‎per_user‎ תופס את מי שמציף קבוצה, ו-‎global‎
    תופס את מי שמפזר את אותה מודעה בעשר קבוצות שהבוט נמצא בהן. לספאמר
    השני אף חלון של קבוצה בודדת לא היה מגיע לסף.

    הכול בזיכרון: זה חלון של דקות, ולא היסטוריה."""

    def __init__(self, window: float = 900.0, max_keys: int = 20000):
        self.window = window
        self.max_keys = max_keys
        self._seen: dict[str, deque] = {}

    def note(self, fp: str, chat_id: int, user_id: int,
             *, now: Optional[float] = None) -> Repeat:
        t = now if now is not None else time.monotonic()
        q = self._seen.setdefault(fp, deque())
        q.append((t, chat_id, user_id))
        while q and t - q[0][0] > self.window:
            q.popleft()
        if len(self._seen) > self.max_keys:
            for k in list(self._seen)[:len(self._seen) - self.max_keys]:
                self._seen.pop(k, None)
        mine = [r for r in q if r[2] == user_id]
        return Repeat(len(mine), len({r[1] for r in mine}), fp)

    def forget(self, fp: str) -> None:
        self._seen.pop(fp, None)

    def stats(self) -> dict:
        return {"tracked": len(self._seen)}


# סף החזרתיות שמעליו זו כבר הפצה ולא שיחה
DUP_COUNT = 2           # אותו תוכן, מאותו משתמש, בחלון
DUP_CHATS = 2           # אותו תוכן בכמה קבוצות — חמור יותר


def repeat_verdict(rep: Repeat, *, count: int = DUP_COUNT,
                   chats: int = DUP_CHATS) -> Optional[Verdict]:
    """חזרתיות כאות, עם משקל שעולה עם הפיזור ולא רק עם הכמות.

    הסף ירד לשתיים: בהצפה של היום אותה תמונה נשלחת כל עשר שניות,
    וסף של שלוש פירושו שתי הודעות שעוברות בכל סבב. השלישית כבר
    שוקלת כמעט כמו הפצה."""
    if rep.chats >= chats and rep.count >= 2:
        return Verdict("dup", 0.85, f"x{rep.count}/{rep.chats} chats")
    if rep.count >= count:
        w = min(0.55 + 0.15 * (rep.count - count), 0.9)
        return Verdict("dup", w, f"x{rep.count}")
    return None

# ── הקשר: על מה הקבוצה מדברת ──────────────────────────────────────────────
# קבוצת סרטים מדברת על "קזינו", על "שיימלס" ועל "פוקר פייס" — אלה
# שמות, לא מודעות. בלי ההבחנה הזאת כל קבוצת תוכן הייתה מוחקת לחבריה
# את השיחה עצמה, וזה בדיוק סוג הטעות שמכבה בוט ניהול אחרי יומיים.
MEDIA_WORDS = (
    "season", "episode", "series", "movie", "film", "trailer", "subtitle",
    "subs", "imdb", "bluray", "webrip", "hdrip", "dubbed", "boxset",
    "netflix", "disney", "hbo", "prime video", "episodes",
    "עונה", "עונות", "פרק", "פרקים", "סדרה", "סדרות", "סרט", "סרטים",
    "כתוביות", "תרגום", "מדובב", "דיבוב", "טריילר", "במאי", "שחקן",
    "שחקנית", "נטפליקס", "דיסני", "צפייה", "לצפייה", "שידור",
    # בקשה היא הצורה הנפוצה ביותר של שיחה בקבוצת תוכן, והיא בדיוק
    # מה שנמחק בטעות: "אשמח לפרק 39", "מישהו יכול להעלות את העונה".
    "אשמח", "מחפש", "מחפשת", "יש למישהו", "אפשר לקבל", "מבקש",
    "להעלות", "הועלה", "חלק", "דיסק", "איכות",
)
_RX_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_RX_SXXEYY = re.compile(r"\bs\d{1,2}\s?e\d{1,2}\b", re.I)
_RX_QUALITY = re.compile(r"\b(?:480|720|1080|2160)p\b|\b4k\b|\bhdr\b", re.I)

# קריאה לפעולה: מה שהופך "דיבור על" ל"מודעה בשביל".
_RX_LINK = re.compile(r"https?://|www\.|t\.me/|@[A-Za-z][A-Za-z0-9_]{4,}", re.I)
CTA_WORDS = (
    "joinnow", "clickhere", "signup", "register", "deposit", "bonus",
    "freespins", "promocode", "bet", "jackpot", "subscribe", "dm",
    "הצטרפו", "הצטרף", "לחצו", "לחץ", "הירשמו", "הרשמה", "בונוס",
    "הפקדה", "קוד קופון", "בפרטי", "פנו אליי", "מקומות אחרונים",
    # הפניה לערוץ משלך היא קריאה לפעולה לכל דבר, וזה בדיוק הנוסח
    # שמודעות הפורנו משתמשות בו בקבוצת תוכן: "סרט מלא בערוץ שלנו".
    # בלעדיו הן נספרו כ"שיחה על סרטים" וקיבלו חסינות מהבלם.
    "בערוץשלנו", "בערוץ שלנו", "בקבוצהשלנו", "בקבוצה שלנו", "בערוץ",
    "לצפייהישירה", "לצפייה ישירה", "צפייהישירה",
    "למבוגריםבלבד", "למבוגרים בלבד", "כניסהחופשית",
    "inourchannel", "ourchannel", "fullinbio", "watchfree",
)


def media_context(text: str) -> bool:
    """האם ההודעה נשמעת כמו שיחה על סרט או סדרה.

    לא 'האם היא מזכירה סרט'. שנה, מספר עונה, רזולוציה או מילה מעולם
    התוכן — אלה סימנים שההודעה **מדברת על** יצירה, ולכן שם שנשמע
    כמו הימורים הוא שם."""
    norm = normalize(text)
    if not norm:
        return False
    if _RX_SXXEYY.search(norm) or _RX_QUALITY.search(norm):
        return True
    # מילה אחת מעולם התוכן מספיקה, ובכוונה: הבלם הזה נבדק תמיד יחד
    # עם ‎solicits‎, כך שמודעה שכתוב בה "סרטים" עדיין נתפסת על הקישור
    # או על הקריאה לפעולה שבה. דרישת שתי מילים פספסה בדיוק את המשפט
    # הנפוץ ביותר בקבוצה כזאת — "מישהו ראה את X? סדרה מעולה".
    return any(w in norm for w in MEDIA_WORDS) or bool(_RX_YEAR.search(norm))


def solicits(text: str) -> bool:
    """האם ההודעה מזמינה לפעולה — קישור, תיוג, או קריאה מפורשת.

    זה הקו בין "ראיתי את קזינו של סקורסזה" לבין "קזינו — הצטרפו
    עכשיו, בונוס 200%". הראשונה היא שיחה; השנייה היא מה שנמחק."""
    if _RX_LINK.search(text or ""):
        return True
    blob = squeeze(text)
    return any(w.replace(" ", "") in blob for w in CTA_WORDS)


def talks_not_sells(text: str) -> bool:
    """שיחה על תוכן ולא מודעה בשבילו — הבלם לפני מחיקה על שם של סרט.

    שלושה תנאים, וכולם נדרשים: ההודעה נשמעת כמו דיבור על יצירה, אין
    בה קריאה לפעולה, **ואין בה מונח מיני מפורש**. התנאי השלישי הוא
    מה שמונע מ"סרטי פורנו מלאים בערוץ שלנו" להיחשב שיחה על סרטים רק
    מפני שכתובה בה המילה "סרטי". שם של יצירה אינו מכיל את המילה
    פורנו; מודעה — כן."""
    if not media_context(text) or solicits(text):
        return False
    # שער גיל **יחד עם** מונח מיני או פיתיון הורג את הבלם. לא שער
    # גיל לבדו: "הסרט מדורג 18+ בגלל אלימות" הוא שיחה. אבל ‎18+‎ ליד
    # מונח מיני אינו דירוג, הוא הבטחה — וזה הנוסח שהחזיק את מודעות
    # הפורנו מאחורי הבלם רק מפני שהופיעה בהן המילה "סרט".
    if (ADULT_GATE.search(text or "") or AGE_RANGE.search(text or "")) \
            and _hits(squeeze(text), SEXUAL + BAIT, normalize(text)):
        return False
    bare = strip_urls(text)
    return not _hits(squeeze(bare), SEXUAL, normalize(bare))
