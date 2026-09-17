#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_check — למה השידורים החיים נתקעים, בלי לחשוף את הספק.

## הרקע

בערב הראשון נמדדו על 30 דקות חיות 95 מקרים של ffmpeg של ערוץ שמת ומופעל
מחדש (~3 בדקה), ובמקביל 1,080 שורות "Send exception ... TCPTransport
closed=True" — 36 בדקה — שהיו דליפת בריכות media של בוט שהוקם מחדש.
הדליפה תוקנה (fix_media_session_leak), והסרטים באמת התייצבו. הערוצים לא,
ולכן צריך למדוד **מה נשאר** ולא להניח שזו אותה סיבה.

## מה הכלי עושה

קורא את היומן של השירות וסופר שלוש משפחות בנפרד, כי הן מצביעות על שורשים
שונים לגמרי:

  • ffmpeg של ערוץ חי שמת/מופעל מחדש → מקור בצד הספק או ברשת
  • "Send exception / closed=True"     → האם דליפת הבריכות חזרה
  • timeout/reconnect מול הספק         → האם המקור עצמו מאט

ומפרק את זה **לפי ערוץ**, כי "כל הערוצים נתקעים" ו"שלושה ערוצים נתקעים
כל הזמן" הם שתי בעיות שונות עם שני פתרונות שונים.

## צנזורה, ולמה היא בקוד ולא בהוראות

בפעם הקודמת הפלט של כלי אבחון כלל את שם השרת של הספק ואת הסיסמה שבנתיב,
ודוד הדביק אותו לצ'אט. לכן הצנזור הוא חלק מהכלי ולא בקשה מהמשתמש: כל
מה שנראה כמו שם מתחם, כתובת IP או מזהה ארוך מוחלף לפני ההדפסה. אפשר
להדביק את הפלט בבטחה.

    python3 live_check.py              # 30 דקות אחרונות
    python3 live_check.py --min 120    # שתי שעות
"""
import argparse, re, subprocess, sys
from collections import Counter

SERVICE = "zovex-bot"

# ── צנזורה ───────────────────────────────────────────────────────────────────
# מוחלף לפני כל הדפסה. הסדר חשוב: קודם כתובות מלאות, אחר כך מה שנשאר.
REDACT = [
    (re.compile(r"https?://[^\s\"'<>]+"), "‹כתובת›"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "‹IP›"),
    (re.compile(r"\b[a-z0-9][a-z0-9.-]{6,}\.(?:tv|pw|com|net|org|io|me|cc|xyz|to)\b", re.I), "‹מתחם›"),
    (re.compile(r"\b[A-Za-z0-9]{12,}\b"), "‹מזהה›"),
]


def clean(s):
    for pat, rep in REDACT:
        s = pat.sub(rep, s)
    return s


# ── סיווג שורות ──────────────────────────────────────────────────────────────
PATTERNS = [
    ("ffmpeg של ערוץ מת / הופעל מחדש", re.compile(r"ffmpeg|hls_fix|_hls_", re.I)),
    ("חיבור מת (דליפת בריכות?)", re.compile(r"Send exception|TCPTransport closed|dead connection", re.I)),
    ("timeout / reconnect מול המקור", re.compile(r"timeout|timed out|reconnect|ConnectError|ReadError", re.I)),
    ("שגיאת ממסר (hls-relay)", re.compile(r"hls-relay|relay", re.I)),
]
# שם ערוץ מופיע בלוג כ-[שם] או channel=שם
CHAN = re.compile(r"\[([^\]\s]{2,40})\]|channel[= ]([^\s,]{2,40})")


def journal(minutes):
    for cmd in (["journalctl", "-u", SERVICE, "--since", f"{minutes} min ago", "--no-pager", "-o", "cat"],
                ["journalctl", "-u", SERVICE + ".service", "--since", f"{minutes} min ago", "--no-pager", "-o", "cat"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.splitlines()
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=30, help="חלון בדקות")
    ap.add_argument("--show", type=int, default=6, help="כמה דוגמאות לכל סוג")
    a = ap.parse_args()

    lines = journal(a.min)
    if lines is None:
        sys.exit(f"לא הצלחתי לקרוא את היומן של {SERVICE}. נסה:\n"
                 f"  journalctl -u {SERVICE} --since '{a.min} min ago' | tail -50")

    print(f"חלון: {a.min} דקות · {len(lines)} שורות ביומן\n")

    counts = Counter()
    samples = {k: [] for k, _ in PATTERNS}
    per_chan = Counter()

    for ln in lines:
        for name, pat in PATTERNS:
            if pat.search(ln):
                counts[name] += 1
                if len(samples[name]) < a.show:
                    samples[name].append(clean(ln.strip())[:170])
                if name.startswith("ffmpeg"):
                    m = CHAN.search(ln)
                    if m:
                        per_chan[clean((m.group(1) or m.group(2) or "?"))[:34]] += 1
                break

    print("── מה נמצא ──")
    if not counts:
        print("  שום דבר מהמשפחות שחיפשתי. אם הערוצים בכל זאת נתקעים,")
        print("  הבעיה לא מגיעה ליומן — והחשוד הבא הוא הנגן בצד הלקוח.")
    for name, n in counts.most_common():
        per_min = n / max(a.min, 1)
        print(f"  {n:6}  ({per_min:5.1f}/דקה)  {name}")

    if per_chan:
        print(f"\n── ffmpeg לפי ערוץ (מובילים) ──")
        top = per_chan.most_common(10)
        for ch, n in top:
            print(f"  {n:5}  {ch}")
        spread = len(per_chan)
        print(f"\n  {spread} ערוצים שונים הופיעו.")
        if spread <= 5:
            print("  → מרוכז במעט ערוצים: כנראה מקורות ספציפיים ולא בעיה כללית.")
        else:
            print("  → מפוזר על הרבה ערוצים: כנראה משאב משותף (רשת/CPU/הספק).")

    for name, _ in PATTERNS:
        if samples[name]:
            print(f"\n── דוגמאות: {name} ──")
            for s in samples[name]:
                print(f"  {s}")

    print("\n(כל הכתובות, ה-IP והמזהים צונזרו — אפשר להדביק את הפלט בבטחה.)")


if __name__ == "__main__":
    main()
