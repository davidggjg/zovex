#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blocklist — מילים וביטויים אסורים, כולל התחמקויות.

## הבעיה האמיתית

חסימת מילה היא קלה. חסימת מילה שמישהו מנסה להעביר היא העבודה:

    ס.פ.א.מ    ‎s p a m‎    ‎ѕраm‎ (קירילית)    ‎5p4m‎    ‎s‌p‌a‌m‌‎ (רוחב אפס)

כל החמש נראות למשתמש כמו אותה מילה, ואף אחת מהן אינה שווה למחרוזת
המקורית. לכן הטקסט עובר **נרמול** לפני ההשוואה: מסירים סימני ניקוד
ופיסוק, ממירים תווים דומים ויזואלית לאותיות לטיניות, ומקפלים leetspeak.

## מה לא נעשה כאן

לא מנרמלים **יותר מדי**. אם כל תו לא-אלפאנומרי היה נופל, "co.il" היה
הופך ל-"coil" ו-"c-o-i-l" היה נחסם יחד איתו. לכן הנרמול שומר על
גבולות מילים, והתאמת ‎word‎ דורשת גבול — ‎"מחשב"‎ לא נחסם בגלל
‎"שבמחשבים"‎, אלא אם המנהל ביקש ‎substring‎ במפורש.

## סוגי התאמה

    word        מילה שלמה, אחרי נרמול
    substring   כל הופעה
    regex       ביטוי רגולרי של המנהל
    domain      דומיין, כולל תת-דומיינים
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

KINDS = ("word", "substring", "regex", "domain")

# תווים ברוחב אפס ומחברים — הכלי הנפוץ ביותר להתחמקות, כי הם בלתי נראים
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)

# אותיות שנראות זהות אך אינן. קירילית ויוונית הן הרוב המכריע.
CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "і": "i", "ѕ": "s",
    "ј": "j", "ԁ": "d", "ɡ": "g", "ν": "v", "α": "a", "ο": "o", "ρ": "p",
    "ε": "e", "τ": "t", "υ": "u", "ι": "i", "κ": "k", "μ": "m", "χ": "x",
})

# leetspeak. רק החלפות חד-משמעיות — "1" ל-"l" ולא ל-"i", כי אחרת
# מספרי טלפון היו הופכים למילים ונחסמים.
LEET = str.maketrans({"4": "a", "3": "e", "0": "o", "1": "l", "5": "s",
                      "7": "t", "@": "a", "$": "s", "!": "i"})

_SEP = re.compile(r"[\s._\-*+~^:;,'\"/\\|()\[\]{}<>]+")
_RX_DOMAIN = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)


def normalize(text: str) -> str:
    """הטקסט כפי שמשתמש **קורא** אותו, לא כפי שהוא מקודד.

    NFKD מפרק ניקוד ואותיות מורכבות; אחר כך מסירים סימני ניקוד,
    תווים בלתי נראים, ודמויי-אותיות. הפיסוק בין אותיות נופל, כי
    ‎ס.פ.א.מ‎ היא אותה מילה."""
    t = unicodedata.normalize("NFKD", text or "").lower()
    t = t.translate(ZERO_WIDTH).translate(CONFUSABLES).translate(LEET)
    t = "".join(c for c in t if not unicodedata.combining(c))
    # פיסוק בין תווים בודדים — ‎s.p.a.m‎ ← ‎spam‎ — אבל לא בין מילים
    t = re.sub(r"(?<=\w)[.\-_*+~^']+(?=\w)", "", t)
    t = _SEP.sub(" ", t)
    return t.strip()


def spaced_out(text: str) -> str:
    """‎'s p a m'‎ ← ‎'spam'‎. רק כשכל האסימונים באורך 1–2."""
    toks = normalize(text).split()
    if len(toks) >= 3 and all(len(w) <= 2 for w in toks):
        return "".join(toks)
    return ""


def domains(text: str) -> set[str]:
    return {m.group(1).lower() for m in _RX_DOMAIN.finditer(text or "")}


@dataclass(frozen=True)
class Match:
    pattern: str
    kind: str
    action: str
    evaded: bool = False        # נתפס רק אחרי נרמול — כלומר מישהו ניסה


def _word_hit(needle: str, hay: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", hay) is not None


def check_text(text: str, rules: list[dict]) -> Optional[Match]:
    """הכלל הראשון שמתאים. ‎rules‎: ‎[{pattern, kind, action}]‎."""
    if not text or not rules:
        return None
    raw = text.lower()
    norm = normalize(text)
    glued = spaced_out(text)
    doms = domains(text)

    for r in rules:
        pat, kind = (r["pattern"] or "").strip(), r.get("kind", "word")
        if not pat:
            continue
        act = r.get("action", "delete")
        if kind == "domain":
            p = pat.lower().lstrip(".")
            if any(d == p or d.endswith("." + p) for d in doms):
                return Match(pat, kind, act)
            continue
        if kind == "regex":
            try:
                if re.search(pat, text, re.I):
                    return Match(pat, kind, act)
            except re.error:
                # ביטוי שגוי של מנהל אינו סיבה להפיל בדיקת הודעה
                continue
            continue
        p = normalize(pat)
        if not p:
            continue
        if kind == "substring":
            if p in raw or p in norm:
                return Match(pat, kind, act, evaded=p not in raw)
            if glued and p in glued:
                return Match(pat, kind, act, evaded=True)
            continue
        # word
        if _word_hit(p, raw):
            return Match(pat, kind, act)
        if _word_hit(p, norm):
            return Match(pat, kind, act, evaded=True)
        if glued and _word_hit(p, glued):
            return Match(pat, kind, act, evaded=True)
    return None


class Blocklist:
    def __init__(self, db):
        self.db = db

    def all(self, chat_id: int) -> list[dict]:
        return [dict(r) for r in self.db.q(
            """SELECT id,pattern,kind,action FROM blocklist
               WHERE chat_id=? ORDER BY id""", (chat_id,))]

    def add(self, chat_id: int, pattern: str, kind: str = "word",
            action: str = "delete") -> bool:
        pattern = (pattern or "").strip()
        if not pattern or kind not in KINDS:
            return False
        if kind == "regex":
            try:
                re.compile(pattern)
            except re.error:
                return False       # לא שומרים ביטוי שבור
        import time
        self.db.run("""INSERT INTO blocklist (chat_id,pattern,kind,action,created_at)
                       VALUES (?,?,?,?,?)""",
                    (chat_id, pattern, kind, action, time.time()))
        return True

    def remove(self, chat_id: int, pattern: str) -> int:
        return self.db.change(
            "DELETE FROM blocklist WHERE chat_id=? AND pattern=?",
            (chat_id, pattern.strip()))

    def clear(self, chat_id: int) -> int:
        return self.db.change("DELETE FROM blocklist WHERE chat_id=?", (chat_id,))

    def check(self, chat_id: int, text: str) -> Optional[Match]:
        return check_text(text, self.all(chat_id))
