#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# צופה קוד מוגן בסיסמה: /code/ באתר, עם כל הקוד שיושב על השרת.
#
# מיועד למסירה למתכנת — הוא רואה בדפדפן את הקוד האמיתי שרץ, בלי גישת SSH
# ובלי לשכפל מאגרים.
#
# ההגנה היא ברמת nginx (auth_basic) ולא ב-JavaScript. בדיקת סיסמה בדף
# אינה הגנה: מי שפותח "הצג מקור" רואה גם את הסיסמה וגם את התוכן. כאן
# בלי סיסמה נכונה השרת פשוט לא מגיש כלום.
#
# סודות: הסקריפט סורק כל קובץ לפני שהוא מעתיק, ומדלג על .env, על קבצי
# session ועל סוד החתימה. אם נמצא משהו שנראה כמו טוקן — הוא מוסתר.
#
#   bash setup_code_viewer.sh           התקנה / רענון
#   bash setup_code_viewer.sh --remove  הסרה מלאה
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
SRC=/opt/zovex-bot
DST=/opt/zovex-code
HTPW=/etc/nginx/.zovex_code
SNIP=/etc/nginx/snippets/zovex-code.conf
SITE=/etc/nginx/sites-enabled/zovex

if [ "${1:-}" = "--remove" ]; then
  rm -rf "$DST" "$HTPW" "$SNIP"
  sed -i '/zovex-code.conf/d' "$SITE"
  nginx -t >/dev/null 2>&1 && systemctl reload nginx && echo "✓ הוסר. /code/ כבר לא קיים."
  exit 0
fi

command -v openssl >/dev/null || { echo "❌ openssl לא מותקן"; exit 1; }

echo "════ 1/5 · סיסמה ════"
read -rsp "  סיסמה לצופה הקוד: " P1; echo
read -rsp "  שוב לאימות:       " P2; echo
[ -z "$P1" ] && { echo "❌ סיסמה ריקה"; exit 1; }
[ "$P1" != "$P2" ] && { echo "❌ הסיסמאות לא זהות"; exit 1; }
printf 'zovex:%s\n' "$(openssl passwd -apr1 "$P1")" > "$HTPW"
chmod 640 "$HTPW"; chown root:www-data "$HTPW" 2>/dev/null
unset P1 P2
echo "  ✓ נשמרה מוצפנת ב-$HTPW"

echo
echo "════ 2/5 · אוסף קבצים ════"
rm -rf "$DST"; mkdir -p "$DST/files"
# מה שנאסף: הקוד האמיתי שרץ + כל סקריפטי הפאץ' + הגדרות המערכת.
# מה שלא: .env, קבצי session, סוד החתימה, נתונים, גיבויים.
n=0
copy() {  # $1=מקור  $2=שם ביעד
  [ -f "$1" ] || return
  cp "$1" "$DST/files/$2" && n=$((n+1))
}
for f in "$SRC"/*.py "$SRC"/*.html "$SRC"/*.sh; do
  b=$(basename "$f")
  case "$b" in
    *session*|*secret*|.env*) continue ;;
    main_before_*|*.bak-*) continue ;;
  esac
  copy "$f" "$b"
done
copy /etc/nginx/sites-enabled/zovex "nginx-zovex.conf"
copy /etc/nginx/snippets/zovex-stream.conf "nginx-stream.conf"
copy /etc/nginx/snippets/zovex-proxy.conf "nginx-proxy.conf"
copy /etc/systemd/system/zovex-bot.service "systemd-zovex-bot.service"
echo "  ✓ $n קבצים"

echo
echo "════ 3/5 · סריקת סודות ════"
python3 - "$DST/files" <<'PY'
import os, re, sys
d = sys.argv[1]
PAT = [
  (r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",                 "טוקן טלגרם"),
  (r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b", "טוקן GitHub"),
  (r"\bhf_[A-Za-z0-9]{30,}\b",                          "טוקן HuggingFace"),
  (r"\bAKIA[0-9A-Z]{16}\b",                             "מפתח AWS"),
  (r"\b[0-9a-f]{32}\b",                                 "מפתח API"),
  (r"\b[A-Za-z0-9+/=_-]{140,}\b",                       "session string"),
]
hits = 0
for fn in sorted(os.listdir(d)):
    p = os.path.join(d, fn)
    try:
        s = open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    orig = s
    for pat, name in PAT:
        def sub(m):
            global hits
            hits += 1
            print(f"  ⚠ {fn}: {name} — הוסתר")
            return "«הוסתר»"
        s = re.sub(pat, sub, s)
    if s != orig:
        open(p, "w", encoding="utf-8").write(s)
print("  ✓ לא נמצא שום סוד" if not hits else f"  ✓ {hits} ערכים הוסתרו")
PY

echo
echo "════ 3.5/5 · אורז זיפ ════"
# נבנה *אחרי* סריקת הסודות, כדי שהארכיון יכיל את הגרסה המנוקה ולא את המקור.
# zipfile של פייתון ולא הפקודה zip — היא לא תמיד מותקנת.
python3 - "$DST" <<'PYZIP'
import os, sys, zipfile, datetime
root = sys.argv[1]; fdir = os.path.join(root, "files")
out = os.path.join(root, "zovex-code.zip")
files = sorted(os.listdir(fdir))
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in files:
        z.write(os.path.join(fdir, f), f"zovex-code/{f}")
    z.writestr("zovex-code/README.txt",
        "ZOVEX — קוד השרת\n"
        f"נוצר: {datetime.datetime.now():%d/%m/%Y %H:%M}\n"
        f"{len(files)} קבצים\n\n"
        "זהו הקוד שרץ בפועל על השרת, ולא מה שנמצא במאגר —\n"
        "main.py ו-admin.html מתעדכנים דרך סקריפטי פאץ' שרצים בשרת.\n\n"
        "טוקנים, סיסמאות וקבצי session אינם כאן: הם מוחרגים באיסוף,\n"
        "וכל ערך שנראה כמו מפתח הוסתר אוטומטית.\n")
mb = os.path.getsize(out) / 1048576
print(f"  ✓ {len(files)} קבצים · {mb:.1f} MB")
PYZIP

echo
echo "════ 4/5 · בונה דפים ════"
python3 - "$DST" <<'PY'
import html, os, sys
root = sys.argv[1]; fdir = os.path.join(root, "files")
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0f1115;color:#e7eaf0;
 font:15px/1.6 'IBM Plex Sans Hebrew',system-ui,sans-serif;direction:rtl}
a{color:#7fb1ff;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1100px;margin:0 auto;padding:22px 16px 60px}
h1{font-size:23px;margin:0 0 4px}
.sub{color:#8b93a3;font-size:14px;margin:0 0 22px}
.grp{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#8b93a3;
 margin:22px 0 8px;font-weight:600}
table{width:100%;border-collapse:collapse;background:#171a21;border-radius:10px;overflow:hidden}
td{padding:9px 14px;border-bottom:1px solid #252a34;font-size:14px}
tr:last-child td{border-bottom:none}
td.sz{color:#8b93a3;font-size:12.5px;text-align:left;white-space:nowrap;
 font-variant-numeric:tabular-nums}
pre{background:#0b0d12;border:1px solid #252a34;border-radius:10px;padding:16px;
 overflow-x:auto;direction:ltr;text-align:left;font-size:12.5px;line-height:1.65;
 font-family:'IBM Plex Mono',ui-monospace,Menlo,monospace;white-space:pre}
.bar{display:flex;gap:14px;align-items:baseline;margin-bottom:14px;flex-wrap:wrap}
.note{background:#1a1420;border:1px solid #3a2a44;border-radius:10px;padding:12px 15px;
 font-size:13.5px;color:#d8c8e4;margin-bottom:20px}
.dl{display:inline-flex;align-items:center;gap:9px;background:#2f6df6;color:#fff;
 padding:12px 20px;border-radius:10px;font-size:15px;font-weight:600;
 margin-bottom:22px}
.dl:hover{background:#4680ff;text-decoration:none}
.dl small{opacity:.75;font-weight:400;font-size:13px}
"""
def page(title, body):
    return ("<!doctype html><html lang=he dir=rtl><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style>"
            f"<div class=wrap>{body}</div>")

GROUPS = [
    ("הקוד שרץ",      lambda f: f in ("main.py", "admin.html")),
    ("הגדרות מערכת",  lambda f: f.startswith(("nginx-", "systemd-"))),
    ("פאצ'ים שהוחלו", lambda f: f.startswith(("fix_", "add_"))),
    ("כלים",          lambda f: True),
]
files = sorted(os.listdir(fdir))
zpath = os.path.join(root, "zovex-code.zip")
zmb = os.path.getsize(zpath) / 1048576 if os.path.exists(zpath) else 0
used, rows = set(), []
for gname, pred in GROUPS:
    grp = [f for f in files if f not in used and pred(f)]
    if not grp: continue
    used |= set(grp)
    rows.append(f"<div class=grp>{gname} · {len(grp)}</div><table>")
    for f in grp:
        sz = os.path.getsize(os.path.join(fdir, f))
        s = f"{sz/1024:.0f} KB" if sz >= 1024 else f"{sz} B"
        rows.append(f"<tr><td><a href='v/{html.escape(f)}.html'>{html.escape(f)}</a></td>"
                    f"<td class=sz>{s}</td></tr>")
    rows.append("</table>")

open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(page(
    "ZOVEX · קוד השרת",
    "<h1>ZOVEX · קוד השרת</h1>"
    f"<p class=sub>{len(files)} קבצים · הקוד האמיתי שרץ על השרת ברגע זה</p>"
    "<div class=note>טוקנים, סיסמאות וקבצי session אינם כאן — הם מוחרגים "
    "בעת האיסוף, וכל ערך שנראה כמו מפתח מוסתר אוטומטית.</div>"
    + (f"<a class=dl href='zovex-code.zip' download>⬇ הורדת הכל בזיפ"
       f"<small>{len(files)} קבצים · {zmb:.1f} MB</small></a>" if zmb else "")
    + "".join(rows)))

os.makedirs(os.path.join(root, "v"), exist_ok=True)
for f in files:
    src = open(os.path.join(fdir, f), encoding="utf-8", errors="replace").read()
    lines = src.count("\n") + 1
    open(os.path.join(root, "v", f + ".html"), "w", encoding="utf-8").write(page(
        f + " · ZOVEX",
        f"<div class=bar><a href='../index.html'>← חזרה</a>"
        f"<b>{html.escape(f)}</b>"
        f"<span class=sz style='color:#8b93a3;font-size:13px'>{lines:,} שורות</span>"
        f"<a href='../files/{html.escape(f)}'>הורדה</a></div>"
        f"<pre>{html.escape(src)}</pre>"))
print(f"  ✓ {len(files)} דפים + מפתח")
PY

echo
echo "════ 5/5 · nginx ════"
cat > "$SNIP" <<'NG'
# צופה קוד מוגן. auth_basic הוא הגנה אמיתית ברמת השרת: בלי סיסמה נכונה
# nginx לא מגיש דבר, בניגוד לבדיקה ב-JavaScript שאפשר לעקוף בהצגת מקור.
location /code/ {
    alias /opt/zovex-code/;
    index index.html;
    auth_basic           "ZOVEX code";
    auth_basic_user_file /etc/nginx/.zovex_code;
    autoindex            off;
    add_header X-Robots-Tag "noindex, nofollow" always;
    charset utf-8;
}

# הקבצים הגולמיים מוגשים תמיד כטקסט. בלי זה admin.html היה *נפתח* כפאנל
# ניהול אמיתי במקום להציג את הקוד שלו — מבלבל, ומנסה לדבר עם /panel/api.
# הזיפ יושב תחת /code/ ולכן כבר מוגן; נשאר רק לוודא שהוא יורד כקובץ
# ולא נפתח בדפדפן.
location = /code/zovex-code.zip {
    alias /opt/zovex-code/zovex-code.zip;
    auth_basic           "ZOVEX code";
    auth_basic_user_file /etc/nginx/.zovex_code;
    default_type application/zip;
    add_header Content-Disposition 'attachment; filename="zovex-code.zip"' always;
    add_header X-Robots-Tag "noindex, nofollow" always;
}

location /code/files/ {
    alias /opt/zovex-code/files/;
    auth_basic           "ZOVEX code";
    auth_basic_user_file /etc/nginx/.zovex_code;
    types { }
    default_type text/plain; charset utf-8;
    add_header X-Robots-Tag "noindex, nofollow" always;
}
NG
# מוזרק אחרי שורת ה-root, שהיא יחידה ובטוחה. עוגן על "location /" היה
# עלול להיתפס על /stream/ או כל location אחר שמופיע קודם.
if ! grep -q "zovex-code.conf" "$SITE"; then
  if [ "$(grep -c '^\s*root /opt/zovex-site;' "$SITE")" != "1" ]; then
    echo "  ✗ לא נמצאה שורת root יחידה ב-$SITE — לא נוגעים"; exit 1
  fi
  sed -i '/^\s*root \/opt\/zovex-site;/a\    include snippets/zovex-code.conf;' "$SITE"
fi

if nginx -t >/dev/null 2>&1; then
  systemctl reload nginx
  echo "  ✓ nginx נטען מחדש"
  echo
  echo "════════════════════════════════════════"
  echo "✅  https://zovex.duckdns.org/code/"
  echo "    שם משתמש: zovex"
  echo "════════════════════════════════════════"
else
  sed -i '/zovex-code.conf/d' "$SITE"
  echo "  ✗ nginx דחה את ההגדרה — בוטל, שום דבר לא השתנה"
  nginx -t
  exit 1
fi
