#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_core — בדיקות לשלב 1. מריצים לפני כל שינוי בליבה.

    python3 test_core.py

כל בדיקה כאן נכשלת אם מישהו ישבור את ההתנהגות, ולא רק אם הקוד יזרוק
חריגה. במיוחד: בדיקות ההרשאות בודקות גם **סירובים**, כי קוד הרשאות
שרק מאשר הוא קוד הרשאות שבור.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit import Audit          # noqa: E402
from db import Db, MIGRATIONS    # noqa: E402
from permissions import Permissions, RANK  # noqa: E402
from ratelimit import RateGuard, GLOBAL_PER_SEC  # noqa: E402

PASS = FAIL = 0
FAILURES: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ✗ {name}   {detail}")


def section(t: str) -> None:
    print(f"\n── {t} ──")


def fresh() -> Db:
    path = os.path.join(tempfile.mkdtemp(prefix="gos_"), "t.db")
    return Db(path)


# ── מסד ────────────────────────────────────────────────────────────────────
def test_db():
    section("מסד ומיגרציות")
    db = fresh()
    ok("כל המיגרציות רצו", db.version == MIGRATIONS[-1][0],
       f"גרסה {db.version}")

    n = db.migrate()
    ok("הרצה שנייה לא עושה כלום", n == 0, f"הוחלו {n}")

    tables = {r["name"] for r in db.q(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    need = {"chats", "users", "members", "role_grants", "settings", "audit_log",
            "warnings", "sanctions", "notes", "filters", "locks", "blocklist",
            "allowlist"}
    ok("כל הטבלאות קיימות", need <= tables, f"חסר: {need - tables}")

    ok("WAL פעיל",
       db.one("PRAGMA journal_mode")[0].lower() == "wal")

    # הגדרות: ירושה מברירת מחדל גלובלית
    db.set(0, "welcome_on", "1")
    ok("קבוצה יורשת ברירת מחדל", db.get(-100, "welcome_on") == "1")
    db.set(-100, "welcome_on", "0")
    ok("דריסה מקומית מנצחת", db.get(-100, "welcome_on") == "0")
    ok("הברירה הגלובלית לא השתנתה", db.get(0, "welcome_on") == "1")
    db.set(-100, "welcome_on", "1")
    ok("UPSERT מעדכן ולא מכפיל", db.get(-100, "welcome_on") == "1" and
       len(db.q("SELECT 1 FROM settings WHERE chat_id=-100 AND key='welcome_on'")) == 1)
    ok("מפתח חסר מחזיר ברירת מחדל",
       db.get(-100, "אין_כזה", "ברירה") == "ברירה")
    return db


# ── הרשאות ────────────────────────────────────────────────────────────────
def test_permissions():
    section("הרשאות")
    db = fresh()
    p = Permissions(db)
    CHAT = -100123

    owner, admin, mod, helper, member = 1, 2, 3, 4, 5
    for uid, role in ((owner, "owner"), (admin, "admin"),
                      (mod, "moderator"), (helper, "helper")):
        p.set_role(CHAT, uid, role)

    ok("ברירת מחדל היא member", p.role_of(CHAT, member) == "member")
    ok("תפקיד נשמר", p.role_of(CHAT, admin) == "admin")

    ok("מנהל יכול לחסום", bool(p.check(CHAT, admin, "user.ban", member)))
    ok("מנחה לא יכול לחסום", not p.check(CHAT, mod, "user.ban", member))
    ok("מנחה כן יכול להשתיק", bool(p.check(CHAT, mod, "user.mute", member)))
    ok("עוזר לא יכול להשתיק", not p.check(CHAT, helper, "user.mute", member))
    ok("עוזר כן יכול למחוק", bool(p.check(CHAT, helper, "msg.delete")))
    ok("חבר רגיל לא יכול כלום", not p.check(CHAT, member, "msg.delete"))

    # כלל הדירוג
    ok("מנהל לא יחסום בעלים", not p.check(CHAT, admin, "user.ban", owner))
    ok("מנהל לא יחסום מנהל", not p.check(CHAT, admin, "user.ban", admin))
    ok("בעלים כן יחסום מנהל", bool(p.check(CHAT, owner, "user.ban", admin)))
    ok("אי אפשר לחסום את עצמך", not p.check(CHAT, owner, "user.ban", owner))
    ok("אבל כן לקרוא הגדרות על עצמך",
       bool(p.check(CHAT, admin, "settings.read", admin)))

    d = p.check(CHAT, member, "user.ban", helper)
    ok("סירוב מסביר את עצמו", (not d) and "נדרש" in d.reason, d.reason)
    ok("הסירוב נושא את שם ההרשאה", d.permission == "user.ban")

    ok("הרשאה לא מוגדרת נדחית",
       not p.check(CHAT, owner, "לא.קיים"))

    # דריסות פר-קבוצה
    p.grant(CHAT, "moderator", "user.ban", True)
    ok("דריסה מעניקה", bool(p.check(CHAT, mod, "user.ban", member)))
    p.grant(CHAT, "admin", "user.ban", False)
    ok("דריסה שוללת", not p.check(CHAT, admin, "user.ban", member))
    p.revoke_override(CHAT, "admin", "user.ban")
    ok("ביטול דריסה מחזיר ברירת מחדל",
       bool(p.check(CHAT, admin, "user.ban", member)))

    # בידוד בין קבוצות
    OTHER = -100999
    ok("דריסה לא דולפת לקבוצה אחרת",
       not p.check(OTHER, mod, "user.ban", member))
    ok("תפקיד לא דולף לקבוצה אחרת", p.role_of(OTHER, admin) == "member")

    lst = p.list_for(CHAT, "moderator")
    ok("רשימת הרשאות משקפת דריסה", lst["user.ban"] is True)
    ok("רשימת הרשאות משקפת ברירת מחדל", lst["chat.reset"] is False)

    try:
        p.set_role(CHAT, member, "קוסם")
        ok("תפקיד לא חוקי נדחה", False)
    except ValueError:
        ok("תפקיד לא חוקי נדחה", True)


# ── יומן ──────────────────────────────────────────────────────────────────
def test_audit():
    section("יומן ביקורת")
    db = fresh()
    a = Audit(db)
    CHAT = -100777

    a.log(CHAT, "user.ban", actor_id=2, target_id=9, reason="ספאם",
          severity="high", source="command")
    a.log(CHAT, "settings.write", actor_id=2, before={"lock": "off"},
          after={"lock": "delete"}, severity="info")
    a.log(CHAT, "msg.delete", actor_id=None, actor_kind="bot", target_id=9,
          source="policy", severity="low")

    rows = a.recent(CHAT)
    ok("נרשמו שלוש רשומות", len(rows) == 3, str(len(rows)))
    ok("הסדר מהחדש לישן", rows[0]["action"] == "msg.delete")

    hi = a.recent(CHAT, min_severity="high")
    ok("סינון לפי חומרה", len(hi) == 1 and hi[0]["action"] == "user.ban",
       str([r["action"] for r in hi]))

    st = [r for r in rows if r["action"] == "settings.write"][0]
    ok("נשמר מצב לפני", '"lock": "off"' in st["before_val"], st["before_val"])
    ok("נשמר מצב אחרי", '"lock": "delete"' in st["after_val"])

    ok("היסטוריה למשתמש", len(a.for_user(CHAT, 9)) == 2)
    ok("היסטוריה למנהל", len(a.by_actor(CHAT, 2)) == 2)
    ok("מקור אוטומטי נשמר",
       [r for r in rows if r["source"] == "policy"][0]["actor_kind"] == "bot")

    ok("חומרה לא חוקית נופלת ל-info",
       a.log(CHAT, "x", severity="קטסטרופה") and
       a.recent(CHAT)[0]["severity"] == "info")

    # מחיקה: רק ישן וקל, וה-high נשאר
    db.run("UPDATE audit_log SET ts=? WHERE severity IN ('info','low')",
           (time.time() - 200 * 86400,))
    removed = a.prune(90)
    left = a.recent(CHAT)
    ok("מחיקה הסירה ישנים", removed >= 2, str(removed))
    ok("החמורות נשמרו", all(r["severity"] == "high" for r in left),
       str([r["severity"] for r in left]))


# ── מגבלות טלגרם ──────────────────────────────────────────────────────────
def test_ratelimit():
    section("שומר המכסות")

    async def run():
        g = RateGuard()
        CHAT = -100555

        t0 = time.monotonic()
        await g.acquire(CHAT)
        ok("הראשונה עוברת מיד", time.monotonic() - t0 < 0.05)

        t0 = time.monotonic()
        await g.acquire(CHAT)
        el = time.monotonic() - t0
        ok("השנייה לאותו צ'אט ממתינה ~שנייה", 0.85 <= el <= 1.4, f"{el:.2f}s")

        # 20 לדקה בקבוצה: אחרי 20 יש המתנה ארוכה
        g2 = RateGuard()
        C = -100666
        for _ in range(20):
            g2._for_group(C).take()
        ok("מכסת הקבוצה מתרוקנת אחרי 20",
           g2._for_group(C).take() > 1.0)

        # תקרה גלובלית: שונה מתקרת הצ'אט
        g3 = RateGuard()
        t0 = time.monotonic()
        await asyncio.gather(*(g3.acquire(-100000 - i, is_group=False)
                               for i in range(int(GLOBAL_PER_SEC))))
        el = time.monotonic() - t0
        ok("28 צ'אטים שונים עוברים כמעט מיד", el < 0.5, f"{el:.2f}s")

        t0 = time.monotonic()
        await g3.acquire(-100999, is_group=False)
        el = time.monotonic() - t0
        ok("ה-29 ממתין לתקרה הגלובלית", el > 0.02, f"{el:.3f}s")

        # FloodWait מכובד
        g4 = RateGuard()
        g4.note_flood_wait(CHAT, 2.0)
        d = g4.delay_for(CHAT)
        ok("FloodWait נכבד במלואו", 2.5 <= d <= 3.5, f"{d:.2f}s")

        ok("סטטיסטיקה נאספת", g.stats()["calls"] == 2, str(g.stats()))

    asyncio.run(run())


# ── שילוב: מסלול מלא של פעולה ─────────────────────────────────────────────
def test_flow():
    section("מסלול מלא — בדיקה, פעולה, תיעוד")
    db = fresh()
    p, a = Permissions(db), Audit(db)
    CHAT, ADMIN, SPAMMER = -100888, 10, 77
    p.set_role(CHAT, ADMIN, "admin")

    d = p.check(CHAT, ADMIN, "user.ban", SPAMMER)
    ok("ההרשאה אושרה", bool(d))
    if d:
        db.run("""INSERT INTO sanctions (chat_id,user_id,kind,by_id,reason,ts)
                  VALUES (?,?,?,?,?,?)""",
               (CHAT, SPAMMER, "ban", ADMIN, "פרסום", time.time()))
        a.log(CHAT, "user.ban", actor_id=ADMIN, target_id=SPAMMER,
              reason="פרסום", severity="high")

    live = db.one("""SELECT * FROM sanctions
                     WHERE chat_id=? AND user_id=? AND lifted_at IS NULL""",
                  (CHAT, SPAMMER))
    ok("הענישה נרשמה", live is not None and live["kind"] == "ban")
    ok("הפעולה תועדה", len(a.for_user(CHAT, SPAMMER)) == 1)

    # משתמש בלי הרשאה — שום דבר לא קורה ושום דבר לא נרשם
    before = len(a.recent(CHAT))
    d2 = p.check(CHAT, 99, "user.ban", SPAMMER)
    ok("משתמש רגיל נדחה", not d2)
    ok("דחייה לא יצרה ענישה",
       len(db.q("SELECT 1 FROM sanctions WHERE chat_id=?", (CHAT,))) == 1)
    ok("דחייה לא זיהמה את היומן", len(a.recent(CHAT)) == before)


def main() -> int:
    print("בדיקות ליבה — GroupOS שלב 1")
    test_db()
    test_permissions()
    test_audit()
    test_ratelimit()
    test_flow()
    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
