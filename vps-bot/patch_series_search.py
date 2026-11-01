#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# בחירת סדרה בפאנל: גלילה דרך מאות שמות.
#
# בהוספת פרק צריך לבחור את הסדרה מרשימה נגללת שמכילה **348 סדרות**
# (נמדד בקטלוג). מציאת אחת בתוכה היא גלילה ארוכה, ובטלפון זה גרוע עוד
# יותר.
#
# ## התיקון
#
# תיבת חיפוש מעל הבורר, שמסננת את האפשרויות תוך כדי הקלדה.
#
# הבורר עצמו נשאר ‎<select id="f_existing">‎ ולא הוחלף ברכיב אחר —
# ‎pickExisting()‎, ‎refreshDerived()‎ וכל מי שקורא ‎.value‎ ממשיכים
# לעבוד בדיוק כמו קודם. רק רשימת האפשרויות מסוננת.
#
# הבחירה הנוכחית נשמרת גם כשהיא אינה תואמת לסינון: אחרת הקלדה אחרי
# בחירה הייתה מאפסת את הטופס בלי שהמשתמש ביקש.
#
#   python3 patch_series_search.py [נתיב ל-admin.html]
#   python3 patch_series_search.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import shutil
import sys

H = "/opt/zovex-bot/admin.html"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    H = args[0]
REVERT = "--revert" in sys.argv
MARK = "seriesSearch"
BAK = H + ".before_seriessearch"

OLD_UI = '''<select id="f_existing" onchange="pickExisting()"><option value="">— סדרה חדשה —</option></select>'''
NEW_UI = '''<input id="f_existing_q" placeholder="🔎 חפש סדרה…" oninput="filterSeries()"
       style="margin-bottom:6px">
<select id="f_existing" onchange="pickExisting()"><option value="">— סדרה חדשה —</option></select>
<div id="f_existing_n" class="muted" style="font-size:12px;margin-top:4px"></div>'''

OLD_JS = '''  const sm=seriesMap(); const sel=$("f_existing");
  sel.innerHTML='<option value="">— סדרה חדשה —</option>'+Object.keys(sm).sort().map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join("");
}'''
NEW_JS = '''  // [seriesSearch] הרשימה נשמרת, והבורר מצויר דרך הסינון.
  _allSeries = Object.keys(seriesMap()).sort();
  filterSeries();
}

// [seriesSearch] סינון רשימת הסדרות לפי הקלדה.
//
// נמדד: 348 סדרות בקטלוג. בחירה מרשימה נגללת בגודל כזה היא גלילה
// ארוכה, ובטלפון גרועה במיוחד.
//
// הבורר נשאר אותו <select> ולא הוחלף — pickExisting(), refreshDerived()
// וכל מי שקורא .value ממשיכים לעבוד. רק האפשרויות מסוננות.
let _allSeries = [];
function filterSeries(){
  const sel=$("f_existing"); if(!sel) return;
  const q=($("f_existing_q")?.value||"").trim().toLowerCase();
  const cur=sel.value;
  const hit = q ? _allSeries.filter(n=>n.toLowerCase().includes(q)) : _allSeries;
  // הבחירה הנוכחית נשארת ברשימה גם כשאינה תואמת לסינון. בלי זה הקלדה
  // אחרי בחירה הייתה מאפסת את הטופס בלי שהמשתמש ביקש.
  const list = (cur && !hit.includes(cur)) ? [cur, ...hit] : hit;
  sel.innerHTML='<option value="">— סדרה חדשה —</option>'+
    list.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join("");
  sel.value=cur;
  const n=$("f_existing_n");
  if(n) n.textContent = q
    ? `${hit.length} מתוך ${_allSeries.length} סדרות`
    : `${_allSeries.length} סדרות`;
}'''


def main():
    if REVERT:
        if not os.path.exists(BAK):
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(BAK, H)
        print("✓ שוחזר")
        return
    try:
        h = io.open(H, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {H}: {e}")
    if MARK in h:
        print("✓ כבר מתוקן — מדלג")
        return
    for i, old in enumerate((OLD_UI, OLD_JS), 1):
        if h.count(old) != 1:
            sys.exit(f"❌ קטע {i} נמצא {h.count(old)} פעמים. לא נגעתי בכלום.")
    shutil.copy(H, BAK)
    h = h.replace(OLD_UI, NEW_UI, 1).replace(OLD_JS, NEW_JS, 1)
    io.open(H, "w", encoding="utf-8").write(h)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print("  תיבת חיפוש מעל בורר הסדרות")


if __name__ == "__main__":
    main()
