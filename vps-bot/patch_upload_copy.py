#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# "ההעלאה לערוץ נכשלה: 'NoneType' object has no attribute 'id'"
#
# ## מה קורה
#
#     copied = await client.copy_message(...)
#     channel_msg_id = copied.id
#
# ‎copy_message‎ של Pyrogram מחזיר ‎None‎ על סוגי הודעות שהוא אינו יודע
# להעתיק, במקום לזרוק שגיאה. השורה הבאה ניגשת ל-‎.id‎ ונופלת, וה-‎except‎
# הכללי מדפיס "ודא שבוט ההעלאה הוא אדמין בערוץ" — הודעה שאין לה שום קשר
# לסיבה.
#
# דווח מהשטח בדיוק כך: הבוט מנהל בערוץ, קובץ אחד נכשל ומיד אחריו קובץ
# אחר עובר. זה לא הרשאות — זה סוג ההודעה.
#
# ## שני תיקונים
#
# 1. נפילה חזרה לשליחה לפי file_id. ‎send_cached_media‎ שולח את אותו קובץ
#    בדיוק בלי להעתיק הודעה, ולכן הוא עובד גם כשההעתקה לא נתמכת. זה
#    הופך את הכישלון הזה לנדיר באמת במקום לשגיאה שהמנהל רואה.
#
# 2. הודעת שגיאה שאומרת אמת. "ודא שהבוט אדמין" נאמר רק כשהשגיאה באמת
#    על הרשאות; בכל שאר המקרים מוצג מה שקרה בפועל, בלי לשלוח את המנהל
#    לבדוק דבר שתקין.
#
# ## בטיחות
#
# התאמה מדויקת או סירוב. גיבוי לפני כתיבה, בדיקת קומפילציה אחרי.
#
#   python3 patch_upload_copy.py [נתיב ל-main.py]
#   python3 patch_upload_copy.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "fix_copy_none"

OLD = '''                copied = await client.copy_message(
                    chat_id=dest_channel,
                    from_chat_id=message.chat.id,
                    message_id=message.id,
                )
                channel_msg_id = copied.id'''

NEW = '''                copied = await client.copy_message(
                    chat_id=dest_channel,
                    from_chat_id=message.chat.id,
                    message_id=message.id,
                )
                # [fix_copy_none] copy_message מחזיר None, לא זורק שגיאה.
                #
                # Pyrogram מחזיר None על סוגי הודעות שהוא אינו יודע
                # להעתיק, והשורה הבאה ניגשה ל-.id ונפלה עם
                # "'NoneType' object has no attribute 'id'". ה-except
                # הכללי הדפיס "ודא שהבוט אדמין בערוץ" — הודעה שאין לה
                # קשר, ששלחה את המנהל לבדוק הרשאות תקינות.
                #
                # send_cached_media שולח את אותו קובץ לפי file_id בלי
                # להעתיק הודעה, ולכן הוא עובד גם כאן. הכיתוב נשמר, ו-
                # 1024 הוא גבול הכיתוב של טלגרם.
                if copied is None:
                    log.warning("upload_bot: copy_message החזיר None — "
                                "נופל לשליחה לפי file_id")
                    cap = (message.caption or "")[:1024] or None
                    copied = await client.send_cached_media(
                        chat_id=dest_channel,
                        file_id=media.file_id,
                        caption=cap,
                    )
                if copied is None:
                    raise RuntimeError(
                        "טלגרם לא החזיר הודעה — הקובץ לא נקלט בערוץ")
                channel_msg_id = copied.id'''

OLD_ERR = '''                log.warning("upload_bot: copy_message נכשל: %s", e)
                await status.edit_text(f"❌ ההעלאה לערוץ נכשלה: {e}\\n"
                                       f"ודא שבוט ההעלאה הוא אדמין בערוץ.")
                return'''

NEW_ERR = '''                log.warning("upload_bot: copy_message נכשל: %s", e)
                # [fix_copy_none] ההודעה אומרת אמת.
                #
                # "ודא שהבוט אדמין" הודפס על *כל* שגיאה, ולכן שלח את
                # המנהל לבדוק הרשאות תקינות בזמן שהסיבה אחרת לגמרי.
                # עכשיו זה נאמר רק כשהשגיאה באמת על הרשאות.
                _txt = str(e).upper()
                _perm = any(k in _txt for k in (
                    "ADMIN", "FORBIDDEN", "RIGHT", "PRIVATE", "BANNED"))
                _hint = ("ודא שבוט ההעלאה הוא אדמין בערוץ."
                         if _perm else
                         "זו אינה בעיית הרשאות. נסה לשלוח את הקובץ שוב, "
                         "ואם זה חוזר — שלח אותו כמסמך.")
                await status.edit_text(f"❌ ההעלאה לערוץ נכשלה: {e}\\n{_hint}")
                return'''

PAIRS = [(OLD, NEW), (OLD_ERR, NEW_ERR)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_copynone_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return

    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return

    for i, (old, _) in enumerate(PAIRS, 1):
        n = s.count(old)
        if n != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} לא נמצא בדיוק פעם אחת "
                     f"({n}). לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_copynone_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)

    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\\n   {e}")

    print(f"✓ הוחל. גיבוי: {bak}")
    print("  נפילה לשליחה לפי file_id כש-copy_message מחזיר None")
    print("  הודעת שגיאה מדויקת במקום האשמת הרשאות")


if __name__ == "__main__":
    main()
