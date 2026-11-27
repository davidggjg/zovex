#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_channel_admins2 — zv-admins מדויק גם מיד אחרי הפעלה + פקודה /admins בבוט ההעלאה.

  1. "מחובר לפאנל" נקבע גם לפי הטוקנים בקובץ stream_bots.txt (מזהה הבוט = החלק שלפני
     ':' בטוקן) — לא רק לפי הבוטים שכבר סיימו לעלות. הגרסה הקודמת, 30ש אחרי הפעלה,
     ראתה רק 4 בוטים מחוברים וסימנה 37 כ"לא מחוברים".
  2. שולחים לבוט ההעלאה /admins (רק מנהל מורשה) ⇒ הוא עונה עם הרשימה. בלי הפעלה מחדש.
    python3 fix_channel_admins2.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot (פעם אחת)"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_channel_admins2]"

A1 = '''    check_panel_password(request, req.password)
    from pyrogram import enums as _ca_enums
    panel_ids = {int(b.get("uid") or 0): b for b in _stream_bots if b.get("uid")}'''
N1 = '''    if request is not None:                                  # [fix_channel_admins2] None = מבוט ההעלאה
        check_panel_password(request, req.password)
    from pyrogram import enums as _ca_enums
    panel_ids = {int(b.get("uid") or 0): b for b in _stream_bots if b.get("uid")}
    _ca_file_ids = set()
    for _t in _pool_tokens_in_file():
        _p = _t.split(":", 1)[0]
        if _p.isdigit():
            _ca_file_ids.add(int(_p))
            panel_ids.setdefault(int(_p), {"name": "בקובץ", "who": ""})'''

A2 = '''    return {"channels": out, "panel_bots": len(_stream_bots), "panel_not_admin": not_admin}'''
N2 = '''    return {"channels": out, "panel_bots": len(_stream_bots), "panel_not_admin": not_admin,
            "in_file": len(_ca_file_ids)}


async def _ca_bot_report(message):
    """[fix_channel_admins2] /admins בבוט ההעלאה."""
    try:
        d = await _pool_channel_admins(None, None)
    except Exception as e:
        await message.reply_text(f"❌ {type(e).__name__}: {e}"[:400]); return
    lines = [f"🤖 בפאנל: {d.get('in_file', 0)} טוקנים · עלו כרגע: {d['panel_bots']}"]
    for c in d["channels"]:
        a = c["admins"]
        lines.append(f"\\n📺 ערוץ {c['channel']} · {len(a)} מנהלים · {sum(x['is_bot'] for x in a)} בוטים")
        if c["error"] and not a:
            lines.append("שגיאה: " + c["error"]); continue
        nb = [x for x in a if x["status"] == "NOT_IN_PANEL" and x["is_bot"]]
        lines.append(f"🔴 בוטים מנהלים שלא בפאנל ({len(nb)}):")
        lines += [f"@{x['username'] or '-'}  ({x['id']})" for x in nb] or ["אין ✓"]
        hu = [x for x in a if not x["is_bot"]]
        lines.append(f"👤 אנשים ({len(hu)}): " + ", ".join("@" + (x["username"] or str(x["id"])) for x in hu))
    pn = d["panel_not_admin"]
    lines.append(f"\\n🟡 בפאנל אבל לא מנהלים ({len(pn)}): " + (", ".join(f"{x['name']} {x['who']}" for x in pn) or "אין"))
    txt, chunk = "\\n".join(lines), ""
    for ln in txt.split("\\n"):
        if len(chunk) + len(ln) > 3800:
            await message.reply_text(chunk); chunk = ""
        chunk += ln + "\\n"
    if chunk.strip():
        await message.reply_text(chunk)'''

A3 = '''        log.info("upload_bot: התעלמות מ-uid לא-מורשה %s", uid)
        return
'''
N3 = A3 + '''    if _txt.strip().split("@")[0] in ("/admins", "/בוטים"):   # [fix_channel_admins2]
        await _ca_bot_report(message)
        return
'''

EDITS = [("נקודת קצה", A1, N1), ("החזרה + דוח", A2, N2), ("פקודה בבוט", A3, N3)]

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src
        for _, a, n in EDITS: out = out.replace(n, a, 1)
        compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_chadmins2"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert "[fix_channel_admins]" in src, "קודם deploy_channel_admins.sh"
    out = src
    for nm, a, n in EDITS:
        c = out.count(a); assert c == 1, f"עוגן '{nm}': נמצא {c}"
        out = out.replace(a, n, 1)
    compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_chadmins2"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_chadmins2"); return 0
if __name__ == "__main__": sys.exit(main())
