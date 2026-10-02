#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_hide_dead_channels — ערוץ שהספק מסרב לו אינו מוצג, וחוזר לבד.

## למה

‎dns_check‎ ו-‎probe_headers‎ קבעו: 44 ערוצים על שרת אחד מחזירים
‎403 direct‎, זה אינו DNS, אינו כותרות ואינו ה-IP שלנו. בלי קישור אחד
עובד מהספק אין מה לתקן בקישורים — והוא בחו"ל לחודשים.

ובינתיים 44 הערוצים **עדיין מופיעים**. כל מי שלוחץ עליהם מקבל שגיאה,
וזה הופך את דף השידורים החיים למלכודת: המשתמש אינו יודע אילו ערוצים
עובדים, ולכן הוא מסיק שהאפליקציה שבורה. 55 הערוצים שכן עובדים נענשים
על 44 שלא.

## מה משתנה

בודק ברקע כל ערוץ חי, ומסתיר מהקטלוג את מי שאינו עונה. כשהספק יחזור —
הערוץ חוזר **לבד**, בלי עדכון, בלי פקודה ובלי שאיש ייגע בכלום.

הבדיקה היא ‎_hls_upstream_alive‎ שכבר קיימת: דרך המסלול הרגיל שלנו
ב-127.0.0.1, עם אסימון הבדיקה. כלומר אותו מסלול בדיוק שהנגן מקבל, עם
אותה סכימה, אותן הרשאות ואותה בדיקת playlist-ריק — ולא מימוש שני
שיתפצל ממנו.

## שלוש הגנות, וכל אחת בגלל תקלה שקרתה

**① תקרה: אם יותר מ-60% מהערוצים "מתים", לא מסתירים כלום.**

זו ההגנה החשובה. שלוש פעמים בשבועות האחרונים הרגרסיות שלי עצמן גרמו
לכל הערוצים להיראות מתים — סימון-מת שהזין את עצמו, ffmpeg בלי אסימון,
ונפילה חזרה שנעקפה. סורק תמים היה מרוקן את דף השידורים החיים לגמרי,
ואז הבאג שלי היה הופך לנתון קבוע בקטלוג. אם כמעט הכל נראה מת — **אנחנו**
שבורים, לא הספק, ואז הנכון הוא לא לגעת ולצעוק ביומן.

**② שלושה כישלונות רצופים כדי להסתיר, הצלחה אחת כדי להחזיר.**

הסתרה היא החלטה שמשפיעה על כל המשתמשים; החזרה היא ביטול שלה. לכן
הראשונה שמרנית והשנייה מיידית. תקלת רשת של שנייה אינה מסתירה ערוץ.

**③ המצב נשמר לקובץ, וערוץ חדש מתחיל כגלוי.**

מפתח שאינו בקובץ נקרא כ"עובד עד שיוכח אחרת" — ברירת המחדל של ספק
חדש או ערוץ שנוסף היא להיראות, לא להיעלם.

## מה זה לא עושה

אינו מוחק דבר מהקטלוג, אינו נוגע ב-content.json ואינו משנה קישורים.
רק מסנן בהגשה. ההסתרה מתפוגגת מהמטמון תוך ‎CONTENT_CACHE_TTL‎ (180ש׳),
ולכן גם החזרה מורגשת תוך שלוש דקות לכל היותר.

וערוץ מוסתר עדיין מתנגן בקישור ישיר לפי מזהה — ההסתרה היא מהרשימות,
לא חסימה.

    python3 fix_hide_dead_channels.py --check
    python3 fix_hide_dead_channels.py
    python3 fix_hide_dead_channels.py --revert

אחרי ההחלה:  systemctl restart zovex-bot
ולראות מה מוסתר:  cat /opt/zovex-bot/data/channels_down.json
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_hide_dead"
MARK = "fix_hide_dead_channels"

# ── 1. המצב, ההחלטה והבודק ───────────────────────────────────────────────
A_STATE = '''def _hls_mark_dead(key: str, reason: str) -> None:
    """סימון קצר-מועד. ההתאוששות של הספק לא דורשת מאיתנו כלום."""
    _hls_dead[key] = (time.time() + HLS_DEAD_TTL, reason)
'''

N_STATE = '''def _hls_mark_dead(key: str, reason: str) -> None:
    """סימון קצר-מועד. ההתאוששות של הספק לא דורשת מאיתנו כלום."""
    _hls_dead[key] = (time.time() + HLS_DEAD_TTL, reason)


# ── [fix_hide_dead_channels] ערוץ שהספק מסרב לו אינו מוצג ────────────────
#
# ‎_hls_dead‎ שמעל הוא סימון של 45 שניות לבקשה בודדת. זה משהו אחר: מצב
# מתמשך של ערוץ, שנקבע בבדיקה תקופתית ומשפיע על מה שהקטלוג מגיש.
CH_DOWN_FILE = DATA_DIR / "channels_down.json"
CH_DOWN_FAILS = int(os.environ.get("CH_DOWN_FAILS", "3"))
CH_PROBE_EVERY = float(os.environ.get("CH_PROBE_EVERY", "600"))
CH_PROBE_GAP = float(os.environ.get("CH_PROBE_GAP", "0.4"))
# אם יותר מזה "מת" — אנחנו שבורים, לא הספק. ראה ההסבר בפאצ'.
CH_DOWN_CEILING = float(os.environ.get("CH_DOWN_CEILING", "0.6"))

_ch_state: dict = {}            # key -> {"fails": int, "down": bool, ...}


def _ch_key(e) -> str:
    """מפתח יציב לערוץ, מתוך כתובת הרלֵיי שלו. ריק = אין מה לבדוק."""
    v = (e.get("video_url") or "").strip()
    m = re.search(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)", v)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def _ch_note(state: dict, key: str, ok: bool, why: str = "",
             now: float = None) -> bool:
    """רושם תוצאת בדיקה. מחזיר True אם מצב ההסתרה של הערוץ השתנה.

    שלושה כישלונות רצופים מסתירים; הצלחה אחת מחזירה. אסימטרי במכוון —
    הסתרה משפיעה על כל המשתמשים, החזרה רק מבטלת אותה.
    """
    now = now if now is not None else time.time()
    ent = state.setdefault(key, {"fails": 0, "down": False, "since": 0.0,
                                 "why": ""})
    was = ent["down"]
    if ok:
        ent["fails"] = 0
        ent["down"] = False
        ent["why"] = ""
        if was:
            ent["since"] = 0.0
    else:
        ent["fails"] += 1
        ent["why"] = why
        if ent["fails"] >= CH_DOWN_FAILS and not was:
            ent["down"] = True
            ent["since"] = now
    return ent["down"] != was


def _ch_hidden(state: dict, total: int) -> frozenset:
    """אילו מפתחות מוסתרים **בפועל**, אחרי התקרה.

    התקרה אינה קוסמטיקה: בלעדיה באג שלנו ברלֵיי מרוקן את דף השידורים
    החיים, וזה קרה שלוש פעמים. אם כמעט הכל נראה מת, עדיף להציג ערוץ
    שבור מלהציג דף ריק — ולצעוק ביומן.
    """
    down = frozenset(k for k, v in state.items() if v.get("down"))
    if total <= 0:
        # לא יודעים כמה ערוצים יש ⇒ אי אפשר להעריך את התקרה. זה קורה
        # לפני הסבב הראשון, ועל קובץ מצב ישן או מעוות. בלי הענף הזה
        # התקרה **נעקפת לגמרי** דווקא במצב שבו אין לנו מידע, וזה בדיוק
        # ההיפך מהמטרה שלה. כשלא יודעים — מציגים.
        return frozenset()
    if len(down) > total * CH_DOWN_CEILING:
        return frozenset()
    return down


def _ch_visible_now() -> frozenset:
    """המפתחות המוסתרים, לשימוש בהגשה. זול — בלי קריאת קבצים."""
    return _ch_hidden(_ch_state, _ch_total_seen[0])


_ch_total_seen = [0]            # כמה ערוצים חיים נראו בסבב האחרון


def _ch_load() -> None:
    """טוען מצב שמור. מפתח שאינו בקובץ נקרא כגלוי."""
    try:
        raw = json.loads(CH_DOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    for k, v in (raw.get("channels") or {}).items():
        if isinstance(v, dict):
            _ch_state[k] = {"fails": int(v.get("fails") or 0),
                            "down": bool(v.get("down")),
                            "since": float(v.get("since") or 0.0),
                            "why": str(v.get("why") or "")}
    _ch_total_seen[0] = int(raw.get("total") or 0)


def _ch_save() -> None:
    """כותב את המצב. גם כדי שאפשר יהיה לראות מה מוסתר ולמה."""
    try:
        CH_DOWN_FILE.write_text(json.dumps(
            {"updated": time.time(), "total": _ch_total_seen[0],
             "hidden": sorted(_ch_visible_now()),
             "channels": _ch_state}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except Exception as e:
        log.warning("channels_down: לא נשמר — %s", e)


async def _ch_probe_loop():
    """בודק כל ערוץ חי, ומסתיר את מי שאינו עונה.

    רץ בהפוגות: ערוץ-ערוץ עם השהייה, כדי שהבדיקה לא תהיה גל של עשרות
    בקשות לספק בבת אחת — זה בדיוק מה שגורם לחסימות.
    """
    _ch_load()
    await asyncio.sleep(30)          # שהשרת והבריכה יתייצבו קודם
    while True:
        try:
            items = [e for e in load_content() if _is_live_item(e)]
            keys = []
            seen = set()
            for e in items:
                k = _ch_key(e)
                if k and k not in seen:
                    seen.add(k)
                    keys.append(k)
            _ch_total_seen[0] = len(keys)
            changed = 0
            for k in keys:
                host, _, path = k.partition("/")
                ok, why = await _hls_upstream_alive(host, path)
                if _ch_note(_ch_state, k, ok, why):
                    changed += 1
                await asyncio.sleep(CH_PROBE_GAP)
            hidden = _ch_visible_now()
            raw_down = sum(1 for v in _ch_state.values() if v.get("down"))
            if raw_down and not hidden:
                log.error("ערוצים: %d/%d נראים מתים — מעל התקרה (%.0f%%). "
                          "לא מסתיר כלום: זו כמעט תמיד תקלה אצלנו ולא אצל "
                          "הספק.", raw_down, len(keys), CH_DOWN_CEILING * 100)
            else:
                log.info("ערוצים: %d/%d מוסתרים%s", len(hidden), len(keys),
                         f" ({changed} שינויים)" if changed else "")
            _ch_save()
        except Exception as e:
            log.warning("_ch_probe_loop: %s", e)
        await asyncio.sleep(CH_PROBE_EVERY)
'''

# ── 2. הסינון בהגשה ──────────────────────────────────────────────────────
A_LITE = '''def _lite_items():
    items = []
    for e in _expand_urls(load_content()):
        d = {k: v for k, v in e.items() if k not in _LITE_DROP}
        if d.get("video_id") and d.get("video_id") == d.get("video_url"):
            d.pop("video_id", None)
        items.append(d)
    return items
'''

N_LITE = '''def _lite_items():
    items = []
    # [fix_hide_dead_channels] ערוץ שהספק מסרב לו אינו מוצג. כאן ולא
    # בכל נתיב בנפרד, כי מכאן נבנים גם /content וגם /content/live —
    # סינון באחד מהם היה משאיר את הערוץ המת בשני.
    hidden = _ch_visible_now()
    for e in _expand_urls(load_content()):
        if hidden and _is_live_item(e) and _ch_key(e) in hidden:
            continue
        d = {k: v for k, v in e.items() if k not in _LITE_DROP}
        if d.get("video_id") and d.get("video_id") == d.get("video_url"):
            d.pop("video_id", None)
        items.append(d)
    return items
'''

# ── 3. הפעלה ─────────────────────────────────────────────────────────────
A_START = '''    asyncio.create_task(staged_bot_startup())
    log.info("All systems ready ✅ BASE_URL=%s", BASE_URL)
'''

N_START = '''    asyncio.create_task(staged_bot_startup())
    # [fix_hide_dead_channels] מסתיר ערוצים שהספק מסרב להם, ומחזיר אותם
    # לבד כשהוא חוזר. אחרון בכוונה: הוא ישן 30 שניות לפני הסבב הראשון.
    asyncio.create_task(_ch_probe_loop())
    log.info("All systems ready ✅ BASE_URL=%s", BASE_URL)
'''

EDITS = [
    ("מצב, החלטה ובודק", A_STATE, N_STATE, 1),
    ("סינון בהגשה", A_LITE, N_LITE, 1),
    ("הפעלה", A_START, N_START, 1),
]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"לא נמצאה הפונקציה {name}")


def code_only(text: str) -> str:
    out = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    joined = "\n".join(out)
    parts = joined.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else joined


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    # התלויות שהפאצ' מסתמך עליהן קיימות
    for need in ("_hls_upstream_alive", "_is_live_item", "load_content",
                 "DATA_DIR", "CONTENT_CACHE_TTL"):
        assert need in out, f"חסר {need} — הפאצ' מסתמך עליו"

    # ── הפונקציות הטהורות מורצות בפועל, לא נקראות בעין ──────────────────
    import re as _re
    import time as _time
    ns = {"re": _re, "time": _time, "CH_DOWN_FAILS": 3,
          "CH_DOWN_CEILING": 0.6}
    for fn in ("_ch_key", "_ch_note", "_ch_hidden"):
        exec(fn_source(out, fn), ns)

    # ① גזירת מפתח
    key = ns["_ch_key"]
    assert key({"video_url": "%BASE%/hls-relay/h.x:86/p/g/s/412/i.m3u8"}) \
        == "h.x:86/p/g/s/412/i.m3u8"
    assert key({"video_url": "https://z/hls-relay/_fix/h.x/a/b.m3u8"}) \
        == "h.x/a/b.m3u8", "מסלול _fix נותן את אותו מפתח כמו הרגיל"
    assert key({"video_url": "https://other/x.m3u8"}) == ""
    assert key({}) == "" and key({"video_url": None}) == ""

    # ② ההחלטה: שלושה כישלונות מסתירים, הצלחה אחת מחזירה
    note, st = ns["_ch_note"], {}
    assert note(st, "a", False, "403") is False, "כישלון ראשון אינו מסתיר"
    assert note(st, "a", False, "403") is False, "ולא השני"
    assert note(st, "a", False, "403") is True, "השלישי כן"
    assert st["a"]["down"] and st["a"]["since"] > 0
    assert note(st, "a", False, "403") is False, "מוסתר שנכשל שוב — בלי שינוי"
    assert note(st, "a", True) is True, "הצלחה אחת מחזירה"
    assert not st["a"]["down"] and st["a"]["fails"] == 0

    # והמונה מתאפס: שני כישלונות, הצלחה, ואז שניים — אינם חמישה
    st2 = {}
    note(st2, "b", False); note(st2, "b", False); note(st2, "b", True)
    assert note(st2, "b", False) is False and note(st2, "b", False) is False, \
        "המונה לא התאפס — ערוץ מהבהב היה נעלם"

    # ③ התקרה — ההגנה שבגללה הפאצ' הזה בטוח
    hid = ns["_ch_hidden"]
    many = {f"k{i}": {"down": True} for i in range(44)}
    assert hid(many, 99) == frozenset(many), "44 מתוך 99 — מוסתרים"
    allof = {f"k{i}": {"down": True} for i in range(99)}
    assert hid(allof, 99) == frozenset(), "99 מתוך 99 — לא מסתירים כלום"
    assert hid({f"k{i}": {"down": True} for i in range(60)}, 99) \
        == frozenset(), "60% ומעלה — התקרה חוסמת"
    assert len(hid({f"k{i}": {"down": True} for i in range(59)}, 99)) == 59, \
        "מתחת לתקרה — עובר"
    assert hid({}, 0) == frozenset(), "בלי ערוצים — בלי הסתרה, ובלי חילוק באפס"
    assert hid({"a": {"down": True}}, 0) == frozenset(), "total=0 אינו מסתיר"

    # ומוטציה: תקרה שהפוכה לכיוון הלא נכון חייבת להיתפס
    assert hid(allof, 99) != frozenset(allof), \
        "התקרה אינה פועלת — באג ברלֵיי ירוקן את דף השידורים"

    # ④ הסינון עצמו: מוסתר יוצא, גלוי נשאר, ולא-חי אינו נוגע בכלל
    lite = code_only(fn_source(out, "_lite_items"))
    assert "_ch_visible_now()" in lite, "הסינון אינו קורא למצב"
    assert "_is_live_item(e)" in lite, "הסינון חל גם על מה שאינו שידור חי"
    assert "continue" in lite

    def filt(items, hidden):
        out_ = []
        for e in items:
            if hidden and e["live"] and e["k"] in hidden:
                continue
            out_.append(e)
        return [e["k"] for e in out_]

    items = [{"k": "a", "live": True}, {"k": "b", "live": True},
             {"k": "c", "live": False}, {"k": "", "live": True}]
    assert filt(items, frozenset({"a"})) == ["b", "c", ""]
    assert filt(items, frozenset()) == ["a", "b", "c", ""], \
        "בלי מוסתרים — הקטלוג זהה לחלוטין"
    assert filt(items, frozenset({"c"})) == ["a", "b", "c", ""], \
        "פריט שאינו שידור חי אינו מוסתר גם אם מפתחו ברשימה"

    # ⑤ הלופ מופעל, ובודק דרך המסלול הקיים ולא במימוש שני
    loop = code_only(fn_source(out, "_ch_probe_loop"))
    assert "_hls_upstream_alive" in loop, "הבדיקה אינה דרך המסלול הקיים"
    assert "CH_PROBE_GAP" in loop and "asyncio.sleep" in loop, \
        "אין הפוגה בין בקשות — זה גל שמביא חסימה"
    assert "_ch_save()" in loop
    start = code_only(fn_source(out, "startup"))
    assert "_ch_probe_loop())" in start, "הלופ אינו מופעל"

    # ⑥ והטעינה סלחנית: קובץ פגום אינו מפיל את השרת
    ns2 = {"json": __import__("json"), "time": _time,
           "_ch_state": {}, "_ch_total_seen": [0],
           "CH_DOWN_FILE": __import__("pathlib").Path("/nonexistent/x.json")}
    exec(fn_source(out, "_ch_load"), ns2)
    ns2["_ch_load"]()                      # לא זורק על קובץ שאינו קיים
    assert ns2["_ch_state"] == {}, "קובץ חסר ⇒ הכל גלוי"


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit(f"אין קובץ ב-{PATH} (אפשר MAIN_PY=...)")
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — "
                     "לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("systemctl restart zovex-bot")
    print()
    print("הסבב הראשון מתחיל 30 שניות אחרי העלייה, ולוקח כדקה.")
    print("אחר כך:")
    print("  journalctl -u zovex-bot -n 50 | grep ערוצים")
    print("  cat /opt/zovex-bot/data/channels_down.json")
    print()
    print("ערוץ חוזר לבד ברגע שהספק עונה לו — עד 3 דקות עד שהמטמון")
    print("מתחלף. אין צורך בפקודה, בעדכון או בהרצה חוזרת.")


if __name__ == "__main__":
    main()
