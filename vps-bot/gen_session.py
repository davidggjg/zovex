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
    return env

async def main():
    from pyrogram import Client
    env = _load_env()
    api_id = env.get("API_ID") or os.environ.get("API_ID") or input("API_ID: ").strip()
    api_hash = env.get("API_HASH") or os.environ.get("API_HASH") or input("API_HASH: ").strip()
    print("מתחבר... הזן מספר טלפון (עם קידומת, למשל +9725...) וקוד אימות כשתתבקש.\n")
    async with Client("zovex_gen", api_id=int(api_id), api_hash=api_hash, in_memory=True) as app:
        s = await app.export_session_string()
        me = await app.get_me()
        print("\n" + "=" * 60)
        print(f"התחברת בתור: {me.first_name} (@{me.username or '—'})")
        print("\n=== SESSION STRING (העתק הכל, שורה אחת) ===\n")
        print(s)
        print("\n" + "=" * 60)
        print("הדבק את המחרוזת הזו בפאנל → טאב 'בוטים'. אל תשתף אותה עם אף אחד!")

if __name__ == "__main__":
    asyncio.run(main())
