#!/usr/bin/env bash
# דף עברי פשוט לטורנטים, מאחורי nginx עם HTTPS.
#
# ## למה דף משלנו ולא לתרגם את qBittorrent
#
# הממשק של qBittorrent בנוי למי שמנהל עשרות טורנטים: טאבים, טראקרים,
# קטגוריות, עדיפויות, גרפים. תרגום שלו לעברית לא הופך אותו לפשוט — הוא
# רק הופך אותו לעמוס בעברית. מה שנדרש כאן הוא שלושה דברים: להוסיף קובץ,
# לראות שזה רץ, לראות שזה נגמר.
#
# ## למה דרך nginx ולא ישירות על 8080
#
# שלושה דברים נפתרים במכה אחת:
#
#   • **HTTPS** — היום הסיסמה עוברת בטקסט גלוי על פורט 8080.
#   • **אותו מקור** — דף שיושב על מקור אחר מה-API לא יכול לדבר איתו בלי
#     CORS, ו-qBittorrent לא שולח כותרות CORS. דרך nginx שניהם על אותו
#     מקור והבעיה לא קיימת.
#   • **אין פורט פתוח** — qBittorrent יכול להאזין רק ל-127.0.0.1, ואז אין
#     שום פורט נוסף חשוף לאינטרנט.
#
# ## הכותרות שנשלפות
#
# ל-qBittorrent יש הגנת CSRF שבודקת Origin ו-Referer מול הכתובת שהוא
# חושב שהוא יושב עליה. מאחורי פרוקסי הן לא יתאימו לעולם, והכל היה נדחה
# עם 403. לכן הן נשלפות בפרוקסי — זו הדרך המקובלת, והיא בטוחה כאן כי
# הגישה ממילא עוברת דרך התחברות עם סיסמה.
#
#     bash qbt_hebrew_ui.sh            # מתקין
#     bash qbt_hebrew_ui.sh --remove   # מסיר
set -uo pipefail

UI_DIR=/opt/qbt-ui
NGINX_SNIP=/etc/nginx/snippets/qbt-ui.conf
PORT=8080
# חייב להיות מוגדר כאן ולא רק ב-setup_qbittorrent.sh: ההיירדוק שכותב את
# תצורת nginx משתמש בו, ועם set -u משתנה לא מוגדר מפיל את cat באמצע
# ומשאיר קובץ באורך אפס — שעובר את nginx -t בשקט ומפיל את הדף.
DL_ROOT=/home/torrents
# גיבויים לא נשמרים בתוך sites-enabled: nginx טוען משם *כל* קובץ, וגיבוי
# שיושב שם נטען כבלוק שרת נוסף וגורם ל-conflicting server name.
BAK_DIR=/root/nginx-backups

ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
die() { printf '\n\033[31m❌ %s\033[0m\n' "$*"; exit 1; }

[[ $EUID -eq 0 ]] || die "צריך להריץ כ-root"

if [[ "${1:-}" == "--remove" ]]; then
  rm -rf "$UI_DIR" "$NGINX_SNIP"
  for f in /etc/nginx/sites-enabled/*; do
    sed -i '/qbt-ui.conf/d' "$f" 2>/dev/null
  done
  nginx -t >/dev/null 2>&1 && nginx -s reload && echo "הוסר."
  exit 0
fi

command -v nginx >/dev/null || die "nginx לא מותקן"
systemctl is-active --quiet qbittorrent-nox || die "qbittorrent-nox לא רץ"

mkdir -p "$UI_DIR"

# ── הדף ───────────────────────────────────────────────────────────────────
cat > "$UI_DIR/index.html" <<'HTML'
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>טורנטים</title>
<style>
  :root { --bg:#0b0b0f; --card:#16161d; --line:#26262f; --txt:#f0f0f4;
          --dim:#8b8b96; --pink:#e91e8c; --ok:#3ecf6b; }
  * { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }
  body { background:var(--bg); color:var(--txt); font:15px/1.5 system-ui,Arial;
         padding:16px; max-width:760px; margin:0 auto; }
  h1 { font-size:20px; margin-bottom:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:16px; margin-bottom:12px; }
  button { font:600 15px system-ui,Arial; border:none; border-radius:10px;
           padding:13px 18px; cursor:pointer; color:#fff; background:var(--pink); }
  button:disabled { opacity:.5; }
  button.ghost { background:#24242e; }
  input[type=text], input[type=password] {
    width:100%; background:#0e0e14; border:1px solid var(--line); color:var(--txt);
    border-radius:10px; padding:12px; font:15px system-ui,Arial; margin-bottom:10px; }
  .big { display:block; width:100%; padding:20px; font-size:16px; text-align:center; }
  .row { display:flex; gap:8px; align-items:center; }
  .t { border-bottom:1px solid var(--line); padding:14px 0; }
  .t:last-child { border-bottom:none; }
  .t .name { font-weight:600; margin-bottom:8px; word-break:break-word; }
  .bar { height:6px; background:#24242e; border-radius:6px; overflow:hidden; margin:8px 0; }
  .fill { height:100%; background:var(--pink); border-radius:6px; transition:width .4s; }
  .fill.done { background:var(--ok); }
  .meta { color:var(--dim); font-size:13px; display:flex; justify-content:space-between;
          gap:10px; flex-wrap:wrap; }
  .x { background:none; color:var(--dim); font-size:20px; padding:4px 8px; }
  .dl { color:var(--ok); font-size:13px; font-weight:600; text-decoration:none;
        white-space:nowrap; padding:4px 8px; }
  .empty { color:var(--dim); text-align:center; padding:28px 0; }
  .sum { display:grid; grid-template-columns:1fr 1fr; gap:10px 14px; }
  .sum div { font-size:13px; color:var(--dim); }
  .sum b { display:block; color:var(--txt); font-size:17px; font-weight:700;
           margin-top:2px; }
  .sum b.up { color:var(--ok); }
  .note { color:var(--dim); font-size:11px; margin-top:10px; line-height:1.4; }
  .stats { color:var(--dim); font-size:12px; margin-top:4px; }
  .stats .u { color:var(--ok); font-weight:600; }
  .live { color:var(--pink); font-weight:600; }
  .msg { padding:12px; border-radius:10px; margin-bottom:12px; font-size:14px; display:none; }
  .msg.err { background:#3a1520; color:#ff9aa8; display:block; }
  .msg.good { background:#122a1a; color:#8ef0ab; display:block; }
  #app { display:none; }
</style>
</head>
<body>

<h1>טורנטים</h1>
<div class="msg" id="msg"></div>

<div id="login" class="card">
  <input type="password" id="pw" placeholder="סיסמה" autocomplete="current-password">
  <button class="big" onclick="login()">כניסה</button>
</div>

<div id="app">
  <div class="card">
    <input type="file" id="file" accept=".torrent" hidden onchange="addFile()">
    <button class="big" onclick="document.getElementById('file').click()">
      ➕ הוספת קובץ טורנט
    </button>
  </div>

  <div class="card">
    <input type="text" id="magnet" placeholder="או הדבק כאן קישור מגנט">
    <button class="big ghost" onclick="addMagnet()">הוספה</button>
  </div>

  <div class="card">
    <div class="sum" id="sum"></div>
    <div class="note">
      המספרים כאן הם של qBittorrent בשרת בלבד, מאז ההתקנה. הטראקר מנהל
      ספירה משלו שכוללת גם מה שהורדת פעם מהטלפון — שני המספרים לא יהיו זהים.
    </div>
  </div>

  <div class="card" id="list"><div class="empty">טוען…</div></div>
</div>

<script>
const API = '/qbt-api/api/v2';
let timer = null;

function show(text, good) {
  const m = document.getElementById('msg');
  m.textContent = text;
  m.className = 'msg ' + (good ? 'good' : 'err');
  clearTimeout(m._t);
  m._t = setTimeout(() => { m.className = 'msg'; }, 5000);
}

async function login() {
  const pw = document.getElementById('pw').value;
  const b = new URLSearchParams({username: 'admin', password: pw});
  try {
    const r = await fetch(API + '/auth/login', {method: 'POST', body: b});
    const t = await r.text();
    if (t.trim() !== 'Ok.') return show('סיסמה שגויה');
    document.getElementById('login').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    refresh();
    timer = setInterval(refresh, 2000);
  } catch (e) { show('אין חיבור לשרת'); }
}

// אם כבר יש עוגיית התחברות תקפה — נכנסים ישר, בלי לבקש סיסמה שוב.
(async () => {
  try {
    const r = await fetch(API + '/torrents/info');
    if (r.ok) {
      document.getElementById('login').style.display = 'none';
      document.getElementById('app').style.display = 'block';
      refresh();
      timer = setInterval(refresh, 2000);
    }
  } catch (e) {}
})();

async function addFile() {
  const f = document.getElementById('file').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('torrents', f);
  const r = await fetch(API + '/torrents/add', {method: 'POST', body: fd});
  show(r.ok ? 'נוסף: ' + f.name : 'ההוספה נכשלה', r.ok);
  document.getElementById('file').value = '';
  refresh();
}

async function addMagnet() {
  const el = document.getElementById('magnet');
  const u = el.value.trim();
  if (!u) return;
  const fd = new FormData();
  fd.append('urls', u);
  const r = await fetch(API + '/torrents/add', {method: 'POST', body: fd});
  show(r.ok ? 'נוסף' : 'ההוספה נכשלה', r.ok);
  if (r.ok) el.value = '';
  refresh();
}

const STATE = {
  downloading: 'מוריד', forcedDL: 'מוריד', metaDL: 'מושך מידע',
  stalledDL: 'ממתין למקורות', queuedDL: 'בתור',
  uploading: 'מזריע', forcedUP: 'מזריע', stalledUP: 'הושלם',
  queuedUP: 'הושלם', pausedUP: 'הושלם', pausedDL: 'מושהה',
  checkingDL: 'בודק', checkingUP: 'בודק', checkingResumeData: 'בודק',
  moving: 'מעביר', error: 'שגיאה', missingFiles: 'קבצים חסרים',
  unknown: '—'
};

function size(n) {
  if (!n) return '0';
  const u = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(i > 1 ? 1 : 0) + u[i];
}

function eta(s) {
  if (!s || s >= 8640000) return '';
  if (s < 60) return Math.round(s) + ' שנ׳';
  if (s < 3600) return Math.round(s / 60) + ' דק׳';
  return (s / 3600).toFixed(1) + ' שע׳';
}

async function refresh() {
  let list, srv;
  try {
    // sync/maindata מחזיר גם את הטורנטים וגם את מצב השרת בבקשה אחת,
    // במקום שתי קריאות נפרדות כל שתי שניות.
    const r = await fetch(API + '/sync/maindata?rid=0');
    if (r.status === 403) { location.reload(); return; }
    const d = await r.json();
    srv = d.server_state || {};
    list = Object.entries(d.torrents || {}).map(([h, t]) => ({...t, hash: h}));
  } catch (e) { return; }

  // ── סיכום למעלה ────────────────────────────────────────────────────
  const active = list.filter(t => (t.num_leechs || 0) > 0).length;
  document.getElementById('sum').innerHTML = `
    <div>העלית מהשרת<b class="up">${size(srv.alltime_ul)}</b></div>
    <div>הורדת לשרת<b>${size(srv.alltime_dl)}</b></div>
    <div>יחס בשרת<b>${srv.global_ratio || '—'}</b></div>
    <div>מעלה עכשיו<b class="up">${size(srv.up_info_speed)} לשנייה</b></div>
    <div>מושכים ממך כרגע<b>${
      active === 0 ? 'אף אחד'
      : `<span class="live">${active === 1 ? 'טורנט אחד' : active + ' טורנטים'}</span>`
    }</b></div>
    <div>מקום פנוי<b>${size(srv.free_space_on_disk)}</b></div>`;

  const box = document.getElementById('list');
  if (!list.length) {
    box.innerHTML = '<div class="empty">אין טורנטים. הוסף קובץ למעלה.</div>';
    return;
  }
  list.sort((a, b) => b.added_on - a.added_on);
  box.innerHTML = list.map(t => {
    const pct = Math.round(t.progress * 100);
    const done = pct >= 100;
    const st = STATE[t.state] || t.state;
    const e = eta(t.eta);
    // קישור הורדה רק למה שהושלם. הקובץ ממשיך לזרוע בזמן ההורדה, וההורדה
    // הזאת אינה עוברת דרך הטראקר ולכן אינה נספרת אצלו בשום צורה.
    const dl = done
      ? `<a class="dl" href="/files/${encodeURIComponent(t.name)}">⬇ הורדה</a>`
      : '';
    return `<div class="t">
      <div class="row">
        <div class="name" style="flex:1">${esc(t.name)}</div>
        ${dl}
        <button class="x" onclick="del('${t.hash}')" title="הסרה">✕</button>
      </div>
      <div class="bar"><div class="fill ${done ? 'done' : ''}" style="width:${pct}%"></div></div>
      <div class="meta">
        <span>${done ? '✓ ' : ''}${st} · <bdi>${pct}%</bdi></span>
        <span><bdi>${size(t.size)}</bdi>${
          t.dlspeed > 0 ? ' · <bdi>' + size(t.dlspeed) + '</bdi> לשנייה' : ''}${
          e ? ' · נותרו <bdi>' + e + '</bdi>' : ''}</span>
      </div>
      <div class="stats">
        אנשים לקחו ממנו <span class="u"><bdi>${size(t.uploaded)}</bdi></span>
        · יחס <bdi>${(t.ratio || 0).toFixed(2)}</bdi>
        ${t.num_leechs > 0
          ? ` · <span class="live">${t.num_leechs} מושכים עכשיו</span>`
          : ''}
        ${t.upspeed > 0 ? ` · <bdi>${size(t.upspeed)}</bdi> לשנייה` : ''}
      </div>
    </div>`;
  }).join('');
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

async function del(hash) {
  if (!confirm('להסיר את הטורנט? הקבצים שכבר ירדו יימחקו.')) return;
  const b = new URLSearchParams({hashes: hash, deleteFiles: 'true'});
  await fetch(API + '/torrents/delete', {method: 'POST', body: b});
  refresh();
}
</script>
</body>
</html>
HTML
ok "נכתב $UI_DIR/index.html"

# ── nginx ─────────────────────────────────────────────────────────────────
# ── סיסמה לתיקיית הקבצים ─────────────────────────────────────────────────
# אותה סיסמה של דף הטורנטים, כדי שלא יהיו שתיים לזכור. openssl קיים בכל
# התקנה; אין צורך להתקין apache2-utils בשביל htpasswd אחד.
PASSFILE=/etc/nginx/.qbt-files
if [[ -f /etc/qbt-webui.pass ]]; then
  P=$(cat /etc/qbt-webui.pass)
  if command -v openssl >/dev/null; then
    printf 'admin:%s\n' "$(openssl passwd -apr1 "$P")" > "$PASSFILE"
  else
    printf 'admin:{SHA}%s\n' \
      "$(printf '%s' "$P" | openssl dgst -binary -sha1 | base64)" > "$PASSFILE"
  fi
  chmod 640 "$PASSFILE"; chown root:www-data "$PASSFILE" 2>/dev/null
  ok "נוצרה סיסמה לתיקיית הקבצים (זהה לזו של הדף)"
else
  bad "לא נמצא /etc/qbt-webui.pass — תיקיית הקבצים לא תוגן!"
fi

cat > "$NGINX_SNIP" <<EOF
# דף הטורנטים בעברית + פרוקסי ל-API של qBittorrent.

# הקבצים שהורדו, להורדה ישירה מהדפדפן.
#
# למה זה בטוח מבחינת הטראקר: ההורדה הזאת היא HTTP רגיל מהשרת שלך אל
# המכשיר שלך. היא אינה עוברת דרך הטורנט, ולכן הטראקר לא רואה אותה ולא
# סופר אותה בשום עמודה. הטורנט ממשיך לזרוע במקביל, בלי הפרעה.
location /files/ {
    alias $DL_ROOT/complete/;
    autoindex on;
    autoindex_exact_size off;
    autoindex_localtime on;
    charset utf-8;

    # בלי סיסמה, לבקשת דוד — לחיצה אחת מהדף והקובץ יורד.
    # המחיר: כל מי שמגיע לכתובת רואה את הרשימה ויכול להוריד. הכתובת אינה
    # מפורסמת בשום מקום ו-X-Robots-Tag מונע אינדוקס, אבל זו הסתרה ולא הגנה.
    # להחזיר סיסמה: לבטל את ההערה בשתי השורות הבאות ולהריץ שוב.
    # auth_basic "ZOVEX";
    # auth_basic_user_file $PASSFILE;

    # קבצי וידאו גדולים: בלי זה nginx מנסה להגיש בכמות ומעמיס זיכרון.
    sendfile on;
    tcp_nopush on;
    add_header X-Robots-Tag "noindex, nofollow" always;
}

location /torrent/ {
    alias $UI_DIR/;
    index index.html;
    add_header X-Robots-Tag "noindex, nofollow" always;
}

location /qbt-api/ {
    proxy_pass http://127.0.0.1:$PORT/;
    proxy_http_version 1.1;

    # הגנת ה-CSRF של qBittorrent בודקת Origin ו-Referer מול הכתובת שהוא
    # חושב שהוא יושב עליה. מאחורי פרוקסי הן לעולם לא יתאימו, והכל היה
    # נדחה ב-403. שליפתן היא הדרך המקובלת, ובטוחה כאן כי הגישה עוברת
    # ממילא דרך התחברות עם סיסמה.
    proxy_set_header Origin  "";
    proxy_set_header Referer "";
    proxy_set_header Host 127.0.0.1:$PORT;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;

    # קבצי טורנט קטנים, אבל בלי זה העלאה של קובץ גדול נחתכת.
    client_max_body_size 32m;
}
EOF
ok "נכתב $NGINX_SNIP"

# מכניסים את ה-include לתוך בלוק ה-server של 443, אם עוד לא שם
# ניקוי שאריות מגרסה קודמת שהניחה גיבויים בתוך sites-enabled. nginx טוען
# משם כל קובץ, ולכן כל גיבוי כזה הפך לבלוק שרת כפול.
mkdir -p "$BAK_DIR"
for stray in /etc/nginx/sites-enabled/*.bak-qbt*; do
  [[ -e "$stray" ]] || continue
  mv -- "$stray" "$BAK_DIR/"
  ok "הוצא מ-sites-enabled: $(basename "$stray")"
done

# רק קבצים אמיתיים, לא גיבויים
SITE=""
for f in /etc/nginx/sites-enabled/*; do
  [[ -f "$f" && "$f" != *.bak* ]] || continue
  grep -q "listen.*443" "$f" && { SITE="$f"; break; }
done
[[ -n "$SITE" ]] || die "לא נמצא בלוק server עם 443 ב-sites-enabled"

# גיבוי של המצב הנוכחי, לפני כל שינוי בהרצה הזאת. הגרסה הקודמת שמרה גיבוי
# רק בהרצה הראשונה, ואז בכשל שחזרה את המצב מלפני ההתקנה — כלומר מחקה את
# ה-include ושברה דף שעבד.
NOW_BAK="$BAK_DIR/$(basename "$SITE").$(date +%Y%m%d-%H%M%S)"
cp "$SITE" "$NOW_BAK"

if grep -q "qbt-ui.conf" "$SITE"; then
  ok "ה-include כבר קיים ב-$(basename "$SITE")"
else
  awk -v snip="$NGINX_SNIP" '
    /listen.*443/ { in443=1 }
    { print }
    in443 && /server_name/ && !done { print "    include " snip ";"; done=1 }
  ' "$NOW_BAK" > "$SITE"
  ok "נוסף include ל-$(basename "$SITE")"
fi

# הקובץ חייב להכיל תוכן. קובץ ריק עובר את nginx -t בשקט ומפיל את הדף —
# בדיוק מה שקרה כשמשתנה לא מוגדר הפיל את ההיירדוק באמצע.
[[ -s "$NGINX_SNIP" ]] || die "$NGINX_SNIP יצא ריק — לא טוענים מחדש"

if nginx -t >/dev/null 2>&1; then
  nginx -s reload
  ok "nginx נטען מחדש (reload, לא restart — בקשות שרצות לא נקטעות)"
else
  cp "$NOW_BAK" "$SITE"
  nginx -t
  die "תצורת nginx לא תקינה — שוחזר המצב מלפני ההרצה הזאת, בלי reload"
fi

# ── אימות ─────────────────────────────────────────────────────────────────
echo
C1=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1/torrent/" -H "Host: zovex.duckdns.org")
C2=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1/qbt-api/api/v2/app/version" -H "Host: zovex.duckdns.org")
[[ "$C1" == "200" ]] && ok "הדף מגיב (HTTP $C1)" || bad "הדף החזיר $C1"
[[ "$C2" =~ ^(200|403)$ ]] && ok "ה-API מגיב דרך הפרוקסי (HTTP $C2)" || bad "ה-API החזיר $C2"

echo
echo "════════════════════════════════════════════"
echo "  https://zovex.duckdns.org/torrent/"
echo
echo "  הסיסמה היא זו שקיבלת בהתקנה"
echo "  (שמורה ב-/etc/qbt-webui.pass)"
echo "════════════════════════════════════════════"
echo
echo "אחרי שתאשר שזה עובד, אפשר לסגור את 8080 מבחוץ לגמרי:"
echo "  sed -i 's/^WebUI.Address=.*/WebUI\\\\Address=127.0.0.1/' /home/qbt/.config/qBittorrent/qBittorrent.conf"
echo "  systemctl restart qbittorrent-nox"
