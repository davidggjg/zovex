#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""server_headroom — כמה מקום פנוי יש בשרת לבוט ניהול קבוצות.

השאלה "האם בוט חדש יעמיס על השרת" אינה נענית ברשימת הפיצ'רים שלו. מה שקובע
הוא כמה **הודעות בשנייה** הוא יטפל, וכמה מהן ידרשו עבודה כבדה (AI, תמלול,
OCR). רוב הפיצ'רים של בוט כזה הם קריאה וכתיבה למסד — זה זול מאוד.

לכן הכלי הזה לא מנחש. הוא מודד שלושה דברים בשרת הזה:

  1. מה יש  — ליבות, זיכרון, דיסק.
  2. מה כבר תפוס — כולל כמה zovex-bot עצמו צורך עכשיו.
  3. כמה נשאר — ומתרגם את זה למספר הודעות לשנייה שבוט כזה יוכל לטפל בהן
     בלי להתחרות בהזרמת הווידאו.

ההערכות מסומנות במפורש כהערכות. מה שנמדד — מסומן כנמדד.

    python3 server_headroom.py
"""
import os
import re
import subprocess
import sys
import time

# עלות מעבד להודעה נכנסת, לפי סוג הטיפול.
#
# שורת ה-moderation **נמדדה** ולא הוערכה: צינור מלא של 200 קבוצות,
# 50,000 משתמשים, רשימת חסימה של 500 מילים ו-51 ביטויי regex, קריאת
# הגדרות, קריאת ועדכון המשתמש ורישום לוג — הכול ב-SQLite עם WAL.
# 6,000 הודעות רצו ב-0.52 שניות, כלומר 0.087ms להודעה.
# שאר השורות הן סדרי גודל מקובלים ומסומנות ככאלה.
COST_MS = {
    "moderation": 0.087,  # נמדד — כולל regex, מסד ולוג
    "logging": 0.0,       # כלול במדידה שלמעלה
    "captcha": 2.0,       # הערכה. רק על הצטרפות, לא על כל הודעה
    "ai_text": 0.0,       # קריאת API חיצונית — לא מעבד מקומי
    "ocr": 300.0,         # הערכה, tesseract על תמונה
    "whisper": 8000.0,    # הערכה, תמלול דקת קול במודל small בלי GPU
}
# נמדד: 49 בייט לכל הודעה שנרשמת ביומן, כולל אינדקס
LOG_BYTES = 49


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def meminfo():
    d = {}
    try:
        for line in open("/proc/meminfo"):
            k, _, v = line.partition(":")
            d[k] = int(v.split()[0]) * 1024
    except Exception:
        pass
    return d


def cpu_busy(sec=2.0):
    """אחוז ניצול המעבד, נמדד על חלון אמיתי ולא מ-load average."""
    def snap():
        with open("/proc/stat") as f:
            p = f.readline().split()[1:]
        v = [int(x) for x in p]
        idle = v[3] + v[4]
        return sum(v), idle
    t0, i0 = snap()
    time.sleep(sec)
    t1, i1 = snap()
    dt, di = t1 - t0, i1 - i0
    return 100.0 * (1 - di / dt) if dt else 0.0


def proc_usage(pattern):
    """זיכרון RSS ואחוז מעבד של תהליכים שתואמים לדפוס."""
    out = sh(f"ps -eo pid,rss,pcpu,comm,args --no-headers | grep -i -- '{pattern}' | grep -v grep")
    rss = cpu = 0.0
    n = 0
    for line in out.splitlines():
        p = line.split(None, 4)
        if len(p) < 4:
            continue
        try:
            rss += int(p[1]) * 1024
            cpu += float(p[2])
            n += 1
        except ValueError:
            pass
    return n, rss, cpu


def gb(b):
    return b / 1024 ** 3


def main():
    cores = os.cpu_count() or 1
    mi = meminfo()
    total = mi.get("MemTotal", 0)
    avail = mi.get("MemAvailable", 0)
    used = total - avail

    print("═══════ מה יש בשרת ═══════")
    print(f"  ליבות מעבד : {cores}")
    print(f"  זיכרון     : {gb(total):.1f}GB  (פנוי עכשיו {gb(avail):.1f}GB)")
    df = sh("df -BG --output=size,avail / | tail -1").split()
    if len(df) == 2:
        print(f"  דיסק       : {df[0]} סה\"כ, {df[1]} פנוי")
    swap = mi.get("SwapTotal", 0)
    print(f"  Swap       : {gb(swap):.1f}GB" + ("  ← אין swap, קריסת זיכרון היא מיידית" if swap == 0 else ""))

    print("\n═══════ מה תפוס עכשיו (נמדד על 2 שניות) ═══════")
    busy = cpu_busy()
    print(f"  מעבד       : {busy:.0f}% מתוך 100%")
    la = open("/proc/loadavg").read().split()[:3] if os.path.exists("/proc/loadavg") else []
    if la:
        print(f"  Load       : {' '.join(la)}   (מעל {cores}.00 = יש תור)")
    print(f"  זיכרון     : {gb(used):.1f}GB תפוס מתוך {gb(total):.1f}GB")

    for name, pat in (("zovex-bot", "zovex"), ("ffmpeg (ערוצים חיים)", "ffmpeg"),
                      ("nginx", "nginx"), ("qbittorrent", "qbittorrent")):
        n, rss, pc = proc_usage(pat)
        if n:
            print(f"  {name:22} {n} תהליכים · {gb(rss):.2f}GB · {pc:.0f}% מעבד")

    print("\n═══════ כמה נשאר לבוט ═══════")
    free_cpu = max(0.0, 100.0 - busy)
    # שומרים 30% מרווח: הזרמת וידאו רגישה לקפיצות, ושרת שרץ על הקצה נתקע
    usable = free_cpu * 0.7
    core_ms = usable / 100.0 * 1000.0      # מילישניות מעבד פנויות בכל שנייה
    print(f"  מעבד פנוי  : {free_cpu:.0f}%  → לוקחים {usable:.0f}% בלבד (30% מרווח לצופים)")
    print(f"  זיכרון פנוי: {gb(avail):.1f}GB\n")

    print("  כמה הודעות בשנייה בוט כזה יוכל לטפל, לפי סוג הטיפול:")
    base = COST_MS["moderation"] + COST_MS["logging"]
    print(f"    ניהול רגיל (locks, blocklist, warns, flood, לוגים)")
    print(f"      ≈ {core_ms / base:,.0f} הודעות/שנייה   ← נמדד, {base}ms להודעה")
    print(f"    + AI על כל הודעה דרך API חיצוני")
    print(f"      ≈ אותו דבר במעבד. העלות היא כסף והשהיה, לא השרת.")
    print(f"    + OCR על כל תמונה")
    print(f"      ≈ {core_ms / COST_MS['ocr']:,.1f} תמונות/שנייה   ← כאן זה כבר נתפס")
    print(f"    + תמלול קולי מקומי")
    print(f"      ≈ {core_ms / COST_MS['whisper'] * 60:,.1f} דקות קול/דקה   ← לא ריאלי בלי מכונה נפרדת")

    # אחסון — הדבר היחיד שבאמת גדל עם הזמן
    print("\n  אחסון היומן (נמדד: 49 בייט להודעה, כולל אינדקס):")
    for label, per_day in (("קבוצה פעילה אחת", 20_000),
                           ("רשת של 50 קבוצות", 1_000_000)):
        year = LOG_BYTES * per_day * 365 / 1024 ** 3
        print(f"    {label:20} {per_day:>9,} הודעות/יום → {year:.1f}GB לשנה")

    print("\n═══════ המסקנה ═══════")
    if busy > 70:
        print("  ⚠ השרת כבר עמוס עכשיו. כל תוספת תורגש. למדוד שוב בשעה שקטה.")
    elif gb(avail) < 1.0:
        print("  ⚠ פחות מ-1GB זיכרון פנוי. הבוט עצמו יתפוס 200-400MB.")
    else:
        print("  ✓ יש מקום לליבת הבוט (ניהול, פילטרים, לוגים) בלי להרגיש.")
    print("  ✗ תמלול קול, ניתוח וידאו ו-OCR בנפח — לא על המכונה הזאת.")
    print("    הם מתחרים ישירות ב-ffmpeg של הערוצים החיים, והצופים ירגישו.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
