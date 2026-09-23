#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""policy — מי מחליט מה לעשות, אחרי שכולם אמרו את שלהם.

## למה השכבה הזאת קיימת

בלעדיה כל מנגנון זיהוי מחליט לעצמו: הנעילות מוחקות, רשימת החסומים
חוסמת, וה-AI — אם נחבר אותו ישר לפעולה — יחסום לפי ניחוש. כשמנהל
ישאל "למה המשתמש הזה נחסם", התשובה תהיה "אחד משלושה מנגנונים, לא
ברור איזה".

לכן: **מזהים מדווחים, ה-Policy מחליט.**

    הודעה → אותות → ציון סיכון → כלל שהתאים → פעולה → יומן

## מה זה אות

‎Signal(source, kind, weight, detail)‎. ‎source‎ הוא מי אמר (‎lock‎,
‎blocklist‎, ‎flood‎, ‎ai‎, ‎reputation‎), ו-‎weight‎ הוא כמה זה שוקל
מ-0 עד 1. אות **אינו פעולה**. הוא קלט.

## למה ציון ולא "if"

הודעה עם קישור אינה ספאם. הודעה עם קישור **ממשתמש שנכנס לפני דקה,
שכבר קיבל אזהרה, שחוזרת על עצמה** — כן. שלושה אותות חלשים יחד שווים
יותר מאחד חזק, וזה בדיוק מה שביטוי בוליאני לא יודע לבטא.

הצבירה אינה סכום: סכום של ארבעה אותות בינוניים היה עובר 100%. כאן
כל אות מכרסם מהמקום שנשאר — ‎1 − ∏(1 − w)‎ — ולכן הציון מתקרב ל-1
ולעולם לא עובר אותו.

## הכללים

    risk >= 0.9  →  ban
    risk >= 0.7  →  mute 1h
    risk >= 0.5  →  delete + warn
    risk >= 0.3  →  delete

ברירת מחדל, לא חוק. כל קבוצה כותבת את שלה, והסימולטור מראה מה היה
קורה **לפני** שמפעילים.

## מה לא נמצא כאן

אין טלגרם, אין מסד, אין רשת. ההחלטה היא פונקציה טהורה של האותות
וההגדרות, ולכן אפשר לבדוק מאות תרחישים בלי קבוצה אחת אמיתית.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

ACTIONS = ("none", "flag", "delete", "warn", "mute", "kick", "ban")

# סדר חומרה. משמש להשוואה — "מה חמור יותר" אינו מובן מאליו.
SEVERITY = {a: i for i, a in enumerate(ACTIONS)}

SOURCES = ("lock", "blocklist", "flood", "filter", "ai", "reputation",
           "report", "account", "behavior")


@dataclass(frozen=True)
class Signal:
    """אות אחד. **לא** פעולה — קלט להחלטה."""
    source: str
    kind: str
    weight: float = 0.5
    detail: str = ""

    def clamped(self) -> float:
        return max(0.0, min(1.0, float(self.weight)))


@dataclass(frozen=True)
class Rule:
    """‎risk >= threshold → action‎, אולי מוגבל למקורות מסוימים."""
    threshold: float
    action: str
    duration: Optional[int] = None
    sources: tuple[str, ...] = ()        # ריק = כל מקור

    def matches(self, risk: float, seen: set[str]) -> bool:
        if risk < self.threshold:
            return False
        return not self.sources or bool(seen & set(self.sources))


@dataclass
class Decision:
    action: str = "none"
    duration: Optional[int] = None
    risk: float = 0.0
    rule: Optional[Rule] = None
    signals: list[Signal] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.action != "none"

    @property
    def reasons(self) -> list[str]:
        """למה זה קרה, בשורה לכל אות. זה מה שמנהל רואה כשהוא שואל."""
        return [f"{s.source}:{s.kind}" + (f" ({s.detail})" if s.detail else "")
                for s in sorted(self.signals, key=lambda x: -x.clamped())]

    def explain(self) -> str:
        head = f"{int(self.risk * 100)}%"
        if not self.signals:
            return head
        return head + " — " + ", ".join(self.reasons)


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(0.90, "ban"),
    Rule(0.70, "mute", 3600),
    Rule(0.50, "warn"),
    Rule(0.30, "delete"),
)


def risk_of(signals: Iterable[Signal]) -> float:
    """ציון מצטבר. שלושה אותות חלשים שווים יותר מאחד בינוני.

    ‎1 − ∏(1 − w)‎ ולא סכום: סכום עובר 100% אחרי ארבעה אותות בינוניים,
    ומאבד את המשמעות של המספר. כאן כל אות מכרסם מהמקום שנשאר."""
    left = 1.0
    for s in signals:
        left *= (1.0 - s.clamped())
    return round(1.0 - left, 4)


def decide(signals: Iterable[Signal],
           rules: Iterable[Rule] = DEFAULT_RULES) -> Decision:
    """הכלל החמור ביותר שהתאים. טהור."""
    sigs = [s for s in signals if s.clamped() > 0]
    risk = risk_of(sigs)
    seen = {s.source for s in sigs}
    best: Optional[Rule] = None
    for r in rules:
        if not r.matches(risk, seen):
            continue
        # החמור מנצח. שני כללים שמתאימים אינם סתירה — הם סולם.
        if best is None or SEVERITY[r.action] > SEVERITY[best.action]:
            best = r
    if best is None:
        return Decision("none", None, risk, None, sigs)
    return Decision(best.action, best.duration, risk, best, sigs)


# ── ניסוח הכללים כטקסט ────────────────────────────────────────────────────
# מנהל עורך אותם בטלגרם, ולכן הם שורה אחת לכלל:
#     0.9:ban      0.7:mute:3600      0.5:warn:0:ai,flood
def parse_rules(raw: str) -> list[Rule]:
    """מנסח שגוי מדלג על הכלל ולא מפיל את השאר.

    כלל אחד עם טעות הקלדה לא אמור להשבית את כל המדיניות של הקבוצה."""
    out: list[Rule] = []
    for chunk in (raw or "").replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        try:
            th = float(parts[0])
        except (ValueError, IndexError):
            continue
        if not 0.0 <= th <= 1.0 or len(parts) < 2:
            continue
        action = parts[1].strip().lower()
        if action not in ACTIONS:
            continue
        dur = None
        if len(parts) > 2 and parts[2].strip().isdigit():
            dur = int(parts[2]) or None
        src = tuple(s for s in (parts[3].split("|") if len(parts) > 3 else [])
                    if s in SOURCES)
        out.append(Rule(th, action, dur, src))
    return sorted(out, key=lambda r: -r.threshold)


def format_rules(rules: Iterable[Rule]) -> str:
    bits = []
    for r in rules:
        s = f"{r.threshold:g}:{r.action}"
        if r.duration:
            s += f":{r.duration}"
        if r.sources:
            s += (":" if r.duration else ":0:") + "|".join(r.sources)
        bits.append(s)
    return ", ".join(bits)


def rules_for(db, chat_id: int) -> list[Rule]:
    raw = db.get(chat_id, "policy_rules", "") or ""
    return parse_rules(raw) or list(DEFAULT_RULES)


# ── סימולטור ──────────────────────────────────────────────────────────────
def simulate(signals: Iterable[Signal],
             rules: Iterable[Rule] = DEFAULT_RULES) -> dict:
    """מה **היה** קורה. משמש את ‎/simulate‎ לפני שמפעילים מדיניות.

    מדיניות אבטחה שמופעלת בלי לראות מה היא עושה היא הדרך המהירה
    ביותר לחסום חצי קבוצה בטעות."""
    sigs = list(signals)
    d = decide(sigs, rules)
    return {
        "risk": d.risk,
        "action": d.action,
        "duration": d.duration,
        "rule": (format_rules([d.rule]) if d.rule else None),
        "signals": [{"source": s.source, "kind": s.kind,
                     "weight": s.clamped(), "detail": s.detail}
                    for s in sigs],
        "explain": d.explain(),
    }
