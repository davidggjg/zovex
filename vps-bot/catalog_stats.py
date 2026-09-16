#!/usr/bin/env python3
"""
catalog_stats — מה באמת חסר בקטלוג, ומה מהמלאי הקיים חשוד.

נכתב כי ניחשתי במקום למדוד. התיעוד של tmdb_enrich טען "description
חסר ברוב הפריטים", ואז דגימה אקראית של 187 פריטים החזירה **אפס**
תיאורים להשלמה. אחד מהשניים לא נכון, ואין סיבה להתלבט: הקובץ על
הדיסק.

הוא גם סופר את מה שמריח רע — en_title שכתוב בעברית. שם "באנגלית"
בעברית אינו שם באנגלית, והוא טביעת האצבע של רשומת TMDB זבל: אותו
סוג רשומה שהחזיקה את "300" על מזהה 1416873 (בלי פוסטר, בלי תיאור,
ציון תוכן 24/100) במקום על 1271.

    python3 catalog_stats.py
    python3 catalog_stats.py /נתיב/אחר/content.json
"""
import json, sys
P = sys.argv[1] if len(sys.argv) > 1 else "/opt/zovex-bot/data/content.json"
items = json.loads(open(P, encoding="utf-8").read())
live = [i for i in items if i.get("is_live")]
vod = [i for i in items if not i.get("is_live")]
def he(s):
    return any("֐" <= c <= "׿" for c in str(s or ""))
print(f"{len(items)} פריטים · {len(vod)} VOD · {len(live)} שידור חי\n")
print(f"{'שדה':<16}{'יש':>8}{'מתוך VOD':>11}")
for f in ("tmdb_id", "description", "en_title", "year",
          "thumbnail_url", "category"):
    n = sum(1 for i in vod if str(i.get(f) or "").strip())
    print(f"{f:<16}{n:>8}{100*n//max(len(vod),1):>10}%")
print()
bad = [i for i in vod if he(i.get("en_title"))]
print(f"en_title שהוא בעצם עברית:  {len(bad)}")
for i in bad[:8]:
    print(f"   {(i.get('series_name') or i.get('title') or '?')[:28]:<30} "
          f"en_title={str(i.get('en_title'))[:26]}  tmdb_id={i.get('tmdb_id')}")
withid = [i for i in vod if i.get("tmdb_id")]
nodesc = [i for i in withid if not str(i.get("description") or "").strip()]
print(f"\nיש מזהה ואין תיאור:  {len(nodesc)} מתוך {len(withid)}")
