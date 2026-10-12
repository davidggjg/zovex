#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_embyil_emby — מוצא את כל הערוצים שקיימים אצל play.embyil.tv
(הפורמט החדש: /emby/videos/{id}/master.m3u8), על אותו דגם בדיוק של
scan_embyil.py (tv.embyil.tv, הפורמט הישן) — ספק/פורמט אחר, אותה גישה.

## למה זה חייב לרוץ על השרת

כש-play.embyil.tv נבדק מסביבה שאינה השרת, Cloudflare חסם ישירות — לא
שגיאת הרשאה/טוקן, אלא עמוד "Attention Required" (חסימת IP של דאטהסנטר,
עוד לפני שמישהו בדק את הטוקן). השרת כבר מגיש embyil.tv (tv., לא play.,
אבל אותו ספק) בהצלחה דרך הרלֵיי — סביר שה-IP שלו לא חסום, אבל זה לא
ודאי עד שבודקים. ‎--probe-only‎ בודק את זה ב-5 בקשות בלבד לפני הכל.

## מה ידוע

דוד קיבל מהספק שני קישורים בפורמט הזה (חשבון-שירות קבוע, לא טוקן
חד-פעמי לכל ערוץ — אותו UserId/X-Emby-Token/X-Emby-Device-Id בשניהם):

    3047655   MediaSourceId=0866ca2c3c1a5863e07b05c673a19a4e
    3047699   MediaSourceId=970167aec44f6636936709f22129f3a5

MediaSourceId משתנה לכל id ולא ניתן לנחש — בבקשות הסריקה הוא *מושמט
בכוונה*; Emby כמעט תמיד בוחר את מקור המדיה הראשי של הפריט לבד כשהוא
חסר (סטנדרטי ב-API הזה).

## שני שלבים, כמו scan_embyil.py

שלב 1 — אינדקס: כמה נתיבי Emby סטנדרטיים שעשויים לחשוף רשימה מלאה
(כולל שמות אמיתיים!) בבקשה אחת — עדיף פי כמה על ניחוש מספרים.
שלב 2 — רק אם שלב 1 לא הניב כלום: סריקת מספרים סביב שני ה-id הידועים,
בבלוקים, עצירה אוטומטית אחרי כמה בלוקים ריקים רצופים, עם תיעוד מדויק
של מה הספק ענה בפועל על מה שלא נמצא (403 אחיד = חסומים; 200 על
מזהים אחרים = המספור פשוט אחר) — בדיוק הלקח שתועד ב-scan_embyil.py.

    export EMBY_USER_ID=...  EMBY_TOKEN=...  EMBY_DEVICE_ID=...   # פרטי החשבון; לעולם לא בקובץ
    python3 scan_embyil_emby.py --probe-only     # רק בודק שזה עובד מהשרת, 5 בקשות
    python3 scan_embyil_emby.py                  # אינדקס, ואז סריקה בלי הגבלה
    python3 scan_embyil_emby.py --from 3040000 --to 3060000 --conns 10

## בטיחות

שום פרט גישה אינו כתוב כאן — שלושתם (UserId/Token/DeviceId) נקראים
מהסביבה בלבד (‎EMBY_USER_ID‎/‎EMBY_TOKEN‎/‎EMBY_DEVICE_ID‎). הסקריפט הזה
עצמו עולה לריפו הציבורי; פרטי הגישה שלך אסור שיהיו בתוכו.
"""
import argparse, asyncio, json, os, pathlib, re, sys, time

try:
    import httpx
except ImportError:
    sys.exit("חסר httpx (הוא מותקן לבוט — הרץ עם אותו פייתון)")

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
OUT = DATA / "embyil_emby_scan.json"

HOST = "play.embyil.tv"
USER_ID = os.environ.get("EMBY_USER_ID", "")
TOKEN = os.environ.get("EMBY_TOKEN", "")
DEVICE_ID = os.environ.get("EMBY_DEVICE_ID", "")
if not (USER_ID and TOKEN and DEVICE_ID):
    sys.exit("❌ חסרים EMBY_USER_ID / EMBY_TOKEN / EMBY_DEVICE_ID בסביבה. "
             "export אותם קודם (ראה הערות למעלה) — לא נכתבים כאן בכוונה.")

HDR = {"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}   # כבר הוכח שעובד מול embyil (ראה import_m3u.py)

QS = (f"UserId={USER_ID}&IsPlayback=true&AutoOpenLiveStream=true"
      f"&AudioStreamIndex=-1&MaxStreamingBitrate=1000001"
      f"&X-Emby-Client=Emby%20Web&X-Emby-Device-Name=Android%20WebView%20Android"
      f"&X-Emby-Device-Id={DEVICE_ID}&X-Emby-Client-Version=d8"
      f"&X-Emby-Token={TOKEN}&X-Emby-Language=he&reqformat=json&Static=true")


def video_url(n):
    return f"https://{HOST}/emby/videos/{n}/master.m3u8?{QS}"


# נקודות שעשויות לחשוף רשימת פריטים מלאה דרך ה-API הסטנדרטי של Emby.
INDEX_URLS = [
    f"https://{HOST}/emby/Users/{USER_ID}/Items"
    f"?api_key={TOKEN}&IncludeItemTypes=TvChannel&Limit=500",
    f"https://{HOST}/emby/Users/{USER_ID}/Items"
    f"?api_key={TOKEN}&IncludeItemTypes=LiveTvChannel&Limit=500",
    f"https://{HOST}/emby/LiveTv/Channels?api_key={TOKEN}&UserId={USER_ID}",
    f"https://{HOST}/emby/Users/{USER_ID}/Items?api_key={TOKEN}&Limit=500",
    f"https://{HOST}/emby/Items?api_key={TOKEN}&Limit=500",
]

ID_RE = re.compile(r"/emby/videos/(\d+)/")


def existing_ids() -> set:
    have = set()
    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("movies", [])
    except Exception as e:
        print(f"⚠️  לא ניתן לקרוא את {CONTENT}: {e} — הכל ידווח כחדש")
        return have
    for m in items:
        g = ID_RE.search(m.get("video_url") or "")
        if g:
            have.add(int(g.group(1)))
    return have


async def probe_only(client):
    """5 בקשות בלבד — בודק אם זה בכלל עובד מהמקום שמריצים ממנו, לפני
    שמתחייבים לסריקה שלמה. Cloudflare עונה בעמוד HTML ("Attention
    Required"), לא JSON/403 רגיל — מזוהה בנפרד כדי שההודעה תהיה ברורה."""
    print(f"בודקת גישה ל-{HOST} מהמקום הזה (5 בקשות)…\n")
    ids = [3047655, 3047699, 3047656, 3047700, 1]
    for n in ids:
        try:
            r = await client.get(video_url(n), headers=HDR, timeout=12)
            cf = "cloudflare" in r.text.lower() and "attention" in r.text.lower()
            tag = ("🚫 חסימת Cloudflare" if cf else
                   "✓ playlist" if r.text.lstrip().startswith("#EXTM3U") else
                   f"{r.status_code} (לא playlist)")
            print(f"  {n:>8}  {r.status_code}  {len(r.content):>6}B   {tag}")
        except Exception as e:
            print(f"  {n:>8}  {type(e).__name__}")
    print()


async def try_index(client):
    print("שלב 1 — מחפשת רשימה מלאה דרך ה-API של Emby…")
    hits = []
    for u in INDEX_URLS:
        try:
            r = await client.get(u, headers=HDR, timeout=15)
        except Exception as e:
            print(f"  ✗ {u[:70]:72} {type(e).__name__}")
            continue
        body = r.text or ""
        note = ""
        if r.status_code == 200 and len(body) > 50:
            try:
                data = json.loads(body)
                items = data.get("Items") if isinstance(data, dict) else data
                if isinstance(items, list) and items:
                    note = f"  ← {len(items)} פריטים!"
                    hits.append((u, body))
            except json.JSONDecodeError:
                pass
        print(f"  {'✓' if r.status_code == 200 else '✗'} {u[:70]:72} "
              f"{r.status_code} {len(body)}B{note}")
    if hits:
        p = DATA / "embyil_emby_index.json"
        p.write_text("\n\n".join(f"=== {u} ===\n{b[:200000]}" for u, b in hits),
                     encoding="utf-8")
        print(f"\n🎯 נמצאה רשימה. נשמרה ל-{p} — שלח לי אותה ואוציא ממנה הכל.")
    else:
        print("  לא נמצאה רשימה פתוחה. עוברת לסריקת מספרים.\n")
    return bool(hits)


async def probe(client, sem, n, found, sigs, errs):
    async with sem:
        for _ in range(2):
            try:
                r = await client.get(video_url(n), headers=HDR, timeout=10)
            except Exception as e:
                await asyncio.sleep(0.3)
                errs[type(e).__name__] = errs.get(type(e).__name__, 0) + 1
                continue
            if r.status_code != 200:
                errs[str(r.status_code)] = errs.get(str(r.status_code), 0) + 1
                return
            body = r.text
            if not body.lstrip().startswith("#EXTM3U"):
                errs["200 לא-playlist"] = errs.get("200 לא-playlist", 0) + 1
                return
            sig = hash(body[:400])
            found.append({"id": n, "url": video_url(n), "sig": sig})
            sigs[sig] = sigs.get(sig, 0) + 1
            return


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--from", dest="lo", type=int, default=3047000)
    ap.add_argument("--to", dest="hi", type=int, default=0,
                    help="0 = בלי תקרה, נעצר לבד")
    ap.add_argument("--conns", type=int, default=15)
    ap.add_argument("--block", type=int, default=300)
    ap.add_argument("--quit-after", type=int, default=3)
    ap.add_argument("--no-index", action="store_true")
    a = ap.parse_args()

    try:
        client = httpx.AsyncClient(follow_redirects=True, http2=True)
    except ImportError:
        client = httpx.AsyncClient(follow_redirects=True)

    async with client:
        if a.probe_only:
            await probe_only(client)
            return 0

        if not a.no_index:
            if await try_index(client):
                return 0

        have = existing_ids()
        print(f"שלב 2 — סריקת מספרים. כבר אצלנו: {len(have)}")
        print(f"מ-{a.lo}, בלוקים של {a.block}, {a.conns} במקביל, "
              f"{'בלי תקרה' if not a.hi else 'עד ' + str(a.hi)}\n")

        found, sigs, errs = [], {}, {}
        sem = asyncio.Semaphore(a.conns)
        t0, lo, empty = time.time(), a.lo, 0
        while True:
            hi = lo + a.block - 1
            if a.hi and hi > a.hi:
                hi = a.hi
            before = len(found)
            await asyncio.gather(*[probe(client, sem, n, found, sigs, errs)
                                   for n in range(lo, hi + 1)])
            got = len(found) - before
            print(f"  {lo}–{hi}:  +{got}   (סה\"כ {len(found)})", flush=True)
            empty = empty + 1 if got == 0 else 0
            if a.hi and hi >= a.hi:
                break
            if not a.hi and empty >= a.quit_after:
                print(f"\n{a.quit_after} בלוקים רצופים בלי כלום — עוצרת.")
                break
            lo = hi + 1

    noise = {s for s, c in sigs.items() if c > 8}
    real = [f for f in found if f["sig"] not in noise]
    new = [f for f in real if f["id"] not in have]
    for f in real:
        f.pop("sig", None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"all": real, "new": new}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"\n{'='*54}")
    print(f"זמן: {time.time()-t0:.0f} שניות   נסרקו עד {lo + a.block - 1}")
    print(f"ערוצים תקינים: {len(real)}")
    if errs:
        top = sorted(errs.items(), key=lambda kv: -kv[1])[:6]
        print("תשובות שלא נספרו: " + " · ".join(f"{k}×{v}" for k, v in top))
        codes = {k for k in errs if k.isdigit()}
        if codes == {"403"} and not real:
            print("\n  כל התשובות 403, ואף מזהה לא החזיר playlist.")
            print("  זו חסימה ולא שינוי מספור.")
        elif real:
            print("\n  נמצאו ערוצים — הגישה פתוחה.")
    if noise:
        print(f"(סוננו {len(found)-len(real)} תשובות ברירת-מחדל זהות)")
    print(f"חדשים שאין לנו: {len(new)}")
    print(f"נשמר: {OUT}")
    if new:
        print("\nהחדשים (עד 100 ראשונים):")
        for f in new[:100]:
            print(f"  {f['id']:>8}   {f['url']}")
        if len(new) > 100:
            print(f"  … ועוד {len(new)-100}. הכל בקובץ.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
