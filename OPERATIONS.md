# ZOVEX · מדריך תפעול

> מה המערכת, איפה כל דבר יושב, ואיך משנים אותו.
> את **מה שאנחנו באמצע** קרא ב-`HANDOFF.md`. זה הקובץ שמסביר את השטח.
>
> ⚠️ **`main.py` שבשרת שונה מזה שבריפו.** העותק כאן ישן. כל מה שכתוב על
> מבנה נכון, אבל מספרי שורות וקוד מדויק — תמיד לקרוא מהשרת.

---

## 1 · מה זה

שירות סטרימינג בעברית: אתר, אפליקציית אנדרואיד/טלוויזיה, ~11,900 פריטי VOD
מגובי טלגרם, ~102 ערוצים חיים, לוח שידורים.

**הכל רץ על שרת אחד.** אין ענן, אין CDN, אין מסד נתונים חיצוני.

| | |
|---|---|
| שרת | `root@213.139.78.39` · Ubuntu 22.04 · 99GB דיסק |
| דומיין | `zovex.duckdns.org` (DuckDNS) · HTTPS מ-Let's Encrypt |
| כניסה | **סיסמה בלבד — לדוד אין מפתחות SSH.** אסור לכבות `PasswordAuthentication` |
| ריפואים | `davidggjg/zovex` · `davidggjg/zovex-android` |
| ענף עבודה | `claude/hls-relay-schema-port-ll8xiz` — **רק אליו דוחפים** |

---

## 2 · מה רץ בשרת

```
nginx  :443  ─┬─ /              →  קבצים סטטיים מ-/opt/zovex-site
              ├─ /epg/          →  /opt/zovex-bot/data/epg
              └─ כל השאר        →  proxy ל-127.0.0.1:8000

zovex-bot.service               →  /opt/zovex-bot/main.py  (uvicorn, פורט 8000)
epg טיימר systemd               →  מרענן לוח שידורים כל שעתיים (oneshot מבודד)
```

`zovex-bot` הוא **הכל**: הזרמת VOD מטלגרם, ממסר הערוצים החיים, ה-API,
פאנל הניהול, בוט ההעלאה, היסטוריית צפייה, משוב.

### מבנה תיקיות

```
/opt/zovex-bot/
├── main.py                 ← השירות כולו. ~6,200 שורות
├── .env                    ← ⚠️ מקום האמת היחיד להגדרות
├── venv/                   ← 101MB
├── stream_bots.txt         ← אסימוני הבוטים לבריכת ההזרמה (21 פעילים)
├── main.py.bak-*           ← גיבוי לכל פאץ' שהוחל (17 כרגע)
└── data/
    ├── content.json        ← ⚠️ הקטלוג. מקור האמת לתוכן
    ├── content_backups/    ← 30 גיבויים אחרונים, אוטומטי בכל שמירה
    ├── content_version.txt ← מונה לנעילה אופטימית
    ├── edge_cache/         ← ראש+זנב של קבצים. ⚠️ 16GB מול מגבלה של 3GB
    ├── saved_uploads/      ← העלאות מהאפליקציה. קבצים דלילים (sparse)
    ├── epg/                ← לוח שידורים, קובץ לכל ערוץ
    ├── sign_secret.txt     ← מפתח חתימת קישורי /stream
    └── *.session           ← קובצי Pyrogram

/opt/zovex-site/            ← האתר הבנוי. nginx מגיש מכאן
```

---

## 3 · איך משנים כל דבר

### 3.1 האתר

**הבנייה נעשית מחוץ לשרת. השרת רק מקבל ארכיון.**

```bash
# כאן:
cd /home/user/zovex
npm run build:vps          # ⚠️ לא "npm run build" — זה מגדיר base=/ ולא /zovex/
rm -f vps-bot/site.tgz && tar czf vps-bot/site.tgz -C dist .
git add vps-bot/site.tgz public/sitemap.xml && git commit && git push
```

```bash
# בשרת:
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/claude/hls-relay-schema-port-ll8xiz/vps-bot/site.tgz?$(date +%s)" -o /tmp/site.tgz \
  && find /opt/zovex-site -mindepth 1 -delete \
  && tar xzf /tmp/site.tgz -C /opt/zovex-site \
  && echo "נפרס: $(ls /opt/zovex-site/assets/index-*.js)"
```

**אין restart ל-nginx.** אחרי פריסה — Ctrl+Shift+R בדפדפן.

⚠️ **`vps-bot/site.tgz` הוא מה שבאמת מגיע לשרת.** קומיט של קוד מקור בלבד
לא משנה כלום לאף משתמש.

⚠️ `build:vps` מריץ גם `generate-sitemap.js` ו-`prerender-routes.js`, שמושכים
את הקטלוג החי ומייצרים 1,132 תיקיות מסלול. `public/sitemap.xml` משתנה בכל
בנייה — לקמט אותו יחד עם ה-tgz.

⚠️ **פריסה מוחקת את `/opt/zovex-site` לגמרי.** כל דבר שנכתב לשם מחוץ לבנייה
ייעלם — זה בדיוק מה שקרה ל-`epg.json` פעם, ראה `epg_serve_fix.sh`.

**אימות שהתיקון בבנדל:** שמות משתנים נעלמים במזעור. תבנה עם ובלי ותשווה
גדלים, או חפש קבועים ששורדים (`8e3`, `.001`).

### 3.2 השרת — main.py

**התבנית היחידה שעובדת: פאץ' שרק מוסיף בסוף הקובץ.** בלי עוגני regex, כי
הקובץ בשרת שונה מהריפו.

```python
TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "שם_ייחודי_מהתוספת"     # אידמפוטנטיות
NEEDED = ["api = FastAPI", "def check_hotlink", ...]   # אחרת מסרבים

src = TARGET.read_text(encoding="utf-8")
if DONE_MARK in src: return                  # כבר מוחל
if [n for n in NEEDED if n not in src]: _fail(...)
out = src.rstrip("\n") + "\n" + BLOCK
py_compile.compile(tmp, doraise=True)        # חייב לעבור לפני כתיבה
shutil.copy2(TARGET, f"{TARGET}.bak-<שם>-<תאריך>")
```

תמיד עם `--check` ו-`--undo`. דוגמאות טובות: `add_vodfix.py`,
`add_authkey_cache.py`, `add_replace_video.py`.

**לדרוס פונקציה קיימת:** להגדיר אותה שוב בסוף. פייתון מחפש שמות גלובליים
בזמן הקריאה, ולכן ההגדרה האחרונה מנצחת.
⚠️ **חובה לאמת את החתימה המדויקת ב-`NEEDED`** — הריפו מראה
`_make_media_session(dc_id)` והשרת מראה `(client, dc_id)`, ודריסה עם חתימה
שגויה שוברת כל קריאה.

**בדיקת NameError חובה.** קומפילציה לא מגלה אותה. אחרי החלה בארגז חול, פרוס
AST ואמת שכל שם גלובלי בבלוק החדש נפתר מול שמות המודול. ראה
`test_saved_video_meta.py`.

**התהליך מול דוד:**
```bash
cd /root && curl -fsSL -o X.py "https://raw.githubusercontent.com/davidggjg/zovex/claude/hls-relay-schema-port-ll8xiz/vps-bot/X.py?$(date +%s)" && python3 X.py --check
python3 X.py && systemctl restart zovex-bot && sleep 25 && systemctl is-active zovex-bot
```

### 3.3 לקרוא את הקוד האמיתי שבשרת

```bash
grep -n "שם_הפונקציה" /opt/zovex-bot/main.py
sed -n '1600,1700p' /opt/zovex-bot/main.py
```

**תמיד לבקש מדוד את הקטע לפני שכותבים פאץ' שנוגע בו.**

### 3.4 הגדרות

**`/opt/zovex-bot/.env` נטען אחרון ודורס drop-ins של systemd.** שעות בוזבזו
פעם על כוונון דרך `/etc/systemd/system/zovex-bot.service.d/` בלי שדבר נכנס
לתוקף.

```bash
curl -s http://127.0.0.1:8000/stream/tune     # מה *באמת* פעיל
```

הערכים הנוכחיים, וכל אחד מהם נבחר במדידה:
```
STREAM_PARALLEL_PARTS=4        # חלונות במקביל, כל אחד על בוט אחר
STREAM_MEDIA_CONNS=4           # חיבורים בתוך בוט. 8 נמדד גרוע פי 3
STREAM_MEDIA_BANDS_TIMEOUT=6   # היה 3 — חתך בוטים בריאים מוקדם מדי
STREAM_MEDIA_BANDS_PER_MB=3
STREAM_EDGE_HEAD=33554432      # 32MB ראש שמור בדיסק
STREAM_WINDOW_WALL=30          # מעבר לזה — הגוף נמסר קטוע במכוון
```

### 3.5 התוכן

`content.json` הוא מקור האמת. `save_content()` מגבה אוטומטית לפני כל דריסה
(30 גיבויים) ומעלה מונה גרסה לנעילה אופטימית.

**עריכה: דרך פאנל הניהול או `/panel/api`.** לא לערוך את הקובץ ידנית בזמן
שהשירות רץ.

### 3.6 אפליקציית אנדרואיד

`davidggjg/zovex-android`, אותו שם ענף. הבנייה ב-GitHub Actions. דוד מקבל
קישור מוכן ל-APK. גרסה מתפרסמת דרך `/app/version/set` ו-`/app/apk`.

---

## 4 · מסלולי ה-API

45 מסלולים ב-main.py. אלה שחשובים:

| מסלול | מה |
|---|---|
| `/stream/{chat}/{msg}` | **הזרמת VOD מטלגרם.** חתום ב-HMAC, תוקף 6 שעות |
| `/cast/{chat}/{msg}` | אותו זרם עם אודיו מומר ל-AAC. **בלי קפיצה בסרט** |
| `/hls-relay/{host}/{path}` | ממסר הערוצים החיים |
| `/content` · `/movies.json` | הקטלוג, עם קישורים חתומים טריים |
| `/panel` · `/panel/api` | ניהול. מוגן `PANEL_PASSWORD` |
| `/ping` | הזול ביותר — לא נוגע בטלגרם ולא בדיסק |
| `/stream/tune` | אילו פרמטרים באמת פעילים |
| `/speedtest/bots?mb=3` | מהירות כל בוט. **טורי — אסור לסכם!** |

**נוספו ולא חוברו לאתר:** `/fs/…` `/vh/…/index.m3u8` `/vodinfo/…`
(`add_vodfix.py`, ראה `HANDOFF.md` סעיף 5).

**חתימה:** `sign_stream_url()` מוסיף `?exp=&sig=`. ה-HMAC מכסה
`chat/msg/exp` **בלבד — לא את הדומיין**, ולכן מותר להפנות קישור חתום
ל-`127.0.0.1` לצורך מדידה.

---

## 5 · הסקריפטים שקיימים

### תשתית (הותקנו פעם, לא להריץ סתם)

| | |
|---|---|
| `site.sh` | פריסת אתר **מלאה** כולל שכתוב nginx. מושך מענף ישן — לעדכון תוכן השתמש ב-3.1 |
| `https.sh` | nginx + Let's Encrypt |
| `harden.sh` | חומת אש. **פותח SSH לפני ההפעלה** כדי לא לנעול בחוץ |
| `epg_deploy.sh` | שירות לוח שידורים + טיימר כל שעתיים |
| `epg_serve_fix.sh` | הוציא את הלוח מתיקיית האתר, אחרי שפריסות מחקו אותו |
| `epg_split_serve.sh` | קובץ לכל ערוץ במקום 1.77MB לכולם — פי 95 פחות |
| `fix_html_cache.sh` | "מסך לבן שאי אפשר לעבור" אחרי פריסה. מוודא `index.html` מול השרת |

### אבחון — **כולם קריאה בלבד**

| | |
|---|---|
| `whystuck.py --min N` | **הכי שימושי.** מודד עכשיו + מסווג יומן + tracebacks + סופר תקיעות |
| `idle_churn.py` | נפילות חיבור **מול תעבורה**. מסרב להסיק אם לא הייתה מנוחה |
| `loop_lag.py` | האם לולאת האירועים חסומה |
| `bench.py --runs 30 --label X` | **אחוז תקיעות**, לא מהירות |
| `stream_probe.py` | משחזר "נתקע באמצע", מושך בקצב של נגן |
| `capacity.py` | כמה צופים במקביל ומי נשבר ראשון |
| `concurrency_test.py` | עומק / גודל חלון / מקביליות |
| `test_live.sh` | אילו ערוצים באמת חיים. שלוש בדיקות, לא רק playlist תקין |
| `audio_scan.py` | קודק האודיו של פריטים בקטלוג |

### תיקונים שהוחלו (`fix_*.py` · `add_*.py`)

לכל אחד `--check` / `--undo` והסבר מלא ב-docstring. הוחלו: `band_window`,
`hls_stall`, `mid_stall`, `window_wall`, `pool_health` ×2, `feedback_bans`,
`hls_codec`, `saved_*`, `authkey_cache`.
**לא הורצו:** `fix_saved_workers.py`, `add_vodfix.py`, `add_replace_video.py`.

---

## 6 · שיטת העבודה

**דוד מדבר עברית ומריץ הכל בעצמו בשרת.** הוא ביקש מפורשות:
> *"תגידי לי לפי הסדר 1 2 3, ואל תביא לי סתם זרקי ואני אפילו לא יודע מה
> להריץ — תעשי את זה מובן מסודר."*

1. **פקודה אחת בכל פעם, ממוספרת, מוכנה להעתקה.**
2. **תגיד מראש מה כל תוצאה אפשרית תלמד.** גם "לא נמצא כלום" הוא ממצא.
3. **מדוד לפני ואחרי.** `bench.py` מזהיר בעצמו: אותה בדיקה נמדדה 9.65 MB/s
   ואז 0.39 MB/s בהפרש 39 דקות. **מדידה בודדת היא רעש.**
4. **תמיד מ-`127.0.0.1`.** מדידה מלקוח חיצוני מוגבלת ברוחב הפס של הלקוח.
   זו מלכודת ג' ב-`STREAMING_DIAGNOSIS.md`, ונפלתי בה פעמיים.
5. **קרא את הקוד שבשרת, לא שבריפו.**
6. **תגיד "טעיתי" ותמשיך.** בלי התנצלויות ארוכות.
7. **בדוק את הכלים שלך.** `bench.py` קרס ב-`NameError` בכל ריצה במשך ימים.
8. **אל תשאיר קוד שלא עושה כלום** בתירוץ שהוא לא מזיק.

### שלושה מסמכים, שלושה תפקידים

| | |
|---|---|
| `OPERATIONS.md` | **הקובץ הזה.** מה המערכת ואיך משנים אותה |
| `HANDOFF.md` | מה אנחנו באמצע, ומה כבר הופרך |
| `vps-bot/STREAMING_DIAGNOSIS.md` | מדידות ההזרמה מ-29/08. **כל שורה מגובה במדידה** |

---

## 7 · תקלות מוכרות ומה עושים

| תסמין | ראשית |
|---|---|
| מסך לבן אחרי פריסה | `fix_html_cache.sh`. הדפדפן מחזיק `index.html` ישן |
| לוח שידורים ריק | פריסה מחקה אותו. `epg_serve_fix.sh` |
| ערוץ עובד ב-VLC ולא באתר | קודק שאינו H.264. `fix_hls_codec.py` ממיר רק את מי שצריך |
| סרט בלי קול | אודיו `ec-3`/`ac-3`. `audio_scan.py` מזהה |
| סרט נתקע | `whystuck.py --min 10` **בזמן התקיעה** |
| השירות לא עולה | `journalctl -u zovex-bot -n 50`. כל פאץ' עם `--undo` |
| דיסק מתמלא | `edge_cache` (16GB!), `syslog` (כפילות של journald), core dumps |

**נסיגה מכל פאץ':**
```bash
cd /root && python3 <שם>.py --undo && systemctl restart zovex-bot
```

---

## 8 · מגבלות שאסור לחצות

המערכת מפיצה סרטים וערוצים ברובם ללא רישיון.

- **לא לחזק אנונימיות** ולא להסתיר זהות מרשויות או מבעלי זכויות.
- **לא לחלץ זרמים מרותי תשלום** של שירותים אחרים, **ולא למפות איפה הם יושבים.**
- **לא להשתמש במוזיקה או בפוסטרים מוגנים** בחומרי שיווק.
- **אין לדוד מפתחות SSH** — אסור לכבות אימות בסיסמה.
- **לא לדחוף לענף אחר** מ-`claude/hls-relay-schema-port-ll8xiz`.
- כתובת המייל שלו משמשת **רק** לייחוס קומיטים.
- סריקת ערוצי IPTV אושרה מפורשות על ידי בעל הספק.
