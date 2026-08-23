"""מוסיף חימום-מקדים לבריכות (מאיץ "המשך צפייה"). החלפת קטע ייחודי.
הרצה:  sudo /opt/zovex-bot/venv/bin/python /opt/zovex-bot/patch_prewarm.py
"""
import py_compile, shutil, sys, time, pathlib
LIVE=pathlib.Path("/opt/zovex-bot/main.py")
PAIRS=[('prewarm on stream open', 'async def stream_from_channel(chat_id: int, message_id: int, request: Request):\n    media = await channel_get_media(chat_id, message_id)\n    if not media:\n        raise HTTPException(status_code=503, detail="No media / no healthy bot")\n    file_size = media.file_size', '# חימום-מקדים של בריכות ה-media. "המשך צפייה" קופץ לאמצע הקובץ (לא במטמון\n# הקצה) והמסלול המקבילי מסובב בוט אחר לכל חלון — כל בוט קר בונה בריכה מחדש\n# (~5ש) בזה אחר זה, ולכן resume חיכה פי-2. כאן, ברגע שפותחים סרט, מדליקים את\n# הבנייה של כמה בוטים *במקביל* (block=False רק מדליק את המילוי ברקע ולא ממתין),\n# כך שכשהחלונות מסתובבים בין הבוטים הם כבר חמים. ה-cooldown מונע הצפה: אותו DC\n# לא מחומם שוב בתוך כמה שניות, גם אם הנגן שולח עשרות בקשות range.\nPREWARM_BOTS = int(os.environ.get("STREAM_PREWARM_BOTS", "8"))\nPREWARM_COOLDOWN = int(os.environ.get("STREAM_PREWARM_COOLDOWN", "20"))\n_prewarm_seen: dict = {}\n\ndef _prewarm_dc(dc_id: int):\n    now = time.time()\n    if now - _prewarm_seen.get(dc_id, 0) < PREWARM_COOLDOWN:\n        return\n    _prewarm_seen[dc_id] = now\n    healthy = [b for b in _stream_bots\n               if b["cooldown_until"] < now and b.get("peer_ok", True)]\n\n    async def _run():\n        await asyncio.gather(*[\n            get_media_session_pool_gen(b["client"], b["name"], dc_id,\n                                       STREAM_MEDIA_CONNS, block=False)\n            for b in healthy[:PREWARM_BOTS]], return_exceptions=True)\n    if healthy:\n        asyncio.create_task(_run())\n\n\nasync def stream_from_channel(chat_id: int, message_id: int, request: Request):\n    media = await channel_get_media(chat_id, message_id)\n    if not media:\n        raise HTTPException(status_code=503, detail="No media / no healthy bot")\n    # מחממים את בריכות הבוטים ל-DC של הקובץ ברקע, כדי ש\'המשך צפייה\' יתחיל מהר\n    try:\n        _prewarm_dc(_file_location(media)[0])\n    except Exception:\n        pass\n    file_size = media.file_size')]
def main():
    out=LIVE.read_text(encoding="utf-8"); applied=skipped=missing=None
    applied,skipped,missing=[],[],[]
    for name,old,new in PAIRS:
        if new in out: skipped.append(name)
        elif old in out: out=out.replace(old,new,1); applied.append(name)
        else: missing.append(name)
    if missing:
        print("❌ קטעים לא נמצאו:")
        for m in missing: print("   -",m)
        print("לא שונה כלום."); sys.exit(2)
    if not applied:
        print("✓ כבר מוחל."); return
    bak=LIVE.with_name("main_before_prewarm_%d.py"%int(time.time()))
    shutil.copy2(LIVE,bak); LIVE.write_text(out,encoding="utf-8")
    try: py_compile.compile(str(LIVE),doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak,LIVE); print("❌ קומפילציה נכשלה — שוחזר. %s"%e); sys.exit(3)
    print("✅ הוחל. גיבוי: %s"%bak.name)
    print("עכשיו:  sudo systemctl restart zovex-bot")
if __name__=="__main__": main()
