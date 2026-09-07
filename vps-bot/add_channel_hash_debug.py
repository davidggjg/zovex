import pathlib, shutil, datetime, py_compile, sys, tempfile, os

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
MARKER = "DEBUG_CHANNEL_HASH_ENDPOINT"

ADDITION = '''

# ── ''' + MARKER + ''' — זמני, קריאה-בלבד: מחזיר את access_hash של הערוץ
# כמו שהבוט הרץ כבר מכיר אותו בזיכרון. להסיר אחרי שימוש. ──────────────────
@api.get("/debug/channel-hash")
async def _debug_channel_hash():
    try:
        peer = await bot_client.resolve_peer(STREAM_CHANNEL_ID)
        return {
            "channel_id": STREAM_CHANNEL_ID,
            "access_hash": getattr(peer, "access_hash", None),
            "type": type(peer).__name__,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
'''

def _fail(msg):
    print("❌ " + msg); print("   לא שונה כלום."); sys.exit(1)

def undo():
    baks = sorted(pathlib.Path("/opt/zovex-bot").glob("main.py.bak-chdebug-*"))
    if not baks: _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{baks[-1].name}")
    print("   הרץ:  systemctl restart zovex-bot")

def main():
    src = TARGET.read_text(encoding="utf-8")
    if MARKER in src:
        print("✓ כבר מוחל."); return
    out = src + ADDITION
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as t:
        t.write(out); tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp); _fail(f"לא מתקמפל: {e}")
    os.unlink(tmp)
    bak = f"/opt/zovex-bot/main.py.bak-chdebug-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print("   עכשיו:   systemctl restart zovex-bot")
    print("   ואז:     curl -s http://127.0.0.1:8000/debug/channel-hash")
    print("   נסיגה:   python3 add_channel_hash_debug.py --undo")

if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
