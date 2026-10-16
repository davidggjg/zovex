#!/usr/bin/env python3
# מלמד את כפתור "העבר דרך השרת שלנו" בפאנל לזהות כתובת Emby.
#
# ## למה
#
# הכפתור ממיר כתובת לרלֵיי בשכתוב טקסט בלבד:
#     https://host/path  →  https://zovex.duckdns.org/hls-relay/host/path
#
# על כתובת Emby זה עושה שני דברים רעים:
#   1. הכתובת הארוכה מכילה X-Emby-Token אישי, והוא נשמר בפאנל ויוצא החוצה
#      עם כל קישור ערוץ.
#   2. הכתובת מפנה ל-URL חתום עם חותמת-זמן שמתחלף כל כמה שעות, ולכן הקישור
#      השמור מת מעצמו.
#
# ## מה משתנה
#
# כשהכתובת מזוהה כ-Emby, הכפתור שולח אותה ל-/emby/register במקום לשכתב
# אותה. השרת שומר אותה אצלו, בודק מיד שהיא נפתרת, ומחזיר כתובת קבועה:
#     https://zovex.duckdns.org/emby/3073497/index.m3u8
# זו הכתובת שנשמרת בפאנל, והיא לא משתנה לעולם. ביום שהטוקן יתחלף — מדביקים
# כתובת ארוכה חדשה לאותו ערוץ, והקישור הקצר ממשיך לעבוד.
#
# כל שאר הכתובות ממשיכות בדיוק כמו קודם.
#
# הסקריפט אידמפוטנטי, ואם הפונקציה בקובץ החי נראית אחרת — הוא לא נוגע
# בכלום ואומר את זה.
#
#   python3 patch_emby_panel.py [נתיב ל-admin.html]
import io
import sys

P = sys.argv[1] if len(sys.argv) > 1 else "/opt/zovex-bot/admin.html"

OLD = """function relayifyUrl(){
  const el=$("l_url"), msg=$("relayMsg"); msg.style.color="#ff8a8a";
  let u; try{ u=new URL(el.value.trim()); }catch{ msg.textContent="קישור לא תקין"; return; }"""

NEW = """async function relayifyUrl(){
  const el=$("l_url"), msg=$("relayMsg"); msg.style.color="#ff8a8a";
  const raw=el.value.trim();
  let u; try{ u=new URL(raw); }catch{ msg.textContent="קישור לא תקין"; return; }
  // כתובת Emby: מכילה טוקן אישי, ומפנה לכתובת חתומה שמתחלפת כל כמה שעות.
  // אסור לשמור אותה כמו שהיא. השרת שומר אותה אצלו ומחזיר קישור קבוע.
  if(/\\/emby\\/videos\\/\\d+\\/master\\.m3u8/i.test(u.pathname) && /X-Emby-Token=/i.test(raw)){
    msg.style.color="#ffd27a"; msg.textContent="ממיר…";
    try{
      const nm=($("l_title")||{}).value||"";
      const r=await fetch("/emby/register",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({password:PASS,url:raw,name:nm})});
      const d=await r.json().catch(()=>({}));
      if(!r.ok) throw new Error(d.detail||("שגיאה "+r.status));
      el.value=d.url;
      msg.style.color=d.ok?"#8aff9e":"#ffd27a";
      msg.textContent=(d.replaced?"✓ עודכן · ":"✓ הומר · ")+(d.detail||"");
    }catch(e){ msg.style.color="#ff8a8a"; msg.textContent="ההמרה נכשלה: "+e.message; }
    return;
  }"""

MARK = "/emby/register"


def main():
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if MARK in s:
        print("✓ כבר מתוקן")
        return

    if s.count(OLD) != 1:
        sys.exit(
            f"❌ הפונקציה relayifyUrl ב-{P} לא נראית כמו שציפיתי "
            f"({s.count(OLD)} התאמות) — לא נגעתי בכלום.\n"
            f"   שלח לי את הפונקציה מהקובץ החי ואתאים את הטלאי.")

    bak = P + ".before_emby"
    io.open(bak, "w", encoding="utf-8").write(s)
    io.open(P, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1))
    print(f"✓ הוחל. גיבוי: {bak}")


if __name__ == "__main__":
    main()
