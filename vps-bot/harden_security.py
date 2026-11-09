#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harden_security — סגירת וקטורי תקיפה שנותרו, בלי לגעת ב-streaming.

סבב תקיפה אדום על כל המערכת העלה שלושה דברים שאפשר לנצל והם *לא*
במסלול הווידאו, ולכן אפשר לתקן אותם בבטחה בלי לגעת בהזרמה הרגישה:

  1. SSRF דרך "למידת מארחים" אוטומטית.
     _rewrite_hls_manifest לומד כל מארח שמופיע במניפסט שהגיע מספק
     מאושר — בלי לבדוק שהמארח ציבורי. כלומר מניפסט (או ספק שנפרץ)
     יכול ללמד את השרת ‎127.0.0.1‎ / ‎169.254.169.254‎ (metadata של
     הענן) / רשת פנימית, ואז ‎/hls-relay/<כתובת פנימית>/…‎ מותר
     והשרת פונה פנימה. בקוד כבר קיימת ‎_host_is_public()‎ שחוסמת
     בדיוק את זה — אבל רק במסלול ההוספה הידנית. כאן מחילים אותה גם
     על הלמידה האוטומטית (שני המקומות: מניפסט + emby).

  2. מיצוי זיכרון דרך אותו מילון.
     ‎_relay_learned_hosts‎ גדל בלי גבול (ניקוי רק בגישה). תוקף שגורם
     ללמידת מארחים רבים מנפח זיכרון. מוסיפים גג קשיח עם גיזום.

  לא נכלל כאן בכוונה — נעשה בשכבת nginx כי שם זה אפס-סיכון להזרמה:
     · הגבלת גודל גוף בקשה (client_max_body_size) נגד הפלת זיכרון.
     · כותרות אבטחה (HSTS / X-Frame-Options / nosniff / Referrer).
     · הגבלת קצב ברמת ה-proxy.
  הקובץ deploy_harden.sh כולל את קטע ה-nginx להדבקה.

ההחלה אינה שוברת כלום: מארח ציבורי אמיתי ממשיך להילמד בדיוק כמו
קודם; רק מארחים פנימיים/פרטיים נחסמים, ורק עודף נגזם.

    python3 harden_security.py --check
    python3 harden_security.py
    python3 harden_security.py --revert

אחרי ההחלה:  systemctl restart zovex-bot
"""
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")

# ── עריכה 1: SSRF — שער על למידת מארח ממניפסט ────────────────────────────────
A1 = '''        if parsed.hostname and _relay_origin_for(parsed.hostname) is None:
            if not parent_ok or parsed.scheme not in ("http", "https"):
                out_lines.append(line)  # לא ידוע לנו - עדיף להשאיר כמו שהוא מלשבור לגמרי
                continue
            _relay_learned_hosts[parsed.hostname] = {'''
N1 = '''        if parsed.hostname and _relay_origin_for(parsed.hostname) is None:
            # [harden_security] מארח פנימי/פרטי לעולם אינו נלמד (SSRF),
            # וגוזמים את המילון לפני הוספה כדי לא לנפח זיכרון בלי גבול.
            if (not parent_ok or parsed.scheme not in ("http", "https")
                    or not _host_is_public(parsed.hostname)):
                out_lines.append(line)  # לא ידוע לנו - עדיף להשאיר כמו שהוא מלשבור לגמרי
                continue
            _relay_prune_learned()
            _relay_learned_hosts[parsed.hostname] = {'''

# ── עריכה 2: SSRF — שער על למידת מארח מ-emby ─────────────────────────────────
A2 = '''    p = urlparse(target)
    if p.hostname and p.scheme in ("http", "https"):
        _relay_learned_hosts[p.hostname] = {'''
N2 = '''    p = urlparse(target)
    if p.hostname and p.scheme in ("http", "https") and _host_is_public(p.hostname):
        _relay_prune_learned()
        _relay_learned_hosts[p.hostname] = {'''

# ── עריכה 3: הגדרת הגיזום ליד הגדרת המילון ───────────────────────────────────
A3 = '_relay_learned_hosts: dict = {}          # host -> {"scheme","port","exp"}'
N3 = '''_relay_learned_hosts: dict = {}          # host -> {"scheme","port","exp"}
RELAY_LEARNED_MAX = int(os.environ.get("RELAY_LEARNED_MAX", "500"))

def _relay_prune_learned() -> None:
    """[harden_security] גג קשיח על מילון המארחים הנלמדים (הגנת זיכרון).
    קודם מסירים פגי-תוקף; אם עדיין מעל הגג — מסירים את הישנים ביותר."""
    if len(_relay_learned_hosts) < RELAY_LEARNED_MAX:
        return
    now = time.time()
    for k in [k for k, v in _relay_learned_hosts.items() if v.get("exp", 0) <= now]:
        _relay_learned_hosts.pop(k, None)
    if len(_relay_learned_hosts) >= RELAY_LEARNED_MAX:
        for k in sorted(_relay_learned_hosts,
                        key=lambda k: _relay_learned_hosts[k].get("exp", 0)
                        )[:len(_relay_learned_hosts) - RELAY_LEARNED_MAX + 1]:
            _relay_learned_hosts.pop(k, None)'''

EDITS = [("SSRF: שער על למידה ממניפסט", A1, N1, 1),
         ("SSRF: שער על למידה מ-emby", A2, N2, 1),
         ("הגנת זיכרון: גיזום מארחים נלמדים", A3, N3, 1)]

MARKER = "[harden_security]"


def validate(body: str) -> None:
    compile(body, "main.py", "exec")
    assert "_host_is_public" in body, "אין _host_is_public בקוד — עצירה"
    assert "_relay_prune_learned" in body, "הגיזום לא הוחל"
    # הלמידה מהמניפסט חייבת לעבור דרך _host_is_public
    i_learn = body.index("_relay_learned_hosts[parsed.hostname] =")
    i_guard = body.rindex("_host_is_public(parsed.hostname)", 0, i_learn)
    assert i_guard < i_learn, "השער לא לפני הלמידה"


def apply() -> str:
    src = open(PATH, encoding="utf-8").read()
    if MARKER in src:
        print("✓ כבר מותקן")
        return src
    out = src
    for name, a, n, cnt in EDITS:
        c = out.count(a)
        assert c == cnt, f"עוגן '{name}': נמצא {c} פעמים (ציפינו {cnt})"
        out = out.replace(a, n, cnt)
    validate(out)
    return out


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()

    if arg == "--revert":
        if MARKER not in src:
            print("אין מה לשחזר")
            return 0
        out = src
        for name, a, n, cnt in EDITS:
            assert out.count(n) == cnt, f"לא נמצא בלוק מוחל '{name}'"
            out = out.replace(n, a, cnt)
        out = out.replace(N3, A3, 1)  # ליתר ביטחון אם ריבוי
        compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_harden")
        open(PATH, "w", encoding="utf-8").write(out)
        print("✓ שוחזר (גיבוי:", PATH + ".bak_harden)")
        return 0

    out = apply()
    if arg == "--check":
        print("✓ בדיקה עברה — מוכן להחלה")
        return 0
    if MARKER in src:
        return 0
    shutil.copy2(PATH, PATH + ".bak_harden")
    open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_harden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
