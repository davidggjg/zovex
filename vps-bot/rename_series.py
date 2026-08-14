"""משנה שם של סדרה בקטלוג (וגם את הכותרת וה-slug של כל הפרקים).

נחוץ כשפרקים נוספו עם תגית המעלה בשם — למשל "לולו סרטים דרגון בול סופר"
במקום "דרגון בול סופר".

    python3 rename_series.py --from "לולו סרטים דרגון בול סופר" --to "דרגון בול סופר"
    python3 rename_series.py --from "..." --to "..." --apply    # מבצע בפועל

בלי --apply זו הרצה יבשה. הכלי מגבה את הקטלוג לפני כל שינוי.
"""
import argparse, json, pathlib, re, shutil, time

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
BAK = DATA / "content_backups"

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="src", required=True, help="השם הנוכחי")
ap.add_argument("--to", dest="dst", required=True, help="השם הרצוי")
ap.add_argument("--slug", default="", help="slug חדש (ברירת מחדל: נגזר מהשם)")
ap.add_argument("--apply", action="store_true", help="לבצע בפועל")
args = ap.parse_args()


def slugify(name: str) -> str:
    s = re.sub(r"[^\w֐-׿]+", "-", name.strip().lower())
    return re.sub(r"-{2,}", "-", s).strip("-")


content = json.loads(CONTENT.read_text(encoding="utf-8"))
src, dst = args.src.strip(), args.dst.strip()
new_slug = args.slug.strip() or slugify(dst)

hits = [e for e in content
        if (e.get("series_name") or "").strip() == src or (e.get("title") or "").strip() == src]
print(f"בקטלוג {len(content)} פריטים. תואמים ל-{src!r}: {len(hits)}")
if not hits:
    print("לא נמצא — בדוק את השם המדויק.")
    raise SystemExit(1)

eps = sorted(e.get("episode_number") for e in hits if e.get("episode_number"))
if eps:
    print(f"פרקים: {len(eps)}  ({min(eps)}–{max(eps)})")
print(f"\nישתנה ל: {dst!r}   slug: {new_slug!r}")

if not args.apply:
    print("\nהרצה יבשה — לא שונה כלום. להחלה הוסף --apply")
    raise SystemExit(0)

BAK.mkdir(parents=True, exist_ok=True)
shutil.copy(CONTENT, BAK / f"content_{int(time.time())}.json")

changed = 0
for e in hits:
    if (e.get("series_name") or "").strip() == src:
        e["series_name"] = dst
    if (e.get("title") or "").strip() == src:
        e["title"] = dst
    e["custom_slug"] = new_slug
    changed += 1

CONTENT.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n✅ עודכנו {changed} פריטים. גובה לפני השינוי.")
print("   הפעל מחדש:  sudo systemctl restart zovex-bot")
