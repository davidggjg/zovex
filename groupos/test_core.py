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
from locks import Locks, LOCK_TYPES, ACTIONS, detect  # noqa: E402
from moderation import Moderation, parse_policy, format_policy  # noqa: E402
import panel  # noqa: E402
import i18n  # noqa: E402
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



# ── נעילות ────────────────────────────────────────────────────────────────
def test_locks():
    section("נעילות")
    ok("כל סוג נעילה שייך לקבוצה מוכרת",
       all(g in ("מדיה", "קישורים", "אינטראקציה", "טקסט")
           for _, g in LOCK_TYPES.values()))

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
    ok("שם הנעילה בעברית", h.label == "קישורים", h.label)
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
        "lockg": panel.locks_in_group(CHAT, "מדיה",
                                      [("photo", "תמונות", "off"),
                                       ("video", "סרטונים", "ban")]),
        "warns": panel.warns_screen(CHAT, "3:mute:3600", [(1, "דוד", 2)]),
        "audit": panel.audit_screen(CHAT, [], lambda t: "12:00"),
        "settings": panel.settings_screen(CHAT, {"autoclean": "30"}),
    }
    for name, sc in screens.items():
        ok(f"מסך {name}: יש טקסט", bool(sc.text.strip()))
        bad = [c for c in sc.all_callbacks()
               if panel.parse_cb(c) is None or len(c.encode()) > panel.CB_MAX]
        ok(f"מסך {name}: כל הכפתורים תקפים", not bad, str(bad))

    for name in ("main", "locks", "lockg", "warns", "audit", "settings"):
        has_back = any("חזרה" in lbl or "לרשימת" in lbl
                       for row in screens[name].rows for lbl, _ in row)
        ok(f"מסך {name}: יש דרך חזרה", has_back)

    ok("מסך ריק מסביר מה לעשות",
       "הוסף אותי לקבוצה" in panel.home([]).text)

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
            "lockg": panel.locks_in_group(CHAT, "מדיה",
                                          [("photo", "תמונות", "ban")], lg),
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
       i18n.t("help.title", "ar") == i18n.t("help.title", "en"))
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
    ok("ברירת מחדל לקבוצה", L.for_chat(CHAT) == "he")
    ok("שפת המשתמש כשאין לקבוצה", L.for_user(CHAT, 1, "ru") == "ru")
    L.set_chat(CHAT, "en")
    ok("שפת הקבוצה מנצחת", L.for_user(CHAT, 1, "ru") == "en")
    ok("נשמר", L.for_chat(CHAT) == "en")


def main() -> int:
    print("בדיקות ליבה — GroupOS שלב 1")
    test_db()
    test_permissions()
    test_audit()
    test_ratelimit()
    test_locks()
    test_moderation()
    test_panel()
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
