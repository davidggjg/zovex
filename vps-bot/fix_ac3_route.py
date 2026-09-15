#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_ac3_route.py — מנתב תוכן ב-AC-3 ישר ל-/vh, בלי לחכות לגילוי.

הבעיה, מאומתת מהשרת:
    סמולוויל  → audio = ac-3   audio_ok = False
דפדפנים הסירו בכוונה את המפענח של AC-3/E-AC-3 מטעמי רישוי — לא Chrome
ולא ה-WebView של האפליקציה. לכן דווקא הסדרה הזאת נופלת בשני הלקוחות
בזמן שכל שאר הקטלוג עובד.

הפתרון /vh כבר קיים ועובד (נבדק: 200, פלייליסט תקין, 0.77 שניות) —
HLS עם וידאו ב-copy ואודיו מומר ל-AAC תוך כדי. אבל הלקוחות מגיעים
אליו רק אחרי *גילוי* בזמן ריצה: מנגנים, מחכים שלוש שניות, מזהים שאין
קול ואז מחליפים. כשהגילוי לא נתפס — שום דבר לא קורה.

שני שינויים, ואחריהם אין צורך בשינוי באתר או באפליקציה:

  1. main.py: sign_stream_url חותם רק /stream/. קישור /vh/ בקטלוג היה
     מוגש בלי חתימה ומקבל 403. התבנית מורחבת ל-(?:stream|vh) — קבוצת
     לא-לוכדת, כדי ש-group(1)/group(2) יישארו chat/msg. מטען החתימה
     הוא chat/msg/exp ולכן זהה בשני הנתיבים, וזה אומת בפועל.

  2. content.json: הקישור של הסדרה מוחלף ל-/vh/<chat>/<msg>/index.m3u8.
     שני הלקוחות מזהים .m3u8 ומנגנים HLS ממילא.

    python3 fix_ac3_route.py --series "סמולוויל" --check
    python3 fix_ac3_route.py --series "סמולוויל"
    python3 fix_ac3_route.py --revert
"""
import argparse, json, os, re, shutil, sys, time
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
MAIN_BAK = MAIN.with_name(MAIN.name + ".bak_ac3")
CONTENT_BAK = CONTENT.with_name("content.json.bak_ac3")
MARK = "# [fix_ac3_route]"

OLD_RE = '_STREAM_PATH_RE = re.compile(r"/stream/(-?\\d+)/(\\d+)")'
NEW_RE = ('# ' + MARK + ' חותמים גם /vh: מטען החתימה הוא chat/msg/exp\n'
          '# ולכן זהה בשני הנתיבים. קבוצה לא-לוכדת כדי שמספרי הקבוצות\n'
          '# יישארו chat=1, msg=2. בלי זה קישור /vh בקטלוג מוגש בלי\n'
          '# חתימה ומקבל 403.\n'
          '_STREAM_PATH_RE = re.compile(r"/(?:stream|vh)/(-?\\d+)/(\\d+)")')

STREAM_URL = re.compile(r"^(.*)/stream/(-?\d+)/(\d+)(\?.*)?$")


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def patch_main(check: bool) -> bool:
    src = MAIN.read_text(encoding="utf-8")
    if MARK in src:
        print("  ✓ main.py כבר מתוקן")
        return False
    n = src.count(OLD_RE)
    if n != 1:
        sys.exit(f"  ✗ התבנית ב-main.py נמצאה {n} פעמים במקום אחת — לא נוגעים")
    out = src.replace(OLD_RE, NEW_RE, 1)
    compile(out, str(MAIN), "exec")
    # אימות: התבנית החדשה חייבת לתפוס את שני הנתיבים ולהחזיר chat/msg
    rx = re.compile(r"/(?:stream|vh)/(-?\d+)/(\d+)")
    for probe in ("/stream/-100/9250", "/vh/-100/9250/index.m3u8"):
        m = rx.search(probe)
        if not m or m.group(1) != "-100" or m.group(2) != "9250":
            sys.exit(f"  ✗ התבנית החדשה לא תופסת נכון את {probe}")
    print("  ✓ main.py: התבנית תתפוס גם /stream וגם /vh, קבוצות נכונות")
    if not check:
        shutil.copy2(MAIN, MAIN_BAK)
        MAIN.write_text(out, encoding="utf-8")
        print(f"  ✓ נכתב. גיבוי: {MAIN_BAK}")
    return True


def patch_content(series: str, check: bool) -> int:
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    hits = [i for i in items
            if (i.get("series_name") or "").strip() == series.strip()]
    if not hits:
        sys.exit(f"  ✗ לא נמצאה סדרה {series!r}")
    changes = []
    already = 0
    for i in hits:
        u = i.get("video_url") or ""
        if "/vh/" in u:
            already += 1
            continue
        m = STREAM_URL.match(u)
        if not m:
            continue
        new = f"{m.group(1)}/vh/{m.group(2)}/{m.group(3)}/index.m3u8{m.group(4) or ''}"
        changes.append((i, u, new))

    print(f"  {series}: {len(hits)} פרקים · "
          f"{len(changes)} יעברו ל-/vh · {already} כבר שם")
    if changes:
        i, old, new = changes[0]
        print(f"     לדוגמה:\n       {old}\n       → {new}")
    if check or not changes:
        return len(changes)

    shutil.copy2(CONTENT, CONTENT_BAK)
    for i, _, new in changes:
        i["video_url"] = new
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"  ✓ נכתב. גיבוי: {CONTENT_BAK} · גרסה {v}")
    return len(changes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        done = []
        if MAIN_BAK.exists():
            shutil.copy2(MAIN_BAK, MAIN); done.append("main.py")
        if CONTENT_BAK.exists():
            shutil.copy2(CONTENT_BAK, CONTENT); done.append("content.json")
        if not done:
            sys.exit("אין גיבויים לשחזור")
        print("✓ שוחזרו: " + ", ".join(done))
        print("  אם main.py שוחזר — צריך systemctl restart zovex-bot")
        return

    if not a.series:
        sys.exit("צריך --series <שם>")
    for p in (MAIN, CONTENT):
        if not p.exists():
            sys.exit(f"לא נמצא: {p}")

    print("שלב 1 — חתימת קישורי /vh ב-main.py")
    need_restart = patch_main(a.check)
    print("\nשלב 2 — ניתוב הסדרה ל-/vh בקטלוג")
    n = patch_content(a.series, a.check)

    print("\n" + "=" * 60)
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return
    if need_restart:
        print("⚠ main.py השתנה — צריך:  systemctl restart zovex-bot")
        print("  ה-restart מנתק צופים פעילים. לעשות כשאין תנועה.")
        print("  עד ה-restart הקישורים החדשים יחזירו 403, כי החתימה")
        print("  לא מתווספת להם. אפשר להריץ --revert ולחכות.")
    elif n:
        print("✓ מוכן. בלי restart — האתר והאפליקציה ירעננו לבד.")


if __name__ == "__main__":
    main()
