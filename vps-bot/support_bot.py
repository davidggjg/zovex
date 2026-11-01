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
# השירות מאזין גם ב-127.0.0.1:8099 על /ticket, כדי שהאתר והאפליקציה
# יוכלו לפתוח כרטיס דרך main.py בלי שהתמיכה תהיה תלויה בו. פנייה כזו
# נכנסת לאותה קבוצה ומסומנת כ"אתר" או "אפליקציה"; אין למי להחזיר
# תשובה בטלגרם, ולכן התשובה נשמרת בקובץ המצב וה-API של האתר יקרא
# אותה. חלק זה פתוח לשימוש רק מהמכונה עצמה.
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
HTTP_PORT = int(os.environ.get("SUPPORT_HTTP_PORT", "8099"))
CLAIM_REMIND = int(os.environ.get("SUPPORT_CLAIM_REMIND", "900"))   # 15 דקות
CLAIM_RELEASE = int(os.environ.get("SUPPORT_CLAIM_RELEASE", "1800"))  # 30 דקות
API = "https://api.telegram.org/bot%s/" % TOKEN

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
def call(method, http_timeout=30, **params):
    data = urllib.parse.urlencode(
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    req = urllib.request.Request(API + method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as r:
            out = json.loads(r.read().decode())
        return out.get("result") if out.get("ok") else None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        desc = body.get("description", str(e))
        if e.code == 429:
            wait = int(body.get("parameters", {}).get("retry_after", 3))
            log("429 על %s — ממתין %ds" % (method, wait))
            time.sleep(wait)
        else:
            log("שגיאה %s: %s" % (method, desc))
        return None
    except Exception as e:
        log("כשל %s: %s" % (method, e))
        return None


def call_poll(secs):
    return call("getUpdates", http_timeout=secs + 15, offset=S["offset"],
                allowed_updates=["message", "edited_message", "callback_query"],
                **{"timeout": secs})


# ── מצב ─────────────────────────────────────────────────────────────────────
#
# נכתב דרך קובץ זמני ו-os.replace: קריסה באמצע כתיבה לא משאירה JSON
# חתוך. זה בדיוק הכישלון שמחק 25,084 פריטים מהקטלוג בשבוע הזה.
_lock = threading.Lock()
S = {"offset": 0, "seq": 0, "tickets": {}, "by_group_msg": {}, "edit_map": {}, "web": {}}


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
    src = {"tg": "טלגרם", "web": "אתר", "app": "אפליקציה"}.get(t.get("src", "tg"), t.get("src"))
    lines = ["🎫 <b>כרטיס #%s</b> · %s" % (t["id"], src),
             "👤 %s · %s" % (esc(t.get("name")), esc(t.get("tag")))]
    if t.get("src") == "tg":
        lines.append("🆔 <code>%s</code>" % t["user_id"])
    if t.get("taken_by"):
        lines.append("✋ מטפל: %s" % esc(t["taken_by"]))
    if t.get("closed"):
        lines.append("✔️ נסגר על ידי %s" % esc(t.get("closed_by") or "—"))
    lines.append("")
    lines.append("💬 <i>השב להודעה הזו כדי לענות למשתמש</i>" if not t.get("closed") else "")
    return "\n".join(x for x in lines if x is not None)


def refresh_card(t):
    kb = None if t.get("closed") else (kb_taken(t["id"]) if t.get("taken_by") else kb_open(t["id"]))
    call("editMessageText", chat_id=GROUP, message_id=t["card_msg"],
         text=header(t) + "\n\n" + t.get("body", ""), parse_mode="HTML",
         reply_markup=kb, disable_web_page_preview=1)


# ── כרטיס חדש ───────────────────────────────────────────────────────────────
def open_ticket(src, user_id, name, tag, body, copy_from=None, copy_msg=None):
    with _lock:
        S["seq"] += 1
        tid = str(S["seq"])
        t = {"id": tid, "src": src, "user_id": user_id, "name": name, "tag": tag,
             "body": body, "opened": int(time.time()), "taken_by": None,
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


# ── תשובת מנהל: תגובה להודעה בקבוצה ─────────────────────────────────────────
def on_group_message(msg):
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
        with _lock:
            t["replies"].append({"at": int(time.time()),
                                 "text": msg.get("text") or msg.get("caption") or ""})
            save()
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
        t["replies"].append({"at": int(time.time()), "by": admin_name, "text": text})
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
    call("answerCallbackQuery", callback_query_id=cq["id"])  # ראשון, תמיד
    data = cq.get("data") or ""
    if ":" not in data:
        return
    act, tid = data.split(":", 1)
    with _lock:
        t = S["tickets"].get(tid)
    if not t:
        return
    name = who(cq["from"])[0]
    with _lock:
        if act == "take":
            if t.get("taken_by") and t["taken_by"] != name:
                call("answerCallbackQuery", callback_query_id=cq["id"],
                     text="%s כבר מטפל בזה" % t["taken_by"], show_alert=True)
                return
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
            answered = any(r.get("by") for r in t.get("replies", []) if r["at"] >= t["taken_at"])
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


# ── כרטיס מהאתר/אפליקציה ────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path.split("?")[0] != "/ticket":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        src = d.get("src") if d.get("src") in ("web", "app") else "web"
        body = str(d.get("text") or "").strip()[:3000]
        if not body:
            return self._json(400, {"error": "empty"})
        t = open_ticket(src, None, str(d.get("name") or "אנונימי")[:80],
                        str(d.get("contact") or "ללא פרטי קשר")[:80], esc(body))
        return self._json(200, {"ticket": t["id"] if t else None})

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == "/health":
            return self._json(200, {"ok": True, "tickets": len(S["tickets"])})
        if p.path == "/replies":
            tid = urllib.parse.parse_qs(p.query).get("ticket", [""])[0]
            t = S["tickets"].get(tid)
            if not t:
                return self._json(404, {"error": "no such ticket"})
            return self._json(200, {"closed": t.get("closed"), "replies": t.get("replies", [])})
        return self._json(404, {"error": "not found"})


def http_server():
    # 127.0.0.1 בלבד: הפתיחה הזו אינה מאומתת, ואין לה מה לעשות באינטרנט.
    srv = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    log("מאזין ב-127.0.0.1:%d" % HTTP_PORT)
    srv.serve_forever()


# ── לופ ─────────────────────────────────────────────────────────────────────
def main():
    load()
    me = call("getMe")
    if not me:
        log("getMe נכשל — טוקן שגוי או אין רשת")
        sys.exit(1)
    log("עלה כ-@%s" % me.get("username"))
    threading.Thread(target=janitor, daemon=True).start()
    threading.Thread(target=http_server, daemon=True).start()
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
        with _lock:
            save()


if __name__ == "__main__":
    main()
