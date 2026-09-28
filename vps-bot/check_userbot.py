#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_userbot — למה ההעלאה מהטלפון אומרת "אין חשבון מחובר".

## הסתירה שדווחה

    באפליקציה:   "חשבון לא מחובר"
    בפאנל ניהול: מחובר

שתי התשובות נכונות, כי הן על שני דברים שונים. הפאנל סופר **חברי pool**,
וה-pool הוא בעיקר בוטים. ההעלאה ל"הודעות שמורות" אינה יכולה לרוץ דרך
בוט — הודעות שמורות שייכות לחשבון, ובוט אינו חשבון. היא דורשת חבר pool
אחד מסוג ‎user‎, כלומר ‎session string‎ של חשבון אמיתי ולא טוקן בוט:

    _pick_userbot()  →  [b for b in _stream_bots if b["kind"] == "user"]

ולכן "16 בוטים פעילים" ו"אין חשבון מחובר" יכולים להיות נכונים באותו רגע.

## שלוש סיבות אפשריות, והסקריפט מפריד ביניהן

1. **אין חשבון ב-stream_bots.txt בכלל** — רק טוקני בוט. אז זה מעולם לא
   עבד, ולא נשבר.
2. **יש חשבון בקובץ אבל הוא לא עלה.** ‎c.start()‎ נכשל — session שפג,
   תקלת רשת, או האטה של טלגרם בזמן שעולים 16 חברים בזה אחר זה. זה
   בדיוק מה שקורה אחרי הפעלה מחדש של השרת.
3. **החשבון עלה, אבל ‎SAVED_UPLOAD_USER‎ לא תואם.** הבחירה מחייבת
   התאמה מדויקת לשם המשתמש, ומי שביקש חשבון מסוים ולא נמצא — נדחה
   בכוונה, כדי לא לשלוח סרטון פרטי לחשבון הלא נכון.

   ויש כאן מלכודת: ‎who‎ נקרא פעם אחת בעלייה בתוך ‎try/except: pass‎.
   אם ‎get_me()‎ חרג מ-15 שניות — שוב, בדיוק בהפעלה מחדש — ‎who‎ נשאר
   ריק, ההתאמה לעולם לא תצליח, ואין שום שורה ביומן שאומרת את זה.

## מה הסקריפט עושה

קורא בלבד. אינו כותב, אינו מפעיל מחדש, ואינו מדפיס שום סוד: לא טוקנים,
לא session strings, לא סיסמת הפאנל ולא קוד ההעלאה — רק אורך וסוג.

    python3 check_userbot.py
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

BOT_DIR = os.environ.get("BOT_DIR", "/opt/zovex-bot")
BOTS_FILE = os.path.join(BOT_DIR, "stream_bots.txt")
ENV_FILE = os.environ.get("BOT_ENV", os.path.join(BOT_DIR, ".env"))
BASE = os.environ.get("BOT_URL", "http://127.0.0.1:8000")
SERVICE = os.environ.get("BOT_SERVICE", "zovex-bot")

# אותו ביטוי שבו main.py מבדיל טוקן בוט מ-session string
IS_BOT_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")


def head(t):
    print(f"\n──── {t} ────")


ENV_SOURCE = ""


def _parse_env_file(path, env):
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return True


def read_env():
    """משתני הסביבה של השירות **כפי שהתהליך החי רואה אותם**.

    הגרסה הראשונה קראה רק את ‎/opt/zovex-bot/.env‎, והיא דיווחה
    "UPLOAD_PANEL_CODE חסר" על שרת שבו הפאנל נפתח מצוין ו-
    "SAVED_UPLOAD_USER לא מוגדר" על שרת שבו הוא בהחלט מוגדר. כלומר
    הכלי הסיק "לא מוגדר" ממה שהוא **לא הצליח לקרוא** — וזו מסקנה
    גרועה יותר מ"לא יודע", כי היא נשמעת כמו תשובה.

    מקור האמת הוא סביבת התהליך עצמו: לא משנה אם ההגדרה הגיעה מ-.env,
    מ-Environment= ביחידת systemd, או מ-EnvironmentFile אחר.

    הערכים נשמרים בזיכרון ולעולם אינם מודפסים — רק "מוגדר"/"חסר".
    """
    global ENV_SOURCE
    env = {}

    # 1. סביבת התהליך החי — התשובה היחידה שאינה ניחוש
    try:
        pid = subprocess.run(
            ["systemctl", "show", SERVICE, "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if pid.isdigit() and int(pid) > 0:
            with open(f"/proc/{pid}/environ", "rb") as fh:
                for part in fh.read().split(b"\0"):
                    s = part.decode("utf-8", "replace")
                    if "=" in s:
                        k, v = s.split("=", 1)
                        env[k] = v
            if env:
                ENV_SOURCE = f"סביבת התהליך החי (pid {pid})"
                return env
    except Exception:
        pass

    # 2. ה-EnvironmentFile שהיחידה מצהירה עליו
    try:
        out = subprocess.run(
            ["systemctl", "show", SERVICE, "-p", "EnvironmentFiles", "--value"],
            capture_output=True, text=True, timeout=15).stdout
        files = re.findall(r"(/\S+?)(?:\s|$)", out)
        used = [f for f in files if _parse_env_file(f.lstrip("-"), env)]
        if used:
            ENV_SOURCE = "EnvironmentFile: " + ", ".join(used)
            return env
    except Exception:
        pass

    # 3. ברירת המחדל הישנה
    if _parse_env_file(ENV_FILE, env):
        ENV_SOURCE = ENV_FILE
    else:
        ENV_SOURCE = ""
    return env


def main():
    print("בדיקת חשבון ההעלאה — קריאה בלבד")

    # ── 1. מה מוגדר בקובץ ────────────────────────────────────────────────
    head("1. מה כתוב ב-stream_bots.txt")
    if not os.path.exists(BOTS_FILE):
        print(f"  ✗ אין קובץ ב-{BOTS_FILE} — אין pool בכלל.")
        return 1
    lines = [t.strip() for t in
             open(BOTS_FILE, encoding="utf-8").read().splitlines() if t.strip()]
    bots = [t for t in lines if IS_BOT_TOKEN.match(t)]
    users = [t for t in lines if not IS_BOT_TOKEN.match(t)]
    print(f"  שורות: {len(lines)}  ·  טוקני בוט: {len(bots)}  ·  "
          f"חשבונות (session string): {len(users)}")
    if not users:
        print("  ✗ אין אף חשבון בקובץ — רק בוטים.")
        print("    ההעלאה להודעות שמורות לא יכולה לעבוד כך, ולא בגלל תקלה:")
        print("    בוט אינו יכול לכתוב להודעות השמורות של חשבון.")
        print("    צריך להוסיף session string של חשבון בטאב 'בוטים' בפאנל.")
    else:
        # רק אורך. session string הוא סוד גמור ואינו מודפס.
        for i, t in enumerate(users):
            print(f"  · חשבון #{i}: מחרוזת באורך {len(t)} תווים")
        print(f"  ← {len(users)} מוגדרים. כמה מהם עלו — בסעיף 2.")

    # ── 2. מה עלה בפועל ──────────────────────────────────────────────────
    head("2. מי עלה בפועל ב-pool")
    env = read_env()
    pw = env.get("PANEL_PASSWORD") or env.get("ADMIN_PASSWORD") or ""
    live_users = []
    if not pw:
        print("  ⚠️ לא נמצאה סיסמת פאנל — מדלג על השאילתה.")
        print(f"     (מקור הסביבה: {ENV_SOURCE or 'לא נקראה כלל'})")
    else:
        try:
            req = urllib.request.Request(
                f"{BASE}/pool/list",
                data=json.dumps({"password": pw}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            print(f"  פעילים: {data.get('active')}  ·  "
                  f"תקינים: {data.get('healthy')}  ·  "
                  f"בקובץ: {data.get('in_file')}")
            for b in data.get("bots", []):
                if b.get("kind") == "user":
                    live_users.append(b)
                    # המזהה מודפס לצד השם: שם משתמש אפשר להחליף — וזה
                    # מה שניתק את ההעלאה פעם אחת — והמזהה לא משתנה.
                    print(f"  · {b['name']}  זהות: "
                          f"{b.get('who') or '(ריקה — get_me לא הצליח)'}"
                          f"  מזהה: {b.get('uid') or '(לא נשמר)'}  "
                          f"· {b.get('status')} · ערוץ: "
                          f"{'כן' if b.get('peer_ok') else 'לא'}")
            if not live_users:
                print("  ✗ אף חבר pool מסוג user לא עלה.")
        except Exception as e:                             # noqa: BLE001
            print(f"  ⚠️ השאילתה נכשלה: {type(e).__name__}: {e}")

    # ── 3. ההגדרה שמצמצמת לחשבון מסוים ──────────────────────────────────
    head("3. SAVED_UPLOAD_USER")
    if ENV_SOURCE:
        print(f"  (נקרא מ: {ENV_SOURCE})")
    want = (env.get("SAVED_UPLOAD_USER") or "").strip().lstrip("@").lower()
    if not ENV_SOURCE:
        # "לא הצלחתי לקרוא" אינו "לא מוגדר". הגרסה הראשונה בלבלה בין
        # השניים ודיווחה "חסר" על שרת שבו הכל מוגדר — תשובה שנשמעת
        # כמו עובדה ואינה.
        print("  ⚠️ לא הצלחתי לקרוא את סביבת השירות בכלל, ולכן אינני")
        print("     יודע מה מוגדר. זה **אינו** 'לא מוגדר'. לבדוק ידנית:")
        print(f"     tr '\\0' '\\n' < /proc/$(systemctl show {SERVICE}"
              " -p MainPID --value)/environ | grep '^SAVED_UPLOAD_USER='")
        want = None
    elif not want:
        print("  לא מוגדר — נבחר החשבון הראשון שעלה. זה המצב הסלחני.")
        if len(live_users) > 1:
            first = live_users[0]
            print(f"     כלומר הקבצים ילכו ל{first.get('who') or first['name']}"
                  f" — החשבון הראשון ברשימה, ולא בהכרח שלך.")
            print(f"     כדי לקבוע: SAVED_UPLOAD_USER=<מזהה מסעיף 2>")
    elif want and want.isdigit():
        print(f"  מוגדר לפי מזהה: {want}  ← זו הדרך היציבה")
        if live_users:
            ids = [str(b.get("uid") or "") for b in live_users]
            if want in ids:
                print("  ✓ תואם לחשבון שעלה.")
            elif any(not i for i in ids):
                print("  ✗ יש חשבון שעלה אבל מזההו לא נשמר — הרץ")
                print("    fix_userbot_by_id.py והפעל מחדש.")
            else:
                print(f"  ✗ לא תואם. ב-pool יש: {', '.join(i or '?' for i in ids)}")
    elif want:
        print(f"  מוגדר לפי שם: @{want}")
        # שם משתמש הוא תווית שאפשר להחליף, וזה בדיוק מה שניתק את
        # ההעלאה פעם אחת בלי שאיש נגע בקוד. המספר אינו משתנה לעולם.
        print("     שם משתמש אפשר להחליף בטלגרם בשתי לחיצות, ואז זה נשבר")
        print("     בלי שנגעת בכלום. עדיף לשים כאן את המזהה מסעיף 2.")
        if live_users:
            got = [(b.get("who") or "").lstrip("@").lower() for b in live_users]
            if want in got:
                print("  ✓ תואם לחשבון שעלה.")
            elif any(g == "" for g in got):
                print("  ✗ יש חשבון שעלה אבל זהותו ריקה, ולכן ההתאמה")
                print("    לעולם לא תצליח — וזו התקלה השקטה מסעיף 3 בראש")
                print("    הקובץ. לא חשבון חסר: חשבון שלא שאלנו מי הוא.")
            else:
                print(f"  ✗ לא תואם. ב-pool יש: {', '.join(g or '?' for g in got)}")
                for b in live_users:
                    if b.get("uid"):
                        print(f"     {b.get('who') or '?'} → "
                              f"SAVED_UPLOAD_USER={b['uid']}")
    if not ENV_SOURCE:
        print("  UPLOAD_PANEL_CODE: לא ידוע (הסביבה לא נקראה)")
    elif (env.get("UPLOAD_PANEL_CODE") or "").strip():
        print("  UPLOAD_PANEL_CODE: מוגדר")
    else:
        print("  UPLOAD_PANEL_CODE: ✗ חסר — הפאנל יחזיר 503 לכל קוד")

    # ── 4. מה היומן אומר על העלייה ───────────────────────────────────────
    head("4. מה היומן אומר")
    try:
        out = subprocess.run(
            ["journalctl", "-u", SERVICE, "-n", "4000", "--no-pager"],
            capture_output=True, text=True, timeout=60).stdout
        rows = [ln for ln in out.splitlines()
                if "pool member" in ln or "pool user" in ln
                or "pool bot" in ln]
        if not rows:
            print("  אין שורות pool ביומן האחרון.")
        for ln in rows[-25:]:
            print("  " + ln.split("]: ")[-1][:150])
    except Exception as e:                                 # noqa: BLE001
        print(f"  ⚠️ {type(e).__name__}: {e}")

    head("שורה תחתונה")
    # "לא ידוע" קודם לכל מסקנה. הגרסה הראשונה הכריזה "החשבון עלה ותואם
    # — התקלה אינה כאן" על שרת שבו היא פשוט לא הצליחה לקרוא את
    # ההגדרה, והמשפט הזה שולח לחפש במקום הלא נכון.
    if not ENV_SOURCE:
        print("  לא הצלחתי לקרוא את סביבת השירות, ולכן אין לי מסקנה.")
        print("  סעיף 3 אומר איך לבדוק ידנית.")
        return 2
    if not users:
        print("  אין חשבון מוגדר. צריך להוסיף אחד — זו אינה תקלה שנשברה.")
    elif not live_users:
        print("  יש חשבון מוגדר שלא עלה. הסיבה בסעיף 4.")
    elif want and not any(
            (str(b.get("uid") or "") == want) if want.isdigit()
            else ((b.get("who") or "").lstrip("@").lower() == want)
            for b in live_users):
        print("  החשבון עלה, אבל SAVED_UPLOAD_USER אינו מתאים לו.")
        print("  fix_saved_userbot.py מתקן את המקרה שבו הסיבה היא זהות ריקה.")
    else:
        print("  ההעלאה תעבוד.", end=" ")
        if want:
            print("החשבון עלה ותואם.")
        else:
            print("אין הגבלה, ולכן נבחר הראשון שעלה.")
    # חשבון שמוגדר בקובץ ולא עלה הוא ממצא בפני עצמו, גם כשההעלאה
    # עובדת דרך חשבון אחר: זה בדיוק מה שקרה כאן — session שנשלל.
    if users and len(live_users) < len(users):
        print(f"  ⚠️ בקובץ {len(users)} חשבונות ורק {len(live_users)} עלו.")
        print("     חפש SESSION_REVOKED בסעיף 4: session שנשלל אינו חוזר")
        print("     מעצמו וצריך ליצור חדש —")
        print("     /opt/zovex-bot/venv/bin/python gen_session.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
