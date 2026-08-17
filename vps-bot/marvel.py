"""זיהוי כותרות מארוול — מקור אמת יחיד לכל סקריפטי הקטגוריות.

אין ב-TMDB "ז'אנר מארוול", ולכן זיהוי אמין נעשה לפי רשימת כותרות מוכרת
(MCU + ספיידרמן + אקס-מן + דדפול + וונום + סדרות דיסני+) בתוספת מילות-מפתח
של זכיינות לתפיסת וריאציות. עצמאי — בלי תלות ב-main.
"""
import re

MARVEL_CATEGORY = "מארוול"

_TITLES = {
    "iron man", "iron man 2", "iron man 3", "the incredible hulk", "thor",
    "thor the dark world", "thor ragnarok", "thor love and thunder",
    "captain america the first avenger", "captain america the winter soldier",
    "captain america civil war", "captain america brave new world",
    "the avengers", "avengers age of ultron", "avengers infinity war",
    "avengers endgame", "guardians of the galaxy", "guardians of the galaxy vol 2",
    "guardians of the galaxy vol 3", "ant man", "ant man and the wasp",
    "ant man and the wasp quantumania", "doctor strange",
    "doctor strange in the multiverse of madness", "black panther",
    "black panther wakanda forever", "captain marvel", "the marvels",
    "spider man homecoming", "spider man far from home", "spider man no way home",
    "black widow", "shang chi and the legend of the ten rings", "eternals",
    "deadpool", "deadpool 2", "deadpool and wolverine", "deadpool wolverine",
    "venom", "venom let there be carnage", "venom the last dance", "morbius",
    "madame web", "kraven the hunter", "spider man", "spider man 2", "spider man 3",
    "the amazing spider man", "the amazing spider man 2", "x men", "x2",
    "x men the last stand", "x men first class", "x men days of future past",
    "x men apocalypse", "x men dark phoenix", "the wolverine", "logan",
    "x men origins wolverine", "fantastic four", "the fantastic four first steps",
    "blade", "wandavision", "the falcon and the winter soldier", "loki",
    "hawkeye", "moon knight", "ms marvel", "she hulk attorney at law",
    "secret invasion", "echo", "agatha all along", "daredevil",
    "daredevil born again", "the punisher", "jessica jones", "luke cage",
    "iron fist", "the defenders", "agents of shield",
}
_KEYWORDS = ("avengers", "x men", "deadpool", "spider man", "iron man",
             "captain america", "guardians of the galaxy", "ant man",
             "black panther", "doctor strange", "thor", "wolverine",
             "venom", "loki", "wandavision", "moon knight", "she hulk")

_EXT = re.compile(r"\.(mkv|mp4|avi|mov|webm|m4v|ts)$", re.I)
_QUALITY = re.compile(r"\b(1080p|720p|2160p|4k|hdr|bluray|web ?dl|webrip|x264|x265|hevc)\b", re.I)


def norm(s: str) -> str:
    s = _EXT.sub("", str(s or ""))
    s = s.replace(".", " ").replace("_", " ").replace("-", " ").lower()
    s = _QUALITY.sub(" ", s)
    s = re.sub(r"[^\w֐-׿]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def looks_marvel(*names) -> bool:
    """True אם אחת מהכותרות שנמסרו (עברית/אנגלית) נראית כמו מארוול."""
    for cand in names:
        n = norm(cand)
        if not n:
            continue
        if n in _TITLES:
            return True
        if any(kw in n for kw in _KEYWORDS):
            return True
    return False
