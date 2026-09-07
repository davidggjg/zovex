#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן את הסיבה לכך שמחיקה בפאנל "לא נתפסת" — התנגשות עם בוט ההעלאות.

## מה קורה היום

הפאנל שולח בכל שמירה את *כל* הקטלוג, יחד עם base_version — מונה הגרסה שהיה
כשהדף נטען. השרת דוחה (409) אם המונה השתנה מאז, כדי ששני עורכים לא ידרסו זה
את זה.

אבל בוט ההעלאות מוסיף פריטים לאורך כל היום ומקפיץ את המונה — נמדד, כ-8
קפיצות בשעה. לכן ברגע שדוד מוחק פריט ולוחץ שמור, הגרסה שלו כבר ישנה:

    delItem() → movies.filter(...) → persist() שולח base_version ישן
    → 409 → הפאנל טוען מחדש את הקטלוג (עם הפריט) → הפריט חוזר

מבחוץ זה נראה בדיוק כמו "מחקתי וזה עדיין שם". הנעילה נכונה לשני בני אדם, אבל
הבוט מפעיל אותה בטעות — הוא רק *מוסיף* פריטים, ולא נוגע במה שמוחקים.

(אי אפשר פשוט לבטל את הנעילה: שמירה של המערך הישן של הפאנל הייתה מוחקת את כל
מה שהבוט הוסיף מאז הטעינה. הנעילה מגינה על זה. הפתרון הוא לא לשלוח את כל
המערך מלכתחילה.)

## מה זה משנה

בשרת — נקודת קצה חדשה POST /content/mutate שמוחקת/מעדכנת/מוסיפה *לפי מזהה*
על גבי המצב הנוכחי בשרת. אין base_version ואין דריסה: פריטים שהבוט הוסיף לא
נוגעים בהם, ולכן אין התנגשות. מגבלות העורך (בלי שידורים חיים, EDITOR_MAX_DELETE)
נשמרות.

בפאנל — כפתורי המחיקה והעריכה של פריט בודד (delItem, quickDel, delSeries,
saveItem, applyToSeries) עוברים דרך /content/mutate במקום דרך persist().
פעולות בכמות (העלאות, ייבוא) נשארות על /content/save — הן *מוסיפות*, ולכן
במקרה הגרוע הן מקבלות 409 ומבקשות לנסות שוב, בלי אובדן מידע.

    python3 fix_panel_delete_race.py --check      # לא נוגע בכלום
    python3 fix_panel_delete_race.py              # מחיל, עם גיבוי
    python3 fix_panel_delete_race.py --revert     # מחזיר
    python3 fix_panel_delete_race.py --dir .      # למקור בריפו במקום לשרת
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

# ── הבלוק שנוסף ל-main.py, לפני /content/relink ──────────────────────────────
MAIN_ANCHOR = '''@api.get("/content/relink")
async def content_relink(request: Request, dry: int = 1):'''

MAIN_BLOCK = '''class ContentMutateReq(BaseModel):
    password: str
    delete_ids: list = []
    upsert: list = []


@api.post("/content/mutate")
async def content_mutate(req: ContentMutateReq, request: Request):
    """שינוי כירורגי לפי מזהה, על גבי המצב הנוכחי בשרת — בלי לשלוח את כל
    הקטלוג ובלי base_version.

    /content/save שולח את כל המערך ונדחה (409) אם התוכן השתנה מאז שהפאנל
    נטען. אבל בוט ההעלאות מוסיף פריטים כל היום ומקפיץ את מונה הגרסה, ולכן
    כמעט כל מחיקה מהפאנל נפלה על הנעילה, הפאנל טען מחדש, והפריט "המחוק" חזר.
    כאן הפעולה חלה על מה שיש עכשיו לפי id, ולכן לא נוגעת בפריטים שהבוט הוסיף
    בינתיים ולא יכולה להתנגש איתם.
    """
    role = panel_role(request, req.password)
    prev = load_content()
    by_id = {str(e.get("id")): e for e in prev}
    del_ids = {str(x) for x in (req.delete_ids or []) if x is not None}
    ups = _collapse_urls([dict(u) for u in (req.upsert or []) if isinstance(u, dict)])

    # מגבלות עורך: אין נגיעה בשידורים חיים, ותקרת מחיקה. למנהל — חופש מלא.
    if role == "editor":
        if any(i in by_id and _is_live_item(by_id[i]) for i in del_ids):
            raise HTTPException(status_code=403,
                detail="עריכת שידורים חיים מותרת למנהל הראשי בלבד.")
        if any(_is_live_item(u) for u in ups):
            raise HTTPException(status_code=403,
                detail="הוספת או עריכת שידור חי מותרת למנהל הראשי בלבד.")
        real_del = [i for i in del_ids if i in by_id]
        if len(real_del) > EDITOR_MAX_DELETE:
            raise HTTPException(status_code=403, detail=(
                f"\\u26d4 \\u05de\\u05d7\\u05d9\\u05e7\\u05ea {len(real_del)} "
                f"\\u05e4\\u05e8\\u05d9\\u05d8\\u05d9\\u05dd \\u05d7\\u05d5\\u05e8\\u05d2\\u05ea "
                f"\\u05de\\u05d4\\u05de\\u05d5\\u05ea\\u05e8 ({EDITOR_MAX_DELETE}) "
                f"\\u05dc\\u05e2\\u05d5\\u05e8\\u05da."))

    # מחיקה
    result = [e for e in prev if str(e.get("id")) not in del_ids]
    deleted = len(prev) - len(result)

    # עדכון/הוספה לפי id (upsert עם id שמחוק — מדולג)
    result_ids = {str(e.get("id")) for e in result}
    to_update, to_add = {}, []
    for u in ups:
        uid = str(u.get("id")) if u.get("id") not in (None, "") else None
        if uid and uid in del_ids:
            continue
        if uid and uid in result_ids:
            to_update[uid] = u
        else:
            to_add.append(u)

    updated = 0
    for i, e in enumerate(result):
        k = str(e.get("id"))
        if k in to_update:
            result[i] = {**e, **to_update[k]}
            updated += 1

    added = 0
    prepend = []
    for u in to_add:
        if not u.get("id"):
            u["id"] = str(uuid.uuid4())
        if not u.get("created_date"):
            u["created_date"] = datetime.utcnow().isoformat() + "Z"
        prepend.append(u)
        added += 1
    result = prepend + result

    if deleted or updated or added:
        log.info("mutate: -%d ~%d +%d (role=%s)", deleted, updated, added, role)
    save_content(result)
    return {"ok": True, "deleted": deleted, "updated": updated, "added": added,
            "count": len(result), "version": get_content_version()}


'''

# ── תיקוני admin.html: (תיאור, לפני, אחרי) ───────────────────────────────────
# העוזר mutate נוסף מיד אחרי הסוגר של persist().
HTML_MUTATE_HELPER_ANCHOR = '''  }catch(e){ alert("שמירה נכשלה: "+e.message); return false; }
  finally{ toast(false); }
}'''

HTML_MUTATE_HELPER = '''  }catch(e){ alert("שמירה נכשלה: "+e.message); return false; }
  finally{ toast(false); }
}
// שינוי כירורגי לפי מזהה: מוחק/מעדכן/מוסיף פריטים בודדים על גבי המצב הנוכחי
// בשרת, בלי לשלוח את כל הקטלוג ובלי base_version. זה עוקף את התנגשות הגרסה
// שבוט ההעלאות גרם לה — כל מחיקה נפלה עליה והפריט "המחוק" חזר. אחרי הצלחה
// טוענים מחדש מהשרת, כך שרואים גם את מה שהבוט הוסיף בינתיים.
async function mutate(ops){
  const delete_ids=(ops&&ops.delete_ids)||[], upsert=(ops&&ops.upsert)||[];
  toast(true);
  try{
    const r=await fetch("/content/mutate",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS, delete_ids, upsert})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){ alert(d.detail||("שגיאה "+r.status)); return false; }
    await loadContent();   // אמת מהשרת, כולל העלאות חדשות של הבוט
    return true;
  }catch(e){ alert("הפעולה נכשלה: "+e.message); return false; }
  finally{ toast(false); }
}'''

HTML_PATCHES = [
    ("delItem — מחיקת פריט מהעורך",
     '''async function delItem(){
  if(!editingId||!confirm("למחוק?")) return;
  movies=movies.filter(m=>m.id!==editingId);
  if(await persist()){ refreshDerived(); openAdd(); }
}''',
     '''async function delItem(){
  if(!editingId||!confirm("למחוק?")) return;
  if(await mutate({delete_ids:[editingId]})){ openAdd(); }
}'''),

    ("saveItem — הוספה/עריכה של פריט בודד",
     '''  const wasEditing=!!editingId;
  if(editingId){ movies=movies.map(m=>m.id===editingId?{...m,...e}:m); }
  else { movies=[{...e,id:crypto.randomUUID(),created_date:new Date().toISOString()}, ...movies]; }
  if(await persist()){
    refreshDerived();
    if(_fromUploadCmid!=null){''',
     '''  const wasEditing=!!editingId;
  const item = editingId
    ? {...e, id:editingId}
    : {...e, id:crypto.randomUUID(), created_date:new Date().toISOString()};
  if(await mutate({upsert:[item]})){
    if(_fromUploadCmid!=null){'''),

    ("applyToSeries — עדכון פוסטר/תקציר לכל הסדרה",
     '''  if(!confirm(`לעדכן ${field==="thumbnail_url"?"פוסטר":"תקציר"} לכל הפרקים של «${n}»?`)) return;
  movies=movies.map(m=>m.series_name===n?{...m,[field]:val}:m);
  if(await persist()){ $("addMsg").innerHTML='<span class="ok">עודכן לכל הסדרה ✓</span>'; }''',
     '''  if(!confirm(`לעדכן ${field==="thumbnail_url"?"פוסטר":"תקציר"} לכל הפרקים של «${n}»?`)) return;
  const ups=movies.filter(m=>m.series_name===n).map(m=>({id:m.id,[field]:val}));
  if(await mutate({upsert:ups})){ $("addMsg").innerHTML='<span class="ok">עודכן לכל הסדרה ✓</span>'; }'''),

    ("quickDel — מחיקה מהירה מרשימת הניהול",
     '''async function quickDel(id){ if(!confirm("למחוק פריט?")) return; movies=movies.filter(m=>m.id!==id); if(await persist()){refreshDerived();renderManage();} }''',
     '''async function quickDel(id){ if(!confirm("למחוק פריט?")) return; if(await mutate({delete_ids:[id]})){ renderManage(); } }'''),

    ("delSeries — מחיקת סדרה שלמה",
     '''async function delSeries(n){ if(!confirm(`למחוק את כל הסדרה «${n}»?`)) return; movies=movies.filter(m=>m.series_name!==n); if(await persist()){refreshDerived();renderManage();} }''',
     '''async function delSeries(n){ if(!confirm(`למחוק את כל הסדרה «${n}»?`)) return; const ids=movies.filter(m=>m.series_name===n).map(m=>m.id).filter(Boolean); if(await mutate({delete_ids:ids})){ renderManage(); } }'''),
]

MAIN_MARK = '@api.post("/content/mutate")'
HTML_MARK = 'async function mutate(ops){'


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
    ap.add_argument("--dir", default="/opt/zovex-bot",
                    help="תיקיית main.py ו-admin.html (ברירת מחדל: השרת)")
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
        _revert(str(main_py), "mutate")
        _revert(str(admin), "mutate")
        print("   צריך: systemctl restart zovex-bot")
        return

    msrc = main_py.read_text(encoding="utf-8")
    hsrc = admin.read_text(encoding="utf-8")

    already_main = MAIN_MARK in msrc
    already_html = HTML_MARK in hsrc
    if already_main and already_html:
        print("✓ הפאץ' כבר מוחל בשני הקבצים. לא שונה כלום.")
        return

    # ── main.py ──
    mout = msrc
    if not already_main:
        for tok, name in [("_collapse_urls", "_collapse_urls"),
                          ("_is_live_item", "_is_live_item"),
                          ("EDITOR_MAX_DELETE", "EDITOR_MAX_DELETE"),
                          ("def load_content", "load_content")]:
            if tok not in msrc:
                _fail(f"main.py חסר {name} — הקובץ לא מה שציפינו לו.")
        if msrc.count(MAIN_ANCHOR) != 1:
            _fail(f"main.py: נמצאו {msrc.count(MAIN_ANCHOR)} עוגני /content/relink, ציפינו ל-1.")
        mout = msrc.replace(MAIN_ANCHOR, MAIN_BLOCK + MAIN_ANCHOR)
        try:
            compile(mout, str(main_py), "exec")
        except SyntaxError as e:
            _fail(f"main.py לא עובר קומפילציה אחרי הפאץ': {e}")
        print("  ✓ main.py: /content/mutate")
    else:
        print("  · main.py כבר מכיל /content/mutate — מדולג")

    # ── admin.html ──
    hout = hsrc
    if not already_html:
        if hout.count(HTML_MUTATE_HELPER_ANCHOR) != 1:
            _fail(f"admin.html: נמצאו {hout.count(HTML_MUTATE_HELPER_ANCHOR)} עוגני persist(), ציפינו ל-1.")
        hout = hout.replace(HTML_MUTATE_HELPER_ANCHOR, HTML_MUTATE_HELPER)
        print("  ✓ admin.html: העוזר mutate()")
        for name, old, new in HTML_PATCHES:
            if hout.count(old) != 1:
                _fail(f"admin.html / {name}: נמצאו {hout.count(old)} התאמות, ציפינו ל-1.")
            hout = hout.replace(old, new)
            print(f"  ✓ admin.html: {name}")
        if "persist()" not in hout:
            _fail("admin.html: persist() נעלם לגמרי — משהו לא צפוי.")
    else:
        print("  · admin.html כבר מכיל mutate() — מדולג")

    if a.check:
        print("\n✓ הכול מתאים ועובר קומפילציה. לא שונה כלום (--check).")
        return

    stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    if not already_main:
        shutil.copy2(main_py, f"{main_py}.bak-mutate-{stamp}")
        main_py.write_text(mout, encoding="utf-8")
    if not already_html:
        shutil.copy2(admin, f"{admin}.bak-mutate-{stamp}")
        admin.write_text(hout, encoding="utf-8")

    print(f"\n✓ הוחל. גיבויים עם החותמת {stamp}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
