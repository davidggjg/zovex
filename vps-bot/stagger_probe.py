#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stagger_probe — מוכיח או מפריך את מנעול 2 השניות, בלי לשנות כלום.

## השאלה

בקוד יש:

    STREAM_START_STAGGER = 2.0
    async def _stagger_new_stream():
        async with _stream_start_lock:      # מנעול גלובלי אחד
            wait = (_last_stream_start + 2.0) - now
            if wait > 0: await asyncio.sleep(wait)

ו-stream_from_channel פותחת בקריאה אליו. אם זה באמת מה שקורה, **כל** בקשת
/stream ממתינה עד שיעברו שתי שניות מאז הקודמת — של כל הצופים יחד.

מדידה סדרתית לא יכולה להכריע את זה: היא מראה "בערך 2 שניות לפתיחה", וזה
מסתדר גם עם מנעול וגם עם "טלגרם פשוט איטי". צריך ניסוי שמפריד ביניהם.

## הניסוי

יורים N פתיחות **באותו רגע**, ומודדים מתי כל אחת חזרה.

  • **יש מנעול** → הזמנים יוצאים במדרגות של 2 שניות: 0.3, 2.3, 4.3, 6.3.
    ההפרש בין פתיחות סמוכות יהיה ~2.0 בעקביות. זו חתימה שאי אפשר לטעות
    בה, כי שום עומס רשת לא מייצר מדרגות קבועות ומדויקות כאלה.
  • **אין מנעול** → כולן חוזרות בערך יחד, וההפרשים אקראיים.

הבדיקה משתמשת בבקשת Range של בייט אחד, כלומר לא מורידה כלום, ולא משנה
שום הגדרה ולא מפעילה שום דבר מחדש. אפשר להריץ על שרת חי בזמן שצופים
צופים.

    python3 stagger_probe.py            # 5 פתיחות במקביל
    python3 stagger_probe.py --n 8
"""
import argparse, json, os, random, statistics, sys, threading, time
import urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit

UA = "zovex-stagger/1"


def rewrite_origin(url, origin):
    p, o = urlsplit(url), urlsplit(origin)
    return urlunsplit((o.scheme, o.netloc, p.path, p.query, p.fragment))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="כמה פתיחות במקביל")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--rounds", type=int, default=2,
                    help="כמה סבבים (סבב שני מאשר שזה לא מקרי)")
    a = ap.parse_args()

    local = "http://127.0.0.1:" + os.environ.get("PORT", "8000")
    try:
        with urllib.request.urlopen(local + "/content/lite", timeout=60) as r:
            catalog = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        sys.exit(f"לא הצלחתי למשוך את הקטלוג: {e}")

    cands = [(str(m.get("title") or "?"),
              rewrite_origin((m.get("video_url") or "").strip(), local))
             for m in catalog
             if not m.get("is_live") and "/stream/" in str(m.get("video_url") or "")]
    if len(cands) < a.n:
        sys.exit("אין מספיק כותרים עם קישור /stream.")

    print(f"{a.n} פתיחות בו-זמנית · {a.rounds} סבבים · בקשת בייט אחד לכל אחת")
    print("אם יש מנעול גלובלי של 2ש — ההפרשים יהיו ~2.0 בעקביות\n")

    all_gaps, firsts, lasts = [], [], []
    for rnd in range(1, a.rounds + 1):
        random.shuffle(cands)
        items = cands[:a.n]
        results = [None] * a.n
        barrier = threading.Barrier(a.n)

        def one(i, url):
            # barrier: כל החוטים ממתינים ומשתחררים באותו רגע. בלי זה
            # ההפרשים שנמדוד יהיו רק הפרשי ההפעלה של החוטים עצמם.
            try:
                barrier.wait(timeout=30)
            except Exception:
                pass
            t = time.time()
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA, "Range": "bytes=0-0"})
                with urllib.request.urlopen(req, timeout=a.timeout) as r:
                    r.read(1)
                results[i] = (time.time() - t, None)
            except Exception as e:
                results[i] = (time.time() - t, type(e).__name__)

        ths = [threading.Thread(target=one, args=(i, u), daemon=True)
               for i, (_t, u) in enumerate(items)]
        for th in ths:
            th.start()
        for th in ths:
            th.join(timeout=a.timeout + 20)

        done = sorted((r[0], items[i][0], r[1])
                      for i, r in enumerate(results) if r)
        print(f"── סבב {rnd} ──")
        prev = None
        gaps = []
        for dt, title, err in done:
            gap = "" if prev is None else f"  (+{dt - prev:.2f})"
            if prev is not None:
                gaps.append(dt - prev)
            prev = dt
            print(f"  {dt:7.2f}ש{gap:12}  {title[:30]}"
                  + (f"  ✗ {err}" if err else ""))
        all_gaps += gaps
        if done:
            firsts.append(done[0][0])
            lasts.append(done[-1][0])
        if rnd < a.rounds:
            print()
            time.sleep(5)

    print("\n── פסק דין ──")
    if not all_gaps:
        print("  לא התקבלו מספיק תוצאות.")
        return
    med = statistics.median(all_gaps)
    # גרסה ראשונה דרשה שהמרווחים ייפלו בטווח צר סביב 2.0, וזו הייתה דרישה
    # שגויה: המנעול קובע מרווח **מזערי**, ולכן פתיחה שעבודתה האמיתית ארכה
    # יותר מכך כבר סיפקה את ההמתנה של הבאה והמרווח יוצא גדול יותר. על
    # נתונים אמיתיים (מרווחים 1.44–3.26 סביב חציון 2.14) היא הכריזה "לא
    # מכריע" על מה שהוא תור ברור. מה שמעיד על תור הוא **הפרישה**: בקשות
    # שנורו יחד יוצאות בזו אחר זו, והאחרונה מסיימת אחרי ~מרווח×(N-1).
    spread = statistics.median(lasts) if lasts else 0.0
    first = statistics.median(firsts) if firsts else 0.0
    print(f"  הפרש חציוני בין פתיחות סמוכות: {med:.2f}ש")
    print(f"  הפתיחה הראשונה (בלי תור לפניה): {first:.2f}ש")
    print(f"  האחרונה מתוך {a.n} שנורו יחד:      {spread:.2f}ש")
    print()
    if med >= 1.0 and spread >= med * (a.n - 1) * 0.7:
        print(f"  ✅ יש תור. {a.n} בקשות שנורו באותו רגע יצאו בזו אחר זו,")
        print(f"     והאחרונה סיימה אחרי {spread:.1f}ש. בלי תור הן היו חוזרות יחד.")
        print(f"     העלות האמיתית של פתיחה היא {first:.2f}ש — כל השאר המתנה.")
        print()
        print("     זה STREAM_START_STAGGER: מנעול גלובלי אחד, ולכן כל צופה")
        print("     נוסף מוסיף השהיה לכל מי שמגיע אחריו, בכל בקשת range.")
        print()
        print("  אפשר לכבות בלי לגעת בקוד — הערך נקרא ממשתנה סביבה:")
        print("     STREAM_START_STAGGER=0.25")
    elif med < 0.5 and spread < 1.5:
        print("  ❌ אין תור. הפתיחות יצאו כמעט יחד, כלומר ההשהיה לא")
        print("     מגיעה מ-_stagger_new_stream וההשערה הזאת מתה.")
    else:
        print(f"  לא מכריע: מרווח חציוני {med:.2f}ש, האחרונה ב-{spread:.2f}ש.")
        print("  נסה --n 8 — ככל שיש יותר בקשות, תור בולט יותר מרעש.")


if __name__ == "__main__":
    main()
