"""מחיל: חימום-מקדים של בריכות + רענון קטלוג לפני שהחתימות פגות.
הרצה:  sudo /opt/zovex-bot/venv/bin/python /opt/zovex-bot/patch_v2.py
"""
import py_compile, shutil, sys, time, pathlib
LIVE=pathlib.Path("/opt/zovex-bot/main.py")
PAIRS=[('prewarm on stream open', 'async def stream_from_channel(chat_id: int, message_id: int, request: Request):\n    media = await channel_get_media(chat_id, message_id)\n    if not media:\n        raise HTTPException(status_code=503, detail="No media / no healthy bot")\n    file_size = media.file_size', '# חימום-מקדים של בריכות ה-media. "המשך צפייה" קופץ לאמצע הקובץ (לא במטמון\n# הקצה) והמסלול המקבילי מסובב בוט אחר לכל חלון — כל בוט קר בונה בריכה מחדש\n# (~5ש) בזה אחר זה, ולכן resume חיכה פי-2. כאן, ברגע שפותחים סרט, מדליקים את\n# הבנייה של כמה בוטים *במקביל* (block=False רק מדליק את המילוי ברקע ולא ממתין),\n# כך שכשהחלונות מסתובבים בין הבוטים הם כבר חמים. ה-cooldown מונע הצפה: אותו DC\n# לא מחומם שוב בתוך כמה שניות, גם אם הנגן שולח עשרות בקשות range.\nPREWARM_BOTS = int(os.environ.get("STREAM_PREWARM_BOTS", "8"))\nPREWARM_COOLDOWN = int(os.environ.get("STREAM_PREWARM_COOLDOWN", "20"))\n_prewarm_seen: dict = {}\n\ndef _prewarm_dc(dc_id: int):\n    now = time.time()\n    if now - _prewarm_seen.get(dc_id, 0) < PREWARM_COOLDOWN:\n        return\n    _prewarm_seen[dc_id] = now\n    healthy = [b for b in _stream_bots\n               if b["cooldown_until"] < now and b.get("peer_ok", True)]\n\n    async def _run():\n        await asyncio.gather(*[\n            get_media_session_pool_gen(b["client"], b["name"], dc_id,\n                                       STREAM_MEDIA_CONNS, block=False)\n            for b in healthy[:PREWARM_BOTS]], return_exceptions=True)\n    if healthy:\n        asyncio.create_task(_run())\n\n\nasync def stream_from_channel(chat_id: int, message_id: int, request: Request):\n    media = await channel_get_media(chat_id, message_id)\n    if not media:\n        raise HTTPException(status_code=503, detail="No media / no healthy bot")\n    # מחממים את בריכות הבוטים ל-DC של הקובץ ברקע, כדי ש\'המשך צפייה\' יתחיל מהר\n    try:\n        _prewarm_dc(_file_location(media)[0])\n    except Exception:\n        pass\n    file_size = media.file_size'), ('SIGN_TTL 6h->24h', 'SIGN_TTL = int(os.environ.get("STREAM_SIGN_TTL", "21600"))  # 6 שעות — מספיק לסרט ארוך', '# 24 שעות. 6 שעות הספיקו לסרט בודד, אבל לא לטאב/אפליקציה שנשארים פתוחים\n# ליום שלם — ואז החתימה פגה מתחת לידיים והנגן קיבל 403. יחד עם רענון הקטלוג\n# לפי SIG_EPOCH_WINDOW, לקוח מקבל קישורים טריים הרבה לפני שהישנים פגים.\nSIGN_TTL = int(os.environ.get("STREAM_SIGN_TTL", "86400"))'), ('sig epoch helper', 'def _fresh(c, ver, ttl, now=None):\n    return c and c["ver"] == ver and ((now or time.time()) - c["built"]) < ttl', 'def _fresh(c, ver, ttl, now=None):\n    return c and c["ver"] == ver and ((now or time.time()) - c["built"]) < ttl\n\n\n# ── רענון כפוי של הקטלוג אצל הלקוח ───────────────────────────────────────────\n# הקישורים בקטלוג חתומים ותקפים SIGN_TTL שניות. ה-ETag היה מבוסס על גרסת\n# התוכן בלבד, ולכן לקוח שלא ראה שינוי תוכן קיבל 304 לנצח והמשיך להחזיק את\n# הקטלוג הישן שלו — עד שהחתימות שבו פגו וכל לחיצה על "נגן" החזירה 403\n# ("הקישור פג תוקף"). זה מה שאילץ מחיקה והתקנה מחדש של האפליקציה.\n#\n# הפתרון: משלבים ב-ETag גם "חלון זמן". כשהחלון מתחלף ה-ETag משתנה, הלקוח\n# מוריד קטלוג טרי עם חתימות חדשות, וזה קורה הרבה לפני שהישנות פגות. החלון\n# הוא שליש מתוקף החתימה — כלומר שני רענונים לפחות בתוך כל חיים של חתימה.\nSIG_EPOCH_WINDOW = max(600, SIGN_TTL // 3)\n\n\ndef _sig_epoch() -> int:\n    return int(time.time()) // SIG_EPOCH_WINDOW'), ('etag lite', 'etag = f\'W/"l{ver}-{limit}"\'', 'etag = f\'W/"l{ver}-{limit}-{_sig_epoch()}"\''), ('etag live', 'f\'W/"v{ver}"\', {"X-Content-Version"', 'f\'W/"v{ver}-{_sig_epoch()}"\', {"X-Content-Version"'), ('etag full', 'f\'W/"c{ver}"\', {"X-Content-Version"', 'f\'W/"c{ver}-{_sig_epoch()}"\', {"X-Content-Version"')]
def main():
    out=LIVE.read_text(encoding="utf-8")
    applied,skipped,missing=[],[],[]
    for name,old,new in PAIRS:
        if new in out: skipped.append(name)
        elif old in out: out=out.replace(old,new,1); applied.append(name)
        else: missing.append(name)
    if missing:
        print("\u274c \u05e7\u05d8\u05e2\u05d9\u05dd \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0\u05d5:")
        for m in missing: print("   -",m)
        print("\u05dc\u05d0 \u05e9\u05d5\u05e0\u05d4 \u05db\u05dc\u05d5\u05dd."); sys.exit(2)
    if not applied:
        print("\u2713 \u05db\u05d1\u05e8 \u05de\u05d5\u05d7\u05dc."); return
    bak=LIVE.with_name("main_before_v2_%d.py"%int(time.time()))
    shutil.copy2(LIVE,bak); LIVE.write_text(out,encoding="utf-8")
    try: py_compile.compile(str(LIVE),doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak,LIVE); print("\u274c \u05e7\u05d5\u05de\u05e4\u05d9\u05dc\u05e6\u05d9\u05d4 \u05e0\u05db\u05e9\u05dc\u05d4 \u2014 \u05e9\u05d5\u05d7\u05d6\u05e8. %s"%e); sys.exit(3)
    print("\u2705 \u05d4\u05d5\u05d7\u05dc. \u05e9\u05d5\u05e0\u05d5 %d \u05e7\u05d8\u05e2\u05d9\u05dd:"%len(applied))
    for a in applied: print("   +",a)
    if skipped: print("   (\u05d3\u05d9\u05dc\u05d5\u05d2 \u05e2\u05dc %d)"%len(skipped))
    print("\u05d2\u05d9\u05d1\u05d5\u05d9: %s"%bak.name)
    print("\n\u05e2\u05db\u05e9\u05d9\u05d5:  sudo systemctl restart zovex-bot")
if __name__=="__main__": main()
