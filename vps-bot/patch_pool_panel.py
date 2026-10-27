#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# הפאנל מציג "bot_0" וזנב טוקן — ואי אפשר לדעת איזה בוט זה בערוץ.
#
# ## הבעיה המעשית
#
# בערוץ מופיעים הבוטים לפי ה-@ שלהם. בפאנל הם מופיעים כ-bot_0, bot_1 —
# שמות שנגזרים מהסדר בקובץ הטוקנים ואין להם שום קשר למה שרואים בטלגרם.
# התוצאה: אי אפשר להצליב. אם מישהו הוסיף בוטים לערוץ בלי למסור טוקנים,
# אין דרך לדעת מי מהם מוכר ומי לא, ולכן אי אפשר לנקות את רשימת האדמינים.
#
# ## המידע כבר קיים
#
# ‎/pool/list‎ מחזיר ‎who‎ (ה-@) ו-‎uid‎ לכל בוט מאז שנוספו. הפאנל פשוט לא
# הציג אותם.
#
# ## מה נוסף
#
#   · ה-‎@‎ בשורה הראשית, במקום שם פנימי חסר משמעות
#   · המזהה המספרי — לא משתנה גם אם ה-@ מוחלף
#   · **המהירות הנמדדת** — בלי זה אפשר לזהות בוט אבל לא לדעת אם הוא
#     שווה את מקומו. נמדד פער של פי 85 בין בוטים, אז זו השאלה האמיתית
#     כשמחליטים את מי להסיר
#   · סימון אדום לבוט שאינו מזהה את ערוץ התוכן (‎peer_ok=false‎) —
#     הוא "פעיל" אבל חסר תועלת לחלוטין
#
# ה-@ והמזהה מסומנים ‎user-select:all‎ כדי שלחיצה אחת תבחר אותם להעתקה.
#
#   python3 patch_pool_panel.py [נתיב ל-main.py] [נתיב ל-admin.html]
#   python3 patch_pool_panel.py --revert
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
MARK = "pool_panel_who"

# ── שרת: המהירות הנמדדת מצטרפת לתשובה ──────────────────────────────────────
OLD_SRV = '''            "kind": b.get("kind", "bot"),
            "token_tail": (b.get("token") or "")[-6:],'''
NEW_SRV = '''            "kind": b.get("kind", "bot"),
            # [pool_panel_who] המהירות הנמדדת. בלעדיה הפאנל מזהה בוט אבל
            # לא אומר אם הוא שווה את מקומו — ונמדד פער של פי 85 ביניהם.
            "speed": (round(b["speed"], 2)
                      if b.get("speed") is not None else None),
            "token_tail": (b.get("token") or "")[-6:],'''

# ── פאנל: שורה שאפשר להצליב מולה את רשימת האדמינים בערוץ ───────────────────
OLD_UI = '''    $("poolList").innerHTML=d.bots.map(b=>`<div class="item">
      <div class="meta"><div class="t">${b.kind==="user"?"👤":"🤖"} ${esc(b.name)} ${b.status==="פעיל"?'<span class="pill" style="background:#e6f9ec;color:#1a7f37">פעיל</span>':'<span class="pill" style="background:#fff4e5;color:#b26a00">מתקרר</span>'}</div>
      <div class="s">${b.kind==="user"?"חשבון":"בוט"} · …${esc(b.token_tail||"")}</div></div>
      <button class="mini gray" onclick="removePoolBot('${esc(b.name)}')">הסר</button></div>`).join("");'''

NEW_UI = '''    // [pool_panel_who] ה-@ בשורה הראשית. בערוץ הבוטים מופיעים לפי ה-@
    // שלהם, ו-bot_0 הוא שם פנימי שנגזר מהסדר בקובץ הטוקנים — בלי ה-@
    // אי אפשר להצליב בין מי שרשום בערוץ למי שיש לנו טוקן עבורו.
    $("poolList").innerHTML=d.bots.map(b=>{
      const who = b.who ? esc(b.who) : "— אין @ —";
      const hasSpeed = (typeof b.speed === "number");
      const sp = hasSpeed ? b.speed.toFixed(2)+" MB/s" : "טרם נמדד";
      // 0.6 MB/s: סרט 4GB בשעתיים צורך ~0.55, כלומר מתחת לזה הבוט אינו
      // מחזיק אפילו צופה אחד של התוכן הכבד בקטלוג.
      const slow = hasSpeed && b.speed < 0.6;
      const pill = b.status==="פעיל"
        ? '<span class="pill" style="background:#e6f9ec;color:#1a7f37">פעיל</span>'
        : '<span class="pill" style="background:#fff4e5;color:#b26a00">מתקרר</span>';
      const bad = b.peer_ok ? "" :
        ' <span class="pill" style="background:#ffe5e5;color:#b00020">לא מזהה ערוץ</span>';
      return `<div class="item">
      <div class="meta">
        <div class="t">${b.kind==="user"?"👤":"🤖"} <span style="user-select:all">${who}</span> ${pill}${bad}</div>
        <div class="s">${esc(b.name)} · מזהה <span style="user-select:all">${b.uid||"?"}</span>
          · <b style="color:${slow?"#b26a00":(hasSpeed?"#1a7f37":"#888")}">${sp}</b>
          · …${esc(b.token_tail||"")}</div></div>
      <button class="mini gray" onclick="removePoolBot('${esc(b.name)}')">הסר</button></div>`;
    }).join("");'''


def main():
    if REVERT:
        d = os.path.dirname(P) or "."
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_poolpanel_")), reverse=True)
        if bak:
            shutil.copy(os.path.join(d, bak[0]), P)
            print(f"✓ main.py שוחזר מ-{bak[0]}")
        hb = H + ".before_poolpanel"
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

    if MARK not in s and s.count(OLD_SRV) != 1:
        sys.exit(f"❌ הקטע ב-main.py לא נמצא בדיוק פעם אחת "
                 f"({s.count(OLD_SRV)}). לא נגעתי בכלום.")
    if MARK not in h and h.count(OLD_UI) != 1:
        sys.exit(f"❌ הקטע ב-admin.html לא נמצא בדיוק פעם אחת "
                 f"({h.count(OLD_UI)}). לא נגעתי בכלום.")

    d = os.path.dirname(P) or "."
    if MARK not in s:
        bak = f"{d}/main_before_poolpanel_{time.strftime('%Y%m%d-%H%M%S')}.py"
        shutil.copy(P, bak)
        io.open(P, "w", encoding="utf-8").write(s.replace(OLD_SRV, NEW_SRV, 1))
        try:
            py_compile.compile(P, doraise=True)
        except Exception as e:
            shutil.copy(bak, P)
            sys.exit(f"❌ main.py לא עובר קומפילציה — שוחזר.\n   {e}")
        print(f"✓ main.py הוחל. גיבוי: {bak}")

    if MARK not in h:
        shutil.copy(H, H + ".before_poolpanel")
        io.open(H, "w", encoding="utf-8").write(h.replace(OLD_UI, NEW_UI, 1))
        print(f"✓ admin.html הוחל. גיבוי: {H}.before_poolpanel")

    print("  כל בוט מציג עכשיו @, מזהה, מהירות, וסימון אם אינו מזהה ערוץ")


if __name__ == "__main__":
    main()
