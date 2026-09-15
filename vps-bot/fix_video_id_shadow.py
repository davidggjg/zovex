#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_video_id_shadow.py — video_id ישן שדורס את video_url באתר.

איך זה נמצא: פתחתי את האתר בכרום אמיתי, דילגתי על ההתחברות, לחצתי על
פרק 1 של סמולוויל וראיתי מה הנגן באמת מקבל:

    src = https://zovex.duckdns.org/stream/-1003936100530/9250?exp=…
    videoWidth 0 · readyState 0 · ERR_ABORTED חוזר ונשנה

כלומר ‎/stream ולא ‎/vh — הכתובת שתיקנו בכלל לא הגיעה לנגן. ב-content.json
היא תקינה, ולכן האפליקציה עובדת. האתר קורא שדה אחר:

    // CustomVideoPlayer.jsx, buildSrc
    const vid = cleanVideoRef(movie.video_id || movie.video_url || "");

‎video_id **קודם** ל-video_url. אצל אותו פרק video_id מחזיק עדיין כתובת
‎/stream ישנה, ולכן הדפדפן מקבל MP4 עם וידאו MPEG-4 Part 2 שהוא לא
מפענח — מסך שחור. האפליקציה קוראת video_url ולכן לא הושפעה.

היקף מדוד: **פריט אחד** בכל 13,172 — סמולוויל פרק 1. שאר 214 הפרקים
נקיים, ולכן הם עובדים באתר. זה גם מסביר למה זה נראה כאילו "כל הסדרה
שבורה": פרק 1 הוא מה שנפתח.

ב-323 פריטים אחרים יש video_id שונה מ-video_url, וזה **תקין** — שם הוא
מחזיק מזהה של Kaltura או של דרייב, וזה בדיוק מה ש-buildSrc מצפה לו.
לכן הסקריפט לא נוגע בהם: הוא מנקה רק video_id שהוא כתובת של השרת שלנו
(‎/stream, /fs או /vh) וסותר את video_url. במצב הזה video_id הוא תמיד
שריד, כי הכתובת הקנונית שלנו חיה ב-video_url.

    python3 fix_video_id_shadow.py --check
    python3 fix_video_id_shadow.py
    python3 fix_video_id_shadow.py --revert

בלי restart — האתר והאפליקציה מרעננים לבד לפי content_version.
"""
import argparse, json, os, re, shutil, sys, time
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_vidshadow")

# כתובת של השרת שלנו, בכל אחד משלושת נתיבי ההגשה.
#
# ‎%BASE% הוא מציין מיקום שהקטלוג שומר במקום הדומיין, ו-expand_base מחליף
# אותו ב-STREAM_PUBLIC_BASE בזמן ההגשה. לכן ב-content.json הערך נראה
# "%BASE%/stream/…" ורק ב-/content/lite הוא נראה כדומיין מלא. הגרסה
# הראשונה שלי בדקה רק את הצורה המורחבת ולכן מצאה אפס — דוד הריץ --check
# וקיבל "אין מה לתקן", וזה מה שחשף את זה.
OURS = re.compile(r"^(?:https?://[^/]+|%BASE%)/(?:stream|fs|vh)/(-?\d+)/(\d+)")


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
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
    hits, kept = [], 0
    for it in items:
        vi = str(it.get("video_id") or "")
        vu = str(it.get("video_url") or "")
        if not vi or not vu or vi == vu:
            continue
        if OURS.match(vi):
            hits.append(it)
        else:
            kept += 1

    print(f"קטלוג: {len(items)} פריטים\n")
    print(f"  video_id שהוא כתובת שלנו וסותר את video_url:  {len(hits)}")
    print(f"  video_id לגיטימי (Kaltura/דרייב/יוטיוב וכו'):  {kept}  — לא נוגעים\n")
    if not hits:
        print("אין מה לתקן.")
        return

    print("=" * 66)
    for it in hits[:20]:
        name = (it.get("series_name") or it.get("title") or "?").strip()
        ep = it.get("episode_number")
        print(f"\n  {name}" + (f"  פרק {ep}" if ep else ""))
        print(f"     video_id  (נמחק): {str(it.get('video_id'))[:78]}")
        print(f"     video_url (נשאר): {str(it.get('video_url'))[:78]}")
    if len(hits) > 20:
        print(f"\n  ... ועוד {len(hits) - 20}")
    print("\n" + "=" * 66)

    if a.check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for it in hits:
        it.pop("video_id", None)
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"✓ נוקו {len(hits)} פריטים · גיבוי: {BACKUP} · גרסה {v}")
    print("  בלי restart. האתר יתפוס את זה ברענון.")


if __name__ == "__main__":
    main()
