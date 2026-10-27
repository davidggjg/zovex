#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# "בלי טריילר" → מרכז "חסרים": טריילר, פוסטר, תיאור, ו-tmdb_id.
#
# ## למה
#
# הכרטיס הקיים עונה על שאלה אחת בלבד — למי אין טריילר. אבל חסרים גם
# תיאורים ופוסטרים, ואין שום מקום בפאנל שמראה אותם. התוצאה: אי אפשר
# לדעת כמה חסר, ולכן אי אפשר להחליט מה לתקן קודם.
#
# ‎tmdb_id‎ מקבל רשימה משלו כי הוא השורש: בלעדיו אין מאיפה למשוך תיאור,
# פוסטר או טריילר אוטומטית. פריט בלי מזהה הוא פריט שאף העשרה לא תעזור
# לו עד שמישהו יצמיד אותו ל-TMDB.
#
# ## מה נוסף
#
# ‎/panel/missing?kind=trailer|poster|desc|tmdb‎ — אותה לוגיקת קיבוץ של
# הכרטיס הקיים (סדרות מקובצות לפי שם; 424 פרקים של אותה סדרה אינם רשימת
# עבודה), אבל עם ארבעה סוגי חוסר. התשובה כוללת תמיד ספירה של **כל
# הארבעה**, כדי שהפאנל יציג את התמונה המלאה גם כשמסתכלים על רשימה אחת.
#
# ‎/panel/no-trailer‎ נשאר כפי שהוא: פאנל ישן שפתוח בדפדפן לא נשבר.
#
#   python3 patch_missing_panel.py [main.py] [admin.html]
#   python3 patch_missing_panel.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

args = [a for a in sys.argv[1:] if not a.startswith("--")]
P = args[0] if len(args) > 0 else "/opt/zovex-bot/main.py"
H = args[1] if len(args) > 1 else "/opt/zovex-bot/admin.html"
REVERT = "--revert" in sys.argv
MARK = "panel_missing"

# ── 1. השרת ────────────────────────────────────────────────────────────────
OLD_SRV = '''@api.get("/content/trailer/{item_id}")'''
NEW_SRV = '''@api.get("/panel/missing")
async def panel_missing(request: Request, password: str = "",
                        kind: str = "trailer"):
    """[panel_missing] מה חסר לכל פריט — טריילר, פוסטר, תיאור או tmdb_id.

    הכרטיס הקודם ענה רק על "למי אין טריילר". תיאורים ופוסטרים חסרים לא
    הופיעו בשום מקום, ולכן לא היה אפשר לדעת כמה חסר ומה לתקן קודם.

    ‎tmdb_id‎ הוא השורש: בלעדיו אין מאיפה למשוך תיאור, פוסטר או טריילר.
    לכן הוא מקבל רשימה משלו ולא נספר יחד עם השאר.
    """
    password = request.headers.get("x-panel-password") or password
    check_panel_password(request, password)
    kinds = ("trailer", "poster", "desc", "tmdb")
    if kind not in kinds:
        kind = "trailer"
    tdb = _load_trailers()

    def lacks(m, k):
        if k == "trailer":
            return not _has_trailer(m, tdb)
        if k == "poster":
            return not str(m.get("thumbnail_url") or "").strip()
        if k == "desc":
            return not str(m.get("description") or "").strip()
        return not m.get("tmdb_id")

    counts = {k: {"movies": 0, "series": 0} for k in kinds}
    seen_ser = {k: set() for k in kinds}
    movies, series = [], {}
    for m in load_content():
        if m.get("is_live"):
            continue
        sn = str(m.get("series_name") or "").strip()
        for k in kinds:
            if not lacks(m, k):
                continue
            if sn:
                seen_ser[k].add(sn)
            else:
                counts[k]["movies"] += 1
        if not lacks(m, kind):
            continue
        if sn:
            e = series.setdefault(sn, {"series_name": sn, "id": m.get("id"),
                                       "category": m.get("category"),
                                       "tmdb_id": m.get("tmdb_id"), "episodes": 0,
                                       "thumbnail_url": m.get("thumbnail_url")})
            e["episodes"] += 1
        else:
            movies.append({"id": m.get("id"), "title": m.get("title"),
                           "year": m.get("year"), "category": m.get("category"),
                           "tmdb_id": m.get("tmdb_id"),
                           "thumbnail_url": m.get("thumbnail_url")})
    for k in kinds:
        counts[k]["series"] = len(seen_ser[k])
    movies.sort(key=lambda x: str(x.get("title") or ""))
    ser = sorted(series.values(), key=lambda x: -x["episodes"])
    return JSONResponse({"kind": kind, "movies": movies, "series": ser,
                         "counts": counts})


@api.get("/content/trailer/{item_id}")'''

# ── 2. לשונית ──────────────────────────────────────────────────────────────
OLD_TAB = '''<button id="tab-notrailer" onclick="showTab('notrailer')">🎬 בלי טריילר</button>'''
NEW_TAB = '''<button id="tab-notrailer" onclick="showTab('notrailer')">🧩 חסרים</button>'''

# ── 3. הכרטיס ──────────────────────────────────────────────────────────────
OLD_PANE = '''    <h2>תוכן בלי טריילר</h2>
    <p class="muted">טריילר אוטומטי מגיע מ-TMDB ודורש <code>tmdb_id</code>. לתוכן
    ישראלי רבות אין שם טריילר גם כשהמזהה קיים. כאן מה שחסר — לוחצים «ערוך»,
    מדביקים קישור יוטיוב בשדה «קישור טריילר», ושומרים.</p>
    <p class="muted">סדרות מקובצות לפי שם: אחרי הזנת קישור בפרק אחד אפשר
    «עדכן טריילר לכל הסדרה» וזה מכסה את כל הפרקים.</p>
    <div class="row" style="margin-bottom:8px">
      <button class="mini" onclick="loadNoTrailer()">רענן</button>'''
NEW_PANE = '''    <h2>תוכן חסר</h2>
    <p class="muted">מה שאין לו טריילר, פוסטר או תיאור. לוחצים «ערוך»,
    משלימים בשדה המתאים, ושומרים.</p>
    <p class="muted"><b>בלי מזהה TMDB</b> הוא השורש: בלי המזהה אין מאיפה
    למשוך תיאור, פוסטר או טריילר אוטומטית. כדאי להתחיל משם.</p>
    <p class="muted">סדרות מקובצות לפי שם: אחרי הזנת קישור בפרק אחד אפשר
    «עדכן טריילר לכל הסדרה» וזה מכסה את כל הפרקים.</p>
    <div class="row" style="margin-bottom:8px;flex-wrap:wrap;gap:6px">
      <button class="mini" id="mk_trailer" onclick="setMissKind('trailer')">🎬 בלי טריילר</button>
      <button class="mini sec" id="mk_poster" onclick="setMissKind('poster')">🖼 בלי פוסטר</button>
      <button class="mini sec" id="mk_desc" onclick="setMissKind('desc')">📝 בלי תיאור</button>
      <button class="mini sec" id="mk_tmdb" onclick="setMissKind('tmdb')">🔗 בלי מזהה TMDB</button>
    </div>
    <div class="row" style="margin-bottom:8px">
      <button class="mini" onclick="loadNoTrailer()">רענן</button>'''

# ── 4. ה-JS ────────────────────────────────────────────────────────────────
OLD_JS = '''let _nt = null;
async function loadNoTrailer(){
  $("ntMsg").textContent="טוען…"; $("ntList").innerHTML="";
  try{
    // [fix_panel_pass_header] בכותרת ולא בכתובת — כתובת נרשמת ביומן של nginx
    const r=await fetch("/panel/no-trailer",{headers:{"X-Panel-Password":PASS}});
    if(!r.ok) throw new Error("שגיאה "+r.status);
    _nt=await r.json();
    $("ntMsg").innerHTML=`<b>${_nt.counts.movies}</b> סרטים ו-<b>${_nt.counts.series}</b> סדרות בלי טריילר`;
    renderNoTrailer();
  }catch(e){ $("ntMsg").innerHTML='<span class="err">'+e.message+'</span>'; }
}'''
NEW_JS = '''let _nt = null;
// [panel_missing] איזה סוג חוסר מוצג כרגע
let _missKind = "trailer";
const _missLabel = {trailer:"בלי טריילר", poster:"בלי פוסטר",
                    desc:"בלי תיאור", tmdb:"בלי מזהה TMDB"};
function setMissKind(k){
  _missKind = k;
  for(const t of ["trailer","poster","desc","tmdb"]){
    const b=$("mk_"+t); if(b) b.className = (t===k) ? "mini" : "mini sec";
  }
  loadNoTrailer();
}
async function loadNoTrailer(){
  $("ntMsg").textContent="טוען…"; $("ntList").innerHTML="";
  try{
    // [fix_panel_pass_header] בכותרת ולא בכתובת — כתובת נרשמת ביומן של nginx
    const r=await fetch("/panel/missing?kind="+encodeURIComponent(_missKind),
                        {headers:{"X-Panel-Password":PASS}});
    if(!r.ok) throw new Error("שגיאה "+r.status);
    _nt=await r.json();
    const c=_nt.counts||{};
    // סיכום כל הסוגים ולא רק המוצג: בלי זה אי אפשר להחליט מה לתקן קודם.
    const sum=["trailer","poster","desc","tmdb"].map(k=>{
      const x=c[k]||{movies:0,series:0};
      const on=(k===_missKind);
      return `<span style="${on?"font-weight:800":"opacity:.65"}">${_missLabel[k]}: `+
             `${x.movies}+${x.series}</span>`;
    }).join(" &nbsp;·&nbsp; ");
    $("ntMsg").innerHTML=sum+'<div class="muted" style="margin-top:4px;font-size:12px">'+
      'המספרים הם סרטים + סדרות</div>';
    renderNoTrailer();
  }catch(e){ $("ntMsg").innerHTML='<span class="err">'+e.message+'</span>'; }
}'''

PAIRS_SRV = [(OLD_SRV, NEW_SRV)]
PAIRS_H = [(OLD_TAB, NEW_TAB), (OLD_PANE, NEW_PANE), (OLD_JS, NEW_JS)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_missingpanel_")), reverse=True)
        if bak:
            shutil.copy(os.path.join(d, bak[0]), P)
            print(f"✓ main.py שוחזר מ-{bak[0]}")
        hb = H + ".before_missingpanel"
        if os.path.exists(hb):
            shutil.copy(hb, H)
            print("✓ admin.html שוחזר")
        if not bak and not os.path.exists(hb):
            sys.exit("❌ אין גיבוי לשחזר")
        return

    try:
        s = io.open(P, encoding="utf-8").read()
        h = io.open(H, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח: {e}")

    if MARK in s and MARK in h:
        print("✓ כבר מתוקן — מדלג")
        return

    if MARK not in s:
        for i, (old, _) in enumerate(PAIRS_SRV, 1):
            if s.count(old) != 1:
                sys.exit(f"❌ main.py קטע {i} נמצא {s.count(old)} פעמים. "
                         f"לא נגעתי בכלום.")
    if MARK not in h:
        for i, (old, _) in enumerate(PAIRS_H, 1):
            if h.count(old) != 1:
                sys.exit(f"❌ admin.html קטע {i} נמצא {h.count(old)} פעמים. "
                         f"לא נגעתי בכלום.")

    if MARK not in s:
        bak = f"{d}/main_before_missingpanel_{time.strftime('%Y%m%d-%H%M%S')}.py"
        shutil.copy(P, bak)
        out = s
        for old, new in PAIRS_SRV:
            out = out.replace(old, new, 1)
        io.open(P, "w", encoding="utf-8").write(out)
        try:
            py_compile.compile(P, doraise=True)
        except Exception as e:
            shutil.copy(bak, P)
            sys.exit(f"❌ main.py לא עובר קומפילציה — שוחזר.\n   {e}")
        print(f"✓ main.py הוחל. גיבוי: {bak}")

    if MARK not in h:
        shutil.copy(H, H + ".before_missingpanel")
        out = h
        for old, new in PAIRS_H:
            out = out.replace(old, new, 1)
        io.open(H, "w", encoding="utf-8").write(out)
        print(f"✓ admin.html הוחל. גיבוי: {H}.before_missingpanel")

    print("  /panel/missing?kind=trailer|poster|desc|tmdb")


if __name__ == "__main__":
    main()
