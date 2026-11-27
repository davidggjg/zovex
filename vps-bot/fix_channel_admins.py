#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_channel_admins — מי מנהל בערוצי התוכן ולא מחובר לפאנל.

POST /pool/channel-admins {password}  →  לכל ערוץ תוכן: כל המנהלים (מטלגרם עצמה),
מסומנים: מחובר לפאנל / בוט ההעלאה / לא מחובר. בנוסף: בוטים בפאנל שאינם מנהלים.
קריאה בלבד — לא משנה כלום. CLI: zv-admins
    python3 fix_channel_admins.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_channel_admins]"
TAIL = '''# [fix_channel_admins] מנהלי ערוצי התוכן מול הבוטים שבפאנל (קריאה בלבד)
@api.post("/pool/channel-admins")
async def _pool_channel_admins(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    from pyrogram import enums as _ca_enums
    panel_ids = {int(b.get("uid") or 0): b for b in _stream_bots if b.get("uid")}
    panel_names = {str(b.get("who") or "").lstrip("@").lower(): b for b in _stream_bots if b.get("who")}
    up_id = 0
    try:
        if upload_bot is not None and getattr(upload_bot, "me", None):
            up_id = int(upload_bot.me.id)
    except Exception:
        pass
    clients = ([upload_bot] if upload_bot is not None else []) + \
              [b["client"] for b in _stream_bots if b.get("peer_ok", True) and b.get("client")]
    out = []
    seen_admin_ids = set()
    for ch in (STREAM_CHANNELS or [STREAM_CHANNEL_ID]):
        res = {"channel": ch, "admins": [], "error": ""}
        for cl in clients[:6]:
            try:
                rows = []
                async for m in cl.get_chat_members(ch, filter=_ca_enums.ChatMembersFilter.ADMINISTRATORS):
                    u = m.user
                    if u is None:
                        continue
                    un = (u.username or "").lower()
                    if u.id in panel_ids or (un and un in panel_names):
                        st = "panel"
                    elif u.id == up_id:
                        st = "upload_bot"
                    else:
                        st = "NOT_IN_PANEL"
                    seen_admin_ids.add(u.id)
                    rows.append({"id": u.id, "username": u.username or "", "name": (u.first_name or "")[:40],
                                 "is_bot": bool(u.is_bot), "status": st})
                res["admins"] = rows
                res["error"] = ""
                break
            except Exception as e:
                res["error"] = f"{type(e).__name__}: {e}"[:200]
        out.append(res)
    not_admin = [{"name": b.get("name"), "who": b.get("who", ""), "uid": b.get("uid", 0)}
                 for b in _stream_bots if b.get("uid") and int(b["uid"]) not in seen_admin_ids]
    return {"channels": out, "panel_bots": len(_stream_bots), "panel_not_admin": not_admin}'''

def _tail_insert(src, block):
    m = re.search(r"^if __name__ == [\"']__main__[\"']\s*:", src, re.M)
    if m: return src[:m.start()] + block + "\n\n" + src[m.start():]
    return src.rstrip("\n") + "\n\n" + block + "\n"

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace("\n\n" + TAIL + "\n", "\n", 1).replace(TAIL, "", 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_chadmins"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    for need in ("class PoolPwReq", "_stream_bots", "upload_bot", "STREAM_CHANNELS"):
        assert need in src, f"חסר {need} ב-main.py"
    out = _tail_insert(src, TAIL); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_chadmins"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_chadmins"); return 0
if __name__ == "__main__": sys.exit(main())
