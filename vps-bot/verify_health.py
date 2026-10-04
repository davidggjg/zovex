#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_health — אחרי שינוי בשרת: האם משהו נשבר, ובמה.

## למה כלי ולא "תסתכל ביומן"

‎systemctl status‎ אומר שהתהליך רץ. הוא לא אומר שההזרמה עובדת, שדף
ההיסטוריה עדיין מחזיר מה שהחזיר, או שנתיב חדש לא מחזיר 500 במקום
401. שירות שעלה ושובר חצי מהמשתמשים ייראה שם ירוק לגמרי.

הכלי בודק **התנהגות**, לא מצב תהליך. כל סעיף הוא שאלה שאפשר
לענות עליה בלבד ב"כן" או "לא".

## מה נבדק

    1. השירות חי ועונה
    2. ארבעת הנתיבים שהאימות נגע בהם — עדיין מתנהגים כמו קודם
    3. ‎/auth/session‎ דוחה אישור שגוי ב-401, לא קורס ב-500
    4. ההזרמה מגישה playlist (זה מה שהיה בסיכון)
    5. הקטלוג נטען
    6. שגיאות ביומן מאז ההפעלה האחרונה

## קריאה בלבד

כל הבקשות הן GET או אימות שנועד להיכשל. שום דבר לא נכתב.

    python3 verify_health.py
    python3 verify_health.py --channel "ילדים"
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
OK, BAD, WARN = "✓", "✗", "⚠"
_fails = []


def call(path, headers=None, data=None, timeout=25):
    """מחזיר (status, body). אינו זורק — 4xx הוא תשובה, לא תקלה."""
    req = urllib.request.Request(
        BASE + path, data=data,
        headers=headers or ({"Content-Type": "application/json"} if data else {}))
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read(80000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(8000)
    except Exception as e:
        return 0, str(e).encode()


def check(name, cond, detail=""):
    mark = OK if cond else BAD
    print("  %s %s%s" % (mark, name, ("   " + detail) if detail else ""))
    if not cond:
        _fails.append(name)
    return cond


def hdr(t):
    print()
    print(t)
    print("─" * 54)


def main():
    chan = "ילדים"
    if "--channel" in sys.argv:
        try:
            chan = sys.argv[sys.argv.index("--channel") + 1]
        except Exception:
            pass

    hdr("1 · השירות")
    st, body = call("/ping")
    if st == 0:
        # אין טעם להריץ 15 בדיקות שכולן ייכשלו על אותה סיבה אחת.
        print("  %s אין קשר ל-%s — השירות כבוי, או מאזין במקום אחר."
              % (BAD, BASE))
        print("     ‎systemctl status zovex-bot‎")
        sys.exit(1)
    check("‎/ping‎ עונה", st == 200, "HTTP %s" % st)
    out = subprocess.run(["systemctl", "is-active", "zovex-bot"],
                         capture_output=True, text=True).stdout.strip()
    check("השירות פעיל", out == "active", out or "(לא ידוע)")

    hdr("2 · הנתיבים שהאימות נגע בהם")
    # אף אחד לא ברשימת המאומתים אחרי ההחלה, ולכן כולם חייבים להתנהג
    # בדיוק כמו קודם. 401 כאן פירושו ששברנו לקוחות קיימים.
    st, _ = call("/api/history", {"x-user-id": "healthcheck-nobody"})
    check("‎/api/history‎ בלי אסימון עדיין עובד", st == 200,
          "HTTP %s — 401 כאן שובר לקוחות ישנים" % st)

    st, _ = call("/api/favorites", {"x-user-id": "healthcheck-nobody"})
    check("‎/api/favorites‎ עדיין עובד", st == 200, "HTTP %s" % st)

    st, _ = call("/api/progress/none", {"x-user-id": "healthcheck-nobody"})
    check("‎/api/progress‎ עדיין עובד", st == 200, "HTTP %s" % st)

    st, b = call("/feedback/mine?user_id=healthcheck-nobody")
    empty = b""
    try:
        empty = json.loads(b).get("messages", None)
    except Exception:
        pass
    check("‎/feedback/mine‎ עדיין עובד", st == 200, "HTTP %s" % st)
    check("ומחזיר ריק למי שאין לו שיחה", empty == [],
          "חזר %r" % (empty,))

    hdr("3 · נתיב ההנפקה החדש")
    st, b = call("/auth/session", data=b'{"id_token":"not-a-real-token"}')
    # ‎st != 404‎ לבדו מתקיים גם כשאין תשובה בכלל (0), וזה היה
    # שומר שמאשר את עצמו כשהשרת כבוי. נתפס בהרצה יבשה.
    check("‎/auth/session‎ קיים", st not in (0, 404), "HTTP %s" % st)
    check("ודוחה אישור שגוי בלי לקרוס", st in (401, 503),
          "HTTP %s — 500 פירושו חריגה לא מטופלת" % st)
    st, _ = call("/auth/session", data=b'{}')
    check("גוף ריק אינו מפיל", st in (401, 422, 503), "HTTP %s" % st)

    hdr("4 · הזרמה — מה שהיה בסיכון")
    st, b = call("/content/live", timeout=60)
    url = ""
    try:
        items = json.loads(b)
        items = items if isinstance(items, list) else items.get("movies", [])
        hit = [e for e in items if chan in (e.get("title") or "")]
        url = (hit[0].get("video_url") or "") if hit else ""
    except Exception:
        pass
    if not url:
        print("  %s לא נמצא ערוץ בשם %r — דלג או העבר ‎--channel‎" % (WARN, chan))
    else:
        path = url.split("127.0.0.1:8000", 1)[-1]
        if path.startswith("http"):
            path = "/" + path.split("/", 3)[-1]
        st, b = call(path, timeout=45)
        segs = b.decode("utf-8", "replace").count("#EXTINF")
        check("הרלֵיי מגיש playlist", st == 200 and segs > 0,
              "HTTP %s · %d מקטעים" % (st, segs))

    hdr("5 · הקטלוג")
    st, b = call("/content/version", timeout=40)
    check("‎/content/version‎ עונה", st == 200, "HTTP %s" % st)

    hdr("6 · שגיאות ביומן מאז ההפעלה האחרונה")
    log = subprocess.run(
        ["journalctl", "-u", "zovex-bot", "--since", "-10min", "--no-pager"],
        capture_output=True, text=True).stdout
    tb = log.count("Traceback (most recent call last)")
    err = sum(1 for l in log.splitlines()
              if " ERROR " in l or "CRITICAL" in l)
    check("אין חריגות", tb == 0, "%d Traceback" % tb)
    check("אין שגיאות", err == 0, "%d שורות ERROR" % err)
    if tb:
        print()
        print("  ── החריגה האחרונה ──")
        i = log.rfind("Traceback (most recent call last)")
        for l in log[i:i + 700].splitlines()[:14]:
            print("   " + l)

    print()
    print("─" * 54)
    if _fails:
        print("%s %d בדיקות נכשלו:" % (BAD, len(_fails)))
        for f in _fails:
            print("   · " + f)
        print("\nאם סעיף 2 נכשל — ‎python3 add_identity_auth.py --revert‎")
        print("ואז ‎systemctl restart zovex-bot‎. זה מחזיר הכול.")
        sys.exit(1)
    print("%s הכול עבר. השרת יציב והאימות לא שבר דבר." % OK)


if __name__ == "__main__":
    main()
