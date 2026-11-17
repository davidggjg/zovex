#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_revoke_links — קישור של פריט שנמחק/הוחלף מפסיק לעבוד מיד.

## התקלה
  /stream, /cast, /fs, /vh, /vt בדקו רק חתימה ותוקף — לא שהפריט עדיין באתר.
  סרט שנמחק או שהקישור שלו הוחלף המשיך להתנגן לכל מי שהחזיק את הקישור הישן,
  עד שהחתימה פגה. גם הרלֵיי של שידורים חיים העביר כל ערוץ ממארח מאושר, גם אם
  הערוץ הוסר.
## התיקון
  אינדקס של מה שפעיל: כל (ערוץ, הודעה) ש-/stream מפנה אליו, וכל נתיב רלֵיי,
  מתוך הקטלוג **ומהממתינים בפאנל** (כדי שהקישור שבוט ההעלאה שולח ימשיך לעבוד).
  נבנה מחדש רק כשהקבצים משתנים. פריט שלא באינדקס → 410 "הפריט הוסר".
  · ברלֵיי נבדקות רק בקשות playlist — בלעדיהן הנגן לא ממשיך, והערוץ נעצר
    תוך שניות. בקשות פנימיות (ffmpeg / בדיקות) לא נחסמות.
  · תקלה באינדקס → מאפשרים (fail-open), כדי שבאג כאן לא יפיל את האתר.
  · STREAM_REVOKE=0 מכבה.
    MAIN_PY=... python3 fix_revoke_links.py [--check|--revert]
"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_revoke_links]"

HELPERS = r'''# ── [fix_revoke_links] רק מה שבאמת באתר (או ממתין בפאנל) מתנגן ──────────────
STREAM_REVOKE = os.environ.get("STREAM_REVOKE", "1") not in ("0", "false", "no")
_active_ix = {"kc": None, "kn": None, "media": set(), "relay": {}}
_RE_ACT_STREAM = re.compile(r"/(?:stream|cast|fs|vh|vt|vodinfo)/(-?\d+)/(\d+)")
_RE_ACT_RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?#]+)/([^?#]*)")
_TS_SFX = "/__ts.m3u8"


def _active_index():
    kc, kn = _file_key(CONTENT_FILE), _file_key(NEW_UPLOADS_FILE)
    if _active_ix["kc"] != kc or _active_ix["kn"] != kn:
        media, relay = set(), {}
        for lst in (load_content(), load_new_uploads()):
            for e in lst or []:
                for f in ("video_url", "video_id"):
                    u = str(e.get(f) or "")
                    for m in _RE_ACT_STREAM.finditer(u):
                        media.add((int(m.group(1)), int(m.group(2))))
                    m = _RE_ACT_RELAY.search(u)
                    if m:
                        h, p = m.group(1).partition(":")[0], m.group(2)
                        if p.endswith(_TS_SFX):   # זרם TS: רק הכתובת המדויקת (ערוצי Xtream חולקים תיקייה)
                            relay.setdefault(h, set()).add(p)
                        else:
                            relay.setdefault(h, set()).update({p, p.rsplit("/", 1)[0] if "/" in p else ""})
        _active_ix.update(kc=kc, kn=kn, media=media, relay=relay)
    return _active_ix


def _media_active(chat, msg) -> bool:
    if not STREAM_REVOKE:
        return True
    try:
        return (int(chat), int(msg)) in _active_index()["media"]
    except Exception as e:
        log.warning("revoke: אינדקס נכשל (%s) — מאפשר", e)
        return True


def _relay_active(host: str, path: str) -> bool:
    if not STREAM_REVOKE:
        return True
    try:
        ix = _active_index()["relay"]
        h = host.partition(":")[0]
        if h not in ix:
            return h in _relay_learned_hosts      # נלמד ממניפסט של ערוץ פעיל
        keys = ix[h]
        if path.endswith(_TS_SFX):
            return path in keys
        p = path
        if p in keys:
            return True
        d = p.rsplit("/", 1)[0] if "/" in p else ""
        return any(k == "" or d == k or d.startswith(k + "/") for k in keys)
    except Exception as e:
        log.warning("revoke: בדיקת רלֵיי נכשלה (%s) — מאפשר", e)
        return True


'''
GONE = '        raise HTTPException(status_code=410, detail="הפריט הוסר מהאתר")\n'
EDITS = [
 ("/stream",
  "    # תוכן בערוץ (chat_id שלילי) → דרך pool הבוטים; תוכן ישן (chat פרטי) → בוט ראשי\n",
  "    if not _media_active(chat_id, message_id):   # [fix_revoke_links]\n" + GONE +
  "    # תוכן בערוץ (chat_id שלילי) → דרך pool הבוטים; תוכן ישן (chat פרטי) → בוט ראשי\n"),
 ("/cast",
  "    # קישור פנימי חתום ל-/stream המקומי (ffmpeg מושך ממנו, דרך בריכת הבוטים)\n",
  "    if not _media_active(chat_id, message_id):   # [fix_revoke_links]\n" + GONE +
  "    # קישור פנימי חתום ל-/stream המקומי (ffmpeg מושך ממנו, דרך בריכת הבוטים)\n"),
 ("_vf_check_sig",
  "    if not hmac.compare_digest(sig, _stream_sig(str(chat), str(msg), exp)):\n        raise HTTPException(403, \"חתימה שגויה\")\n",
  "    if not hmac.compare_digest(sig, _stream_sig(str(chat), str(msg), exp)):\n        raise HTTPException(403, \"חתימה שגויה\")\n"
  "    if not _media_active(chat, msg):   # [fix_revoke_links] fs/vh/vt/vodinfo\n"
  "        raise HTTPException(410, \"הפריט הוסר מהאתר\")\n"),
 ("רלֵיי",
  "    if _is_hls_manifest(path):\n",
  "    if (_is_hls_manifest(path) and request.headers.get(\"x-zovex-probe\") != HLS_PROBE_TOKEN\n"
  "            and not is_local_request(request) and not _relay_active(base_host, path)):   # [fix_revoke_links]\n"
  "        raise HTTPException(410, \"הערוץ הוסר מהאתר\")\n"
  "    if _is_hls_manifest(path):\n"),
 ("_fix",
  "    # [fix_live_robust] בקשה ל-playlist.\n",
  "    if (request.headers.get(\"x-zovex-probe\") != HLS_PROBE_TOKEN and not is_local_request(request)\n"
  "            and not _relay_active(host, path)):   # [fix_revoke_links]\n"
  "        raise HTTPException(410, \"הערוץ הוסר מהאתר\")\n"
  "    # [fix_live_robust] בקשה ל-playlist.\n"),
]
EDITS.append(("הודעת כפילות בבוט",
  "    dup = find_upload_by_fuid(fuid)\n    if dup:\n        await message.reply_text(\n            f\"♻️ הקובץ הזה כבר קיים במערכת:\\n<b>{dup.get('title','—')}</b>\"\n",
  "    dup = find_upload_by_fuid(fuid)\n    if dup:\n"
  "        _c, _n = _dup_index()   # [fix_revoke_links] איפה הוא באמת\n"
  "        _where = (\"✅ כבר באתר\" if fuid in _c[\"fu\"]\n"
  "                  else \"⏳ ממתין לאישור בפאנל (העלאות מהבוט) — עוד לא באתר\")\n"
  "        await message.reply_text(\n            f\"♻️ הקובץ הזה כבר הועלה — {_where}:\\n<b>{dup.get('title','—')}</b>\"\n"))
HDR = '@api.get("/stream/{chat_id}/{message_id}")'


def apply(src):
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    out = src
    for name, a, n in EDITS:
        c = out.count(a)
        assert c == 1, f"עוגן '{name}': נמצא {c}"
        out = out.replace(a, n, 1)
    assert out.count(HDR) == 1
    out = out.replace(HDR, HELPERS + HDR, 1)
    compile(out, "main.py", "exec")
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_revoke"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__": sys.exit(main())
