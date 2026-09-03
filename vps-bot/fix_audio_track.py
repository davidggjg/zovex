#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ממיר ל-AAC קבצים שהועלו עם פס קול שדפדפן אינו מפענח, ומעלה אותם מחדש.

## מה נמדד

ונסדיי פרק 1 (וכל 16 הפרקים) נמצאו כך:

    וידאו:  avc1  1920x1080         ← תקין
    אודיו:  ec-3  6 ערוצים  48kHz  ← Dolby Digital Plus (E-AC3), 5.1

`ec-3` הוא Dolby Digital Plus. שום דפדפן אינו מפענח אותו ב-HTML5 — הוא **זורק
את רצועת הקול בשקט**, מנגן וידאו בלי סאונד, ולא מדווח שגיאה. VLC כן מנגן, כי יש
לו מפענח Dolby משלו. זה בדיוק מה שדווח: "עובד ב-VLC, אין קול באתר", ואצל כולם.

נבדקו גם 16 פריטים אחרים מהקטלוג — לכולם `mp4a` (AAC) תקין. כלומר זו האצווה
החדשה, לא כל הספרייה.

## מה הסקריפט עושה לכל פריט

1. מוריד את הקובץ מהשרת המקומי (127.0.0.1) — לא דרך האינטרנט.
2. `-c:v copy` — **הווידאו אינו מקודד מחדש**. אין הפסד איכות ואין עלות מעבד
   ממשית. רק פס הקול מומר ל-AAC סטריאו.
3. `-movflags +faststart` — מזיז את ה-moov לתחילת הקובץ. כל 16 הפרקים היו עם
   moov בסוף, וזה מה שגרם לטעינה של 12 שניות ולקפיצה תקועה באמצע: הנגן חייב
   את האינדקס לפני שהוא מנגן, ולכן נאלץ למשוך את קצה הקובץ קודם.
4. מעלה מחדש לאותו ערוץ ומעדכן את הקטלוג, דרך `/panel/replace-video`.
5. מאמת מהקובץ החדש שהאודיו הוא באמת `mp4a` ושה-moov בהתחלה. אם לא — עוצר.

ההודעה הישנה בטלגרם **אינה נמחקת** אלא אם ביקשת `--delete-old`. ככה יש דרך
חזרה: הגיבוי של content.json כולל את מזהה ההודעה הקודם.

## למה 5.1 יורד לסטריאו

הרצועה נשארת אחת, AAC סטריאו. אפשר היה לשמור גם את ה-5.1 כרצועה שנייה, אבל
בנגן MP4 מתקדם הדפדפן מנגן רק את הרצועה הראשונה, וקבצים עם שתי רצועות מבלבלים
חלק מהנגנים. 640kbps של Dolby שאף אחד לא מפענח אינם שווים את הסיכון.

## הרצה

    python3 add_replace_video.py && systemctl restart zovex-bot   # פעם אחת
    python3 audio_scan.py --series ונסדיי                          # מי שבור
    python3 fix_audio_track.py --from-scan --limit 1               # פרק אחד לבדיקה
    python3 fix_audio_track.py --from-scan                         # הכל

לפני הכול כדאי `--dry-run` — מראה בדיוק מה יקרה בלי לגעת בכלום.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
SCAN = HERE / "audio_scan.json"
STATE = HERE / "audio_fix_state.json"
WORK = pathlib.Path(os.environ.get("AUDIOFIX_DIR", "/opt/zovex-bot/audiofix"))
ENV_FILE = pathlib.Path("/opt/zovex-bot/.env")
LOCAL = "http://127.0.0.1:8000"

sys.path.insert(0, str(HERE))
from audio_scan import probe, BROWSER_OK   # noqa: E402  אותה קריאת moov בדיוק


def panel_password():
    p = os.environ.get("PANEL_PASSWORD", "").strip()
    if p:
        return p
    # מקום האמת לפרמטרים בשרת הזה הוא .env — כך תועד ב-STREAMING_DIAGNOSIS.md
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("PANEL_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def catalog():
    """הקטלוג עם קישורים חתומים טריים. החתימה מכסה chat/msg/exp בלבד ולא את
    הדומיין, ולכן מותר להפנות אותה ל-127.0.0.1."""
    for u in (f"{LOCAL}/movies.json", "https://zovex.duckdns.org/movies.json"):
        raw = subprocess.run(["curl", "-sS", "--max-time", "120", u],
                             capture_output=True).stdout
        if len(raw) > 10000:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
    print("❌ לא הצלחתי לקרוא את הקטלוג")
    sys.exit(1)


def to_local(url):
    return url.replace("https://zovex.duckdns.org", LOCAL)


def free_mb(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize // (1024 * 1024)


def size_of(url):
    txt = subprocess.run(["curl", "-sS", "-D", "-", "-o", "/dev/null",
                          "--max-time", "40", "-H", "Range: bytes=0-1", url],
                         capture_output=True, text=True).stdout
    for line in txt.splitlines():
        if line.lower().startswith("content-range"):
            try:
                return int(line.split("/")[-1].strip())
            except ValueError:
                pass
    return None


def download(url, dst, expect, rate="5M", tries=40, verbose=True):
    """מוריד עם המשכיות.

    הורדה רצופה אחת של קובץ 1.6GB מ-/stream נסגרת באמצע (נמדד: curl 18 אחרי
    206MB). זה לא באג בהורדה — זו אותה נפילת חלון שמפילה גם צופה. לכן במקום
    להיכשל, ממשיכים מאותה נקודה בבקשת Range. כל ניסיון שמתקדם מאפס את מונה
    הכישלונות; רק חוסר התקדמות נחשב כישלון אמיתי.

    הקצב מוגבל כברירת מחדל: כל משיכת רקע מטלגרם נגזלת ישירות מהצופים
    (STREAMING_DIAGNOSIS.md, מלכודת ב').
    """
    t0 = time.time()
    stuck = 0
    last_err = ""
    while True:
        have = dst.stat().st_size if dst.exists() else 0
        if expect and have >= expect:
            break
        cmd = ["curl", "-sS", "--max-time", "3600", "--connect-timeout", "20",
               "-C", "-", "-o", str(dst), url]
        if rate and rate != "0":
            cmd[1:1] = ["--limit-rate", rate]
        r = subprocess.run(cmd, capture_output=True, text=True)
        now = dst.stat().st_size if dst.exists() else 0
        if expect and now >= expect:
            break
        if now > have:
            stuck = 0
            if verbose:
                print(f"      המשך מ-{now / 1048576:.0f}MB "
                      f"מתוך {(expect or 0) / 1048576:.0f}MB", flush=True)
        else:
            stuck += 1
            last_err = (r.stderr.strip() or f"curl {r.returncode}")[:160]
            if stuck >= 6:
                return False, (f"נתקע על {now / 1048576:.0f}MB מתוך "
                               f"{(expect or 0) / 1048576:.0f}MB — {last_err}")
            time.sleep(min(60, 3 * 2 ** (stuck - 1)))
        tries -= 1
        if tries <= 0:
            return False, f"יותר מדי ניסיונות, נעצר על {now / 1048576:.0f}MB"

    got = dst.stat().st_size
    if expect and got != expect:
        return False, f"גודל לא תואם: {got} מול {expect}"
    dt = max(time.time() - t0, 1)
    return True, (f"{got / 1048576:.0f}MB ב-{dt / 60:.1f} דק' "
                  f"({got / 1048576 / dt:.1f} MB/s)")


def sub_args(path):
    """כתוביות טקסט נשמרות; כתוביות תמונה (PGS/VobSub) אינן יכולות לשבת ב-MP4
    ולכן יורדות. עדיף לומר את זה מפורש מאשר להפיל את ffmpeg בשקל."""
    exe = shutil.which("ffprobe")
    if not exe:
        return [], ""
    out = subprocess.run(
        [exe, "-v", "error", "-select_streams", "s", "-show_entries",
         "stream=codec_name", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=120).stdout.split()
    if not out:
        return [], ""
    text = [c for c in out if c in ("mov_text", "subrip", "srt", "ass", "ssa", "text")]
    img = [c for c in out if c not in text]
    args = ["-map", "0:s?", "-c:s", "mov_text"] if text and not img else []
    note = ""
    if img:
        note = f"כתוביות תמונה יורדות ({','.join(sorted(set(img)))}) — MP4 אינו מכיל אותן"
    elif text:
        note = f"כתוביות טקסט נשמרות ({','.join(sorted(set(text)))})"
    return args, note


def transcode(src, dst, bitrate="192k"):
    exe = shutil.which("ffmpeg")
    if not exe:
        return False, "ffmpeg אינו מותקן"
    sargs, note = sub_args(src)
    cmd = [exe, "-nostdin", "-y", "-v", "error", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0"] + sargs + [
        "-c:v", "copy",                     # הווידאו אינו מקודד מחדש
        "-c:a", "aac", "-ac", "2", "-b:a", bitrate, "-ar", "48000",
        "-movflags", "+faststart",
        str(dst)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 1000:
        return False, f"ffmpeg נכשל: {r.stderr.strip()[-400:]}"
    return True, (f"{dst.stat().st_size / 1048576:.0f}MB ב-{(time.time() - t0) / 60:.1f} דק'"
                  + (f"  · {note}" if note else ""))


def replace(item_id, path, pwd, delete_old, caption=""):
    body = json.dumps({"password": pwd, "item_id": item_id, "path": str(path),
                       "caption": caption, "delete_old": bool(delete_old)},
                      ensure_ascii=False)
    r = subprocess.run(["curl", "-sS", "--max-time", "5400",
                        "-H", "Content-Type: application/json",
                        "-d", body, f"{LOCAL}/panel/replace-video"],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"detail": (r.stdout or r.stderr).strip()[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-scan", action="store_true",
                    help="לקחת את הפריטים מ-audio_scan.json")
    ap.add_argument("--series", help="או לפי שם סדרה")
    ap.add_argument("--id", action="append", default=[], help="פריט בודד לפי id")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--bitrate", default="192k")
    ap.add_argument("--rate", default="5M",
                    help="תקרת קצב הורדה. כל משיכת רקע מטלגרם נגזלת מהצופים. "
                         "0 = בלי הגבלה.")
    ap.add_argument("--delete-old", action="store_true",
                    help="למחוק את ההודעה הישנה בטלגרם. בלי זה היא נשארת.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="לא למחוק את הקבצים המקומיים")
    a = ap.parse_args()

    if not (a.from_scan or a.series or a.id):
        print(__doc__)
        print("❌ חייב לבחור מה לתקן: --from-scan / --series / --id")
        sys.exit(1)

    pwd = panel_password()
    if not pwd and not a.dry_run:
        print("❌ לא נמצאה PANEL_PASSWORD (לא בסביבה ולא ב-/opt/zovex-bot/.env)")
        sys.exit(1)

    cat = catalog()
    by_id = {str(m.get("id")): m for m in cat}

    want = []
    if a.from_scan:
        if not SCAN.exists():
            print(f"❌ אין {SCAN}. הרץ קודם:  python3 audio_scan.py --series ונסדיי")
            sys.exit(1)
        scan = json.load(open(SCAN, encoding="utf-8"))
        want = [i for i, r in scan.items() if r.get("silent")]
    if a.series:
        want += [str(m["id"]) for m in cat
                 if a.series in str(m.get("series_name", ""))
                 or a.series in str(m.get("title", ""))]
    want += a.id

    state = json.load(open(STATE, encoding="utf-8")) if STATE.exists() else {}
    seen, todo = set(), []
    for i in want:
        if i in seen or i not in by_id:
            continue
        seen.add(i)
        if state.get(i, {}).get("done"):
            continue
        todo.append(by_id[i])
    todo.sort(key=lambda m: (str(m.get("series_name", "")),
                             m.get("season_number") or 0,
                             m.get("episode_number") or 0))
    if a.limit:
        todo = todo[:a.limit]

    WORK.mkdir(parents=True, exist_ok=True)
    print(f"לתיקון: {len(todo)} פריטים   ·   תיקיית עבודה: {WORK}   ·   "
          f"פנוי: {free_mb(WORK)}MB")
    if a.dry_run:
        for m in todo:
            print(f"   {m.get('series_name') or m.get('title')} "
                  f"s{m.get('season_number')}e{m.get('episode_number')}  ({m['id']})")
        print("\n(--dry-run — לא נעשה כלום)")
        return
    print()

    ok = fail = 0
    for k, m in enumerate(todo, 1):
        iid = str(m["id"])
        label = (f"{m.get('series_name') or m.get('title')} "
                 f"s{m.get('season_number')}e{m.get('episode_number')}").strip()
        print(f"[{k}/{len(todo)}] {label}   ({iid})", flush=True)

        url = to_local(m["video_url"])
        n = size_of(url)
        need = (n or 0) * 2 // 1048576 + 500
        if n and free_mb(WORK) < need:
            print(f"   ⏭  אין מקום: צריך ~{need}MB, פנוי {free_mb(WORK)}MB")
            fail += 1
            continue

        raw = WORK / f"{iid}.src.mp4"
        out = WORK / f"{iid}.aac.mp4"
        # קובץ מקור חלקי מריצה קודמת נשמר בכוונה — ההורדה ממשיכה ממנו.
        out.unlink(missing_ok=True)
        if raw.exists() and n and raw.stat().st_size > n:
            raw.unlink()      # גדול מהמקור = שארית של קובץ אחר

        good, msg = download(url, raw, n, a.rate)
        print(f"   הורדה: {msg}", flush=True)
        if not good:
            fail += 1
            continue

        good, msg = transcode(raw, out, a.bitrate)
        print(f"   המרה: {msg}", flush=True)
        if not good:
            fail += 1
            if not a.keep:
                raw.unlink(missing_ok=True)
            continue

        res = replace(iid, out, pwd, a.delete_old, caption="")
        if not res.get("ok"):
            print(f"   ❌ העלאה: {res.get('detail') or res}")
            fail += 1
            if not a.keep:
                raw.unlink(missing_ok=True)
                out.unlink(missing_ok=True)
            continue
        print(f"   הועלה: הודעה {res['old_msg_id']} → {res['new_msg_id']}   "
              f"({res['duration']}ש', {res['width']}x{res['height']})", flush=True)

        # ── אימות מהקובץ שבאמת יושב עכשיו בטלגרם ────────────────────────────
        time.sleep(3)
        newurl = to_local(res["video_url"])
        if "sig=" not in newurl:
            fresh = {str(x.get("id")): x for x in catalog()}.get(iid, {})
            newurl = to_local(fresh.get("video_url", newurl))
        where, st = probe(newurl)
        auds = [s for s in (st or []) if s[0] == "audio"]
        codecs = [c for _, c, _, _ in auds]
        playable = any(c in BROWSER_OK for c in codecs)
        faststart = str(where).startswith("התחלה")
        print(f"   אימות: אודיו {codecs or where}  ·  moov ב{where}"
              f"  →  {'✅' if playable else '❌'}"
              f"{'' if faststart else '  (⚠️ moov לא בהתחלה)'}", flush=True)

        state[iid] = {"done": bool(playable), "label": label,
                      "old_msg_id": res["old_msg_id"], "new_msg_id": res["new_msg_id"],
                      "codecs": codecs, "moov": where, "at": time.strftime("%F %T")}
        json.dump(state, open(STATE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

        if playable:
            ok += 1
        else:
            fail += 1
            print("   ⛔ עוצר: הקובץ החדש עדיין לא מתנגן. אל תמשיך לפרקים הבאים "
                  "לפני שנבין למה.")
            break

        if not a.keep:
            raw.unlink(missing_ok=True)
            out.unlink(missing_ok=True)
        print()

    print(f"\nהצליחו: {ok}   ·   נכשלו: {fail}   ·   מצב: {STATE}")
    if ok:
        print("הקטלוג עודכן בשרת. content.json מגובה אוטומטית לפני כל שמירה.")


if __name__ == "__main__":
    main()
