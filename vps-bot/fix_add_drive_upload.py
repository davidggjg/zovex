#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט העלאה מ-Google Drive: מעלה מאושר שולח "היי בוט" + קישור, והשרת מוריד
ומוסיף לרשימת ההעלאות בפאנל.

## מה זה עושה

  • רשימה חדשה בפאנל (כרטיס "בוט העלאה מדרייב") של מזהי טלגרם מורשים —
    נפרדת מהאדמינים. רק מי שברשימה (או אדמין) יכול להשתמש.
  • בבוט ההעלאה: הודעה שמתחילה ב-"היי בוט" ואחריה קישור Google Drive ציבורי
    → השרת מוריד את הקובץ (gdown), מעלה אותו לערוץ, ומוסיף לרשימת ההעלאות
    (ממתין לאישור בפאנל, בדיוק כמו העלאה רגילה).
  • מי שלא מורשה — הבוט מתעלם, לא עונה. מורשה שלא כתב "היי בוט" — אותו זרימת
    האדמין הרגילה (ואם אינו אדמין, שתיקה).

## הערות

  • דורש gdown:  pip3 install gdown
  • מגבלת גודל: 2GB (מגבלת העלאה של בוט טלגרם). קובץ גדול יותר — מהטלפון.
  • הנתיב בפאנל הוא /panel/drive-uploaders — תחת /panel/ שכבר מנותב לבוט
    (בשונה מנתיב ברמה עליונה, ש-nginx היה מגיש כקובץ סטטי ומחזיר 405).

    python3 fix_add_drive_upload.py --check
    python3 fix_add_drive_upload.py
    python3 fix_add_drive_upload.py --revert
    python3 fix_add_drive_upload.py --dir .     # למקור בריפו
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

# ── main.py: (תיאור, לפני, אחרי) ─────────────────────────────────────────────
MAIN_HELPERS_ANCHOR = "def is_admin_id(uid) -> bool:"
MAIN_HELPERS = '''# ── מעלי-דרייב מאושרים ────────────────────────────────────────────────────────
# רשימה נפרדת מהאדמינים: משתמשי טלגרם שמורשים לשלוח "היי בוט <קישור דרייב>"
# ולהזרים תוכן, בלי גישת אדמין מלאה. מנוהלת בפאנל (כרטיס נפרד).
DRIVE_UPLOADERS_FILE = DATA_DIR / "drive_uploaders.json"

def load_drive_uploaders() -> list:
    if DRIVE_UPLOADERS_FILE.exists():
        try:
            return json.loads(DRIVE_UPLOADERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_drive_uploaders(lst: list):
    DRIVE_UPLOADERS_FILE.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")

def is_drive_uploader(uid) -> bool:
    try:
        uid = int(uid)
    except Exception:
        return False
    return any(int(a.get("id", 0)) == uid for a in load_drive_uploaders())


'''

MAIN_PANEL_ANCHOR = "class PanelReq(BaseModel):"
MAIN_PANEL = '''class DriveUploaderReq(BaseModel):
    password: str
    action: str
    id: Optional[int] = None
    name: Optional[str] = ""


@api.post("/panel/drive-uploaders")
async def drive_uploaders_api(req: DriveUploaderReq, request: Request):
    """ניהול רשימת מעלי-הדרייב המאושרים. גישת אדמין בלבד."""
    check_panel_password(request, req.password)
    lst = load_drive_uploaders()
    if req.action == "list":
        return {"uploaders": lst}
    if req.action == "add":
        if req.id is None:
            raise HTTPException(400, "חסר id")
        if not any(int(a["id"]) == int(req.id) for a in lst):
            lst.append({"id": int(req.id), "name": req.name or ""})
            save_drive_uploaders(lst)
        return {"uploaders": lst}
    if req.action == "remove":
        lst = [a for a in lst if int(a["id"]) != int(req.id)]
        save_drive_uploaders(lst)
        return {"uploaders": lst}
    raise HTTPException(400, "פעולה לא מוכרת")


'''

MAIN_HANDLER_ANCHOR = "async def on_upload(client: Client, message: Message):"
MAIN_HANDLER = '''# ── העלאה מ-Google Drive: "היי בוט <קישור>" ממעלה מאושר ──────────────────────
DRIVE_TMP = DATA_DIR / "drive_tmp"
DRIVE_MIN_FREE = int(os.environ.get("DRIVE_MIN_FREE_GB", "6")) * 1024 ** 3
DRIVE_MAX_BYTES = int(os.environ.get("DRIVE_MAX_GB", "2")) * 1024 ** 3  # מגבלת בוט טלגרם


def _extract_drive_link(text: str):
    from urllib.parse import urlparse
    m = re.search(r"https?://[^\\s]+", text or "")
    if not m:
        return None
    url = m.group(0).strip().rstrip(").,\\u200f\\u200e")
    host = urlparse(url).netloc.lower()
    if host.endswith("google.com") or host.endswith("googleusercontent.com"):
        return url
    return None


def _blocking_drive_download(url: str, outdir: str):
    import re as _re, gdown
    # מחלצים את מזהה הקובץ מכל צורה נפוצה של קישור Drive ומשתמשים ב-uc?id=,
    # במקום פרמטר שלא קיים בכל גרסת gdown. gdown מטפל באישור של קבצים גדולים.
    m = (_re.search(r"/d/([A-Za-z0-9_-]{20,})", url)
         or _re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url))
    src = f"https://drive.google.com/uc?id={m.group(1)}" if m else url
    return gdown.download(src, output=outdir + "/", quiet=True)


async def _handle_drive_upload(client, message, uid, text):
    link = _extract_drive_link(text)
    if not link:
        await message.reply_text("שלח כך:\\nהיי בוט\\n<קישור Google Drive ציבורי>")
        return
    try:
        free = shutil.disk_usage(str(DATA_DIR)).free
    except Exception:
        free = None
    if free is not None and free < DRIVE_MIN_FREE:
        await message.reply_text(f"❌ אין מספיק מקום פנוי בשרת ({free // 1024**3}GB). נקה ונסה שוב.")
        return
    status = await message.reply_text("⏳ מוריד מהדרייב… יכול לקחת כמה דקות.")
    DRIVE_TMP.mkdir(parents=True, exist_ok=True)
    import tempfile
    workdir = tempfile.mkdtemp(dir=str(DRIVE_TMP))
    try:
        try:
            path = await asyncio.to_thread(_blocking_drive_download, link, workdir)
        except ModuleNotFoundError:
            await status.edit_text("❌ gdown לא מותקן בשרת. הרץ: pip3 install gdown")
            return
        except Exception as e:
            await status.edit_text(f"❌ ההורדה נכשלה: {str(e)[:200]}")
            return
        if not path or not os.path.exists(path):
            await status.edit_text("❌ לא הצלחתי להוריד. ודא שהקישור ציבורי ('כל מי שיש לו הקישור').")
            return
        size = os.path.getsize(path)
        if size > DRIVE_MAX_BYTES:
            await status.edit_text(
                f"❌ הקובץ גדול מדי ({size // 1024**3}GB). המגבלה דרך הבוט היא "
                f"{DRIVE_MAX_BYTES // 1024**3}GB — קובץ כזה תעלה מהטלפון.")
            return
        fname = os.path.basename(path)
        await status.edit_text(f"⬆️ מעלה לטלגרם: {fname} ({size // 1024**2}MB)…")
        dest_channel = current_upload_channel()
        async with _upload_lock:
            try:
                sent = await client.send_document(
                    dest_channel, path, file_name=fname, caption=fname[:200])
            except Exception as e:
                await status.edit_text(f"❌ ההעלאה לטלגרם נכשלה: {str(e)[:200]}")
                return
            channel_msg_id = sent.id
            note_uploaded_msg_id(dest_channel, channel_msg_id)
            await asyncio.sleep(1.5)
        media = sent.document or sent.video or sent.audio
        fuid = getattr(media, "file_unique_id", "") or ""
        # מוסיפים לרשימת ההעלאות (ממתין לאישור בפאנל), בלי בחירת TMDB אינטראקטיבית —
        # מעלה-דרייב אינו בהכרח אדמין, והאישור נעשה בפאנל כמו בכל העלאה.
        ep = parse_episode_info(fname)
        if ep:
            add_episode_entry(ep, channel_msg_id, fuid, dest_channel)
            await status.edit_text(
                f"✅ נוסף לרשימת ההעלאות: {ep['series']} — עונה {ep['season']} פרק {ep['episode']}.\\n"
                f"ממתין לאישור בפאנל.")
            return
        query, options = await smart_tmdb_search(fname)
        if options:
            entry = add_movie_entry(options[0], channel_msg_id, fuid, dest_channel)
            await status.edit_text(
                f"✅ נוסף לרשימת ההעלאות: {entry['title']} ({entry.get('year') or '?'}).\\n"
                f"בדוק ואשר בפאנל.")
        else:
            entry = add_movie_entry(
                {"title": query or fname, "year": "", "tmdb_id": 0, "type": "movie",
                 "poster": "", "overview": ""}, channel_msg_id, fuid, dest_channel)
            await status.edit_text(
                f"✅ נוסף לרשימת ההעלאות בשם: {entry['title']}.\\nבדוק ואשר בפאנל.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


'''

MAIN_ONUPLOAD_OLD = '''    uid = message.from_user.id if message.from_user else 0
    if not is_admin_id(uid):
        # לא מורשה — לא עונים כלל (הבעלים ביקש: מי שלא ברשימה, הבוט לא יענה לו)
        log.info("upload_bot: התעלמות מ-uid לא-מורשה %s", uid)
        return'''
MAIN_ONUPLOAD_NEW = '''    uid = message.from_user.id if message.from_user else 0
    _txt = (message.text or "")
    # "היי בוט <קישור דרייב>" — פתוח גם למעלי-דרייב מאושרים, לא רק לאדמינים.
    if re.match(r"^\\s*היי\\s*בוט", _txt):
        if is_admin_id(uid) or is_drive_uploader(uid):
            await _handle_drive_upload(client, message, uid, _txt)
        else:
            log.info("drive: התעלמות מ-uid לא-מורשה %s", uid)
        return
    if not is_admin_id(uid):
        # לא מורשה — לא עונים כלל (הבעלים ביקש: מי שלא ברשימה, הבוט לא יענה לו)
        log.info("upload_bot: התעלמות מ-uid לא-מורשה %s", uid)
        return'''

# ── admin.html: (תיאור, לפני, אחרי) ──────────────────────────────────────────
HTML_CARD_OLD = '''      <button class="mini" onclick="addAdmin()">הוסף</button>
      <div id="adminErr" class="err"></div><div id="adminsList" style="margin-top:8px"></div></div>'''
HTML_CARD_NEW = '''      <button class="mini" onclick="addAdmin()">הוסף</button>
      <div id="adminErr" class="err"></div><div id="adminsList" style="margin-top:8px"></div></div>

    <div class="card"><h2>בוט העלאה מדרייב — מזהים מורשים (Telegram ID)</h2>
      <div class="muted">מי שברשימה יכול לשלוח לבוט ההעלאה «היי בוט» ואז קישור Google Drive ציבורי, והשרת יוריד את הקובץ ויוסיף לרשימת ההעלאות. מי שלא ברשימה — הבוט מתעלם.</div>
      <div class="grid2" style="margin-top:8px">
        <input id="du_id" type="number" placeholder="Telegram ID"><input id="du_name" placeholder="שם (לא חובה)">
      </div>
      <button class="mini" onclick="addDriveUp()">הוסף</button>
      <div id="duErr" class="err"></div><div id="duList" style="margin-top:8px"></div></div>'''

HTML_JS_OLD = '''async function rmAdmin(id){ try{ renderAdmins((await panelApi("remove",{id})).admins);}catch(e){ alert(e.message); } }'''
HTML_JS_NEW = '''async function rmAdmin(id){ try{ renderAdmins((await panelApi("remove",{id})).admins);}catch(e){ alert(e.message); } }
// ── מעלי דרייב מאושרים ──
async function driveApi(action,extra){
  const r=await fetch("/panel/drive-uploaders",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({password:PASS,action,...(extra||{})})});
  if(!r.ok) throw new Error((await r.json()).detail||r.status); return r.json();
}
async function loadDriveUp(){ try{ renderDriveUp((await driveApi("list")).uploaders);}catch(e){ $("duErr").textContent=e.message; } }
function renderDriveUp(a){ $("duList").innerHTML=(a&&a.length)?a.map(x=>`<div class="item">
  <div class="meta"><div class="t">${esc(x.name||"—")}</div><div class="s">${x.id}</div></div>
  <button class="mini gray" onclick="rmDriveUp(${x.id})">הסר</button></div>`).join(""):'<div class="muted">אין מעלי דרייב.</div>'; }
async function addDriveUp(){ const id=$("du_id").value,name=$("du_name").value;
  if(!id){ $("duErr").textContent="חסר ID"; return; }
  try{ renderDriveUp((await driveApi("add",{id:parseInt(id),name})).uploaders); $("du_id").value="";$("du_name").value="";$("duErr").textContent="";}
  catch(e){ $("duErr").textContent=e.message; } }
async function rmDriveUp(id){ try{ renderDriveUp((await driveApi("remove",{id})).uploaders);}catch(e){ alert(e.message); } }'''

HTML_TAB_OLD = '''  if(n==="admins"){ loadAdmins(); loadVersion(); loadBans(); }'''
HTML_TAB_NEW = '''  if(n==="admins"){ loadAdmins(); loadDriveUp(); loadVersion(); loadBans(); }'''

MAIN_MARK = '@api.post("/panel/drive-uploaders")'
HTML_MARK = 'async function loadDriveUp('


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def _revert(path, tag):
    baks = sorted(glob.glob(f"{path}.bak-{tag}-*"))
    if not baks:
        print(f"  · אין גיבוי ל-{os.path.basename(path)} — מדולג")
        return
    shutil.copy2(baks[-1], path)
    print(f"  ✓ שוחזר {os.path.basename(path)} מ-{os.path.basename(baks[-1])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/opt/zovex-bot")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    base = pathlib.Path(a.dir)
    main_py = base / "main.py"
    admin = base / "admin.html"
    for p in (main_py, admin):
        if not p.exists():
            _fail(f"{p} לא נמצא")

    if a.revert:
        _revert(str(main_py), "driveup")
        _revert(str(admin), "driveup")
        print("   צריך: systemctl restart zovex-bot")
        return

    msrc = main_py.read_text(encoding="utf-8")
    hsrc = admin.read_text(encoding="utf-8")
    already_main = MAIN_MARK in msrc
    already_html = HTML_MARK in hsrc
    if already_main and already_html:
        print("✓ הפאץ' כבר מוחל בשני הקבצים. לא שונה כלום.")
        return

    mout = msrc
    if not already_main:
        for tok in ("def is_admin_id", "class PanelReq(BaseModel):",
                    "async def on_upload(", "def add_movie_entry",
                    "def smart_tmdb_search", "current_upload_channel",
                    "_upload_lock", "import subprocess"):
            if tok not in msrc:
                _fail(f"main.py חסר {tok} — הקובץ לא מה שציפינו לו.")
        edits = [("helpers", MAIN_HELPERS_ANCHOR, MAIN_HELPERS + MAIN_HELPERS_ANCHOR),
                 ("panel endpoint", MAIN_PANEL_ANCHOR, MAIN_PANEL + MAIN_PANEL_ANCHOR),
                 ("drive handler", MAIN_HANDLER_ANCHOR, MAIN_HANDLER + MAIN_HANDLER_ANCHOR),
                 ("on_upload routing", MAIN_ONUPLOAD_OLD, MAIN_ONUPLOAD_NEW)]
        for name, old, new in edits:
            if mout.count(old) != 1:
                _fail(f"main.py / {name}: נמצאו {mout.count(old)} התאמות, ציפינו ל-1.")
            mout = mout.replace(old, new)
            print(f"  ✓ main.py: {name}")
        try:
            compile(mout, str(main_py), "exec")
        except SyntaxError as e:
            _fail(f"main.py לא עובר קומפילציה: {e}")
    else:
        print("  · main.py כבר מוחל — מדולג")

    hout = hsrc
    if not already_html:
        edits = [("כרטיס מעלי-דרייב", HTML_CARD_OLD, HTML_CARD_NEW),
                 ("פונקציות JS", HTML_JS_OLD, HTML_JS_NEW),
                 ("טעינה בכניסה ללשונית", HTML_TAB_OLD, HTML_TAB_NEW)]
        for name, old, new in edits:
            if hout.count(old) != 1:
                _fail(f"admin.html / {name}: נמצאו {hout.count(old)} התאמות, ציפינו ל-1.")
            hout = hout.replace(old, new)
            print(f"  ✓ admin.html: {name}")
    else:
        print("  · admin.html כבר מוחל — מדולג")

    if a.check:
        print("\n✓ הכול מתאים ועובר קומפילציה. לא שונה כלום (--check).")
        return

    stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    if not already_main:
        shutil.copy2(main_py, f"{main_py}.bak-driveup-{stamp}")
        main_py.write_text(mout, encoding="utf-8")
    if not already_html:
        shutil.copy2(admin, f"{admin}.bak-driveup-{stamp}")
        admin.write_text(hout, encoding="utf-8")
    print(f"\n✓ הוחל. גיבויים עם החותמת {stamp}")
    print("   צריך: pip3 install gdown && systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
