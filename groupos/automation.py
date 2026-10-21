#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""automation — כשקורה X ומתקיים Y, עשה Z.

## מה זה נותן שאין בלעדיו

עד כאן כל התנהגות הייתה קבועה בקוד: נעילה מוחקת, אזהרה מצטברת. כאן
מנהל מרכיב התנהגות משלו בלי שנכתוב שורה:

    WHEN join IF account_age < 7d AND has_link THEN captcha, alert
    WHEN message IF risk > 0.8 THEN delete, warn
    WHEN join IF joins_in_60s > 30 THEN emergency

## הניסוח

שורה אחת לכלל, כי מנהל כותב אותה בטלגרם ואין שם עורך:

    when:<אירוע> if:<תנאי> then:<פעולות>

התנאים מופרדים ב-‎&‎ וכולם חייבים להתקיים. **אין ‎OR‎ בכוונה**: שני
כללים נפרדים קריאים יותר מביטוי אחד עם סוגריים, ומנהל שכותב תנאי
מורכב בטלגרם יטעה בו.

## למה זה לא מבצע כלום

המנוע מחזיר **רשימת פעולות מבוקשות**. מי שמבצע אותן הוא המתאם, ומה
שמותר לבצע נקבע בהרשאות. אוטומציה שמבצעת בעצמה היא דרך לעקוף את
מערכת ההרשאות בכתיבת שורת טקסט.

## תקרה

עשרה כללים לקבוצה, ועד שלוש פעולות לכלל. לא בגלל ביצועים — בגלל
שרשרת: כלל שמפעיל מצב חירום שמפעיל כלל אחר הוא לולאה שאיש לא התכוון
אליה.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

EVENTS = ("join", "leave", "message", "media", "link", "edit", "raid")

ACTIONS = ("delete", "warn", "mute", "kick", "ban", "captcha", "alert",
           "lockdown", "emergency", "log", "reply")

# שדות שאפשר לבדוק, והטיפוס שלהם. שדה לא מוכר פוסל את הכלל.
FIELDS = {
    "risk": float, "account_age": int, "joins_in_60s": int,
    "warns": int, "level": int, "trust": float, "xp": int,
    "msg_len": int, "mentions": int, "links": int,
    "is_new": bool, "has_link": bool, "has_media": bool,
    "is_forward": bool, "has_button": bool,
}

OPS = ("<=", ">=", "!=", "=", "<", ">")

MAX_RULES = 10
MAX_ACTIONS = 3

_RX_DUR = re.compile(r"^(\d+)([smhd])$", re.I)


def _num(raw: str) -> Optional[float]:
    """מספר, או משך כמו ‎7d‎ בשניות. ‎7d‎ קריא יותר מ-‎604800‎."""
    raw = raw.strip()
    m = _RX_DUR.match(raw)
    if m:
        return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600,
                                  "d": 86400}[m.group(2).lower()]
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Cond:
    field: str
    op: str
    value: float

    def holds(self, facts: dict) -> bool:
        got = facts.get(self.field)
        if got is None:
            return False
        if FIELDS[self.field] is bool:
            want = bool(self.value)
            return bool(got) == want if self.op in ("=", "==") else bool(got) != want
        try:
            g = float(got)
        except (TypeError, ValueError):
            return False
        v = self.value
        return {"<": g < v, ">": g > v, "<=": g <= v, ">=": g >= v,
                "=": g == v, "!=": g != v}[self.op]


@dataclass(frozen=True)
class Rule:
    event: str
    conds: tuple[Cond, ...] = ()
    actions: tuple[str, ...] = ()
    # הטקסט המקורי נשמר לתצוגה בלבד ואינו חלק מהזהות: ‎if:is_new‎
    # ו-‎if:is_new=1‎ הם אותו כלל, ורק הניסוח שונה.
    raw: str = field(default="", compare=False)

    def fires(self, event: str, facts: dict) -> bool:
        if event != self.event:
            return False
        return all(c.holds(facts) for c in self.conds)


def parse_cond(raw: str) -> Optional[Cond]:
    raw = raw.strip()
    for op in OPS:                    # הארוכים ראשונים: ‎>=‎ לפני ‎>‎
        if op in raw:
            left, right = raw.split(op, 1)
            f = left.strip().lower()
            if f not in FIELDS:
                return None
            if FIELDS[f] is bool:
                v = right.strip().lower()
                if v in ("true", "yes", "1", ""):
                    return Cond(f, "=", 1.0)
                if v in ("false", "no", "0"):
                    return Cond(f, "=", 0.0)
                return None
            n = _num(right)
            return Cond(f, op, n) if n is not None else None
    # שדה בוליאני לבדו: ‎has_link‎ פירושו ‎has_link = true‎
    f = raw.strip().lower()
    if f in FIELDS and FIELDS[f] is bool:
        return Cond(f, "=", 1.0)
    return None


def parse_rule(raw: str) -> Optional[Rule]:
    """‎when:join if:is_new & has_link then:captcha,alert‎.

    כלל שלא נפרס מוחזר כ-‎None‎ ולא זורק — שורה אחת עם טעות לא אמורה
    להשבית את כל האוטומציה של הקבוצה."""
    txt = (raw or "").strip()
    if not txt:
        return None
    # עצירה לפני מילת המפתח הבאה. ‎[^|]+‎ היה בולע את השאר, ואז
    # ‎when‎ קיבל את כל השורה ו-‎then‎ נשאר ריק.
    parts = {k.lower(): v.strip() for k, v in re.findall(
        r"\b(when|if|then)\s*:\s*(.*?)(?=\s+\b(?:when|if|then)\s*:|$)",
        txt, re.I)}
    ev = (parts.get("when") or "").strip().lower()
    if ev not in EVENTS:
        return None
    acts = tuple(a.strip().lower()
                 for a in (parts.get("then") or "").split(",") if a.strip())
    acts = tuple(a for a in acts if a in ACTIONS)[:MAX_ACTIONS]
    if not acts:
        return None
    conds = []
    for chunk in (parts.get("if") or "").split("&"):
        if not chunk.strip():
            continue
        c = parse_cond(chunk)
        if c is None:
            return None          # תנאי שלא הובן הופך כלל לרחב מדי
        conds.append(c)
    return Rule(ev, tuple(conds), acts, txt)


def format_rule(r: Rule) -> str:
    bits = [f"when:{r.event}"]
    if r.conds:
        bits.append("if:" + " & ".join(
            f"{c.field}{c.op}{int(c.value) if c.value == int(c.value) else c.value}"
            for c in r.conds))
    bits.append("then:" + ",".join(r.actions))
    return " ".join(bits)


def parse_rules(raw: str) -> list[Rule]:
    out = []
    for line in (raw or "").replace("|", "\n").splitlines():
        r = parse_rule(line)
        if r:
            out.append(r)
        if len(out) >= MAX_RULES:
            break
    return out


def rules_for(db, chat_id: int) -> list[Rule]:
    return parse_rules(db.get(chat_id, "automation", "") or "")


def run(rules: Iterable[Rule], event: str, facts: dict) -> list[str]:
    """הפעולות המבוקשות, בלי כפילויות ובסדר שבו נתבקשו.

    **אינו מבצע כלום.** מי שמבצע הוא המתאם, ומה שמותר נקבע בהרשאות."""
    out: list[str] = []
    for r in rules:
        if not r.fires(event, facts):
            continue
        for a in r.actions:
            if a not in out:
                out.append(a)
    return out


def explain(rules: Iterable[Rule], event: str, facts: dict) -> list[str]:
    """אילו כללים נורו. משמש ב-‎/simulate‎ וביומן."""
    return [format_rule(r) for r in rules if r.fires(event, facts)]
