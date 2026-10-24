#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקות לתכונות שנוספו: שבת וחגים, שעות פתיחה, וזיהוי תוכן חריג.

אותו סגנון כמו ‎test_core‎: בלי pytest, בלי רשת, בלי טוקן. הפיד של
hebcal מוזרק כמילון, ולכן אפשר לבדוק שבת שלמה בשנייה אחת ביום שלישי.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grouphours as gh      # noqa: E402
import spamguard as sg       # noqa: E402
import prompts as pr        # noqa: E402
import evidence as ev       # noqa: E402
import zmanim as zm          # noqa: E402

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


# ── פיד לדוגמה ────────────────────────────────────────────────────────────
FEED = {
    "items": [
        {"category": "candles", "title": "Candle lighting: 17:42",
         "date": "2026-10-23T17:42:00+03:00"},
        {"category": "parashat", "title": "Parashat Noach",
         "hebrew": "פרשת נח"},
        {"category": "havdalah", "title": "Havdalah: 18:38",
         "date": "2026-10-24T18:38:00+03:00"},
    ]
}


def test_zmanim() -> None:
    section("זמני שבת")
    evs = zm.parse_feed(FEED)
    ok("הפיד נקרא", len(evs) == 3, str(evs))
    ok("הפיד כ-JSON גולמי", len(zm.parse_feed(json.dumps(FEED))) == 3)
    ok("פיד פגום אינו זורק", zm.parse_feed("<html>") == []
       and zm.parse_feed(None) == [])

    wins = zm.windows(evs, before=10, after=0)
    ok("חלון אחד", len(wins) == 1, str(wins))
    w = wins[0]
    ok("הנעילה עשר דקות לפני הכניסה", w.lock_at == w.candles - 600)
    ok("הפתיחה בצאת השבת", w.open_at == w.havdalah)
    ok("שם הפרשה נשמר", w.parasha == "פרשת נח")

    mid = (w.candles + w.havdalah) / 2
    ok("באמצע השבת — פעיל", w.active(mid) and not w.upcoming(mid))
    ok("לפני — צפוי", w.upcoming(w.lock_at - 60))
    ok("אחרי — לא פעיל", not w.active(w.open_at + 60))
    ok("current מוצא", zm.current(wins, mid) is w)
    ok("next_window מוצא", zm.next_window(wins, w.lock_at - 60) is w)
    ok("אין next אחרי", zm.next_window(wins, w.open_at + 1) is None)

    # כניסה בלי יציאה לא נועלת. עדיף לא לנעול מאשר לנעול בלי לדעת
    # מתי נפתח.
    half = zm.parse_feed({"items": [FEED["items"][0]]})
    ok("כניסה בלי יציאה אינה חלון", zm.windows(half) == [])

    # ההיסט מגיע מהפיד עצמו ולא מהגדרת הקבוצה — זה התיקון לשעות
    # שהוצגו ב-UTC (14:18 במקום 17:18).
    ok("ההיסט נקרא מהפיד", w.tz == 3 * 3600, str(w.tz))
    txt = zm.fill("{city} · {parasha} · {candles}–{havdalah}", w,
                  city="ירושלים")
    ok("תבנית מתמלאת", txt == "ירושלים · פרשת נח · 17:42–18:38", txt)
    ok("תאריך מלא", zm.fill("{fulldate}", w) == "23/10/2026",
       zm.fill("{fulldate}", w))
    rows = [zm.CityTime("jerusalem", "ירושלים", w.candles, w.havdalah, w.tz),
            zm.CityTime("haifa", "חיפה", w.candles + 600,
                        w.havdalah + 120, w.tz)]
    block = zm.times_block(rows)
    ok("לוח ערים נבנה",
       "ירושלים — 17:42" in block and "חיפה — 17:52" in block, block)
    ok("ובשתי קבוצות: כניסה ויציאה",
       block.count("ירושלים") == 2 and "18:38" in block, block)
    ok("לוח ריק אינו מייצר רעש", zm.times_block([]) == "")
    ok("{times} מוצב בתבנית",
       "חיפה" in zm.fill("א\n\n{times}", w, rows=rows))
    ok("משתנה לא מוכר נשאר",
       zm.fill("{nope}", w) == "{nope}")
    ok("סוגר מסולסל ביד אינו מפיל",
       "{" in zm.fill("שלום {", w))

    ok("כל עיר היא שלשה", all(len(v) == 3 for v in zm.CITIES.values()))
    ok("ברירת המחדל קיימת", zm.DEFAULT_CITY in zm.CITIES)
    ok("שם עיר בעברית ובאנגלית",
       zm.city_name("jerusalem", "he") == "ירושלים"
       and zm.city_name("jerusalem", "en") == "Jerusalem")
    ok("עיר לא מוכרת נופלת לברירת מחדל",
       zm.city_name("atlantis", "he") == "ירושלים")
    u = zm.url_for("telaviv")
    ok("ה-URL נושא geonameid", "geonameid=293397" in u, u)

    # המטמון: שתי קריאות, הורדה אחת
    calls = []

    async def fake(url: str, timeout: float) -> str:
        calls.append(url)
        return json.dumps(FEED)

    z = zm.Zmanim(transport=fake)
    asyncio.run(z.events("jerusalem", now=1000.0))
    asyncio.run(z.events("jerusalem", now=1100.0))
    ok("המטמון חוסך בקשה", len(calls) == 1, str(calls))
    asyncio.run(z.events("jerusalem", now=1000.0 + zm.CACHE_TTL + 1))
    ok("ופג אחרי הזמן", len(calls) == 2)

    async def boom(url: str, timeout: float) -> str:
        raise OSError("רשת")

    z2 = zm.Zmanim(transport=boom)
    ok("כישלון רשת אינו זורק",
       asyncio.run(z2.events("jerusalem")) == [] and z2.failures == 1)
    z.transport = boom
    ok("כישלון מחזיר את המטמון הישן",
       len(asyncio.run(z.events("jerusalem",
                                now=2 * zm.CACHE_TTL + 5000))) == 3)


def test_hours() -> None:
    section("שעות פתיחה")
    raw = "sun=08:00-23:00, mon=closed, tue=off, wed=22:00-02:00"
    sched = gh.parse(raw)
    ok("ארבעה ימים נקראו", len(sched) == 4, str(sched))
    ok("סגור כל היום", sched["mon"].mode == "closed")
    ok("ללא כלל", sched["tue"].mode == "off")
    ok("חציית חצות מזוהה", sched["wed"].wraps)
    ok("ניסוח שגוי מדלג ולא מפיל",
       gh.parse("mon=99:99, tue=08:00-09:00") == {"tue": gh.Day("range", 480, 540)})
    ok("הפורמט חוזר", gh.format_sched(gh.parse(raw)) ==
       "mon=closed, wed=22:00-02:00, sun=08:00-23:00",
       gh.format_sched(gh.parse(raw)))

    # ‎2026-10-21‎ הוא יום רביעי. חצות UTC, ובלי היסט.
    import calendar
    wed = float(calendar.timegm((2026, 10, 21, 0, 0, 0)))
    ok("נקודת הייחוס היא רביעי", time.gmtime(wed).tm_wday == 2)
    ok("חמישי לפנות בוקר עדיין פתוח מרביעי",
       gh.is_open(raw, now=wed + 24 * 3600 + 3600))        # חמישי 01:00
    # חמישי אינו בלוח כלל, ולכן אחרי שהזליגה מרביעי נגמרת הוא פתוח.
    ok("חמישי בשלוש — אין כלל, פתוח",
       gh.is_open(raw, now=wed + 24 * 3600 + 3 * 3600))
    ok("וכשיש לו כלל — סגור",
       not gh.is_open(raw + ", thu=08:00-23:00",
                      now=wed + 24 * 3600 + 3 * 3600))
    ok("לוח ריק = תמיד פתוח", gh.is_open("", now=wed))
    ok("רביעי בבוקר סגור", not gh.is_open(raw, now=wed + 9 * 3600))
    ok("רביעי בערב פתוח", gh.is_open(raw, now=wed + 23 * 3600))

    nxt = gh.next_change(raw, now=wed + 9 * 3600)
    ok("המעבר הבא הוא פתיחה", nxt is not None and nxt[1] is True, str(nxt))
    ok("והוא בעשר בערב", nxt is not None
       and abs(nxt[0] - (wed + 22 * 3600)) < 61, str(nxt))
    ok("לוח ריק אינו מחזיר מעבר", gh.next_change("", now=wed) is None)
    ok("לוח שכולו סגור אינו מחזיר מעבר",
       gh.next_change("mon=closed,tue=closed,wed=closed,thu=closed,"
                      "fri=closed,sat=closed,sun=closed", now=wed) is None)

    # טווח סגירה: כך אנשים מנסחים "סגור מחצות עד שבע"
    night = "mon=!00:00-07:00"
    mon = float(__import__("calendar").timegm((2026, 10, 19, 0, 0, 0)))
    ok("נקודת הייחוס היא שני", time.gmtime(mon).tm_wday == 0)
    ok("אחת בלילה סגור", not gh.is_open(night, now=mon + 3600))
    ok("שש וחצי סגור", not gh.is_open(night, now=mon + 6 * 3600 + 1800))
    ok("שמונה בבוקר פתוח", gh.is_open(night, now=mon + 8 * 3600))
    ok("אחת עשרה בלילה פתוח", gh.is_open(night, now=mon + 23 * 3600))
    ok("הניסוח נשמר כפי שנבחר",
       gh.format_sched(gh.parse(night)) == night,
       gh.format_sched(gh.parse(night)))
    ok("המעבר הבא הוא פתיחה בשבע",
       gh.next_change(night, now=mon + 3600)[1] is True
       and abs(gh.next_change(night, now=mon + 3600)[0]
               - (mon + 7 * 3600)) < 61,
       str(gh.next_change(night, now=mon + 3600)))
    # סגירת לילה שחוצה חצות: ‎!23:00-06:00‎
    over = "mon=!23:00-06:00"
    ok("לפני הסגירה פתוח", gh.is_open(over, now=mon + 22 * 3600))
    ok("אחרי 23 סגור", not gh.is_open(over, now=mon + 23 * 3600 + 600))
    ok("וגם בשלוש לפנות בוקר למחרת",
       not gh.is_open(over, now=mon + 27 * 3600))
    ok("ובשבע כבר פתוח", gh.is_open(over, now=mon + 31 * 3600))

    ok("set_day מחליף יום",
       gh.parse(gh.set_day(raw, "mon", "09:00-17:00"))["mon"].open_min == 540)
    # ‎off‎ אינו "יום סגור" אלא "אין כלל ליום הזה", ולכן הוא נעלם
    # מהלוח במקום להישמר כשורה שאומרת כלום.
    ok("set_day מסיר יום", "mon" not in gh.parse(gh.set_day(raw, "mon", "off")))
    ok("תיאור קריא נבנה",
       "08:00–23:00" in gh.describe(raw, {"sun": "ראשון"}), gh.describe(raw))


def test_spamguard() -> None:
    section("תוכן חריג")
    ok("נרמול מפרק ערפול",
       sg.squeeze("Ch1ld  L a dybo y") == "childladyboy",
       sg.squeeze("Ch1ld  L a dybo y"))
    ok("אותיות מתחזות מנורמלות", "paypal" in sg.squeeze("раypal"))
    ok("תווים בלתי נראים מוסרים",
       sg.squeeze("te​ens") == "teens")
    ok("מספר נשאר מספר", "2026" in sg.normalize("שנת 2026"))

    v = sg.classify("💦Ch1ld 💜 Ladyboy 💝 Te ens 14-16 😻 Gay")
    ok("המודעה מהקבוצה נתפסת", v is not None and v.kind == "illegal", str(v))
    ok("והיא מסלול נפרד", v is not None and v.escalate and v.weight >= 0.95)

    v2 = sg.classify("100% RAW SCANDAL IS FULLY UNLOCKED — GRAB THIS LINK")
    # מודעה, לא אזכור: מונח מיני יחד עם קריאה לפעולה. זה מה שמוצף
    # בטלגרם כל עשר שניות, ולכן הוא מסלול מהיר ולא ציון מצטבר.
    ok("פיתיון מיני נתפס", v2 is not None and v2.kind == "adult_ad", str(v2))
    ok("והוא מסלים", v2 is not None and v2.escalate)
    v3 = sg.classify("יש פה הרבה דיבורים על סקס לאחרונה")
    ok("אזכור בלי הזמנה אינו מסלים",
       v3 is not None and not v3.escalate, str(v3))

    for clean in ("שלום לכולם, מה המצב?",
                  "Hey, photos from the kids school trip are up",
                  "I reported a channel sharing child abuse to the police",
                  "Meeting at 14-16 tomorrow"):
        ok(f"תקין אינו נתפס: {clean[:28]}", sg.classify(clean) is None,
           str(sg.classify(clean)))
    ok("ריק מחזיר None", sg.classify("") is None and sg.classify("   ") is None)
    ok("אימוג׳ים בלבד אינם פסק", sg.classify("😀😀😀") is None)

    ok("ערפול מזוהה לעצמו", sg.obfuscated("fr3e g1ft"))
    ok("טקסט רגיל אינו מעורפל", not sg.obfuscated("free gift tomorrow"))

    # טביעה: אותה תמונה, כיתוב מתחלף — אותה טביעה? לא. אבל אותה
    # תמונה עם אותו כיתוב כן, ותמונה בלי כיתוב כן.
    a = sg.fingerprint(text="", media_id="AgACabc")
    b = sg.fingerprint(text="", media_id="AgACabc")
    c = sg.fingerprint(text="", media_id="other")
    ok("אותה מדיה — אותה טביעה", a == b and a != c)
    ok("אותו טקסט בניסוח מעורפל — אותה טביעה",
       sg.fingerprint(text="Fr3e  gift") == sg.fingerprint(text="free gift"))

    tr = sg.RepeatTracker(window=60)
    last = None
    for i in range(3):
        last = tr.note(a, chat_id=-100, user_id=7, now=1000.0 + i)
    ok("שלוש פעמים נספרות", last is not None and last.count == 3)
    ok("וזו חזרתיות", sg.repeat_verdict(last) is not None)
    ok("פעם אחת אינה", sg.repeat_verdict(
        sg.RepeatTracker().note(a, -100, 8, now=1.0)) is None)

    tr2 = sg.RepeatTracker(window=60)
    tr2.note(a, chat_id=-100, user_id=9, now=1000.0)
    spread = tr2.note(a, chat_id=-200, user_id=9, now=1001.0)
    ok("אותו תוכן בשתי קבוצות", spread.chats == 2)
    ver = sg.repeat_verdict(spread)
    ok("פיזור שוקל יותר מכמות",
       ver is not None and ver.weight >= 0.7, str(ver))

    old = tr2.note(a, chat_id=-100, user_id=9, now=1000.0 + 600)
    ok("החלון מתיישן", old.count == 1, str(old))



def test_prompts() -> None:
    section("עריכה בכפתורים")
    ok("כל שדה מצהיר על מפתח",
       all(f.key for f in pr.FIELDS.values()))
    ok("שמות השדות קצרים למזהה כפתור",
       all(len(n) <= 10 for n in pr.FIELDS), str(list(pr.FIELDS)))
    ok("כל שדה ברשימות קיים",
       all(n in pr.FIELDS for n in
           pr.TEXT_FIELDS + pr.SHAB_FIELDS + pr.NUMBER_FIELDS))

    p = pr.Pending(ttl=10)
    ok("שדה לא מוכר אינו נפתח", p.start(5, -100, "nope") is None)
    w = p.start(5, -100, "welcome", now=100.0)
    ok("ההמתנה נפתחה", w is not None and p.get(5, 101.0) is w)
    ok("ולמשתמש אחר אין", p.get(6, 101.0) is None)
    ok("היא פגה", p.get(5, 200.0) is None)
    p.start(5, -100, "welcome", now=100.0)
    p.start(5, -100, "rules", now=101.0)
    got = p.get(5, 102.0)
    ok("לחיצה שנייה מחליפה ולא מוסיפה",
       got is not None and got.field == "rules" and p.count() == 1)
    p.clear(5)
    ok("ביטול מנקה", p.get(5, 102.0) is None and p.count() == 0)

    ok("מספר נשמר", pr.validate("floodrate", " 12 ") == ("12", ""))
    ok("מספר מחוץ לטווח נחתך ולא נדחה",
       pr.validate("floodrate", "9999") == ("60", ""))
    ok("טקסט במקום מספר נדחה",
       pr.validate("floodrate", "הרבה")[0] is None)
    ok("מקף מוחק", pr.validate("welcome", "-") == ("", ""))
    ok("טקסט ארוך מדי נדחה",
       pr.validate("aictx", "א" * 500)[0] is None)
    ok("טקסט תקין נשמר",
       pr.validate("aictx", " קבוצת סרטים ") == ("קבוצת סרטים", ""))
    ok("שדה לא מוכר", pr.validate("nope", "x")[0] is None)


def test_media_talk() -> None:
    section("שיחה על יצירה מול מודעה")
    talk = ["קזינו 1995 סרט של סקורסזה, יש כתוביות?",
            "Casino Royale 2006 1080p",
            "עונה 3 פרק 5 עלה אתמול",
            "מישהו ראה את The Deuce? סדרה מעולה"]
    ads = ["קזינו אונליין הצטרפו עכשיו בונוס t.me/x",
           "סרטי פורנו מלאים בערוץ שלנו",
           "Full HD porn 2024 free",
           "סרטי פורנו בלעדיים, הצטרפו לערוץ @xxxxxxx",
           "הימורים בטוחים! לחצו כאן https://bet.example"]
    for t in talk:
        ok(f"שיחה: {t[:26]}", sg.talks_not_sells(t), str(sg.media_context(t)))
    for t in ads:
        ok(f"מודעה: {t[:26]}", not sg.talks_not_sells(t),
           f"ctx={sg.media_context(t)} cta={sg.solicits(t)}")


def test_aggressive() -> None:
    section("מצב אגרסיבי")
    ad = "💋 100% RAW SCANDAL IS FULLY UNLOCKED ✅ GRAB THIS LINK NOW"
    v = sg.classify(ad)
    ok("מודעה מינית עם קריאה לפעולה מסלימה",
       v is not None and v.kind == "adult_ad" and v.escalate, str(v))
    v2 = sg.classify("Hot nudes, join now @somechannel")
    ok("גם תיוג נחשב הזמנה",
       v2 is not None and v2.escalate, str(v2))
    v3 = sg.classify("מישהו ראה את The Deuce? סדרה על תעשיית הפורנו")
    ok("שיחה על יצירה אינה מסלימה",
       v3 is not None and not v3.escalate, str(v3))

    tr = sg.RepeatTracker(window=60)
    tr.note("fp", -100, 7, now=1.0)
    second = tr.note("fp", -100, 7, now=11.0)
    ok("פעם שנייה כבר חזרתיות", sg.repeat_verdict(second) is not None,
       str(sg.repeat_verdict(second)))
    ok("ומשקלה גבוה מספיק למחיקה",
       sg.repeat_verdict(second).weight >= 0.5)



def test_city_rows() -> None:
    section("לוח רב-ערים")
    import asyncio as _aio
    feeds = {
        "jerusalem": ("2026-10-23T17:18:00+03:00", "2026-10-24T18:34:00+03:00"),
        "haifa": ("2026-10-23T17:28:00+03:00", "2026-10-24T18:34:00+03:00"),
        "telaviv": ("2026-10-23T17:39:00+03:00", "2026-10-24T18:36:00+03:00"),
    }
    seen = []

    async def fake(url: str, timeout: float) -> str:
        key = next(k for k, v in zm.CITIES.items() if f"geonameid={v[2]}" in url)
        seen.append(key)
        c, h = feeds.get(key, feeds["jerusalem"])
        return json.dumps({"items": [
            {"category": "candles", "title": "c", "date": c},
            {"category": "parashat", "hebrew": "פרשת לך־לך"},
            {"category": "havdalah", "title": "h", "date": h}]})

    z = zm.Zmanim(transport=fake)
    now = zm._ts("2026-10-22T12:00:00+03:00")[0]
    rows = _aio.run(z.city_rows(["jerusalem", "haifa", "telaviv"], now=now))
    ok("שורה לכל עיר", len(rows) == 3, str(rows))
    ok("ולכל אחת השעה שלה",
       [zm.clock(r.candles, r.tz) for r in rows] == ["17:18", "17:28", "17:39"],
       str([zm.clock(r.candles, r.tz) for r in rows]))
    ok("עיר לא מוכרת מושמטת",
       len(_aio.run(z.city_rows(["jerusalem", "atlantis"], now=now))) == 1)
    n = len(seen)
    _aio.run(z.city_rows(["jerusalem", "haifa"], now=now))
    ok("המטמון חוסך בקשות חוזרות", len(seen) == n, str(seen))

    block = zm.times_block(rows)
    ok("הלוח מכיל את כל הערים",
       all(c in block for c in ("ירושלים", "חיפה", "תל אביב")), block)



def test_evidence() -> None:
    section("יומן אכיפה")
    import os as _os
    import tempfile as _tmp
    _os.environ["GROUPOS_DB"] = _os.path.join(
        _tmp.mkdtemp(prefix="groupos_ev_"), "t.db")
    import importlib
    import db as _db
    importlib.reload(_db)
    d = _db.Db()
    e = ev.Evidence(d)
    CHAT, U = -100, 7

    i1 = e.add(CHAT, U, action="ban", reason="spam.adult_ad", risk=0.95,
               text="💋 RAW SCANDAL — GRAB THIS LINK", media_kind="photo",
               media_id="AgACfile", name="ספאמר", now=1000.0)
    e.add(CHAT, U, action="delete", reason="lock.url", text="t.me/x",
          name="ספאמר", now=900.0)
    e.add(CHAT, 8, action="mute", reason="flood.rate", text="aaa",
          name="דנה", now=800.0)
    ok("נשמר", i1 > 0)
    ok("שלושה מקרים", e.count(CHAT) == 3, str(e.count(CHAT)))
    rec = e.recent(CHAT, 10)
    ok("החדש ראשון", rec[0].id == i1 and rec[0].action == "ban")
    ok("הטקסט נשמר", "SCANDAL" in rec[0].text)
    ok("והמדיה כ-file_id", rec[0].has_media and rec[0].media_id == "AgACfile")
    ok("תצוגה מקדימה נחתכת", len(rec[0].preview(10)) <= 11, rec[0].preview(10))
    ok("מדיה בלי טקסט מתוארת",
       ev.Item(1, CHAT, U, 0, "ban", "", 0, "", "photo", "f", "x")
       .preview() == "[photo]")
    ok("לפי משתמש", len(e.for_user(CHAT, U)) == 2)
    ok("ספירה לפי משתמש", e.count_user(CHAT, U) == 2)
    ok("שליפה לפי מזהה", e.get(CHAT, i1) is not None)
    ok("קבוצה אחרת אינה רואה", e.get(-200, i1) is None)

    # טקסט ארוך נחתך, ושמירה כושלת אינה זורקת
    long_id = e.add(CHAT, U, action="warn", text="א" * 5000, now=1100.0)
    ok("טקסט ארוך נחתך",
       len(e.get(CHAT, long_id).text) <= ev.MAX_TEXT)

    class Broken:
        def run(self, *a, **k):
            raise RuntimeError("מסד נפל")

    ok("כישלון שמירה אינו מפיל אכיפה",
       ev.Evidence(Broken()).add(CHAT, U, action="ban") == 0)

    # תפוגה: גיל ותקרה. חותמי זמן אמיתיים, אחרת חישוב הגיל מוחק הכול.
    base = 1_700_000_000.0
    e.add(CHAT, U, action="ban", text="ישן", now=base - 40 * 86400)
    e.add(CHAT, U, action="ban", text="טרי", now=base - 86400)
    before = e.count(CHAT)
    gone = e.prune(days=30, rows=500, now=base)
    ok("ישן נמחק והטרי נשאר",
       gone >= 1 and e.count(CHAT) == before - gone
       and any(x.text == "טרי" for x in e.recent(CHAT, 50)),
       f"{gone} {e.count(CHAT)}")
    for i in range(12):
        e.add(CHAT, 9, action="delete", text=f"x{i}", now=base + i)
    e.prune(days=3650, rows=5, now=base + 100)
    ok("תקרה לכל קבוצה נאכפת", e.count(CHAT) == 5, str(e.count(CHAT)))


def main() -> int:
    test_zmanim()
    test_city_rows()
    test_hours()
    test_spamguard()
    test_prompts()
    test_evidence()
    test_media_talk()
    test_aggressive()
    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
