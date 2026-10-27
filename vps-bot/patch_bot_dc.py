#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# פער של פי 85 בין הבוטים — למה?
#
# ## מה נמדד
#
#   @Hrxhxbot     6.78 MB/s
#   @Zovfxhbot    1.86
#   @Movergbot    0.25
#   @Zfugbbot     0.08
#   @Hrjg64zobot  timeout
#
# אותו קובץ, אותו רגע, אותם 4 חיבורים לכל בוט. כלומר ההבדל אינו בעומס
# ואינו בתצורה — הוא תכונה של הבוט עצמו.
#
# ## שתי השערות מהשטח
#
# מפעיל אחר של אותה ארכיטקטורה (tgdrive/teldrive, דיון 183) דיווח על
# אותו תסמין בדיוק: "חלק מהבוטים מהירים וחלק איטיים, נראה אקראי".
# הפתרון שלו היה לזהות את האיטיים ולהוציא אותם, והחשד שלו היה **המיקום
# של הבוט**. באותו דיון עולה גם ש**בוט חדש מוגבל להעברות** לתקופה.
#
# ## מה זה מוסיף
#
# ‎/speedtest/bots‎ מודד תפוקה אבל לא אומר למה. שני שדות הופכים אותו
# לאבחנה:
#
#   · ‎home_dc‎  — ה-DC שבו הבוט עצמו רשום
#   · ‎file_dc‎  — ה-DC שבו הקובץ יושב
#   · ‎cross_dc‎ — האם הבוט נאלץ לייצא הרשאה ל-DC אחר
#
# אם כל האיטיים חולקים ‎home_dc‎ אחד, או שכולם ‎cross_dc‎ — זו הסיבה,
# והתיקון הוא להחליף אותם בבוטים מה-DC הנכון. אם אין קשר — הסיבה אחרת
# (גיל הבוט, חניקה פר-טוקן), ונחפש שם במקום לנחש.
#
# ## בטיחות
#
# קריאה בלבד, בנקודת קצה שממילא מוגבלת ל-localhost. אינו משנה התנהגות,
# אינו נוגע בבריכה, ואינו פותח חיבורים נוספים.
#
#   python3 patch_bot_dc.py [נתיב ל-main.py]
#   python3 patch_bot_dc.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "home_dc_probe"

OLD_ROW = '''            dc_id, location = _file_location(media)
            sessions, _gen = await get_media_session_pool_gen(
                bot["client"], bot["name"], dc_id, max(1, STREAM_MEDIA_CONNS))'''
NEW_ROW = '''            dc_id, location = _file_location(media)
            # [home_dc_probe] מאיפה הבוט, ומאיפה הקובץ.
            #
            # המדידה הראתה פער של פי 85 בין בוטים על אותו קובץ באותו רגע.
            # אם האיטיים חולקים DC אחד, או שכולם חוצי-DC, זו הסיבה —
            # ואז מחליפים אותם במקום לכוונן פרמטרים שלא קשורים.
            row["file_dc"] = dc_id
            try:
                row["home_dc"] = await bot["client"].storage.dc_id()
            except Exception:
                row["home_dc"] = None
            row["cross_dc"] = (row["home_dc"] is not None
                               and row["home_dc"] != dc_id)
            sessions, _gen = await get_media_session_pool_gen(
                bot["client"], bot["name"], dc_id, max(1, STREAM_MEDIA_CONNS))'''

OLD_SUM = '''    good = [r["mb_per_sec"] for r in out if r.get("mb_per_sec")]'''
NEW_SUM = '''    good = [r["mb_per_sec"] for r in out if r.get("mb_per_sec")]
    # [home_dc_probe] פילוח לפי DC — התשובה לשאלה "האם זו בעיית מיקום".
    _by_dc = {}
    for r in out:
        k = str(r.get("home_dc"))
        e = _by_dc.setdefault(k, {"בוטים": 0, "מהירויות": []})
        e["בוטים"] += 1
        if r.get("mb_per_sec"):
            e["מהירויות"].append(r["mb_per_sec"])
    for k, e in _by_dc.items():
        sp = e.pop("מהירויות")
        e["חציון"] = sorted(sp)[len(sp) // 2] if sp else 0
        e["כשלו"] = e["בוטים"] - len(sp)'''

OLD_RET = '''    return {"message_id": msg_id, "conns_per_bot": STREAM_MEDIA_CONNS,
            "bots": out,'''
NEW_RET = '''    return {"message_id": msg_id, "conns_per_bot": STREAM_MEDIA_CONNS,
            "bots": out,
            "לפי_DC": _by_dc,'''

PAIRS = [(OLD_ROW, NEW_ROW), (OLD_SUM, NEW_SUM), (OLD_RET, NEW_RET)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_botdc_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return

    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return

    for i, (old, _) in enumerate(PAIRS, 1):
        n = s.count(old)
        if n != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} לא נמצא בדיוק פעם אחת "
                     f"({n}). לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_botdc_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)

    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")

    print(f"✓ הוחל. גיבוי: {bak}")
    print("  /speedtest/bots מציג עכשיו home_dc, file_dc, cross_dc ופילוח")


if __name__ == "__main__":
    main()
