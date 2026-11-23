#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_apk_guard — מונע את נעילת העדכון (APK ישן מוגש בשקט).

הבאג: קישור המקור (וגם ברירת המחדל APP_UPDATE_URL_DEFAULT) הוא דף השחרור
‎…/releases/latest‎ — דף HTML ולא קובץ. ההורדה נדחתה בשקט והשרת המשיך
להגיש APK ישן מהמטמון. העלאת min במצב כזה = לולאת עדכון שנועלת את כולם.

התיקון:
  1. כתובת דף-שחרור של GitHub מתוקנת אוטומטית ל-‎…/download/zovex.apk‎,
     וגם ברירת המחדל עצמה.
  2. ההורדה נבדקת שהיא באמת APK (חתימת ZIP ‏PK\\x03\\x04), לא רק בגודל.
  3. תוצאת הרענון האחרון (הצלחה/שגיאה/מקור/גודל/זמן) נשמרת ומוחזרת
     ב-/app/apk/status — כישלון כבר לא שקט.
  4. /app/version/set: פורמט x.y.z בלבד, min ≤ latest, ואסור להעלות
     latest/min כשהרענון האחרון נכשל או לא אומת (409 עם הסבר).
    python3 fix_apk_guard.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_apk_guard]"

E = []
# 1א. ברירת המחדל
E.append(("ברירת מחדל", '''    "APP_UPDATE_URL",
    "https://github.com/davidggjg/zovex-android/releases/latest")''',
'''    "APP_UPDATE_URL",
    "https://github.com/davidggjg/zovex-android/releases/latest/download/zovex.apk")  # [fix_apk_guard]'''))
# 1ב. תיקון אוטומטי של דף-שחרור
E.append(("תיקון קישור", '''                    "מתעלם ומשתמש בברירת המחדל")
        return APK_SOURCE_URL
    return u''',
'''                    "מתעלם ומשתמש בברירת המחדל")
        return APK_SOURCE_URL
    return _apk_fix_release_url(u)

def _apk_fix_release_url(u: str) -> str:
    """[fix_apk_guard] דף שחרור של GitHub (HTML) → קישור ההורדה של הקובץ."""
    import re as _re
    m = _re.match(r"^(https://github\\.com/[^/]+/[^/]+)/releases/(latest|tag/([^/?#]+))/?(?:[?#].*)?$", u)
    if not m:
        return u
    if m.group(3):
        return f"{m.group(1)}/releases/download/{m.group(3)}/zovex.apk"
    return f"{m.group(1)}/releases/latest/download/zovex.apk"

_apk_last: dict = {"ok": None}   # [fix_apk_guard] תוצאת הרענון האחרון'''))
# 2. בדיקת תוכן + רישום
E.append(("בדיקת APK", '''            if tmp.stat().st_size < 1_000_000:
                raise RuntimeError("קובץ קטן מדי — כנראה לא APK")
            tmp.replace(APK_CACHE_FILE)''',
'''            if tmp.stat().st_size < 1_000_000:
                raise RuntimeError("קובץ קטן מדי — כנראה לא APK")
            with tmp.open("rb") as _f:           # [fix_apk_guard] APK = ZIP
                if _f.read(4) != b"PK\\x03\\x04":
                    raise RuntimeError("הקובץ שהורד אינו APK (כנראה דף אינטרנט) — בדוק את הקישור")
            tmp.replace(APK_CACHE_FILE)
            _apk_last.update(ok=True, error="", ts=time.time(), src=src,
                             size=APK_CACHE_FILE.stat().st_size)'''))
E.append(("רישום כישלון", '''            log.warning("רענון APK נכשל: %s", e)''',
'''            log.warning("רענון APK נכשל: %s", e)
            _apk_last.update(ok=False, error=str(e)[:300], ts=time.time(),
                             src=locals().get("src", ""))   # [fix_apk_guard]'''))
# 3. סטטוס
E.append(("סטטוס", '''            "updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}''',
'''            "updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "last_refresh": dict(_apk_last), "source": _apk_source_url()}   # [fix_apk_guard]'''))
# 4. ולידציה בשמירת גרסה
E.append(("ולידציית גרסה", '''    check_panel_password(request, req.password)
    v = load_app_version()
    if req.latest is not None: v["latest"] = req.latest.strip()
    if req.min is not None:    v["min"] = req.min.strip()''',
'''    check_panel_password(request, req.password)
    v = load_app_version()
    # [fix_apk_guard] ולידציה: פורמט, min ≤ latest, ולא מעלים גרסה על APK לא מאומת
    import re as _re
    def _vt(s):
        return tuple(int(x) for x in s.split("."))
    for _name, _val in (("latest", req.latest), ("min", req.min)):
        if _val is not None and not _re.fullmatch(r"\\d+(\\.\\d+){1,3}", _val.strip()):
            raise HTTPException(status_code=400, detail=f"{_name}: פורמט לא תקין «{_val}» — צריך למשל 1.0.68 (נקודות, לא פסיקים)")
    _new_latest = (req.latest or v.get("latest") or "0.0").strip()
    _new_min = (req.min or v.get("min") or "0.0").strip()
    if _vt(_new_min) > _vt(_new_latest):
        raise HTTPException(status_code=400, detail=f"min ({_new_min}) גבוה מ-latest ({_new_latest})")
    _raising = ((req.latest and _vt(req.latest.strip()) > _vt(v.get("latest") or "0.0"))
                or (req.min and _vt(req.min.strip()) > _vt(v.get("min") or "0.0")))
    if _raising and _apk_last.get("ok") is not True:
        raise HTTPException(status_code=409, detail=(
            "לא מעלים גרסה לפני שה-APK במטמון אומת: "
            + ("הרענון האחרון נכשל — " + _apk_last.get("error", "") if _apk_last.get("ok") is False
               else "לחץ 'רענן APK' וודא שהגודל תואם לגיטהאב")
            + ". אחרת המשתמשים ייכנסו ללולאת עדכון."))
    if req.latest is not None: v["latest"] = req.latest.strip()
    if req.min is not None:    v["min"] = req.min.strip()'''))
# 4ב. קישור נשמר כבר מתוקן
E.append(("שמירת קישור", '''        new_url = req.url.strip() or APP_UPDATE_URL_DEFAULT''',
'''        new_url = _apk_fix_release_url(req.url.strip() or APP_UPDATE_URL_DEFAULT)   # [fix_apk_guard]'''))

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src
        for _, a, n in E: out = out.replace(n, a, 1)
        compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_apkguard"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    if "def _apk_source_url" not in src:
        print("❌ patch_apk_source לא מותקן בשרת הזה — קודם deploy_apk_source.sh"); return 1
    out = src
    for name, a, n in E:
        c = out.count(a)
        assert c == 1, f"עוגן '{name}': נמצא {c} פעמים — שלח לי: grep -n 'apk' {PATH} | head -60"
        out = out.replace(a, n, 1)
    compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_apkguard"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_apkguard"); return 0
if __name__ == "__main__": sys.exit(main())
