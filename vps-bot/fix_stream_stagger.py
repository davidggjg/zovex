import pathlib, shutil, datetime, py_compile, sys, tempfile, os

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

ANCHOR = '''async def stream_from_channel(chat_id: int, message_id: int, request: Request):
    media = await channel_get_media(chat_id, message_id)'''

REPLACEMENT = '''# פיזור פתיחת זרמים חדשים: כשכמה צופים מתחילים סרט כמעט באותה
# שנייה, פתיחת כל החיבורים החדשים בבת אחת גורמת להתנגשות (נמדד:
# 3/4 נכשלים כשמתחילים ביחד, 1/4 כשמפוזרים ב-4 שניות). לצופה בודד
# זה שקוף לגמרי — ה-wait כמעט תמיד 0, כי אין עם מי להתנגש.
_stream_start_lock = asyncio.Lock()
_last_stream_start = 0.0
STREAM_START_STAGGER = float(os.environ.get("STREAM_START_STAGGER", "2.0"))

async def _stagger_new_stream():
    global _last_stream_start
    async with _stream_start_lock:
        now = time.time()
        wait = (_last_stream_start + STREAM_START_STAGGER) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_stream_start = time.time()

async def stream_from_channel(chat_id: int, message_id: int, request: Request):
    await _stagger_new_stream()
    media = await channel_get_media(chat_id, message_id)'''

def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)

def undo():
    baks = sorted(pathlib.Path("/opt/zovex-bot").glob("main.py.bak-stagger-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{baks[-1].name}")
    print("   הרץ:  systemctl restart zovex-bot")

def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")
    if "STREAM_START_STAGGER" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    n = src.count(ANCHOR)
    if n != 1:
        _fail(f"העוגן נמצא {n} פעמים (ציפינו לאחת) — הקובץ בשרת שונה ממה שציפינו.")
    out = src.replace(ANCHOR, REPLACEMENT, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as t:
        t.write(out); tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp); _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)
    bak = f"/opt/zovex-bot/main.py.bak-stagger-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   עכשיו:   systemctl restart zovex-bot")
    print("   ואז:     בדיקת 4 זרמים בבת אחת שוב, כדי לוודא שיפור")
    print("   נסיגה:   python3 fix_stream_stagger.py --undo")

if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
