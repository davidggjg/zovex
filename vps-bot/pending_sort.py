#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pending_sort — סידור הפרקים שממתינים לאישור (רק הממתינים, לא כל האתר).

לכל פרק ממתין:
  ✅ הסדרה קיימת באתר והפרק/העונה חדשים  → מתווסף לסדרה, עם הפוסטר/התקציר/ה-slug שלה
  ♻️ כבר באתר (אותו קובץ, או אותה עונה+פרק) → לא עולה; יורד מרשימת הממתינים
  ❓ לא בטוח לאיזו סדרה / סדרה חדשה          → לא נוגעים; נשאר לך בפאנל
סרטים ממתינים — לא נוגעים.

ברירת מחדל: רק מציג תוכנית. --apply: מבצע (דרך ‎/content/mutate‎ ו-‎/uploads/clear‎
של השרת המקומי — אותם נתיבים שהפאנל משתמש בהם; הסיסמה נקראת מהשרת).
    sudo python3 pending_sort.py            # תוכנית בלבד
    sudo python3 pending_sort.py --apply    # ביצוע
"""
import json, os, re, sys, urllib.request
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "."))
BASE = os.environ.get("ZOVEX_BASE", "http://127.0.0.1:8000")
AUTO = float(os.environ.get("AUTO_MATCH", "0.8"))      # סף התאמה לשיוך אוטומטי


def norm(s):
    s = str(s or "").lower()
    s = re.sub(r"[._\-–—:|()\[\]{}\"'׳״!?,•·+]", " ", s)
    s = re.sub(r"עונה\s*\d+|פרק\s*\d+|ע\s*\d+\s*פ\s*\d+|מתורגם|כתוביות|תרגום\s*מובנה|דיבוב", " ", s)
    s = re.sub(r"\b(s\d{1,2}(e\d{1,3})?|season\s*\d+|e\d{1,3}|ep\s*\d+|\d{3,4}p|hd|fhd|web(-?dl|rip)?|hebsub|x26[45]|hevc)\b", " ", s)
    s = re.sub(r"\d+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def bigrams(s):
    s = s.replace(" ", ""); out = {}
    for i in range(len(s) - 1):
        out[s[i:i+2]] = out.get(s[i:i+2], 0) + 1
    return out


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return 0.0
    if a == b: return 1.0
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    # מוכל בתוך: רק כשהאורכים קרובים ("פאודה"⊂"פאודה ישראל") — לא "בית"⊂"בית הנייר"
    if len(short) >= 3 and short in long_:
        return 0.9 if len(short) / len(long_) >= 0.6 else 0.7
    ta, tb = set(a.split()), set(b.split()); i = len(ta & tb)
    jac = i / (len(ta) + len(tb) - i)
    A, B = bigrams(a), bigrams(b)
    inter = sum(min(v, B.get(k, 0)) for k, v in A.items()); tot = sum(A.values()) + sum(B.values())
    return max(jac, (2 * inter / tot if tot else 0) * 0.95)


def is_series(e):
    return bool(e.get("series_name")) or e.get("media_kind") == "tv" or e.get("episode_number") is not None


def msg_key(e):
    m = re.search(r"/stream/(-?\d+)/(\d+)", str(e.get("video_url") or e.get("video_id") or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def plan(content, pending):
    series = {}
    for e in content:
        sn = e.get("series_name")
        if not sn: continue
        s = series.setdefault(sn, {"eps": set(), "meta": None})
        s["eps"].add((int(e.get("season_number") or 1), int(e.get("episode_number") or 0)))
        if s["meta"] is None or (not s["meta"].get("thumbnail_url") and e.get("thumbnail_url")):
            s["meta"] = e
    on_fu = {e.get("file_unique_id") for e in content if e.get("file_unique_id")}
    on_msg = {k for k in (msg_key(e) for e in content) if k}

    add, dup, manual, skipped_movies = [], [], [], 0
    taken = set()                                   # מונע שני ממתינים לאותו פרק
    for p in pending:
        if not is_series(p):
            skipped_movies += 1; continue
        name = p.get("series_name") or p.get("title") or ""
        se, ep = int(p.get("season_number") or 1), int(p.get("episode_number") or 0)
        if (p.get("file_unique_id") and p["file_unique_id"] in on_fu) or (msg_key(p) and msg_key(p) in on_msg):
            dup.append((p, "אותו קובץ כבר באתר")); continue
        best, score = None, 0.0
        for sn, s in series.items():
            m = s["meta"] or {}
            sc = max(sim(name, sn), sim(name, m.get("en_title") or ""),
                     sim(name, (m.get("custom_slug") or "").replace("-", " ")))
            if sc > score: best, score = sn, sc
        if not best or score < AUTO:
            manual.append((p, best, score)); continue
        if (se, ep) in series[best]["eps"] or (best, se, ep) in taken:
            dup.append((p, f"ע{se}פ{ep} כבר קיים ב«{best}»")); continue
        taken.add((best, se, ep))
        add.append((p, best, score))
    return add, dup, manual, skipped_movies, series


def build_item(p, target, series):
    m = series[target]["meta"] or {}
    it = dict(p)
    it.update({"series_name": target, "title": target,
               "custom_slug": m.get("custom_slug") or p.get("custom_slug"),
               "category": m.get("category") or p.get("category") or "סדרות",
               "thumbnail_url": p.get("thumbnail_url") or m.get("thumbnail_url") or "",
               "backdrop_url": p.get("backdrop_url") or m.get("backdrop_url") or "",
               "description": p.get("description") or m.get("description") or "",
               "year": p.get("year") or m.get("year") or "",
               "en_title": m.get("en_title") or p.get("en_title") or "",
               "tmdb_id": m.get("tmdb_id") or p.get("tmdb_id") or 0})
    return it


def panel_password():
    env = {}
    p = Path("/opt/zovex-bot/.env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
    if not env.get("PANEL_PASSWORD"):
        try:
            import subprocess
            pid = subprocess.run(["systemctl", "show", "zovex-bot", "-p", "MainPID", "--value"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            for part in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                if part.startswith(b"PANEL_PASSWORD="):
                    env["PANEL_PASSWORD"] = part.split(b"=", 1)[1].decode()
        except Exception:
            pass
    return env.get("PANEL_PASSWORD") or os.environ.get("PANEL_PASSWORD") or ""


def get(path):
    req = urllib.request.Request(BASE + path, headers={"Referer": "https://zovex.duckdns.org/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"[]")


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def main():
    apply = "--apply" in sys.argv
    if os.environ.get("ZOVEX_DATA"):          # קבצים מקומיים (לבדיקות)
        content = json.loads((DATA / "content.json").read_text(encoding="utf-8"))
        pending = json.loads((DATA / "new_uploads.json").read_text(encoding="utf-8"))
    else:                                     # מהשרת עצמו — לא תלוי איפה הקבצים שמורים
        content = get("/content")
        pending = get("/uploads/new").get("items", [])
    add, dup, manual, movies, series = plan(content, pending)

    print(f"ממתינים: {len(pending)}  (סרטים שלא נוגעים בהם: {movies})\n")
    print(f"✅ יתווספו לסדרה קיימת ({len(add)}):")
    by = {}
    for p, t, sc in add: by.setdefault(t, []).append((p, sc))
    for t, lst in by.items():
        eps = ", ".join(f"ע{int(p.get('season_number') or 1)}פ{p.get('episode_number')}" for p, _ in sorted(lst, key=lambda x: (int(x[0].get('season_number') or 1), int(x[0].get('episode_number') or 0))))
        names = sorted({p.get('series_name') or p.get('title') for p, _ in lst})
        print(f"   «{t}» ← {len(lst)} פרקים: {eps}")
        if names != [t]: print(f"        (שמות מהבוט: {', '.join(names)[:120]})")
    print(f"\n♻️ כבר באתר — לא יעלו, ירדו מרשימת הממתינים ({len(dup)}):")
    for p, why in dup[:40]:
        print(f"   {p.get('series_name') or p.get('title')}  ע{p.get('season_number')}פ{p.get('episode_number')} — {why}")
    if len(dup) > 40: print(f"   …ועוד {len(dup)-40}")
    print(f"\n❓ נשארים לך בפאנל — לא בטוח / סדרה חדשה ({len(manual)}):")
    for p, best, sc in manual[:40]:
        hint = f" (הכי קרוב: «{best}», {int(sc*100)}%)" if best and sc >= 0.4 else ""
        print(f"   {p.get('series_name') or p.get('title')}  ע{p.get('season_number')}פ{p.get('episode_number')}{hint}")
    if len(manual) > 40: print(f"   …ועוד {len(manual)-40}")

    if not apply:
        print("\nזו תוכנית בלבד — לא שונה כלום. לביצוע:  sudo python3 pending_sort.py --apply")
        return 0
    if not add and not dup:
        print("\nאין מה לבצע."); return 0
    pw = panel_password()
    if not pw: sys.exit("❌ לא נמצאה PANEL_PASSWORD בשרת — לא בוצע כלום")
    if add:
        items = [build_item(p, t, series) for p, t, _ in add]
        r = post("/content/mutate", {"password": pw, "delete_ids": [], "upsert": items})
        print(f"\n✓ נוספו לאתר: {r.get('added', 0)} (עודכנו {r.get('updated', 0)})")
    ids = [p.get("channel_msg_id") for p, *_ in add + [(d[0],) for d in dup] if p.get("channel_msg_id") is not None]
    if ids:
        post("/uploads/clear", {"password": pw, "channel_msg_ids": ids})
        print(f"✓ ירדו מרשימת הממתינים: {len(ids)}")
    print("✅ בוצע. מה שסומן ❓ מחכה לך בפאנל (העלאות מהבוט).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
