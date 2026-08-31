#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בודק אם לולאת האירועים של השרת נתקעת — מבחוץ, בלי לגעת בקוד.

למה זה השאלה הפתוחה: התיעוד של Pyrogram מונה "blocking the event loop for
too long" ו-"running too many clients at once" כשתי סיבות ישירות לשגיאות
השקע שאנחנו רואים. אצלנו 22 קליינטים, עשרות חיבורי מדיה, רלֵיי HLS,
ffmpeg וכל בקשות ה-HTTP חולקים לולאה אחת. Pyrogram שולח פינג כל 5 שניות
כדי להחזיק חיבור פתוח; אם הלולאה חסומה כמה שניות, הפינג מאחר וטלגרם סוגר
את החיבור מצדו. זה יסביר גם למה החיבורים מתים מלכתחילה וגם למה זה מצטבר
לאורך שעות בלי קשר למספר הצופים.

איך מודדים בלי לגעת בשרת: /ping הוא הנתיב הזול ביותר — הוא לא נוגע
בטלגרם ולא בדיסק, ולכן כל עיכוב בתשובה שלו הוא עיכוב של הלולאה עצמה
ולא של העבודה. דוגמים בתדירות גבוהה ומחפשים קפיצות.

הפלט אינו ממוצע אלא זנב: ממוצע מסתיר בדיוק את מה שמחפשים. תקיעה של
12 שניות פעם בדקה נעלמת בממוצע ומופיעה במקסימום.

    python3 loop_lag.py                    # 10 דקות
    python3 loop_lag.py --minutes 120      # ריצה ארוכה ברקע
    python3 loop_lag.py --every 0.25       # תדירות דגימה
"""
import argparse, json, pathlib, statistics, sys, time
import urllib.request, urllib.error

URL = "http://127.0.0.1:8000/ping"
SPIKES = pathlib.Path("/opt/zovex-bot/loop_lag_spikes.log")
# מעל זה נחשב "תקיעה": פינג של Pyrogram יוצא כל 5 שניות, ולכן חסימה של
# שנייה שלמה כבר מסוכנת, וחסימה של חמש כמעט מבטיחה חיבור אבוד.
SPIKE = 1.0


def sample(timeout):
    t0 = time.time()
    try:
        with urllib.request.urlopen(URL, timeout=timeout) as r:
            r.read(200)
        return time.time() - t0, None
    except Exception as e:
        return time.time() - t0, type(e).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--every", type=float, default=0.25)
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args()

    print(f"בודקת {URL} כל {a.every}ש למשך {a.minutes:.0f} דקות")
    print(f"כל תשובה שלוקחת יותר מ-{SPIKE:.0f}ש נרשמת כתקיעה\n", flush=True)

    lat, errs, spikes = [], {}, []
    t0 = time.time()
    end = t0 + a.minutes * 60
    next_report = t0 + 60
    while time.time() < end:
        d, err = sample(a.timeout)
        if err:
            errs[err] = errs.get(err, 0) + 1
        else:
            lat.append(d)
            if d >= SPIKE:
                stamp = time.strftime("%H:%M:%S")
                spikes.append((stamp, d))
                line = f"{stamp}  תקיעה {d:.2f}ש"
                print("  " + line, flush=True)
                try:
                    with SPIKES.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass
        if time.time() >= next_report:
            next_report += 60
            if lat:
                s = sorted(lat)
                print(f"  [{(time.time()-t0)/60:.0f} דק'] "
                      f"חציון {s[len(s)//2]*1000:.0f}ms · "
                      f"גרוע {s[-1]:.2f}ש · תקיעות {len(spikes)}", flush=True)
        time.sleep(a.every)

    print("\n" + "=" * 56)
    if not lat:
        print("לא התקבלה אף תשובה. שגיאות: " +
              " · ".join(f"{k}×{v}" for k, v in errs.items()))
        sys.exit(1)

    s = sorted(lat)
    def pct(p):
        return s[min(len(s) - 1, int(len(s) * p))]

    print(f"דגימות: {len(lat)}  ·  {(time.time()-t0)/60:.1f} דקות")
    print(f"  חציון      {pct(0.50)*1000:8.0f} ms")
    print(f"  אחוזון 95  {pct(0.95)*1000:8.0f} ms")
    print(f"  אחוזון 99  {pct(0.99)*1000:8.0f} ms")
    print(f"  הגרוע ביותר{s[-1]*1000:8.0f} ms")
    if errs:
        print("  שגיאות: " + " · ".join(f"{k}×{v}" for k, v in errs.items()))

    print(f"\nתקיעות מעל {SPIKE:.0f}ש: {len(spikes)}")
    for stamp, d in sorted(spikes, key=lambda x: -x[1])[:10]:
        print(f"   {stamp}  {d:6.2f}ש")

    print()
    worst = s[-1]
    if worst < 0.3:
        print("✅ הלולאה חלקה. היא *אינה* הסיבה שהחיבורים מתים —")
        print("   צריך לחפש במקום אחר.")
    elif worst < 2.0:
        print(f"↔️  עיכוב מרבי {worst:.1f}ש — לא נעים אבל כנראה לא מספיק")
        print("   כדי להפיל פינג של 5 שניות. חשוד חלש.")
    else:
        print(f"❌ הלולאה נחסמת עד {worst:.1f}ש.")
        print("   פינג של Pyrogram יוצא כל 5 שניות; חסימה כזאת מאחרת אותו")
        print("   וטלגרם סוגר את החיבור מצדו. זו ההסבר לחיבורים המתים,")
        print("   והפתרון הוא להוציא עבודה מהלולאה — לא עוד שכבת החייאה.")
    print(f"\nהתקיעות נשמרו גם ב-{SPIKES}")


if __name__ == "__main__":
    main()
