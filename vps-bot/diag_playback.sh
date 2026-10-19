#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · למה סרטים לא מתנגנים. אבחון, לא תיקון.
#
# ## למה זה קודם לכל תיקון
#
# "מלא סרטים לא עובדים" הוא דיווח, לא ממצא. הוא יכול לנבוע מבוטים חנוקים,
# מקישורים שפג תוקפם, מקבצים שנמחקו מהערוץ, או מעומס שאנחנו עצמנו יצרנו.
# לכל אחד מהם תיקון אחר, ולכמה מהם תיקון שגוי מחמיר את המצב. הסקריפט
# הופך את הדיווח לרשימה: אילו פריטים נכשלים, באיזה קוד, וכמה מהם.
#
# ## החשד הראשון, ולכן הצעד הראשון
#
# המחמם מושך מאותה בריכת בוטים שהצופים משתמשים בה. הוא רץ ברציפות,
# ושלושה בוטים כבר נחנקו לפני שהתחלנו. מחמם רקע שמתחרה בצופים הוא
# בדיוק התסמין שמתואר — ולכן הוא נעצר כאן ראשון, לפני כל מדידה.
#
# קורא בלבד מעבר לעצירת המחמם. לא נוגע בקוד, בתצורה או במטמון.
#
#   sudo bash diag_playback.sh
#   DIAG_N=30 sudo bash diag_playback.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
BASE=http://127.0.0.1:8000
N="${DIAG_N:-15}"

echo "════════ אבחון הפעלה ════════"
echo

echo "① עוצר את המחמם (החשד הראשון — הוא מתחרה בצופים על אותם בוטים)"
if pkill -f warm_tails.py 2>/dev/null; then
  echo "   נעצר. אם זו הייתה הסיבה, המצב ישתפר תוך דקה."
else
  echo "   לא רץ."
fi
echo

echo "② מצב השירות"
systemctl is-active "$SVC" | sed 's/^/   /'
systemctl show -p ActiveEnterTimestamp --value "$SVC" | sed 's/^/   עלה: /'
echo

echo "③ בוטים חנוקים ושגיאות בשעה האחרונה"
# FloodWait הוא החתימה של בוט שחרג ממגבלה. הספירה חשובה יותר מהטקסט:
# כמה, ובאיזה קצב, אומר אם זו תקלה נקודתית או חניקה מתמשכת.
FW=$(journalctl -u "$SVC" --since "1 hour ago" --no-pager 2>/dev/null | grep -c "FloodWait")
ERR=$(journalctl -u "$SVC" --since "1 hour ago" --no-pager 2>/dev/null | grep -ci "error\|exception\|traceback")
echo "   FloodWait: $FW"
echo "   שגיאות:    $ERR"
echo "   אחרונות:"
journalctl -u "$SVC" --since "1 hour ago" --no-pager 2>/dev/null \
  | grep -i "FloodWait\|error\|exception" | tail -8 | sed 's/^/     /'
echo

echo "④ בודק $N פריטים מהקטלוג — 256KB ראשונים מכל אחד"
echo
python3 - "$BASE" "$N" <<'PY'
import json, re, sys, time, urllib.error, urllib.request

base, n = sys.argv[1], int(sys.argv[2])
rx = re.compile(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?")
try:
    body = urllib.request.urlopen(base + "/content/lite", timeout=180).read().decode("utf-8", "replace")
except Exception as e:
    sys.exit(f"   לא הצלחתי לקרוא את הקטלוג: {e}")

seen, items = set(), []
for c, m, q in rx.findall(body):
    if (c, m) in seen:
        continue
    seen.add((c, m))
    items.append((c, m, q or ""))

# פרושים על כל הקטלוג ולא רק ההתחלה: הפריטים הראשונים הם התוספות
# האחרונות, והתקלה עשויה להיות דווקא בישנים.
step = max(1, len(items) // n)
sample = items[::step][:n]
print(f"   קטלוג {len(items)} · בודק {len(sample)}\n")

ok = []
bad = []
for i, (c, m, q) in enumerate(sample, 1):
    path = f"/stream/{c}/{m}{q}"
    req = urllib.request.Request(base + path)
    req.add_header("Range", "bytes=0-262143")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            first = time.time() - t0
            data = r.read()
        dt = time.time() - t0
        kb = len(data) / 1024
        if len(data) < 262144:
            bad.append((c, m, f"קצר: {kb:.0f}KB בלבד"))
            print(f"   [{i:2}] {c}/{m}  ⚠️  {kb:.0f}KB בלבד")
        else:
            ok.append(dt)
            print(f"   [{i:2}] {c}/{m}  ✅ בייט ראשון {first:5.2f}s · "
                  f"{kb / max(dt, .001):7.0f} KB/s")
    except urllib.error.HTTPError as e:
        bad.append((c, m, f"HTTP {e.code}"))
        print(f"   [{i:2}] {c}/{m}  ❌ HTTP {e.code}")
    except Exception as e:
        bad.append((c, m, type(e).__name__))
        print(f"   [{i:2}] {c}/{m}  ❌ {type(e).__name__}")

print(f"\n   {'─' * 50}")
print(f"   עובדים {len(ok)}/{len(sample)} · נכשלים {len(bad)}/{len(sample)}")
if ok:
    ok.sort()
    print(f"   זמן ל-256KB: חציון {ok[len(ok)//2]:.2f}s · הגרוע {ok[-1]:.2f}s")
if bad:
    from collections import Counter
    print("\n   סיבות הכישלון:")
    for reason, cnt in Counter(r for _, _, r in bad).most_common():
        print(f"      {cnt:3}x  {reason}")
    print("\n   פריטים שנכשלו (להעתיק לי):")
    for c, m, r in bad[:12]:
        print(f"      /stream/{c}/{m}  — {r}")
PY

echo
echo "════════ סוף האבחון ════════"
echo "שלח לי את כל הפלט. אל תריץ שום תיקון לפני שאסתכל."
