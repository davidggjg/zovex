"""הגדרות — הכל ממשתני סביבה (.env). בלי סודות בקוד."""
import os


def _ids(raw: str) -> set[int]:
    out = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# בעלים בדרגת-על — כמה מזהים, מופרדים בפסיק. הם מאשרים ערוצים ומנהלים הכל.
OWNER_IDS = _ids(os.environ.get("OWNER_IDS", os.environ.get("OWNER_ID", "")))

# הקבוצה שהבוט מנהל (שבת/מנעולים). אופציונלי.
MANAGED_GROUP_ID = int(os.environ.get("MANAGED_GROUP_ID", "0") or "0")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Jerusalem")

# מאגר ZOVEX הקיים — נטען כמקור תוכן ראשוני (11K+ פריטים) לצד ערוצים מחוברים.
ZOVEX_CONTENT_URL = os.environ.get("ZOVEX_CONTENT_URL", "https://zovex.duckdns.org/content/lite")
CATALOG_TTL = int(os.environ.get("CATALOG_TTL", "300"))

DB_PATH = os.environ.get("DB_PATH", "/app/data/zovex_bot.db")

# סוד לחתימת סשן הדשבורד (מיוצר אקראית אם חסר; יושב ב-.env)
DASHBOARD_SECRET = os.environ.get("DASHBOARD_SECRET", "")


def missing() -> list[str]:
    out = []
    if not API_ID:
        out.append("API_ID")
    if not API_HASH:
        out.append("API_HASH")
    if not BOT_TOKEN:
        out.append("BOT_TOKEN")
    if not OWNER_IDS:
        out.append("OWNER_IDS")
    return out
