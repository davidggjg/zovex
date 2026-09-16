#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmdb_names — כלל ההתאמה הדטרמיניסטי, במקום אחד.

גם tmdb_exact_probe (שמודד אותו) וגם tmdb_ai_match (שמשתמש בו כדי לא
לשאול את המודל לחינם) קוראים מכאן, כדי שלא יהיו שתי גרסאות של אותו
כלל שמתפצלות עם הזמן.
"""
import json, re, unicodedata

# ── נרמול שמות ───────────────────────────────────────────────────────────────
# המטרה: "שובר-שורות" ו"שובר שורות" ו"שובר שורות!" הם אותו שם, ו-"The
# Batman" ו-"Batman" לא. ניקוד מוסר כי בקטלוג הוא מופיע לפעמים ובכותר
# של TMDB כמעט לעולם לא.
_KEEP = re.compile(r"[^\w֐-׿]+", re.U)
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _KEEP.sub(" ", s.lower())
    s = re.sub(r"\s{2,}", " ", s).strip()
    return _ARTICLE.sub("", s).strip()


def kind_ok(unit_kind: str, media_type: str) -> bool:
    """סדרה אצלנו היא tv ב-TMDB. פריט בודד — לא בהכרח movie.

    לכן הסינון א-סימטרי בכוונה: לסדרה פוסלים movie, לפריט בודד לא
    פוסלים כלום. פריט בודד אצלנו יכול להיות מיני-סדרה או סרט טלוויזיה
    שנשמר כשורה אחת, וסינון שם היה פוסל את התשובה הנכונה. כל שאר
    הצינור (tmdb_apply, tmdb_enrich) ממילא מניח סדרה→tv, כך שזה עקבי.
    """
    return not (unit_kind == "series" and media_type == "movie")


def exact_pick(query: str, year: str, cands: list):
    """המועמד היחיד שהשם שלו זהה אחרי נרמול, או None אם אין כזה.

    מחזיר (מועמד|None, נימוק). כל מצב מעורפל מחזיר None — הכלל הזה
    נועד להיות זהיר, כי כל מה שהוא פוסל פשוט עובר למודל.
    """
    nq = norm(query)
    if not nq:
        return None, "שאילתה ריקה"
    hits = [c for c in cands
            if norm(c.get("title")) == nq or norm(c.get("original_title")) == nq]
    if not hits:
        return None, "אין התאמת שם מדויקת"
    if len(hits) > 1 and year:
        yh = [c for c in hits
              if str(c.get("year") or "").isdigit()
              and abs(int(c["year"]) - int(year)) <= 1]
        if yh:
            hits = yh
    if len(hits) == 1:
        return hits[0], "שם מדויק יחיד"
    return None, f"{len(hits)} התאמות מדויקות — מעורפל"


# ── אמדן טוקנים ──────────────────────────────────────────────────────────────
# אין טוקנייזר של qwen מקומית, ולכן זה אמדן ולא מדידה: עברית ב-BPE
# יוצאת בערך טוקן לכל 1.5 תווים, אנגלית טוקן לכל 4. מה שמעניין כאן
# הוא היחס בין הגרסאות, והוא לא תלוי בקבוע.
def est_tokens(payload: str) -> int:
    he = sum(1 for ch in payload if "֐" <= ch <= "׿")
    return int(he / 1.5 + (len(payload) - he) / 4)


def payload_variants(m, name: str, year: str, cands: list) -> dict:
    """אותה יחידה בשלוש צורות, כדי לראות מה כל ויתור חוסך."""
    def body(cs, drop_overview, ov_cap=0):
        cs2 = []
        for c in cs:
            d = dict(c)
            if drop_overview:
                d.pop("overview", None)
            elif ov_cap:
                d["overview"] = (d.get("overview") or "")[:ov_cap]
            cs2.append(d)
        return json.dumps({"catalogue_name": name, "catalogue_year": year or None,
                           "candidates": cs2}, ensure_ascii=False)
    sys_t = est_tokens(m.SYSTEM)
    return {
        "כמו עכשיו":       sys_t + est_tokens(body(cands, False)) + 200,
        "overview ל-80":   sys_t + est_tokens(body(cands[:5], False, 80)) + 60,
        "בלי overview":    sys_t + est_tokens(body(cands[:5], True)) + 60,
    }
