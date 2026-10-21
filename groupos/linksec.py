#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""linksec — בדיקת קישורים, בלי לפתוח אותם.

## למה לא פשוט "לבקר בקישור ולראות"

מעקב אחרי הפניה מהשרת שלנו פירושו: הוצאת בקשה לכתובת שספאמר בחר,
מהשרת שמריץ גם אתר סטרימינג. זה גם מבזבז זמן במסלול שההודעה מחכה
בו, וגם הופך את הבוט לכלי שאפשר לכוון אותו.

לכן הכול כאן הוא **ניתוח מבני**: איך הכתובת בנויה, לא מה יש בקצה
שלה. זול, מיידי, ולא נותן לאף אחד לכוון את השרת שלנו.

## מה נחשב חשוד

    מקצר כתובות      הקצה אינו ידוע, וזו כל המטרה של המקצר
    IP במקום שם      אתר לגיטימי קונה דומיין
    סיומת זולה       ‎.tk .ml .ga .cf .gq‎ — חינמיות, ולכן חביבות על ספאם
    דמיון לשם מוכר   ‎teIegram.org‎ עם I גדולה במקום l
    יוזר וסיסמה      ‎https://telegram.org@evil.com‎ — הקצה הוא evil
    פורט לא רגיל     אתר אמיתי יושב על 80/443
    מילות דחיפות     "מיהרו", "24 שעות", "רק היום" ליד קישור

אף אחד מהם אינו הוכחה. כולם אותות, והמדיניות מחליטה.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import policy

SHORTENERS = frozenset({
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rb.gy", "shorturl.at", "rebrand.ly", "bl.ink", "tiny.cc",
    "shorte.st", "adf.ly", "bc.vc", "s.id", "v.gd", "clck.ru", "vk.cc",
})

CHEAP_TLDS = frozenset({"tk", "ml", "ga", "cf", "gq", "top", "xyz", "work",
                        "click", "link", "rest", "surf", "buzz"})

# שמות שמתחזים אליהם. הרשימה קצרה בכוונה: שם מוכר נוסף = התחזות נוספת
# שכדאי לזהות, אבל רשימה ארוכה מדי מייצרת התאמות שווא.
LOOKALIKE_TARGETS = frozenset({
    "telegram.org", "telegram.me", "t.me", "whatsapp.com", "google.com",
    "youtube.com", "facebook.com", "instagram.com", "binance.com",
    "metamask.io", "paypal.com", "apple.com", "microsoft.com",
})

URGENCY = re.compile(
    r"\b(hurry|urgent|limited|only today|last chance|act now|expires?|"
    r"claim now|free money|guaranteed|double your)\b"
    r"|מהרו|דחוף|רק היום|הזדמנות אחרונה|מוגבל|כסף חינם|רווח מובטח",
    re.I)

_RX_URL = re.compile(
    r"(?:(?P<scheme>https?)://)?"
    r"(?:(?P<userinfo>[^\s/@]+)@)?"
    r"(?P<host>[A-Za-z0-9\u0080-￿.-]+\.[A-Za-z\u0080-￿]{2,}|"
    r"\d{1,3}(?:\.\d{1,3}){3})"
    r"(?::(?P<port>\d{1,5}))?"
    r"(?P<path>/\S*)?")

SAFE_PORTS = {"80", "443", ""}


@dataclass(frozen=True)
class Link:
    raw: str
    host: str
    tld: str
    port: str = ""
    userinfo: str = ""
    path: str = ""

    @property
    def is_ip(self) -> bool:
        return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", self.host))


def find(text: str) -> list[Link]:
    out: list[Link] = []
    for m in _RX_URL.finditer(text or ""):
        host = m.group("host").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        out.append(Link(m.group(0), host, tld, m.group("port") or "",
                        m.group("userinfo") or "", m.group("path") or ""))
    return out


def _skeleton(host: str) -> str:
    """הכתובת כפי שהעין קוראת אותה: ספרות ואותיות דומות מאוחדות."""
    t = unicodedata.normalize("NFKD", host).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return (t.replace("0", "o").replace("1", "l").replace("3", "e")
            .replace("5", "s").replace("|", "l").replace("rn", "m")
            .replace("vv", "w"))


def _edit1(a: str, b: str) -> bool:
    """האם שתי מחרוזות נבדלות בעריכה אחת לכל היותר."""
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1:] == short:
            return True
    return False


def lookalike(host: str) -> Optional[str]:
    """השם המוכר שהכתובת מתחזה אליו, אם יש."""
    # קודם: האם זה **באמת** אחד מהם. בדיקה בתוך אותה לולאה החזירה
    # "התחזות" עבור ‎web.telegram.org‎, כי ‎telegram.me‎ נבדק לפניו.
    if any(host == t or host.endswith("." + t) for t in LOOKALIKE_TARGETS):
        return None
    sk = _skeleton(host)
    for target in LOOKALIKE_TARGETS:
        tsk = _skeleton(target)
        if sk == tsk or _edit1(sk, tsk):
            return target
        # ‎telegram-org-login.com‎ — השם המוכר בתוך דומיין אחר
        base = target.split(".")[0]
        if len(base) >= 5 and base in sk and not sk.startswith(base + "."):
            return target
    return None


def inspect(text: str, *, allowed: Optional[set[str]] = None
            ) -> list[policy.Signal]:
    """אותות על הקישורים בטקסט. אף אחד מהם אינו הוכחה."""
    links = find(text)
    if not links:
        return []
    ok = allowed or set()
    out: list[policy.Signal] = []
    urgent = bool(URGENCY.search(text or ""))

    for lk in links:
        if any(lk.host == a or lk.host.endswith("." + a) for a in ok):
            continue
        if lk.userinfo:
            # ‎https://telegram.org@evil.com‎ — הקצה הוא evil
            out.append(policy.Signal("link", "userinfo", 0.85, lk.host))
            continue
        if lk.is_ip:
            out.append(policy.Signal("link", "raw_ip", 0.6, lk.host))
            continue
        if lk.host in SHORTENERS:
            out.append(policy.Signal("link", "shortener", 0.45, lk.host))
        elif lk.tld in CHEAP_TLDS:
            out.append(policy.Signal("link", "cheap_tld", 0.4, lk.host))
        fake = lookalike(lk.host)
        if fake:
            out.append(policy.Signal("link", "lookalike", 0.9,
                                     f"{lk.host} ≈ {fake}"))
        if lk.port and lk.port not in SAFE_PORTS:
            out.append(policy.Signal("link", "odd_port", 0.35,
                                     f"{lk.host}:{lk.port}"))

    if out and urgent:
        # דחיפות לבדה אינה כלום; דחיפות **ליד קישור חשוד** היא הדפוס
        out.append(policy.Signal("link", "urgency", 0.4))
    return out
