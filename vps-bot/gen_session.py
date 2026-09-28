#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מחולל session string לחשבון משתמש (userbot) לבריכת הסטרימינג.
# הרץ על השרת:   /opt/zovex-bot/venv/bin/python gen_session.py
# הוא יבקש מספר טלפון + קוד אימות, ויוציא בסוף מחרוזת session — מדביקים אותה
# בפאנל (טאב "בוטים") בדיוק כמו טוקן בוט. חשוב: השתמש בחשבון שאינו הראשי שלך,
# ותוסיף אותו כחבר בערוץ הסטרימינג. משתמש ב-API_ID/API_HASH מ-/opt/zovex-bot/.env.
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import os
from pathlib import Path

def _load_env(path="/opt/zovex-bot/.env"):
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    # .env אינו בהכרח המקום שממנו השירות מקבל את ההגדרות — הן יכולות
    # לשבת ב-Environment= של יחידת systemd. check_userbot.py כבר דיווח
    # "חסר" על שרת שבו הכל מוגדר בגלל ההנחה הזאת, ולכן כאן יש נפילה
    # לסביבת התהליך החי במקום לשאול את המשתמש ערכים שכבר קיימים.
    if not (env.get("API_ID") and env.get("API_HASH")):
        try:
            import subprocess
            pid = subprocess.run(
                ["systemctl", "show", "zovex-bot", "-p", "MainPID", "--value"],
                capture_output=True, text=True, timeout=15).stdout.strip()
            if pid.isdigit() and int(pid) > 0:
                raw = Path(f"/proc/{pid}/environ").read_bytes()
                for part in raw.split(b"\0"):
                    s = part.decode("utf-8", "replace")
                    if "=" in s:
                        k, v = s.split("=", 1)
                        env.setdefault(k, v)
        except Exception:
            pass
    return env

async def main():
    from pyrogram import Client
    env = _load_env()
    api_id = env.get("API_ID") or os.environ.get("API_ID") or input("API_ID: ").strip()
    api_hash = env.get("API_HASH") or os.environ.get("API_HASH") or input("API_HASH: ").strip()
    print("הזן מספר טלפון עם קידומת (למשל +9725...).\n")
    # איפה הקוד מגיע — השאלה הראשונה ששואלים כאן בכל פעם. טלגרם שולח
    # אותו **בתוך טלגרם**, לצ'אט הרשמי בשם "Telegram", לכל מכשיר
    # שהחשבון מחובר בו. לא ב-SMS, אלא אם אין אף מכשיר כזה — ואז הוא
    # נופל ל-SMS או לשיחה אחרי כדקה-שתיים.
    print("הקוד יגיע **בתוך אפליקציית טלגרם**, בצ'אט הרשמי בשם")
    print("\"Telegram\" — ולא ב-SMS. אם אינך מחובר לחשבון בשום מכשיר,")
    print("המתן דקה-שתיים וטלגרם ייפול ל-SMS או לשיחה. אל תסגור חלון זה.")
    print("יש 2FA? תתבקש גם סיסמת הענן אחרי הקוד.\n")
    async with Client("zovex_gen", api_id=int(api_id), api_hash=api_hash, in_memory=True) as app:
        s = await app.export_session_string()
        me = await app.get_me()
        print("\n" + "=" * 60)
        print(f"התחברת בתור: {me.first_name} (@{me.username or '—'})")
        # המזהה, ולא רק השם: שם משתמש אפשר להחליף — וזה כבר ניתק כאן את
        # ההעלאה פעם אחת — והמזהה אינו משתנה לעולם.
        print(f"מזהה המשתמש: {me.id}")
        print("\n=== SESSION STRING (העתק הכל, שורה אחת) ===\n")
        print(s)
        print("\n" + "=" * 60)
        print("1. הדבק את המחרוזת בפאנל → טאב 'בוטים'. אל תשתף עם אף אחד.")
        print("2. מחק משם את השורה הישנה של החשבון הזה — session שנשלל")
        print("   ממשיך להיכשל בלולאה ולזהם את היומן.")
        print("3. אם זה החשבון שאליו ההעלאה מהטלפון צריכה להגיע, שים")
        print(f"   ב-.env:   SAVED_UPLOAD_USER={me.id}")
        print("   מספר ולא שם משתמש — שם אפשר להחליף, מזהה לא.")

if __name__ == "__main__":
    asyncio.run(main())
