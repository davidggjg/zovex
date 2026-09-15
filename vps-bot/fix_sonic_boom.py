#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_sonic_boom.py — מסדר את פרקי "סוניק בום" לסדרה אחת מסודרת.

הקבצים הועלו בשמות כמו:
    מ T.S סוניק בום ע1 פ2+1.mp4
    מ T.S סוניק בום ע1 פ4+3.mp4

כלומר כל קובץ מכיל *שני* פרקים, והמספרים כתובים **מהגבוה לנמוך**:
"פ2+1" הוא פרקים 1 ו-2, לא 2 ו-1. מי שיקרא את המספר הראשון כפרק ההתחלה
יקבל סדרה שמוצגת הפוך. לכן הסקריפט לוקח min/max ולא ראשון/שני.

    python3 fix_sonic_boom.py --check                 # רק מראה, לא נוגע
    python3 fix_sonic_boom.py --merge-from "אחד"      # ממזג סדרה קיימת
    python3 fix_sonic_boom.py                         # מחיל
    python3 fix_sonic_boom.py --revert

בסוף מעדכן content_version.txt — האתר והאפליקציה מרעננים לבד,
בלי restart ובלי לנתק צופים.
"""
import argparse, json, os, re, shutil, sys, time
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_sonic")

SERIES = "סוניק בום"

# "סוניק בום ע1 פ2+1"  → עונה 1, פרקים 1-2
# "סוניק בום ע1 פ7"    → עונה 1, פרק 7
PAIR = re.compile(r"ע\s*(\d+)\s*.*?פ\s*(\d+)\s*\+\s*(\d+)")
ONE = re.compile(r"ע\s*(\d+)\s*.*?פ\s*(\d+)(?!\s*\+)")


def atomic_write(path: Path, text: str) -> None:
    """אותה שיטה שכבר בשימוש במטמון הקצה: tmp + fsync + replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def parse(title: str):
    """מחזיר (עונה, פרק_ראשון, פרק_אחרון) או None."""
    m = PAIR.search(title)
    if m:
        s, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return s, min(a, b), max(a, b)      # "פ2+1" = פרקים 1-2
    m = ONE.search(title)
    if m:
        return int(m.group(1)), int(m.group(2)), None
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--merge-from", default="",
                    help="שם סדרה קיימת שתמוזג לתוך 'סוניק בום'")
    ap.add_argument("--match", default="סוניק בום",
                    help="הטקסט שמזהה את הפריטים בכותרת")
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return

    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    print(f"קטלוג: {len(items)} פריטים\n")

    def g(i, k):
        return (i.get(k) or "").strip() if isinstance(i.get(k), str) else i.get(k)

    # ── 1. מה קיים כרגע ───────────────────────────────────────────────
    hits = [i for i in items
            if a.match in ((g(i, "title") or "") + " " + (g(i, "series_name") or ""))]
    print(f"=== פריטים שמכילים {a.match!r}: {len(hits)} ===")
    for i in hits:
        print(f"  [{str(i.get('id'))[:8]}] series={g(i,'series_name')!r} "
              f"ע{i.get('season_number')} פ{i.get('episode_number')}"
              f"-{i.get('episode_number_end')} | {(g(i,'title') or '')[:60]}")
    if not hits:
        print("  (אין. ייתכן שההעלאה עוד לא הסתיימה, או שהשם בכותרת שונה.)")
        print(f"  נסה:  python3 {Path(__file__).name} --check --match 'סוניק'")

    merged = []
    if a.merge_from:
        merged = [i for i in items if g(i, "series_name") == a.merge_from]
        print(f"\n=== סדרה {a.merge_from!r} למיזוג: {len(merged)} פריטים ===")
        for i in merged[:20]:
            print(f"  [{str(i.get('id'))[:8]}] ע{i.get('season_number')} "
                  f"פ{i.get('episode_number')} | {(g(i,'title') or '')[:60]}")
        if len(merged) > 20:
            print(f"  ... ועוד {len(merged)-20}")
        if not merged:
            print("  (לא נמצאה סדרה בשם הזה. בדוק איות מדויק.)")

    # ── 2. מה ישתנה ───────────────────────────────────────────────────
    changes = []
    for i in hits:
        p = parse(g(i, "title") or "")
        if not p:
            print(f"\n⚠ לא הצלחתי לפענח עונה/פרק מ: {g(i,'title')!r} — מדלג")
            continue
        season, ep, ep_end = p
        new = {"series_name": SERIES, "season_number": season,
               "episode_number": ep, "episode_number_end": ep_end}
        old = {k: i.get(k) for k in new}
        if old != new:
            changes.append((i, old, new))

    for i in merged:
        new = {"series_name": SERIES}
        if g(i, "series_name") != SERIES:
            changes.append((i, {"series_name": g(i, "series_name")}, new))

    def final(i, new, k):
        """הערך שיהיה לפריט אחרי השינוי — מהשינוי אם נקבע, אחרת מה שכבר יש.
        מיזוג משנה רק את שם הסדרה, ולכן חייבים ליפול חזרה לערך הקיים."""
        return new[k] if k in new else i.get(k)

    print(f"\n{'='*62}\n{len(changes)} פריטים ישתנו\n{'='*62}")
    for i, old, new in changes:
        t = (g(i, "title") or "")[:44]
        s, e, ee = (final(i, new, "season_number"),
                    final(i, new, "episode_number"),
                    final(i, new, "episode_number_end"))
        label = f"ע{s if s is not None else '?'} פ{e if e is not None else '?'}"
        if ee:
            label += f"-{ee}"
        print(f"  {t:<46} → {SERIES} {label}")

    if not changes:
        print("  אין מה לשנות.")
        return

    # התנגשויות: שני פריטים שיתפסו את אותו פרק אחרי השינוי. קריטי דווקא
    # במיזוג — סדרה קיימת יכולה להחזיק פרקים 1-2 שגם קובץ "פ2+1" תופס,
    # והתוצאה היא סדרה עם כפילויות שנראית שבורה למשתמש.
    seen, clashes = {}, 0
    for i, _, new in changes:
        s = final(i, new, "season_number")
        e = final(i, new, "episode_number")
        ee = final(i, new, "episode_number_end")
        if s is None or e is None:
            continue
        for n in range(e, (ee or e) + 1):
            k = (s, n)
            if k in seen:
                print(f"\n⚠ התנגשות: עונה {s} פרק {n} נתפס גם על ידי "
                      f"{(g(seen[k],'title') or '')[:40]!r} "
                      f"וגם {(g(i,'title') or '')[:40]!r}")
                clashes += 1
            seen[k] = i
    if clashes:
        print(f"\n🔴 {clashes} התנגשויות. אל תחיל לפני שתחליט איזה פריט "
              f"נשאר — אחרת תקבל סדרה עם פרקים כפולים.")
        if not a.check:
            sys.exit("עוצר. הרץ עם --check, תקן, ואז שוב.")

    if a.check:
        print("\n--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for i, _, new in changes:
        i.update(new)
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))

    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))

    print(f"\n✓ הוחל על {len(changes)} פריטים")
    print(f"  גיבוי: {BACKUP}")
    print(f"  content_version → {v} (האתר והאפליקציה ירעננו לבד, בלי restart)")


if __name__ == "__main__":
    main()
