#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_video — סריקת וידאו לספאם, מקומית לגמרי, בלי שום API.

## למה בכלל

השאלה הייתה אם ניתוח וידאו שווה את המשאבים. התשובה שנמדדה: כן, בתנאי
שלא עושים את זה בדרך הנאיבית.

הדרך הנאיבית דוגמת פריים כל 3 שניות — 10 פריימים לסרטון של 30 שניות,
ומריצה OCR על כולם. אבל סרטון ספאם הוא כמעט תמיד **סטטי**: אותו מסך עם
אותו טקסט. זיהוי החלפת סצנה מצמצם 30 שניות לפריים אחד.

    נמדד, סרטון ספאם סטטי של 30 שניות : 1 פריים ייחודי
    נמדד, סרטון דינמי של 24 שניות      : 4 פריימים ייחודיים

## מה נמדד על המנוע

    tesseract + חבילת עברית : 74ms לפריים, קרא "כסף חינם לחצו כאן" נכון
    rapidocr (נבדק ונפסל)   : 303ms לפריים, ובעברית החזיר ג'יבריש
    זיהוי QR ב-OpenCV       : 29ms לפריים

כלומר סרטון שלם עולה בערך 0.6 עד 0.9 שניות מעבד. לא פי עשרה ממה שחשבנו,
ובלי להוציא בייט אחד החוצה.

## למה זה חשוב שזה מקומי

ההעלאה של הווידאו ל-API חיצוני הייתה יוצאת באותו קו שמזרים סרטים לצופים.
כאן שום דבר לא יוצא — הקובץ כבר על השרת, והניתוח נגמר אצלנו.

דרישות:  ffmpeg, tesseract-ocr, tesseract-ocr-heb, python3-opencv

    python3 scan_video.py video.mp4
    python3 scan_video.py video.mp4 --json
    python3 scan_video.py --benchmark video.mp4
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# ניקוד חשד. אף אחד מהם אינו "אשם" לבדו — הם מוזנים ל-Policy Engine.
PATTERNS = [
    (r"\bt\.me/\S+", 30, "קישור לטלגרם בתוך הווידאו"),
    (r"https?://\S+", 20, "קישור בתוך הווידאו"),
    (r"\b(?:free|חינם|בחינם)\b", 15, "הבטחת חינם"),
    (r"\b(?:crypto|bitcoin|forex|השקעה|קריפטו|ביטקוין)\b", 25, "פיננסי"),
    (r"\b(?:click|לחצו|לחץ|הירשמו|הצטרפו)\b", 15, "קריאה לפעולה"),
    (r"\b(?:winner|זכית|פרס|מתנה)\b", 20, "הבטחת זכייה"),
    (r"\b(?:\+?\d[\d\-\s]{7,})\b", 10, "מספר טלפון"),
]


def have(*tools):
    return [t for t in tools if not shutil.which(t)]


def unique_frames(path, out_dir, threshold=0.3, cap=8):
    """הפריים הראשון, ועוד אחד בכל החלפת סצנה. זה הלב של החיסכון."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
         f"select='eq(n\\,0)+gt(scene,{threshold})',scale=640:-1",
         "-vsync", "vfr", os.path.join(out_dir, "f%03d.jpg")],
        capture_output=True, timeout=180)
    fr = sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir)
                if f.startswith("f") and f.endswith(".jpg"))
    return fr[:cap]      # תקרה, כדי שסרטון ארוך לא יבלע את המעבד


def ocr(frame, langs="heb+eng"):
    try:
        r = subprocess.run(["tesseract", frame, "-", "-l", langs],
                           capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def qr_codes(frame):
    try:
        import cv2
    except ImportError:
        return []
    try:
        img = cv2.imread(frame)
        if img is None:
            return []
        ok, infos, _, _ = cv2.QRCodeDetector().detectAndDecodeMulti(img)
        return [i for i in (infos or []) if i] if ok else []
    except Exception:
        return []


def score(text, qrs):
    hits, total = [], 0
    for rx, pts, why in PATTERNS:
        if re.search(rx, text, re.I):
            hits.append(why)
            total += pts
    if qrs:
        hits.append("קוד QR בתוך הווידאו")
        total += 35
    return min(total, 100), hits


def scan(path, langs="heb+eng"):
    t0 = time.perf_counter()
    tmp = tempfile.mkdtemp(prefix="scanvid_")
    try:
        frames = unique_frames(path, tmp)
        t_extract = time.perf_counter() - t0
        text, qrs = "", []
        t1 = time.perf_counter()
        for f in frames:
            text += ocr(f, langs) + "\n"
            qrs += qr_codes(f)
        t_read = time.perf_counter() - t1
        risk, why = score(text, qrs)
        return {
            "file": os.path.basename(str(path)),
            "frames": len(frames),
            "risk": risk,
            "reasons": why,
            "qr": qrs,
            "text": " ".join(text.split())[:400],
            "ms_extract": round(t_extract * 1000),
            "ms_read": round(t_read * 1000),
            "ms_total": round((time.perf_counter() - t0) * 1000),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--langs", default="heb+eng")
    ap.add_argument("--benchmark", action="store_true",
                    help="מריץ 3 פעמים ומדווח ממוצע")
    a = ap.parse_args()

    missing = have("ffmpeg", "tesseract")
    if missing:
        print(f"❌ חסר: {', '.join(missing)}")
        print("   apt-get install -y ffmpeg tesseract-ocr tesseract-ocr-heb")
        return 1
    langs = subprocess.run(["tesseract", "--list-langs"],
                           capture_output=True).stdout.decode()
    if "heb" not in langs:
        print("⚠ חבילת העברית של tesseract אינה מותקנת — עברית לא תיקרא.")
        print("   apt-get install -y tesseract-ocr-heb")

    out = []
    for v in a.video:
        if not os.path.exists(v):
            print(f"❌ לא נמצא: {v}")
            continue
        runs = 3 if a.benchmark else 1
        r = None
        times = []
        for _ in range(runs):
            r = scan(v, a.langs)
            times.append(r["ms_total"])
        if a.benchmark:
            r["ms_total"] = round(sum(times) / len(times))
            r["runs"] = runs
        out.append(r)

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    for r in out:
        bar = "🔴" if r["risk"] >= 60 else "🟡" if r["risk"] >= 30 else "🟢"
        print(f"\n{bar} {r['file']}")
        print(f"   סיכון      : {r['risk']}/100")
        print(f"   פריימים    : {r['frames']} ייחודיים")
        print(f"   זמן מעבד   : {r['ms_total']}ms "
              f"(חילוץ {r['ms_extract']}ms · קריאה {r['ms_read']}ms)")
        if r["reasons"]:
            print(f"   נמצא       : {', '.join(r['reasons'])}")
        if r["qr"]:
            print(f"   QR         : {r['qr']}")
        if r["text"]:
            print(f"   טקסט       : {r['text'][:160]}")
        if not r["reasons"]:
            print("   נקי")
    return 0


if __name__ == "__main__":
    sys.exit(main())
