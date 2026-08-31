#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מודד נפילות חיבור לטלגרם *לצד* התעבורה האמיתית, באותו חלון זמן.

למה שתי המדידות חייבות להיות יחד: מדידה של "כמה חיבורים נפלו במנוחה" חסרת
ערך בלי הוכחה שבאמת הייתה מנוחה. לאתר יש משתמשים אמיתיים שממשיכים לצפות
גם כשלא נוגעים בו, ודי בצופה אחד כדי להסביר קריאות GetFile ולהפוך מסקנה
של "יש לולאת רקע שוברת חיבורים" למסקנה שגויה לגמרי.

לכן כאן נדגמות שלוש כמויות באותו קצב:

    תעבורה יוצאת   מהמונה של הכרטיס — האם מישהו באמת צופה עכשיו
    חיבורי הזרמה   כמה חיבורי TCP פתוחים אל האפליקציה
    נפילות         Send exception / Session stopped / Retrying מהיומן

ורק אם התעבורה אפסית והנפילות אינן — יש כאן תקלת רקע.

חשוב על הספירה: Pyrogram מנסה כל קריאה עד 10 פעמים ומדפיס שורה בכל ניסיון.
לכן "Retrying" נספר בנפרד מ-Send exception, ומספר השורות אינו מספר התקלות.

    python3 idle_churn.py                  # 3 דקות
    python3 idle_churn.py --minutes 10
    python3 idle_churn.py --every 30
"""
import argparse, pathlib, re, subprocess, time

SITE_PORTS = ("8000", "443", "80")
PATTERNS = {
    "Send exception":  r"Send exception",
    "Session stopped": r"Session stopped",
    "Session started": r"Session started",
}
RETRY_RX = re.compile(r'Retrying "([A-Za-z.]+)"')


def tx_bytes(dev):
    try:
        return int(pathlib.Path(
            f"/sys/class/net/{dev}/statistics/tx_bytes").read_text().strip())
    except Exception:
        return 0


def pick_dev():
    best, best_tx = "eth0", -1
    for p in sorted(pathlib.Path("/sys/class/net").iterdir()):
        if p.name == "lo":
            continue
        t = tx_bytes(p.name)
        if t > best_tx:
            best, best_tx = p.name, t
    return best


def conns():
    """חיבורי TCP פתוחים אל האפליקציה — כלומר צופים אמיתיים ברגע זה."""
    try:
        out = subprocess.run(["ss", "-tn", "state", "established"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return -1
    n = 0
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) >= 4 and f[3].rsplit(":", 1)[-1] in SITE_PORTS:
            n += 1
    return n


def journal(since_str):
    try:
        return subprocess.run(
            ["journalctl", "-u", "zovex-bot", "--since", since_str, "--no-pager"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--every", type=int, default=20, help="שניות בין דגימות")
    a = ap.parse_args()

    dev = pick_dev()
    t0 = time.time()
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))
    print(f"ממשק {dev} · {a.minutes:.0f} דקות · דגימה כל {a.every}ש")
    print("אל תיגע באתר. משתמשים אמיתיים כן עשויים להיות פעילים — "
          "בדיוק בשביל זה נמדדת גם התעבורה.\n")
    print("  דקה   Mbps החוצה   חיבורים   נפילות מצטברות")

    prev_tx = tx_bytes(dev)
    prev_t = t0
    peak_mbps, peak_conns = 0.0, -1      # -1 = ss לא זמין
    end = t0 + a.minutes * 60
    while True:
        left = end - time.time()
        if left <= 1:
            break
        time.sleep(min(a.every, left))
        now = time.time()
        cur_tx = tx_bytes(dev)
        mbps = (cur_tx - prev_tx) * 8 / max(0.001, now - prev_t) / 1e6
        prev_tx, prev_t = cur_tx, now
        c = conns()
        peak_mbps = max(peak_mbps, mbps)
        if c >= 0:
            peak_conns = max(peak_conns, c)
        sofar = journal(since)
        sends = len(re.findall(PATTERNS["Send exception"], sofar))
        print(f"  {(now-t0)/60:4.1f}   {mbps:10.1f}   "
              f"{(str(c) if c >= 0 else '?'):>7}   "
              f"Send exception {sends}")

    log = journal(since)
    elapsed_min = (time.time() - t0) / 60
    counts = {k: len(re.findall(v, log)) for k, v in PATTERNS.items()}
    retries = {}
    for m in RETRY_RX.finditer(log):
        retries[m.group(1)] = retries.get(m.group(1), 0) + 1

    print("\n" + "=" * 58)
    print(f"סיכום · {elapsed_min:.1f} דקות")
    print(f"  תעבורה יוצאת בשיא : {peak_mbps:.1f} Mbps")
    print("  חיבורים בשיא      : " +
          (str(peak_conns) if peak_conns >= 0 else "לא נמדד (חסר ss)"))
    for k, v in counts.items():
        print(f"  {k:<17}: {v}   ({v/max(0.1,elapsed_min):.0f} לדקה)")
    if retries:
        print("  קריאות שנוסו מחדש :")
        for k, v in sorted(retries.items(), key=lambda x: -x[1]):
            print(f"      {k:<26} {v}")

    print()
    # ההכרעה. הסף על התעבורה נמוך בכוונה: סרט אחד הוא ~6 Mbps, ולכן כל דבר
    # מתחת ל-2 Mbps אינו יכול להיות צפייה פעילה אלא רק דפים ובקשות קטנות.
    busy = peak_mbps >= 2.0
    churn = counts["Send exception"] / max(0.1, elapsed_min)
    if busy:
        print(f"⚠️  לא הייתה מנוחה — יצאו עד {peak_mbps:.1f} Mbps, כלומר מישהו צפה.")
        print("   המדידה הזאת לא יכולה להפריד בין תקלת רקע לבין עומס אמיתי.")
        print("   הרץ שוב בשעה שקטה יותר.")
    elif churn >= 10:
        print(f"❌ מנוחה אמיתית ({peak_mbps:.1f} Mbps) אבל {churn:.0f} נפילות לדקה.")
        print("   כלומר החיבורים לטלגרם נשברים מעצמם, בלי שום צופה. זו תקלת רקע.")
    elif churn > 0:
        print(f"✔️  מנוחה, ורק {churn:.0f} נפילות לדקה — רעש סביר.")
    else:
        print("✅ מנוחה מלאה, אפס נפילות.")


if __name__ == "__main__":
    main()
