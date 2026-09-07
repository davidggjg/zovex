#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
פותח CORS על מסלול תיקון-הקול (/vh ו-/fs), כמו שכבר פתוח על הריליי.

## למה באתר זה עובד ובאפליקציה לא

זו בדיוק השאלה שדוד שאל, והיא זו שהובילה לתשובה. נמדד מול השרת החי:

    /hls-relay/…/index.m3u8   access-control-allow-origin: *      ← עובד באפליקציה
    /vh/…/index.m3u8          (אין access-control-allow-origin)   ← לא עובד

באתר אין CORS בכלל: הדף והמדיה יושבים שניהם על zovex.duckdns.org, זו אותה
מקור (same-origin) ואף אחד לא בודק כלום. לכן באתר זה "עובד טיל".

באפליקציה הנגן הוא WebView שנטען מ-HTML בזיכרון, בלי baseUrl — ולכן ה-origin
שלו הוא המחרוזת ‎"null". כל משיכה של m3u8 או מקטע ‎.ts היא cross-origin, וב-CORS
היא נחסמת אם אין ‎Access-Control-Allow-Origin בתשובה. Shaka נכשל, hls.js
נכשל אחריו, ומה שהצופה רואה זה ספינר שלא נגמר.

וזה גם מסביר למה ‎/stream‎ הרגיל דווקא עובד באפליקציה: שם זה תג ‎<video src>‎
פשוט, ולתג וידאו בלי crossorigin אין דרישת CORS בכלל. רק MSE — כלומר HLS —
מושך דרך fetch, ורק הוא נחסם.

## למה זה נפל בין הכיסאות

‎CORS_MEDIA‎ כבר קיים בקובץ, ונוסף בדיוק מהסיבה הזאת ("היא שברה שידורים חיים
באפליקציה"). הוא הוחל על ‎/relay‎ ו-‎/stream‎. מסלולי ‎/vh‎ ו-‎/fs‎ נוספו אחר כך,
ולא קיבלו אותו.

## אבטחה

‎ACAO: *‎ כאן זהה למה שכבר מוגש על הריליי: תוכן מדיה ציבורי, בלי עוגיות ובלי
הרשאות. הקישורים עצמם עדיין חתומים (‎exp/sig‎) ועדיין עוברים את ‎check_hotlink‎.
נעילת ה-CORS של ה-API — זה שמחזיק נתוני משתמשים — לא נוגעים בה.

    python3 fix_vh_cors.py --check     # לא נוגע בכלום
    python3 fix_vh_cors.py             # מחיל, עם גיבוי
    python3 fix_vh_cors.py --revert    # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

# (תיאור, לפני, אחרי)
PATCHES = [
    ("‎/fs — הקובץ עם ה-moov בהתחלה",
     '''    headers = {"Accept-Ranges": "bytes",
               "Content-Length": str(end - start + 1),
               "Cache-Control": "no-store"}''',
     '''    headers = {"Accept-Ranges": "bytes",
               "Content-Length": str(end - start + 1),
               "Cache-Control": "no-store", **CORS_MEDIA}'''),

    ("‎/vh — הפלייליסט",
     '''    return Response("\\n".join(lines) + "\\n",
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store"})''',
     '''    # CORS_MEDIA: ה-WebView באפליקציה מריץ את הנגן מ-HTML בלי baseUrl,
    # ולכן ה-origin שלו הוא "null" וכל משיכת m3u8/מקטע היא cross-origin.
    # בלי ACAO היא נחסמת, Shaka ו-hls.js נכשלים, והצופה רואה ספינר אינסופי.
    # באתר זה לא נראה כי שם הדף והמדיה על אותו מקור.
    return Response("\\n".join(lines) + "\\n",
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store", **CORS_MEDIA})'''),

    ("‎/vh — המקטעים",
     '''    return StreamingResponse(gen(), media_type="video/mp2t",
                             headers={"Cache-Control": "no-store"})''',
     '''    return StreamingResponse(gen(), media_type="video/mp2t",
                             headers={"Cache-Control": "no-store",
                                      **CORS_MEDIA})'''),
]

MARK = '"Cache-Control": "no-store", **CORS_MEDIA}'


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-vhcors-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return
    if "CORS_MEDIA = {" not in src:
        _fail("CORS_MEDIA לא קיים בקובץ — הקובץ לא מה שציפינו לו.")

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            _fail(f"{name}: נמצאו {n} התאמות, ציפינו ל-1. לא נוגעים.")
        out = out.replace(old, new)
        print(f"  ✓ {name}")

    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if "--check" in sys.argv:
        print("\n✓ שלושת הפאצ'ים מתאימים והתוצאה עוברת קומפילציה. "
              "לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-vhcors-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"\n✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
