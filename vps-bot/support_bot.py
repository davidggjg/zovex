#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · בוט תמיכה — גשר בין משתמשים לקבוצת המנהלים.
#
# ## למה שירות נפרד ולא טלאי ל-main.py
#
# main.py הוא ~13,200 שורות שמזרימות וידאו מ-31 בוטים, והוא כבר קרס
# בלופ פעם אחת בשבוע הזה. בוט תמיכה אינו קשור להזרמה: אם הוא ייפול,
# אסור שההזרמה תיפול איתו, ואם ההזרמה תיפול אסור שהתמיכה תישתק. לכן
# תהליך משלו, יחידת systemd משלה, וקובץ מצב משלו.
#
# אין תלויות חדשות: urllib בלבד. ה-venv לא נוגעים בו.
#
# ## איך זה עובד
#
#   משתמש → DM לבוט → הודעה בקבוצת המנהלים עם כותרת וכפתורים
#   מנהל → לוחץ "אני מטפל" → הכפתורים מתחלפים ושמו מופיע
#   מנהל → **מגיב** (swipe-to-reply) להודעה בקבוצה → הטקסט נשלח למשתמש
#   מנהל → עורך הודעה שכבר נשלחה → העריכה מתעדכנת גם אצל המשתמש
#
# המנהל אינו צריך לדעת מי מטפל במה ואינו מקליד פקודות: תגובה להודעה
# היא כל הממשק.
#
# ## החלטות שנדרשו ולא נשאלו
#
# • **כרטיס שנתפס ולא נענה** — תזכורת בקבוצה אחרי 15 דקות, ואחרי 30
#   דקות התפיסה משתחררת והכפתור חוזר להיות פנוי. אחרת מנהל שלחץ
#   ושכח חוסם את הכרטיס לנצח, וזה גרוע יותר מכרטיס שאף אחד לא תפס.
#
# • **המשתמש אינו רואה את שם המנהל** — התשובות מגיעות בשם "צוות ZOVEX".
#   מנהלים הם אנשים פרטיים, ושם פרטי שנחשף למשתמש אקראי הוא דלת
#   לפנייה ישירה מחוץ למערכת. בקבוצה כן רואים מי טיפל.
#
# ## אתר ואפליקציה
#
# לאתר ולאפליקציה **כבר יש** צ'אט תמיכה: SupportModal.jsx כותב
# ל-/feedback/send, המשתמש קורא ב-/feedback/mine, והמנהל עונה בפאנל.
# לכן לא נבנה כאן ממשק שני — זה היה מפצל את התמיכה לשני מקומות שאינם
# רואים אחד את השני, וזה גרוע מלא לעשות כלום.
#
# מה שנבנה הוא גשר:
#
#   משתמש באתר/באפליקציה כותב → feedback.json → כרטיס באותה קבוצה
#   מנהל מגיב להודעה בקבוצה → POST /feedback/reply → ההודעה מופיעה
#   בצ'אט שלו באתר ובאפליקציה, ובטלפון מגיעה התראה
#
# התשובה נכתבת דרך ה-API של main.py ולא ישירות ל-feedback.json: הנתיב
# הזה הוא שמסמן unread, ושולח את ה-push דרך FCM. כתיבה ישירה לקובץ
# הייתה גם מתחרה על אותו קובץ עם main.py וגם משתיקה את ההתראה.
#
# התוצאה: המנהלים עונים לאתר, לאפליקציה ולטלגרם מאותה קבוצה אחת,
# והמשתמש מקבל את התשובה במקום שבו הוא שאל.
#
#   SUPPORT_BOT_TOKEN  — טוקן הבוט (ב-/opt/zovex-bot/.env)
#   SUPPORT_GROUP_ID   — מזהה קבוצת המנהלים
# ─────────────────────────────────────────────────────────────────────────────
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("SUPPORT_BOT_TOKEN", "").strip()
GROUP = os.environ.get("SUPPORT_GROUP_ID", "").strip()
STATE = os.environ.get("SUPPORT_STATE", "/opt/zovex-bot/support_state.json")
HTTP_PORT = int(os.environ.get("SUPPORT_HTTP_PORT", "8107"))
FEEDBACK_FILE = os.environ.get(
    "FEEDBACK_FILE",
    os.path.join(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"), "feedback.json"))
MAIN_API = "http://127.0.0.1:%s" % os.environ.get("PORT", "8000")
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "").strip()
FEEDBACK_POLL = int(os.environ.get("SUPPORT_FEEDBACK_POLL", "10"))
CLAIM_REMIND = int(os.environ.get("SUPPORT_CLAIM_REMIND", "900"))   # 15 דקות
CLAIM_RELEASE = int(os.environ.get("SUPPORT_CLAIM_RELEASE", "1800"))  # 30 דקות
API = "https://api.telegram.org/bot%s/" % TOKEN
START = time.time()
ME = {}
# מספר גרסה שמודפס בעלייה ומוחזר ב-/ping. בלעדיו "הבוט לא מגיב"
# ו"רץ בשרת קוד שאינו מכיר את הפקודה" נראים אותו דבר מבחוץ, וזה בדיוק
# מה שבלבל אותנו: raw.githubusercontent מגיש מהמטמון עד חמש דקות.
VERSION = "4"

# --selftest מריץ את צד ה-HTTP בלי טלגרם: פותח כרטיס, עונה לו, קורא
# את השיחה ובודק שה-token נדרש. זה מה שמוודא שהאתר והאפליקציה יעבדו
# בלי לחכות למשתמש אמיתי.
SELFTEST = "--selftest" in sys.argv
if SELFTEST:
    TOKEN = TOKEN or "selftest"
    GROUP = GROUP or "-1"
    STATE = os.environ.get("SUPPORT_STATE", "/tmp/zovex_support_selftest.json")

if not TOKEN or not GROUP:
    sys.stderr.write("SUPPORT_BOT_TOKEN / SUPPORT_GROUP_ID חסרים\n")
    sys.exit(2)


def log(msg):
    sys.stdout.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


# ── קריאות ל-API ────────────────────────────────────────────────────────────
#
# שגיאה מטלגרם אינה מפילה את התהליך: הבוט הזה אמור לשרוד רעש רשת,
# 429, ומשתמש שחסם את הבוט. כל קריאה מחזירה None בכשל והקורא מחליט.
#
# ## למה http.client ולא urllib
#
# urlopen פותח חיבור חדש לכל קריאה: TCP, ואחריו TLS handshake שלם.
# מהשרת הזה ל-api.telegram.org זה היה הרוב המוחלט של זמן התגובה —
# תשובה אחת למנהל היא שתיים-שלוש קריאות (שליחה, עריכת כרטיס, ריאקשן),
# כלומר שלושה handshakes. חיבור אחד שנשמר פתוח משלם את זה פעם אחת.
#
# הנעילה נחוצה כי התגובות מטופלות בשרשורים: שתי קריאות במקביל על אותו
# socket מערבבות תשובות. ה-polling מחזיק חיבור נפרד משלו כדי שלא יחסום
# שליחות בזמן שהוא תלוי 60 שניות על getUpdates.
import http.client

_HOST = "api.telegram.org"
_PATH = "/bot%s/" % TOKEN
_conn = {}
_conn_lock = {"send": threading.Lock(), "poll": threading.Lock()}
SLOW_MS = int(os.environ.get("SUPPORT_SLOW_MS", "2500"))


def _request(lane, method, http_timeout, body):
    with _conn_lock[lane]:
        for attempt in (1, 2):
            c = _conn.get(lane)
            if c is None or getattr(c, "_zovex_timeout", None) != http_timeout:
                if c is not None:
                    try:
                        c.close()
                    except Exception:
                        pass
                c = http.client.HTTPSConnection(_HOST, timeout=http_timeout)
                c._zovex_timeout = http_timeout
                _conn[lane] = c
            try:
                c.request("POST", _PATH + method, body,
                          {"Content-Type": "application/x-www-form-urlencoded",
                           "Connection": "keep-alive"})
                r = c.getresponse()
                return r.status, r.read()
            except Exception as e:
                # חיבור שנשמר פתוח נסגר מהצד השני בשקט. ניסיון שני על
                # חיבור חדש אינו "ניסיון חוזר" אמיתי אלא אותה קריאה.
                try:
                    c.close()
                except Exception:
                    pass
                _conn[lane] = None
                if attempt == 2:
                    raise
    return None, None


def call(method, http_timeout=30, _lane="send", **params):
    body = urllib.parse.urlencode(
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    t0 = time.time()
    try:
        code, raw = _request(_lane, method, http_timeout, body)
        out = json.loads(raw.decode())
    except Exception as e:
        log("כשל %s: %s (%.0fms)" % (method, e, (time.time() - t0) * 1000))
        return None
    ms = (time.time() - t0) * 1000
    if method != "getUpdates" and ms > SLOW_MS:
        log("⏱ %s לקח %.0fms" % (method, ms))
    if out.get("ok"):
        return out.get("result")
    desc = out.get("description", "")
    if code == 429:
        wait = int(out.get("parameters", {}).get("retry_after", 3))
        log("429 על %s — ממתין %ds" % (method, wait))
        time.sleep(wait)
    elif "query is too old" in desc:
        # הלחיצה נענתה מאוחר מדי. הפעולה עצמה כן בוצעה; מה שאבד הוא רק
        # ההודעה הקופצת. נרשם כאזהרה עם הסבר, כדי שלא ייראה ככשל.
        log("⚠️ לחיצה נענתה באיחור — הפעולה בוצעה, החיווי למנהל לא הוצג")
    elif "message is not modified" not in desc:
        log("שגיאה %s: %s" % (method, desc))
    return None


def call_poll(secs):
    return call("getUpdates", http_timeout=secs + 15, _lane="poll", offset=S["offset"],
                allowed_updates=["message", "edited_message", "callback_query"],
                **{"timeout": secs})


# ── מצב ─────────────────────────────────────────────────────────────────────
#
# נכתב דרך קובץ זמני ו-os.replace: קריסה באמצע כתיבה לא משאירה JSON
# חתוך. זה בדיוק הכישלון שמחק 25,084 פריטים מהקטלוג בשבוע הזה.
_lock = threading.Lock()
S = {"offset": 0, "seq": 0, "tickets": {}, "by_group_msg": {}, "edit_map": {},
     "fb": {}, "secret": None}


def load():
    global S
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and "tickets" in d:
            S.update(d)
            log("מצב נטען: %d כרטיסים" % len(S["tickets"]))
    except FileNotFoundError:
        log("אין קובץ מצב — מתחיל נקי")
    except Exception as e:
        log("קובץ המצב פגום (%s) — מתחיל נקי, הקובץ נשמר בצד" % e)
        try:
            os.replace(STATE, STATE + ".corrupt")
        except Exception:
            pass


def save():
    tmp = STATE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(S, f, ensure_ascii=False)
        os.replace(tmp, STATE)
    except Exception as e:
        log("שמירת מצב נכשלה: %s" % e)


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def who(u):
    name = " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x) or "ללא שם"
    tag = ("@" + u["username"]) if u.get("username") else "אין שם משתמש"
    return name, tag


# ── כפתורים ─────────────────────────────────────────────────────────────────
#
# הכפתורים אינם פגים. מה שכן מתיישן הוא ה-callback: טלגרם מצפה
# ל-answerCallbackQuery בתוך כמה שניות, אחרת המנהל רואה שעון מסתובב.
# לכן answer נשלח ראשון, לפני כל עבודה אחרת.
def kb_open(tid):
    return {"inline_keyboard": [[
        {"text": "✋ אני מטפל", "callback_data": "take:%s" % tid},
        {"text": "✔️ סגור", "callback_data": "close:%s" % tid},
    ]]}


def kb_taken(tid):
    return {"inline_keyboard": [[
        {"text": "↩️ שחרר", "callback_data": "free:%s" % tid},
        {"text": "✔️ סגור", "callback_data": "close:%s" % tid},
    ]]}


def header(t):
    src = {"tg": "טלגרם", "web": "אתר", "app": "אפליקציה",
           "fb": "אתר/אפליקציה"}.get(t.get("src", "tg"), t.get("src"))
    lines = ["🎫 <b>כרטיס #%s</b> · %s" % (t["id"], src),
             "👤 %s · %s" % (esc(t.get("name")), esc(t.get("tag")))]
    if t.get("src") == "tg":
        lines.append("🆔 <code>%s</code>" % t["user_id"])
    # רק תשובה מסמנת. פתיחת שיחה בפאנל אינה אות לכלום — פותחים שיחות
    # ולא עונים כל הזמן, וסימון כזה היה גורם למנהל בקבוצה לחשוב שיש מי
    # שמטפל, והפנייה הייתה נופלת בין הכיסאות.
    if t.get("panel_answered"):
        lines.append("💼 <b>נענה מפאנל הניהול</b> — אין צורך לענות כאן")
    if t.get("taken_by"):
        lines.append("✋ מטפל: %s" % esc(t["taken_by"]))
    if t.get("closed"):
        lines.append("✔️ נסגר על ידי %s" % esc(t.get("closed_by") or "—"))
    lines.append("")
    lines.append("💬 <i>השב להודעה הזו כדי לענות למשתמש</i>" if not t.get("closed") else "")
    return "\n".join(x for x in lines if x is not None)


def refresh_card(t):
    """מצייר מחדש את הכרטיס, ורק אם באמת השתנה משהו.

    טלגרם מחזיר "message is not modified" על עריכה זהה, וזו הייתה
    שליחה מיותרת שגם רשמה שגיאה ביומן על כל לחיצה שלא שינתה כלום.
    """
    # כרטיס שנענה מהפאנל נשאר קריא אבל בלי כפתורים: אין מה "לתפוס"
    # בשיחה שכבר נענתה במקום אחר, וזה בדיוק מה שמונע שני מנהלים
    # שעונים לאותו אדם.
    kb = None if (t.get("closed") or t.get("panel_answered")) \
        else (kb_taken(t["id"]) if t.get("taken_by") else kb_open(t["id"]))
    body = header(t) + "\n\n" + t.get("body", "")
    fingerprint = body + "|" + json.dumps(kb, ensure_ascii=False, sort_keys=True)
    with _lock:
        if t.get("card_fp") == fingerprint:
            return
    r = call("editMessageText", chat_id=GROUP, message_id=t["card_msg"],
             text=body, parse_mode="HTML",
             reply_markup=kb, disable_web_page_preview=1)
    # נרשם רק אחרי הצלחה: אחרת עריכה שנכשלה ברשת לא הייתה מנוסה שוב
    # לעולם, והכרטיס היה נשאר מציג מצב ישן.
    if r is not None:
        with _lock:
            t["card_fp"] = fingerprint
            save()


# ── כרטיס חדש ───────────────────────────────────────────────────────────────
def open_ticket(src, user_id, name, tag, body, copy_from=None, copy_msg=None, raw=None):
    with _lock:
        S["seq"] += 1
        tid = str(S["seq"])
        t = {"id": tid, "src": src, "user_id": user_id, "name": name, "tag": tag,
             "body": body, "raw": raw, "opened": int(time.time()), "taken_by": None,
             "taken_at": 0, "closed": False, "reminded": False, "replies": []}
        S["tickets"][tid] = t
    m = call("sendMessage", chat_id=GROUP, text=header(t) + "\n\n" + body,
             parse_mode="HTML", reply_markup=kb_open(tid), disable_web_page_preview=1)
    if not m:
        log("פתיחת כרטיס %s נכשלה — אין קבוצה?" % tid)
        return None
    with _lock:
        t["card_msg"] = m["message_id"]
        S["by_group_msg"][str(m["message_id"])] = tid
        save()
    if copy_from and copy_msg:
        c = call("copyMessage", chat_id=GROUP, from_chat_id=copy_from,
                 message_id=copy_msg, reply_to_message_id=m["message_id"])
        if c:
            with _lock:
                S["by_group_msg"][str(c["message_id"])] = tid
                save()
    log("כרטיס #%s נפתח (%s)" % (tid, src))
    return t


def ticket_for_user(user_id):
    # פנייה נוספת מאותו משתמש נכנסת לכרטיס הפתוח שלו ולא פותחת חדש:
    # אחרת שלוש שורות רצופות נראות כשלושה כרטיסים ושלושה מנהלים.
    with _lock:
        for t in sorted(S["tickets"].values(), key=lambda x: -x["opened"]):
            if t.get("src") == "tg" and t.get("user_id") == user_id and not t.get("closed"):
                return t
    return None


# ── הודעה מהמשתמש ───────────────────────────────────────────────────────────
def on_user_message(msg):
    u = msg["from"]
    name, tag = who(u)
    text = msg.get("text") or msg.get("caption") or ""
    if text.strip() in ("/start", "/help"):
        call("sendMessage", chat_id=u["id"],
             text="שלום 👋\nזו התמיכה של <b>ZOVEX</b>.\nכתוב כאן מה הבעיה — תקלה, "
                  "בקשת תוכן או שאלה — ונחזור אליך.",
             parse_mode="HTML")
        return
    media = None
    for k in ("photo", "video", "document", "voice", "audio", "animation", "sticker"):
        if msg.get(k):
            media = k
            break
    body = esc(text) if text else ("📎 <i>%s</i>" % media if media else "<i>(הודעה ריקה)</i>")

    t = ticket_for_user(u["id"])
    if t:
        with _lock:
            t["name"], t["tag"] = name, tag
        m = call("sendMessage", chat_id=GROUP,
                 text="➕ <b>#%s</b> המשך מהמשתמש:\n\n%s" % (t["id"], body),
                 parse_mode="HTML", reply_to_message_id=t["card_msg"])
        if m:
            with _lock:
                S["by_group_msg"][str(m["message_id"])] = t["id"]
                save()
        if media:
            c = call("copyMessage", chat_id=GROUP, from_chat_id=u["id"],
                     message_id=msg["message_id"],
                     reply_to_message_id=(m or {}).get("message_id") or t["card_msg"])
            if c:
                with _lock:
                    S["by_group_msg"][str(c["message_id"])] = t["id"]
                    save()
    else:
        t = open_ticket("tg", u["id"], name, tag, body,
                        copy_from=u["id"] if media else None,
                        copy_msg=msg["message_id"] if media else None)
        if t:
            call("sendMessage", chat_id=u["id"],
                 text="התקבל ✅ נציג יחזור אליך בהקדם.")


# ── /ping בקבוצה ────────────────────────────────────────────────────────────
#
# הבוט מתעלם מכל הודעה בקבוצה שאינה תגובה לכרטיס, ולכן בלי זה אין שום
# דרך לראות שהוא בכלל שם ושיש לו ההרשאות שהוא צריך.
#
# התשובה אינה "אני חי" בלבד: היא אומרת גם מה מצבו בקבוצה. בוט שלא
# הוכנס לקבוצה בכלל עולה, מתחבר, ומחזיר getMe תקין — ורק אחרי שמשתמש
# ראשון יכתוב יתברר שאין לאן לשלוח.
#
# מנהל אינו נדרש לזרימה שלנו: בוט תמיד יכול לערוך את ההודעות של עצמו,
# ו-privacy mode מעביר אליו פקודות ותגובות להודעות שלו. מנהל כן עוזר
# אם נרצה בעתיד למחוק הודעות או להצמיד כרטיס.
def on_ping(msg):
    up = int(time.time() - START)
    with _lock:
        tot = len(S["tickets"])
        op = sum(1 for t in S["tickets"].values() if not t.get("closed"))
        taken = sum(1 for t in S["tickets"].values()
                    if not t.get("closed") and t.get("taken_by"))
    me = ME
    cm = call("getChatMember", chat_id=GROUP, user_id=me.get("id")) or {}
    status = cm.get("status", "?")
    can_edit = bool(cm.get("can_edit_messages")) or status == "creator"
    if status == "administrator":
        perms = "✅ מנהל בקבוצה"
    elif status == "member":
        perms = "✅ חבר בקבוצה (מנהל אינו נדרש)"
    else:
        perms = "⚠️ מצב בקבוצה: %s" % esc(status)
    with _lock:
        bridged = len(S["fb"])
    fb_ok = os.path.exists(FEEDBACK_FILE)
    call("sendMessage", chat_id=GROUP, parse_mode="HTML",
         reply_to_message_id=msg["message_id"],
         text="🟢 <b>בוט התמיכה פעיל</b>\n"
              "@%s · גרסה %s · למעלה %dh %dm\n"
              "%s\n"
              "גשר האתר/אפליקציה: %s · %d שיחות\n"
              "החזרת תשובות לאתר: %s\n"
              "כרטיסים: %d פתוחים מתוך %d · %d נתפסו"
              % (esc(me.get("username")), VERSION, up // 3600, (up % 3600) // 60,
                 perms, "✅" if fb_ok else "❌ feedback.json לא נמצא", bridged,
                 "✅" if PANEL_PASSWORD else "❌ PANEL_PASSWORD חסר",
                 op, tot, taken))


# ── תשובת מנהל: תגובה להודעה בקבוצה ─────────────────────────────────────────
def on_group_message(msg):
    text0 = (msg.get("text") or "").strip()
    if text0.split("@")[0].split()[0:1] and text0.split("@")[0].split()[0] in ("/ping", "/status"):
        return on_ping(msg)
    rep = msg.get("reply_to_message")
    if not rep:
        return
    with _lock:
        tid = S["by_group_msg"].get(str(rep["message_id"]))
        t = S["tickets"].get(tid) if tid else None
    if not t:
        return
    if t.get("src") != "tg":
        # אתר/אפליקציה: אין צ'אט טלגרם להחזיר אליו, התשובה נשמרת ל-API.
        # אתר/אפליקציה: התשובה חוזרת לצ'אט שבו המשתמש שאל, דרך
        # /feedback/reply — הנתיב שגם שולח לו את ההתראה לטלפון.
        admin = who(msg["from"])[0]
        body = msg.get("text") or msg.get("caption") or ""
        if not body:
            call("sendMessage", chat_id=GROUP, reply_to_message_id=msg["message_id"],
                 text="⚠️ לצ'אט האתר/האפליקציה אפשר לשלוח טקסט בלבד.")
            return
        uid = t.get("fb_uid")
        if not uid:
            return
        with _lock:
            # נרשם לפני השליחה: הגשר קורא את feedback.json כל כמה שניות,
            # ובלי זה הוא היה רואה את התשובה של עצמו וחושב שענו מהפאנל.
            S["fb"].setdefault(uid, {}).setdefault("pending", []).append(body)
            save()
        ok, why = fb_reply(uid, body)
        if not ok:
            with _lock:
                try:
                    S["fb"][uid]["pending"].remove(body)
                except Exception:
                    pass
                save()
            call("sendMessage", chat_id=GROUP, parse_mode="HTML",
                 reply_to_message_id=msg["message_id"],
                 text="⚠️ התשובה לא נשלחה: %s" % esc(why))
            return
        with _lock:
            t["replies"].append({"at": int(time.time()), "side": "team",
                                 "by": admin, "text": body})
            if not t.get("taken_by"):
                t["taken_by"], t["taken_at"] = admin, int(time.time())
            save()
        refresh_card(t)
        call("setMessageReaction", chat_id=GROUP, message_id=msg["message_id"],
             reaction=[{"type": "emoji", "emoji": "👍"}])
        return

    admin_name = who(msg["from"])[0]
    text = msg.get("text") or msg.get("caption") or ""
    sent = None
    if text:
        sent = call("sendMessage", chat_id=t["user_id"],
                    text="<b>צוות ZOVEX:</b>\n%s" % esc(text), parse_mode="HTML")
    for k in ("photo", "video", "document", "voice", "audio", "animation"):
        if msg.get(k):
            sent = call("copyMessage", chat_id=t["user_id"], from_chat_id=GROUP,
                        message_id=msg["message_id"]) or sent
            break
    if not sent:
        call("sendMessage", chat_id=GROUP,
             text="⚠️ <b>#%s</b> התשובה לא נשלחה — המשתמש כנראה חסם את הבוט." % t["id"],
             parse_mode="HTML", reply_to_message_id=msg["message_id"])
        return

    with _lock:
        # מפת עריכות: מנהל שעורך את ההודעה שלו בקבוצה מעדכן גם את
        # העותק אצל המשתמש. טלגרם מאפשר עריכה עד 48 שעות.
        S["edit_map"][str(msg["message_id"])] = {"chat": t["user_id"],
                                                 "msg": sent["message_id"]}
        if not t.get("taken_by"):
            t["taken_by"], t["taken_at"] = admin_name, int(time.time())
        t["replies"].append({"at": int(time.time()), "side": "team",
                             "by": admin_name, "text": text})
        save()
    refresh_card(t)
    call("setMessageReaction", chat_id=GROUP, message_id=msg["message_id"],
         reaction=[{"type": "emoji", "emoji": "👍"}])


def on_group_edit(msg):
    with _lock:
        tgt = S["edit_map"].get(str(msg["message_id"]))
    if not tgt:
        return
    text = msg.get("text") or msg.get("caption") or ""
    if not text:
        return
    ok = call("editMessageText", chat_id=tgt["chat"], message_id=tgt["msg"],
              text="<b>צוות ZOVEX:</b>\n%s" % esc(text), parse_mode="HTML")
    if ok is None:
        call("sendMessage", chat_id=GROUP,
             text="⚠️ העריכה לא עברה (עברו 48 שעות?) — שלח הודעה חדשה.",
             reply_to_message_id=msg["message_id"])


# ── כפתורים ─────────────────────────────────────────────────────────────────
def on_callback(cq):
    # answerCallbackQuery נשלח פעם אחת בלבד: הראשון הוא שמוריד את השעון
    # המסתובב, והשני מתעלמים ממנו — ולכן ההודעה "כבר מטפל בזה" צריכה
    # להיות בראשון. הפענוח שלפניו הוא מקומי ואינו לוקח זמן.
    data = cq.get("data") or ""
    act, tid = (data.split(":", 1) + [""])[:2] if ":" in data else ("", "")
    with _lock:
        t = S["tickets"].get(tid)
    name = who(cq["from"])[0]
    note = None
    if not t:
        note = "הכרטיס הזה לא קיים יותר"
    elif act == "take" and t.get("taken_by") and t["taken_by"] != name:
        note = "%s כבר מטפל בזה" % t["taken_by"]
    call("answerCallbackQuery", callback_query_id=cq["id"], text=note,
         show_alert=1 if note else None)
    if note or not t:
        return
    with _lock:
        if act == "take":
            t["taken_by"], t["taken_at"], t["reminded"] = name, int(time.time()), False
        elif act == "free":
            t["taken_by"], t["taken_at"], t["reminded"] = None, 0, False
        elif act == "close":
            t["closed"], t["closed_by"] = True, name
        save()
    refresh_card(t)
    if act == "close" and t.get("src") == "tg":
        call("sendMessage", chat_id=t["user_id"],
             text="הפנייה נסגרה ✔️ אם זה לא נפתר — כתוב שוב ונפתח כרטיס חדש.")


# ── גשר לצ'אט התמיכה של האתר והאפליקציה ─────────────────────────────────────
#
# לאתר ולאפליקציה כבר יש צ'אט תמיכה שעובד מול /feedback ב-main.py.
# הגשר מביא אותו לקבוצה, כדי שכל המנהלים יקבלו התראה ויוכלו לענות —
# ולא רק מי שיושב מול הפאנל.
#
# ## קוראים קובץ, כותבים דרך ה-API
#
# הקריאה היא מ-feedback.json ישירות: זה קובץ מקומי, וקריאה ממנו אינה
# מעמיסה את main.py שכבר מזרים וידאו מ-31 בוטים.
#
# הכתיבה, לעומת זה, **חייבת** לעבור ב-POST /feedback/reply: הנתיב הזה
# הוא שמסמן unread_user ושולח את ה-push ל-FCM. כתיבה ישירה לקובץ הייתה
# משתיקה את ההתראה בטלפון, וגם מתחרה על אותו קובץ עם main.py — שתי
# כתיבות במקביל, והשיחה נעלמת. ראינו בשבוע הזה מה זה עושה לקטלוג.
#
# ## "ענו מהפאנל"
#
# אם מנהל עונה מהפאנל, מופיעה בשיחה הודעת admin שהבוט לא שלח. הכרטיס
# בקבוצה מסומן "נענה מפאנל הניהול" והכפתורים מוסרים — אחרת שני מנהלים
# עונים לאותו אדם, אחד בפאנל ואחד בטלגרם.
#
# הזיהוי הוא לפי מה שהבוט עצמו שלח: כל תשובה שהוא כותב נרשמת, וכשהיא
# חוזרת מהקובץ היא מזוהה ולא נחשבת לתשובה מהפאנל.
def fb_read():
    try:
        with open(FEEDBACK_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        # main.py כותב את הקובץ בלי קובץ זמני, ולכן קריאה בדיוק באמצע
        # כתיבה מחזירה JSON חתוך. הסבב הבא יקרא אותו שלם; אין מה להתריע.
        log("feedback.json לא נקרא (%s)" % e)
        return None


def fb_reply(user_id, text):
    """תשובה לצ'אט של האתר/האפליקציה דרך ה-API של main.py."""
    if not PANEL_PASSWORD:
        return False, "PANEL_PASSWORD חסר ב-.env"
    body = json.dumps({"password": PANEL_PASSWORD, "user_id": user_id,
                       "text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(MAIN_API + "/feedback/reply", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            json.loads(r.read().decode())
        return True, ""
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read().decode()).get("detail", str(e))
        except Exception:
            why = str(e)
        return False, "%s: %s" % (e.code, why)
    except Exception as e:
        return False, str(e)


def fb_src(th):
    # ‎g:<email>‎ הוא הפורמט שהאתר שולח; האפליקציה שולחת את אותו מזהה,
    # ולכן אין כאן הפרדה אמיתית בין השניים ואין טעם להמציא אחת.
    return "fb"


def fb_ticket(uid, th):
    with _lock:
        rec = S["fb"].get(uid)
        t = S["tickets"].get(rec["tid"]) if rec else None
    if t and not t.get("closed"):
        return t
    name = th.get("name") or th.get("email") or uid
    tag = th.get("email") or uid
    t = open_ticket(fb_src(th), None, name, tag, "<i>(ממתין להודעה)</i>", raw="")
    if t:
        with _lock:
            t["fb_uid"] = uid
            S["fb"].setdefault(uid, {})["tid"] = t["id"]
            save()
    return t


KINDS = {"support": "💬 תמיכה", "review": "⭐ חוות דעת", "tip": "💡 טיפ"}


def fb_watch():
    first = True
    while True:
        try:
            d = fb_read()
            if d is None:
                time.sleep(FEEDBACK_POLL)
                continue
            for uid, th in d.items():
                if not isinstance(th, dict):
                    continue
                msgs = th.get("messages") or []
                with _lock:
                    rec = S["fb"].setdefault(uid, {})
                    seen = rec.get("seen")
                    if seen is None:
                        # בעלייה ראשונה לא מציפים את הקבוצה בכל ההיסטוריה:
                        # מסמנים את מה שקיים כנראה וממשיכים מכאן.
                        rec["seen"] = len(msgs)
                        save()
                        seen = len(msgs)
                fresh = msgs[seen:]
                if not fresh:
                    continue
                for m in fresh:
                    if m.get("from") == "user":
                        fb_user_msg(uid, th, m)
                    elif m.get("from") == "admin":
                        fb_admin_msg(uid, m)
                with _lock:
                    S["fb"][uid]["seen"] = len(msgs)
                    save()
        except Exception as e:
            log("גשר התמיכה נפל: %s" % e)
        first = False
        time.sleep(FEEDBACK_POLL)


def fb_user_msg(uid, th, m):
    t = fb_ticket(uid, th)
    if not t:
        return
    kind = KINDS.get(m.get("kind") or "support", "")
    text = esc(m.get("text") or "")
    with _lock:
        t["replies"].append({"at": int(time.time()), "side": "user",
                             "text": m.get("text") or ""})
        if not t.get("raw"):
            t["raw"] = m.get("text") or ""
            t["body"] = "%s\n%s" % (kind, text) if kind else text
            new_card = True
        else:
            new_card = False
        # תשובה מהפאנל אינה נועלת את השיחה לנצח: הודעה חדשה מהמשתמש
        # מחזירה את הכרטיס למשחק, אחרת פנייה שנייה שלו לא תגיע לאף אחד.
        t["panel_answered"] = False
        save()
    if new_card:
        refresh_card(t)
    else:
        mm = call("sendMessage", chat_id=GROUP, parse_mode="HTML",
                  reply_to_message_id=t["card_msg"],
                  text="➕ <b>#%s</b> המשך מהמשתמש:\n\n%s%s"
                       % (t["id"], (kind + "\n") if kind else "", text))
        if mm:
            with _lock:
                S["by_group_msg"][str(mm["message_id"])] = t["id"]
                save()
        refresh_card(t)


def fb_admin_msg(uid, m):
    """הודעת admin שהופיעה בשיחה. אם לא הבוט שלח אותה — ענו מהפאנל."""
    text = (m.get("text") or "").strip()
    with _lock:
        rec = S["fb"].get(uid) or {}
        t = S["tickets"].get(rec.get("tid") or "")
        mine = rec.get("pending") or []
        if text in mine:
            mine.remove(text)
            rec["pending"] = mine
            save()
            return
    if not t or t.get("closed"):
        return
    with _lock:
        t["panel_answered"] = True
        t["taken_by"] = None
        t["taken_at"] = 0
        t["replies"].append({"at": int(time.time()), "side": "team",
                             "by": "פאנל הניהול", "text": text})
        save()
    refresh_card(t)
    call("sendMessage", chat_id=GROUP, parse_mode="HTML",
         reply_to_message_id=t["card_msg"],
         text="💼 <b>#%s</b> נענה מפאנל הניהול:\n\n%s" % (t["id"], esc(text[:600])))


# ── תפיסה שנשכחה ────────────────────────────────────────────────────────────
#
# מנהל שלוחץ "אני מטפל" ונעלם חוסם את הכרטיס: שאר המנהלים רואים
# שמטופל ולא נוגעים. תזכורת אחרי 15 דקות, שחרור אחרי 30.
def janitor():
    while True:
        time.sleep(60)
        now = int(time.time())
        for t in list(S["tickets"].values()):
            if t.get("closed") or not t.get("taken_by"):
                continue
            answered = any(r.get("side") == "team" for r in t.get("replies", [])
                           if r["at"] >= t["taken_at"])
            if answered:
                continue
            age = now - t["taken_at"]
            if age >= CLAIM_RELEASE:
                with _lock:
                    t["taken_by"], t["taken_at"], t["reminded"] = None, 0, False
                    save()
                refresh_card(t)
                call("sendMessage", chat_id=GROUP,
                     text="↩️ <b>#%s</b> שוחרר — חצי שעה ללא תשובה." % t["id"],
                     parse_mode="HTML", reply_to_message_id=t["card_msg"])
            elif age >= CLAIM_REMIND and not t.get("reminded"):
                with _lock:
                    t["reminded"] = True
                    save()
                call("sendMessage", chat_id=GROUP,
                     text="⏰ <b>#%s</b> נתפס על ידי %s לפני %d דקות וטרם נענה."
                          % (t["id"], esc(t["taken_by"]), age // 60),
                     parse_mode="HTML", reply_to_message_id=t["card_msg"])


# ── בדיקת מצב מקומית ────────────────────────────────────────────────────────
#
# אין כאן API לאתר. האתר והאפליקציה מדברים עם /feedback ב-main.py כמו
# קודם, והגשר למעלה הוא שמחבר אותם לקבוצה — ולכן אין מה לחשוף לדפדפן,
# ו-nginx לא נוגעים בו בכלל. נקודה אחת, ל-localhost, כדי שסקריפט
# ההתקנה יוכל לוודא שהשירות עלה.
class Handler(BaseHTTPRequestHandler):
    server_version = "zovex-support"

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if (urllib.parse.urlparse(self.path).path.rstrip("/") or "/") != "/health":
            return self._json(404, {"error": "not found"})
        with _lock:
            op = sum(1 for t in S["tickets"].values() if not t.get("closed"))
            br = len(S["fb"])
        return self._json(200, {"ok": True, "version": VERSION,
                                "bot": ME.get("username"),
                                "up": int(time.time() - START),
                                "tickets": len(S["tickets"]), "open": op,
                                "bridged_chats": br})


def http_server():
    # 127.0.0.1 בלבד: הפתיחה הזו אינה מאומתת, ואין לה מה לעשות באינטרנט.
    #
    # פורט תפוס אינו תקלה קטנה: הוא אומר שתהליך קודם עדיין רץ, ושני
    # בוטים על אותו טוקן גונבים זה מזה עדכונים ב-getUpdates. עד עכשיו
    # זה היה שורה ביומן בזמן שהשירות נראה תקין לגמרי. מעכשיו הוא נופל,
    # systemd מנסה שוב, והיומן אומר מה לעשות.
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    except OSError as e:
        log("❌ הפורט %d תפוס (%s) — כנראה רץ עוד עותק של הבוט." % (HTTP_PORT, e))
        log("   בדוק:  pgrep -af support_bot.py   ואז:  systemctl restart zovex-support")
        os._exit(3)
    log("מאזין ב-127.0.0.1:%d" % HTTP_PORT)
    srv.serve_forever()


def handle(up):
    try:
        if "callback_query" in up:
            on_callback(up["callback_query"])
        elif "message" in up:
            m = up["message"]
            if str(m["chat"]["id"]) == str(GROUP):
                on_group_message(m)
            elif m["chat"]["type"] == "private":
                on_user_message(m)
        elif "edited_message" in up:
            m = up["edited_message"]
            if str(m["chat"]["id"]) == str(GROUP):
                on_group_edit(m)
    except Exception as e:
        log("עדכון %s נפל: %s" % (up.get("update_id"), e))


# ── לופ ─────────────────────────────────────────────────────────────────────
def selftest():
    """מריץ את הגשר מול feedback.json מדומה, בלי טלגרם ובלי main.py.

    זה המסלול שהמשתמש באמת הולך בו: הוא כותב באתר, מנהל עונה בקבוצה,
    ואחר כך מנהל אחר עונה מהפאנל. בלי בדיקה כזו הייתי מגלה את זה רק
    כשמשתמש אמיתי כותב.
    """
    global call, fb_reply
    sent = []
    seq = {"n": 1000}
    FB = "/tmp/zovex_fb_selftest.json"
    globals()["FEEDBACK_FILE"] = FB
    globals()["ME"] = {"username": "selftest_bot"}

    def fake(method, http_timeout=30, _lane="send", **kw):
        sent.append((method, kw))
        if method == "getMe":
            return {"id": 1, "username": "selftest_bot"}
        if method in ("sendMessage", "copyMessage"):
            seq["n"] += 1
            return {"message_id": seq["n"]}
        return True

    pushed = []

    def fake_reply(uid, text):
        pushed.append((uid, text))
        fb = json.load(open(FB, encoding="utf-8"))
        fb[uid]["messages"].append({"from": "admin", "text": text, "ts": "now"})
        json.dump(fb, open(FB, "w", encoding="utf-8"), ensure_ascii=False)
        return True, ""

    call = fake
    fb_reply = fake_reply
    load()

    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print("  %s %s %s" % ("✅" if cond else "❌", name, extra))
        ok = ok and cond

    def write_fb(msgs, name="דוד", email="d@x.com"):
        json.dump({"g:d@x.com": {"user_id": "g:d@x.com", "name": name,
                                 "email": email, "messages": msgs}},
                  open(FB, "w", encoding="utf-8"), ensure_ascii=False)

    def pump():
        d = fb_read()
        for uid, th in d.items():
            msgs = th.get("messages") or []
            rec = S["fb"].setdefault(uid, {})
            seen = rec.get("seen") or 0
            for m in msgs[seen:]:
                if m.get("from") == "user":
                    fb_user_msg(uid, th, m)
                else:
                    fb_admin_msg(uid, m)
            S["fb"][uid]["seen"] = len(msgs)

    def last_text():
        return [kw for m, kw in sent if m in ("sendMessage", "editMessageText")][-1]["text"]

    # ① פנייה חדשה מהאתר נכנסת לקבוצה
    write_fb([{"from": "user", "text": "הסרט נתקע <b>בדקה 3</b>", "ts": "t1",
               "kind": "support"}])
    pump()
    tid = S["fb"]["g:d@x.com"]["tid"]
    t = S["tickets"][tid]
    card = [kw for m, kw in sent if m == "editMessageText"][-1]["text"]
    check("פנייה מהאתר נפתחה ככרטיס", "🎫" in card and "אתר/אפליקציה" in card)
    check("השם והאימייל מוצגים למנהלים", "דוד" in card and "d@x.com" in card)
    check("HTML מהמשתמש מנוטרל", "&lt;b&gt;" in card and "<b>בדקה" not in card)
    check("סוג הפנייה מסומן", "💬 תמיכה" in card)

    # ② מנהל עונה בקבוצה → ההודעה חוזרת לצ'אט של המשתמש
    on_group_message({"message_id": 5001, "chat": {"id": GROUP, "type": "supergroup"},
                      "from": {"id": 9, "first_name": "אבי"},
                      "reply_to_message": {"message_id": t["card_msg"]},
                      "text": "בודקים, תודה"})
    check("התשובה נשלחה לצ'אט של המשתמש", pushed == [("g:d@x.com", "בודקים, תודה")], pushed)
    check("הכרטיס מסומן כמטופל", t.get("taken_by") == "אבי")

    # ③ אותה תשובה חוזרת מהקובץ — אסור שתיחשב "ענו מהפאנל"
    pump()
    check("תשובה של הבוט אינה מזוהה כפאנל", not t.get("panel_answered"))

    # ④ מנהל אחר עונה מהפאנל
    fb = json.load(open(FB, encoding="utf-8"))
    fb["g:d@x.com"]["messages"].append({"from": "admin", "text": "טופל, תודה", "ts": "t3"})
    json.dump(fb, open(FB, "w", encoding="utf-8"), ensure_ascii=False)
    pump()
    check("תשובה מהפאנל מסומנת בכרטיס", t.get("panel_answered") is True)
    check("התפיסה שוחררה", t.get("taken_by") is None)
    check("הודעה בקבוצה אומרת שענו מהפאנל", "נענה מפאנל הניהול" in last_text())
    check("הכפתורים הוסרו", [kw for m, kw in sent if m == "editMessageText"][-1]
          .get("reply_markup") is None)

    # ⑤ הודעה חדשה מהמשתמש מחזירה את הכרטיס למשחק
    fb = json.load(open(FB, encoding="utf-8"))
    fb["g:d@x.com"]["messages"].append({"from": "user", "text": "עדיין נתקע", "ts": "t4"})
    json.dump(fb, open(FB, "w", encoding="utf-8"), ensure_ascii=False)
    pump()
    check("פנייה חוזרת פותחת את הכרטיס מחדש", not t.get("panel_answered"))
    check("ההמשך הגיע לקבוצה", "עדיין נתקע" in "".join(
        kw.get("text", "") for m, kw in sent[-4:]))

    # ⑥ ציור חוזר של אותו כרטיס אינו שולח עריכה זהה
    n0 = len([1 for m, _ in sent if m == "editMessageText"])
    refresh_card(t)
    refresh_card(t)
    check("עריכה זהה אינה נשלחת שוב",
          len([1 for m, _ in sent if m == "editMessageText"]) == n0)

    # ⑦ היסטוריה קיימת בעלייה ראשונה אינה מוצפת לקבוצה
    S["fb"].clear()
    S["tickets"].clear()
    before = len(sent)
    write_fb([{"from": "user", "text": "הודעה %d" % i, "ts": "t"} for i in range(40)])
    d = fb_read()
    for uid, th in d.items():
        S["fb"].setdefault(uid, {})["seen"] = len(th["messages"])
    pump()
    check("40 הודעות היסטוריה לא הוצפו", len(sent) == before, len(sent) - before)

    # ⑧ קובץ חתוך באמצע כתיבה אינו מפיל כלום
    open(FB, "w", encoding="utf-8").write('{"g:d@x.com": {"mes')
    check("JSON חתוך מוחזר כ-None ולא קורס", fb_read() is None)

    os.remove(FB)
    print("\n%s" % ("✅ הכל עבר" if ok else "❌ נכשל"))
    return 0 if ok else 1


def main():
    load()
    global ME
    ME = call("getMe")
    me = ME
    if not me:
        log("getMe נכשל — טוקן שגוי או אין רשת")
        sys.exit(1)
    log("עלה כ-@%s · גרסה %s" % (me.get("username"), VERSION))
    # privacy mode הוא ההסבר הנפוץ ל"בקבוצה הוא לא מגיב": בוט שהוא
    # דלוק אינו מקבל הודעות רגילות בקבוצה, אלא רק פקודות ותגובות
    # להודעות שלו עצמו. זה מודפס כדי שלא נחפש את זה בקוד.
    if not me.get("can_read_all_group_messages"):
        log("privacy mode דלוק — הבוט מקבל בקבוצה רק פקודות ותגובות "
            "להודעות שלו. לכיבוי: BotFather → Bot Settings → Group Privacy → Turn off")
    log("גשר התמיכה: %s" % FEEDBACK_FILE)
    if not os.path.exists(FEEDBACK_FILE):
        log("⚠️ הקובץ אינו קיים — הגשר לא יראה פניות מהאתר. בדוק DATA_DIR ב-.env")
    if not PANEL_PASSWORD:
        log("⚠️ PANEL_PASSWORD חסר — אי אפשר להחזיר תשובה לצ'אט של האתר")
    threading.Thread(target=janitor, daemon=True).start()
    threading.Thread(target=http_server, daemon=True).start()
    threading.Thread(target=fb_watch, daemon=True).start()
    fails = 0
    while True:
        # long polling: טלגרם מחזיק את החיבור 60 שניות, ולכן ה-timeout של
        # ה-HTTP חייב להיות גדול ממנו — אחרת כל סבב נראה כשל רשת.
        ups = call_poll(60)
        if ups is None:
            fails += 1
            time.sleep(min(30, 2 ** min(fails, 4)))
            continue
        fails = 0
        for up in ups:
            with _lock:
                S["offset"] = up["update_id"] + 1
            # כל עדכון בשרשור משלו: תשובה למשתמש היא שתיים-שלוש קריאות
            # ל-API, וכל עוד הן רצו בלופ הראשי, העדכון הבא חיכה להן.
            # זה מה שנראה כמו "לוקח לו מלא זמן להגיב".
            threading.Thread(target=handle, args=(up,), daemon=True).start()
        with _lock:
            save()


if __name__ == "__main__":
    sys.exit(selftest() if SELFTEST else main())
