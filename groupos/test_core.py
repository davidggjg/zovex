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
from locks import Locks, LOCK_TYPES, GROUPS, ACTIONS, detect  # noqa: E402
from moderation import Moderation, parse_policy, format_policy  # noqa: E402
import panel  # noqa: E402
import i18n  # noqa: E402
from ratelimit import RateGuard, GLOBAL_PER_SEC  # noqa: E402
import templates as tpl  # noqa: E402
import blocklist as bl  # noqa: E402
import content  # noqa: E402
import re as _re_mod  # noqa: E402
import captcha as cap  # noqa: E402
import emergency as emerg  # noqa: E402
from antiflood import AntiFlood  # noqa: E402

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

    # run מחזיר lastrowid; DELETE חייב להימדד ב-rowcount. קוד שבדק
    # ‎if run(DELETE...)‎ קיבל "הצלחתי" גם כשלא נמחק דבר — נתפס בבדיקה.
    db.run("INSERT INTO allowlist (chat_id,scope,value) VALUES (?,?,?)",
           (-100, "user", "1"))
    ok("change סופר מחיקה אמיתית",
       db.change("DELETE FROM allowlist WHERE chat_id=?", (-100,)) == 1)
    ok("change מחזיר אפס כשאין מה למחוק",
       db.change("DELETE FROM allowlist WHERE chat_id=?", (-999,)) == 0)
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



# ── נעילות ────────────────────────────────────────────────────────────────
def test_locks():
    section("נעילות")
    ok("כל סוג נעילה שייך לקבוצה מוכרת",
       all(g in GROUPS for g in LOCK_TYPES.values()),
       str([g for g in LOCK_TYPES.values() if g not in GROUPS]))
    # שם קשיח בקוד הוא מה שנועל בוט לשפה אחת. כאן השם הוא מפתח תרגום.
    holes = [k for k in LOCK_TYPES if i18n.t(f"lock.{k}", "en") == f"lock.{k}"]
    ok("לכל סוג נעילה יש שם מתורגם", not holes, str(holes))
    gholes = [g for g in GROUPS if i18n.t(f"group.{g}", "en") == f"group.{g}"]
    ok("לכל קבוצת נעילות יש שם מתורגם", not gholes, str(gholes))

    d = detect({"text": "תראו את זה https://example.com"})
    ok("קישור מזוהה", "url" in d, str(d))
    d = detect({"text": "הצטרפו t.me/joinchat/AbCdEf"})
    ok("קישור הזמנה מזוהה", "invite" in d and "url" in d, str(d))
    ok("תיוג מזוהה", "mention" in detect({"text": "היי @someuser מה קורה"}))
    ok("מייל מזוהה", "email" in detect({"text": "כתבו ל-a.b@mail.co.il"}))
    ok("טלפון מזוהה", "phone" in detect({"text": "חייגו 050-123-4567"}))
    ok("פקודה מזוהה", "command" in detect({"text": "/ban"}))
    ok("מדיה מזוהה", "photo" in detect({"media_kind": "photo"}))
    ok("אלבום מזוהה", "album" in detect({"media_kind": "photo",
                                         "media_group_id": "1"}))
    ok("העברה מזוהה", "forward" in detect({"text": "x", "is_forward": True}))
    ok("ערוץ אנונימי מזוהה",
       "anonchannel" in detect({"text": "x", "sender_chat": -100}))
    ok("צעקה מזוהה", "caps" in detect({"text": "BUY NOW FREE MONEY"}))
    ok("טקסט עברי לא נחשב צעקה",
       "caps" not in detect({"text": "קנו עכשיו כסף חינם לכולם"}))
    ok("קיצור קצר לא נחשב צעקה", "caps" not in detect({"text": "OK LOL"}))
    ok("אימוג'י בלבד מזוהה", "emoji_only" in detect({"text": "😀😀😀"}))
    ok("טקסט עם אימוג'י אינו אימוג'י-בלבד",
       "emoji_only" not in detect({"text": "שלום 😀"}))
    ok("הודעה נקייה לא מפעילה כלום",
       detect({"text": "בוקר טוב לכולם"}) == set(),
       str(detect({"text": "בוקר טוב לכולם"})))

    db = fresh()
    L = Locks(db)
    CHAT = -100321
    ok("בלי נעילות אין פגיעה", L.check(CHAT, {"text": "http://x.com"}) is None)

    L.set(CHAT, "url", "delete")
    h = L.check(CHAT, {"text": "בואו http://x.com"})
    ok("נעילת קישורים תופסת", h is not None and h.action == "delete")
    ok("הפגיעה נושאת מפתח ולא שם", h.lock == "url" and h.key == "lock.url")
    ok("הודעה נקייה עוברת", L.check(CHAT, {"text": "שלום"}) is None)

    # החמורה מנצחת
    L.set(CHAT, "invite", "ban")
    h = L.check(CHAT, {"text": "t.me/joinchat/xyz"})
    ok("החמורה מנצחת כששתיים מתאימות",
       h.action == "ban" and h.lock == "invite", f"{h.lock}/{h.action}")

    L.set(CHAT, "url", "off")
    ok("כיבוי מסיר את הנעילה",
       L.check(CHAT, {"text": "http://x.com"}) is None)

    OTHER = -100322
    ok("נעילה לא דולפת לקבוצה אחרת",
       L.check(OTHER, {"text": "t.me/joinchat/xyz"}) is None)

    try:
        L.set(CHAT, "לא_קיים", "delete"); ok("נעילה לא מוכרת נדחית", False)
    except ValueError:
        ok("נעילה לא מוכרת נדחית", True)
    try:
        L.set(CHAT, "url", "לרסק"); ok("פעולה לא מוכרת נדחית", False)
    except ValueError:
        ok("פעולה לא מוכרת נדחית", True)

    grp = L.by_group(CHAT)
    ok("תצוגה מקובצת מחזירה את כל הסוגים",
       sum(len(v) for v in grp.values()) == len(LOCK_TYPES))

    # נעילה גורפת: מה שמנהל מחפש כשמתחיל ספאם
    n = L.set_many(CHAT, "delete")
    ok("נעילת הכול נועלת את כל הסוגים",
       n == len(LOCK_TYPES) and len(L.get_all(CHAT)) == len(LOCK_TYPES))
    L.set_many(CHAT, "off")
    ok("פתיחת הכול מנקה", L.get_all(CHAT) == {})


# ── מדיניות אזהרות ────────────────────────────────────────────────────────
def test_moderation():
    section("אזהרות ומדיניות")
    pol = parse_policy("3:mute:3600,5:mute:86400,7:ban:0")
    ok("מדיניות מפוענחת", pol == [(3, "mute", 3600), (5, "mute", 86400),
                                  (7, "ban", None)], str(pol))
    ok("שורה פגומה מדולגת",
       parse_policy("3:mute:3600,זבל,7:ban:0") == [(3, "mute", 3600),
                                                   (7, "ban", None)])
    ok("מדיניות ריקה לא מפילה", parse_policy("") == [])
    ok("תצוגה בעברית", "השתקה" in format_policy(pol), format_policy(pol))

    db = fresh()
    a = Audit(db)
    m = Moderation(db, a)
    CHAT, U, BY = -100444, 55, 7

    o = m.warn(CHAT, U, BY, "ספאם")
    ok("אזהרה ראשונה", o.kind == "warn" and o.warns == 1)
    ok("לא חצתה סף", not o.threshold_hit)
    m.warn(CHAT, U, BY)
    o = m.warn(CHAT, U, BY)
    ok("השלישית מפעילה השתקה",
       o.kind == "mute" and o.threshold_hit and o.duration == 3600,
       f"{o.kind}/{o.duration}")
    ok("התווית בעברית", "השתקה ל-שעה" == o.label, o.label)

    ok("מונה נשמר", m.warn_count(CHAT, U) == 3)
    ok("ביטול מוריד אחת", m.unwarn(CHAT, U, BY) == 2)
    ok("היסטוריה נשמרת גם אחרי ביטול", len(m.history(CHAT, U)) == 3)
    m.reset_warns(CHAT, U, BY)
    ok("איפוס מאפס", m.warn_count(CHAT, U) == 0)

    # מדיניות פר-קבוצה
    db.set(CHAT, "warn_policy", "2:kick:0")
    m.warn(CHAT, U, BY)
    o = m.warn(CHAT, U, BY)
    ok("מדיניות מותאמת נאכפת", o.kind == "kick", o.kind)

    OTHER = -100445
    ok("אזהרות לא דולפות בין קבוצות", m.warn_count(OTHER, U) == 0)

    # ענישות
    m.record(CHAT, U, "mute", BY, "בדיקה", 1)
    ok("ענישה פעילה נרשמת", len(m.active(CHAT, U)) == 1)
    time.sleep(1.1)
    ok("ענישה שפגה מזוהה", any(r["user_id"] == U for r in m.expired()))
    ok("ענישה שפגה אינה פעילה", len(m.active(CHAT, U)) == 0)
    ok("שחרור עובד", m.lift(CHAT, U, "mute", BY))
    ok("שחרור כפול מחזיר False", not m.lift(CHAT, U, "mute", BY))



# ── פאנל הניהול הפרטי ─────────────────────────────────────────────────────
def test_panel():
    section("פאנל פרטי")
    CHAT = -1001234567890          # מזהה ארוך אמיתי, לא צעצוע

    ok("מזהה כפתור נבנה ונפרס",
       panel.parse_cb(panel.cb(CHAT, "lock", "premium_sticker")) ==
       (CHAT, "lock", "premium_sticker"))
    ok("מזהה זר נדחה", panel.parse_cb("משהו אחר") is None)
    ok("מזהה פגום נדחה", panel.parse_cb("g:לא_מספר:main") is None)

    # המגבלה של טלגרם נשברת בשקט — לכן היא נבדקת על הנעילה עם השם הארוך ביותר
    longest = max(LOCK_TYPES, key=len)
    ok(f"הכפתור הארוך ביותר נכנס ב-64 בייט ({longest})",
       len(panel.cb(CHAT, "lock", longest).encode()) <= panel.CB_MAX,
       str(len(panel.cb(CHAT, "lock", longest).encode())))

    # כל מסך: כל כפתור תקף, ויש דרך חזרה
    screens = {
        "home": panel.home([(CHAT, "קבוצה לבדיקה")]),
        "main": panel.main_menu(CHAT, "קבוצה", {"members": 5}),
        "locks": panel.locks_groups(CHAT, {}),
        "lockg": panel.locks_in_group(CHAT, "media",
                                      [("photo", "off"), ("video", "ban")]),
        "warns": panel.warns_screen(CHAT, "3:mute:3600", [(1, "דוד", 2)]),
        "audit": panel.audit_screen(CHAT, [], lambda t: "12:00"),
        "settings": panel.settings_screen(CHAT, {"autoclean": "30"}),
    }
    for name, sc in screens.items():
        ok(f"מסך {name}: יש טקסט", bool(sc.text.strip()))
        bad = [c for c in sc.all_callbacks()
               if panel.parse_cb(c) is None or len(c.encode()) > panel.CB_MAX]
        ok(f"מסך {name}: כל הכפתורים תקפים", not bad, str(bad))

    # "דרך חזרה" נמדדת לפי היעד ולא לפי מילה, כי הטקסט תלוי שפה
    for name in ("main", "locks", "lockg", "warns", "audit", "settings"):
        dests = {panel.parse_cb(c)[1] for c in screens[name].all_callbacks()
                 if panel.parse_cb(c)}
        ok(f"מסך {name}: יש דרך חזרה",
           bool(dests & {"main", "locks", "home"}), str(dests))

    for lg in ("he", "en"):
        ok(f"מסך ריק מסביר מה לעשות ב-{lg}",
           "/start" in panel.home([], lg).text)

    # מחזור הלחיצות חייב לכסות פעולות אמיתיות ולחזור להתחלה
    ok("מחזור הנעילה מכיל רק פעולות מוכרות",
       all(a in ACTIONS for a in panel.CYCLE))
    cur = "off"
    seen = []
    for _ in range(len(panel.CYCLE)):
        cur = panel.next_in_cycle(panel.CYCLE, cur)
        seen.append(cur)
    ok("המחזור חוזר להתחלה", seen[-1] == "off", str(seen))
    ok("ערך לא מוכר מתחיל מההתחלה",
       panel.next_in_cycle(panel.CYCLE, "זבל") == "off")

    ok("כל הגדרות האזהרה מפוענחות",
       all(parse_policy(v) is not None for v in panel.WARN_PRESETS.values()))
    ok("קיצור 'רק אזהרות' באמת ריק", parse_policy(panel.WARN_PRESETS["c"]) == [])

    # לכל פעולה יש תווית בעברית — אחרת המסך יציג מפתח באנגלית
    ok("לכל פעולה יש תווית",
       all(a in panel.ACTION_LABEL for a in ACTIONS),
       str([a for a in ACTIONS if a not in panel.ACTION_LABEL]))

    # כל מסך שהפאנל מפנה אליו חייב להיות מטופל במתאם — אחרת כפתור מת
    import re as _re
    bot_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "bot.py"), encoding="utf-8").read()
    panel_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "panel.py"), encoding="utf-8").read()
    referenced = set(_re.findall(r'cb\([^,]+, "(\w+)"', panel_src)) | {"home"}
    handled = set(_re.findall(r'name == "(\w+)"', bot_src)) | \
              set(_re.findall(r'name in \("(\w+)", "(\w+)"\)', bot_src)[0]
                  if _re.findall(r'name in \("(\w+)", "(\w+)"\)', bot_src) else [])
    missing = referenced - handled
    ok("כל מסך שהפאנל מפנה אליו מטופל במתאם", not missing, str(missing))

    # ── פקודות ורב-לשוניות ────────────────────────────────────────────────
    names = [n for n, _ in panel.COMMANDS]
    ok("אין פקודה כפולה", len(names) == len(set(names)),
       str([n for n in names if names.count(n) > 1]))
    ok("כל שם פקודה חוקי לטלגרם",
       all(_re.fullmatch(r"[a-z0-9_]{1,32}", n) for n in names),
       str([n for n in names if not _re.fullmatch(r"[a-z0-9_]{1,32}", n)]))

    # פקודה שמוצהרת ואינה רשומה במתאם היא כפתור מת בתפריט ✏️
    declared = set(_re.findall(r'Command\("(\w+)"\)', bot_src))
    declared |= {"start"} if "CommandStart()" in bot_src else set()
    ok("כל פקודה מוצהרת קיימת במתאם", not (set(names) - declared),
       str(set(names) - declared))
    ok("כל פקודה במתאם מופיעה בתפריט", not (declared - set(names)),
       str(declared - set(names)))

    for lg in ("he", "en"):
        holes = [n for n in names if i18n.t(f"cmd.{n}", lg) == f"cmd.{n}"]
        ok(f"לכל פקודה יש תיאור ב-{lg}", not holes, str(holes))
    ok("תיאור פקודה נכנס ב-256 תווים",
       all(len(d) <= 256 for _, d in panel.command_list("he")))

    # כל מסך חייב להיבנות בכל שפה, גם כזו שהמילון שלה חלקי
    for lg in i18n.STRINGS:
        built = {
            "home": panel.home([(CHAT, "קבוצה")], lg),
            "main": panel.main_menu(CHAT, "קבוצה", {"members": 5}, lg),
            "locks": panel.locks_groups(CHAT, {}, lg),
            "lockg": panel.locks_in_group(CHAT, "media",
                                          [("photo", "ban")], lg),
            "warns": panel.warns_screen(CHAT, "3:mute:3600", [], lg),
            "audit": panel.audit_screen(CHAT, [], lambda t: "12:00", lg),
            "settings": panel.settings_screen(CHAT, {"autoclean": "0"}, lg),
            "lang": panel.language_screen(CHAT, lg),
            "help": panel.help_screen(lg),
        }
        empty = [n for n, sc in built.items() if not sc.text.strip()]
        ok(f"כל המסכים נבנים ב-{lg}", not empty, str(empty))
        bad = [c for sc in built.values() for c in sc.all_callbacks()
               if panel.parse_cb(c) is None or len(c.encode()) > panel.CB_MAX]
        ok(f"כל הכפתורים תקפים ב-{lg}", not bad, str(bad))

    ok("בורר השפה מסמן את הנוכחית",
       any("●" in lbl for row in panel.language_screen(CHAT, "en").rows
           for lbl, _ in row))
    ok("בורר השפה מציע כל שפה שיש לה מילון",
       {c for c in i18n.STRINGS} <=
       {panel.parse_cb(c)[2] for row in panel.language_screen(CHAT, "he").rows
        for _, c in row if panel.parse_cb(c)[1] == "setlang"})
    ok("מסך השפה נכתב בשפה הנוכחית",
       "Language" in panel.language_screen(CHAT, "en").text)

    # הקבוצה נרשמה רק כשהגיעה ממנה הודעה — וטלגרם לא מוסרת הודעות
    # רגילות לבוט שאינו מנהל. בלי הרישום ברגע ההוספה, הבוט יושב בקבוצה
    # והפאנל מציג "לא ראיתי אותך מנהל באף קבוצה". זה קרה בפועל.
    ok("הבוט מגיב לרגע ההוספה לקבוצה", "@dp.my_chat_member()" in bot_src)
    ok("יש מטפל לכניסת משתמש", "F.new_chat_members)" in bot_src)
    ok("יש מטפל ליציאת משתמש", "F.left_chat_member)" in bot_src)
    # הודעת הצטרפות היא הודעה בלי טקסט. בלי ההחרגה, המטפל הכללי
    # בולע אותה וברכת הכניסה לא נורית לעולם.
    generic = bot_src.split("async def on_group_message")[0].rsplit("@dp.message", 1)[-1]
    ok("המטפל הכללי מחריג הודעות שירות",
       "~F.new_chat_members" in generic and "~F.left_chat_member" in generic,
       generic.strip()[:120])
    ok("הבוט מגיב לקידום מנהלים", "@dp.chat_member()" in bot_src)
    ok("המסך הריק מפנה ל-/start בקבוצה",
       "/start" in i18n.t("home.empty", "he")
       and "/start" in i18n.t("home.empty", "en"))




# ── manifest ולכידות ההתקנה ───────────────────────────────────────────────
def test_manifest():
    section("manifest")
    import re as _re
    here = os.path.dirname(os.path.abspath(__file__))
    mf = os.path.join(here, "manifest.txt")
    ok("manifest קיים", os.path.exists(mf))
    listed = {l.strip() for l in open(mf, encoding="utf-8") if l.strip()}
    on_disk = {f for f in os.listdir(here) if f.endswith(".py")}
    missing = on_disk - listed
    ok("כל מודול קיים רשום ב-manifest", not missing, str(missing))
    ghosts = {f for f in listed if f.endswith(".py")} - on_disk
    ok("אין ב-manifest קבצים שלא קיימים", not ghosts, str(ghosts))

    # כל מה ש-bot.py מייבא מקומית חייב להיות ב-manifest — זה הבאג
    # שהפיל את ההתקנה: שלושה מודולים חדשים לא הגיעו לשרת.
    import ast as _ast
    need = set()
    for n in _ast.walk(_ast.parse(open(os.path.join(here, "bot.py"),
                                       encoding="utf-8").read())):
        if isinstance(n, _ast.Import):
            need |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, _ast.ImportFrom) and n.module and n.level == 0:
            need.add(n.module.split(".")[0])
    local = {f[:-3] for f in on_disk}
    ok("כל ייבוא מקומי של bot.py רשום ב-manifest",
       all(f"{m}.py" in listed for m in (need & local)),
       str([m for m in (need & local) if f"{m}.py" not in listed]))

    # המתקין חייב להשאיר עותק של עצמו ב-DIR. בלי זה הפקודה שכתובה
    # ב-README ובמסך הסיום נכשלת ב-"No such file or directory" — וזה קרה.
    ins = open(os.path.join(here, "install.sh"), encoding="utf-8").read()
    ok("install.sh מוריד את עצמו", "install.sh" in
       (ins.split("EXTRA=(", 1)[1].split(")", 1)[0] if "EXTRA=(" in ins else ""))
    ok("install.sh מעתיק את עצמו ל-DIR", '"$DIR/install.sh"' in ins)

    # כל נתיב שהמתקין וה-README מבטיחים חייב להיות נתיב שהמתקין יוצר
    promised = set(_re.findall(r"/opt/groupos/([A-Za-z0-9_.]+)", ins + open(
        os.path.join(here, "README.md"), encoding="utf-8").read()))
    delivered = set(listed) | {"install.sh", "README.md", "requirements.txt",
                               "manifest.txt", "data", ".env"}
    ok("כל קובץ שמבטיחים ב-/opt/groupos באמת מותקן",
       not (promised - delivered), str(promised - delivered))


# ── שפות ──────────────────────────────────────────────────────────────────
def test_i18n():
    section("שפות")
    ok("נרמול קוד שפה", i18n.normalize("he-IL") == "he")
    ok("קו תחתון גם", i18n.normalize("pt_BR") == "pt")
    ok("שפה לא מוכרת נופלת לברירת מחדל",
       i18n.normalize("קלינגונית") == i18n.DEFAULT)
    ok("None נופל לברירת מחדל", i18n.normalize(None) == i18n.DEFAULT)

    ok("עברית RTL", i18n.is_rtl("he"))
    ok("ערבית RTL", i18n.is_rtl("ar"))
    ok("אנגלית LTR", not i18n.is_rtl("en"))
    ok("רוסית LTR", not i18n.is_rtl("ru"))

    ok("תרגום קיים", i18n.t("menu.locks", "he") == "🔒 נעילות")
    ok("תרגום באנגלית", i18n.t("menu.locks", "en") == "🔒 Locks")
    ok("תרגום בערבית", "الأقفال" in i18n.t("menu.locks", "ar"))
    ok("חסר בערבית נופל לאנגלית",
       i18n.t("help.hint", "ar") == i18n.t("help.hint", "en")
       and "help.hint" not in i18n.STRINGS["ar"])
    ok("מפתח לא קיים מחזיר את עצמו",
       i18n.t("אין.כזה.מפתח", "he") == "אין.כזה.מפתח")

    ok("החלפת משתנה", i18n.t("warn.count", "he", n=3) == "אזהרות פתוחות: 3")
    ok("משתנה חסר לא מפיל", isinstance(i18n.t("warn.count", "he"), str))

    # כל מפתח שמופיע באנגלית חייב להופיע בעברית ולהפך — אחרת יש טקסט
    # שאף פעם לא יוצג בשפה שהיא ברירת המחדל
    he, en = set(i18n.STRINGS["he"]), set(i18n.STRINGS["en"])
    ok("עברית ואנגלית מכסות את אותם מפתחות", he == en,
       f"רק בעברית: {he-en} · רק באנגלית: {en-he}")

    cov = i18n.coverage()
    ok("עברית מכסה 100%", cov["he"] == 100.0, str(cov))
    ok("אנגלית מכסה 100%", cov["en"] == 100.0, str(cov))
    ok("לכל שפה יש שם לתצוגה",
       all(c in i18n.LANG_NAMES for c in i18n.STRINGS),
       str([c for c in i18n.STRINGS if c not in i18n.LANG_NAMES]))

    db = fresh()
    L = i18n.Lang(db)
    CHAT = -100888
    # ברירת המחדל היא אנגלית ולא עברית: בוט שמיועד לעולם לא מניח
    # שמי שפנה אליו קורא עברית
    ok("ברירת המחדל היא אנגלית", i18n.DEFAULT == "en")
    ok("שפה לא נתמכת נופלת לאנגלית", i18n.normalize("th") == "en")
    ok("טרם נבחרה שפה", L.chosen(CHAT) is None)
    ok("בלי בחירה — ברירת מחדל", L.for_chat(CHAT) == "en")
    ok("שפת המשתמש כשאין לקבוצה", L.resolve(CHAT, "ru") == "ru")
    L.set_chat(CHAT, "he")
    ok("שפת הקבוצה מנצחת", L.resolve(CHAT, "ru") == "he")
    ok("נשמר", L.for_chat(CHAT) == "he" and L.chosen(CHAT) == "he")

    # כל שפה שמוצעת בבורר חייבת לכסות את CORE
    for code, _ in i18n.available():
        holes = [k for k in i18n.CORE if k not in i18n.STRINGS[code]]
        ok(f"{code} מכסה את הליבה", not holes, str(holes[:5]))
    ok("יש לפחות שמונה שפות מוצעות", len(i18n.available()) >= 8,
       str(len(i18n.available())))


# ── משתנים בהודעות ────────────────────────────────────────────────────────
def test_templates():
    section("משתנים בהודעות")
    ctx = tpl.context(user_id=7, first="דוד", username="david",
                      chat_title="הקבוצה", chat_id=-100, count=42)
    ok("שם מוחלף", tpl.render("שלום {user}", ctx) == "שלום דוד")
    ok("username עם שטרודל", "@david" in tpl.render("{username}", ctx))
    ok("mention הוא קישור", 'tg://user?id=7' in tpl.render("{mention}", ctx))
    ok("מונה חברים", tpl.render("{count}", ctx) == "42")
    ok("משתנה לא מוכר נשאר", tpl.render("{smile}", ctx) == "{smile}")
    ok("סוגר בודד לא מפיל", isinstance(tpl.render("שלום { ", ctx), str))

    # הזרקת HTML דרך שם משתמש — הבוט שולח ב-HTML
    evil = tpl.context(user_id=1, first="<b>פריצה</b>")
    out = tpl.render("שלום {user}", evil)
    ok("שם עם תגיות עובר בריחה", "&lt;b&gt;" in out and "<b>פריצה" not in out, out)
    ok("mention נשאר HTML תקין", "<a href=" in tpl.render("{mention}", evil))

    ok("משתנה שאינו בהקשר נשאר", tpl.render("{risk}", {"user": "x"}) == "{risk}")
    ok("זיהוי משתנים בטקסט",
       tpl.used("שלום {user}, יש לך {warnings}") == {"user", "warnings"})

    picks = {tpl.pick("א|||ב|||ג") for _ in range(40)}
    ok("בחירה אקראית מכסה את כל הנוסחים", picks == {"א", "ב", "ג"}, str(picks))
    ok("בלי מפריד מחזיר את עצמו", tpl.pick("שלום") == "שלום")


# ── רשימת חסומים והתחמקויות ───────────────────────────────────────────────
def test_blocklist():
    section("רשימת חסומים")
    rules = [{"pattern": "spam", "kind": "word", "action": "delete"}]

    ok("מילה נחסמת", bl.check_text("this is spam here", rules) is not None)
    ok("מילה בתוך מילה לא נחסמת",
       bl.check_text("spammer? no. spamalot", rules) is None or
       bl.check_text("nospamhere", rules) is None)
    ok("הודעה נקייה עוברת", bl.check_text("שלום לכולם", rules) is None)

    # ההתחמקויות שספאמרים באמת משתמשים בהן
    evasions = {
        "נקודות": "s.p.a.m now",
        "רווחים": "s p a m",
        "leetspeak": "5p4m deal",
        "קירילית": "ѕраm offer",
        "רוחב אפס": "s\u200bp\u200ba\u200bm",
        "מקפים": "s-p-a-m",
    }
    for name, text in evasions.items():
        m = bl.check_text(text, rules)
        ok(f"התחמקות נתפסת: {name}", m is not None, repr(text))
        if m:
            ok(f"סומן כהתחמקות: {name}", m.evaded, name)

    # דומיינים
    dom = [{"pattern": "bad.com", "kind": "domain", "action": "ban"}]
    ok("דומיין נתפס", bl.check_text("go to https://bad.com/x", dom) is not None)
    ok("תת-דומיין נתפס", bl.check_text("a.bad.com", dom) is not None)
    ok("דומיין דומה לא נתפס", bl.check_text("notbad.com", dom) is None)
    ok("דומיין אחר לא נתפס", bl.check_text("good.com", dom) is None)

    # ביטוי רגולרי שבור של מנהל לא מפיל בדיקת הודעה
    broken = [{"pattern": "([", "kind": "regex", "action": "delete"}]
    ok("regex שבור לא מפיל", bl.check_text("כל טקסט", broken) is None)

    rx = [{"pattern": r"\bcrypto\s+deal\b", "kind": "regex", "action": "warn"}]
    ok("regex תקין עובד", bl.check_text("best CRYPTO  deal", rx) is not None)

    db = fresh()
    B = bl.Blocklist(db)
    CHAT = -100321
    ok("הוספה", B.add(CHAT, "ספאם"))
    ok("regex שבור לא נשמר", not B.add(CHAT, "([", "regex"))
    ok("סוג לא מוכר נדחה", not B.add(CHAT, "x", "קסם"))
    ok("נתפס דרך המסד", B.check(CHAT, "יש כאן ס.פ.א.ם") is not None)
    ok("בידוד בין קבוצות", B.check(-100999, "ספאם") is None)
    B.remove(CHAT, "ספאם")
    ok("הסרה", B.check(CHAT, "ספאם") is None)


# ── הערות ופילטרים ────────────────────────────────────────────────────────
def test_content():
    section("הערות ופילטרים")
    db = fresh()
    N, F = content.Notes(db), content.Filters(db)
    CHAT = -100654

    ok("שם מנוקה", content.clean_name("#כללי  ") == "כללי")
    ok("רווחים הופכים לקו תחתון", content.clean_name("שני חלקים") == "שני_חלקים")

    ok("שמירה", N.save(CHAT, "#rules", "החוקים כאן"))
    ok("הערה ריקה נדחית", not N.save(CHAT, "x", ""))
    n = N.get(CHAT, "rules")
    ok("שליפה", n is not None and n.content == "החוקים כאן")
    ok("שליפה עם סולמית", N.get(CHAT, "#rules") is not None)
    N.save(CHAT, "rules", "עודכן")
    ok("שמירה חוזרת דורסת", N.get(CHAT, "rules").content == "עודכן")
    ok("רשימה", N.names(CHAT) == ["rules"])
    N.save(CHAT, "פנימי", "רק למנהלים", visibility="admin")
    ok("הערת מנהלים מוסתרת", "פנימי" not in N.names(CHAT))
    ok("מנהל רואה אותה", "פנימי" in N.names(CHAT, include_admin=True))
    ok("מחיקה", N.delete(CHAT, "rules") == 1 and N.get(CHAT, "rules") is None)

    # כפתורים — קלט של משתמש
    rows = content.parse_buttons("אתר|https://a.com\nרע|javascript:alert(1)")
    ok("כפתור תקין נשמר", rows == [[("אתר", "https://a.com")]], str(rows))
    ok("javascript: נזרק",
       not any("javascript" in u for r in content.parse_buttons(
           "x|javascript:alert(1)") for _, u in r))
    ok("tg:// נזרק", content.parse_buttons("x|tg://user?id=1") == [])
    two = content.parse_buttons("א|https://a.com && ב|https://b.com")
    ok("שני כפתורים בשורה", len(two) == 1 and len(two[0]) == 2, str(two))

    ok("פילטר נשמר", F.add(CHAT, "שלום", "היי!"))
    h = F.check(CHAT, "שלום לכולם")
    ok("פילטר נורה", h is not None and h.content == "היי!")
    ok("מילה בתוך מילה לא יורה", F.check(CHAT, "שלומי הגיע") is None)
    ok("הודעה אחרת לא יורה", F.check(CHAT, "מה נשמע") is None)
    F.add(CHAT, "קנה", "פרסומת", match_kind="substring", action="delete")
    ok("substring יורה על חלק ממילה", F.check(CHAT, "תקנה עכשיו") is not None)
    ok("פעולה לא מוכרת נדחית", not F.add(CHAT, "x", "y", action="לרסק"))
    ok("regex שבור נדחה", not F.add(CHAT, "([", "y", match_kind="regex"))
    F.remove(CHAT, "שלום")
    ok("הסרה", F.check(CHAT, "שלום לכולם") is None)


# ── הצפה ──────────────────────────────────────────────────────────────────
def test_antiflood():
    section("הגנת הצפה")
    A = AntiFlood()
    CHAT, U = -100111, 5

    out = [A.note(CHAT, U, f"הודעה {i}", now=100 + i * 0.1, rate=5)
           for i in range(5)]
    ok("מתחת לסף לא נורה", not any(out), str(out))
    hit = A.note(CHAT, U, "עוד אחת", now=100.6, rate=5)
    ok("קצב נתפס", hit is not None and hit.kind == "rate")

    A2 = AntiFlood()
    slow = [A2.note(CHAT, U, f"שונה {i}", now=100 + i * 30, rate=5)
            for i in range(6)]
    ok("הודעות מפוזרות בזמן לא נתפסות", not any(slow))

    # ספאמר שנשאר מתחת לסף הקצב אבל חוזר על עצמו
    A3 = AntiFlood()
    rep = [A3.note(CHAT, U, "אותו טקסט", now=100 + i * 8, rate=50)
           for i in range(4)]
    ok("חזרתיות נתפסת גם מתחת לסף הקצב",
       rep[-1] is not None and rep[-1].kind == "repeat", str(rep))

    A4 = AntiFlood()
    ok("הצפת תיוגים נתפסת",
       (A4.note(CHAT, U, "היי", mentions=20, now=1) or
        type("x", (), {"kind": None})).kind == "mention")
    ok("תיוג בודד עובר", A4.note(CHAT, 6, "היי @a", mentions=1, now=1) is None)

    A5 = AntiFlood()
    joins = [A5.join(CHAT, now=100 + i, count=10) for i in range(10)]
    ok("הצטרפות המונית נתפסת",
       joins[-1] is not None and joins[-1].kind == "raid")
    ok("הצטרפות בודדת לא", AntiFlood().join(CHAT, now=1, count=10) is None)

    A6 = AntiFlood()
    for u in range(6000):
        A6.note(CHAT, u, "x", now=1)
    ok("תקרת זיכרון נאכפת", A6.stats()["users"] <= 5000, str(A6.stats()))


# ── אימות נכנסים ──────────────────────────────────────────────────────────
def test_captcha():
    section("אימות נכנסים")
    CHAT, U = -100222, 77

    b = cap.build(CHAT, U, "button", now=0, timeout=60)
    ok("כפתור: תשובה אחת", b.choices == ["ok"] and b.answer == "ok")
    ok("דדליין נקבע", b.deadline == 60)
    ok("טרם פג", not b.expired(now=59))
    ok("פג בזמן", b.expired(now=60))
    ok("זמן מינימלי נאכף", cap.build(CHAT, U, "button", timeout=0, now=0).deadline >= 10)

    m = cap.build(CHAT, U, "math", now=0)
    ok("תרגיל: התשובה בין האפשרויות", m.answer in m.choices)
    ok("תרגיל: ארבע אפשרויות", len(m.choices) == 4, str(m.choices))
    ok("תרגיל: בלי כפילויות", len(set(m.choices)) == 4)
    nums = [int(x) for x in _re_mod.findall(r"\d+", m.prompt)]
    ok("תרגיל: התשובה נכונה", sum(nums) == int(m.answer), m.prompt)

    e = cap.build(CHAT, U, "emoji", now=0)
    ok("אימוג'י: התשובה בין האפשרויות", e.answer in e.choices)
    ok("אימוג'י: בלי כפילויות", len(set(e.choices)) == 4)

    P = cap.Pending()
    P.add(cap.build(CHAT, U, "button", tries=2, now=time.time()))
    ok("ממתין", P.waiting(CHAT, U))
    ok("תשובה נכונה עוברת", P.answer(CHAT, U, "ok") == "ok")
    ok("אחרי הצלחה לא ממתין", not P.waiting(CHAT, U))
    ok("תשובה לאתגר שנסגר", P.answer(CHAT, U, "ok") == "gone")

    P.add(cap.build(CHAT, U, "math", tries=2, now=time.time()))
    ch = P.get(CHAT, U)
    wrong = next(c for c in ch.choices if c != ch.answer)
    ok("ניסיון ראשון שגוי מאפשר עוד", P.answer(CHAT, U, wrong) == "retry")
    ok("ניסיון אחרון שגוי מכשיל", P.answer(CHAT, U, wrong) == "fail")
    ok("אחרי כישלון האתגר נסגר", not P.waiting(CHAT, U))

    # אתגר שפג חייב להיסגר לבד — הנכנס מושתק כל עוד הוא פתוח
    P2 = cap.Pending()
    P2.add(cap.build(CHAT, 1, "button", timeout=10, now=0))
    P2.add(cap.build(CHAT, 2, "button", timeout=10, now=1000))
    gone = P2.expired(now=100)
    ok("פג נאסף", len(gone) == 1 and gone[0].user_id == 1, str(len(gone)))
    ok("שלא פג נשאר", P2.waiting(CHAT, 2))
    ok("שנאסף הוסר", not P2.waiting(CHAT, 1))
    ok("ספירה לפי קבוצה", P2.count(CHAT) == 1)


# ── מצב חירום ─────────────────────────────────────────────────────────────
def test_emergency():
    section("מצב חירום")
    db = fresh()
    CHAT = -100333

    db.set(CHAT, "flood", "0")
    db.set(CHAT, "silent", "1")
    ok("כבוי מלכתחילה", not emerg.is_on(db, CHAT))

    emerg.enable(db, CHAT, 5)
    ok("הופעל", emerg.is_on(db, CHAT))
    ok("הצפה הופעלה", db.get(CHAT, "flood") == "1")
    ok("אימות הופעל", db.get(CHAT, "captcha") == "1")
    ok("סף ההצפה הוקשח", int(db.get(CHAT, "flood_rate")) < 8)
    ok("מצב שקט כובה", db.get(CHAT, "silent") == "0")
    ok("הפעלה כפולה לא עושה כלום", emerg.enable(db, CHAT, 5) == {})

    emerg.disable(db, CHAT, 5)
    ok("כובה", not emerg.is_on(db, CHAT))
    # השחזור חייב להיות מדויק, אחרת מנהל יפחד ללחוץ
    ok("הצפה חזרה לכבוי", db.get(CHAT, "flood") == "0")
    ok("מצב שקט חזר", db.get(CHAT, "silent") == "1")
    ok("מפתח שלא היה קיים לא נשאר",
       db.get(CHAT, "captcha_kind") is None, str(db.get(CHAT, "captcha_kind")))
    ok("כיבוי כפול לא מפיל", not emerg.disable(db, CHAT, 5))

    # הרכב מותאם לקבוצה
    db.set(CHAT, "emergency_preset", '{"flood_rate": "2"}')
    emerg.enable(db, CHAT, 5)
    ok("דריסה פר-קבוצה נלקחת", db.get(CHAT, "flood_rate") == "2")
    emerg.disable(db, CHAT, 5)
    db.set(CHAT, "emergency_preset", "{לא json")
    ok("הרכב פגום לא מונע הפעלה", emerg.enable(db, CHAT, 5) != {})
    emerg.disable(db, CHAT, 5)

    st = emerg.status(db, CHAT)
    ok("מרכז האבטחה מחזיר את כל ההגנות", len(st) == len(emerg.PROTECTIONS))
    ok("לכל הגנה יש שם מתורגם",
       all(i18n.t(k, "en") != k for k, _ in st),
       str([k for k, _ in st if i18n.t(k, "en") == k]))


def main() -> int:
    print("בדיקות ליבה — GroupOS שלב 1")
    test_db()
    test_permissions()
    test_audit()
    test_ratelimit()
    test_locks()
    test_moderation()
    test_panel()
    test_templates()
    test_blocklist()
    test_content()
    test_antiflood()
    test_captcha()
    test_emergency()
    test_manifest()
    test_i18n()
    test_flow()
    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
