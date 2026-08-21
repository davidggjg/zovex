"""טלאי כירורגי ל-main.py החי: מתקן את באג "נתקע אחרי ~37 דקות".

הבאג: כשה-file_reference של טלגרם פג באמצע צפייה, השגיאה מגיעה *בתוך* תוצאות
ה-gather של מסלול ה-media-bands (return_exceptions=True), ולכן ה-except לא
תפס אותה — וה-reference הפג נשאר במטמון וכל חלון המשיך להיכשל, עד כניסה מחדש
לסרט. התיקון: מנקים את מטמון ההודעה (לכל הבוטים) כשה-reference פג → שליפה
טרייה והזרם ממשיך לבד.

הטלאי נוגע רק בקטעים האלה; מגבה, בודק קומפילציה, ומשחזר אם משהו נכשל.
כל שינוי עצמאי — מדלג על מה שכבר מוחל.

    /opt/zovex-bot/venv/bin/python3 patch_file_reference.py           # דו"ח
    /opt/zovex-bot/venv/bin/python3 patch_file_reference.py --apply   # מחיל
"""
import argparse
import py_compile
import shutil
import time
from pathlib import Path

TARGET = Path("/opt/zovex-bot/main.py")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

HELPER = '''        _bot_msg_cache[key] = (msg, now + _BOT_MSG_TTL)
        return msg
    return None


def _purge_msg_cache(chat_id, message_id):
    """מנקה את הודעת ה-cache של *כל* הבוטים עבור פריט מסוים (file_reference פג
    גלובלית)."""
    for k in [k for k in _bot_msg_cache if k[1] == chat_id and k[2] == message_id]:
        _bot_msg_cache.pop(k, None)
'''
HELPER_OLD = '''        _bot_msg_cache[key] = (msg, now + _BOT_MSG_TTL)
        return msg
    return None
'''

BAD_OLD = '''            log.warning("media bands (%s) חלק נכשל: %s — מרענן חיבורים", bot["name"], bad)
            await drop_media_sessions(bot["name"], dc_id, gen)
            return None'''
BAD_NEW = '''            log.warning("media bands (%s) חלק נכשל: %s — מרענן חיבורים", bot["name"], bad)
            await drop_media_sessions(bot["name"], dc_id, gen)
            if isinstance(bad, FileReferenceExpired):
                _purge_msg_cache(chat_id, message_id)
            return None'''

# שדרוג שלושת מטפלי ה-FileReferenceExpired מ"בוט אחד" ל"כל הבוטים"
POPS = [
    ('''        except FileReferenceExpired:
            # ה-reference פג — נזרוק את ה-cache של הבוט ונתן לו סיבוב נוסף
            _bot_msg_cache.pop((bot["name"], chat_id, message_id), None)
            if pos > start:''',
     '''        except FileReferenceExpired:
            _purge_msg_cache(chat_id, message_id)
            if pos > start:'''),
    ('''        except FileReferenceExpired:
            _bot_msg_cache.pop((bot["name"], chat_id, message_id), None)
        except FloodWait as e:''',
     '''        except FileReferenceExpired:
            _purge_msg_cache(chat_id, message_id)
        except FloodWait as e:'''),
    ('''    except FileReferenceExpired:
        _bot_msg_cache.pop((bot["name"], chat_id, message_id), None)
        return None''',
     '''    except FileReferenceExpired:
        _purge_msg_cache(chat_id, message_id)
        return None'''),
]


def main():
    if not TARGET.exists():
        print(f"❌ לא נמצא {TARGET}")
        return 1
    src = TARGET.read_text(encoding="utf-8")
    steps, done, skip = [], [], []

    if "_purge_msg_cache" in src:
        skip.append("_purge_msg_cache כבר קיים")
    elif HELPER_OLD in src:
        steps.append(("helper", HELPER_OLD, HELPER))
    else:
        print("❌ לא נמצא עוגן ל-_get_bot_msg — ה-main.py החי שונה. עצירה.")
        return 1

    if "isinstance(bad, FileReferenceExpired)" in src:
        skip.append("תיקון ה-bad כבר מוחל")
    elif BAD_OLD in src:
        steps.append(("bad", BAD_OLD, BAD_NEW))
    else:
        skip.append("קטע ה-bad לא נמצא (אולי שונה) — מדלג")

    for i, (old, new) in enumerate(POPS):
        if old in src:
            steps.append((f"pop{i}", old, new))
        else:
            skip.append(f"pop{i} כבר מוחל/לא נמצא")

    print("שינויים שיוחלו:", ", ".join(s[0] for s in steps) or "(אין)")
    for m in skip:
        print("  · דילוג:", m)
    if not steps:
        print("אין מה להחיל.")
        return 0
    if not args.apply:
        print("\nהרצה יבשה — לא שונה כלום. להחלה: --apply")
        return 0

    patched = src
    for _name, old, new in steps:
        patched = patched.replace(old, new, 1)

    backup = TARGET.with_suffix(f".py.bak.{int(time.time())}")
    shutil.copy2(TARGET, backup)
    TARGET.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup, TARGET)
        print(f"❌ קומפילציה נכשלה — שוחזר. שגיאה:\n{e}")
        return 1
    print(f"✅ הוחלו {len(steps)} שינויים. גיבוי: {backup.name}")
    print("   להפעלה: systemctl restart zovex-bot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
