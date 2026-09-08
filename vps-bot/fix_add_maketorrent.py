#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף ל-main.py נקודת קצה POST /maketorrent — יוצרת קובץ .torrent מפריט
שכבר הושלם בשרת, ומחזירה אותו להורדה.

## למה

qBittorrent 4.4.1 (שרץ בשרת) לא חושף API ליצירת טורנט — זה נוסף רק ב-5.0.
לכן היצירה רצה דרך mktorrent (כלי סטנדרטי: apt install -y mktorrent).

השימוש: להעלות לטרקר תוכן שהמשתמש מחזיק בזכויות עליו (יצירה שלו/של חבר,
נחלת הכלל, רישיון מתיר), כשהזריעה נשארת מהשרת — מוסיפים את ה-.torrent חזרה
ל-qBittorrent על אותו קובץ. השרת אינו בודק זכויות; האחריות על המשתמש.

## אבטחה

  • אימות: מעביר את עוגיית ה-SID של המבקש ל-qBittorrent ובודק שהיא תקפה —
    כך אין סיסמה שנייה, ומי שלא מחובר לדף הטורנטים נדחה (401). גיבוי:
    סיסמת ה-WebUI מ-/etc/qbt-webui.pass.
  • מניעת path traversal: הפריט חייב לשבת בתוך DL_ROOT/complete.
  • announce מאומת כ-URL, ולא נכתב ל-log (הוא מכיל passkey אישי).

    python3 fix_add_maketorrent.py --check
    python3 fix_add_maketorrent.py
    python3 fix_add_maketorrent.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py"))

ANCHOR = '@api.get("/content/relink")'
MARK = '@api.post("/maketorrent")'

BLOCK = '''# ── יצירת קובץ .torrent מפריט שכבר על השרת (mktorrent) ────────────────────────
# qBittorrent 4.4.1 לא חושף API ליצירת טורנט. לתוכן שהמשתמש מחזיק בזכויות עליו.
QBT_DL_ROOT = pathlib.Path(os.environ.get("QBT_DL_ROOT", "/home/torrents"))
QBT_WEBUI_HOST = os.environ.get("QBT_WEBUI_HOST", "127.0.0.1:8080")
QBT_WEBUI_PASS_FILE = pathlib.Path("/etc/qbt-webui.pass")


async def _qbt_cookie_ok(request: Request) -> bool:
    """מאמת מול qBittorrent — מעביר את עוגיית ה-SID ובודק אם תקפה. כך מי
    שכבר מחובר לדף הטורנטים מורשה, בלי סיסמה שנייה."""
    sid = request.cookies.get("SID")
    if not sid:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as cx:
            r = await cx.get(f"http://{QBT_WEBUI_HOST}/api/v2/app/version",
                             headers={"Cookie": f"SID={sid}"})
        return r.status_code == 200
    except Exception:
        return False


def _webui_pass_ok(pw: str) -> bool:
    """גיבוי לאימות מול /etc/qbt-webui.pass (טקסט גולמי)."""
    try:
        stored = QBT_WEBUI_PASS_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return False
    return bool(stored) and hmac.compare_digest(
        (pw or "").encode("utf-8", "surrogatepass"),
        stored.encode("utf-8", "surrogatepass"))


class MakeTorrentReq(BaseModel):
    name: str
    announce: str
    private: bool = True
    password: Optional[str] = None


@api.post("/maketorrent")
async def make_torrent(req: MakeTorrentReq, request: Request):
    """יוצר .torrent מפריט שהושלם ב-DL_ROOT/complete ומחזיר אותו להורדה.
    הזריעה נשארת מהשרת: מוסיפים את ה-.torrent חזרה ל-qBittorrent על אותו קובץ."""
    import tempfile
    if not (await _qbt_cookie_ok(request) or _webui_pass_ok(req.password or "")):
        raise HTTPException(status_code=401, detail="לא מחובר — התחבר בדף הטורנטים.")

    if not shutil.which("mktorrent"):
        raise HTTPException(status_code=503,
            detail="mktorrent לא מותקן בשרת. הרץ: apt install -y mktorrent")

    ann = (req.announce or "").strip()
    if not re.match(r"^(https?|udp)://", ann):
        raise HTTPException(status_code=400,
            detail="announce URL לא תקין — צריך להתחיל ב-http:// או https://")

    base = (QBT_DL_ROOT / "complete").resolve()
    name = (req.name or "").strip().strip("/")
    if not name:
        raise HTTPException(status_code=400, detail="חסר שם פריט")
    target = (base / name).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(status_code=400, detail="נתיב לא חוקי")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"הפריט לא נמצא: {name}")

    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name.split("/")[-1]) or "download"
    tmpdir = tempfile.mkdtemp()
    out = pathlib.Path(tmpdir) / (safe + ".torrent")
    cmd = ["mktorrent", "-a", ann, "-o", str(out)]
    if req.private:
        cmd.append("-p")
    cmd.append(str(target))
    try:
        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="יצירת הטורנט ארכה יותר מדי")
    if proc.returncode != 0 or not out.exists():
        err = (proc.stderr.decode("utf-8", "ignore")[:200] or "שגיאה").strip()
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="mktorrent נכשל: " + err)

    data = out.read_bytes()
    shutil.rmtree(tmpdir, ignore_errors=True)
    return Response(content=data, media_type="application/x-bittorrent",
        headers={"Content-Disposition": f'attachment; filename="{safe}.torrent"'})


'''


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-mktor-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הנקודה כבר קיימת. לא שונה כלום.")
        return
    for tok in ("import httpx", "import hmac", "import subprocess",
                "from pydantic import BaseModel", "Optional"):
        if tok not in src:
            _fail(f"main.py חסר {tok} — הקובץ לא מה שציפינו לו.")
    if src.count(ANCHOR) != 1:
        _fail(f"נמצאו {src.count(ANCHOR)} עוגני /content/relink, ציפינו ל-1.")

    out = src.replace(ANCHOR, BLOCK + ANCHOR)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if a.check:
        print("✓ העוגן מתאים והתוצאה עוברת קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-mktor-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: apt install -y mktorrent && systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
